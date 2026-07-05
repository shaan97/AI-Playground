"""TDD for viewer.jobs.JobManager — the pool-limited experiment supervisor.

Run as ``python v2/tests/test_viewer_jobs_tdd.py``. RED until JobManager exists.

The supervisor spawns each experiment as a worker subprocess, capped at a small
concurrency pool; extra launches queue and start as slots free. To keep this a
deterministic unit test (no real processes, no model), we inject a fake spawner
returning controllable fake processes and drive the pump by hand.

Spec under test:
- JobManager(root, max_concurrent=N, spawn=<fn>) — spawn(cmd, cwd) -> proc, where
  proc has .pid, .poll() (None while alive, int rc when exited), .terminate().
- .launch(spec) -> run_id: mints a unique timestamped id, creates runs/<id>/ with
  run.json (spec) + status.json, and either starts a worker (state 'running') or
  queues it (state 'queued') when the pool is full. Ids are unique across rapid
  launches.
- .status(id) -> current run-state string (from status.json), or None if unknown.
- ._pump(): reap exited procs (a proc that exits without writing a terminal
  status is 'crashed'; one that wrote 'done'/'stopped' keeps it) and fill freed
  slots from the queue.
- .control(id, 'pause'|'resume'|'stop'): writes control.json for the worker; a
  'stop' on a still-queued run cancels it to 'stopped' without ever starting it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from viewer.jobs import JobManager  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"ok: {name}")
    else:
        _FAIL += 1
        print(f"FAIL: {name}")


class FakeProc:
    _next_pid = 1000

    def __init__(self, cmd, cwd):
        self.cmd = cmd
        self.cwd = cwd
        FakeProc._next_pid += 1
        self.pid = FakeProc._next_pid
        self._rc = None
        self.terminated = False

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        if self._rc is None:
            self._rc = -15

    def finish(self, rc=0):
        self._rc = rc


class Spawner:
    def __init__(self):
        self.procs = []

    def __call__(self, cmd, cwd):
        p = FakeProc(cmd, cwd)
        self.procs.append(p)
        return p


def _status(root: Path, run_id: str) -> str:
    return json.loads((root / run_id / "status.json").read_text(encoding="utf-8"))["state"]


def _write_status(root: Path, run_id: str, state: str) -> None:
    p = root / run_id / "status.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["state"] = state
    p.write_text(json.dumps(d), encoding="utf-8")


DEMO = {"kind": "demo", "steps": 5, "delay": 0.0}


def test_launch_creates_run_dir_and_starts():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sp = Spawner()
        jm = JobManager(root, max_concurrent=2, spawn=sp)
        rid = jm.launch(DEMO)
        check("launch returns an id", isinstance(rid, str) and rid)
        check("run dir created", (root / rid).is_dir())
        check("run.json written with spec", json.loads((root / rid / "run.json").read_text())["spec"]["kind"] == "demo")
        check("a worker was spawned", len(sp.procs) == 1)
        check("status is running", jm.status(rid) == "running" and _status(root, rid) == "running")
        check("worker cmd references the run dir", str(root / rid) in " ".join(sp.procs[0].cmd) or rid in " ".join(sp.procs[0].cmd))


def test_unique_ids():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        jm = JobManager(root, max_concurrent=5, spawn=Spawner())
        ids = {jm.launch(DEMO) for _ in range(6)}
        check("rapid launches get unique ids", len(ids) == 6)


def test_pool_caps_and_queues():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sp = Spawner()
        jm = JobManager(root, max_concurrent=2, spawn=sp)
        a = jm.launch(DEMO)
        b = jm.launch(DEMO)
        c = jm.launch(DEMO)
        check("only max_concurrent spawned", len(sp.procs) == 2)
        check("first two run", jm.status(a) == "running" and jm.status(b) == "running")
        check("overflow is queued", jm.status(c) == "queued")


def test_queued_starts_when_slot_frees():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sp = Spawner()
        jm = JobManager(root, max_concurrent=1, spawn=sp)
        a = jm.launch(DEMO)
        b = jm.launch(DEMO)
        check("second is queued", jm.status(b) == "queued" and len(sp.procs) == 1)
        # Worker a finishes cleanly (writes done, exits).
        _write_status(root, a, "done")
        sp.procs[0].finish(0)
        jm._pump()
        check("queued run starts after a slot frees", len(sp.procs) == 2 and jm.status(b) == "running")
        check("finished run keeps its terminal status", jm.status(a) == "done")


def test_crash_detection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sp = Spawner()
        jm = JobManager(root, max_concurrent=1, spawn=sp)
        a = jm.launch(DEMO)
        # Proc dies WITHOUT writing a terminal status -> crashed.
        sp.procs[0].finish(1)
        jm._pump()
        check("dead worker with no terminal status -> crashed", jm.status(a) == "crashed")


def test_control_writes_file_and_cancels_queued():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sp = Spawner()
        jm = JobManager(root, max_concurrent=1, spawn=sp)
        a = jm.launch(DEMO)
        b = jm.launch(DEMO)  # queued
        st = jm.control(a, "pause")
        ctrl = json.loads((root / a / "control.json").read_text())
        check("pause writes control.json", ctrl.get("command") == "pause")
        check("control returns target state", st == "paused")
        # Stopping a queued run cancels it without ever starting a worker.
        st2 = jm.control(b, "stop")
        check("stop on queued cancels to stopped", jm.status(b) == "stopped" and st2 == "stopped")
        check("cancelled queued run never spawned", len(sp.procs) == 1)


def test_reconcile_on_startup():
    """A new manager adopts what a previous server life left on disk: stale
    'running' runs (dead worker, old heartbeat) become 'crashed'; fresh-heartbeat
    orphans are left alone (their worker is still alive and still polls
    control.json); 'queued' runs are re-enqueued and started; terminal runs are
    untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        import time as _t

        def mk(rid, state, hb):
            d = root / rid
            d.mkdir()
            (d / "run.json").write_text(json.dumps({"id": rid, "spec": DEMO}), encoding="utf-8")
            (d / "status.json").write_text(json.dumps(
                {"state": state, "heartbeat": hb, "step": 1}), encoding="utf-8")

        mk("run-a-stale", "running", _t.time() - 999)
        mk("run-b-fresh", "running", _t.time())
        mk("run-c-queued", "queued", _t.time() - 999)
        mk("run-d-done", "done", _t.time() - 999)
        sp = Spawner()
        jm = JobManager(root, max_concurrent=2, spawn=sp)
        check("stale running run marked crashed", jm.status("run-a-stale") == "crashed")
        check("fresh running orphan left alone", jm.status("run-b-fresh") == "running")
        check("queued run re-enqueued and started", jm.status("run-c-queued") == "running")
        check("terminal run untouched", jm.status("run-d-done") == "done")
        check("exactly one worker spawned by reconcile", len(sp.procs) == 1)


def test_status_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        jm = JobManager(Path(tmp), max_concurrent=1, spawn=Spawner())
        check("status of unknown run is None", jm.status("nope") is None)


if __name__ == "__main__":
    test_launch_creates_run_dir_and_starts()
    test_unique_ids()
    test_pool_caps_and_queues()
    test_queued_starts_when_slot_frees()
    test_crash_detection()
    test_control_writes_file_and_cancels_queued()
    test_reconcile_on_startup()
    test_status_unknown()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
