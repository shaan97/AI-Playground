#!/usr/bin/env python3
"""A tiny world with a Gemma 4 agent, so you can watch it act in the substrate.

The world holds one **agent** vertex (a Gemma 4 `LLMKernel`) plus two inert,
deterministic objects — a `beacon` carrying a signal and a `note` carrying text.
A registry vertex makes the world discoverable: the agent observes the registry
(so it can read the ledger of identifiers), and from there it can attach to
things it didn't create and read their state, all through substrate effectors.

The agent acts only through the world's effectors (set_state / add_arc /
add_vertex) — substrate-only, no computer-use tools in this first version.

Requirements: a running Ollama (>= 0.22.0) with the model pulled, e.g.
    ollama pull gemma4

Run:
    python v2/examples/gemma_world.py --steps 6
    python v2/examples/gemma_world.py --model gemma4:26b --steps 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import (  # noqa: E402
    Configuration,
    Digraph,
    FunctionKernel,
    GraphDynamicalSystem,
    Limits,
    install_registry,
)
from gds.agents.ollama import gemma_agent  # noqa: E402

# Deliberately minimal: by default the agent gets NO system prompt at all. It
# sees only its own state and what it observes (the per-turn render) plus the
# tools it can call. The point of this first version is to watch what an agent
# does when told almost nothing. Pass --system "..." to give it guidance.
DEFAULT_SYSTEM = ""


def idle(state, inputs):
    return state


def build(model: str, url: str, system: str):
    config = Configuration(
        Digraph.of({"agent": [], "beacon": [], "note": []}),
        {
            "agent": {"notes": []},
            "beacon": {"signal": "the answer is 42"},
            "note": {"text": "hello from the note object"},
        },
    )
    kernels = {
        "agent": gemma_agent(model=model, url=url, system=system, max_rounds=6),
        "beacon": FunctionKernel(idle),
        "note": FunctionKernel(idle),
    }
    gds = GraphDynamicalSystem(config, kernels, limits=Limits(max_vertices=12, max_out_degree=16))
    install_registry(gds)
    return gds


def render(gds) -> str:
    dg = gds.config.digraph
    observes = sorted(dg.out_neighbours("agent"))
    state = gds.config.state_of("agent")
    others = sorted(v for v in gds.config.vertices() if v not in ("agent", "registry"))
    return (
        f"  agent.state = {json.dumps(state, ensure_ascii=False)}\n"
        f"  agent observes = {observes}\n"
        f"  world objects = {others}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="A tiny world with a Gemma 4 agent.")
    p.add_argument("--model", default="gemma4", help="Ollama model tag (default: gemma4)")
    p.add_argument("--url", default="http://127.0.0.1:11434", help="Ollama base URL")
    p.add_argument("--steps", type=int, default=6, help="number of world steps")
    p.add_argument("--system", default=DEFAULT_SYSTEM,
                   help="system prompt for the agent (default: none — minimal)")
    args = p.parse_args()

    gds = build(args.model, args.url, args.system)
    sys_note = "none (minimal)" if not args.system else repr(args.system[:60] + "...")
    print(f"World built (model={args.model}, system={sys_note}). Stepping {args.steps} times.\n")
    print("step 0 (genesis):")
    print(render(gds))
    for t in range(1, args.steps + 1):
        gds.step()
        print(f"\nstep {t}:")
        print(render(gds))

    print("\nDone. The full history is in gds.trajectory "
          f"({len(gds.trajectory)} configurations).")
    print("Tip: if nothing changed, check that Ollama is running and the model is pulled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
