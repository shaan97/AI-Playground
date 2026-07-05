#!/usr/bin/env python3
"""Audit & analyze a saved Gemma-world run.

A run directory (``runs/run-*/``) holds:
  trajectory.jsonl  — one world-graph snapshot per step: {"states":{v:{...}}, "arcs":{v:[...]}}
  run.json          — {"steps", "registry", "local_kernels": {v: code}, ...}
  transcripts.jsonl — (only if produced via the viewer harness) one line per
                      (step, agent) turn: {"step", "agent", "messages":[...]}

The substrate persists only configurations, so the *only* window into an agent's
reasoning is transcripts.jsonl (the per-turn render it saw + its assistant
messages + tool calls). The status strings agents write via set_state are their
own words and double as a cheap cognitive trace even without transcripts.

Usage:
    python analyze_run.py <run_dir>                      # summary + audit + evolution
    python analyze_run.py <run_dir> --evolution          # per-step structural diff only
    python analyze_run.py <run_dir> --audit              # audit findings only
    python analyze_run.py <run_dir> --summary            # stats + created vertices only
    python analyze_run.py <run_dir> --trace 7:agent1 17:agent1 ...   # reasoning for turns
    python analyze_run.py <run_dir> --trace-all          # every turn's assistant+tool calls
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Windows consoles default to cp1252; force UTF-8 so em-dashes etc. don't mojibake.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OBJECTS = {"beacon", "note"}          # inert demo objects in gemma_world
NONVERTEX_TARGETS = {"*"}             # known wildcard arc target


def load(run_dir: Path):
    traj = [json.loads(l) for l in (run_dir / "trajectory.jsonl").read_text("utf-8").splitlines() if l.strip()]
    meta = {}
    if (run_dir / "run.json").exists():
        meta = json.loads((run_dir / "run.json").read_text("utf-8"))
    transcripts = []
    tp = run_dir / "transcripts.jsonl"
    if tp.exists():
        transcripts = [json.loads(l) for l in tp.read_text("utf-8").splitlines() if l.strip()]
    return traj, meta, transcripts


def detect_agents(traj, transcripts):
    if transcripts:
        return sorted({t["agent"] for t in transcripts})
    genesis = traj[0]["states"]
    # agents = genesis vertices that aren't the registry or the demo objects
    return sorted(v for v in genesis if v not in OBJECTS and v != "registry"
                  and not re.fullmatch(r"v\d+", v))


def evolution(traj):
    out, prev = [], None
    for i, d in enumerate(traj):
        states, arcs = d["states"], d["arcs"]
        changes = []
        if prev is None:
            changes.append("GENESIS nodes=" + ",".join(sorted(states)))
        else:
            ps, pa = prev["states"], prev["arcs"]
            new_v = [v for v in states if v not in ps]
            if new_v:
                changes.append("NEW VERTICES: " + ", ".join(new_v))
            for v in states:
                if states[v] != ps.get(v):
                    changes.append(f"{v}.state {json.dumps(ps.get(v))} -> {json.dumps(states[v])}")
            for v in arcs:
                added = set(arcs[v]) - set(pa.get(v, []))
                removed = set(pa.get(v, [])) - set(arcs[v])
                if added:
                    changes.append(f"{v} +observes {sorted(added)}")
                if removed:
                    changes.append(f"{v} -observes {sorted(removed)}")
        if changes:
            out.append((i, changes))
        prev = d
    return out


def audit(traj, meta, transcripts, agents):
    f = []
    n = len(traj) - 1  # steps (genesis is index 0)
    final = traj[-1]
    created = sorted(meta.get("local_kernels", {}), key=lambda s: (len(s), s))

    # 1. Convergence. Distinguish STRUCTURAL change (new vertex / arc rewiring) from
    # mere state churn — agents often keep paraphrasing the same conclusion in their
    # state every step, so "some state changed" is a poor stop signal.
    last_struct = 0
    for i in range(1, len(traj)):
        prev_v, cur_v = set(traj[i - 1]["states"]), set(traj[i]["states"])
        arcs_changed = any(set(traj[i]["arcs"].get(v, [])) != set(traj[i - 1]["arcs"].get(v, []))
                           for v in cur_v | prev_v)
        if cur_v != prev_v or arcs_changed:
            last_struct = i
    if last_struct < n:
        f.append(f"STRUCTURAL CONVERGENCE: last vertex/arc change at step {last_struct}; "
                 f"steps {last_struct + 1}-{n} only reworded agent state (no topology change).")
    else:
        f.append(f"STRUCTURAL CONVERGENCE: topology still changing at the final step {n}.")

    # 2. Phantom arcs: observation targets that are not real vertices.
    phantom = {}
    for d in traj:
        verts = set(d["states"])
        for v, tgts in d["arcs"].items():
            for t in tgts:
                if t not in verts and t not in NONVERTEX_TARGETS and t != "ledger":
                    phantom.setdefault(t, set()).add(v)
    if phantom:
        f.append("PHANTOM ARCS (agents observing names that are not vertices — model drifted off the graph):")
        for t, srcs in sorted(phantom.items()):
            f.append(f"    '{t}'  <- observed by {sorted(srcs)}")

    # 3. Created vertices: inert? non-Python behavior?
    if created:
        f.append(f"CREATED VERTICES: {len(created)} ({', '.join(created)})")
        for v in created:
            code = meta["local_kernels"][v]
            state_changed = any(
                traj[i]["states"].get(v) != traj[i - 1]["states"].get(v)
                for i in range(1, len(traj)) if v in traj[i]["states"]
                and v in traj[i - 1].get("states", {})
            )
            looks_js = bool(re.search(r"\bfunction\b|//|console\.|&&|\|\||\{\s*$", code, re.M)) \
                or "def " not in code and ("return \"" in code or "return {" in code) and "function" in code
            nonpy = "function " in code or "console." in code or "//" in code
            tags = []
            if not state_changed:
                tags.append("state never changed after creation (inert)")
            if nonpy:
                tags.append("behavior looks like JS/pseudocode — the Python sandbox cannot run it")
            f.append(f"    {v}: {', '.join(tags) if tags else 'has Python-looking behavior'}")

    # 4. Self-observation.
    self_obs = sorted(v for v in agents if v in final["arcs"].get(v, []))
    if self_obs:
        f.append(f"SELF-OBSERVATION: {self_obs} observe their own state (memory loop).")

    # 5. Peer observation across the WHOLE run (did they ever discover each other?).
    ever_peer = sorted({a for d in traj for a in agents
                        if any(b in d["arcs"].get(a, []) for b in agents if b != a)})
    f.append(f"PEER OBSERVATION: {ever_peer or 'none'} observed another agent at some step "
             f"(coordination here is stigmergic — agents read each other's state; there is no message primitive).")

    # 6. Signal propagation: how far did beacon/note content spread into agent states?
    final_blob = json.dumps(final["states"])
    for sig, label in (("42", "beacon '42'"), ("hello from the note", "note text")):
        hits = sum(1 for a in agents if sig in json.dumps(final["states"].get(a, {})))
        f.append(f"SIGNAL SPREAD: {label} present in {hits}/{len(agents)} agents' final state.")

    # 7. Late-stage repetition: even when the literal JSON differs each step, the
    # agents may just be rewording one conclusion. Measure word-set overlap (Jaccard)
    # between consecutive agent states in the tail; high overlap => paraphrasing.
    if n >= 6:
        def words(blob):
            return set(re.findall(r"[a-zA-Z0-9]+", json.dumps(blob).lower()))
        tail = traj[-7:]
        sims = []
        for a in agents:
            for i in range(1, len(tail)):
                w0, w1 = words(tail[i - 1]["states"].get(a, {})), words(tail[i]["states"].get(a, {}))
                if w0 or w1:
                    sims.append(len(w0 & w1) / max(1, len(w0 | w1)))
        avg = sum(sims) / len(sims) if sims else 0.0
        verdict = "paraphrasing one conclusion" if avg >= 0.5 else "still introducing new content"
        f.append(f"LATE NOVELTY: mean word-overlap between consecutive agent states "
                 f"in last {len(tail)} steps = {avg:.2f} ({verdict}).")

    # 8. Per-agent activity.
    if transcripts:
        f.append("PER-AGENT TOOL ACTIVITY (from transcripts):")
        for a in agents:
            calls = {}
            for t in transcripts:
                if t["agent"] != a:
                    continue
                for m in t["messages"]:
                    for tc in (m.get("tool_calls") or []):
                        name = (tc.get("function", {}) or {}).get("name", "?")
                        calls[name] = calls.get(name, 0) + 1
            f.append(f"    {a}: " + (", ".join(f"{k}={v}" for k, v in sorted(calls.items())) or "no tool calls"))
    return f


def show_traces(transcripts, picks=None, maxlen=900):
    want = None
    if picks:
        want = set()
        for p in picks:
            s, a = p.split(":")
            want.add((int(s), a))
    for d in transcripts:
        if want is not None and (d["step"], d["agent"]) not in want:
            continue
        print("\n" + "=" * 72)
        print(f"STEP {d['step']}  {d['agent']}")
        for m in d["messages"]:
            role = m.get("role")
            if role in ("system", "user"):
                continue  # skip the render; show the agent's own words + actions
            content = (m.get("content") or "").strip()
            if content:
                print(f"[{role}] {content[:maxlen]}")
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                print(f"  >> {fn.get('name')}({str(fn.get('arguments'))[:maxlen]})")


def main():
    p = argparse.ArgumentParser(description="Audit & analyze a Gemma-world run.")
    p.add_argument("run_dir")
    p.add_argument("--evolution", action="store_true")
    p.add_argument("--audit", action="store_true")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--trace", nargs="*", metavar="STEP:AGENT")
    p.add_argument("--trace-all", action="store_true")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    traj, meta, transcripts = load(run_dir)
    agents = detect_agents(traj, transcripts)
    steps = len(traj) - 1

    if args.trace is not None or args.trace_all:
        if not transcripts:
            print("(no transcripts.jsonl in this run — re-run via the viewer harness to capture reasoning)")
            return
        show_traces(transcripts, picks=None if args.trace_all else args.trace)
        return

    selective = args.evolution or args.audit or args.summary
    print(f"RUN {run_dir.name}  |  steps={steps}  agents={agents}  "
          f"transcripts={'yes (' + str(len(transcripts)) + ' turns)' if transcripts else 'NO'}")

    if not selective or args.summary:
        created = meta.get("local_kernels", {})
        print(f"\n== CREATED VERTICES ({len(created)}) ==")
        for v in sorted(created, key=lambda s: (len(s), s)):
            code = created[v].replace("\n", " ")
            print(f"  {v}: state={json.dumps(traj[-1]['states'].get(v, {}))}")
            print(f"      code: {code[:200]}")

    if not selective or args.audit:
        print("\n== AUDIT ==")
        for line in audit(traj, meta, transcripts, agents):
            print("  " + line)

    if not selective or args.evolution:
        print("\n== EVOLUTION ==")
        for i, changes in evolution(traj):
            print(f"\n-- step {i} --")
            for c in changes:
                print("  " + c)


if __name__ == "__main__":
    main()
