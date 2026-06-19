"""The directed graph (digraph) underlying the world.

Formally a digraph ``G = (V, A)``: a set of vertices ``V`` and a set of arcs
``A ⊆ V×V``. An arc ``(u, v)`` is read "*u* observes *v*" — *v*'s state feeds
*u*'s transition. So a vertex's **inputs** are its out-neighbourhood ``N⁺(v)``,
and the vertices it can **influence** are its in-neighbourhood ``N⁻(v)``.

Vertices are identified by opaque labels (`Vertex`); the graph imposes no
structure on them beyond equality/hashing. `Digraph` is **immutable** — every
mutation returns a new `Digraph`, which is what lets one step read a whole
generation while the next is being constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

# An opaque vertex label. Domain terms for the thing it identifies: "object",
# "thing", or "agent" (when its kernel is an LLM).
Vertex = str


@dataclass(frozen=True)
class Digraph:
    # _out[v] = N⁺(v): the vertices v observes. Treated as immutable; never
    # mutate in place — the functional methods below return fresh Digraphs.
    _out: Mapping[Vertex, frozenset[Vertex]]

    # ------------------------------------------------------------- constructors

    @staticmethod
    def empty() -> "Digraph":
        return Digraph({})

    @staticmethod
    def of(adjacency: Mapping[Vertex, Iterable[Vertex]]) -> "Digraph":
        """Build from a plain adjacency mapping ``v -> N⁺(v)``."""
        return Digraph({v: frozenset(outs) for v, outs in adjacency.items()})

    # -------------------------------------------------------------- inspection

    def vertices(self) -> frozenset[Vertex]:
        return frozenset(self._out)

    def has_vertex(self, v: Vertex) -> bool:
        return v in self._out

    def out_neighbours(self, v: Vertex) -> frozenset[Vertex]:
        """``N⁺(v)`` — the vertices *v* observes (its inputs)."""
        return self._out.get(v, frozenset())

    def in_neighbours(self, v: Vertex) -> frozenset[Vertex]:
        """``N⁻(v)`` — the vertices that observe *v* (those *v* can influence)."""
        return frozenset(u for u, outs in self._out.items() if v in outs)

    def out_star(self, v: Vertex) -> frozenset[tuple[Vertex, Vertex]]:
        """``δ⁺(v)`` — the arcs *v* owns: ``(v, w)`` for each ``w ∈ N⁺(v)``."""
        return frozenset((v, w) for w in self.out_neighbours(v))

    def out_degree(self, v: Vertex) -> int:
        return len(self.out_neighbours(v))

    def in_degree(self, v: Vertex) -> int:
        return len(self.in_neighbours(v))

    # ---------------------------------------------------------- functional ops

    def with_vertex(self, v: Vertex, out: Iterable[Vertex] = ()) -> "Digraph":
        """Add a fresh vertex *v* observing *out* (no-op fields if it exists)."""
        new = dict(self._out)
        new[v] = frozenset(out)
        return Digraph(new)

    def without_vertex(self, v: Vertex) -> "Digraph":
        """Remove *v* and every arc touching it."""
        return Digraph({u: (outs - {v}) for u, outs in self._out.items() if u != v})

    def with_arc(self, u: Vertex, v: Vertex) -> "Digraph":
        """Add arc ``u → v`` (*u* now observes *v*). Ensures *u* exists."""
        new = dict(self._out)
        new[u] = self.out_neighbours(u) | {v}
        return Digraph(new)

    def without_arc(self, u: Vertex, v: Vertex) -> "Digraph":
        """Remove arc ``u → v`` if present."""
        new = dict(self._out)
        new[u] = self.out_neighbours(u) - {v}
        return Digraph(new)
