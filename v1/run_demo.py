#!/usr/bin/env python3
"""One-command end-to-end demo: a world server plus a couple of agents.

The agents run as **separate client processes** (examples/scripted_agent.py) —
real clients, no in-process privilege — so this exercises the same path a
remote Claude/Ollama/etc. agent would. No API key needed; the agents are
scripted. State is ephemeral (a temp directory) so the demo is repeatable.

    python run_demo.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from world.kernel import World
from world.server import WorldServer, load_or_create_tokens

REPO = Path(__file__).resolve().parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="demo_world_") as tmp:
        data_dir = Path(tmp)
        world = World(root=data_dir, quiet=True)
        tokens = load_or_create_tokens(data_dir)
        # Fast heartbeat so the demo finishes quickly; open registration.
        server = WorldServer(world, tokens=tokens, port=0, tick_interval=1.0)
        server.start()
        url = f"http://{server.host}:{server.port}"
        print(f"demo world serving on {url} (ephemeral state in {data_dir})\n")

        agent_script = str(REPO / "examples" / "scripted_agent.py")
        launches = [
            [sys.executable, agent_script, "--server", url, "--builder", "--max-wakes", "5"],
            [sys.executable, agent_script, "--server", url, "--max-wakes", "5"],
        ]
        procs = [subprocess.Popen(cmd) for cmd in launches]
        try:
            for p in procs:
                p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            for p in procs:
                p.kill()
        finally:
            time.sleep(0.5)
            with server.lock:
                print("\n=== final world ===")
                print(world.digest())
            server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
