"""Publisher-free local FluxVLA PI0.5 RTC inference server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import time
from typing import Any

import numpy as np

from .wire import decode_message, encode_message


CAMERA_KEYS = ("cam_high", "cam_left_wrist", "cam_right_wrist")


def initialize_private_inference_dataset(
    dataset_cls: type, dataset_cfg: dict[str, Any], transform_builder: Any
) -> Any:
    """Initialize pinned upstream inference dataset without global path injection.

    At the pinned FluxVLA revision, ``PrivateInferenceDataset.__init__`` adds
    its dataset-level ``model_path`` to every transform.  Non-tokenizer
    transforms such as ``JointSignTransform`` do not accept that keyword.
    The Cobot overlay already places the verified base path in the nested
    ``ProcessPrompts.tokenizer`` config, so preserve the upstream ``__call__``
    while constructing only the transform list correctly here.
    """
    cfg = dict(dataset_cfg)
    dataset_type = cfg.pop("type", None)
    if dataset_type != "PrivateInferenceDataset":
        raise ValueError(f"unexpected inference dataset type: {dataset_type!r}")
    cfg.pop("model_path", None)
    transforms = cfg.pop("transforms")
    norm_stats = cfg.pop("norm_stats")
    dataset = dataset_cls.__new__(dataset_cls)
    dataset.transforms = [transform_builder(dict(item)) for item in transforms]
    if isinstance(norm_stats, str):
        with Path(norm_stats).open("r", encoding="utf-8") as stream:
            dataset.norm_stats = json.load(stream)
    else:
        dataset.norm_stats = norm_stats
    dataset.img_keys = cfg.pop("img_keys", ["agentview_image"])
    dataset.center_crop = cfg.pop("center_crop", False)
    dataset.resize_size = cfg.pop("resize_size", 224)
    dataset.max_len = cfg.pop("max_len", 180)
    dataset.use_quantiles = cfg.pop("use_quantiles", True)
    dataset.embodiment_id = cfg.pop("embodiment_id", None)
    dataset.extra_tensor_keys = cfg.pop("extra_tensor_keys", []) or []
    if cfg:
        raise TypeError(f"unsupported PrivateInferenceDataset options: {sorted(cfg)}")
    return dataset


def _storage_signature(tensor: Any) -> tuple[Any, ...] | None:
    if (
        not hasattr(tensor, "untyped_storage")
        or tensor.numel() == 0
        or getattr(tensor, "is_meta", False)
    ):
        return None
    data_ptr = tensor.untyped_storage().data_ptr()
    if data_ptr == 0:
        return None
    return (
        data_ptr,
        tensor.storage_offset(),
        tuple(tensor.shape),
        tuple(tensor.stride()),
        tensor.dtype,
    )


def restore_missing_tied_tensors(
    loaded: dict[str, Any], model_state: dict[str, Any]
) -> dict[str, Any]:
    """Restore only aliases proven tied by the instantiated model storage."""
    restored = dict(loaded)
    aliases: dict[tuple[Any, ...], list[str]] = {}
    for name, tensor in model_state.items():
        signature = _storage_signature(tensor)
        if signature is not None:
            aliases.setdefault(signature, []).append(name)
    for names in aliases.values():
        present = next((name for name in names if name in restored), None)
        if present is None:
            continue
        for name in names:
            if name not in restored:
                restored[name] = restored[present]
    return restored


def validate_rtc_request(
    request: dict[str, Any],
) -> tuple[dict[str, Any], np.ndarray | None, int]:
    observation = request.get("observation")
    if not isinstance(observation, dict):
        raise ValueError("observation must be a mapping")
    qpos = np.asarray(observation.get("qpos"), dtype=np.float32)
    if qpos.shape != (14,) or not np.isfinite(qpos).all():
        raise ValueError("observation qpos must be one finite 14D vector")
    checked = dict(observation)
    checked["qpos"] = np.ascontiguousarray(qpos)
    for key in CAMERA_KEYS:
        image = np.asarray(observation.get(key))
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError(f"camera {key} must be one HWC uint8 RGB image")
        checked[key] = np.ascontiguousarray(image)
    if not isinstance(observation.get("task_description"), str):
        raise ValueError("task_description must be a string")

    prefix_len = int(request.get("prefix_len", 0))
    if not 0 <= prefix_len <= 50:
        raise ValueError("prefix_len must be between 0 and 50")
    raw_value = request.get("previous_raw_actions")
    if raw_value is None:
        if prefix_len:
            raise ValueError("prefix_len requires previous_raw_actions")
        previous = None
    else:
        previous = np.asarray(raw_value, dtype=np.float32)
        if (
            previous.ndim != 2
            or previous.shape[1] != 32
            or len(previous) < prefix_len
            or not np.isfinite(previous).all()
        ):
            raise ValueError(
                "previous_raw_actions must be finite with shape (steps, 32) "
                "and cover prefix_len"
            )
        previous = np.ascontiguousarray(previous)
    return checked, previous, prefix_len


class FluxPI05RTCPolicy:
    """Own model preprocessing and official prefix-RTC prediction only."""

    def __init__(
        self, *, config: str, checkpoint: str, statistics: str | None = None
    ) -> None:
        import torch
        from mmengine import Config
        from safetensors.torch import load_file

        from fluxvla.datasets.parquet_dataset import PrivateInferenceDataset
        from fluxvla.engines import build_dataset_from_cfg, build_transform_from_cfg
        from fluxvla.engines import build_vla_from_cfg

        self._torch = torch
        # The fixed project overlay reads registered local paths from the
        # environment and imports the pinned upstream RTC config. MMEngine's
        # lazy Python parser rejects those runtime operations, so execute this
        # trusted local file and admit only the sections consumed here.
        source = runpy.run_path(str(Path(config).expanduser().resolve()))
        required = ("inference_model", "dataset", "denormalize_action")
        missing = [name for name in required if name not in source]
        if missing:
            raise RuntimeError(f"RTC config sections missing: {missing}")
        cfg = Config({name: source[name] for name in required})
        checkpoint_path = Path(checkpoint).expanduser().resolve()
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"checkpoint not found: {checkpoint_path}")
        statistics_path = (
            Path(statistics).expanduser().resolve()
            if statistics is not None
            else checkpoint_path.parent.parent / "dataset_statistics.json"
        )
        if not statistics_path.is_file():
            raise FileNotFoundError(
                f"dataset statistics not found beside checkpoint: {statistics_path}"
            )

        dataset_cfg = dict(cfg.dataset)
        dataset_cfg["norm_stats"] = str(statistics_path)
        if dataset_cfg.get("type") == "PrivateInferenceDataset":
            self._dataset = initialize_private_inference_dataset(
                PrivateInferenceDataset, dataset_cfg, build_transform_from_cfg
            )
        else:
            self._dataset = build_dataset_from_cfg(dataset_cfg)
        denormalize_cfg = dict(cfg.denormalize_action)
        denormalize_cfg["norm_stats"] = str(statistics_path)
        self._denormalize = build_transform_from_cfg(denormalize_cfg)
        self._rtc_config = {"enabled": True, "method": "prefix"}

        self._vla = build_vla_from_cfg(cfg.inference_model)
        state = load_file(str(checkpoint_path), device="cpu")
        state = restore_missing_tied_tensors(state, self._vla.state_dict())
        self._vla.load_state_dict(state, strict=True)
        self._vla.eval()
        self._requests = 0
        self._total_inference_s = 0.0

    @property
    def status(self) -> dict[str, Any]:
        average = self._total_inference_s / self._requests if self._requests else 0.0
        return {
            "status": "ready",
            "requests": self._requests,
            "average_inference_s": average,
        }

    def infer(self, request: dict[str, Any]) -> dict[str, Any]:
        observation, previous, prefix_len = validate_rtc_request(request)
        batch = self._dataset(observation)
        if isinstance(batch, tuple):
            batch = batch[0]
        if previous is not None and prefix_len:
            batch["prev_actions"] = self._torch.from_numpy(previous).cuda()
            batch["prefix_len"] = prefix_len
            batch["rtc_config"] = self._rtc_config

        started = time.perf_counter()
        with self._torch.inference_mode():
            raw = self._vla.predict_action(**batch)
        self._torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        raw_numpy = raw.detach().float().cpu().numpy()
        actions = self._denormalize(
            {"action": raw_numpy, "state": observation["qpos"]}
        )
        if raw_numpy.ndim == 3 and raw_numpy.shape[0] == 1:
            raw_numpy = raw_numpy[0]
        self._requests += 1
        self._total_inference_s += elapsed
        return {
            "actions": np.ascontiguousarray(actions, dtype=np.float32),
            "raw_actions": np.ascontiguousarray(raw_numpy, dtype=np.float32),
            "inference_s": elapsed,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--statistics")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7896)
    parser.add_argument("--prewarm", action="store_true")
    return parser.parse_args()


def main() -> None:
    import zmq

    args = parse_args()
    policy = FluxPI05RTCPolicy(
        config=args.config,
        checkpoint=args.checkpoint,
        statistics=args.statistics,
    )
    if args.prewarm:
        zeros = np.zeros((480, 640, 3), dtype=np.uint8)
        policy.infer(
            {
                "observation": {
                    "qpos": np.zeros(14, dtype=np.float32),
                    "cam_high": zeros,
                    "cam_left_wrist": zeros,
                    "cam_right_wrist": zeros,
                    "task_description": (
                        "Open the pot lid, put the object into the pot, then close the lid."
                    ),
                },
                "prefix_len": 0,
            }
        )
        print("[flux-pi05-server] baseline CUDA graph prewarm complete", flush=True)

    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.setsockopt(zmq.LINGER, 0)
    socket.bind(f"tcp://{args.host}:{args.port}")
    print(
        f"[flux-pi05-server] ready on tcp://{args.host}:{args.port}", flush=True
    )
    try:
        while True:
            request = decode_message(socket.recv())
            try:
                endpoint = request.get("endpoint")
                if endpoint == "ping":
                    response = policy.status
                elif endpoint == "infer":
                    response = policy.infer(request)
                elif endpoint == "stop":
                    socket.send(encode_message({"status": "stopping"}))
                    break
                else:
                    raise ValueError(f"unknown endpoint: {endpoint!r}")
            except Exception as error:  # noqa: BLE001 - send fail-closed error
                response = {"error": f"{type(error).__name__}: {error}"}
            socket.send(encode_message(response))
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    main()
