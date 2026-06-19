import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import os
import tempfile

from gds import (
    AddArc,
    AddVertex,
    Configuration,
    Digraph,
    FullObservation,
    FunctionKernel,
    GraphDynamicalSystem,
    LocalKernel,
    PENDING,
    ParallelSchedule,
    RemoveArc,
    RemoveVertex,
    Step,
    TransitionKernel,
    Trajectory,
)

# ---------------------------------------------------------------------------
# tiny test harness (stdlib only)
# ---------------------------------------------------------------------------

_RESULTS = []


def test(name, fn):
    try:
        fn()
    except AssertionError as e:
        _RESULTS.append((name, False, "assert: " + str(e)))
        print("FAIL %s -- %s" % (name, e))
    except Exception as e:  # spec mismatch / unexpected error
        _RESULTS.append((name, False, "%s: %s" % (type(e).__name__, e)))
        print("FAIL %s -- %s: %s" % (name, type(e).__name__, e))
    else:
        _RESULTS.append((name, True, ""))
        print("ok   %s" % name)


# ---------------------------------------------------------------------------
# 1. Digraph & Configuration immutability
# ---------------------------------------------------------------------------

def t_digraph_empty():
    g = Digraph.empty()
    assert g.vertices() == frozenset()


def t_digraph_of_and_neighbours():
    g = Digraph.of({"a": ["b", "c"], "b": [], "c": []})
    assert g.vertices() == frozenset({"a", "b", "c"})
    assert g.has_vertex("a") is True
    assert g.has_vertex("z") is False
    assert g.out_neighbours("a") == frozenset({"b", "c"})
    assert g.in_neighbours("b") == frozenset({"a"})
    assert g.out_degree("a") == 2
    assert g.in_degree("a") == 0
    assert g.in_degree("b") == 1


def t_digraph_out_star():
    g = Digraph.of({"a": ["b", "c"]})
    assert g.out_star("a") == frozenset({("a", "b"), ("a", "c")})


def t_digraph_with_vertex_immutable():
    g = Digraph.empty()
    g2 = g.with_vertex("a", out=("b",))
    assert g.vertices() == frozenset()  # original unchanged
    assert g2.has_vertex("a")
    assert "b" in g2.out_neighbours("a")


def t_digraph_without_vertex_immutable():
    g = Digraph.of({"a": ["b"], "b": []})
    g2 = g.without_vertex("b")
    assert g.has_vertex("b")  # original unchanged
    assert not g2.has_vertex("b")


def t_digraph_with_arc_immutable():
    g = Digraph.of({"a": [], "b": []})
    g2 = g.with_arc("a", "b")
    assert g.out_neighbours("a") == frozenset()  # original unchanged
    assert g2.out_neighbours("a") == frozenset({"b"})


def t_digraph_without_arc_immutable():
    g = Digraph.of({"a": ["b"], "b": []})
    g2 = g.without_arc("a", "b")
    assert g.out_neighbours("a") == frozenset({"b"})  # original unchanged
    assert g2.out_neighbours("a") == frozenset()


def t_neighbours_unknown_vertex_empty():
    g = Digraph.of({"a": ["b"], "b": []})
    assert g.out_neighbours("zzz") == frozenset()
    assert g.in_neighbours("zzz") == frozenset()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def t_config_basic():
    g = Digraph.of({"a": ["b"], "b": []})
    c = Configuration(g, {"a": 1, "b": 2})
    assert c.vertices() == frozenset({"a", "b"})
    assert c.state_of("a") == 1
    assert c.state_of("b") == 2


def t_config_inputs_are_outneighbour_states():
    # inputs(v) == states of N+(v)
    g = Digraph.of({"a": ["b", "c"], "b": [], "c": []})
    c = Configuration(g, {"a": 0, "b": 10, "c": 20})
    assert c.inputs("a") == {"b": 10, "c": 20}
    assert c.inputs("b") == {}


def t_config_dangling_arc_reads_none():
    # arc to nonexistent vertex reads as None, not an error
    g = Digraph.of({"a": ["ghost"]})
    c = Configuration(g, {"a": 1})
    inp = c.inputs("a")
    assert inp == {"ghost": None}, inp


def t_config_with_states_immutable():
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 1})
    c2 = c.with_states({"a": 99})
    assert c.state_of("a") == 1  # original unchanged
    assert c2.state_of("a") == 99


def t_config_with_digraph_immutable():
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 1})
    g2 = g.with_vertex("b")
    c2 = c.with_digraph(g2)
    assert not c.digraph.has_vertex("b")  # original unchanged
    assert c2.digraph.has_vertex("b")


