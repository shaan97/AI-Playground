"""Update schedules: which vertices transition on a given step.

The schedule is the substrate's choice of *update order* — the structure that, in
the (sequential) dynamical-systems literature, distinguishes one computational
model from another. It is isolated as a strategy interface so swapping models is
swapping a schedule, not rewriting the engine.

`ParallelSchedule` is the synchronous model: every vertex updates each step,
reading the same generation (the engine double-buffers). `RandomSubsetSchedule`
(population-protocol flavour) and `StochasticCadenceSchedule` are later additions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .configuration import Configuration
from .digraph import Vertex


class UpdateSchedule(ABC):
    """Abstract update schedule. Subclass and implement `participants`."""

    @abstractmethod
    def participants(self, config: Configuration) -> frozenset[Vertex]:
        """The vertices that transition this step."""
        ...


class ParallelSchedule(UpdateSchedule):
    """Synchronous update: all vertices transition every step."""

    def participants(self, config: Configuration) -> frozenset[Vertex]:
        return config.vertices()
