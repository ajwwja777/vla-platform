"""The official G0.5 msgpack + NumPy wire format, without upstream imports."""

from __future__ import annotations

import functools
from typing import Any

import msgpack
import numpy as np


_UNSUPPORTED_KINDS = ("V", "O", "c")


def _pack(value: Any) -> Any:
    if isinstance(value, (np.ndarray, np.generic)) and value.dtype.kind in _UNSUPPORTED_KINDS:
        raise ValueError(f"Unsupported dtype: {value.dtype}")
    if isinstance(value, np.ndarray):
        contiguous = np.ascontiguousarray(value)
        return {
            "__ndarray__": True,
            "data": contiguous.tobytes(),
            "dtype": contiguous.dtype.str,
            "shape": contiguous.shape,
        }
    if isinstance(value, np.generic):
        return {"__npgeneric__": True, "data": value.item(), "dtype": value.dtype.str}
    return value


def _bytes_to_str_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            (key.decode() if isinstance(key, bytes) else key): _bytes_to_str_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_bytes_to_str_keys(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_bytes_to_str_keys(item) for item in value)
    return value


def _unpack(value: dict[Any, Any]) -> Any:
    value = _bytes_to_str_keys(value)
    if "__ndarray__" in value:
        return np.ndarray(
            buffer=value["data"],
            dtype=np.dtype(value["dtype"]),
            shape=tuple(value["shape"]),
        )
    if "__npgeneric__" in value:
        return np.dtype(value["dtype"]).type(value["data"])
    return value


packb = functools.partial(msgpack.packb, default=_pack)
unpackb = functools.partial(msgpack.unpackb, object_hook=_unpack)
