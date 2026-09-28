#!/usr/bin/env python3
"""Install the Task5 DAgger inference config without replacing existing configs."""

from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile


CONFIG_NAME = "pi05_jiaan_task5_in_the_pot_dagger_round001"
BEGIN = "    # BEGIN JIAAN TASK5 PI05 DAGGER ROUND001\n"
END = "    # END JIAAN TASK5 PI05 DAGGER ROUND001\n"
ANCHOR = "    #\n    # Fine-tuning DROID configs.\n"
BLOCK = """    # BEGIN JIAAN TASK5 PI05 DAGGER ROUND001
    TrainConfig(
        name="pi05_jiaan_task5_in_the_pot_dagger_round001",
        model=pi0_config.Pi0Config(pi05=True),
        data=LeRobotAlohaDataConfig(
            repo_id="jiaan/task5_cobot_in_the_pot",
            assets=AssetsConfig(asset_id="task5_cobot_in_the_pot_round_001"),
            default_prompt="Open the pot lid, put the object into the pot, then close the lid.",
            repack_transforms=_transforms.Group(
                inputs=[
                    _transforms.RepackTransform(
                        {
                            "images": {
                                "cam_high": "observation.images.cam_high",
                                "cam_left_wrist": "observation.images.cam_left_wrist",
                                "cam_right_wrist": "observation.images.cam_right_wrist",
                            },
                            "state": "observation.state",
                            "actions": "action",
                        }
                    )
                ]
            ),
        ),
    ),
    # END JIAAN TASK5 PI05 DAGGER ROUND001
"""


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(path.stat().st_mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def install(config_path: Path) -> int:
    if not config_path.is_file() or config_path.is_symlink():
        return fail(f"OpenPI config is missing or unsafe: {config_path}")

    source = config_path.read_text(encoding="utf-8")
    if BEGIN in source or END in source:
        if source.count(BEGIN) == 1 and source.count(END) == 1 and BLOCK in source:
            print(f"{CONFIG_NAME} is already installed in {config_path}")
            return 0
        return fail("managed WJA configuration markers are incomplete or modified")

    if CONFIG_NAME in source:
        return fail(
            "refusing to replace an unmanaged configuration with the same name"
        )
    if source.count(ANCHOR) != 1:
        return fail("could not find one unambiguous OpenPI configuration anchor")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = config_path.with_name(
        f"{config_path.name}.jiaan-task5-backup-{timestamp}"
    )
    if backup.exists():
        return fail(f"backup path already exists: {backup}")
    shutil.copy2(config_path, backup)

    installed = source.replace(ANCHOR, BLOCK + ANCHOR, 1)
    try:
        compile(installed, str(config_path), "exec")
        atomic_write(config_path, installed)
    except BaseException:
        if config_path.read_text(encoding="utf-8") != source:
            atomic_write(config_path, source)
        raise

    print(f"Installed {CONFIG_NAME} in {config_path}")
    print(f"Backup: {backup}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", type=Path)
    args = parser.parse_args()
    return install(args.config_path)


if __name__ == "__main__":
    raise SystemExit(main())
