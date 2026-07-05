---
name: audit-runs
description: Audit and analyze saved Gemma-world runs — what the agents did over time, how their understanding evolved, whether they discovered/interacted with each other, what they created, and where the world converged. Use when asked to analyze/audit/investigate/inspect a run, an agent trajectory, agent behavior, or transcripts under runs/. Also covers producing a fresh traced run.
---

# Audit & analyze Gemma-world runs

A "run" is a saved trajectory of the v2 graph substrate (`runs/run-*/`), produced
when Gemma-4 agents act in a tiny world. Auditing one answers: what did the agents
do, how did their understanding evolve, did they discover/talk to each other, what
did they build, and did the world converge or deadlock.

The analysis is driven by **`.claude/skills/audit-runs/analyze_run.py`** — a
stdlib-only Python tool that turns a run directory into a structural + audit
report and extracts the agents' reasoning. **All paths below are relative to the
unit root `AI-Playground/`.** The driver path from there is the long but explicit
`.claude/skills/audit-runs/analyze_run.py`.

## What a run directory contains

```
runs/run-<ts>-viewer/
  trajectory.jsonl   one world-graph snapshot per step: {"states":{v:{...}}, "arcs":{v:[...]}}
  run.json           {"steps","registry","local_kernels":{v: behavior-code}, ...}
  transcripts.jsonl  ONE LINE per (step, agent) turn: the render it saw + its
                     assistant messages + tool calls. ONLY present if the run was
                     produced via the viewer harness (see "Produce a run" below).
```

The substrate persists only configurations, so **`transcripts.jsonl` is the only
window into the agents' actual reasoning.** Without it you can still audit a lot:
the `status`/`analysis` strings agents write via `set_state` are their own words
and double as a cheap cognitive trace.

## Prerequisites

- Python 3.11+ (stdlib only — nothing to install). Verified with pyenv 3.13.5.
- Producing a *new* run additionally needs a running **Ollama** with a tool-capable
  model pulled (`gemma4`): `curl -s http://127.0.0.1:11434/api/tags` should list it.

## Audit an existing run (agent path) — start here

Full report (summary of creations + audit findings + per-step evolution):

```bash
python .claude/skills/audit-runs/analyze_run.py runs/run-20260621-174845-viewer
```

The high-signal sections on their own:

```bash
python .claude/skills/audit-runs/analyze_run.py runs/run-20260621-174845-viewer --audit
python .claude/skills/audit-runs/analyze_run.py runs/run-20260621-174845-viewer --summary
python .claude/skills/audit-runs/analyze_run.py runs/run-20260621-174845-viewer --evolution
```

`--audit` reports the things that matter and are easy to miss:

- **STRUCTURAL CONVERGENCE** — last step the *topology* changed (new vertex / arc
  rewiring), vs. steps that only reworded agent state. A world that "freezes" at
  step 6 but runs to 93 spent 87 steps paraphrasing one conclusion.
- **PHANTOM ARCS** — agents observing names that aren't real vertices (e.g.
  `AxiomEngine` when the substrate minted `v3`). Signals the agent's mental model
  drifted off the actual graph.
- **CREATED VERTICES** — and whether each is *inert* (state never changed) and
  whether its behavior code is JS/pseudocode the Python sandbox can't run.
