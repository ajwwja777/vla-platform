"""Small, auditable MsgPack wire format for Cobot RTC inference."""

from __future__ import annotations

import io
from typing import Any

import cv2
import msgpack
import numpy as np


CAMERA_KEYS = frozenset({"cam_high", "cam_left_wrist", "cam_right_wrist"})


class WireError(RuntimeError):
    """Raised for malformed or failed inference messages."""


def _encode_array(value: np.ndarray) -> bytes:
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=False)
    return stream.getvalue()


def _prepare(value: Any, *, key: str | None, compress_images: bool) -> Any:
    if isinstance(value, np.ndarray):
        if (
            compress_images
            and key in CAMERA_KEYS
            and value.ndim == 3
            and value.shape[2] == 3
            and value.dtype == np.uint8
        ):
            ok, encoded = cv2.imencode(
                ".jpg", value, [cv2.IMWRITE_JPEG_QUALITY, 95]
            )
            if not ok:
                raise WireError(f"JPEG encoding failed for {key}")
            return {"__jpeg__": True, "data": encoded.tobytes()}
        return {"__ndarray__": True, "data": _encode_array(value)}
    if isinstance(value, dict):
        return {
            item_key: _prepare(
                item_value, key=str(item_key), compress_images=compress_images
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _prepare(item, key=None, compress_images=compress_images) for item in value
        ]
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    raise WireError(f"unsupported wire value: {type(value).__name__}")


def encode_message(payload: dict[str, Any], *, compress_images: bool = False) -> bytes:
    if not isinstance(payload, dict):
        raise WireError("wire payload must be a mapping")
    return msgpack.packb(
        _prepare(payload, key=None, compress_images=compress_images),
        use_bin_type=True,
    )


def _restore(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("__jpeg__") is True:
            decoded = cv2.imdecode(
                np.frombuffer(value["data"], dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if decoded is None:
                raise WireError("JPEG decoding failed")
            return decoded
        if value.get("__ndarray__") is True:
            return np.load(io.BytesIO(value["data"]), allow_pickle=False)
        return {key: _restore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore(item) for item in value]
    return value


def decode_message(payload: bytes) -> dict[str, Any]:
    try:
        decoded = msgpack.unpackb(payload, raw=False)
    except Exception as error:  # noqa: BLE001 - normalize transport errors
        raise WireError(f"invalid MsgPack payload: {error}") from error
    restored = _restore(decoded)
    if not isinstance(restored, dict):
        raise WireError("decoded wire payload must be a mapping")
    return restored


def validate_inference_response(
    response: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, float]:
    if not isinstance(response, dict):
        raise WireError("inference response must be a mapping")
    if response.get("error"):
        raise WireError(str(response["error"]))
    actions = np.asarray(response.get("actions"), dtype=np.float32)
    raw_actions = np.asarray(response.get("raw_actions"), dtype=np.float32)
    if actions.ndim == 3 and actions.shape[0] == 1:
        actions = actions[0]
    if raw_actions.ndim == 3 and raw_actions.shape[0] == 1:
        raw_actions = raw_actions[0]
    if actions.ndim != 2 or actions.shape[1] != 14 or len(actions) < 1:
        raise WireError(f"expected actions shaped (steps, 14), got {actions.shape}")
    if raw_actions.shape != (len(actions), 32):
        raise WireError(
            f"expected raw actions shaped ({len(actions)}, 32), got {raw_actions.shape}"
        )
    if not np.isfinite(actions).all() or not np.isfinite(raw_actions).all():
        raise WireError("inference response contains non-finite actions")
    inference_s = float(response.get("inference_s", -1.0))
    if not np.isfinite(inference_s) or inference_s < 0:
        raise WireError("inference_s must be finite and non-negative")
    return (
        np.ascontiguousarray(actions),
        np.ascontiguousarray(raw_actions),
        inference_s,
    )