def t_config_to_from_dict_roundtrip():
    g = Digraph.of({"a": ["b"], "b": []})
    c = Configuration(g, {"a": 1, "b": 2})
    d = c.to_dict()
    c2 = Configuration.from_dict(d)
    assert c2.to_dict() == d


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

def t_step_construction():
    s = Step(5)
    assert s.next_state == 5
    assert s.updates == ()
    s2 = Step(7, updates=(AddArc("x"),))
    assert s2.next_state == 7
    assert len(s2.updates) == 1


def t_function_kernel_bare_state():
    k = FunctionKernel(lambda state, inputs: state + 1)
    r = k.evaluate(3, {})
    assert isinstance(r, Step)
    assert r.next_state == 4


def t_function_kernel_returns_step():
    k = FunctionKernel(lambda state, inputs: Step(99))
    r = k.evaluate(0, {})
    assert r.next_state == 99


def t_function_kernel_tuple():
    k = FunctionKernel(lambda state, inputs: (5, [AddArc("z")]))
    r = k.evaluate(0, {})
    assert r.next_state == 5
    assert len(r.updates) == 1
    assert isinstance(list(r.updates)[0], AddArc)


def t_function_kernel_pending():
    k = FunctionKernel(lambda state, inputs: PENDING)
    r = k.evaluate(0, {})
    assert r is PENDING


def t_transition_kernel_is_abc():
    # Cannot instantiate the ABC directly
    raised = False
    try:
        TransitionKernel()
    except TypeError:
        raised = True
    assert raised, "TransitionKernel should be abstract"


# ---------------------------------------------------------------------------
# GraphDynamicalSystem - stepping semantics
# ---------------------------------------------------------------------------

def t_empty_graph_step_noop():
    c = Configuration(Digraph.empty(), {})
    gds = GraphDynamicalSystem(c, {})
    c2 = gds.step()
    assert c2.vertices() == frozenset()


def t_vertex_without_kernel_skipped():
    g = Digraph.of({"a": [], "b": []})
    c = Configuration(g, {"a": 1, "b": 2})
    # only a has a kernel
    k = FunctionKernel(lambda state, inputs: state + 100)
    gds = GraphDynamicalSystem(c, {"a": k})
    c2 = gds.step()
    assert c2.state_of("a") == 101
    assert c2.state_of("b") == 2  # unchanged, no kernel


def t_pending_holds_state():
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 7})
    k = FunctionKernel(lambda state, inputs: PENDING)
    gds = GraphDynamicalSystem(c, {"a": k})
    c2 = gds.step()
    assert c2.state_of("a") == 7


def t_double_buffering_synchronous():
    # Two mutually-observing vertices: new = neighbour's PREVIOUS state.
    # a observes b, b observes a. Kernel sets state = the input value.
    # Initial a=1, b=2. Synchronous: a->2, b->1 (swap).
    # Sequential would give a->2 then b->2.
    g = Digraph.of({"a": ["b"], "b": ["a"]})
    c = Configuration(g, {"a": 1, "b": 2})

    def fn(state, inputs):
        # single neighbour: take its observed (previous) state
        (val,) = list(inputs.values())
        return val

    k = FunctionKernel(fn)
    gds = GraphDynamicalSystem(c, {"a": k, "b": k})
    c2 = gds.step()
    assert c2.state_of("a") == 2, c2.state_of("a")
    assert c2.state_of("b") == 1, c2.state_of("b")


def t_step_index_and_trajectory_grow():
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 0})
    k = FunctionKernel(lambda state, inputs: state + 1)
    gds = GraphDynamicalSystem(c, {"a": k})
    start_len = len(gds.trajectory)
    gds.step()
    gds.step()
    assert gds.step_index == 2, gds.step_index
    assert len(gds.trajectory) == start_len + 2, len(gds.trajectory)


def t_run_n_steps():
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 0})
    k = FunctionKernel(lambda state, inputs: state + 1)
    gds = GraphDynamicalSystem(c, {"a": k})
    final = gds.run(5)
    assert final.state_of("a") == 5, final.state_of("a")


# ---------------------------------------------------------------------------
# Topology: out-star ownership
# ---------------------------------------------------------------------------

