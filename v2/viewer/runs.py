"""RunStore — read models over saved run directories.

A run directory *is* the unit of persistence (UNIVERSE.md §6, "the world is its
own dataset"). This module turns such a directory into exactly the read models
the web viewer needs, and does so **identically** whether the run is a finished
archive or a still-growing live run — a live run is just one whose files are
still being appended to, so tailing and history use one code path.

Directory layout (all files optional except the trajectory):
    trajectory.jsonl   one ``{"states", "arcs"}`` line per step (step 0 = genesis)
    transcripts.jsonl  one ``{"step", "agent", "messages"}`` row per agent turn
    run.json           run metadata + launch spec (absent on very old runs)
    status.json        live run-state (absent = a finished archive)

Everything here is read-only and defensive: a half-written line (a run being
appended to right now) is skipped rather than fatal, so the viewer never crashes
on a live directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TRAJECTORY_FILE = "trajectory.jsonl"
TRANSCRIPTS_FILE = "transcripts.jsonl"
RUN_FILE = "run.json"
STATUS_FILE = "status.json"
KERNELS_FILE = "kernels.json"

# Run-states that mean "still going" (the dir may still be growing).
LIVE_STATES = {"queued", "running", "paused"}

# Any one of these marks a directory as a run. A just-launched run has only
# run.json + status.json (the worker hasn't written its genesis yet); a legacy
# archive may have only trajectory.jsonl.
RUN_MARKERS = (TRAJECTORY_FILE, RUN_FILE, STATUS_FILE)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file, tolerating a trailing half-written line (live append)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # A line being written this very moment — stop; we'll see it next read.
            break
    return out


class RunStore:
    """Read-only view over a directory of run directories (typically ``runs/``)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    # ------------------------------------------------------------- discovery

    def _dir(self, run_id: str) -> Path:
        return self.root / run_id

    def exists(self, run_id: str) -> bool:
        d = self._dir(run_id)
        return d.is_dir() and any((d / m).exists() for m in RUN_MARKERS)

    def _run_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return [p.name for p in self.root.iterdir()
                if p.is_dir() and any((p / m).exists() for m in RUN_MARKERS)]

    def list_runs(self) -> list[dict]:
        """Newest-first summaries of every run in the root, for the index page."""
        runs = [self.summary(rid) for rid in self._run_ids()]
        # Newest first: run ids are timestamped (run-YYYYMMDD-HHMMSS), so id sort
        # is chronological; fall back to saved_at for anything non-conforming.
        runs.sort(key=lambda r: (r["id"], r.get("saved_at") or 0), reverse=True)
        return runs

    # ----------------------------------------------------------- run helpers

    def _run_json(self, run_id: str) -> dict:
        return _read_json(self._dir(run_id) / RUN_FILE)

    def _status(self, run_id: str) -> dict:
        return _read_json(self._dir(run_id) / STATUS_FILE)

    def _transcript_rows(self, run_id: str) -> list[dict]:
        return _read_jsonl(self._dir(run_id) / TRANSCRIPTS_FILE)

    def _configs(self, run_id: str) -> list[dict]:
        return _read_jsonl(self._dir(run_id) / TRAJECTORY_FILE)

    def _acted_by_step(self, run_id: str) -> dict[int, list[str]]:
        acted: dict[int, set[str]] = {}
        for row in self._transcript_rows(run_id):
            acted.setdefault(int(row.get("step", 0)), set()).add(row.get("agent"))
        return {step: sorted(v) for step, v in acted.items()}

    def agents(self, run_id: str) -> list[str]:
        """Agents in the run — those that took at least one recorded turn."""
        return sorted({row.get("agent") for row in self._transcript_rows(run_id)
                       if row.get("agent")})

    def summary(self, run_id: str) -> dict:
        run = self._run_json(run_id)
        status = self._status(run_id)
        configs = self._configs(run_id)
        steps = max(0, len(configs) - 1)  # genesis is step 0
        state = status.get("state") or "done"  # no status.json => finished archive
        return {
            "id": run_id,
            "status": state,
            "live": state in LIVE_STATES,
            "steps": steps,
            "agents": self.agents(run_id),
            "config": run.get("spec", {}),
            "registry": run.get("registry"),
            "saved_at": run.get("saved_at") or status.get("heartbeat"),
        }

    def meta(self, run_id: str) -> dict:
        configs = self._configs(run_id)
        run = self._run_json(run_id)
        status = self._status(run_id)
        state = status.get("state") or "done"
        # The viewer's operator pill wants running/paused/stopped; map run-states.
        control = {"running": "running", "paused": "paused"}.get(state, "stopped")
        return {
            "id": run_id,
            "count": len(configs),
            "latest": len(configs) - 1,
            "agents": self.agents(run_id),
            "registry": run.get("registry", "registry" if any(
                "registry" in c.get("states", {}) for c in configs) else None),
            "control": control,
            "status": state,
            "live": state in LIVE_STATES,
            "config": run.get("spec", {}),
        }

    # ----------------------------------------------------------- read models

    def history(self, run_id: str) -> list[dict]:
        """Light snapshots ``[{step, states, arcs, traced}]`` — what the graph UI
        consumes (identical shape to the live hub's snapshots)."""
        if not self.exists(run_id):
            return []
        acted = self._acted_by_step(run_id)
        out = []
        for step, config in enumerate(self._configs(run_id)):
            out.append({
                "step": step,
                "states": config.get("states", {}),
                "arcs": config.get("arcs", {}),
                "traced": acted.get(step, []),
            })
        return out

    def snapshots_from(self, run_id: str, start: int) -> list[dict]:
        """Light snapshots for steps ``>= start`` — the incremental slice an SSE
        tailer sends as a live run grows (reads the files once, not per step)."""
        if not self.exists(run_id):
            return []
        start = max(0, start)
        acted = self._acted_by_step(run_id)
        out = []
        for step, config in enumerate(self._configs(run_id)):
            if step < start:
                continue
            out.append({
                "step": step,
                "states": config.get("states", {}),
                "arcs": config.get("arcs", {}),
                "traced": acted.get(step, []),
            })
        return out

    def snapshot(self, run_id: str, step: int) -> dict | None:
        hist = self.history(run_id)
        if 0 <= step < len(hist):
            return hist[step]
        return None

    def trace(self, run_id: str, step: int, agent: str) -> dict:
        """One agent's turn at one step (mirrors the live hub's ``/api/trace``)."""
        for row in self._transcript_rows(run_id):
            if int(row.get("step", -1)) == step and row.get("agent") == agent:
                return {"step": step, "vertex": agent, "messages": row.get("messages", [])}
        return {"step": step, "vertex": agent, "messages": []}

    def kernels(self, run_id: str) -> dict:
        """Code + latest error of every runtime-created object, keyed by vertex.

        Shape: ``{vertex: {"code": str, "error": str|None}}``. Prefers the live
        ``kernels.json`` (written every step by :class:`RunWriter`); falls back to
        the ``local_kernels`` code map folded into ``run.json`` on finish, so old
        archives (which predate ``kernels.json``) still surface their object code.
        """
        live = _read_json(self._dir(run_id) / KERNELS_FILE)
        if live:
            return live
        code_map = self._run_json(run_id).get("local_kernels") or {}
        return {v: {"code": code, "error": None} for v, code in code_map.items()}

    def conversation(self, run_id: str, agent: str) -> dict:
        """The agent's whole trajectory as one transcript.

        Each recorded turn is self-contained and begins with the same system
        prompt, so we lift the system message out once and strip the repeated
        leading system message from every turn. Turns are returned in step order.
        """
        rows = [r for r in self._transcript_rows(run_id) if r.get("agent") == agent]
        rows.sort(key=lambda r: int(r.get("step", 0)))
        system: str | None = None
        turns: list[dict] = []
        for row in rows:
            messages = list(row.get("messages", []))
            if messages and messages[0].get("role") == "system":
                if system is None:
                    system = messages[0].get("content")
                messages = messages[1:]
            turns.append({"step": int(row.get("step", 0)), "messages": messages})
        return {"agent": agent, "system": system, "turns": turns}
