#!/usr/bin/env python3
"""Serve a world over HTTP. Agents join as clients and act at their own pace.

The world starts empty by default; agents register themselves (open
registration). Pass --names/--agents to pre-seed identities and print their
tokens, or --registration-token to gate who may join.

The server owns time (a wall-clock heartbeat, default every 10 minutes) and the
world state; clients connect from anywhere (see client.py / examples/) and
stream events, act, and acknowledge.

Examples:
    # Empty world; agents self-register, heartbeat every 10 minutes:
    python run_server.py

    # Faster world with two pre-seeded agents (tokens printed at startup):
    python run_server.py --names aria,bram --tick-interval 60

    # Gate registration behind a shared secret:
    python run_server.py --registration-token s3cret
"""

from __future__ import annotations

import argparse
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
    parser.add_argument("--agents", type=int, default=0,
                        help="number of agent slots to pre-seed (default 0; agents can self-register)")
    parser.add_argument("--names", type=str, default=None,
                        help="comma-separated agent names to pre-seed (overrides --agents)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="bind address (see SAFETY.md before widening)")
    parser.add_argument("--port", type=int, default=8470)
    parser.add_argument("--tick-interval", type=float, default=DEFAULT_TICK_INTERVAL,
                        help="seconds between heartbeat ticks (default 600 = 10 min; 0 disables)")
    parser.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT,
                        help="max actions per agent per minute")
    parser.add_argument("--registration-token", type=str, default=None,
                        help="require this token (X-Registration-Token header) to register")
    parser.add_argument("--data-dir", type=Path, default=Path("world_data"),
                        help="where the world lives on disk")
    args = parser.parse_args()

    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    else:
        names = DEFAULT_NAMES[: args.agents]

    world = World(root=args.data_dir)
    tokens = load_or_create_tokens(args.data_dir)
    server = WorldServer(
        world,
        tokens=tokens,
        host=args.host,
        port=args.port,
        tick_interval=args.tick_interval,
        rate_limit=args.rate_limit,
        registration_token=args.registration_token,
    )

    # Pre-seed any requested names that don't already exist (mints + prints tokens).
    for name in names:
        if name not in world.agents:
            server.register_agent(name)

    print(f"world '{args.data_dir}' at tick {world.tick} — serving on http://{server.host}:{server.port}")
    print(f"heartbeat: every {args.tick_interval:g}s" if args.tick_interval > 0
          else "heartbeat: disabled (--admin step only)")
    print(f"registration: {'gated by --registration-token' if args.registration_token else 'open'}")
    if world.agents:
        print(f"agent tokens (also in {args.data_dir}/tokens.json):")
        for name in world.agents:
            print(f"  {name}: {tokens['agents'].get(name, '(unknown)')}")
    else:
        print("no agents yet — clients can POST /register to join")
    print(f"admin token: {tokens['admin']}")
    print("Ctrl-C to stop; world state persists and the server can be restarted.\n")
    server.serve_forever()
    print(f"\nWorld paused at tick {world.tick}. Data in {args.data_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
