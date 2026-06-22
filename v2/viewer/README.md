# Universe viewer

A phone-first web viewer for the v2 graph dynamical substrate. Watch a
`GraphDynamicalSystem` evolve **live** (or scrub its **history**): see the graph,
tap a vertex to inspect its state and neighbourhood, and read an agent's per-turn
**trace**. Zero dependencies (stdlib `http.server` + Cytoscape.js from a CDN). The
viewer only *observes* the world — it never changes its dynamics.

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
