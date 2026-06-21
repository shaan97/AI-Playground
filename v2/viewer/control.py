"""RunControl — a thread-safe pause/resume/stop switch for the serve loop.

This is an **operator** effector, deliberately living in the viewer (not the
substrate): the world model stays pure, while an operator watching remotely can
intervene. The HTTP handler thread flips the state; the step-loop thread consults
it **between steps**, so a step is never interrupted mid-flight (the substrate's
double-buffering already makes a step all-or-nothing).

States:
  running → paused → running   (resume)
  running/paused → stopped      (terminal — the loop exits)

`on_change(state)` is invoked outside the internal lock on every real transition,
so the hub can broadcast the new state to connected clients.
"""

from __future__ import annotations

import threading
from typing import Callable


class RunControl:
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"

    def __init__(self, on_change: Callable[[str], None] | None = None):
        self._cond = threading.Condition()
        self._state = self.RUNNING
        self._on_change = on_change

    # ------------------------------------------------------------------ reads

    def state(self) -> str:
        with self._cond:
            return self._state

    # --------------------------------------------------------- transitions

    def _transition(self, target: str, allowed_from: tuple[str, ...]) -> str:
        with self._cond:
            changed = self._state in allowed_from and self._state != target
            if changed:
                self._state = target
            self._cond.notify_all()  # wake a paused/sleeping loop
            new_state = self._state
        if changed and self._on_change is not None:
            self._on_change(new_state)
        return new_state

    def pause(self) -> str:
        return self._transition(self.PAUSED, (self.RUNNING,))

    def resume(self) -> str:
        return self._transition(self.RUNNING, (self.PAUSED,))

    def stop(self) -> str:
        # Allowed from any non-terminal state; terminal and irreversible.
        return self._transition(self.STOPPED, (self.RUNNING, self.PAUSED))

    # ------------------------------------------------------- loop-side helpers

    def should_stop(self) -> bool:
        with self._cond:
            return self._state == self.STOPPED

    def wait_while_paused(self) -> None:
        """Block while paused; return immediately if running or stopped."""
        with self._cond:
            while self._state == self.PAUSED:
                self._cond.wait()

    def sleep(self, seconds: float) -> None:
        """Inter-step delay that wakes early if we leave the RUNNING state, so a
        pause/stop during the delay takes effect promptly instead of after the
        full interval."""
        if seconds <= 0:
            return
        with self._cond:
            self._cond.wait_for(lambda: self._state != self.RUNNING, timeout=seconds)
