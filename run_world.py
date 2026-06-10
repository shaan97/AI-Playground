#!/usr/bin/env python3
"""Run the agent world.

Examples:
    # Three Claude-powered agents, five ticks (requires ANTHROPIC_API_KEY):
    python run_world.py --ticks 5

    # Resume the same world for five more ticks:
    python run_world.py --ticks 5

    # Offline smoke run with scripted agents (no API key needed):
    python run_world.py --mock --ticks 4 --data-dir ./mock_world
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from world.kernel import World
from world.llm import DEFAULT_MODEL, ClaudeBrain, MockBrain

DEFAULT_NAMES = ["aria", "bram", "cleo", "dex", "echo", "fern", "gale", "hugo"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a world of event-driven AI agents.")
    parser.add_argument("--agents", type=int, default=3, help="number of agents (new worlds only)")
    parser.add_argument("--names", type=str, default=None,
                        help="comma-separated agent names (overrides --agents)")
    parser.add_argument("--ticks", type=int, default=5, help="ticks to simulate this run")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Claude model id")
    parser.add_argument("--effort", type=str, default=None,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help="effort level per agent turn (default: API default)")
    parser.add_argument("--max-tool-calls", type=int, default=16,
                        help="max tool-use iterations per agent turn")
    parser.add_argument("--data-dir", type=Path, default=Path("world_data"),
                        help="where the world lives on disk")
    parser.add_argument("--mock", action="store_true",
                        help="use scripted MockBrain agents (no API calls)")
    args = parser.parse_args()

    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    else:
        names = DEFAULT_NAMES[: args.agents]

    if args.mock:
        def brain_factory(index: int, name: str):
            return MockBrain(builder=(index == 0))
    else:
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            print(
                "No ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN set. "
                "Set one, or use --mock for an offline run.",
                file=sys.stderr,
            )
            return 1

        def brain_factory(index: int, name: str):
            return ClaudeBrain(
                model=args.model,
                effort=args.effort,
                max_tool_iterations=args.max_tool_calls,
            )

    world = World(root=args.data_dir, brain_factory=brain_factory, agent_names=names)
    world.run(args.ticks)
    print(f"\nWorld paused at tick {world.tick}. Data in {args.data_dir}/ — rerun to resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
