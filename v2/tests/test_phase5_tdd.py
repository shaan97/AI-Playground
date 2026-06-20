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
    """Adds an arc to a fresh distinct target every step (out-degree grows)."""
    i = state.get("i", 0)
    return Step({"i": i + 1}, (AddArc(f"t{i}"),))


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
    config = Configuration(Digraph.of({"a": []}), {"a": {"i": 0}})
    gds = GraphDynamicalSystem(config, {"a": FunctionKernel(arc_grower)},
                               limits=Limits(max_out_degree=2))
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


if __name__ == "__main__":
    test_limits_defaults_unlimited()
    test_max_vertices_cap()
    test_no_limit_grows_unbounded()
    test_max_out_degree_cap()
    test_max_creations_per_step()
    test_creations_budget_resets_each_step()
    test_overbudget_does_not_crash_and_keeps_running()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
