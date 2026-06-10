"""Kernel smoke tests using the scripted MockBrain — no API key required.

Run with:  python tests/test_world.py   (or pytest)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from world.kernel import World
from world.llm import MockBrain


def make_world(root: Path) -> World:
    return World(
        root=root,
        brain_factory=lambda index, name: MockBrain(builder=(index == 0)),
        agent_names=["alpha", "beta"],
        quiet=True,
    )


def test_full_run():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        world = make_world(root)
        world.run(ticks=4)

        # Agents persisted memory in their private workspaces.
        for name in ("alpha", "beta"):
            ws = root / "agents" / name / "workspace"
            assert (ws / "identity.md").exists()
            memory = (ws / "memory.md").read_text()
            assert "Turn 1" in memory and "Turn 4" in memory, memory

        # The builder created the beacon; its on_tick ran and mutated state.
        assert "beacon" in world.objects
        beacon = world.objects["beacon"]
        assert beacon.creator == "alpha"
        assert beacon.state["pulses"] >= 1, beacon.state
        # beta touched the beacon after perceiving a pulse event.
        assert beacon.state["touches"] >= 1, beacon.state

        # Everything was logged.
        log_lines = (root / "log" / "events.jsonl").read_text().splitlines()
        kinds = {json.loads(line)["kind"] for line in log_lines}
        assert {"genesis", "message", "object", "object_created", "turn", "interaction"} <= kinds

        # Workspace jail holds.
        agent = world.agents["alpha"]
        result = agent._dispatch("read_file", {"path": "../../../meta.json"})
        assert result.startswith("error:"), result


def test_resume():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        make_world(root).run(ticks=2)
        resumed = make_world(root)
        assert resumed.tick == 2
        assert "beacon" in resumed.objects  # objects reload from disk
        resumed.run(ticks=2)
        assert resumed.tick == 4
        meta = json.loads((root / "meta.json").read_text())
        assert meta["tick"] == 4
        assert meta["agents"] == ["alpha", "beta"]


def test_object_error_routed_to_creator():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        world = make_world(root)
        world.run(ticks=1)
        world.create_object(
            creator="alpha",
            name="broken",
            description="raises on tick",
            behavior_code="def on_tick(state, world, emit):\n    raise RuntimeError('boom')\n",
        )
        world.step()
        log_lines = (root / "log" / "events.jsonl").read_text().splitlines()
        errors = [
            json.loads(line)
            for line in log_lines
            if json.loads(line).get("source") == "broken"
        ]
        assert errors and errors[0]["to"] == "alpha"
        assert "boom" in errors[0]["payload"]["error"]


if __name__ == "__main__":
    test_full_run()
    test_resume()
    test_object_error_routed_to_creator()
    print("all tests passed")
