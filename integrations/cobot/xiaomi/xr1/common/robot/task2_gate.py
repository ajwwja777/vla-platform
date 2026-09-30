"""Thread-safe Task2 pause/takeover generation gate for model clients."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class GateSnapshot:
    armed: bool
    paused: bool
    generation: int
    mode: str


class Task2PauseGate:
    """Invalidate inference work across every pause or handover boundary."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed = False
        from web_pause import from_environment
        self.web_pause = from_environment()
        self._paused = True
        self._generation = 0
        self._mode = "unknown"

    def snapshot(self) -> GateSnapshot:
        with self._lock:
            return GateSnapshot(
                armed=self._armed,
                paused=self._paused,
                generation=self._generation,
                mode=self._mode,
            )

    def set_paused(self, paused: bool) -> GateSnapshot:
        with self._lock:
            wanted = bool(paused) or not self._armed or bool(self.web_pause and self.web_pause.manual)
            if self._paused != wanted:
                self._paused = wanted
                self._generation += 1
            return GateSnapshot(
                armed=self._armed,
                paused=self._paused,
                generation=self._generation,
                mode=self._mode,
            )

    def arm(self) -> GateSnapshot:
        """Allow the operator wrapper to enable policy resumes once."""

        with self._lock:
            if self._mode == "policy" and not self._armed:
                self._armed = True
                self._generation += 1
            return GateSnapshot(
                armed=self._armed,
                paused=self._paused,
                generation=self._generation,
                mode=self._mode,
            )

    def update_mode(self, mode: str) -> GateSnapshot:
        normalized = str(mode or "").strip()
        with self._lock:
            self._mode = normalized or "unknown"
            wanted_paused = normalized != "policy" or not self._armed or bool(self.web_pause and (self.web_pause.manual or self.web_pause.hil))
            if self._paused != wanted_paused:
                self._paused = wanted_paused
                self._generation += 1
            return GateSnapshot(
                armed=self._armed,
                paused=self._paused,
                generation=self._generation,
                mode=self._mode,
            )

    def publish_if_current(self, generation, publish, action):
        with self._lock:
            if self._armed and not self._paused and generation == self._generation:
                publish(action)

    def accepts(self, generation: int) -> bool:
        with self._lock:
            return (
                self._armed
                and not self._paused
                and int(generation) == self._generation
            )


class Task2ChunkSession:
    """Bind accepted inference results to one uninterrupted policy epoch."""

    def __init__(self, gate: Task2PauseGate) -> None:
        self.gate = gate
        self._active_generation: int | None = None

    @property
    def requires_fresh(self) -> bool:
        return (
            self._active_generation is None
            or not self.gate.accepts(self._active_generation)
        )

    def begin_fresh(self) -> int:
        snapshot = self.gate.snapshot()
        if not self.gate.accepts(snapshot.generation):
            raise RuntimeError("Task2 policy is paused")
        self._active_generation = snapshot.generation
        return snapshot.generation

    def accept_result(self, generation: int, result):
        if (
            self._active_generation != int(generation)
            or not self.gate.accepts(generation)
        ):
            self._active_generation = None
            return None
        return result

    def invalidate(self) -> None:
        self._active_generation = None
