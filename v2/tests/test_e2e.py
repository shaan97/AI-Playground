"""End-to-end tests: whole worlds run to completion with DETERMINISTIC vertices.

No LLMs. Each scenario composes several subsystems at once (engine, schedules,
registry/discovery, topology growth, sandboxed LocalKernels, Limits, trajectory
record-replay) and asserts emergent end-state, the way a real world would run.

Stdlib-only, ASCII output (Windows-console safe). Run as
``python v2/tests/test_e2e.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import (  # noqa: E402
    PENDING,
    REGISTRY_ID,
    AddArc,
    AddVertex,
    Configuration,
    Digraph,
    FunctionKernel,
    GraphDynamicalSystem,
    Limits,
    LocalKernel,
    install_registry,
    ParallelSchedule,
    RandomSubsetSchedule,
    RemoveArc,
    Step,
    StochasticCadenceSchedule,
    Trajectory,
)

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"ok:   {name}")
    else:
        _FAIL += 1
        print(f"FAIL: {name}  {detail}")


def idle(state, inputs):
    return state


def traj_dicts(gds):
    return [c.to_dict() for c in gds.trajectory.snapshots]


# ===========================================================================
# E2E 1: discovery + propagation
#   registry coupling -> ledger -> a seeker discovers a vertex it did NOT create
#   (created mid-run by someone else) -> attaches -> reads its signal.
#   Exercises: engine loop, double-buffering, registry kernel + coupling,
#   opaque-handle discovery, dynamic out-arc attach, creation, propagation.
# ===========================================================================

def _seeker(state, inputs):
    me = state["me"]
    reg = inputs.get(REGISTRY_ID)
    ledger = reg.get("ledger", []) if isinstance(reg, dict) else []
    observed = set(state.get("observed", []))
    updates = []
    for h in ledger:
        if h != me and h != REGISTRY_ID and h not in observed:
            updates.append(AddArc(h))
            observed.add(h)
    signal = state.get("signal_seen")
    for st in inputs.values():
        if isinstance(st, dict) and "signal" in st:
            signal = st["signal"]
    new = {**state, "observed": sorted(observed), "signal_seen": signal}
    return Step(new, tuple(updates))


def _creator_once(child_state):
    def creator(state, inputs):
        if state.get("done"):
            return state
        return Step({"done": True}, (AddVertex(initial_state=child_state, kernel=FunctionKernel(idle)),))
    return creator


def test_e2e_discovery_and_propagation():
    config = Configuration(
        Digraph.of({"seeker": [], "creator": []}),
        {"seeker": {"me": "seeker", "observed": [], "signal_seen": None}, "creator": {}},
    )
    gds = GraphDynamicalSystem(
        config,
        {"seeker": FunctionKernel(_seeker),
         "creator": FunctionKernel(_creator_once({"signal": 42, "kind": "treasure"}))},
    )
    registry_id = install_registry(gds)
    gds.run(10)

    treasure = "v1"  # first minted vertex
    out_seeker = set(gds.config.digraph.out_neighbours("seeker"))
    reg_ledger = gds.config.state_of(registry_id)["ledger"]

    check("e2e/discovery: treasure created and in ledger", treasure in reg_ledger, str(reg_ledger))
    check("e2e/discovery: seeker discovered+attached to treasure", treasure in out_seeker, str(out_seeker))
    check("e2e/discovery: signal propagated to seeker", gds.config.state_of("seeker")["signal_seen"] == 42,
          str(gds.config.state_of("seeker")))


# ===========================================================================
# E2E 2: a basketball game from pointers (UNIVERSE.md sec.4), deterministic.
#   ball state is a possession pointer; players observe the ball and react;
#   after 3 passes the ball "shoots" to the hoop. Exercises mutual observation,
#   the state-as-pointer pattern, multi-step dynamics, trajectory inspection.
# ===========================================================================

RING = ["p0", "p1", "p2"]


def _ball(state, inputs):
    if state.get("scored"):
        return state
    passes = state["passes"]
    if passes >= 3:
        return {"holder": "hoop", "passes": passes, "scored": True}
    nxt = RING[(RING.index(state["holder"]) + 1) % len(RING)]
    return {"holder": nxt, "passes": passes + 1, "scored": False}


def _player(me):
    def player(state, inputs):
        b = inputs.get("ball")
        return {"me": me, "has_ball": bool(isinstance(b, dict) and b.get("holder") == me)}
    return player


def test_e2e_basketball():
    config = Configuration(
        Digraph.of({"ball": [], "p0": ["ball"], "p1": ["ball"], "p2": ["ball"], "hoop": []}),
        {
            "ball": {"holder": "p0", "passes": 0, "scored": False},
            "p0": {"me": "p0", "has_ball": False},
            "p1": {"me": "p1", "has_ball": False},
            "p2": {"me": "p2", "has_ball": False},
            "hoop": {},
        },
    )
    kernels = {"ball": FunctionKernel(_ball), "hoop": FunctionKernel(idle)}
    for p in RING:
        kernels[p] = FunctionKernel(_player(p))
    gds = GraphDynamicalSystem(config, kernels)
    gds.run(5)

    ball = gds.config.state_of("ball")
    check("e2e/basketball: ball scored at the hoop", ball["scored"] and ball["holder"] == "hoop", str(ball))

    # Possession rotated through every player at some point in history.
    possessed_all = all(
        any(snap.state_of(p)["has_ball"] for snap in gds.trajectory.snapshots)
        for p in RING
    )
    check("e2e/basketball: every player possessed the ball at some step", possessed_all)


# ===========================================================================
# E2E 3: self-replicating ecosystem of sandboxed LocalKernels under Limits.
#   Organisms age; at age 2 each spawns one child carrying the same code, then
#   becomes terminal. Limits cap total growth. Exercises the LocalKernel
#   subprocess path, child-code-crossing-the-JSON-boundary, creation cascade,
#   terminal-state "death", resource guardrails, and in-process replay.
# ===========================================================================

ORG_CODE = (
    "def transition(state, inputs, emit):\n"
    "    age = state.get('age', 0) + 1\n"
    "    code = state.get('code', '')\n"
    "    if age >= 2 and not state.get('seeded'):\n"
    "        emit({'op': 'add_vertex', 'state': {'age': 0, 'code': code}, 'code': code, 'observes': []})\n"
    "        return {'age': age, 'seeded': True, 'code': code}\n"
    "    return {'age': age, 'seeded': state.get('seeded', False), 'code': code}\n"
)


def _build_ecosystem():
    config = Configuration(Digraph.of({"org0": []}), {"org0": {"age": 0, "code": ORG_CODE}})
    return GraphDynamicalSystem(
        config, {"org0": LocalKernel(ORG_CODE)},
        limits=Limits(max_vertices=4, max_creations_per_step=2),
    )


def test_e2e_local_kernel_ecosystem():
    gds = _build_ecosystem()
    gds.run(6)
    n = len(gds.config.vertices())
    seeded = [v for v in gds.config.vertices()
              if isinstance(gds.config.state_of(v), dict) and gds.config.state_of(v).get("seeded")]

    check("e2e/ecosystem: grew beyond the seed but stayed within max_vertices", 1 < n <= 4, f"n={n}")
    check("e2e/ecosystem: at least one organism decomposed (spawned)", len(seeded) >= 1)

    # Deterministic LocalKernel code -> identical re-run in-process.
    gds2 = _build_ecosystem()
    gds2.run(6)
    check("e2e/ecosystem: deterministic re-run matches", traj_dicts(gds) == traj_dicts(gds2))


# ===========================================================================
# E2E 4: schedule pluggability + trajectory record-replay on one world.
#   A ring of counters under three schedules. Exercises Parallel/RandomSubset/
#   StochasticCadence end-to-end, seed reproducibility, and JSONL round-trip.
# ===========================================================================

def _inc(state, inputs):
    return {"n": state["n"] + 1}


def _ring(n=4):
    verts = [f"c{i}" for i in range(n)]
    return Configuration(
        Digraph.of({v: [verts[(i + 1) % n]] for i, v in enumerate(verts)}),
        {v: {"n": 0} for v in verts},
    ), {v: FunctionKernel(_inc) for v in verts}


def test_e2e_schedules_and_replay():
    cfg, kers = _ring(4)
    par = GraphDynamicalSystem(cfg, kers, schedule=ParallelSchedule())
    par.run(5)
    par_total = sum(par.config.state_of(v)["n"] for v in par.config.vertices())
    check("e2e/schedules: parallel advances every vertex every step", par_total == 20, f"total={par_total}")

    cfg, kers = _ring(4)
    sub = GraphDynamicalSystem(cfg, kers, schedule=RandomSubsetSchedule(2, seed=11))
    sub.run(5)
    sub_total = sum(sub.config.state_of(v)["n"] for v in sub.config.vertices())
    check("e2e/schedules: random-subset(k=2) does exactly 2 per step", sub_total == 10, f"total={sub_total}")

    # Seeded stochastic cadence is reproducible run-to-run.
    def cadence_run():
        c, k = _ring(4)
        g = GraphDynamicalSystem(c, k, schedule=StochasticCadenceSchedule(0.5, seed=7))
        g.run(6)
        return traj_dicts(g)
    check("e2e/schedules: seeded cadence is reproducible", cadence_run() == cadence_run())

    # Trajectory round-trips through JSONL.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trajectory.jsonl"
        par.trajectory.to_jsonl(path)
        reloaded = Trajectory.from_jsonl(path)
    check("e2e/schedules: trajectory JSONL round-trip",
          [c.to_dict() for c in reloaded.snapshots] == traj_dicts(par))


# ===========================================================================
# E2E 5: detach (RemoveArc) and externally-triggered PENDING.
#   Exercises stopping observation, and a vertex that holds its state on steps
#   where it chooses not to act (PENDING) based on a neighbour's state.
# ===========================================================================

def _detacher(state, inputs):
    if not state.get("detached"):
        return Step({"detached": True}, (RemoveArc("b"),))
    return state


def _src_inc(state, inputs):
    return {"n": state["n"] + 1}


def _even_watcher(state, inputs):
    src = inputs.get("src")
    v = src.get("n") if isinstance(src, dict) else None
    if v is None or v % 2 == 1:
        return PENDING  # only act when the observed value is even
    return {"last": v}


def test_e2e_detach_and_pending():
    # detach
    cfg = Configuration(Digraph.of({"a": ["b"], "b": []}), {"a": {}, "b": {}})
    g = GraphDynamicalSystem(cfg, {"a": FunctionKernel(_detacher), "b": FunctionKernel(idle)})
    check("e2e/detach: starts observing b", "b" in g.config.digraph.out_neighbours("a"))
    g.step()
    check("e2e/detach: RemoveArc stops observation", "b" not in g.config.digraph.out_neighbours("a"))

    # externally-triggered PENDING
    cfg = Configuration(
        Digraph.of({"src": [], "watcher": ["src"]}),
        {"src": {"n": 0}, "watcher": {"last": None}},
    )
    g = GraphDynamicalSystem(cfg, {"src": FunctionKernel(_src_inc), "watcher": FunctionKernel(_even_watcher)})
    # Record watcher.last after each step; it must only change on even src values
    # and otherwise hold (PENDING), never regress.
    lasts = []
    for _ in range(5):
        g.step()
        lasts.append(g.config.state_of("watcher")["last"])
    nondecreasing = all(
        (a is None) or (b is not None and b >= a) for a, b in zip(lasts, lasts[1:])
    )
    check("e2e/pending: watcher only records even values", set(x for x in lasts if x is not None) <= {0, 2, 4},
          str(lasts))
    check("e2e/pending: PENDING holds state (never regresses)", nondecreasing, str(lasts))


if __name__ == "__main__":
    test_e2e_discovery_and_propagation()
    test_e2e_basketball()
    test_e2e_local_kernel_ecosystem()
    test_e2e_schedules_and_replay()
    test_e2e_detach_and_pending()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
