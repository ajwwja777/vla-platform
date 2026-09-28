from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "interface_task2_teach_rtc_live.sh"
RUNNER = ROOT / "run_checkpoint_task2.sh"
START_SERVER = ROOT / "start_local_server.sh"
STOP_SERVER = ROOT / "stop_local_server.sh"
CONFIG_PROBE = ROOT / "server" / "config_probe.py"
SERVER_COMPAT = ROOT / "server" / "serve_policy_compat.py"


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class Task2WrapperTest(unittest.TestCase):
    def test_operator_arm_precedes_resume_ready_and_cleanup_pause(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            event_log = temp / "events.log"
            write_executable(
                fake_bin / "rosservice",
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -eu
                    if [[ "$1" == info ]]; then
                      if [[ "$2" == /task2/teach_handover/reset_fault ]]; then exit 0; fi
                      [[ -f "$G05_TEST_POLICY_READY" ]] && exit 0 || exit 1
                    fi
                    if [[ "$1" != call ]]; then exit 2; fi
                    case "$2" in
                      /task2/policy/arm) echo arm >>"$G05_TEST_EVENT_LOG" ;;
                      /task2/policy/set_paused)
                        if [[ "${3:-}" == false ]]; then echo resume >>"$G05_TEST_EVENT_LOG"; else echo pause >>"$G05_TEST_EVENT_LOG"; fi ;;
                      /task2/policy/chunk_ready) echo ready >>"$G05_TEST_EVENT_LOG" ;;
                    esac
                    echo 'success: True'
                    echo 'message: "ok"'
                    """
                ),
            )
            write_executable(
                fake_bin / "rostopic",
                "#!/usr/bin/env bash\nif [[ \"$1\" == info ]]; then exit 0; fi\necho 'data: \"policy\"'\n",
            )
            write_executable(fake_bin / "ip", "#!/usr/bin/env bash\necho 'state UP ERROR-ACTIVE'\n")
            runner = temp / "runner.sh"
            write_executable(runner, "#!/usr/bin/env bash\ntouch \"$G05_TEST_POLICY_READY\"\nsleep 3\n")
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": str(fake_bin) + os.pathsep + environment["PATH"],
                    "G05_TASK2_RUNNER": str(runner),
                    "G05_TASK2_SERVICE_TIMEOUT": "5",
                    "G05_HANDOVER_RELEASE_TIMEOUT": "5",
                    "G05_FIRST_CHUNK_TIMEOUT": "5",
                    "G05_TEST_EVENT_LOG": str(event_log),
                    "G05_TEST_POLICY_READY": str(temp / "policy.ready"),
                }
            )

            result = subprocess.run(
                ["script", "-q", "-e", "-c", f"{shlex.quote(str(WRAPPER))} 4000", "/dev/null"],
                input="\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            events = event_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(events[:3], ["arm", "resume", "ready"])
            self.assertEqual(events[-1], "pause")
            self.assertIn("首个模型输出已通过", result.stdout)

    def test_wrapper_never_probes_task5(self):
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertNotIn("8015", source)
        self.assertNotIn("Task5", source)
        self.assertNotIn("curl", source)

    def test_direct_runner_requires_gated_wrapper_ack(self):
        result = subprocess.run(
            ["bash", str(RUNNER), "4000"], text=True, capture_output=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gated Task2 wrapper", result.stderr)

    def test_server_start_is_local_identity_gated_and_never_kills_other_processes(self):
        source = START_SERVER.read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", source)
        self.assertIn("preflight.py", source)
        self.assertIn("config_probe.py", source)
        self.assertIn("serve_policy_compat.py", source)
        self.assertIn("G05_MIN_FREE_GPU_MIB", source)
        self.assertIn('XDG_CACHE_HOME="${RUNTIME}/cache/xdg"', source)
        self.assertIn('TRITON_CACHE_DIR="${RUNTIME}/cache/triton"', source)
        self.assertIn('TMPDIR="${RUNTIME}/cache/tmp"', source)
        self.assertIn('export G05_FIXED_ACTIONCODEC="${STEP_ROOT}/action_tokenizer.pt"', source)
        self.assertIn('export COBOT_LEGACY40_DATASET="${DATASET_ROOT}"', source)
        self.assertIn('model.model_arch.discrete_action=false', source)
        self.assertIn('G05_COBOT_DATASET_ROOT:-/media/agilex/Getea1/jiaan/data/datasets/in_the_pot/lerobot/wja/cobot_in_the_pot_40episodes', source)
        self.assertIn('git -C "${UPSTREAM}" rev-parse HEAD', source)
        self.assertIn('git -C "${UPSTREAM}" status --short', source)
        self.assertNotIn("pkill", source)
        self.assertNotIn("kill -9", source)

        stop_source = STOP_SERVER.read_text(encoding="utf-8")
        self.assertIn("serve_policy_compat.py", stop_source)
        self.assertNotIn("kill -9", stop_source)

    def test_config_loaders_enter_the_fixed_upstream_root_for_relative_oc_load(self):
        self.assertIn("os.chdir(args.upstream)", CONFIG_PROBE.read_text(encoding="utf-8"))
        self.assertIn("os.chdir(upstream)", SERVER_COMPAT.read_text(encoding="utf-8"))

    def test_wrapper_refuses_to_replace_an_existing_policy_client(self):
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("another Task2 policy service", source)


if __name__ == "__main__":
    unittest.main()
