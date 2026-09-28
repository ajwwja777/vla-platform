from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "interface_task2_teach_rtc_live.sh"
RUNNER = ROOT / "run_checkpoint.sh"


def test_runner_pins_validated_task2_ik_and_safe_prefix_limits():
    """Catches deployment silently reverting to the all-or-nothing IK gate."""

    script = RUNNER.read_text(encoding="utf-8")
    assert "--ik-position-tolerance-m 0.003" in script
    assert "--ik-rotation-tolerance-rad 0.020" in script
    assert "--ik-max-target-joint-step-rad 0.12" in script
    assert "--min-safe-prefix-actions 20" in script


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _fake_commands(tmp_path: Path, *, coordinator_ok: bool = True) -> Path:
    binary = tmp_path / "bin"
    binary.mkdir()
    _write_executable(
        binary / "rosservice",
        (
            'if [[ "$1" == info ]]; then '
            + ("exit 0; " if coordinator_ok else "exit 1; ")
            + 'fi\nif [[ "$1" == call ]]; then echo "success: True"; exit 0; fi\nexit 1\n'
        ),
    )
    _write_executable(
        binary / "rostopic",
        'if [[ "$1" == info ]]; then exit 0; fi\n'
        'if [[ "$1" == echo ]]; then echo "data: \\"policy\\""; exit 0; fi\n'
        "exit 1\n",
    )
    _write_executable(
        binary / "ip",
        'if [[ "$1" == -details ]]; then '
        'echo "can state ERROR-ACTIVE restart-ms 100"; exit 0; fi\n'
        "exit 1\n",
    )
    return binary


def test_direct_task2_runner_requires_gated_wrapper_ack():
    """Catches bypassing the operator-facing preflight and initial pause."""

    result = subprocess.run(
        ["bash", str(RUNNER), "4000", "task2"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "gated Task2 wrapper" in result.stderr


def test_wrapper_fails_before_runner_when_coordinator_is_missing(tmp_path):
    """Catches model startup without the single-writer handover coordinator."""

    binary = _fake_commands(tmp_path, coordinator_ok=False)
    capture = tmp_path / "runner.args"
    fake_runner = tmp_path / "runner.sh"
    _write_executable(fake_runner, f'echo "$*" > "{capture}"\n')
    environment = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "XR1_TASK2_RUNNER": str(fake_runner),
    }

    result = subprocess.run(
        ["bash", str(WRAPPER), "4000"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "coordinator" in result.stderr.lower()
    assert not capture.exists()


def test_wrapper_runs_without_task5_service_or_recording(tmp_path):
    """Catches coupling ordinary Task2 deployment to the optional Task5 recorder."""

    assert shutil.which("script"), "util-linux script is required for the TTY test"
    binary = _fake_commands(tmp_path)
    task5_probe = tmp_path / "task5.probed"
    _write_executable(
        binary / "curl",
        f'touch "{task5_probe}"\n'
        'echo "Task5 is intentionally unavailable" >&2\n'
        "exit 7\n",
    )
    capture = tmp_path / "runner.args"
    fake_runner = tmp_path / "runner.sh"
    _write_executable(
        fake_runner,
        f'echo "$*" > "{capture}"\ntrap "exit 0" TERM INT\nsleep 0.2\n',
    )
    environment = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "XR1_TASK2_RUNNER": str(fake_runner),
    }

    command = f"bash {WRAPPER} 4000"
    result = subprocess.run(
        ["script", "-qfec", command, "/dev/null"],
        env=environment,
        input="\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert capture.read_text(encoding="utf-8").strip() == "4000 task2"
    assert not task5_probe.exists()


def test_wrapper_runs_only_task2_mode_after_preflight_and_operator_enter(tmp_path):
    """Catches a model wrapper changing the historical one-command operator contract."""

    assert shutil.which("script"), "util-linux script is required for the TTY test"
    binary = _fake_commands(tmp_path)
    capture = tmp_path / "runner.args"
    fake_runner = tmp_path / "runner.sh"
    _write_executable(
        fake_runner,
        f'echo "$*" > "{capture}"\ntrap "exit 0" TERM INT\nsleep 0.2\n',
    )
    environment = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "XR1_TASK2_RUNNER": str(fake_runner),
    }

    command = f"bash {WRAPPER} 4000"
    result = subprocess.run(
        ["script", "-qfec", command, "/dev/null"],
        env=environment,
        input="\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert capture.read_text(encoding="utf-8").strip() == "4000 task2"
    assert "推理已就绪，当前处于暂停" in result.stdout


def test_wrapper_arms_only_after_operator_enter_and_before_resume(tmp_path):
    """Catches a pre-Enter teach release being treated as first policy start."""

    assert shutil.which("script"), "util-linux script is required for the TTY test"
    binary = _fake_commands(tmp_path)
    calls = tmp_path / "rosservice.calls"
    _write_executable(
        binary / "rosservice",
        f'if [[ "$1" == info ]]; then exit 0; fi\n'
        f'if [[ "$1" == call ]]; then echo "$2 ${{3:-}}" >> "{calls}"; echo "success: True"; exit 0; fi\n'
        'exit 1\n',
    )
    fake_runner = tmp_path / "runner.sh"
    _write_executable(fake_runner, "trap 'exit 0' TERM INT\nsleep 0.2\n")
    environment = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "XR1_TASK2_RUNNER": str(fake_runner),
    }

    result = subprocess.run(
        ["script", "-qfec", f"bash {WRAPPER} 4000", "/dev/null"],
        env=environment,
        input="\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    service_calls = calls.read_text(encoding="utf-8").splitlines()
    arm_index = service_calls.index("/task2/policy/arm ")
    resume_index = service_calls.index("/task2/policy/set_paused false")
    assert arm_index < resume_index


def test_wrapper_fails_if_client_exits_before_first_chunk_is_ready(tmp_path):
    """Catches a resume acknowledgement being mistaken for successful inference."""

    assert shutil.which("script"), "util-linux script is required for the TTY test"
    binary = _fake_commands(tmp_path)
    _write_executable(
        binary / "rosservice",
        'if [[ "$1" == info ]]; then exit 0; fi\n'
        'if [[ "$1" == call && "$2" == "/task2/policy/chunk_ready" ]]; then\n'
        '  echo "success: False"; exit 0\n'
        'fi\n'
        'if [[ "$1" == call ]]; then echo "success: True"; exit 0; fi\n'
        'exit 1\n',
    )
    fake_runner = tmp_path / "runner.sh"
    _write_executable(fake_runner, "sleep 0.2\nexit 23\n")
    environment = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "XR1_TASK2_RUNNER": str(fake_runner),
        "XR1_TASK2_FIRST_CHUNK_TIMEOUT": "5",
    }

    result = subprocess.run(
        ["script", "-qfec", f"bash {WRAPPER} 4000", "/dev/null"],
        env=environment,
        input="\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "exited before producing the first Task2 chunk" in result.stdout
    assert "XR-1 推理已开始" not in result.stdout