def t_add_arc_only_actor_to_target():
    # a emits AddArc(b); only a->b appears, never b->a
    g = Digraph.of({"a": [], "b": []})
    c = Configuration(g, {"a": 0, "b": 0})
    k_a = FunctionKernel(lambda state, inputs: Step(state, updates=(AddArc("b"),)))
    k_b = FunctionKernel(lambda state, inputs: PENDING)
    gds = GraphDynamicalSystem(c, {"a": k_a, "b": k_b})
    c2 = gds.step()
    assert "b" in c2.digraph.out_neighbours("a"), c2.digraph.out_neighbours("a")
    assert "a" not in c2.digraph.out_neighbours("b"), c2.digraph.out_neighbours("b")


def t_remove_arc_only_actor_to_target():
    g = Digraph.of({"a": ["b"], "b": ["a"]})
    c = Configuration(g, {"a": 0, "b": 0})
    k_a = FunctionKernel(lambda state, inputs: Step(state, updates=(RemoveArc("b"),)))
    k_b = FunctionKernel(lambda state, inputs: PENDING)
    gds = GraphDynamicalSystem(c, {"a": k_a, "b": k_b})
    c2 = gds.step()
    assert "b" not in c2.digraph.out_neighbours("a")
    assert "a" in c2.digraph.out_neighbours("b"), "b->a must be untouched"


# ---------------------------------------------------------------------------
# AddVertex / registry coupling / causal delay
# ---------------------------------------------------------------------------

def t_add_vertex_creates_one_vertex():
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 0})
    child_k = FunctionKernel(lambda state, inputs: state)
    # a spawns one new vertex on step 1, then holds afterwards
    def fn(state, inputs):
        if state == 0:
            return Step(1, updates=(AddVertex(initial_state=42, kernel=child_k),))
        return PENDING
    k = FunctionKernel(fn)
    gds = GraphDynamicalSystem(c, {"a": k})
    c2 = gds.step()
    assert len(c2.vertices()) == 2, c2.vertices()


def t_registry_coupling():
    # registry "r" exists; new vertex w gets r->w and w->r
    g = Digraph.of({"r": [], "a": []})
    c = Configuration(g, {"r": 0, "a": 0})
    child_k = FunctionKernel(lambda state, inputs: state)
    def fn(state, inputs):
        if state == 0:
            return Step(1, updates=(AddVertex(initial_state=7, kernel=child_k),))
        return PENDING
    k_a = FunctionKernel(fn)
    k_r = FunctionKernel(lambda state, inputs: PENDING)
    gds = GraphDynamicalSystem(c, {"a": k_a, "r": k_r}, registry="r")
    c2 = gds.step()
    new = [v for v in c2.vertices() if v not in ("r", "a")]
    assert len(new) == 1, new
    w = new[0]
    assert w in c2.digraph.out_neighbours("r"), "expected r->w"
    assert "r" in c2.digraph.out_neighbours(w), "expected w->r"


def t_causal_one_step_delay():
    # Vertex born in step N must not be evaluated until step N+1.
    # The child increments its state each time it acts. After the step in which
    # it is born, it should still hold its initial state.
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 0})
    child_k = FunctionKernel(lambda state, inputs: state + 1)
    def fn(state, inputs):
        if state == 0:
            return Step(1, updates=(AddVertex(initial_state=100, kernel=child_k),))
        return PENDING
    k = FunctionKernel(fn)
    gds = GraphDynamicalSystem(c, {"a": k})
    c1 = gds.step()  # step where child is born
    new = [v for v in c1.vertices() if v != "a"]
    assert len(new) == 1, new
    w = new[0]
    assert c1.state_of(w) == 100, ("child acted in birth step", c1.state_of(w))
    c2 = gds.step()  # now child should act -> 101
    assert c2.state_of(w) == 101, ("child did not act next step", c2.state_of(w))


# ---------------------------------------------------------------------------
# RemoveVertex surfaces NotImplementedError
# ---------------------------------------------------------------------------

def t_remove_vertex_raises():
    g = Digraph.of({"a": [], "b": []})
    c = Configuration(g, {"a": 0, "b": 0})
    k_a = FunctionKernel(lambda state, inputs: Step(state, updates=(RemoveVertex(),)))
    k_b = FunctionKernel(lambda state, inputs: PENDING)
    gds = GraphDynamicalSystem(c, {"a": k_a, "b": k_b})
    raised = False
    try:
        gds.step()
    except NotImplementedError:
        raised = True
    assert raised, "RemoveVertex should surface NotImplementedError"


# ---------------------------------------------------------------------------
# Trajectory record/replay
# ---------------------------------------------------------------------------

