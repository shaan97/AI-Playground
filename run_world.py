#!/usr/bin/env python3
"""Run the agent world.

Examples:
    # Three Claude-powered agents, five ticks (requires ANTHROPIC_API_KEY):
    python run_world.py --ticks 5

    # Resume the same world for five more ticks:
    python run_world.py --ticks 5

    # Offline smoke run with scripted agents (no API key needed):
    python run_world.py --mock --ticks 4 --data-dir ./mock_world

    # Every agent driven by your own external harness (see PROTOCOL.md):
    python run_world.py --agent-cmd "python examples/external_agent.py" --ticks 3

    # A heterogeneous world — different model/harness per agent:
    python run_world.py --config agents.json --ticks 5

    # Inject a read-only observation from the real world (delivered next wake):
    python run_world.py --inject "News from outside: it is raining in SF." --ticks 0

agents.json format:
    [
      {"name": "aria", "harness": "claude", "model": "claude-opus-4-8", "effort": "medium"},
      {"name": "bram", "harness": "process", "command": "python examples/external_agent.py"},
      {"name": "cleo", "harness": "mock"}
    ]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from world.connectors import (
    DEFAULT_MODEL,
    ClaudeConnector,
    MockConnector,
    ProcessConnector,
)
from world.kernel import World

DEFAULT_NAMES = ["aria", "bram", "cleo", "dex", "echo", "fern", "gale", "hugo"]


def connector_from_spec(spec: dict, args, index: int):
    harness = spec.get("harness", "claude")
    if harness == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            raise SystemExit(
                "Claude harness requires ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN. "
                "Set one, or use --mock / --agent-cmd / a config without claude agents."
            )
        return ClaudeConnector(
            model=spec.get("model", args.model),
            effort=spec.get("effort", args.effort),
            max_tool_iterations=spec.get("max_tool_calls", args.max_tool_calls),
        )
    if harness == "process":
        command = spec.get("command")
        if not command:
            raise SystemExit(f"agent {spec.get('name', index)}: process harness needs a 'command'")
        return ProcessConnector(command, turn_timeout=spec.get("turn_timeout", args.turn_timeout))
    if harness == "mock":
        return MockConnector(builder=spec.get("builder", index == 0))
    raise SystemExit(f"unknown harness {harness!r} (expected claude, process, or mock)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a world of event-driven AI agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples:", 1)[1],
    )
    parser.add_argument("--agents", type=int, default=3, help="number of agents (new worlds only)")
    parser.add_argument("--names", type=str, default=None,
                        help="comma-separated agent names (overrides --agents)")
    parser.add_argument("--ticks", type=int, default=5, help="ticks to simulate this run (0 is allowed)")
    parser.add_argument("--config", type=Path, default=None,
                        help="JSON file: per-agent harness specs (heterogeneous worlds)")
    parser.add_argument("--agent-cmd", type=str, default=None,
                        help="drive every agent with this external command (PROTOCOL.md)")
    parser.add_argument("--mock", action="store_true",
                        help="use scripted MockConnector agents (no API calls)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help="Claude model id (claude harness)")
    parser.add_argument("--effort", type=str, default=None,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help="effort level per agent turn (claude harness)")
    parser.add_argument("--max-tool-calls", type=int, default=16,
                        help="max tool-use iterations per agent turn (claude harness)")
    parser.add_argument("--turn-timeout", type=float, default=600.0,
                        help="wall-clock seconds per external-harness turn (process harness)")
    parser.add_argument("--data-dir", type=Path, default=Path("world_data"),
                        help="where the world lives on disk")
    parser.add_argument("--inject", type=str, default=None,
                        help="inject a system event into the world before running")
    parser.add_argument("--inject-to", type=str, default="all",
                        help="recipient of --inject (agent name or 'all')")
    args = parser.parse_args()

    if args.config:
        specs = json.loads(args.config.read_text())
        names = [spec["name"] for spec in specs]
        spec_by_name = {spec["name"]: spec for spec in specs}
    else:
        if args.names:
            names = [n.strip() for n in args.names.split(",") if n.strip()]
        else:
            names = DEFAULT_NAMES[: args.agents]
        if args.mock:
            default_harness: dict = {"harness": "mock"}
        elif args.agent_cmd:
            default_harness = {"harness": "process", "command": args.agent_cmd}
        else:
            default_harness = {"harness": "claude"}
        spec_by_name = {name: default_harness for name in names}

    def connector_factory(index: int, name: str):
        spec = spec_by_name.get(name)
        if spec is None:
            raise SystemExit(
                f"agent {name!r} exists in this world but has no harness spec — "
                f"this world's roster is {names}; pass a matching --config/--names"
            )
        return connector_from_spec(spec, args, index)

    world = World(root=args.data_dir, connector_factory=connector_factory, agent_names=names)
    if args.inject:
        world.inject(args.inject, to=args.inject_to)
    world.run(args.ticks)
    print(f"\nWorld paused at tick {world.tick}. Data in {args.data_dir}/ — rerun to resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
