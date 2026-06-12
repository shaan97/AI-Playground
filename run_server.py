#!/usr/bin/env python3
"""Serve a world over HTTP so agents can live as clients.

The server owns time (a wall-clock heartbeat, default every 10 minutes) and
the world state; agents connect from anywhere with run_client.py (or any
HTTP client) and act at their own pace.

Examples:
    # Fresh world with 3 agent slots, heartbeat every 10 minutes:
    python run_server.py --agents 3

    # Faster world, custom names:
    python run_server.py --names aria,bram --tick-interval 60

    # Then, elsewhere (tokens are printed at startup / in tokens.json):
    python run_client.py --server http://127.0.0.1:8470 --agent aria --token <t>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from world.kernel import World
from world.server import (
    DEFAULT_RATE_LIMIT,
    DEFAULT_TICK_INTERVAL,
    WorldServer,
    load_or_create_tokens,
)

DEFAULT_NAMES = ["aria", "bram", "cleo", "dex", "echo", "fern", "gale", "hugo"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a world of event-driven AI agents.")
    parser.add_argument("--agents", type=int, default=3, help="number of agent slots (new worlds only)")
    parser.add_argument("--names", type=str, default=None,
                        help="comma-separated agent names (overrides --agents)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="bind address (see SAFETY.md before widening)")
    parser.add_argument("--port", type=int, default=8470)
    parser.add_argument("--tick-interval", type=float, default=DEFAULT_TICK_INTERVAL,
                        help="seconds between heartbeat ticks (default 600 = 10 min; 0 disables)")
    parser.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT,
                        help="max actions per agent per minute")
    parser.add_argument("--data-dir", type=Path, default=Path("world_data"),
                        help="where the world lives on disk")
    args = parser.parse_args()

    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    else:
        names = DEFAULT_NAMES[: args.agents]

    # Brains live in remote clients; the server hosts no connectors.
    world = World(root=args.data_dir, connector_factory=lambda i, n: None, agent_names=names)
    tokens = load_or_create_tokens(args.data_dir, list(world.agents))

    server = WorldServer(
        world,
        tokens=tokens,
        host=args.host,
        port=args.port,
        tick_interval=args.tick_interval,
        rate_limit=args.rate_limit,
    )
    print(f"world '{args.data_dir}' at tick {world.tick} — serving on http://{server.host}:{server.port}")
    print(f"heartbeat: every {args.tick_interval:g}s" if args.tick_interval > 0 else "heartbeat: disabled (--admin step only)")
    print(f"agent tokens (also in {args.data_dir}/tokens.json):")
    for name in world.agents:
        print(f"  {name}: {tokens['agents'][name]}")
    print(f"admin token: {tokens['admin']}")
    print("Ctrl-C to stop; world state persists and the server can be restarted.\n")
    server.serve_forever()
    print(f"\nWorld paused at tick {world.tick}. Data in {args.data_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
