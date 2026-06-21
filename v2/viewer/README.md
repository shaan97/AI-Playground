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
  its full state (pretty-printed JSON). Tap a neighbour chip to jump to it.
- **Trace tab** (agents only) — the selected step's turn as collapsible cards:
  system / user (what it saw) / assistant (reasoning + tool calls) / tool results.
- **Transport bar** — scrub the timeline, ▶ to play through history, **LIVE** to
  snap to the newest step and follow in real time.

## HTTP API

| Endpoint | Returns |
|---|---|
| `GET /` | the single-page viewer |
| `GET /api/meta` | `{count, latest, agents, registry}` |
| `GET /api/history` | `[snapshot, …]` (light: `states`, `arcs`, `traced`) |
| `GET /api/step/<i>` | one snapshot |
| `GET /api/trace/<i>/<vertex>` | that agent's turn transcript at step `i` |
| `GET /api/stream` | SSE: a `hello` (meta) event then a `step` event per step |
