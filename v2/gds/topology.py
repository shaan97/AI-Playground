"""Topology updates: how a transition rewrites the graph.

Besides its next state, a transition kernel may emit `TopologyUpdate`s. They are
applied at the **end of a step** (after the synchronous state update), giving
one-arc-per-step causal propagation (a "light cone").

Two laws hold (see `apply`):

* **Out-star ownership.** A vertex may modify only its own out-star ``δ⁺(actor)``
  — add/remove arcs *from itself*, or add fresh vertices. It can never add an arc
  *into* itself or touch another vertex's arcs. Note this is enforced *by the
  type*: `AddArc`/`RemoveArc` carry only a ``target``; the source is always the
  acting vertex, so a cross-vertex edit is simply inexpressible. Hence
  *observation is unilateral* and *influence is consensual*.
* **Registry coupling.** Every newly created vertex is wired to the registry
  vertex ``r`` (``r ↔ v``) so the world stays discoverable, when a registry is
  configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Mapping

from .configuration import State
from .digraph import Digraph, Vertex

if TYPE_CHECKING:
    from .kernel import TransitionKernel


class TopologyUpdate:
    """Base class for graph-rewriting effects emitted by a transition."""


@dataclass(frozen=True)
class AddArc(TopologyUpdate):
    """Add arc ``actor → target``: "I choose to observe *target*."

    *target* need not exist; an arc to a missing/destroyed vertex simply reads as
    an empty input (stale arcs are inert).
    """

    target: Vertex


@dataclass(frozen=True)
class RemoveArc(TopologyUpdate):
    """Remove arc ``actor → target``: stop observing *target*."""

    target: Vertex


@dataclass(frozen=True)
class AddVertex(TopologyUpdate):
    """Create a new vertex with an initial state, a kernel (its behaviour), and
    initial out-arcs (what the newcomer will observe). The engine mints its
    label and applies registry coupling."""

    initial_state: State
    kernel: "TransitionKernel"
    out_arcs: frozenset[Vertex] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RemoveVertex(TopologyUpdate):
    """Deferred — destruction is not a substrate primitive (a terminal "dead"
    state reproduces its behaviour). Present for completeness; applying it raises.
    """


@dataclass
class ApplyResult:
    digraph: Digraph
    states: dict[Vertex, State]
    kernels: dict[Vertex, "TransitionKernel"]
    created: list[Vertex]


def apply(
    digraph: Digraph,
    states: Mapping[Vertex, State],
    kernels: Mapping[Vertex, "TransitionKernel"],
    actor: Vertex,
    updates,
    *,
    mint: Callable[[], Vertex],
    registry: Vertex | None = None,
) -> ApplyResult:
    """Apply *actor*'s topology *updates*, enforcing the two laws.

    Returns fresh ``(digraph, states, kernels)`` plus the labels created. Pure
    w.r.t. its inputs (copies the mappings); the engine swaps in the result.
    """
    dg = digraph
    new_states = dict(states)
    new_kernels = dict(kernels)
    created: list[Vertex] = []

    for u in updates:
        if isinstance(u, AddArc):
            dg = dg.with_arc(actor, u.target)
        elif isinstance(u, RemoveArc):
            dg = dg.without_arc(actor, u.target)
        elif isinstance(u, AddVertex):
            w = mint()
            dg = dg.with_vertex(w, u.out_arcs)
            new_states[w] = u.initial_state
            new_kernels[w] = u.kernel
            created.append(w)
            if registry is not None:
                dg = dg.with_arc(registry, w).with_arc(w, registry)
        elif isinstance(u, RemoveVertex):
            raise NotImplementedError(
                "vertex destruction is deferred; model death as a terminal state"
            )
        else:
            raise TypeError(f"unknown topology update: {u!r}")

    return ApplyResult(dg, new_states, new_kernels, created)
