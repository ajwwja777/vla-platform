import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "interface_task2_teach_rtc_live.sh"


def write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


class Task2WrapperTest(unittest.TestCase):
    def test_operator_arm_precedes_resume_and_first_chunk_readiness(self):
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
                    if [[ "$1" == info ]]; then exit 0; fi
                    if [[ "$1" != call ]]; then exit 2; fi
                    case "$2" in
                      /task2/policy/arm) echo arm >>"$DM05_TEST_EVENT_LOG" ;;
                      /task2/policy/set_paused)
                        if [[ "${3:-}" == false ]]; then echo resume >>"$DM05_TEST_EVENT_LOG"; else echo pause >>"$DM05_TEST_EVENT_LOG"; fi ;;
                      /task2/policy/chunk_ready) echo ready >>"$DM05_TEST_EVENT_LOG" ;;
                    esac
                    echo 'success: True'
                    echo 'message: "ok"'
                    """
                ),
            )
            write_executable(
                fake_bin / "rostopic",
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -eu
                    if [[ "$1" == info ]]; then exit 0; fi
                    echo 'data: "policy"'
                    """
                ),
            )
            write_executable(
                fake_bin / "ip",
                "#!/usr/bin/env bash\necho 'state UP ERROR-ACTIVE'\n",
            )
            runner = temp / "runner.sh"
            write_executable(runner, "#!/usr/bin/env bash\nsleep 1\n")

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": str(fake_bin) + os.pathsep + environment["PATH"],
                    "DM05_TASK2_RUNNER": str(runner),
                    "DM05_TASK2_SERVICE_TIMEOUT": "5",
                    "DM05_HANDOVER_RELEASE_TIMEOUT": "5",
                    "DM05_FIRST_CHUNK_TIMEOUT": "5",
                    "DM05_TEST_EVENT_LOG": str(event_log),
                }
            )
            command = " ".join(
                [shlex.quote(str(WRAPPER)), "4000"]
            )
            result = subprocess.run(
                ["script", "-q", "-e", "-c", command, "/dev/null"],
                input="\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            events = event_log.read_text().splitlines()
            self.assertGreaterEqual(len(events), 4, events)
            self.assertEqual(events[:3], ["arm", "resume", "ready"])
            self.assertEqual(events[-1], "pause")
            self.assertIn("首个模型输出已通过", result.stdout)


if __name__ == "__main__":
    unittest.main()
