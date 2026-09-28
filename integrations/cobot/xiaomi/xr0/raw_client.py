"""Python-3.8-compatible raw observation client for the local XR-0 server."""

from __future__ import annotations

import pickle
import socket
import struct

import numpy as np


def make_request(observation, instruction: str, action_prefix=None) -> dict:
    state = np.asarray(observation["observation.state"], dtype=np.float32)
    if state.shape != (14,) or not np.isfinite(state).all():
        raise ValueError("XR-0 client state must be one finite 14-D vector")
    images = {}
    for source, target in (
        ("observation.images.cam_high", "ego"),
        ("observation.images.cam_left_wrist", "left_wrist"),
        ("observation.images.cam_right_wrist", "right_wrist"),
    ):
        image = np.asarray(observation[source], dtype=np.uint8)
        if image.ndim != 3 or image.shape[-1] != 3:
            raise ValueError(f"{source} must be an RGB HWC image")
        images[target] = np.ascontiguousarray(image)
    request = {"state": state, "images": images, "instruction": str(instruction)}
    if action_prefix is not None:
        prefix = np.asarray(action_prefix, dtype=np.float32)
        if prefix.ndim != 2 or prefix.shape[1] != 32 or not 1 <= len(prefix) <= 30:
            raise ValueError("action prefix must have shape (1..30, 32)")
        if not np.isfinite(prefix).all():
            raise ValueError("action prefix contains non-finite values")
        request["action_prefix"] = np.ascontiguousarray(prefix)
    return request


def validate_response(value) -> np.ndarray:
    action = np.asarray(value, dtype=np.float32)
    if action.shape == (1, 30, 32):
        action = action[0]
    if action.shape != (30, 32):
        raise ValueError(f"XR-0 server response must have shape (30, 32), got {action.shape}")
    if not np.isfinite(action).all():
        raise ValueError("XR-0 server response contains non-finite values")
    return np.ascontiguousarray(action)


class RawClient:
    def __init__(self, host: str, port: int, timeout: float = 30.0) -> None:
        self.socket = socket.create_connection((host, port), timeout=timeout)
        self.socket.settimeout(timeout)

    @staticmethod
    def _recv_all(sock, length: int) -> bytes:
        data = b""
        while len(data) < length:
            packet = sock.recv(length - len(data))
            if not packet:
                raise ConnectionError("XR-0 server closed the connection")
            data += packet
        return data

    def __call__(self, observation, instruction: str, action_prefix=None) -> np.ndarray:
        payload = pickle.dumps(
            make_request(observation, instruction, action_prefix),
            protocol=pickle.HIGHEST_PROTOCOL,
        )
        self.socket.sendall(struct.pack(">I", len(payload)) + payload)
        size = struct.unpack(">I", self._recv_all(self.socket, 4))[0]
        return validate_response(pickle.loads(self._recv_all(self.socket, size)))

    def close(self) -> None:
        self.socket.close()

