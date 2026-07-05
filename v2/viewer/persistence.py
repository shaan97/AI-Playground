"""Persist and resume a run.

A run's recoverable essence is its **trajectory** (every step's `Configuration`)
plus the **kernels** (behaviour). The trajectory is fully serialisable. Kernels
are not, in general — a `FunctionKernel`/`LLMKernel` wraps live Python — so the
resume contract is: *the world's `build()` re-creates the genesis kernels, and we
persist the code of any `LocalKernel` created during the run* (the only kind the
substrate mints at runtime). Everything else a run accumulates — agent memory,
wiring, object state — lives in the `Configuration` and is saved.

This is the design's "the world is its own dataset" (UNIVERSE.md §6) made
concrete: save on halt, reload any snapshot later, keep stepping.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from gds import Configuration, GraphDynamicalSystem, Trajectory
from gds.kernel import LocalKernel

TRAJECTORY_FILE = "trajectory.jsonl"
TRANSCRIPTS_FILE = "transcripts.jsonl"
RUN_FILE = "run.json"
STATUS_FILE = "status.json"
KERNELS_FILE = "kernels.json"


def _local_kernel_map(gds: GraphDynamicalSystem) -> dict:
    """``{vertex: {"code", "error"}}`` for every runtime-created LocalKernel.

    Genesis kernels (agents, registry, scripted objects) are omitted — only the
    author-written objects the substrate mints at runtime carry recoverable code.
    ``error`` is the object's most recent transition failure (``None`` if its last
    step ran cleanly): the single most useful signal when an object looks inert in
    the viewer — an object whose code keeps raising silently holds its state, so
    surfacing the error explains "why isn't this updating?".
    """
    return {
        v: {"code": k.code, "error": getattr(k, "last_error", None)}
        for v, k in gds.kernels.items()
        if isinstance(k, LocalKernel)
    }


def save_run(gds: GraphDynamicalSystem, directory: str | Path) -> Path:
    """Write the trajectory + run metadata so the run can be resumed later."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    gds.trajectory.to_jsonl(d / TRAJECTORY_FILE)
    # Code for runtime-created vertices (LocalKernels); genesis kernels are
    # rebuilt by the world's build() on resume.
    local_kernels = {
        v: k.code for v, k in gds.kernels.items() if isinstance(k, LocalKernel)
    }
    meta = {
        "steps": gds.step_index,
        "registry": gds.registry,
        "local_kernels": local_kernels,
        "saved_at": time.time(),
    }
    (d / RUN_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return d


class RunWriter:
    """Append a run's trajectory + transcripts + status to a directory as it runs.

    Where :func:`save_run` writes a finished run all at once, this streams: one
    trajectory line and (if any) transcript rows per step, plus a ``status.json``
    heartbeat. That is what lets the control plane *tail* a live run — a run
    directory that is still growing — with the same reader it uses for archives.

    A worker owns its ``status.json`` while running: it writes ``running`` /
    ``paused`` heartbeats each step and a terminal ``done`` / ``stopped`` /
    ``crashed`` on exit.
    """

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.traj = self.dir / TRAJECTORY_FILE
        self.transcripts = self.dir / TRANSCRIPTS_FILE

    def genesis(self, gds: GraphDynamicalSystem) -> None:
        """Start fresh files and record the genesis configuration (step 0)."""
        self.traj.write_text("", encoding="utf-8")
        self.transcripts.write_text("", encoding="utf-8")
        self._append_config(gds.config)
        self._write_kernels(gds)
        self.set_status("running", step=getattr(gds, "step_index", 0))

    def _append_config(self, config: Configuration) -> None:
        with self.traj.open("a", encoding="utf-8") as f:
            f.write(json.dumps(config.to_dict(), ensure_ascii=False) + "\n")

    def _write_kernels(self, gds: GraphDynamicalSystem) -> None:
        """Snapshot the code + latest error of every runtime-created object, so a
        *live* run can be inspected (run.json's copy is only written on finish).
        Rewritten in full each step — the map is small and objects' errors change."""
        (self.dir / KERNELS_FILE).write_text(
            json.dumps(_local_kernel_map(gds), ensure_ascii=False), encoding="utf-8")

    def record_step(self, gds: GraphDynamicalSystem, traces: dict[str, list]) -> None:
        """Append this step's configuration and any agent turns, then heartbeat."""
        step = getattr(gds, "step_index", 0)
        self._append_config(gds.config)
        if traces:
            with self.transcripts.open("a", encoding="utf-8") as f:
                for agent, messages in sorted(traces.items()):
                    f.write(json.dumps({"step": step, "agent": agent,
                                        "messages": messages}, ensure_ascii=False) + "\n")
        self._write_kernels(gds)
        self.set_status("running", step=step)

    def set_status(self, state: str, *, step: int | None = None,
                   error: str | None = None) -> None:
        path = self.dir / STATUS_FILE
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d["state"] = state
        if step is not None:
            d["step"] = step
        d["pid"] = os.getpid()
        d["heartbeat"] = time.time()
        d.setdefault("started_at", time.time())
        d["error"] = error
        path.write_text(json.dumps(d), encoding="utf-8")

    def finish(self, gds: GraphDynamicalSystem, state: str = "done",
               error: str | None = None) -> None:
        """Write terminal status and fold run metadata (registry + runtime-created
        kernel code) into run.json, so the run stays resumable — without dropping
        the launch spec the manager wrote there."""
        path = self.dir / RUN_FILE
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        meta["steps"] = getattr(gds, "step_index", meta.get("steps", 0))
        meta["registry"] = getattr(gds, "registry", meta.get("registry"))
        meta["local_kernels"] = {
            v: k.code for v, k in gds.kernels.items() if isinstance(k, LocalKernel)
        }
        meta["saved_at"] = time.time()
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self.set_status(state, step=getattr(gds, "step_index", None), error=error)


def load_trajectory(directory: str | Path) -> Trajectory:
    return Trajectory.from_jsonl(Path(directory) / TRAJECTORY_FILE)


def resume_gds(build, directory: str | Path, step: int = -1) -> GraphDynamicalSystem:
    """Rebuild a `GraphDynamicalSystem` positioned at a saved snapshot.

    `build` is a zero-arg callable returning a fresh world (genesis kernels wired,
    registry installed) — typically the example's own ``build()``. `step` selects
    which snapshot to resume from (default ``-1`` = the last saved step); history
    up to that point is preserved on the trajectory so the viewer can still scrub
    it. Continue with ``gds.step()`` / ``serve_gds(gds, ...)``.
    """
    d = Path(directory)
    meta = json.loads((d / RUN_FILE).read_text(encoding="utf-8"))
    traj = load_trajectory(d)
    n = len(traj)
    idx = step if step >= 0 else n + step
    if not (0 <= idx < n):
        raise IndexError(f"step {step} out of range for {n} snapshots")
    snap: Configuration = traj[idx]

    gds = build()
    # Reconstruct kernels for any vertex the builder didn't provide (runtime
    # creations). A vertex with no recoverable kernel simply holds its state.
    for v in snap.vertices():
        if v not in gds.kernels:
            code = meta.get("local_kernels", {}).get(v)
            if code is not None:
                gds.kernels[v] = LocalKernel(code)

    gds.config = snap
    gds.registry = meta.get("registry", gds.registry)
    gds.step_index = idx
    gds.trajectory = Trajectory(list(traj.snapshots[: idx + 1]))
    return gds
