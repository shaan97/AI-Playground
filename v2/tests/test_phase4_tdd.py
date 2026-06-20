"""Phase 4 TDD: alternative update schedules. Stdlib-only.

Run as ``python v2/tests/test_phase4_tdd.py``. Tests are written from the
interface spec; they are RED until the schedules are implemented.

Spec under test:
- RandomSubsetSchedule(k=2, *, rng=None, seed=None): participants(config) returns
  a frozenset of min(k, |V|) distinct vertices chosen uniformly at random via the
  RNG. Deterministic given a seed. RNG is scheduling-only.
- StochasticCadenceSchedule(p, *, rng=None, seed=None): participants(config)
  returns each vertex independently with probability p. p>=1 -> all, p<=0 -> none.
  Deterministic given a seed.
- Both are UpdateSchedule; plug into GraphDynamicalSystem(schedule=...). The engine
  evaluates only participants; non-participants hold their state.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import (  # noqa: E402
    Configuration,
    Digraph,
    FunctionKernel,
    GraphDynamicalSystem,
    ParallelSchedule,
    RandomSubsetSchedule,
    StochasticCadenceSchedule,
    UpdateSchedule,
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


def cfg(vertices):
    return Configuration(Digraph.of({v: [] for v in vertices}), {v: {"n": 0} for v in vertices})


def inc(state, inputs):
    return {"n": state["n"] + 1}


# ---------------------------------------------------------------- RandomSubset

def test_random_subset_size_and_membership():
    c = cfg(["a", "b", "c", "d"])
    s = RandomSubsetSchedule(2, seed=1)
    for _ in range(20):
        p = s.participants(c)
        if len(p) != 2 or not p.issubset(c.vertices()):
            check("RandomSubset: |p|==k and p subset V", False)
            return
    check("RandomSubset: |p|==k and p subset V", True)


def test_random_subset_clamps_k_to_n():
    c = cfg(["a", "b"])
    s = RandomSubsetSchedule(5, seed=1)
    p = s.participants(c)
    check("RandomSubset: k clamped to |V|", p == c.vertices())


def test_random_subset_deterministic_with_seed():
    c = cfg(["a", "b", "c", "d", "e"])
    s1 = RandomSubsetSchedule(2, seed=42)
    s2 = RandomSubsetSchedule(2, seed=42)
    seq1 = [tuple(sorted(s1.participants(c))) for _ in range(15)]
    seq2 = [tuple(sorted(s2.participants(c))) for _ in range(15)]
    check("RandomSubset: same seed -> same sequence", seq1 == seq2)


def test_random_subset_eventually_covers_all():
    c = cfg(["a", "b", "c", "d"])
    s = RandomSubsetSchedule(1, seed=7)
    seen = set()
    for _ in range(200):
        seen |= s.participants(c)
    check("RandomSubset: covers all vertices over time", seen == c.vertices())


def test_random_subset_only_participants_update():
    c = cfg(["a", "b", "c"])
    gds = GraphDynamicalSystem(
        c, {v: FunctionKernel(inc) for v in ("a", "b", "c")},
        schedule=RandomSubsetSchedule(1, seed=3),
    )
    before = {v: gds.config.state_of(v)["n"] for v in ("a", "b", "c")}
    p = gds.schedule.participants(gds.config)  # peek; note this advances the RNG
    # Re-seed a fresh equivalent run to compare deterministically.
    gds2 = GraphDynamicalSystem(
        cfg(["a", "b", "c"]), {v: FunctionKernel(inc) for v in ("a", "b", "c")},
        schedule=RandomSubsetSchedule(1, seed=3),
    )
    parts = gds2.schedule.participants(gds2.config)
    gds3 = GraphDynamicalSystem(
        cfg(["a", "b", "c"]), {v: FunctionKernel(inc) for v in ("a", "b", "c")},
        schedule=RandomSubsetSchedule(1, seed=3),
    )
    gds3.step()
    changed = {v for v in ("a", "b", "c") if gds3.config.state_of(v)["n"] != 0}
    # exactly the first-drawn participant set updated
    check("RandomSubset: only participants update (count)", len(changed) == 1)


# ------------------------------------------------------------ StochasticCadence

def test_cadence_p1_all_participate():
    c = cfg(["a", "b", "c"])
    s = StochasticCadenceSchedule(1.0, seed=1)
    check("Cadence p=1 -> all", s.participants(c) == c.vertices())


def test_cadence_p0_none_participate():
    c = cfg(["a", "b", "c"])
    s = StochasticCadenceSchedule(0.0, seed=1)
    check("Cadence p=0 -> none", s.participants(c) == frozenset())


def test_cadence_deterministic_with_seed():
    c = cfg(["a", "b", "c", "d", "e", "f"])
    s1 = StochasticCadenceSchedule(0.5, seed=99)
    s2 = StochasticCadenceSchedule(0.5, seed=99)
    seq1 = [tuple(sorted(s1.participants(c))) for _ in range(15)]
    seq2 = [tuple(sorted(s2.participants(c))) for _ in range(15)]
    check("Cadence: same seed -> same sequence", seq1 == seq2)


def test_cadence_subset_and_varies():
    c = cfg([f"v{i}" for i in range(10)])
    s = StochasticCadenceSchedule(0.5, seed=5)
    draws = [s.participants(c) for _ in range(30)]
    all_subset = all(d.issubset(c.vertices()) for d in draws)
    varies = len({tuple(sorted(d)) for d in draws}) > 1
    check("Cadence: subsets of V and they vary", all_subset and varies)


# ----------------------------------------------------------------- pluggability

def test_schedules_are_update_schedules():
    check(
        "schedules subclass UpdateSchedule",
        isinstance(RandomSubsetSchedule(1, seed=1), UpdateSchedule)
        and isinstance(StochasticCadenceSchedule(0.5, seed=1), UpdateSchedule)
        and isinstance(ParallelSchedule(), UpdateSchedule),
    )


def test_same_system_three_schedules_runs():
    def build(schedule):
        return GraphDynamicalSystem(
            cfg(["a", "b", "c", "d"]),
            {v: FunctionKernel(inc) for v in ("a", "b", "c", "d")},
            schedule=schedule,
        )

    par = build(ParallelSchedule()); par.run(5)
    sub = build(RandomSubsetSchedule(2, seed=1)); sub.run(5)
    cad = build(StochasticCadenceSchedule(0.5, seed=1)); cad.run(5)
    # Parallel advances every vertex 5 times; the stochastic ones advance fewer
    # in aggregate (a strict, schedule-dependent difference proving pluggability).
    par_total = sum(par.config.state_of(v)["n"] for v in ("a", "b", "c", "d"))
    sub_total = sum(sub.config.state_of(v)["n"] for v in ("a", "b", "c", "d"))
    check("pluggable: parallel advances strictly more than random-subset(k=2)",
          par_total == 20 and sub_total == 10)


if __name__ == "__main__":
    test_random_subset_size_and_membership()
    test_random_subset_clamps_k_to_n()
    test_random_subset_deterministic_with_seed()
    test_random_subset_eventually_covers_all()
    test_random_subset_only_participants_update()
    test_cadence_p1_all_participate()
    test_cadence_p0_none_participate()
    test_cadence_deterministic_with_seed()
    test_cadence_subset_and_varies()
    test_schedules_are_update_schedules()
    test_same_system_three_schedules_runs()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
