"""Phase 2 TDD test suite (RED phase) for the GDS registry.

Written purely from the Phase 2 interface spec. The Phase 2 implementation is a
stub raising NotImplementedError, so these tests are EXPECTED to fail/error.

Runnable as: python v2/tests/test_phase2_tdd.py
Prints per-test ok/FAIL and exits nonzero on any failure.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import (
    AddArc,
    AddVertex,
    Configuration,
    Digraph,
    FunctionKernel,
    GraphDynamicalSystem,
    REGISTRY_ID,
    RegistryKernel,
    Step,
    TransitionKernel,
    install_registry,
)


# ---------------------------------------------------------------------------
# Tiny test harness (stdlib only).
# ---------------------------------------------------------------------------

_RESULTS = []


def _run(name, fn):
    try:
        fn()
    except AssertionError as exc:
        _RESULTS.append((name, "FAIL", str(exc)))
        print("FAIL %s: %s" % (name, exc))
    except Exception as exc:  # noqa: BLE001 - report any unexpected error
        _RESULTS.append((name, "ERROR", "%s: %s" % (type(exc).__name__, exc)))
        print("ERROR %s: %s: %s" % (name, type(exc).__name__, exc))
    else:
        _RESULTS.append((name, "ok", ""))
        print("ok %s" % name)


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Helpers for building small worlds.
# ---------------------------------------------------------------------------

def _inert():
    """A kernel that returns its state unchanged (no topology updates)."""
    return FunctionKernel(lambda s, i: s)


def _build_inert_world(vertex_ids):
    """Build a Configuration + kernels of mutually-uncoupled inert vertices."""
    adjacency = {v: [] for v in vertex_ids}
    digraph = Digraph.of(adjacency)
    states = {v: {} for v in vertex_ids}
    config = Configuration(digraph, states)
    kernels = {v: _inert() for v in vertex_ids}
    return config, kernels


# ---------------------------------------------------------------------------
# Law 1: install_registry adds exactly one new vertex; returns the id.
# ---------------------------------------------------------------------------

def test_install_adds_one_vertex_and_returns_id():
    config, kernels = _build_inert_world(["a", "b", "c"])
    new_config, new_kernels, reg_id = install_registry(config, kernels)

    _assert(reg_id == REGISTRY_ID, "returned id should equal REGISTRY_ID")

    original = set(config.vertices())
    after = set(new_config.vertices())
    added = after - original
    _assert(added == {reg_id}, "exactly one new vertex (the registry) expected, got added=%r" % (added,))
    _assert(original <= after, "all original vertices must remain present")

    _assert(new_config.has_vertex(reg_id), "registry must be present in returned config")
    _assert(reg_id in new_kernels, "registry must be present in returned kernels")
    # All original kernels remain.
    for v in kernels:
        _assert(v in new_kernels, "original kernel %r must remain in returned kernels" % v)


def test_install_registry_initial_state_and_kernel():
    config, kernels = _build_inert_world(["a", "b"])
    new_config, new_kernels, reg_id = install_registry(config, kernels)

    _assert(new_config.state_of(reg_id) == {"ledger": []},
            "registry initial state must be {'ledger': []}, got %r" % (new_config.state_of(reg_id),))
    _assert(isinstance(new_kernels[reg_id], RegistryKernel),
            "registry kernel must be a RegistryKernel instance")


def test_install_custom_registry_id():
    config, kernels = _build_inert_world(["a", "b"])
    new_config, new_kernels, reg_id = install_registry(config, kernels, registry_id="myreg")
    _assert(reg_id == "myreg", "returned id should equal the requested registry_id")
    _assert(new_config.has_vertex("myreg"), "custom registry id must be present")


# ---------------------------------------------------------------------------
# Law 2: bidirectional coupling of all initial vertices.
# ---------------------------------------------------------------------------

def test_bidirectional_coupling_of_initial_vertices():
    ids = ["a", "b", "c"]
    config, kernels = _build_inert_world(ids)
    new_config, _new_kernels, reg_id = install_registry(config, kernels)

    digraph = new_config.digraph if hasattr(new_config, "digraph") else None
    # Use the configuration's view of out-neighbours via inputs/digraph.
    reg_out = set(_out_neighbours(new_config, reg_id))
    for v in ids:
        v_out = set(_out_neighbours(new_config, v))
        _assert(reg_id in v_out, "registry must be in N+(%r) (v -> registry)" % v)
        _assert(v in reg_out, "%r must be in N+(registry) (registry -> v)" % v)


def _out_neighbours(config, v):
    """Resolve out-neighbours of v from a Configuration's digraph."""
    digraph = getattr(config, "digraph", None)
    if digraph is None:
        # Fall back: Configuration may expose inputs only; but coupling is about
        # out-arcs, so a digraph attribute is expected.
        raise AssertionError("configuration exposes no digraph for out_neighbours")
    return digraph.out_neighbours(v)


