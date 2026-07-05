"""Phase 5 TDD: engine-level resource guardrails (Limits). Stdlib-only.

Run as ``python v2/tests/test_phase5_tdd.py``. RED until GraphDynamicalSystem
enforces Limits.

Spec under test:
- gds.Limits(max_vertices=None, max_out_degree=None, max_creations_per_step=None)
  is a frozen dataclass; None means unlimited.
- GraphDynamicalSystem(config, kernels, limits=Limits(...)) enforces the caps when
  applying topology updates:
    * AddVertex is dropped once total vertices reach max_vertices;
    * AddVertex is dropped once max_creations_per_step have been made this step
      (counted across all actors);
    * AddArc is dropped once the actor's out-degree reaches max_out_degree.
  Over-budget updates are silently dropped (no crash); the system keeps running.
- With no limits (default), growth is unbounded.
"""

from __future__ import annotations

import sys
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
    Limits,
    Step,
    TransitionKernel,
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


def spawner(state, inputs):
    """Creates one fresh vertex every step, forever."""
    child = AddVertex(initial_state={}, kernel=FunctionKernel(idle))
    return Step(state, (child,))


def arc_grower(state, inputs):
    """Adds an arc to a real target each step, cycling over t0..t2 so out-degree
    grows toward the cap. Targets must exist (arcs are A ⊆ V×V), so the config
    that uses this fixture provides t0..t2."""
    i = state.get("i", 0)
    return Step({"i": i + 1}, (AddArc(f"t{i % 3}"),))


# ----------------------------------------------------------------- Limits type

def test_limits_defaults_unlimited():
    lim = Limits()
    check("Limits defaults are None (unlimited)",
          lim.max_vertices is None and lim.max_out_degree is None
          and lim.max_creations_per_step is None)


# -------------------------------------------------------------- max_vertices

def test_max_vertices_cap():
    config = Configuration(Digraph.of({"s": []}), {"s": {}})
    gds = GraphDynamicalSystem(config, {"s": FunctionKernel(spawner)},
                               limits=Limits(max_vertices=3))
    gds.run(10)
    n = len(gds.config.vertices())
    check("max_vertices caps total vertices", n == 3)


def test_no_limit_grows_unbounded():
    config = Configuration(Digraph.of({"s": []}), {"s": {}})
    gds = GraphDynamicalSystem(config, {"s": FunctionKernel(spawner)})
    gds.run(6)
    # 1 original + 6 created
    check("no limit -> unbounded growth", len(gds.config.vertices()) == 7)


# ------------------------------------------------------------- max_out_degree

def test_max_out_degree_cap():
    # t0..t2 exist so the arcs are legal; the out-degree cap (not existence) is
    # what limits growth.
    config = Configuration(
        Digraph.of({"a": [], "t0": [], "t1": [], "t2": []}),
        {"a": {"i": 0}, "t0": {}, "t1": {}, "t2": {}},
    )
    gds = GraphDynamicalSystem(
        config,
        {"a": FunctionKernel(arc_grower),
         **{t: FunctionKernel(idle) for t in ("t0", "t1", "t2")}},
        limits=Limits(max_out_degree=2),
    )
    gds.run(10)
    check("max_out_degree caps out-arcs", gds.config.digraph.out_degree("a") == 2)


# ------------------------------------------------------ max_creations_per_step

def test_max_creations_per_step():
    # Three spawners each emit one AddVertex in the same step; cap = 2.
    config = Configuration(
        Digraph.of({"a": [], "b": [], "c": []}),
        {"a": {}, "b": {}, "c": {}},
    )
    gds = GraphDynamicalSystem(
        config,
        {v: FunctionKernel(spawner) for v in ("a", "b", "c")},
        limits=Limits(max_creations_per_step=2),
    )
    before = len(gds.config.vertices())
    gds.step()
    created = len(gds.config.vertices()) - before
    check("max_creations_per_step caps per-step creations", created == 2)


