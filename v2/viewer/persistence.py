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
import time
from pathlib import Path

from gds import Configuration, GraphDynamicalSystem, Trajectory
from gds.kernel import LocalKernel

TRAJECTORY_FILE = "trajectory.jsonl"
RUN_FILE = "run.json"


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
