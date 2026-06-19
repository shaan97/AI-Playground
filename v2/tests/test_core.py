"""Core GDS tests: evolution, double-buffering, topology laws, record-replay.

Stdlib-only, runnable as ``python v2/tests/test_core.py`` (mirrors v1 style).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import (  # noqa: E402
    AddArc,
    AddVertex,
    Configuration,
    Digraph,
    FunctionKernel,
    GraphDynamicalSystem,
    Step,
    Trajectory,
)

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"ok: {name}")
    else:
        _FAIL += 1
        print(f"FAIL: {name}")


def idle(state, inputs):
    return state


# --------------------------------------------------------- evolution + buffering

def test_synchronous_double_buffer():
    """Two vertices each observing the other; n' = n + neighbour.n. Synchronous
    update means both read generation t, so they stay equal: 1 -> 2 -> 4 -> 8."""
    def grow(state, inputs):
        neighbour_sum = sum(s["n"] for s in inputs.values())
        return {"n": state["n"] + neighbour_sum}

    dg = Digraph.of({"a": ["b"], "b": ["a"]})
    config = Configuration(dg, {"a": {"n": 1}, "b": {"n": 1}})
    gds = GraphDynamicalSystem(config, {"a": FunctionKernel(grow), "b": FunctionKernel(grow)})
    gds.run(3)
    check("double-buffered evolution (a==b==8)",
          gds.config.state_of("a") == {"n": 8} and gds.config.state_of("b") == {"n": 8})


# ------------------------------------------------------------- topology updates

def test_add_arc_is_out_star_only():
    """AddArc adds only actor -> target; the reverse arc is never created."""
    def reach(state, inputs):
        if not state.get("linked"):
            return Step({"linked": True}, (AddArc("b"),))
        return state

    dg = Digraph.of({"a": [], "b": []})
    gds = GraphDynamicalSystem(
        Configuration(dg, {"a": {}, "b": {}}),
        {"a": FunctionKernel(reach), "b": FunctionKernel(idle)},
    )
    gds.step()
    out_a = gds.config.digraph.out_neighbours("a")
    out_b = gds.config.digraph.out_neighbours("b")
    check("AddArc creates a->b", "b" in out_a)
    check("AddArc does NOT create b->a (ownership)", "a" not in out_b)


def test_add_vertex_with_registry_coupling():
    """A spawner adds one vertex; registry coupling wires r <-> new vertex."""
    def spawn_once(state, inputs):
        if not state.get("done"):
            child = AddVertex(initial_state={"born": True}, kernel=FunctionKernel(idle))
            return Step({"done": True}, (child,))
        return state

    dg = Digraph.of({"r": [], "s": []})
    gds = GraphDynamicalSystem(
        Configuration(dg, {"r": {"ledger": []}, "s": {}}),
        {"r": FunctionKernel(idle), "s": FunctionKernel(spawn_once)},
        registry="r",
    )
    before = len(gds.config.vertices())
    gds.step()
    after = gds.config.vertices()
    new = [v for v in after if v not in ("r", "s")]
    check("one vertex created", len(after) == before + 1 and len(new) == 1)
    if new:
        w = new[0]
        dgr = gds.config.digraph
        check("registry coupling r->w", w in dgr.out_neighbours("r"))
        check("registry coupling w->r", "r" in dgr.out_neighbours(w))


# --------------------------------------------------------------- record-replay

def test_replay_roundtrip_and_determinism():
    def grow(state, inputs):
        return {"n": state["n"] + 1}

    def build():
        dg = Digraph.of({"a": []})
        return GraphDynamicalSystem(Configuration(dg, {"a": {"n": 0}}), {"a": FunctionKernel(grow)})

    run1 = build()
    run1.run(5)

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trajectory.jsonl"
        run1.trajectory.to_jsonl(path)
        reloaded = Trajectory.from_jsonl(path)
    check("trajectory round-trips through JSONL",
          [c.to_dict() for c in reloaded.snapshots] == [c.to_dict() for c in run1.trajectory.snapshots])

    run2 = build()
    run2.run(5)
    check("pure-kernel run is deterministic (re-run matches)",
          [c.to_dict() for c in run2.trajectory.snapshots] == [c.to_dict() for c in run1.trajectory.snapshots])


if __name__ == "__main__":
    test_synchronous_double_buffer()
    test_add_arc_is_out_star_only()
    test_add_vertex_with_registry_coupling()
    test_replay_roundtrip_and_determinism()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
