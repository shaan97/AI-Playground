---
name: run-universe-viewer
description: Run, launch, screenshot, or drive the Universe phone viewer — the web app that visualizes the v2 graph dynamical simulation (the graph of vertices, per-vertex state, and agent traces). Use when asked to run/start/serve/open/screenshot/visualize the simulation, the world, the graph, or agent trajectories.
---

# Run the Universe viewer

A phone-first **web app** (under `v2/viewer/`) that visualizes a running
`GraphDynamicalSystem`: the directed graph of vertices, each vertex's state, and
agent turn-by-turn **traces**. It is a Python stdlib HTTP+SSE server (no deps)
serving a single Cytoscape.js page; the substrate stays untouched — the viewer
only observes.

It is driven headless by **`.claude/skills/run-universe-viewer/driver.mjs`**, a
zero-dependency Chrome DevTools Protocol script (Node ≥ 22's built-in
`WebSocket`). The driver checks the JSON API, launches headless Chrome/Edge,
waits for the graph to render, drives the real UI (selects the agent vertex and
opens its Trace tab), and writes three screenshots.

All paths below are relative to the repo root (`AI-Playground/`). Cytoscape loads
from a CDN, so **the machine needs internet** for the page to render.

## Prerequisites

- Python 3.11+ (stdlib only — nothing to install for the server).
- Node ≥ 22 (for the driver's built-in `WebSocket`). Verified: `node --version` → `v22.19.0`.
- Chrome or Edge. The driver autodetects the Windows install paths; override with
  `CHROME=<path>`.

## Run (agent path) — serve, then drive headless

Start a viewer. The demo world needs **no model** (its agent is a scripted
`LLMKernel`, so traces are still populated). It serves for ~minutes then idles:

```bash
python v2/examples/viewer_demo.py --steps 12 --delay 0.4 --port 8011
```

Run it in the background (it keeps serving after stepping finishes). Then drive it
+ screenshot:

```bash
node .claude/skills/run-universe-viewer/driver.mjs http://127.0.0.1:8011 _viewer_shots
```

Expected output (verified this session):

```
[api] meta: {"count":10,"latest":9,"agents":["agent"],"registry":"registry","control":"running"}
[api] history: 10 snapshots
[api] trace agent@9: 5 messages
[shot] _viewer_shots\01-graph.png
[shot] _viewer_shots\02-vertex-state.png
[ui] trace cards rendered: 5
[shot] _viewer_shots\03-agent-trace.png
[ui] after pause: runState=paused
[ui] step nav: start=182 sheetPrev=181 prevBtn=180 sheetNext=181
[shot] _viewer_shots\05-step-nav.png
[ui] after resume: runState=running
[ui] stop-confirm modal open: true
[shot] _viewer_shots\04-confirm-modal.png

PASS — viewer driven over CDP. Screenshots in _viewer_shots
```

Screenshots land in `_viewer_shots/` (phone-sized, 430×932 @2x):
`01-graph.png` (graph + transport ‹ ›), `02-vertex-state.png` (agent selected,
state tab), `03-agent-trace.png` (Trace tab — collapsible cards),
`05-step-nav.png` (in-sheet ‹ step N / M › nav, paused), `04-confirm-modal.png`
(the Stop "Are you sure?" modal). The driver also exercises the controls: it
pauses, steps through history with the in-sheet and transport arrows (asserting
the step index moves), resumes, and opens + cancels the Stop modal. **Open the
PNGs and confirm they aren't blank** before claiming success.

## Inspect the JSON API directly (no browser)

```bash
curl -s http://127.0.0.1:8011/api/meta
curl -s http://127.0.0.1:8011/api/trace/12/agent
```

Endpoints: `/api/meta`, `/api/history`, `/api/step/<i>`, `/api/trace/<i>/<vertex>`,
`/api/stream` (SSE: `hello`, a `step` per tick, a `control` on run-state change).

**Operator controls** (pause/resume/stop the live run remotely):

```bash
curl -s -X POST http://127.0.0.1:8011/api/control/pause
curl -s -X POST http://127.0.0.1:8011/api/control/resume
curl -s -X POST http://127.0.0.1:8011/api/control/stop
```

Each returns `{"state": "running"|"paused"|"stopped"}`. Stop ("Freeze") halts
stepping but keeps the server up for inspection. All checked *between* steps, so a
step never tears mid-flight. Unauthenticated — intended for a private tailnet.

**Shutdown** saves a resumable snapshot and exits the process:

```bash
curl -s -X POST http://127.0.0.1:8011/api/control/shutdown   # {"state":"shutting_down"}
```

By default the snapshot lands in `runs/<timestamp>` (relative to the server's CWD,
i.e. `v2/`); pass `serve_gds(..., save_dir=...)` or `--save <dir>` to choose. The
demo also save-on-halts when `--save` is given.

## Resume a saved run

```bash
python v2/examples/viewer_demo.py --resume v2/runs/<dir> --port 8016
```

Reloads the saved `Configuration` and continues stepping; history up to the resume
point is preserved (scrub it in the viewer). Use `--resume-step N` for an earlier
snapshot. Verified: a 54-step run shut down → resumed with `count: 55` and full
history. Programmatically: `resume_gds(build, "<dir>", step=-1)` then
`serve_gds(gds, ...)`.

## Run (human path) — open it on a phone/browser

```bash
python v2/examples/viewer_demo.py --delay 0.8 --port 8000
```

Open `http://localhost:8000` (or `http://<lan-ip>:8000` on the same wifi). For
remote/phone access over Tailscale, use the machine's MagicDNS name, e.g.
`http://<machine>.<tailnet>.ts.net:8000` (phone on the same tailnet; needs an
inbound firewall allow for the port on the Tailscale interface).

To visualize a **real LLM agent** instead of the scripted demo, the Gemma example
takes the same flag (requires a running Ollama):
`python v2/examples/gemma_world.py --viewer --steps 8 --delay 1.5`.

## Gotchas (battle scars, all hit this session)

- **`--screenshot` flag alone produces no file here.** Two reasons: (1) if Chrome
  is already running, a new `chrome.exe` invocation hands off to the existing
  process and ignores headless flags — the driver forces a separate instance with
  its own `--user-data-dir`. (2) `--virtual-time-budget` never settles because the
  viewer holds an SSE stream open, so the timed screenshot is never taken. The
  driver sidesteps both by using CDP `Page.captureScreenshot`, which captures on
  demand regardless of the live stream.
- **`Target.createTarget` with a size needs `newWindow: true`** in new headless,
  else it fails with "Target position can only be set for new windows".
- **`window.cy` / `window.App` are undefined.** The page uses `const cy`/`const App`
  in a *classic* script, so they are global *bindings* but not properties of
  `window`. Reference the bare identifiers behind `typeof` guards (the driver
  polls `typeof cy!=='undefined' ? cy.nodes().length : -1`).
- **Edges aren't blank lines.** Edge ids join source/target with a ``
  separator (never appears in vertex labels); don't "fix" that to an empty string.
- **Node colors must be hex, not `var(--…)`.** Cytoscape style values don't resolve
  CSS custom properties — a `var()` background silently falls back to gray.

## Troubleshooting

- `graph never rendered (state=…; CDN blocked / no internet?)` — the page loaded
  but Cytoscape never initialized. Check the machine can reach `unpkg.com`. The
  `state=` blob tells you whether the library (`lib`), graph (`n`), and history
  (`h`) were present.
- `viewer has no snapshots` — the server is up but the world isn't stepping;
  make sure you passed `--steps`/left it running, and hit `/api/meta` to confirm
  `count > 0`.
- `No Chrome/Edge found` — set `CHROME=<full path to chrome.exe or msedge.exe>`.
- `DevTools endpoint never came up` — port 9333 was busy or the browser failed to
  start; close stray headless Chrome processes and retry.