def t_trajectory_record_and_len():
    tr = Trajectory()
    g = Digraph.of({"a": []})
    c = Configuration(g, {"a": 0})
    tr.record(c)
    tr.record(c.with_states({"a": 1}))
    assert len(tr) == 2
    assert tr[0].state_of("a") == 0
    assert tr[1].state_of("a") == 1


def t_trajectory_jsonl_roundtrip():
    tr = Trajectory()
    g = Digraph.of({"a": ["b"], "b": []})
    tr.record(Configuration(g, {"a": 0, "b": 5}))
    tr.record(Configuration(g, {"a": 1, "b": 5}))
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        tr.to_jsonl(path)
        tr2 = Trajectory.from_jsonl(path)
        assert len(tr2) == len(tr)
        for i in range(len(tr)):
            assert tr2[i].to_dict() == tr[i].to_dict(), i
    finally:
        os.remove(path)


def t_function_system_deterministic_replay():
    def build():
        g = Digraph.of({"a": ["b"], "b": ["a"]})
        c = Configuration(g, {"a": 1, "b": 2})
        def fn(state, inputs):
            return state + sum(v for v in inputs.values() if isinstance(v, int))
        k = FunctionKernel(fn)
        return GraphDynamicalSystem(c, {"a": k, "b": k})

    g1 = build()
    g1.run(4)
    snaps1 = [s.to_dict() for s in g1.trajectory.snapshots]

    g2 = build()
    g2.run(4)
    snaps2 = [s.to_dict() for s in g2.trajectory.snapshots]

    assert snaps1 == snaps2, "re-run from same initial config must match"


# ---------------------------------------------------------------------------
# LocalKernel
# ---------------------------------------------------------------------------

def t_localkernel_updates_state():
    code = "def transition(state, inputs, emit):\n    return state + 1\n"
    k = LocalKernel(code)
    assert k.code == code
    r = k.evaluate(10, {})
    # may be a Step or PENDING-like; expect a Step holding next_state 11
    assert isinstance(r, Step), type(r)
    assert r.next_state == 11, r.next_state


def t_localkernel_none_unchanged():
    code = "def transition(state, inputs, emit):\n    return None\n"
    k = LocalKernel(code)
    r = k.evaluate(5, {})
    assert isinstance(r, Step), type(r)
    assert r.next_state == 5, r.next_state


def t_localkernel_uses_inputs():
    code = (
        "def transition(state, inputs, emit):\n"
        "    return sum(inputs.values())\n"
    )
    k = LocalKernel(code)
    r = k.evaluate(0, {"x": 3, "y": 4})
    assert isinstance(r, Step), type(r)
    assert r.next_state == 7, r.next_state


def t_localkernel_emit_add_arc():
    code = (
        "def transition(state, inputs, emit):\n"
        "    emit({'op': 'add_arc', 'target': 'b'})\n"
        "    return state\n"
    )
    k = LocalKernel(code)
    r = k.evaluate(0, {})
    assert isinstance(r, Step), type(r)
    ops = [u for u in r.updates if isinstance(u, AddArc)]
    assert len(ops) == 1, r.updates
    assert ops[0].target == "b", ops[0].target


def t_localkernel_blocked_import_holds_and_sets_error():
    code = (
        "def transition(state, inputs, emit):\n"
        "    import os\n"
        "    return 999\n"
    )
    k = LocalKernel(code)
    r = k.evaluate(5, {})
    assert isinstance(r, Step), type(r)
    assert r.next_state == 5, ("blocked import must hold state", r.next_state)
    assert getattr(k, "last_error", None), "last_error should be set"
    assert isinstance(k.last_error, str)


def t_localkernel_atomic_failure_keeps_original():
    # mutate state then raise -> original state preserved
    code = (
        "def transition(state, inputs, emit):\n"
        "    state['n'] = 999\n"
        "    raise ValueError('boom')\n"
    )
    k = LocalKernel(code)
    orig = {"n": 1}
    r = k.evaluate(orig, {})
    assert isinstance(r, Step), type(r)
    assert r.next_state == {"n": 1} or r.next_state == orig, r.next_state
    assert getattr(k, "last_error", None), "last_error should be set"


