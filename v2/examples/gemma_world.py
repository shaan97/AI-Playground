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
    LLMKernel,
    Limits,
    install_registry,
)
from gds.kernel import LocalKernel  # noqa: E402
from gds.agents.ollama import gemma_agent  # noqa: E402

# Graded system prompts (L0..L4), for an ablation: give the agent everything,
# then strip it down to find the minimal prompt that still yields interesting
# behaviour. The axis stripped is *information about how the world works*, split
# into "mechanics" (the physics/affordances — what the tools do, how perception
# and discovery work) and "content" (examples, goals, hints). The bet is that
# mechanics is load-bearing and content is not; L2 gives mechanics only.
#
#   L0  nothing at all (raw JSON render + tool specs; the original default)
#   L1  one line of orientation
#   L2  full mechanics, no examples or goals
#   L3  mechanics + one worked example
#   L4  mechanics + example + an explicit goal and an other-minds hint
#
# Choose with --level N; --system "..." overrides the ladder entirely.

_L1 = (
    "You are an object in a world of objects. Each turn you see your own state "
    "and the states of the objects you observe, and you may act with the tools "
    "provided. Everything else is yours to figure out."
)

_MECHANICS = (
    "You are one object in a world made only of objects. Time advances in "
    "discrete turns.\n\n"
    "Each turn you are shown your own state and the states of the objects you "
    "currently observe, and you act by calling tools:\n"
    "- set_state: replace your own state. This is your only memory across turns, "
    "and it is the only thing other objects can perceive about you.\n"
    "- add_arc / remove_arc: choose what you observe. Observing is one-way and "
    "silent — the target is neither asked nor notified, and it cannot see you "
    "unless it observes you back.\n"
    "- add_vertex: create a new object with its own behaviour (Python transition "
    "code). Give it a short name (e.g. \"logger\") — that becomes its identifier "
    "in the registry so you can find and read it on later turns.\n\n"
    "You do not see the whole world — only what you observe. To discover what "
    "else exists, read the registry: it is an object you already observe whose "
    "state is a ledger of identifiers for every object in the world. Pick an "
    "identifier from the ledger and add_arc to it to start reading that object's "
    "state.\n\n"
    "Nothing is ever pushed to you: you are changed only by objects you choose "
    "to observe. When you have nothing more to do this turn, stop calling tools."
)

_EXAMPLE = (
    "\n\nWorked example — coordinating with nothing but state and observation. "
    "Say two objects want to pass a token. Object A holds {\"token\": true} in "
    "its state; object B observes A. On B's turn it reads A's state, and seeing "
    "the token, calls set_state to record {\"token\": true}; next turn A (which "
    "observes B) sets its own token false. The \"hand-off\" is just each object "
    "reading the other's state and updating its own — there is no message or "
    "transfer primitive, and none is needed. Roles, goals, games, whole "
    "ecosystems are all built the same way: state that others read, plus new "
    "objects you create."
)

_GUIDANCE = (
    "\n\nSome objects out there may be other minds — objects driven by an agent "
    "like you. Nothing labels which; you can only infer it by observing one over "
    "time and seeing whether it responds. Your aim: explore what exists and make "
    "something interesting happen. Discover other objects, and if any seem to be "
    "minds, try to interact — remember that for another object to react to you it "
    "must observe you, so the way to invite interaction is to make your own state "
    "worth reading. There is no win condition; act with intent rather than "
    "waiting to be told what to do."
)

PROMPT_LEVELS = {
    0: "",
    1: _L1,
    2: _MECHANICS,
    3: _MECHANICS + _EXAMPLE,
    4: _MECHANICS + _EXAMPLE + _GUIDANCE,
}

DEFAULT_SYSTEM = PROMPT_LEVELS[0]


def idle(state, inputs):
    return state


def agent_names(n: int) -> list[str]:
    return ["agent"] if n == 1 else [f"agent{i + 1}" for i in range(n)]


def build(model: str, url: str, system: str, *, objects: bool = True, n_agents: int = 1,
          continuous: bool = True):
    # Each agent starts blank — a true blank slate. install_registry adds the
    # registry vertex and couples every agent <-> registry, so agents can discover
    # each other (and anything else) only through the registry's ledger.
    agents = agent_names(n_agents)
    adjacency: dict = {a: [] for a in agents}
    states: dict = {a: {} for a in agents}
    kernels = {a: gemma_agent(model=model, url=url, system=system, max_rounds=6,
                              continuous=continuous) for a in agents}
    if objects:
        adjacency.update({"beacon": [], "note": []})
        states.update({
            "beacon": {"signal": "the answer is 42"},
            "note": {"text": "hello from the note object"},
        })
        kernels["beacon"] = FunctionKernel(idle)
        kernels["note"] = FunctionKernel(idle)
    gds = GraphDynamicalSystem(
        Configuration(Digraph.of(adjacency), states),
        kernels,
        # Generous but bounded: a lone agent may populate the world via add_vertex
        # over an unlimited run; these caps prevent runaway growth.
        limits=Limits(max_vertices=64, max_out_degree=32, max_creations_per_step=4),
    )
    install_registry(gds)
    return gds


