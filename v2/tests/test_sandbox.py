"""LocalKernel (sandboxed author code) tests. Stdlib-only.

Run as ``python v2/tests/test_sandbox.py``.
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
    LocalKernel,
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


def test_local_kernel_updates_state_and_reads_inputs():
    code = """
def transition(state, inputs, emit):
    neighbour_sum = sum(s.get("n", 0) for s in inputs.values())
    return {"n": state["n"] + 1 + neighbour_sum}
"""
    dg = Digraph.of({"a": ["b"], "b": []})
    gds = GraphDynamicalSystem(
        Configuration(dg, {"a": {"n": 0}, "b": {"n": 10}}),
        {"a": LocalKernel(code), "b": FunctionKernel(idle)},
    )
    gds.step()
    # a sees b.n == 10, so a.n -> 0 + 1 + 10 == 11
    check("sandboxed transition updates state from inputs", gds.config.state_of("a") == {"n": 11})


def test_local_kernel_emits_add_arc():
    code = """
def transition(state, inputs, emit):
    if not state.get("linked"):
        emit({"op": "add_arc", "target": "b"})
        return {"linked": True}
    return state
"""
    dg = Digraph.of({"a": [], "b": []})
    gds = GraphDynamicalSystem(
        Configuration(dg, {"a": {}, "b": {}}),
        {"a": LocalKernel(code), "b": FunctionKernel(idle)},
    )
    gds.step()
    check("sandboxed emit add_arc creates a->b", "b" in gds.config.digraph.out_neighbours("a"))


def test_local_kernel_blocks_imports():
    code = """
def transition(state, inputs, emit):
    import os
    return {"hacked": os.getcwd()}
"""
    dg = Digraph.of({"a": []})
    k = LocalKernel(code)
    gds = GraphDynamicalSystem(Configuration(dg, {"a": {"n": 1}}), {"a": k})
    gds.step()
    # import is blocked -> transition errors -> state held, error recorded
    check("import blocked: state unchanged", gds.config.state_of("a") == {"n": 1})
    check("import blocked: error recorded", k.last_error is not None and "import" in (k.last_error or "").lower() or k.last_error is not None)


def test_local_kernel_spawns_child():
    code = """
def transition(state, inputs, emit):
    if not state.get("spawned"):
        emit({"op": "add_vertex", "state": {"child": True},
              "code": "def transition(state, inputs, emit):\\n    return state\\n",
              "observes": []})
        return {"spawned": True}
    return state
"""
    dg = Digraph.of({"r": [], "s": []})
    gds = GraphDynamicalSystem(
        Configuration(dg, {"r": {}, "s": {}}),
        {"r": FunctionKernel(idle), "s": LocalKernel(code)},
        registry="r",
    )
    gds.step()
    new = [v for v in gds.config.vertices() if v not in ("r", "s")]
    check("sandboxed add_vertex creates one child", len(new) == 1)
    if new:
        check("child is a LocalKernel", isinstance(gds.kernels.get(new[0]), LocalKernel))
        check("child registry-coupled", "r" in gds.config.digraph.out_neighbours(new[0]))


if __name__ == "__main__":
    test_local_kernel_updates_state_and_reads_inputs()
    test_local_kernel_emits_add_arc()
    test_local_kernel_blocks_imports()
    test_local_kernel_spawns_child()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
