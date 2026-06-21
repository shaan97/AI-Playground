"""A phone-first web viewer for the v2 graph dynamical substrate.

Watch a `GraphDynamicalSystem` evolve live (or scrub its history): see the graph,
tap a vertex to inspect its state and neighbourhood, and read an agent's per-turn
trace. The viewer observes the world without altering its dynamics.

Quick start::

    from gds import GraphDynamicalSystem, ...
    from viewer import serve_gds

    gds = build_my_world()
    serve_gds(gds, steps=50, delay=1.0)  # prints the URLs to open on your phone

See `examples/viewer_demo.py` for a runnable, model-free example.
"""

from __future__ import annotations

from .hub import ViewerHub
from .server import serve_gds, start_server

__all__ = ["ViewerHub", "serve_gds", "start_server"]