# ---------------------------------------------------------------------------
# Law 3: no mutation of inputs; ValueError on existing id.
# ---------------------------------------------------------------------------

def test_install_does_not_mutate_inputs():
    ids = ["a", "b", "c"]
    config, kernels = _build_inert_world(ids)

    orig_vertices = set(config.vertices())
    orig_kernel_keys = set(kernels.keys())

    install_registry(config, kernels)

    _assert(set(config.vertices()) == orig_vertices,
            "original config must be unchanged after install_registry")
    _assert(set(kernels.keys()) == orig_kernel_keys,
            "original kernels dict must be unchanged after install_registry")
    for v in ids:
        _assert(REGISTRY_ID not in set(_out_neighbours(config, v)),
                "original config must not gain coupling to the registry")


def test_install_raises_if_id_exists():
    config, kernels = _build_inert_world(["registry", "a"])
    raised = False
    try:
        install_registry(config, kernels)  # default id "registry" already exists
    except ValueError:
        raised = True
    _assert(raised, "install_registry must raise ValueError when registry_id already names a vertex")


def test_install_raises_if_custom_id_exists():
    config, kernels = _build_inert_world(["dup", "a"])
    raised = False
    try:
        install_registry(config, kernels, registry_id="dup")
    except ValueError:
        raised = True
    _assert(raised, "install_registry must raise ValueError when custom registry_id already exists")


# ---------------------------------------------------------------------------
# Law 4: RegistryKernel.evaluate returns Step with sorted ledger, no updates.
# ---------------------------------------------------------------------------

def test_registry_kernel_is_transition_kernel():
    _assert(isinstance(RegistryKernel(), TransitionKernel),
            "RegistryKernel must be a TransitionKernel")


def test_registry_kernel_evaluate_sorted_ledger():
    kernel = RegistryKernel()
    inputs = {"b": {"x": 1}, "a": {"y": 2}, "c": {}}
    step = kernel.evaluate({"ledger": []}, inputs)

    _assert(isinstance(step, Step), "evaluate must return a Step, got %r" % (type(step),))
    _assert(step.next_state == {"ledger": ["a", "b", "c"]},
            "ledger must be the sorted list of input identifiers, got %r" % (step.next_state,))
    _assert(tuple(step.updates) == (), "RegistryKernel must emit no topology updates, got %r" % (step.updates,))


def test_registry_kernel_evaluate_empty_inputs():
    kernel = RegistryKernel()
    step = kernel.evaluate({"ledger": ["stale"]}, {})
    _assert(step.next_state == {"ledger": []},
            "empty inputs -> empty ledger, got %r" % (step.next_state,))
    _assert(tuple(step.updates) == (), "no updates expected for empty inputs")


def test_registry_kernel_does_not_list_itself():
    # The registry never appears in its own inputs, so it never lists itself.
    kernel = RegistryKernel()
    inputs = {"a": {}, "z": {}}  # no "registry" key
    step = kernel.evaluate({"ledger": []}, inputs)
    _assert("registry" not in step.next_state["ledger"],
            "registry must not list itself")
    _assert(step.next_state["ledger"] == ["a", "z"], "ledger sorted, got %r" % (step.next_state["ledger"],))


