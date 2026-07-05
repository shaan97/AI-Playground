#!/usr/bin/env python3
"""Serve the Universe control plane — the website for the v2 substrate.

One long-lived server that outlives any individual run:

- **Runs index** — every experiment ever saved under ``runs/`` (live or archived).
- **Run view** — the graph, scrubbable history, per-step traces; live runs
  stream in over SSE.
- **Trajectory view** — an agent's whole run as one scrollable transcript
  (system prompt, then per step: reasoning, tool calls, tool results).
- **Launcher** — start new experiments from the browser (demo world, or Gemma
  agents via Ollama); a pool-limited supervisor runs each as a subprocess.

Run:
    python v2/serve.py                     # serves <repo>/runs on :8000
    python v2/serve.py --port 8010 --max-concurrent 2

Open the printed URL (phone-friendly; use Tailscale to reach it from anywhere).
Controls are unauthenticated — keep it on a private tailnet (see SAFETY-v2.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

V2 = Path(__file__).resolve().parent
sys.path.insert(0, str(V2))

from viewer.app import serve  # noqa: E402
from viewer.jobs import JobManager  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Serve the Universe control plane.")
    p.add_argument("--runs", default=None,
                   help="runs directory (default: <repo>/runs)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--max-concurrent", type=int, default=3,
                   help="max experiments running at once (default: 3)")
    args = p.parse_args()

    root = Path(args.runs) if args.runs else V2.parent / "runs"
    root.mkdir(parents=True, exist_ok=True)
    jobs = JobManager(root, max_concurrent=args.max_concurrent)
    serve(root, host=args.host, port=args.port, jobs=jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
