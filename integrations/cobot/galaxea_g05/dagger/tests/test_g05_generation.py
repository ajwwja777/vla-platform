from __future__ import annotations

import unittest

import numpy as np

from common.robot.g05_task2_client import (
    ActionGenerationState,
    create_policy_publishers,
    limit_action_step,
)


class ActionGenerationStateTest(unittest.TestCase):
    def test_prearm_resume_cannot_start_policy(self):
        state = ActionGenerationState()

        prearm = state.set_paused(False)
        self.assertFalse(state.is_armed())
        self.assertIsNone(state.capture_generation())

        armed = state.arm()
        self.assertNotEqual(armed, prearm)
        self.assertIsNone(state.capture_generation())

        running = state.set_paused(False)
        self.assertEqual(state.capture_generation(), running)

    def test_takeover_invalidates_inflight_response_and_readiness(self):
        state = ActionGenerationState()
        state.arm()
        running = state.set_paused(False)

        state.mark_ready(running)
        self.assertTrue(state.is_ready())

        state.set_paused(True)
        self.assertFalse(state.is_current(running))
        self.assertFalse(state.is_ready())

        fresh = state.set_paused(False)
        self.assertNotEqual(fresh, running)
        self.assertFalse(state.is_ready())
        state.mark_ready(fresh)
        self.assertTrue(state.is_ready())

    def test_step_limiter_preserves_pi05_joint_safety_contract(self):
        wanted = np.ones(14)
        limited = limit_action_step(wanted, np.zeros(14), [0.01] * 6 + [0.2])
        np.testing.assert_allclose(limited[:6], 0.01)
        self.assertAlmostEqual(limited[6], 0.2)
        np.testing.assert_allclose(limited[7:13], 0.01)
        self.assertAlmostEqual(limited[13], 0.2)

    def test_shadow_mode_constructs_zero_command_publishers(self):
        calls = []

        class FakeRos:
            @staticmethod
            def Publisher(*args, **kwargs):
                calls.append((args, kwargs))
                return object()

        self.assertEqual(create_policy_publishers(FakeRos, object, shadow=True), (None, None))
        self.assertEqual(calls, [])
        left, right = create_policy_publishers(FakeRos, object, shadow=False)
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