- **PEER OBSERVATION** — did any agent ever observe another (how they "discover"
  each other: by reading the registry ledger, not by perceiving action). There is
  no message primitive — all coordination is stigmergic (reading each other's state).
- **SIGNAL SPREAD** — how far the beacon `42` / note text propagated into agent state.
- **LATE NOVELTY** — mean word-overlap between consecutive agent states in the tail;
  ≥0.5 means "paraphrasing one conclusion" (converged), low means still exploring.
- **PER-AGENT TOOL ACTIVITY** — `set_state`/`add_arc`/`add_vertex` counts per agent
  (needs transcripts).

Read the agents' **actual reasoning** for specific turns — `STEP:AGENT` pairs
(skips the system/user render, shows assistant text + tool calls):

```bash
python .claude/skills/audit-runs/analyze_run.py runs/run-20260621-174845-viewer --trace 2:agent2 7:agent1 17:agent1
python .claude/skills/audit-runs/analyze_run.py runs/run-20260621-174845-viewer --trace-all   # every turn
```

Runs **without** `transcripts.jsonl` (older runs like `runs/run-20260621-165344`)
still work for everything except `--trace*`; the tool prints a note and skips.

## Produce a fresh traced run (so it has transcripts)

Plain `gemma_world.py` only prints and saves nothing; the **viewer** harness saves
`trajectory.jsonl` + `run.json` + `transcripts.jsonl` (the last via
`ViewerHub.save_traces`, wired into `serve_gds`'s save path). Launch it headless,
let it step, and it auto-saves on completion because `--save-dir` is given:

```bash
SYS="You are a vertex in a world of objects. Each turn you are shown your own state and the states you observe. Act through the provided tools: call set_state to update your own state (your memory), add_arc/remove_arc to choose what you observe, and add_vertex to create a new thing. When you are finished, stop calling tools."
TS=$(date +%Y%m%d-%H%M%S)
python v2/examples/gemma_world.py --viewer --agents 2 --steps 45 --delay 0 \
    --port 8771 --system "$SYS" --save-dir "runs/run-$TS-viewer" > runs/_viewer.log 2>&1 &
```

It serves while stepping (~8 s/step for gemma4:8b). Watch progress and wait for the
save, then stop the still-serving process (it idles for inspection after stepping):

```bash
curl -s http://127.0.0.1:8771/api/meta          # {"count":N+1,...} -> N steps done
until [ -f runs/run-$TS-viewer/transcripts.jsonl ]; do sleep 5; done   # save landed
# then kill it: find the python PID for port 8771 and stop it (Windows: taskkill //F //PID <pid>)
```

Then audit it with the commands above. **`--system` is mandatory**: with the
`gemma_world` default empty prompt the agents behave like a passive chatbot
("standing by for a task") and the world never changes — see Gotchas.

**Conversation continuity** is controlled by `--continuous` (default) / `--no-continuous`:
- `--continuous` (default): each agent keeps ONE running conversation across steps,
  so it directly remembers prior turns (memory lives in the dialogue). Context grows
  every step — watch the model's window on long runs.
- `--no-continuous`: every step is a fresh conversation rebuilt only from the agent's
  own `state` (the substrate's stateless-between-turns default). Runs saved before
  this flag existed are effectively `--no-continuous`.

## Gotchas (learned the hard way)

- **Empty system prompt = dead world.** `gemma_world.py`'s `DEFAULT_SYSTEM` is `""`.
  With no prompt, gemma4 narrates what it sees and asks "how can I help?" — it never
  calls tools, so nothing happens. You must pass `--system` (the substrate's own
  `gds/agents/llm.py:DEFAULT_SYSTEM`, reproduced above, works well).
- **Transcripts are not saved by default anywhere except the viewer save path.**
  Plain `gemma_world.py` prints only; `persistence.save_run` writes trajectory +
  run.json but NOT reasoning. The reasoning lives in `ViewerHub._traces` and is only
  persisted by `ViewerHub.save_traces` (called from `serve_gds._save`). Older runs
  predating that have no `transcripts.jsonl`.
- **"Created a thing" ≠ "built a working thing."** Agents write behavior code as
  JS/pseudocode; the substrate sandbox runs restricted Python, so those `on_tick`
  bodies don't execute and the vertices stay inert. `--audit` flags this.
- **Agents lose the name→id mapping.** They refer to creations by the name in their
  own state (`AxiomEngine`) while the substrate minted `v1/v2/v3`, producing phantom
  observation arcs. Don't read a phantom arc as a real edge.
- **"Topology still changing at the final step" can still be converged.** Agents
  fidget with arcs late while only rewording their conclusion; cross-check
  STRUCTURAL CONVERGENCE against LATE NOVELTY (word-overlap) before calling it.
- **Windows console is cp1252.** The driver forces `sys.stdout.reconfigure("utf-8")`
  so em-dashes in agent text don't mojibake; keep that if you edit it.

## Troubleshooting

- `--trace` prints "(no transcripts.jsonl ...)" — the run predates transcript
  persistence; produce a new run via the viewer path, or audit it without `--trace`.
- New run never changes (every step identical in `--evolution`) — you forgot
  `--system`, or Ollama isn't running / the model lacks tool support
  (`curl http://127.0.0.1:11434/api/tags`).
- The viewer process keeps running after stepping — that's by design (it idles
  serving for inspection); kill it once `transcripts.jsonl` exists, or POST
  `/api/control/shutdown` to make it save-and-exit.
