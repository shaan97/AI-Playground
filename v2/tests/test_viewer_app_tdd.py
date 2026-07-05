"""TDD for viewer.app — the long-lived control-plane HTTP server.

Run as ``python v2/tests/test_viewer_app_tdd.py``. RED until viewer.app exists.

This is an end-to-end HTTP smoke test (stdlib ``urllib``): it starts the app
against a temp ``runs/`` directory holding one fixture run, then drives the
read-model endpoints the SPA depends on. It does *not* launch worker
subprocesses (that is covered by the jobs test) — ``jobs=None`` disables the
launcher so the read surface can be tested in isolation.

Spec under test:
- create_server(root, host, port=0, jobs=None) binds and returns a server; the
  bound port is ``server.server_address[1]``.
- GET /                                  -> the SPA (text/html)
- GET /api/runs                          -> [summary, ...]
- GET /api/runs/<id>/meta                -> {count, latest, agents, ...}
- GET /api/runs/<id>/history             -> [snapshot, ...]
- GET /api/runs/<id>/step/<i>            -> one snapshot
- GET /api/runs/<id>/trace/<i>/<agent>   -> {step, vertex, messages}
- GET /api/runs/<id>/conversation/<agent>-> {agent, system, turns}
- unknown run -> 404; with jobs=None, POST /api/runs -> 404 (launch disabled).
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from viewer.app import create_server  # noqa: E402

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


def _write_run(root: Path, run_id: str) -> None:
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    traj = [
        {"states": {"agent": {}, "registry": {"ledger": []}}, "arcs": {"agent": ["registry"], "registry": []}},
        {"states": {"agent": {"t": 1}, "registry": {"ledger": []}}, "arcs": {"agent": ["registry"], "registry": []}},
        {"states": {"agent": {"t": 2}, "registry": {"ledger": []}}, "arcs": {"agent": ["registry"], "registry": []}},
    ]
    (d / "trajectory.jsonl").write_text("".join(json.dumps(c) + "\n" for c in traj), encoding="utf-8")
    sys_msg = {"role": "system", "content": "You are a vertex."}
    rows = [
        {"step": 1, "agent": "agent", "messages": [sys_msg,
            {"role": "user", "content": "s"},
            {"role": "assistant", "content": "hi", "reasoning": "r1", "tool_calls": []}]},
        {"step": 2, "agent": "agent", "messages": [sys_msg,
            {"role": "user", "content": "s"},
            {"role": "assistant", "content": "bye", "reasoning": "r2", "tool_calls": []}]},
    ]
    (d / "transcripts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (d / "run.json").write_text(json.dumps({"id": run_id, "steps": 2, "registry": "registry",
                                            "spec": {"kind": "demo", "model": "gemma4"}}), encoding="utf-8")


def _get(port: int, path: str):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def _get_json(port: int, path: str):
    status, ctype, body = _get(port, path)
    return status, json.loads(body.decode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-20260101-000000")
        server = create_server(root, host="127.0.0.1", port=0, jobs=None)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            status, ctype, body = _get(port, "/")
            check("GET / serves html", status == 200 and "text/html" in ctype and b"Universe" in body)

            status, runs = _get_json(port, "/api/runs")
            check("GET /api/runs lists the run", status == 200
                  and any(r["id"] == "run-20260101-000000" for r in runs))

            status, meta = _get_json(port, "/api/runs/run-20260101-000000/meta")
            check("GET meta returns counts", status == 200 and meta["count"] == 3 and meta["latest"] == 2)
            check("GET meta lists agents", meta["agents"] == ["agent"])

            status, hist = _get_json(port, "/api/runs/run-20260101-000000/history")
            check("GET history returns snapshots", status == 200 and len(hist) == 3)
            check("history marks traced step", hist[1]["traced"] == ["agent"])

            status, snap = _get_json(port, "/api/runs/run-20260101-000000/step/1")
            check("GET step returns snapshot", status == 200 and snap["step"] == 1)

            status, tr = _get_json(port, "/api/runs/run-20260101-000000/trace/2/agent")
            check("GET trace returns messages", status == 200 and len(tr["messages"]) == 3)

            status, conv = _get_json(port, "/api/runs/run-20260101-000000/conversation/agent")
            check("GET conversation stitches turns", status == 200
                  and [t["step"] for t in conv["turns"]] == [1, 2]
                  and "vertex" in (conv["system"] or ""))

            code = None
            try:
                _get(port, "/api/runs/nope/meta")
            except urllib.error.HTTPError as e:
                code = e.code
            check("unknown run meta -> 404", code == 404)

            # Launch disabled when jobs=None.
            code = None
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/runs",
                                             data=b"{}", method="POST")
                urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as e:
                code = e.code
            check("POST /api/runs with jobs=None -> 404", code == 404)
        finally:
            server.shutdown()

    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
