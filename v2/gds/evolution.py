"""The evolution operator: one global step of the world.

`GraphDynamicalSystem` ties together the mutable parts of the model — the current
`Configuration`, the kernels ``{κᵥ}`` (which live here, not in the configuration),
a `UpdateSchedule`, and an `Observation` policy — and exposes ``step()`` = the
evolution operator ``Φ_σ``.

One step:
  1. ask the schedule which vertices participate;
  2. evaluate each participant's kernel on its observed inputs;
  3. **double-buffer** the state update — everyone reads generation *t*, the
     results form generation *t+1* (a `PENDING` kernel simply holds its state);
  4. apply emitted topology updates *after* the state update (end-of-step);
  5. record the new configuration on the trajectory.
"""

from __future__ import annotations

import re
from typing import Mapping

from . import topology
from .configuration import Configuration, State
from .digraph import Vertex
from .kernel import PENDING, Step, TransitionKernel
from .observation import FullObservation, Observation
from .schedule import ParallelSchedule, UpdateSchedule
from .trajectory import Trajectory


class GraphDynamicalSystem:
    def __init__(
        self,
        config: Configuration,
        kernels: Mapping[Vertex, TransitionKernel],
        schedule: UpdateSchedule | None = None,
        observation: Observation | None = None,
        registry: Vertex | None = None,
        limits=None,
    ):
        self.config = config
        self.kernels: dict[Vertex, TransitionKernel] = dict(kernels)
        self.schedule = schedule or ParallelSchedule()
        self.observation = observation or FullObservation()
        self.registry = registry
        self.limits = limits
        self.step_index = 0
        self.trajectory = Trajectory([config])
        self._counter = 0
        # Every label this engine has ever minted. Guards against reusing a label
        # for a second vertex *within the same step* (created vertices are not
        # folded into self.config/self.kernels until the step's topology pass
        # finishes) as well as across steps.
        self._minted: set[Vertex] = set()

    # ----------------------------------------------------------- id allocation

    @staticmethod
    def _slugify(hint: str) -> str:
        """Turn a free-text name hint into a safe, readable label stem (or "")."""
        slug = re.sub(r"[^0-9A-Za-z]+", "_", hint).strip("_").lower()
        return slug[:40]

    def _taken(self, label: Vertex) -> bool:
        return (self.config.digraph.has_vertex(label)
                or label in self.kernels or label in self._minted)

    def _mint(self, hint: str | None = None) -> Vertex:
        """Mint a fresh, unused vertex label.

        With a *hint* (an agent-supplied name) the label is a readable slug of it,
        de-duplicated with a numeric suffix on collision (``logger``, ``logger_2``).
        Without one — or if the hint slugifies to nothing — fall back to the
        opaque ``v{n}`` scheme, so allocation never fails.
        """
        base = self._slugify(hint) if hint else ""
        if base:
            if not self._taken(base):
                self._minted.add(base)
                return base
            i = 2
            while self._taken(f"{base}_{i}"):
                i += 1
            label = f"{base}_{i}"
            self._minted.add(label)
            return label
        while True:
            self._counter += 1
            label = f"v{self._counter}"
            if not self._taken(label):
                self._minted.add(label)
                return label

    # -------------------------------------------------------------- one step Φ

    def step(self) -> Configuration:
        participants = self.schedule.participants(self.config)

        # (2)+(3) Evaluate on generation t; gather next states and emitted updates.
        # Iterate in a sorted, deterministic order so that vertex-mint order and
        # per-step creation-budget allocation do not depend on set hashing — the
        # evolution stays reproducible across processes (state itself is
        # double-buffered, so order never affects what each vertex computes).
        next_states = dict(self.config.states)
        emitted: list[tuple[Vertex, tuple]] = []
        for v in sorted(participants):
            kernel = self.kernels.get(v)
            if kernel is None:
                continue
            result = kernel.evaluate(self.config.state_of(v), self.observation.observe(self.config, v))
            if result is PENDING:
                continue  # hold state this step
            assert isinstance(result, Step)
            next_states[v] = result.next_state
            if result.updates:
                emitted.append((v, result.updates))

        digraph = self.config.digraph

        # (4) Apply topology updates after the synchronous state update. The
        # per-step creation budget (if any) is shared across all actors.
        remaining = getattr(self.limits, "max_creations_per_step", None)
        for actor, updates in emitted:
            res = topology.apply(
                digraph, next_states, self.kernels, actor, updates,
                mint=self._mint, registry=self.registry,
                limits=self.limits, creations_remaining=remaining,
            )
            digraph, next_states, self.kernels = res.digraph, res.states, res.kernels
            if remaining is not None:
                remaining -= len(res.created)

        # (5) Commit and record.
        self.config = Configuration(digraph, next_states)
        self.step_index += 1
        self.trajectory.record(self.config)
        return self.config

    def run(self, steps: int) -> Configuration:
        for _ in range(steps):
            self.step()
        return self.config
