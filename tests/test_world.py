"""Kernel, sandbox, protocol, and server tests — no API key required.

Run with:  python tests/test_world.py   (or pytest)
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from world import sandbox
from world.client import WorldClient
from world.connectors import MockConnector, ProcessConnector
from world.kernel import World
from world.server import WorldServer


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


def test_subscriptions_filter_broadcasts_not_directs():
    with tempfile.TemporaryDirectory() as tmp:
        world = make_world(Path(tmp) / "w")
        world.ensure_genesis()
        world.inboxes = {name: [] for name in world.agents}  # clear genesis

        result = world.set_subscriptions("beta", ["message"])
        assert "message" in result and not result.startswith("error:")
        assert world.set_subscriptions("beta", ["nonsense"]).startswith("error:")

        world.advance_tick()
        kinds_beta = {e.kind for e in world.inboxes["beta"]}
        kinds_alpha = {e.kind for e in world.inboxes["alpha"]}
        assert "tick" not in kinds_beta, kinds_beta  # unsubscribed
        assert "tick" in kinds_alpha  # default subscription intact

        # Broadcast system events are filtered too...
        world.inject("for everyone", to="all")
        assert not any(e.kind == "system" for e in world.inboxes["beta"])
        # ...but direct events always land, regardless of subscriptions.
        world.inject("for beta only", to="beta")
        world.send_message(source="alpha", to="beta", text="psst")
        texts = [e.payload.get("text") for e in world.inboxes["beta"]]
        assert "for beta only" in texts and "psst" in texts

        # Subscriptions persist across reloads.
        reloaded = make_world(world.root)
        assert reloaded.subscriptions["beta"] == ["message"]


def test_custom_timer_replaces_tick():
    """The pattern subscriptions enable: silence the clock, build your own."""
    with tempfile.TemporaryDirectory() as tmp:
        world = make_world(Path(tmp) / "w")
        world.ensure_genesis()
        world.inboxes = {name: [] for name in world.agents}
        world.set_subscriptions("beta", [])  # total silence from broadcasts
        world.create_object(
            creator="beta",
            name="alarm",
            description="emits a chime to beta every 2 ticks",
            state={},
            behavior_code=(
                "def on_tick(state, world, emit):\n"
                "    if world['tick'] % 2 == 0:\n"
                "        emit({'chime': world['tick']}, to='beta')\n"
            ),
        )
        world.advance_tick()  # tick 1: nothing for beta
        assert world.inboxes["beta"] == []
        world.advance_tick()  # tick 2: chime (direct), but no tick broadcast
        kinds = [(e.kind, e.payload) for e in world.inboxes["beta"]]
        assert kinds == [("object", {"chime": 2})], kinds


def test_server_client_end_to_end():
    """The world as a server; agents joining as clients at their own pace."""
    tokens = {"admin": "adm-token", "agents": {"alpha": "tok-a", "beta": "tok-b"}}

    def http(method, path, token, body=None):
        req = urllib.request.Request(
            f"http://{server.host}:{server.port}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(
            root=Path(tmp) / "w",
            connector_factory=lambda i, n: None,  # brains live in the clients
            agent_names=["alpha", "beta"],
            quiet=True,
        )
        server = WorldServer(world, tokens=tokens, port=0, tick_interval=0)  # manual time
        server.start()
        try:
            # Auth is enforced.
            status, _ = http("GET", "/world", "wrong-token")
            assert status == 403
            status, info = http("GET", "/world", "tok-a")
            assert status == 200 and info["agents"] == ["alpha", "beta"]

            # alpha joins as a client and wakes on its pending genesis event.
            alpha = WorldClient(
                f"http://{server.host}:{server.port}", "alpha", "tok-a",
                MockConnector(builder=True), wait=5, quiet=True,
            )
            assert alpha.run(max_wakes=1) == 1
            with server.lock:
                assert "beacon" in world.objects
                assert not world.inboxes["alpha"]  # acked after the turn

            # beta unsubscribes from ticks via the HTTP action endpoint.
            status, body = http("POST", "/agents/beta/actions", "tok-b",
                                {"name": "set_subscriptions", "input": {"kinds": ["message"]}})
            assert status == 200 and not body["content"].startswith("error:")

            # Admin advances time twice; beacon pulses on even ticks.
            assert http("POST", "/admin/step", "adm-token", {})[1]["tick"] == 1
            assert http("POST", "/admin/step", "adm-token", {})[1]["tick"] == 2
            with server.lock:
                beta_kinds = {e.kind for e in world.inboxes["beta"]}
                alpha_kinds = {e.kind for e in world.inboxes["alpha"]}
            assert "tick" not in beta_kinds, beta_kinds        # unsubscribed
            assert "tick" in alpha_kinds                       # still subscribed
            # beta still has genesis + alpha's greeting + pulse?? — pulse is a
            # broadcast 'object' event, filtered out by beta's subscription.
            assert "object" not in beta_kinds, beta_kinds

            # A direct admin inject reaches beta despite its narrow subscription.
            http("POST", "/admin/inject", "adm-token", {"text": "hello beta", "to": "beta"})
            beta = WorldClient(
                f"http://{server.host}:{server.port}", "beta", "tok-b",
                MockConnector(builder=False), wait=5, quiet=True,
            )
            assert beta.run(max_wakes=1) == 1
            memory = (world.root / "agents" / "beta" / "workspace" / "memory.md").read_text()
            assert "Turn 1" in memory

            # Turn notes from remote clients land in the world log.
            log_text = (world.root / "log" / "events.jsonl").read_text()
            assert '"kind": "turn"' in log_text
        finally:
            server.shutdown()


def test_server_rate_limit():
    tokens = {"admin": "adm", "agents": {"alpha": "tok-a", "beta": "tok-b"}}
    with tempfile.TemporaryDirectory() as tmp:
        world = World(root=Path(tmp) / "w", connector_factory=lambda i, n: None,
                      agent_names=["alpha", "beta"], quiet=True)
        server = WorldServer(world, tokens=tokens, port=0, tick_interval=0, rate_limit=3)
        server.start()
        try:
            client = WorldClient(f"http://{server.host}:{server.port}", "alpha", "tok-a",
                                 None, quiet=True)
            for _ in range(3):
                assert not client.dispatch("observe_world", {}).startswith("error:")
            assert "429" in client.dispatch("observe_world", {})
        finally:
            server.shutdown()


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
