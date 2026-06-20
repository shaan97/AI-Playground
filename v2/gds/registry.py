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


def _install_into(
    config: Configuration,
    kernels: Mapping[Vertex, TransitionKernel],
    registry_id: Vertex,
) -> tuple[Configuration, dict[Vertex, TransitionKernel], Vertex]:
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


def install_registry(target, kernels=None, registry_id: Vertex = REGISTRY_ID):
    """Add a registry vertex coupled ``r ↔ v`` to every existing vertex.

    Two calling forms:

    * ``install_registry(config, kernels) -> (config, kernels, registry_id)`` —
      the pure form: returns new config & kernels with the registry installed.
    * ``install_registry(gds) -> registry_id`` — the convenience form: installs
      the registry into a `GraphDynamicalSystem` in place (updating its config,
      kernels, registry, and the recorded initial snapshot) and returns the id.

    The registry vertex gets initial state ``{"ledger": []}`` and a
    `RegistryKernel`. Raises `ValueError` if ``registry_id`` already exists.
    """
    if isinstance(target, Configuration):
        if kernels is None:
            raise TypeError("install_registry(config, kernels): kernels is required")
        return _install_into(target, kernels, registry_id)

    # Convenience form: target is a GraphDynamicalSystem-like engine.
    gds = target
    config, new_kernels, rid = _install_into(gds.config, gds.kernels, registry_id)
    gds.config = config
    gds.kernels = new_kernels
    gds.registry = rid
    # Keep the recorded initial snapshot consistent if no steps have run yet.
    if getattr(gds, "trajectory", None) is not None and len(gds.trajectory) == 1:
        gds.trajectory.snapshots[0] = config
    return rid
