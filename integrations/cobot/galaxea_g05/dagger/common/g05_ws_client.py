"""Small synchronous client for the official G0.5 WebSocket/msgpack protocol."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from common.g05_contract import validate_metadata
from common.g05_wire import packb, unpackb


class G05WebSocketSession:
    def __init__(
        self,
        endpoint: str,
        *,
        expected_action_steps: int,
        timeout_s: float = 120.0,
        socket_factory: Callable[..., Any] | None = None,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("endpoint must be an absolute WebSocket URL")
        if expected_action_steps < 1:
            raise ValueError("expected_action_steps must be positive")
        self.endpoint = endpoint
        self.expected_action_steps = expected_action_steps
        self.timeout_s = float(timeout_s)
        self._socket_factory = socket_factory
        self._socket = None
        self.metadata = None

    def connect(self) -> dict:
        if self._socket is not None:
            return self.metadata
        factory = self._socket_factory
        if factory is None:
            import websocket

            factory = websocket.create_connection
        self._socket = factory(
            self.endpoint,
            timeout=self.timeout_s,
            enable_multithread=True,
            http_proxy_host=None,
            http_no_proxy=["127.0.0.1", "localhost"],
        )
        metadata = unpackb(self._socket.recv())
        validate_metadata(metadata, expected_action_steps=self.expected_action_steps)
        self.metadata = metadata
        return metadata

    def infer(self, raw_observation: dict) -> dict:
        if self._socket is None:
            raise RuntimeError("G0.5 WebSocket is not connected")
        self._socket.send_binary(packb(raw_observation))
        response = unpackb(self._socket.recv())
        if not isinstance(response, dict):
            raise ValueError("G0.5 response must be a dict")
        return response

    def reset(self) -> None:
        if self._socket is None:
            return
        self._socket.send_binary(packb({"__reset__": True}))
        response = unpackb(self._socket.recv())
        if not isinstance(response, dict) or response.get("__reset__") is not True:
            raise RuntimeError(f"unexpected G0.5 reset response: {response}")

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
            self.metadata = None
