"""TDD for viewer.runs.RunStore — the read model over saved run directories.

Run as ``python v2/tests/test_viewer_runs_tdd.py``. RED until RunStore exists.

A run directory is the unit of persistence (UNIVERSE.md §6, "the world is its own
dataset"). RunStore turns a directory on disk into the read models the web viewer
needs, *identically* for a finished archive and a still-growing live run:

- trajectory.jsonl : one ``{"states", "arcs"}`` line per step (step 0 = genesis).
- transcripts.jsonl: one ``{"step", "agent", "messages"}`` row per agent turn.
- run.json         : run metadata + the launch spec (may be absent on old runs).
- status.json      : live run-state {state, step, pid, ...} (absent = archived).

Spec under test:
- RunStore(root).list_runs() -> newest-first list of {id, status, steps, agents,
  config, live, saved_at}. Robust to legacy runs with no status.json/run.json.
- .exists(id), .agents(id), .meta(id) {count, latest, agents, registry, control,
  config, status, steps}.
- .history(id) -> [{step, states, arcs, traced}] built from trajectory.jsonl, with
  `traced` = the agents that took a turn that step (from transcripts).
- .snapshot(id, step); .trace(id, step, agent) {step, vertex, messages}.
- .conversation(id, agent) {agent, system, turns:[{step, messages}]} — the whole
  trajectory as one transcript, system prompt lifted out once, per-step turns in
  order with the repeated leading system message stripped.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from viewer.runs import RunStore  # noqa: E402

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


# --------------------------------------------------------------- fixtures

def _write_run(root: Path, run_id: str, *, with_status: bool = True,
               with_transcripts: bool = True, with_run_json: bool = True) -> Path:
    """Write a tiny but realistic run directory and return its path."""
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)

    # 3 configurations: genesis (step 0) + two steps. One agent + registry + note.
    traj = [
        {"states": {"agent": {}, "registry": {"ledger": []}, "note": {"text": "hi"}},
         "arcs": {"agent": ["registry"], "note": [], "registry": ["agent"]}},
        {"states": {"agent": {"turn": 1}, "registry": {"ledger": ["note"]}, "note": {"text": "hi"}},
         "arcs": {"agent": ["registry"], "note": [], "registry": ["agent"]}},
        {"states": {"agent": {"turn": 2}, "registry": {"ledger": ["note"]}, "note": {"text": "hi"}},
         "arcs": {"agent": ["registry", "note"], "note": [], "registry": ["agent"]}},
    ]
    (d / "trajectory.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in traj), encoding="utf-8")

    if with_transcripts:
        sys_msg = {"role": "system", "content": "You are a vertex in a world of objects."}
        rows = [
            {"step": 1, "agent": "agent", "messages": [
                sys_msg,
                {"role": "user", "content": "Your state:\n{}"},
                {"role": "assistant", "content": "", "reasoning": "thinking about step 1",
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": "set_state", "arguments": '{"state":{"turn":1}}'}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            ]},
            {"step": 2, "agent": "agent", "messages": [
                sys_msg,
                {"role": "user", "content": "Your state:\n{\"turn\":1}"},
                {"role": "assistant", "content": "watching note", "reasoning": "thinking about step 2",
                 "tool_calls": [{"id": "c2", "type": "function",
                                 "function": {"name": "add_arc", "arguments": '{"target":"note"}'}}]},
                {"role": "tool", "tool_call_id": "c2", "content": "ok"},
            ]},
        ]
        (d / "transcripts.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    if with_run_json:
        (d / "run.json").write_text(json.dumps({
            "id": run_id,
            "steps": 2,
            "registry": "registry",
            "local_kernels": {},
            "saved_at": 1000.0,
            "spec": {"model": "gemma4", "agents": 1, "level": 2, "steps": 2},
        }), encoding="utf-8")

    if with_status:
        (d / "status.json").write_text(json.dumps({
            "state": "done", "step": 2, "pid": None,
            "started_at": 900.0, "heartbeat": 1000.0, "error": None,
        }), encoding="utf-8")

    return d


# --------------------------------------------------------------- discovery

def test_list_runs_discovers_and_sorts():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-20260101-000000")
        _write_run(root, "run-20260102-000000")
        (root / "not-a-run.txt").write_text("ignore me", encoding="utf-8")
        store = RunStore(root)
        runs = store.list_runs()
        ids = [r["id"] for r in runs]
        check("list_runs finds both run dirs", set(ids) == {"run-20260101-000000", "run-20260102-000000"})
        check("list_runs ignores stray files", "not-a-run.txt" not in ids)
        check("list_runs sorts newest id first", ids[0] == "run-20260102-000000")
        r0 = runs[0]
        check("run summary has agents", r0["agents"] == ["agent"])
        check("run summary has step count (=2 steps past genesis)", r0["steps"] == 2)
        check("run summary status from status.json", r0["status"] == "done")
        check("run summary surfaces spec/config", r0["config"].get("model") == "gemma4")
        check("done run is not live", r0["live"] is False)


def test_legacy_run_without_status_or_runjson():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-legacy", with_status=False, with_run_json=False)
        store = RunStore(root)
        runs = store.list_runs()
        check("legacy run still discovered", len(runs) == 1)
        r = runs[0]
        check("legacy run defaults to done/archived", r["status"] == "done" and r["live"] is False)
        check("legacy run agents derived from transcripts", r["agents"] == ["agent"])
        check("legacy run step count from trajectory", r["steps"] == 2)


def test_exists_and_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-x")
        store = RunStore(root)
        check("exists true for present run", store.exists("run-x"))
        check("exists false for absent run", not store.exists("nope"))
        check("history of absent run is empty", store.history("nope") == [])
        check("snapshot of absent run is None", store.snapshot("nope", 0) is None)


# --------------------------------------------------------------- read models

def test_history_and_traced():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-h")
        store = RunStore(root)
        hist = store.history("run-h")
        check("history has one snapshot per config", len(hist) == 3)
        check("snapshot 0 is genesis (step 0)", hist[0]["step"] == 0)
        check("genesis has no traced agent", hist[0]["traced"] == [])
        check("step 1 traced the agent", hist[1]["traced"] == ["agent"])
        check("snapshot carries states", hist[2]["states"]["agent"] == {"turn": 2})
        check("snapshot carries arcs", "note" in hist[2]["arcs"]["agent"])


def test_snapshot_and_trace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-s")
        store = RunStore(root)
        snap = store.snapshot("run-s", 1)
        check("snapshot(1) returns step 1", snap is not None and snap["step"] == 1)
        check("snapshot out of range is None", store.snapshot("run-s", 99) is None)
        tr = store.trace("run-s", 2, "agent")
        check("trace returns the step's messages", tr["step"] == 2 and len(tr["messages"]) == 4)
        check("trace of silent step is empty", store.trace("run-s", 0, "agent")["messages"] == [])


def test_conversation_stitches_turns():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-c")
        store = RunStore(root)
        conv = store.conversation("run-c", "agent")
        check("conversation is for the agent", conv["agent"] == "agent")
        check("system prompt lifted out once", "world of objects" in (conv["system"] or ""))
        check("one turn per acted step", [t["step"] for t in conv["turns"]] == [1, 2])
        # Leading system message stripped from each turn (it lives in conv['system']).
        first_turn = conv["turns"][0]["messages"]
        check("turn strips the repeated system message", first_turn[0]["role"] != "system")
        check("turn keeps reasoning", any(m.get("reasoning") for m in first_turn))
        check("turn keeps tool calls", any(m.get("tool_calls") for m in first_turn))


def test_pre_genesis_run_discoverable():
    """A just-launched run has run.json + status.json but no trajectory yet —
    the UI navigates to it immediately, so reads must not 404."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "run-fresh"
        d.mkdir()
        (d / "run.json").write_text(json.dumps(
            {"id": "run-fresh", "spec": {"kind": "demo"}}), encoding="utf-8")
        (d / "status.json").write_text(json.dumps(
            {"state": "queued", "step": 0}), encoding="utf-8")
        store = RunStore(root)
        check("pre-genesis run exists", store.exists("run-fresh"))
        runs = store.list_runs()
        check("pre-genesis run listed queued + live", len(runs) == 1
              and runs[0]["status"] == "queued" and runs[0]["live"] is True)
        check("pre-genesis history is empty", store.history("run-fresh") == [])
        m = store.meta("run-fresh")
        check("pre-genesis meta count 0", m["count"] == 0 and m["latest"] == -1)
        check("pre-genesis snapshots_from empty", store.snapshots_from("run-fresh", 0) == [])


def test_meta():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run(root, "run-m")
        store = RunStore(root)
        meta = store.meta("run-m")
        check("meta count = number of snapshots", meta["count"] == 3)
        check("meta latest = last index", meta["latest"] == 2)
        check("meta lists agents", meta["agents"] == ["agent"])
        check("meta names the registry", meta["registry"] == "registry")
        check("meta carries run status", meta["status"] == "done")
        check("meta carries config/spec", meta["config"].get("model") == "gemma4")


if __name__ == "__main__":
    test_list_runs_discovers_and_sorts()
    test_legacy_run_without_status_or_runjson()
    test_exists_and_missing()
    test_history_and_traced()
    test_snapshot_and_trace()
    test_conversation_stitches_turns()
    test_pre_genesis_run_discoverable()
    test_meta()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
