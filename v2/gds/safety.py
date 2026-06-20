"""Engine-level resource guardrails.

Author-written kernel code runs in an isolated subprocess (see `gds._sandbox`),
which bounds a *single* transition's CPU/memory/time. These `Limits` bound the
*system* instead — they stop runaway graph growth (a "fork bomb" of vertices or
an out-degree explosion) by capping what topology updates the engine will apply.

A cap set to ``None`` means unlimited. Over-budget updates are silently dropped,
not errored — a misbehaving thing is contained, the world keeps running.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    # Maximum total vertices in the system; AddVertex beyond it is dropped.
    max_vertices: int | None = None
    # Maximum out-arcs a single vertex may have; AddArc beyond it is dropped.
    max_out_degree: int | None = None
    # Maximum vertices created across all actors in one step.
    max_creations_per_step: int | None = None
