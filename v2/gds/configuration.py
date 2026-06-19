"""A configuration: one point in the system's phase space.

A `Configuration` pairs a `Digraph` with a labeling ``x : V → S`` assigning each
vertex a **state** (a JSON-serialisable value). It is the complete instantaneous
description of the world — what exists, how it is wired, and the state of each
thing. Immutable: a step reads a configuration and produces the next one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .digraph import Digraph, Vertex

# A state is any JSON-serialisable value; in practice usually a dict.
State = Any


@dataclass(frozen=True)
class Configuration:
    digraph: Digraph
    states: Mapping[Vertex, State]

    # -------------------------------------------------------------- inspection

    def vertices(self) -> frozenset[Vertex]:
        return self.digraph.vertices()

    def has_vertex(self, v: Vertex) -> bool:
        return self.digraph.has_vertex(v)

    def state_of(self, v: Vertex) -> State:
        return self.states.get(v)

    def inputs(self, v: Vertex) -> dict[Vertex, State]:
        """``x | N⁺(v)`` — the states of the vertices *v* observes."""
        return {w: self.states.get(w) for w in self.digraph.out_neighbours(v)}

    # ---------------------------------------------------------- functional ops

    def with_states(self, states: Mapping[Vertex, State]) -> "Configuration":
        return Configuration(self.digraph, states)

    def with_digraph(self, digraph: Digraph) -> "Configuration":
        return Configuration(digraph, self.states)

    # ----------------------------------------------------------- (de)serialise

    def to_dict(self) -> dict:
        return {
            "states": dict(self.states),
            "arcs": {
                v: sorted(self.digraph.out_neighbours(v))
                for v in sorted(self.digraph.vertices())
            },
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Configuration":
        return Configuration(Digraph.of(d["arcs"]), dict(d["states"]))
