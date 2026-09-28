from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalServerWrapperTest(unittest.TestCase):
    def test_runner_owns_local_server_and_hides_endpoint_from_operator(self):
        runner = (ROOT / "run_checkpoint_task2.sh").read_text(encoding="utf-8")
        self.assertIn("start_local_server.sh", runner)
        self.assertIn("http://127.0.0.1:7891/v1/infer", runner)
        self.assertNotIn("DM05_ENDPOINT", runner)

    def test_start_and_stop_are_exact_identity_gated(self):
        start = (ROOT / "start_local_server.sh").read_text(encoding="utf-8")
        stop = (ROOT / "stop_local_server.sh").read_text(encoding="utf-8")
        self.assertIn("/dev/sda2", start)
        self.assertIn("local_preflight.py", start)
        self.assertIn("DM05_MIN_FREE_GPU_MIB", start)
        self.assertIn("127.0.0.1", start)
        self.assertIn("pid=${pid}", start)
        self.assertIn("--model-config.vision-attn-implementation sdpa", start)
        self.assertIn("--model-config.no-liger-kernel", start)
        self.assertIn("PYTHONPYCACHEPREFIX", start)
        self.assertIn("HF_HOME", start)
        self.assertIn("TMPDIR", start)
        self.assertNotIn("pkill", start)
        self.assertNotIn("kill -9", start)
        self.assertIn("dm05_cobot_sft.py", stop)
        self.assertNotIn("pkill", stop)
        self.assertNotIn("kill -9", stop)

    def test_project_server_binds_loopback_only(self):
        server = (ROOT / "server" / "dm05_local_server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('host="127.0.0.1"', server)
        self.assertNotIn('host="0.0.0.0"', server)

    def test_shadow_uses_fixed_fixture_without_ros_or_publishers(self):
        shadow = (ROOT / "run_shadow.sh").read_text(encoding="utf-8")
        self.assertIn("common/remote_client.py", shadow)
        self.assertIn("--send", shadow)
        self.assertIn("publisher_used", shadow)
        self.assertNotIn("roslaunch", shadow)
        self.assertNotIn("rospy", shadow)
        self.assertNotIn("rostopic pub", shadow)


if __name__ == "__main__":
    unittest.main()
