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

from .control import RunControl
from .hub import ViewerHub
from .persistence import RunWriter, load_trajectory, resume_gds, save_run
from .runs import RunStore
from .server import serve_gds, start_server

# `app` (control plane) and `jobs` (supervisor) are imported lazily via their
# modules to keep this package importable even if a subprocess launch context is
# unavailable; import them directly: `from viewer.app import serve`.

__all__ = [
    "ViewerHub", "RunControl", "serve_gds", "start_server",
    "save_run", "load_trajectory", "resume_gds", "RunWriter", "RunStore",
]
