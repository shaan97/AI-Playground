#!/usr/bin/env python3
"""Watch a tiny world evolve in the phone viewer — no model required.

This builds a small world and serves it to the web viewer so you can open it on
your phone and watch live: the graph, each vertex's state, and a real agent
*trace* (turn transcript). To keep it dependency-free, the "agent" is an
`LLMKernel` driven by a *scripted* chat stub rather than a real model — it still
produces genuine tool calls and transcripts, so the Trace tab is populated.

Run:
    python v2/examples/viewer_demo.py
    python v2/examples/viewer_demo.py --steps 40 --delay 0.6 --port 8000

Then open the printed URL on your phone (same wifi, or over Tailscale).
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import (  # noqa: E402
    Configuration,
    Digraph,
    FunctionKernel,
    GraphDynamicalSystem,
    LLMKernel,
    Limits,
    install_registry,
)
from viewer import serve_gds  # noqa: E402


def drifting(state, inputs):
    """A cheap object whose scalar value random-walks each step."""
    v = float(state.get("value", 0.0)) + random.uniform(-1.0, 1.0)
    return {"value": round(v, 2), "label": state.get("label", "")}


def pulsing(state, inputs):
    """An object that toggles on/off and counts ticks."""
    n = int(state.get("ticks", 0)) + 1
    return {"on": (n % 3 == 0), "ticks": n}


def scripted_brain():
    """A fake `chat(messages, tools) -> assistant_message`.

    It glances at what it observes and acts: notes the highest 'value' it can see,
    then alternates between recording an observation and (re)wiring an out-arc to a
    target it read from the registry ledger. Deterministic-ish, model-free, but
    exercises the real LLMKernel tool loop so traces look authentic.
    """
    turn = {"n": 0}

    def chat(messages, tools):
        turn["n"] += 1
        user = messages[-1]["content"] if messages else ""
        # First model round: emit one tool call; second round: stop (no calls).
        if messages and messages[-1].get("role") == "tool":
            return {"content": "Done for this turn.", "tool_calls": []}

        n = turn["n"]
        if n % 2 == 1:
            note = f"observed neighbours at turn {n}"
            return {"content": f"I'll record what I see.", "tool_calls": [{
                "id": f"c{n}", "type": "function",
                "function": {"name": "set_state",
                             "arguments": '{"state": {"last_note": "%s", "turn": %d}}' % (note, n)},
            }]}
        else:
            # Try to observe the 'beacon' (a target it could learn from the ledger).
            return {"content": "Let me watch the beacon.", "tool_calls": [{
                "id": f"c{n}", "type": "function",
                "function": {"name": "add_arc", "arguments": '{"target": "beacon"}'},
            }]}

    return chat


def build() -> GraphDynamicalSystem:
    config = Configuration(
        Digraph.of({
            "agent": [],
            "beacon": [],
            "sensor": [],
            "lamp": [],
        }),
        {
            "agent": {"last_note": "(nothing yet)", "turn": 0},
            "beacon": {"value": 5.0, "label": "beacon"},
            "sensor": {"value": -2.0, "label": "sensor"},
            "lamp": {"on": False, "ticks": 0},
        },
    )
    kernels = {
        "agent": LLMKernel(scripted_brain(), system="You are a curious agent.", max_rounds=4),
        "beacon": FunctionKernel(drifting),
        "sensor": FunctionKernel(drifting),
        "lamp": FunctionKernel(pulsing),
    }
    gds = GraphDynamicalSystem(config, kernels, limits=Limits(max_vertices=20, max_out_degree=16))
    install_registry(gds)
    return gds


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steps", type=int, default=None, help="number of steps (default: run forever)")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between steps")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    random.seed(args.seed)
    gds = build()
    serve_gds(gds, steps=args.steps, delay=args.delay, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