def test_creations_budget_resets_each_step():
    config = Configuration(Digraph.of({"a": [], "b": []}), {"a": {}, "b": {}})
    gds = GraphDynamicalSystem(
        config,
        {v: FunctionKernel(spawner) for v in ("a", "b")},
        limits=Limits(max_creations_per_step=1),
    )
    gds.run(3)  # at most 1 creation per step -> 3 created over 3 steps
    created = len(gds.config.vertices()) - 2
    check("creation budget resets per step", created == 3)


# ------------------------------------------------------------- robustness

def test_overbudget_does_not_crash_and_keeps_running():
    config = Configuration(Digraph.of({"s": []}), {"s": {}})
    gds = GraphDynamicalSystem(config, {"s": FunctionKernel(spawner)},
                               limits=Limits(max_vertices=2))
    # Dropping over-budget AddVertex must not raise; state still evolves.
    gds.run(5)
    check("over-budget updates dropped without crashing", len(gds.config.vertices()) == 2)


# ------------------------------------------ arc existence invariant (A ⊆ V×V)

class _ArcThenWatch(TransitionKernel):
    """Emits an add_arc to `target` on its first step, then idles. Records any
    feedback the engine delivers via its `notify` hook."""

    def __init__(self, target):
        self.target = target
        self.notices: list = []
        self._acted = False

    def notify(self, reasons):
        self.notices.extend(reasons)

    def evaluate(self, state, inputs):
        if not self._acted:
            self._acted = True
            return Step(state, (AddArc(self.target),))
        return Step(state)


def test_add_arc_to_missing_vertex_refused():
    gds = GraphDynamicalSystem(
        Configuration(Digraph.of({"a": []}), {"a": {}}), {"a": _ArcThenWatch("ghost")})
    gds.step()  # 'a' tries to observe 'ghost', which does not exist
    check("arc to non-existent vertex is not created",
          "ghost" not in gds.config.digraph.out_neighbours("a"))


def test_arc_to_existing_vertex_still_works():
    k = _ArcThenWatch("b")
    gds = GraphDynamicalSystem(
        Configuration(Digraph.of({"a": [], "b": []}), {"a": {}, "b": {}}),
        {"a": k, "b": FunctionKernel(idle)})
    gds.step()
    check("arc to existing vertex is created (no refusal)",
          "b" in gds.config.digraph.out_neighbours("a") and k.notices == [])


def test_refusal_propagates_upward_to_kernel():
    k = _ArcThenWatch("ghost")
    gds = GraphDynamicalSystem(
        Configuration(Digraph.of({"a": []}), {"a": {}}), {"a": k})
    gds.step()   # emit the bad arc; refusal is queued, not yet delivered
    before = list(k.notices)
    gds.step()   # engine delivers the refusal to k.notify before 'a' acts again
    check("refusal is delivered on the next turn, naming the missing target",
          before == [] and any("ghost" in str(n) for n in k.notices))


def test_newborn_observe_arc_to_missing_is_filtered():
    def spawn_child(state, inputs):
        child = AddVertex(initial_state={}, kernel=FunctionKernel(idle),
                          out_arcs=frozenset({"a", "ghost"}), name="child")
        return Step(state, (child,))
    gds = GraphDynamicalSystem(
        Configuration(Digraph.of({"a": []}), {"a": {}}), {"a": FunctionKernel(spawn_child)})
    gds.step()
    outs = gds.config.digraph.out_neighbours("child")
    check("newborn keeps its real observe-arc and drops the non-existent one",
          "a" in outs and "ghost" not in outs)


if __name__ == "__main__":
    test_limits_defaults_unlimited()
    test_max_vertices_cap()
    test_no_limit_grows_unbounded()
    test_max_out_degree_cap()
    test_max_creations_per_step()
    test_creations_budget_resets_each_step()
    test_overbudget_does_not_crash_and_keeps_running()
    test_add_arc_to_missing_vertex_refused()
    test_arc_to_existing_vertex_still_works()
    test_refusal_propagates_upward_to_kernel()
    test_newborn_observe_arc_to_missing_is_filtered()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
