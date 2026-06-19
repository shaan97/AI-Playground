#!/usr/bin/env python3
"""A scripted, model-free agent — the demo and test 'brain'.

Stateless between wakes like a real agent: its memory is a plain local file
(client-side, invisible to the world), and what it does is derived from the
event that woke it. Built on the thin client (client.py): it registers itself
and consumes the SSE event stream, reaching the world only through world
operations.

    python examples/scripted_agent.py --server http://127.0.0.1:8470 [--builder]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from client import WorldClient  # noqa: E402

BEACON_BEHAVIOR = (
    "def on_tick(state, world, emit):\n"
    "    if world['tick'] % 2 == 0:\n"
    "        state['pulses'] += 1\n"
    "        emit({'pulse': state['pulses']})\n"
    "\n"
    "def on_interact(state, action, source, emit):\n"
    "    state['touches'] += 1\n"
    "    return {'touched_by': source, 'total_touches': state['touches']}\n"
)


def main() -> int:
    p = argparse.ArgumentParser(description="A scripted agent client.")
    p.add_argument("--server", required=True, help="world server URL")
    p.add_argument("--name", default=None, help="desired name (default: server-assigned)")
    p.add_argument("--builder", action="store_true", help="create the beacon at genesis")
    p.add_argument("--workspace", default=None, help="local memory dir (default: ./agent-workspaces/<name>)")
    p.add_argument("--max-wakes", type=int, default=5, help="exit after this many events")
    p.add_argument("--registration-token", default=None)
    p.add_argument("--timeout", type=float, default=30.0,
                   help="end if no event arrives for this many seconds")
    args = p.parse_args()

    agent = WorldClient.join(args.server, name=args.name, registration_token=args.registration_token)
    workspace = Path(args.workspace) if args.workspace else REPO / "agent-workspaces" / agent.agent
    workspace.mkdir(parents=True, exist_ok=True)
    identity, memory = workspace / "identity.md", workspace / "memory.md"
    print(f"[{agent.agent}] joined {args.server}")

    wakes = 0
    for msg in agent.events(timeout=args.timeout):
        if msg["event"] == "hello":
            continue
        note = handle(agent, msg["data"], args.builder, identity, memory)
        agent.ack(msg["id"], note=note)
        print(f"[{agent.agent}] {note}")
        wakes += 1
        if wakes >= args.max_wakes:
            break
    print(f"[{agent.agent}] done after {wakes} wake(s)")
    return 0


def handle(agent: WorldClient, event: dict, builder: bool, identity: Path, memory: Path) -> str:
    kind = event.get("kind")
    payload = event.get("payload", {})
    if kind == "genesis":
        identity.write_text("I am a scripted agent in a demo world.\n")
        memory.write_text("Woke for the first time.\n")
        agent.act("send_message", {"to": "all", "text": "Hello, world. I exist."})
        if builder:
            agent.act("create_object", {
                "name": "beacon",
                "description": "A beacon that pulses every other tick and counts touches.",
                "state": {"pulses": 0, "touches": 0},
                "behavior_code": BEACON_BEHAVIOR,
            })
            return "Greeted everyone and lit a beacon."
        return "Greeted everyone."
    if not builder and "pulse" in payload:
        agent.act("interact_with_object", {"name": "beacon", "action": {"touch": True}})
        _append(memory, "Felt a pulse; touched the beacon.")
        return "Felt the beacon pulse and touched it."
    _append(memory, f"Saw a {kind} event.")
    return f"Noted a {kind} event."


def _append(path: Path, line: str) -> None:
    with path.open("a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
