from __future__ import annotations

import unittest

import numpy as np

from common.g05_contract import (
    assert_complete_action_response,
    ACTION_PARTS,
    CAMERA_KEYS,
    build_raw_observation,
    flatten_action_response,
    validate_metadata,
)
from common.g05_wire import packb, unpackb
from common.g05_ws_client import G05WebSocketSession


class G05WireContractTest(unittest.TestCase):
    def test_msgpack_numpy_round_trip_matches_official_wire_shape(self):
        payload = {
            "images": {"cam_high": np.arange(18, dtype=np.uint8).reshape(3, 2, 3)},
            "state": {"left_arm": np.arange(6, dtype=np.float32)},
        }

        decoded = unpackb(packb(payload))

        np.testing.assert_array_equal(decoded["images"]["cam_high"], payload["images"]["cam_high"])
        np.testing.assert_array_equal(decoded["state"]["left_arm"], payload["state"]["left_arm"])

    def test_rejects_object_arrays(self):
        with self.assertRaisesRegex(ValueError, "Unsupported dtype"):
            packb(np.array([object()], dtype=object))


class G05ObservationContractTest(unittest.TestCase):
    def test_builds_exact_three_camera_and_split_legacy14_request(self):
        images = [np.full((480, 640, 3), value, dtype=np.uint8) for value in (1, 2, 3)]
        state = np.arange(14, dtype=np.float32)

        request = build_raw_observation(images, state, "put the object in the pot", frequency=30)

        self.assertEqual(tuple(request["images"]), CAMERA_KEYS)
        for index, key in enumerate(CAMERA_KEYS, start=1):
            self.assertEqual(request["images"][key].shape, (3, 480, 640))
            self.assertEqual(int(request["images"][key][0, 0, 0]), index)
        self.assertEqual(tuple(request["state"]), ACTION_PARTS)
        np.testing.assert_array_equal(request["state"]["left_arm"], state[0:6])
        np.testing.assert_array_equal(request["state"]["left_gripper"], state[6:7])
        np.testing.assert_array_equal(request["state"]["right_arm"], state[7:13])
        np.testing.assert_array_equal(request["state"]["right_gripper"], state[13:14])
        self.assertEqual(request["embodiment_type"], "cobot_legacy14")
        self.assertEqual(request["frequency"], 30)

    def test_rejects_bad_camera_state_or_instruction(self):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "three RGB"):
            build_raw_observation([image, image], np.zeros(14), "task", frequency=30)
        with self.assertRaisesRegex(ValueError, "14D"):
            build_raw_observation([image] * 3, np.zeros(13), "task", frequency=30)
        with self.assertRaisesRegex(ValueError, "instruction"):
            build_raw_observation([image] * 3, np.zeros(14), "", frequency=30)


class G05ResponseContractTest(unittest.TestCase):
    def test_offline_acceptance_requires_all_physical_action_parts(self):
        complete = {key: np.zeros(6 if "arm" in key else 1) for key in ACTION_PARTS}
        self.assertEqual(assert_complete_action_response({"action": complete}), ACTION_PARTS)
        incomplete = dict(complete)
        incomplete.pop("right_gripper")
        with self.assertRaisesRegex(ValueError, "missing physical action parts"):
            assert_complete_action_response({"action": incomplete})

    def test_flattens_exact_four_part_absolute_action_to_legacy14(self):
        response = {
            "action": {
                "left_arm": np.arange(6, dtype=np.float32),
                "left_gripper": np.array([6], dtype=np.float32),
                "right_arm": np.arange(7, 13, dtype=np.float32),
                "right_gripper": np.array([13], dtype=np.float32),
            },
            "need_obs": False,
        }

        action = flatten_action_response(response, fallback_state=np.full(14, -1.0))

        np.testing.assert_array_equal(action, np.arange(14, dtype=np.float32))

    def test_holds_current_part_when_official_ar_head_omits_it(self):
        fallback = np.arange(14, dtype=np.float32)
        response = {
            "action": {"left_arm": np.full(6, 2.0, dtype=np.float32)},
            "need_obs": True,
        }

        action = flatten_action_response(response, fallback_state=fallback)

        np.testing.assert_array_equal(action[:6], 2.0)
        np.testing.assert_array_equal(action[6:], fallback[6:])

    def test_rejects_error_unknown_shape_or_nonfinite_response(self):
        fallback = np.zeros(14, dtype=np.float32)
        with self.assertRaisesRegex(RuntimeError, "server error"):
            flatten_action_response({"error": {"code": 500, "message": "bad"}}, fallback)
        with self.assertRaisesRegex(ValueError, "unknown"):
            flatten_action_response({"action": {"lower_body": np.zeros(7)}}, fallback)
        with self.assertRaisesRegex(ValueError, "left_arm"):
            flatten_action_response({"action": {"left_arm": np.zeros(7)}}, fallback)
        with self.assertRaisesRegex(ValueError, "finite"):
            flatten_action_response({"action": {"left_gripper": np.array([np.nan])}}, fallback)

    def test_metadata_requires_expected_action_steps(self):
        self.assertEqual(validate_metadata({"action_steps": 16}, expected_action_steps=16), 16)
        with self.assertRaisesRegex(ValueError, "action_steps"):
            validate_metadata({"action_steps": 1}, expected_action_steps=16)


class _FakeSocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    def recv(self):
        return self.frames.pop(0)

    def send_binary(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed = True


class G05WebSocketSessionTest(unittest.TestCase):
    def test_handshake_infer_and_reset_follow_official_protocol(self):
        action = {
            "left_arm": np.zeros(6, dtype=np.float32),
            "left_gripper": np.zeros(1, dtype=np.float32),
            "right_arm": np.zeros(6, dtype=np.float32),
            "right_gripper": np.zeros(1, dtype=np.float32),
        }
        socket = _FakeSocket(
            [
                packb({"action_steps": 16}),
                packb({"action": action, "need_obs": False}),
                packb({"__reset__": True}),
            ]
        )
        factory_calls = []

        def factory(endpoint, **kwargs):
            factory_calls.append((endpoint, kwargs))
            return socket

        session = G05WebSocketSession(
            "ws://127.0.0.1:8180", expected_action_steps=16, timeout_s=2.0, socket_factory=factory
        )

        metadata = session.connect()
        response = session.infer({"images": {}, "state": {}, "task": "x"})
        session.reset()
        session.close()

        self.assertEqual(metadata["action_steps"], 16)
        self.assertFalse(response["need_obs"])
        self.assertEqual(unpackb(socket.sent[0])["task"], "x")
        self.assertEqual(unpackb(socket.sent[1]), {"__reset__": True})
        self.assertTrue(socket.closed)
        self.assertEqual(factory_calls[0][0], "ws://127.0.0.1:8180")
        self.assertEqual(factory_calls[0][1]["http_no_proxy"], ["127.0.0.1", "localhost"])

    def test_rejects_non_websocket_endpoint(self):
        with self.assertRaisesRegex(ValueError, "WebSocket"):
            G05WebSocketSession("http://127.0.0.1:8180", expected_action_steps=16)


if __name__ == "__main__":
    unittest.main()
