"""Observation: what a vertex perceives of its out-neighbourhood.

A pluggable policy mapping ``(configuration, vertex) -> inputs``. The default,
`FullObservation`, hands a kernel the exact states of everything it observes.
Alternatives (noisy, aggregated) are a later concern; isolating this as a
strategy interface keeps them drop-in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .configuration import Configuration, State
from .digraph import Vertex


class Observation(ABC):
    """Abstract observation policy. Subclass and implement `observe`."""

    @abstractmethod
    def observe(self, config: Configuration, v: Vertex) -> dict[Vertex, State]:
        ...


class FullObservation(Observation):
    """Exact, lossless view: a kernel sees the true states of ``N⁺(v)``."""

    def observe(self, config: Configuration, v: Vertex) -> dict[Vertex, State]:
        return config.inputs(v)
