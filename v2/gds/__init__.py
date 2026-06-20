"""A stochastic graph dynamical system (GDS) — the v2 substrate.

The world is one mathematical object: a directed graph whose vertices carry
state and advance, each step, by a local transition kernel of the states they
observe. See ``docs/UNIVERSE.md`` for the design and the naming conventions used
here (formal terms for types/algorithms, domain terms — *agent*, *thing*,
*world* — where they read more clearly).
"""

from __future__ import annotations

from .configuration import Configuration, State
from .digraph import Digraph, Vertex
from .evolution import GraphDynamicalSystem
from .kernel import PENDING, FunctionKernel, LocalKernel, Step, TransitionKernel
from .observation import FullObservation, Observation
from .registry import REGISTRY_ID, RegistryKernel, install_registry
from .schedule import (
    ParallelSchedule,
    RandomSubsetSchedule,
    StochasticCadenceSchedule,
    UpdateSchedule,
)
from .topology import AddArc, AddVertex, RemoveArc, RemoveVertex, TopologyUpdate
from .trajectory import Trajectory
from .agents.llm import LLMKernel

__all__ = [
    "Configuration",
    "State",
    "Digraph",
    "Vertex",
    "GraphDynamicalSystem",
    "PENDING",
    "FunctionKernel",
    "LocalKernel",
    "Step",
    "TransitionKernel",
    "FullObservation",
    "Observation",
    "REGISTRY_ID",
    "RegistryKernel",
    "install_registry",
    "ParallelSchedule",
    "RandomSubsetSchedule",
    "StochasticCadenceSchedule",
    "UpdateSchedule",
    "AddArc",
    "AddVertex",
    "RemoveArc",
    "RemoveVertex",
    "TopologyUpdate",
    "Trajectory",
    "LLMKernel",
]
