import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import threading
import unittest
from unittest.mock import patch

import numpy as np

from common.robot import dm05_task2_client
from common.robot.dm05_task2_client import (
    ActionGenerationBuffer,
    clamp_grippers,
    build_request_from_jpegs,
    limit_action_step,
    validate_response,
)


class _LoopbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"dm05-loopback-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class LoopbackTransportTest(unittest.TestCase):
    def test_loopback_session_ignores_broken_shell_proxy(self):
        """Catches regressions that route 127.0.0.1 inference through port 7898."""
        factory = getattr(dm05_task2_client, "create_loopback_session", None)
        self.assertIsNotNone(factory, "DM0.5 client lacks a loopback-only HTTP session")

        server = HTTPServer(("127.0.0.1", 0), _LoopbackHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = "http://127.0.0.1:%d/health" % server.server_port
        try:
            with patch.dict(
                os.environ,
                {
                    "http_proxy": "http://127.0.0.1:1",
                    "https_proxy": "http://127.0.0.1:1",
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1",
                    "NO_PROXY": "",
                    "no_proxy": "",
                },
                clear=False,
            ):
                response = factory().get(endpoint, timeout=2)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "dm05-loopback-ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class RequestContractTest(unittest.TestCase):
    def test_builds_verified_three_camera_14d_aloha_request(self):
        payload = build_request_from_jpegs(
            [b"head", b"left", b"right"],
            np.arange(14, dtype=np.float32),
            "Open the pot lid, put the object into the pot, then close the lid.",
            seed=42,
        )
        observation = payload["observation"]
        self.assertEqual(list(observation["images"]), ["1", "2", "3"])
        self.assertEqual(base64.b64decode(observation["images"]["1"]), b"head")
        self.assertEqual(len(observation["state"]), 14)
        self.assertEqual(observation["robot_type"], "Aloha")
        self.assertEqual(payload["sampling"], {"num_steps": 10, "seed": 42})

    def test_rejects_bad_camera_or_state_contract(self):
        with self.assertRaisesRegex(ValueError, "three JPEG"):
            build_request_from_jpegs([b"one"], [0.0] * 14, "task", seed=42)
        with self.assertRaisesRegex(ValueError, "14D"):
            build_request_from_jpegs([b"1", b"2", b"3"], [0.0] * 13, "task", seed=42)


class ResponseContractTest(unittest.TestCase):
    def test_accepts_only_finite_50_by_14_actions(self):
        actions = validate_response({"actions": np.zeros((50, 14)).tolist()})
        self.assertEqual(actions.shape, (50, 14))
        with self.assertRaisesRegex(ValueError, "shape"):
            validate_response({"actions": np.zeros((49, 14)).tolist()})
        bad = np.zeros((50, 14))
        bad[1, 2] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_response({"actions": bad.tolist()})

    def test_step_limiter_matches_existing_pi05_safety_contract(self):
        previous = np.zeros(14)
        wanted = np.ones(14)
        limited = limit_action_step(wanted, previous, [0.01] * 6 + [0.2])
        np.testing.assert_allclose(limited[:6], 0.01)
        self.assertAlmostEqual(limited[6], 0.2)
        np.testing.assert_allclose(limited[7:13], 0.01)
        self.assertAlmostEqual(limited[13], 0.2)

    def test_clamps_both_grippers_to_verified_cobot_physical_range(self):
        action = np.zeros(14)
        action[6] = -0.2
        action[13] = 0.4
        bounded = clamp_grippers(action, minimum=0.0, maximum=0.078)
        self.assertEqual(bounded[6], 0.0)
        self.assertEqual(bounded[13], 0.078)
        np.testing.assert_allclose(bounded[[0, 1, 7, 8]], 0.0)


class PauseGenerationTest(unittest.TestCase):
    def test_prearm_resume_stays_paused_until_operator_arms(self):
        queue = ActionGenerationBuffer()

        prearm_generation = queue.set_paused(False)
        self.assertIsNone(queue.capture_generation())
        self.assertFalse(queue.is_armed())

        armed_generation = queue.arm()
        self.assertNotEqual(armed_generation, prearm_generation)
        self.assertTrue(queue.is_armed())
        self.assertIsNone(queue.capture_generation())

        running_generation = queue.set_paused(False)
        self.assertEqual(queue.capture_generation(), running_generation)

    def test_takeover_discards_old_http_result_and_requires_fresh_replan(self):
        queue = ActionGenerationBuffer()
        self.assertIsNone(queue.capture_generation())
        queue.arm()
        running_generation = queue.set_paused(False)
        self.assertEqual(queue.capture_generation(), running_generation)

        queue.set_paused(True)
        stale_actions = np.ones((50, 14), dtype=np.float32)
        self.assertFalse(queue.accept(running_generation, stale_actions, 25))
        self.assertIsNone(queue.pop(running_generation))

        fresh_generation = queue.set_paused(False)
        self.assertNotEqual(fresh_generation, running_generation)
        self.assertTrue(queue.accept(fresh_generation, stale_actions, 25))
        self.assertTrue(queue.is_ready())
        self.assertEqual(queue.pop(fresh_generation).shape, (14,))

        queue.set_paused(True)
        self.assertFalse(queue.is_ready())


if __name__ == "__main__":
    unittest.main()
