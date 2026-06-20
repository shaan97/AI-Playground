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

import random
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


class RandomSubsetSchedule(UpdateSchedule):
    """Activate a random subset of ``k`` vertices each step (population-protocol
    / asynchronous flavour). The RNG is for *scheduling* only — it does not enter
    any transition. Seed it for reproducible schedules.

    STATUS: interface stub for TDD.
    """

    def __init__(self, k: int = 2, *, rng: random.Random | None = None, seed: int | None = None):
        self.k = k
        self._rng = rng if rng is not None else random.Random(seed)

    def participants(self, config: Configuration) -> frozenset[Vertex]:
        # Sort for reproducibility: sampling over a deterministic order makes the
        # schedule a deterministic function of the seed.
        vertices = sorted(config.vertices())
        k = min(self.k, len(vertices))
        return frozenset(self._rng.sample(vertices, k))


class StochasticCadenceSchedule(UpdateSchedule):
    """Each vertex participates independently with probability ``p`` each step
    (per-vertex stochastic cadence — the timing-as-distribution model). The RNG
    is for scheduling only. Seed it for reproducibility.

    STATUS: interface stub for TDD.
    """

    def __init__(self, p: float, *, rng: random.Random | None = None, seed: int | None = None):
        self.p = p
        self._rng = rng if rng is not None else random.Random(seed)

    def participants(self, config: Configuration) -> frozenset[Vertex]:
        # Iterate in sorted order so the per-vertex draws are reproducible.
        return frozenset(v for v in sorted(config.vertices()) if self._rng.random() < self.p)