def render(gds) -> str:
    dg = gds.config.digraph
    agents = sorted(v for v, k in gds.kernels.items() if isinstance(k, LLMKernel))
    lines = []
    for a in agents:
        lines.append(f"  {a}.state = {json.dumps(gds.config.state_of(a), ensure_ascii=False)}")
        lines.append(f"  {a} observes = {sorted(dg.out_neighbours(a))}")
    others = sorted(v for v in gds.config.vertices() if v not in agents and v != "registry")
    lines.append(f"  world objects = {others}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="A tiny world with a Gemma 4 agent.")
    p.add_argument("--model", default="gemma4", help="Ollama model tag (default: gemma4)")
    p.add_argument("--url", default="http://127.0.0.1:11434", help="Ollama base URL")
    p.add_argument("--steps", type=int, default=6, help="number of world steps (0 = unlimited)")
    p.add_argument("--bare", action="store_true",
                   help="empty universe: only the agent(s) and the registry (no objects)")
    p.add_argument("--agents", type=int, default=1, help="number of Gemma agents (default: 1)")
    p.add_argument("--level", type=int, default=0, choices=range(5),
                   help="how much to tell the agent about the world, 0..4 "
                        "(0=nothing, 2=mechanics only, 4=mechanics+example+goal). "
                        "See PROMPT_LEVELS. Ignored if --system is given.")
    p.add_argument("--system", default=None,
                   help="explicit system prompt; overrides --level entirely")
    p.add_argument("--viewer", action="store_true",
                   help="serve the phone web viewer and watch the run live")
    p.add_argument("--port", type=int, default=8000, help="viewer port (with --viewer)")
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds between steps when serving the viewer")
    p.add_argument("--save-dir", default=None,
                   help="with --viewer, persist trajectory + transcripts here on halt")
    p.add_argument("--continuous", action=argparse.BooleanOptionalAction, default=True,
                   help="keep ONE running conversation across steps (default); "
                        "use --no-continuous for a fresh conversation each step "
                        "(memory only via the agent's own state)")
    args = p.parse_args()

    # --system wins if given; otherwise the prompt is chosen by --level.
    system = args.system if args.system is not None else PROMPT_LEVELS[args.level]

    steps = None if args.steps <= 0 else args.steps  # None = unlimited
    gds = build(args.model, args.url, system, objects=not args.bare,
                n_agents=args.agents, continuous=args.continuous)
    if args.system is not None:
        sys_note = repr(args.system[:60] + ("..." if len(args.system) > 60 else ""))
    elif system:
        sys_note = f"L{args.level} ({len(system)} chars)"
    else:
        sys_note = f"L{args.level} (none — minimal)"
    world_note = (f"bare ({args.agents} agent(s) + registry)" if args.bare
                  else f"{args.agents} agent(s) + objects")

    if args.viewer:
        # Hand the world to the web viewer: it instruments the agent for tracing,
        # serves the UI, and runs the step loop live. Open the printed URL on your
        # phone (same wifi, or over Tailscale from anywhere).
        from viewer import serve_gds
        print(f"World built ({world_note}, model={args.model}, system={sys_note}). Serving the viewer.")
        serve_gds(gds, steps=steps, delay=args.delay, port=args.port, save_dir=args.save_dir)
        return 0

    print(f"World built ({world_note}, model={args.model}, system={sys_note}). "
          f"Stepping {'unlimited' if steps is None else steps} times.\n")
    print("step 0 (genesis):")
    print(render(gds))

    created_vertices = set()
    t = 0
    while steps is None or t < steps:
        gds.step()
        t += 1
        print(f"\nstep {t}:")
        print(render(gds))
        # Show any newly created vertices and their code
        now_vertices = set(gds.config.vertices())
        new_vertices = now_vertices - created_vertices - {"agent", "registry", "beacon", "note"}
        for v in sorted(new_vertices):
            kernel = gds.kernels.get(v)
            if isinstance(kernel, LocalKernel):
                print(f"  [created {v}] code (first 150 chars): {kernel.code[:150].replace(chr(10), ' ')}...")
        created_vertices = now_vertices

    print("\nDone. The full history is in gds.trajectory "
          f"({len(gds.trajectory)} configurations).")
    print("Tip: if nothing changed, check that Ollama is running and the model is pulled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
