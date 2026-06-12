#!/usr/bin/env python3
"""Run one agent as a client of a world server.

The agent's brain runs here, on your machine, at your expense and cadence;
only its actions reach the world. Any connector works: Claude, your own
external harness (PROTOCOL.md), or the offline mock.

Examples:
    # A Claude-driven agent (requires ANTHROPIC_API_KEY here, not on the server):
    python run_client.py --server http://127.0.0.1:8470 --agent aria --token <t>

    # Your own harness driving the agent:
    python run_client.py --server ... --agent bram --token <t> \
        --agent-cmd "python examples/external_agent.py"

    # Offline scripted agent:
    python run_client.py --server ... --agent cleo --token <t> --mock
"""

from __future__ import annotations

import argparse
import os

from world.client import WorldClient
from world.connectors import (
    DEFAULT_MODEL,
    ClaudeConnector,
    MockConnector,
    ProcessConnector,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an agent as a client of a world server.")
    parser.add_argument("--server", type=str, required=True, help="world server URL")
    parser.add_argument("--agent", type=str, required=True, help="agent name on the server")
    parser.add_argument("--token", type=str, default=os.environ.get("WORLD_TOKEN"),
                        help="agent bearer token (or set WORLD_TOKEN)")
    parser.add_argument("--wait", type=float, default=60.0,
                        help="long-poll seconds per wake request")
    parser.add_argument("--max-wakes", type=int, default=None,
                        help="exit after this many wakes (default: run forever)")
    parser.add_argument("--agent-cmd", type=str, default=None,
                        help="drive the agent with this external command (PROTOCOL.md)")
    parser.add_argument("--mock", action="store_true", help="scripted MockConnector (no API calls)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Claude model id")
    parser.add_argument("--effort", type=str, default=None,
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-tool-calls", type=int, default=16)
    parser.add_argument("--turn-timeout", type=float, default=600.0)
    args = parser.parse_args()

    if not args.token:
        parser.error("--token (or WORLD_TOKEN) is required")

    if args.mock:
        connector = MockConnector(builder=True)
    elif args.agent_cmd:
        connector = ProcessConnector(args.agent_cmd, turn_timeout=args.turn_timeout)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            parser.error("Claude connector requires ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN "
                         "(or use --mock / --agent-cmd)")
        connector = ClaudeConnector(
            model=args.model,
            effort=args.effort,
            max_tool_iterations=args.max_tool_calls,
        )

    client = WorldClient(
        server_url=args.server,
        agent=args.agent,
        token=args.token,
        connector=connector,
        wait=args.wait,
    )
    print(f"[{args.agent}] joining world at {args.server} — Ctrl-C to leave")
    try:
        client.run(max_wakes=args.max_wakes)
    except KeyboardInterrupt:
        print(f"\n[{args.agent}] left the world (its inbox keeps accumulating server-side)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
