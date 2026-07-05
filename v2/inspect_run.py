#!/usr/bin/env python3
"""Quick script to inspect what vertices were created and their code."""

from gds import Configuration, Digraph, FunctionKernel, GraphDynamicalSystem, LLMKernel, Limits, install_registry
from gds.agents.ollama import gemma_agent
from gds.kernel import LocalKernel
import json

# Rebuild the same L4 setup
PROMPT_LEVELS = {
    0: "",
    1: "You are an object in a world of objects. Each turn you see your own state and the states of the objects you observe, and you may act with the tools provided. Everything else is yours to figure out.",
    2: """You are one object in a world made only of objects. Time advances in discrete turns.

Each turn you are shown your own state and the states of the objects you currently observe, and you act by calling tools:
- set_state: replace your own state. This is your only memory across turns, and it is the only thing other objects can perceive about you.
- add_arc / remove_arc: choose what you observe. Observing is one-way and silent — the target is neither asked nor notified, and it cannot see you unless it observes you back.
- add_vertex: create a new object with its own behaviour (Python transition code).

You do not see the whole world — only what you observe. To discover what else exists, read the registry: it is an object you already observe whose state is a ledger of identifiers for every object in the world. Pick an identifier from the ledger and add_arc to it to start reading that object's state.

Nothing is ever pushed to you: you are changed only by objects you choose to observe. When you have nothing more to do this turn, stop calling tools."""
}

def idle(state, inputs):
    return state

gds = GraphDynamicalSystem(
    Configuration(Digraph.of({"agent": []}), {"agent": {}}),
    {"agent": gemma_agent(system=PROMPT_LEVELS[2], max_rounds=6, continuous=True)},
    limits=Limits(max_vertices=64, max_out_degree=32, max_creations_per_step=4),
)
install_registry(gds)

for i in range(10):
    gds.step()

print("=== FINAL WORLD STATE ===")
print(f"Total vertices: {len(list(gds.config.vertices()))}")
print(f"Agent state: {gds.config.state_of('agent')}")
print(f"\n=== CREATED VERTICES (those without kernel yet) ===")

for v in sorted(gds.config.vertices()):
    if v in ["agent", "registry", "beacon", "note"]:
        continue
    kernel = gds.kernels.get(v)
    state = gds.config.state_of(v)
    if isinstance(kernel, LocalKernel):
        print(f"\n{v}:")
        print(f"  State: {json.dumps(state, default=str)}")
        print(f"  Code (first 300 chars):\n{kernel.code[:300]}")
        if kernel.last_error:
            print(f"  Last error: {kernel.last_error}")
    else:
        print(f"{v}: {type(kernel).__name__}")

print(f"\n=== TRAJECTORY ===")
print(f"Total steps: {len(gds.trajectory)}")
