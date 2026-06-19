"""The registry: a distinguished vertex that makes the world discoverable.

The world has no global directory and no built-in notion of "agent", so a fresh
thing cannot be *told* what else exists — it must discover it. The mechanism is a
single distinguished **registry vertex** ``r`` whose state holds a **ledger** of
the vertex identifiers that exist. A handle reveals *existence, not nature*.

Bootstrap rule (enforced by the engine's registry coupling): every created vertex
``v`` is wired ``r ↔ v`` — so ``r`` observes every newcomer (its ledger lists it
a step later) and every vertex observes ``r`` (so it can read the ledger and then
choose, via its own out-arcs, what to attend to).

`install_registry` adds ``r`` to an initial configuration and couples the
pre-existing vertices to it (the engine only couples vertices *created during a
run*). Pass the returned id as ``GraphDynamicalSystem(..., registry=r)``.

"""

from __future__ import annotations

from typing import Mapping

from .configuration import Configuration, State
from .digraph import Vertex
from .kernel import Result, Step, TransitionKernel

REGISTRY_ID: Vertex = "registry"


class RegistryKernel(TransitionKernel):
    """Maintains the ledger: next state is ``{"ledger": sorted(N⁺(r) ids)}`` —
    the identifiers of the vertices the registry observes. Pure; emits nothing."""

    def evaluate(self, state: State, inputs: dict[Vertex, State]) -> Result:
        return Step({"ledger": sorted(inputs.keys())})


def install_registry(
    config: Configuration,
    kernels: Mapping[Vertex, TransitionKernel],
    registry_id: Vertex = REGISTRY_ID,
) -> tuple[Configuration, dict[Vertex, TransitionKernel], Vertex]:
    """Add a registry vertex coupled ``r ↔ v`` to every existing vertex.

    Returns ``(config, kernels, registry_id)`` with the registry installed
    (initial state ``{"ledger": []}``, kernel `RegistryKernel`). Raises if
    ``registry_id`` already names a vertex.
    """
    if config.digraph.has_vertex(registry_id):
        raise ValueError(f"registry id {registry_id!r} already names a vertex")

    existing = config.vertices()
    # r observes every existing vertex; every existing vertex observes r.
    digraph = config.digraph.with_vertex(registry_id, out=existing)
    for v in existing:
        digraph = digraph.with_arc(v, registry_id)

    new_states = {**config.states, registry_id: {"ledger": []}}
    new_kernels = {**dict(kernels), registry_id: RegistryKernel()}
    return Configuration(digraph, new_states), new_kernels, registry_id
