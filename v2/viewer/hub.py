"""ViewerHub — the in-memory bridge between a running world and the web UI.

The hub is deliberately *outside* the substrate: it observes a
`GraphDynamicalSystem` without changing its dynamics. It keeps

  * a light snapshot per step (states + arcs + which vertices have a trace),
  * the full per-turn transcript for each agent vertex per step, and
  * a set of live SSE subscriber queues to push new steps to.

The flow is: `instrument(gds)` wires each `LLMKernel`'s `recorder` to the hub so
turns are captured as they happen; the run loop calls `publish(gds)` after every
`gds.step()` (and once for the genesis configuration). Capture is best-effort and
side-effect-free with respect to the world.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any

# Imported lazily / defensively so the hub has no hard dependency surface beyond
# the substrate package being importable on sys.path.
try:  # pragma: no cover - exercised indirectly
    from gds.agents.llm import LLMKernel
except Exception:  # pragma: no cover
    LLMKernel = ()  # isinstance(..., ()) is always False


def _jsonable(value: Any) -> Any:
    """Coerce arbitrary state into something json.dumps can handle."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))


class ViewerHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # One light snapshot dict per step (index == step number).
        self._snapshots: list[dict] = []
        # traces[step][vertex] = list[message] for that agent's turn that step.
        self._traces: dict[int, dict[str, list]] = {}
        # Filled by recorders *during* a step; drained into _traces on publish.
        self._pending: dict[str, list] = {}
        # Vertices whose kernel is an LLM (agents) — for UI styling.
        self._agents: set[str] = set()
        self._registry: str | None = None
        # Last broadcast operator run-state (running/paused/stopped).
        self._control_state = "running"
        self._subscribers: list[queue.Queue] = []

    # ------------------------------------------------------------ instrumenting

    def instrument(self, gds) -> "ViewerHub":
        """Attach trace recorders to every LLM agent and note metadata."""
        self._registry = getattr(gds, "registry", None)
        for vertex, kernel in gds.kernels.items():
            if isinstance(kernel, LLMKernel):
                self._agents.add(vertex)
                kernel.recorder = self._recorder_for(vertex)
        return self

    def _recorder_for(self, vertex: str):
        def record(messages: list) -> None:
            # Copy so later mutation of the kernel's list can't change history.
            with self._lock:
                self._pending[vertex] = _jsonable(list(messages))
        return record

    # ----------------------------------------------------------------- publish

    def publish(self, gds) -> None:
        """Snapshot the current configuration and notify live subscribers."""
        config = gds.config
        step = getattr(gds, "step_index", len(self._snapshots))
        dg = config.digraph
        states = {v: _jsonable(config.state_of(v)) for v in dg.vertices()}
        arcs = {v: sorted(dg.out_neighbours(v)) for v in sorted(dg.vertices())}

        with self._lock:
            traces = self._pending
            self._pending = {}
            if traces:
                self._traces[step] = traces
            snap = {
                "step": step,
                "states": states,
                "arcs": arcs,
                "traced": sorted(traces.keys()),
            }
            # Index by step so out-of-order genesis/step calls stay consistent.
            while len(self._snapshots) <= step:
                self._snapshots.append(snap)
            self._snapshots[step] = snap
            subscribers = list(self._subscribers)

        payload = json.dumps(snap, ensure_ascii=False)
        self._broadcast("step", payload)

    def publish_control(self, state: str) -> None:
        """Record and broadcast a new operator run-state to all clients."""
        with self._lock:
            self._control_state = state
        self._broadcast("control", json.dumps({"state": state}))

    def _broadcast(self, event: str, data: str) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait((event, data))
            except queue.Full:  # pragma: no cover - unbounded queues used
                pass

    # -------------------------------------------------------------- read models

    def meta(self) -> dict:
        with self._lock:
            return {
                "count": len(self._snapshots),
                "latest": len(self._snapshots) - 1,
                "agents": sorted(self._agents),
                "registry": self._registry,
                "control": self._control_state,
            }

    def history(self) -> list[dict]:
        with self._lock:
            return list(self._snapshots)

    def snapshot(self, step: int) -> dict | None:
        with self._lock:
            if 0 <= step < len(self._snapshots):
                return self._snapshots[step]
            return None

    def trace(self, step: int, vertex: str) -> dict:
        with self._lock:
            messages = self._traces.get(step, {}).get(vertex)
        return {"step": step, "vertex": vertex, "messages": messages or []}

    # ------------------------------------------------------------- subscriptions

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
