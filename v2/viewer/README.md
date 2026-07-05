# Universe viewer & control plane

A phone-first website for the v2 graph dynamical substrate. Zero dependencies
(stdlib `http.server` + Cytoscape.js from a CDN). Two ways to use it:

1. **The control plane** (`v2/serve.py`) — one long-lived server that outlives
   any run: browse every experiment, watch live ones, read whole trajectories,
   and **launch new experiments from the browser**.
2. **The single-run viewer** (`serve_gds`) — bolt a viewer onto one in-process
   run, as before (still used by `gemma_world.py --viewer`).

Either way the viewer only *observes* the world — it never changes its dynamics;
operator control (pause/stop) acts strictly *between* steps.

## The control plane

```bash
python v2/serve.py                     # serves <repo>/runs on :8000
python v2/serve.py --port 8010 --max-concurrent 2
```

**Everything is a run directory.** `runs/<id>/` holds `trajectory.jsonl` (one
configuration per step), `transcripts.jsonl` (one row per agent turn),
`kernels.json` (`{vertex: {code, error}}` for every runtime-created object, so
the viewer can show an object's source and its latest transition error),
`run.json` (launch spec + resume metadata) and `status.json`
(queued/running/paused/done/stopped/crashed + heartbeat). A *live* run is just a
directory that is still growing — the server tails it over SSE; an archived run
is read by the same code. The server is restart-tolerant: on startup it
re-enqueues `queued` runs and marks stale `running` ones `crashed`.

**Pages:**

- **Runs index** (`#/`) — a gallery of every run: status badge, steps, world
  config, agents. Plus **＋ New experiment**.
- **Run view** (`#/run/<id>`) — the familiar graph: scrub history, follow live,
  tap a vertex for state/neighbourhood/per-step trace, pause/stop the run.
- **Trajectory** (`#/run/<id>/trajectory`) — an agent's **whole run as one
  scrollable transcript**: the system prompt once, then per step its
  observations, reasoning (shown italic), tool calls and tool results. Tap a
  step divider to jump to that step in the graph.

**Launcher.** The form maps onto `examples/gemma_world.py`'s flags: world kind
(`demo` = model-free scripted world, `gemma` = real Ollama agents), model, #
agents, prompt level L0–L4 or a custom system prompt, bare/continuous, steps,
delay. Launching spawns a **worker subprocess** (`python -m viewer.worker
<run_dir>`) supervised by a pool (`JobManager`, default 3 concurrent; extra
launches queue). Workers append to their run dir every step, so you can watch
live, and honour `control.json` (pause/resume/stop) between steps.

### Control-plane HTTP API

| Endpoint | Returns |
|---|---|
| `GET /` | the single-page app |
| `GET /api/runs` | newest-first run summaries |
| `POST /api/runs` `{spec}` | launch: `201 {id, status}` |
| `GET /api/runs/<id>/meta` | `{count, latest, agents, registry, control, status, config}` |
| `GET /api/runs/<id>/history` | `[{step, states, arcs, traced}, …]` |
| `GET /api/runs/<id>/step/<i>` | one snapshot |
| `GET /api/runs/<id>/trace/<i>/<agent>` | that agent's turn at step *i* |
| `GET /api/runs/<id>/conversation/<agent>` | `{agent, system, turns}` — the whole trajectory |
| `GET /api/runs/<id>/kernels` | `{vertex: {code, error}}` — runtime-created objects' source + latest error |
| `GET /api/runs/<id>/stream?from=N` | SSE: `hello`, then `step` / `control` events |
| `POST /api/runs/<id>/control/pause·resume·stop` | `{state}` |

Tests: `python v2/tests/test_viewer_runs_tdd.py` (read models),
`test_viewer_app_tdd.py` (HTTP surface), `test_viewer_jobs_tdd.py` (supervisor).

## The single-run viewer (`serve_gds`)

Watch a `GraphDynamicalSystem` evolve **live** (or scrub its **history**): see
the graph, tap a vertex to inspect its state and neighbourhood, and read an
agent's per-turn **trace**.

## Try it (no model needed)

```bash
python v2/examples/viewer_demo.py          # runs forever, ~1 step/sec
python v2/examples/viewer_demo.py --steps 40 --delay 0.6 --port 8000
```

It prints the URLs to open. The demo's "agent" is an `LLMKernel` driven by a
scripted stub, so the **Trace** tab is populated without needing Ollama.

## Use it on your own world

```python
from viewer import serve_gds

gds = build_my_world()          # any GraphDynamicalSystem
serve_gds(gds, steps=50, delay=1.0, port=8000)
```

`serve_gds` instruments every `LLMKernel` agent for tracing, starts the server in
a background thread, prints the URLs, then runs the step loop. For finer control,
use `start_server(hub)` + `hub.publish(gds)` yourself (see `server.py`).

## Open it on your phone

- **Same wifi:** open `http://<machine-lan-ip>:<port>` (printed on start).
- **Anywhere (recommended):** put your machine and phone on the same
  [Tailscale](https://tailscale.com) tailnet, then open
  `http://<machine>.<tailnet>.ts.net:<port>` — works over cellular, nothing
  exposed publicly. This matters because the world runs untrusted agent code.
- **Public tunnel** (ngrok / `cloudflared`) also works but exposes the viewer to
  the internet; add auth if you go this route.

## UI

- **Graph** — force-directed; agents (blue), objects (teal), registry (purple).
  An arc `X → Y` means *X observes Y*. A vertex outlined in green *acted this
  step* (an agent took a turn). Node size grows with in-degree (how observed it
  is).
- **Tap a vertex** — bottom sheet with what it *observes*, what *observes it*, and
  its full state (pretty-printed JSON). Tap a neighbour chip to jump to it. The
  sheet has its own **‹ step N / M ›** arrows so you can move through history while
  staying on the same vertex (state and trace update with each step).
- **Trace tab** (agents only) — the selected step's turn as collapsible cards:
  system / user (what it saw) / assistant (reasoning + tool calls) / tool results.
- **Transport bar** — **‹ ›** step one tick back/forward, scrub the timeline, ▶ to
  play through history, **LIVE** to snap to the newest step and follow live.
  (Arrow keys ←/→ also step.)
- **Operator controls** (top bar) — a run-state pill plus **⏸ Pause/Resume** and
  **⏹ Stop**. The Stop button opens an "Are you sure?" modal offering **Freeze run**
  (halt stepping, keep the viewer up for inspection) or **Save & shut down** (write
  a resumable snapshot and exit the process). State is broadcast over SSE, so
  acting from your phone updates every open tab.

## Intervening in a running world

The viewer can pause, stop, or shut down the live run remotely — an **operator**
capability that lives entirely in the viewer (the substrate stays pure). All
checks happen *between* steps, so a step never tears mid-flight. Controls are
unauthenticated by default — fine on a private tailnet, where only your own
devices can reach the viewer.

- **Pause/Resume** — freeze stepping and continue later (the world holds).
- **Freeze (Stop)** — halt stepping; the server keeps serving the final state.
- **Save & shut down** — persist a snapshot, then exit the process.

```python
serve_gds(gds, delay=1.0, save_dir="runs/my-run")   # save on halt + shutdown
```

## Resuming a run

A snapshot stores **state + wiring** (a `Configuration`), not the transition
functions — so resume reloads the saved configuration and gets kernels back from
the world's `build()` (genesis vertices) plus persisted `LocalKernel` code
(runtime-created vertices). An agent's *memory* is in its vertex state, so it's
restored; its *model* comes from `build()`.

```python
from viewer import resume_gds, serve_gds

gds = resume_gds(build, "runs/my-run", step=-1)  # -1 = last snapshot; any index works
serve_gds(gds, delay=1.0)                         # keep stepping from there
```

The demo wires this to flags: `python v2/examples/viewer_demo.py --resume runs/my-run`
(optionally `--resume-step N`). History up to the resume point is preserved, so
you can still scrub it in the viewer.

## HTTP API

| Endpoint | Returns |
|---|---|
| `GET /` | the single-page viewer |
| `GET /api/meta` | `{count, latest, agents, registry, control}` |
| `GET /api/history` | `[snapshot, …]` (light: `states`, `arcs`, `traced`) |
| `GET /api/step/<i>` | one snapshot |
| `GET /api/trace/<i>/<vertex>` | that agent's turn transcript at step `i` |
| `GET /api/stream` | SSE: `hello` (meta), a `step` per step, a `control` on run-state change |
| `POST /api/control/pause` · `/resume` · `/stop` | `{state}` — operator run control |
| `POST /api/control/shutdown` | `{state: "shutting_down"}` — save a snapshot and exit the process |
