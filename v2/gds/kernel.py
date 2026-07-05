"""Transition kernels: the local update rule of a single vertex.

A transition kernel is the map ``κᵥ : S × S^{N⁺(v)} → S`` — given a vertex's own
state and the states it observes, it produces the next state (and, optionally,
graph-rewriting `TopologyUpdate`s). It is the *behaviour* of a thing; for an
**agent**, ``κᵥ`` is an LLM.

`evaluate` returns either a `Step` (next state + topology updates) or `PENDING`,
meaning "not ready this step — hold my state". `PENDING` exists in the type now
so slow in-process kernels and (later) remote ones are handled uniformly: it is
how *update timing* becomes part of the dynamics rather than a special case.

The substrate has **no notion of randomness** — a kernel is arbitrary author
code and may use randomness or not, seed it or not; that is the author's choice
(see ``docs/UNIVERSE.md`` §Randomness).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Union

from .configuration import State
from .digraph import Vertex

if TYPE_CHECKING:
    from .topology import TopologyUpdate


@dataclass(frozen=True)
class Step:
    """A kernel's output: the next state, plus any topology updates it emits."""

    next_state: State
    updates: tuple["TopologyUpdate", ...] = ()


class _Pending:
    """Singleton sentinel: the kernel did not produce a step this round."""

    _instance: "_Pending | None" = None

    def __new__(cls) -> "_Pending":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "PENDING"


PENDING = _Pending()

Result = Union[Step, _Pending]


class TransitionKernel(ABC):
    """Abstract local update rule. Subclass and implement `evaluate`."""

    @abstractmethod
    def evaluate(self, state: State, inputs: dict[Vertex, State]) -> Result:
        ...


class FunctionKernel(TransitionKernel):
    """A kernel whose behaviour is a plain in-process Python callable.

    The callable receives ``(state, inputs)`` and returns one of:
      * a `Step`,
      * a bare next state (wrapped as ``Step(state)``),
      * ``(next_state, [TopologyUpdate, ...])``, or
      * `PENDING`.
    Useful for cheap deterministic things, tests, and the registry.
    """

    def __init__(self, fn: Callable[[State, dict], object]):
        self._fn = fn

    def evaluate(self, state: State, inputs: dict[Vertex, State]) -> Result:
        out = self._fn(state, inputs)
        if out is PENDING or isinstance(out, Step):
            return out  # type: ignore[return-value]
        if isinstance(out, tuple) and len(out) == 2:
            next_state, updates = out
            return Step(next_state, tuple(updates))
        return Step(out)


class LocalKernel(TransitionKernel):
    """A kernel whose behaviour is author-written Python, run in isolation.

    The code defines ``transition(state, inputs, emit)`` (see `gds._sandbox` for
    the contract). Emitted JSON effects are translated into `TopologyUpdate`s
    here — in particular ``add_vertex`` carries the child's source code, which
    becomes a child `LocalKernel`, so behaviour crosses the JSON boundary as data.
    """

    def __init__(self, code: str):
        self.code = code
        self.last_error: str | None = None

    def evaluate(self, state: State, inputs: dict[Vertex, State]) -> Result:
        from . import _sandbox
        from .topology import AddArc, AddVertex, RemoveArc

        res = _sandbox.run_transition(self.code, state, inputs)
        self.last_error = res.error
        if not res.ok:
            # A crashed transition holds its state this step (and records the
            # error for inspection); it does not corrupt the world.
            return Step(state)

        updates: list = []
        for e in res.effects:
            op = e.get("op")
            if op == "add_arc":
                updates.append(AddArc(e["target"]))
            elif op == "remove_arc":
                updates.append(RemoveArc(e["target"]))
            elif op == "add_vertex":
                updates.append(AddVertex(
                    initial_state=e.get("state", {}),
                    kernel=LocalKernel(e.get("code", "")),
                    out_arcs=frozenset(e.get("observes", [])),
                    name=e.get("name"),
                ))
        return Step(res.next_state, tuple(updates))