# ---------------------------------------------------------------------------
# Law 5: ledger reflects initial vertices after one engine step.
# ---------------------------------------------------------------------------

def test_ledger_reflects_initial_vertices():
    ids = ["alpha", "beta", "gamma"]
    config, kernels = _build_inert_world(ids)
    new_config, new_kernels, reg_id = install_registry(config, kernels)

    gds = GraphDynamicalSystem(new_config, new_kernels, registry=reg_id)
    gds.step()

    reg_state = gds.config.state_of(reg_id)
    _assert(reg_state == {"ledger": sorted(ids)},
            "after one step, registry ledger must equal sorted original ids, got %r" % (reg_state,))


# ---------------------------------------------------------------------------
# Law 6: a newcomer minted during a run appears in the ledger eventually.
# ---------------------------------------------------------------------------

def _creator_kernel():
    """A kernel that emits exactly one AddVertex on its first step, then idles.

    State carries a 'spawned' flag so it only creates once.
    """

    def fn(state, inputs):
        if state.get("spawned"):
            return state
        new_state = dict(state)
        new_state["spawned"] = True
        child = AddVertex(initial_state={"tag": "child"}, kernel=_inert())
        return (new_state, (child,))

    return FunctionKernel(fn)


def test_newcomer_appears_in_ledger():
    # World: one creator vertex. Registry auto-couples newly-created vertices.
    adjacency = {"creator": []}
    digraph = Digraph.of(adjacency)
    states = {"creator": {"spawned": False}}
    config = Configuration(digraph, states)
    kernels = {"creator": _creator_kernel()}

    new_config, new_kernels, reg_id = install_registry(config, kernels)
    gds = GraphDynamicalSystem(new_config, new_kernels, registry=reg_id)

    for _ in range(10):
        gds.step()

    ledger = gds.config.state_of(reg_id)["ledger"]
    # The minted child id should eventually appear. It is some vertex id that is
    # neither the original creator nor the registry.
    minted = [v for v in gds.config.vertices() if v not in ("creator", reg_id)]
    _assert(len(minted) >= 1, "creator should have minted at least one vertex, got %r" % (list(gds.config.vertices()),))
    for m in minted:
        _assert(m in ledger,
                "minted vertex %r must eventually appear in registry ledger %r" % (m, ledger))


# ---------------------------------------------------------------------------
# Law 7: discovery end-to-end via a seeker reading the ledger.
# ---------------------------------------------------------------------------

def _seeker_kernel(reg_id):
    """A kernel that reads the registry ledger from its inputs and wires up to
    every ledger id it doesn't already observe (excluding itself and registry).
    """

    def fn(state, inputs):
        # The registry's state arrives as an input value keyed by its id.
        reg_state = inputs.get(reg_id, {})
        ledger = reg_state.get("ledger", []) if isinstance(reg_state, dict) else []
        already = set(inputs.keys())
        self_id = state.get("self")
        new_targets = [
            t for t in ledger
            if t not in already and t != reg_id and t != self_id
        ]
        new_state = dict(state)
        return (new_state, tuple(AddArc(t) for t in new_targets))

    return FunctionKernel(fn)


