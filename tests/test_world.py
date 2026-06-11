"""Kernel, sandbox, and protocol tests — no API key required.

Run with:  python tests/test_world.py   (or pytest)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from world import sandbox
from world.connectors import MockConnector, ProcessConnector
from world.kernel import World


def make_world(root: Path) -> World:
    return World(
        root=root,
        connector_factory=lambda index, name: MockConnector(builder=(index == 0)),
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

        # The builder created the beacon; its on_tick ran (sandboxed) and
        # mutated state.
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
        result = agent.dispatch("read_file", {"path": "../../../meta.json"})
        assert result.startswith("error:"), result


def test_resume_and_inbox_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        first = make_world(root)
        first.run(ticks=2)
        # A message queued after the run ends must survive into the next run.
        first.send_message(source="alpha", to="beta", text="see you next run")
        first._save_meta()

        resumed = make_world(root)
        assert resumed.tick == 2
        assert "beacon" in resumed.objects  # objects reload from disk
        pending = [e for e in resumed.inboxes["beta"] if e.kind == "message"]
        assert any(e.payload["text"] == "see you next run" for e in pending)
        resumed.run(ticks=2)
        assert resumed.tick == 4
        meta = json.loads((root / "meta.json").read_text())
        assert meta["tick"] == 4
        assert meta["agents"] == ["alpha", "beta"]


def test_inject_is_persistent_and_delivered():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        make_world(root).inject("News from outside: rain.", to="all")
        world = make_world(root)  # reload: injection must survive
        texts = [e.payload.get("text") for e in world.inboxes["beta"]]
        assert "News from outside: rain." in texts


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


def test_sandbox_blocks_imports_and_files():
    res = sandbox.run_hook(
        code="import os\ndef on_tick(state, world, emit):\n    pass\n",
        hook="on_tick", state={},
    )
    assert not res.ok and "ImportError" in (res.error or ""), res

    res = sandbox.run_hook(
        code="def on_tick(state, world, emit):\n    open('/etc/passwd')\n",
        hook="on_tick", state={},
    )
    assert not res.ok and "open" in (res.error or ""), res


def test_sandbox_kills_infinite_loop():
    res = sandbox.run_hook(
        code="def on_tick(state, world, emit):\n    while True:\n        pass\n",
        hook="on_tick", state={}, cpu_seconds=1, wall_timeout=5,
    )
    assert not res.ok, res
    assert res.state == {}  # state untouched on failure


def test_sandbox_allows_math_and_emit():
    res = sandbox.run_hook(
        code=(
            "def on_tick(state, world, emit):\n"
            "    state['root'] = math.sqrt(16)\n"
            "    emit({'hello': True}, to='alpha')\n"
        ),
        hook="on_tick", state={},
    )
    assert res.ok, res.error
    assert res.state == {"root": 4.0}
    assert res.emitted == [{"payload": {"hello": True}, "to": "alpha"}]


def test_process_harness_end_to_end():
    """An external program speaking PROTOCOL.md drives an agent."""
    cmd = [sys.executable, str(REPO / "examples" / "external_agent.py")]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"

        def factory(index, name):
            if name == "ext":
                return ProcessConnector(cmd, turn_timeout=60)
            return MockConnector(builder=False)

        world = World(root=root, connector_factory=factory,
                      agent_names=["ext", "buddy"], quiet=True)
        world.run(ticks=2)

        # The external harness created the guestbook at genesis...
        assert "guestbook" in world.objects
        guestbook = world.objects["guestbook"]
        assert guestbook.creator == "ext"
        # ...and signed it on tick 2 after hearing buddy's greeting.
        assert len(guestbook.state["entries"]) >= 1, guestbook.state
        # It also wrote memory via direct filesystem access to its workspace.
        memory = (root / "agents" / "ext" / "workspace" / "memory.md").read_text()
        assert "tick 1" in memory and "tick 2" in memory, memory
        # Turn notes from the harness made it into the log.
        log_text = (root / "log" / "events.jsonl").read_text()
        assert "Introduced myself and opened a guestbook." in log_text


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"ok: {test.__name__}")
    print("all tests passed")
