"""JobManager — a small, pool-limited supervisor for experiment runs.

Launching an experiment spawns a **worker subprocess** (``python -m
viewer.worker <run_dir>``) that builds a world, steps it, and appends its
trajectory/transcripts to the run directory as it goes. The manager caps how
many run concurrently; extra launches queue and start as slots free.

Everything the manager needs to know lives on disk (``status.json`` per run), so
it is restart-tolerant and the same status a run reports is what the viewer
reads. This is an **operator** capability — it lives in the viewer, never in the
substrate.

The process boundary is injectable (``spawn(cmd, cwd) -> proc``) so the pool and
lifecycle logic can be unit-tested with fake processes, no model required.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# Run-states written to status.json. Terminal states are never restarted.
TERMINAL = {"done", "stopped", "crashed"}
V2_DIR = Path(__file__).resolve().parent.parent  # worker runs with v2/ on cwd


def _now() -> float:
    return time.time()


class JobManager:
    def __init__(self, root, max_concurrent: int = 3, *, spawn=None,
                 worker_cmd=None, python: str | None = None, cwd=None,
                 reap_interval: float = 0.5, stale_after: float = 30.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max(1, int(max_concurrent))
        self._spawn = spawn or self._default_spawn
        self._worker_cmd = worker_cmd or self._default_worker_cmd
        self._python = python or sys.executable
        self._cwd = str(cwd) if cwd else str(V2_DIR)
        self._procs: dict[str, object] = {}   # run_id -> proc (running only)
        self._queue: list[str] = []           # run_ids awaiting a free slot
        self._lock = threading.RLock()
        self._reconcile(stale_after)
        if reap_interval and reap_interval > 0:
            t = threading.Thread(target=self._reap_loop, args=(reap_interval,),
                                 name="jobs-reaper", daemon=True)
            t.start()

    # ------------------------------------------------------------- defaults
    def _default_worker_cmd(self, run_dir: Path) -> list[str]:
        return [self._python, "-m", "viewer.worker", str(run_dir)]

    def _default_spawn(self, cmd, cwd):
        return subprocess.Popen(cmd, cwd=cwd)

    # ------------------------------------------------------------- public API
    def launch(self, spec) -> str:
        """Create a run directory for ``spec`` and start (or queue) its worker."""
        if not isinstance(spec, dict):
            raise ValueError("spec must be an object")
        spec = dict(spec)
        spec.setdefault("kind", "demo")
        run_id = self._mint_id()
        d = self.root / run_id
        d.mkdir(parents=True, exist_ok=True)
        steps = int(spec.get("steps") or 0)
        (d / "run.json").write_text(json.dumps({
            "id": run_id, "spec": spec, "steps": steps, "created_at": _now(),
        }, indent=2), encoding="utf-8")
        self._set_status(run_id, "queued", step=0, pid=None, started_at=None)
        with self._lock:
            self._queue.append(run_id)
        self._pump()
        return run_id

    def status(self, run_id: str) -> str | None:
        """Current run-state from status.json, or None if the run is unknown."""
        return self._read_state(run_id)

    def control(self, run_id: str, action: str) -> str:
        """Pause/resume/stop a run. Returns the operator-visible target state.

        A worker acts on the signal *between* steps (writing control.json); a
        run still sitting in the queue is cancelled to 'stopped' directly, since
        no worker exists yet to honour the signal.
        """
        with self._lock:
            if action == "stop" and run_id in self._queue:
                self._queue.remove(run_id)
                self._set_status(run_id, "stopped")
                return "stopped"
            self._write_control(run_id, action)
            if action == "stop":
                return "stopped"
            return "paused" if action == "pause" else "running"

    # ------------------------------------------------------------- internals
    def _reconcile(self, stale_after: float) -> None:
        """Adopt whatever a previous server life left on disk.

        - 'queued' runs never started; re-enqueue them (their spec is in
          run.json, so starting them now is safe and resumes the queue).
        - 'running'/'paused' runs with a **stale heartbeat** lost their worker
          when the old server died -> mark 'crashed'.
        - Fresh-heartbeat orphans are left alone: their worker is still alive
          and still polls control.json, so viewing *and* control keep working
          (the filesystem is the control plane).
        - Terminal runs are untouched.
        """
        if not self.root.is_dir():
            return
        with self._lock:
            for d in sorted(self.root.iterdir()):
                if not d.is_dir() or not (d / "status.json").exists():
                    continue
                rid = d.name
                status = self._read_status(rid)
                state = status.get("state")
                if state == "queued":
                    if rid not in self._queue:
                        self._queue.append(rid)
                elif state in ("running", "paused"):
                    heartbeat = status.get("heartbeat") or 0
                    if _now() - heartbeat > stale_after:
                        self._set_status(rid, "crashed")
        self._pump()

    def _reap_loop(self, interval: float) -> None:
        while True:
            time.sleep(interval)
            try:
                self._pump()
            except Exception:  # pragma: no cover - never let the reaper die
                pass

    def _pump(self) -> None:
        """Reap finished workers and fill freed slots from the queue."""
        with self._lock:
            for rid, proc in list(self._procs.items()):
                if proc.poll() is not None:
                    del self._procs[rid]
                    # A worker that exits without a terminal status has crashed.
                    if self._read_state(rid) not in TERMINAL:
                        self._set_status(rid, "crashed")
            while self._queue and len(self._procs) < self.max_concurrent:
                rid = self._queue.pop(0)
                if self._read_state(rid) == "stopped":
                    continue  # cancelled while queued
                self._start(rid)

    def _start(self, run_id: str) -> None:
        cmd = self._worker_cmd(self.root / run_id)
        proc = self._spawn(cmd, self._cwd)
        self._procs[run_id] = proc
        self._set_status(run_id, "running", pid=getattr(proc, "pid", None),
                         started_at=_now())

    def _mint_id(self) -> str:
        # Timestamp keeps ids roughly chronological (the index sorts by id);
        # a short random suffix guarantees uniqueness within the same second.
        return f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # ------- status.json helpers (the manager writes these before/at start;
    #         a live worker then owns the file, appending heartbeats/step). ----
    def _status_path(self, run_id: str) -> Path:
        return self.root / run_id / "status.json"

    def _read_status(self, run_id: str) -> dict:
        try:
            return json.loads(self._status_path(run_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _read_state(self, run_id: str) -> str | None:
        return self._read_status(run_id).get("state")

    _UNSET = object()

    def _set_status(self, run_id: str, state: str, *, step=_UNSET, pid=_UNSET,
                    started_at=_UNSET) -> None:
        d = self._read_status(run_id)
        d["state"] = state
        if step is not self._UNSET:
            d["step"] = step
        if pid is not self._UNSET:
            d["pid"] = pid
        if started_at is not self._UNSET and started_at is not None:
            d["started_at"] = started_at
        d.setdefault("started_at", None)
        d["heartbeat"] = _now()
        d.setdefault("error", None)
        self._status_path(run_id).write_text(json.dumps(d), encoding="utf-8")

    def _write_control(self, run_id: str, command: str) -> None:
        (self.root / run_id / "control.json").write_text(
            json.dumps({"command": command, "ts": _now()}), encoding="utf-8")