def t_localkernel_add_vertex_spawns_localkernel_child_registry_coupled():
    # add_vertex effect -> one child that is a LocalKernel and registry coupled
    child_code = "def transition(state, inputs, emit):\n    return state\n"
    code = (
        "def transition(state, inputs, emit):\n"
        "    if state == 0:\n"
        "        emit({'op': 'add_vertex', 'state': 7, 'code': %r, 'observes': []})\n"
        "        return 1\n"
        "    return None\n" % child_code
    )
    g = Digraph.of({"r": [], "a": []})
    c = Configuration(g, {"r": 0, "a": 0})
    k_a = LocalKernel(code)
    k_r = FunctionKernel(lambda state, inputs: PENDING)
    gds = GraphDynamicalSystem(c, {"a": k_a, "r": k_r}, registry="r")
    c2 = gds.step()
    new = [v for v in c2.vertices() if v not in ("r", "a")]
    assert len(new) == 1, new
    w = new[0]
    # registry coupled
    assert w in c2.digraph.out_neighbours("r"), "expected r->w"
    assert "r" in c2.digraph.out_neighbours(w), "expected w->r"
    # child kernel is a LocalKernel
    child_kernel = gds.kernels.get(w)
    assert isinstance(child_kernel, LocalKernel), type(child_kernel)


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        ("digraph_empty", t_digraph_empty),
        ("digraph_of_and_neighbours", t_digraph_of_and_neighbours),
        ("digraph_out_star", t_digraph_out_star),
        ("digraph_with_vertex_immutable", t_digraph_with_vertex_immutable),
        ("digraph_without_vertex_immutable", t_digraph_without_vertex_immutable),
        ("digraph_with_arc_immutable", t_digraph_with_arc_immutable),
        ("digraph_without_arc_immutable", t_digraph_without_arc_immutable),
        ("neighbours_unknown_vertex_empty", t_neighbours_unknown_vertex_empty),
        ("config_basic", t_config_basic),
        ("config_inputs_are_outneighbour_states", t_config_inputs_are_outneighbour_states),
        ("config_dangling_arc_reads_none", t_config_dangling_arc_reads_none),
        ("config_with_states_immutable", t_config_with_states_immutable),
        ("config_with_digraph_immutable", t_config_with_digraph_immutable),
        ("config_to_from_dict_roundtrip", t_config_to_from_dict_roundtrip),
        ("step_construction", t_step_construction),
        ("function_kernel_bare_state", t_function_kernel_bare_state),
        ("function_kernel_returns_step", t_function_kernel_returns_step),
        ("function_kernel_tuple", t_function_kernel_tuple),
        ("function_kernel_pending", t_function_kernel_pending),
        ("transition_kernel_is_abc", t_transition_kernel_is_abc),
        ("empty_graph_step_noop", t_empty_graph_step_noop),
        ("vertex_without_kernel_skipped", t_vertex_without_kernel_skipped),
        ("pending_holds_state", t_pending_holds_state),
        ("double_buffering_synchronous", t_double_buffering_synchronous),
        ("step_index_and_trajectory_grow", t_step_index_and_trajectory_grow),
        ("run_n_steps", t_run_n_steps),
        ("add_arc_only_actor_to_target", t_add_arc_only_actor_to_target),
        ("remove_arc_only_actor_to_target", t_remove_arc_only_actor_to_target),
        ("add_vertex_creates_one_vertex", t_add_vertex_creates_one_vertex),
        ("registry_coupling", t_registry_coupling),
        ("causal_one_step_delay", t_causal_one_step_delay),
        ("remove_vertex_raises", t_remove_vertex_raises),
        ("trajectory_record_and_len", t_trajectory_record_and_len),
        ("trajectory_jsonl_roundtrip", t_trajectory_jsonl_roundtrip),
        ("function_system_deterministic_replay", t_function_system_deterministic_replay),
        ("localkernel_updates_state", t_localkernel_updates_state),
        ("localkernel_none_unchanged", t_localkernel_none_unchanged),
        ("localkernel_uses_inputs", t_localkernel_uses_inputs),
        ("localkernel_emit_add_arc", t_localkernel_emit_add_arc),
        ("localkernel_blocked_import_holds_and_sets_error", t_localkernel_blocked_import_holds_and_sets_error),
        ("localkernel_atomic_failure_keeps_original", t_localkernel_atomic_failure_keeps_original),
        ("localkernel_add_vertex_spawns_localkernel_child_registry_coupled", t_localkernel_add_vertex_spawns_localkernel_child_registry_coupled),
    ]
    for name, fn in tests:
        test(name, fn)

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = sum(1 for _, ok, _ in _RESULTS if not ok)
    print("\n%d tests, %d passed, %d failed" % (len(_RESULTS), passed, failed))
    if failed:
        print("\nFAILURES:")
        for name, ok, msg in _RESULTS:
            if not ok:
                print("  - %s :: %s" % (name, msg))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