def test_discovery_end_to_end():
    # World: a seeker and a creator. Seeker observes the registry so it can read
    # the ledger; creator mints a recognizable child.
    adjacency = {
        "seeker": [],
        "creator": [],
    }
    digraph = Digraph.of(adjacency)
    states = {
        "seeker": {"self": "seeker"},
        "creator": {"spawned": False},
    }
    config = Configuration(digraph, states)
    kernels = {
        "seeker": _seeker_kernel(REGISTRY_ID),
        "creator": _creator_kernel(),
    }

    new_config, new_kernels, reg_id = install_registry(config, kernels)
    # install couples registry<->seeker and registry<->creator, so the seeker
    # observes the registry (registry is in N+(seeker)? No: seeker -> registry
    # means registry's state is NOT an input of seeker).
    #
    # Spec: "seeker observes the registry (so it can read the ledger)". Observing
    # the registry means the registry is an out-neighbour of the seeker, i.e. the
    # registry's state is among the seeker's inputs. install_registry adds the
    # bidirectional coupling registry<->seeker, which includes seeker->registry,
    # so registry is an out-neighbour of seeker. Good.

    gds = GraphDynamicalSystem(new_config, new_kernels, registry=reg_id)

    for _ in range(10):
        gds.step()

    # Identify the minted child (recognizable state {"tag": "child"}).
    children = [
        v for v in gds.config.vertices()
        if v not in ("seeker", "creator", reg_id)
        and gds.config.state_of(v).get("tag") == "child"
    ]
    _assert(len(children) >= 1, "a recognizable child must have been minted, got %r" % (list(gds.config.vertices()),))
    child = children[0]

    seeker_inputs = gds.config.inputs("seeker")
    _assert(child in seeker_inputs,
            "seeker must end up observing the child %r; seeker inputs=%r" % (child, list(seeker_inputs.keys()) if hasattr(seeker_inputs, "keys") else seeker_inputs))

    # And it can read the child's state via inputs.
    child_state = seeker_inputs[child] if hasattr(seeker_inputs, "__getitem__") else None
    _assert(isinstance(child_state, dict) and child_state.get("tag") == "child",
            "seeker must be able to read the child's state via inputs, got %r" % (child_state,))


# ---------------------------------------------------------------------------
# Law 8: opacity — ledger entries are plain id strings matching real vertices.
# ---------------------------------------------------------------------------

def test_ledger_entries_are_opaque_strings():
    ids = ["one", "two", "three"]
    config, kernels = _build_inert_world(ids)
    new_config, new_kernels, reg_id = install_registry(config, kernels)

    gds = GraphDynamicalSystem(new_config, new_kernels, registry=reg_id)
    gds.step()

    ledger = gds.config.state_of(reg_id)["ledger"]
    all_vertices = set(gds.config.vertices())
    _assert(len(ledger) >= 1, "ledger should be non-empty after a step")
    for entry in ledger:
        _assert(isinstance(entry, str), "every ledger entry must be a str, got %r" % (type(entry),))
        _assert(entry in all_vertices, "ledger entry %r must be an actual vertex id" % (entry,))
        _assert(entry != reg_id, "registry must not list itself in the ledger")


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------

def main():
    tests = [
        ("install_adds_one_vertex_and_returns_id", test_install_adds_one_vertex_and_returns_id),
        ("install_registry_initial_state_and_kernel", test_install_registry_initial_state_and_kernel),
        ("install_custom_registry_id", test_install_custom_registry_id),
        ("bidirectional_coupling_of_initial_vertices", test_bidirectional_coupling_of_initial_vertices),
        ("install_does_not_mutate_inputs", test_install_does_not_mutate_inputs),
        ("install_raises_if_id_exists", test_install_raises_if_id_exists),
        ("install_raises_if_custom_id_exists", test_install_raises_if_custom_id_exists),
        ("registry_kernel_is_transition_kernel", test_registry_kernel_is_transition_kernel),
        ("registry_kernel_evaluate_sorted_ledger", test_registry_kernel_evaluate_sorted_ledger),
        ("registry_kernel_evaluate_empty_inputs", test_registry_kernel_evaluate_empty_inputs),
        ("registry_kernel_does_not_list_itself", test_registry_kernel_does_not_list_itself),
        ("ledger_reflects_initial_vertices", test_ledger_reflects_initial_vertices),
        ("newcomer_appears_in_ledger", test_newcomer_appears_in_ledger),
        ("discovery_end_to_end", test_discovery_end_to_end),
        ("ledger_entries_are_opaque_strings", test_ledger_entries_are_opaque_strings),
    ]

    for name, fn in tests:
        _run(name, fn)

    passed = sum(1 for _, status, _ in _RESULTS if status == "ok")
    failed = sum(1 for _, status, _ in _RESULTS if status == "FAIL")
    errored = sum(1 for _, status, _ in _RESULTS if status == "ERROR")
    total = len(_RESULTS)

    print("\n%d tests: %d ok, %d FAIL, %d ERROR" % (total, passed, failed, errored))

    if failed or errored:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
