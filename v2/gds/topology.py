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

    *target* must name a vertex that exists when the update is applied (arcs are
    ``A ⊆ V×V`` — no dangling arcs). If it does not, `apply` refuses the arc and
    reports the refusal (see `ApplyResult.rejected`); the engine propagates that
    back to the actor's kernel. Identifiers are matched exactly (case-sensitive).
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
    label and applies registry coupling.

    *name* is an optional human-readable hint for the label: the engine slugifies
    it into a readable, unique identifier (``logger``, ``logger_2``, …) instead of
    an opaque ``v1``. It is only a hint — the engine still owns label allocation
    and falls back to a minted ``v{n}`` when *name* is absent or unusable, so the
    substrate never crashes on a missing/duplicate name.
    """

    initial_state: State
    kernel: "TransitionKernel"
    out_arcs: frozenset[Vertex] = field(default_factory=frozenset)
    name: str | None = None


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
    # Human-readable reasons for updates the actor emitted that were *refused*
    # (as opposed to silently dropped for being over-budget) — currently arcs to
    # non-existent vertices. The engine propagates these to the actor's kernel.
    rejected: list[str] = field(default_factory=list)


def apply(
    digraph: Digraph,
    states: Mapping[Vertex, State],
    kernels: Mapping[Vertex, "TransitionKernel"],
    actor: Vertex,
    updates,
    *,
    mint: Callable[..., Vertex],
    registry: Vertex | None = None,
    limits=None,
    creations_remaining: int | None = None,
) -> ApplyResult:
    """Apply *actor*'s topology *updates*, enforcing the two laws and `limits`.

    Returns fresh ``(digraph, states, kernels)`` plus the labels created. Pure
    w.r.t. its inputs (copies the mappings); the engine swaps in the result.

    Resource guardrails (`gds.safety.Limits`) silently DROP over-budget updates
    rather than raising: ``max_out_degree`` caps agent-emitted `AddArc` (registry
    coupling is exempt — it is a system invariant, not an agent action),
    ``max_vertices`` and ``creations_remaining`` cap `AddVertex`.
    """
    max_out_degree = getattr(limits, "max_out_degree", None)
    max_vertices = getattr(limits, "max_vertices", None)

    dg = digraph
    new_states = dict(states)
    new_kernels = dict(kernels)
    created: list[Vertex] = []
    rejected: list[str] = []

    for u in updates:
        if isinstance(u, AddArc):
            if not dg.has_vertex(u.target):
                # Arcs are A ⊆ V×V: refuse (and report) an arc to a vertex that
                # does not exist, rather than creating a dangling one. Matched
                # exactly, so a mis-cased name is simply "no such object".
                rejected.append(
                    f"add_arc refused: no object named {u.target!r} exists "
                    f"(names are matched exactly), so the arc was not made."
                )
                continue
            if max_out_degree is not None and dg.out_degree(actor) >= max_out_degree:
                continue  # out-degree cap reached — drop
            dg = dg.with_arc(actor, u.target)
        elif isinstance(u, RemoveArc):
            dg = dg.without_arc(actor, u.target)
        elif isinstance(u, AddVertex):
            if max_vertices is not None and len(dg.vertices()) >= max_vertices:
                continue  # total-vertex cap reached — drop
            if creations_remaining is not None and len(created) >= creations_remaining:
                continue  # per-step creation budget exhausted — drop
            w = mint(u.name)
            # A newborn's birth arcs obey the same invariant: keep only those to
            # vertices that already exist; report any dropped as non-existent.
            valid_out = frozenset(o for o in u.out_arcs if dg.has_vertex(o))
            missing = sorted(set(u.out_arcs) - valid_out)
            if missing:
                rejected.append(
                    f"add_vertex {w!r}: dropped observe-arcs to non-existent "
                    f"objects {missing}."
                )
            dg = dg.with_vertex(w, valid_out)
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

    return ApplyResult(dg, new_states, new_kernels, created, rejected)
