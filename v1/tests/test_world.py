"""Kernel, sandbox, registration, and server/SSE tests — no API key required.

Run with:  python tests/test_world.py   (or pytest)
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import client as C
from world import sandbox
from world.kernel import InvalidName, NameTaken, World
from world.server import WorldServer


def make_world(root: Path) -> World:
    world = World(root=root, quiet=True)
    world.register("alpha")
    world.register("beta")
    return world


# ----------------------------------------------------------------- kernel

def test_registration():
    with tempfile.TemporaryDirectory() as tmp:
        world = World(root=Path(tmp), quiet=True)
        assert world.register("alpha") == "alpha"
        assert "alpha" in world.agents
        # the newcomer is greeted with a direct genesis event
        assert any(e.kind == "genesis" for e in world.inboxes["alpha"])

        # duplicate and invalid names are rejected
        try:
            world.register("alpha")
            assert False, "duplicate name should raise"
        except NameTaken:
            pass
        try:
            world.register("Bad Name")
            assert False, "invalid name should raise"
        except InvalidName:
            pass

        # omitting a name gets one assigned, and others are told someone joined
        before = len(world.inboxes["alpha"])
        assigned = world.register()
        assert assigned in world.agents
        assert any(e.kind == "system" for e in world.inboxes["alpha"][before:])


def test_resume_and_inbox_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        first = make_world(root)
        first.advance_tick()
        first.advance_tick()
        # A message queued after the last tick must survive into the next run;
        # direct kernel mutations don't auto-persist (the server wraps actions
        # with _save_meta), so save explicitly here.
        first.send_message(source="alpha", to="beta", text="see you next run")
        first._save_meta()

        resumed = World(root=root, quiet=True)
        assert resumed.tick == 2
        assert set(resumed.agents) == {"alpha", "beta"}
        texts = [e.payload.get("text") for e in resumed.inboxes["beta"]]
        assert "see you next run" in texts
        meta = json.loads((root / "meta.json").read_text())
        assert meta["tick"] == 2 and meta["agents"] == ["alpha", "beta"]


def test_inject_is_persistent_and_delivered():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        make_world(root).inject("News from outside: rain.", to="all")
        world = World(root=root, quiet=True)  # reload: injection must survive
        texts = [e.payload.get("text") for e in world.inboxes["beta"]]
        assert "News from outside: rain." in texts


def test_object_error_routed_to_creator():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "w"
        world = make_world(root)
        world.create_object(
            creator="alpha", name="broken", description="raises on tick",
            behavior_code="def on_tick(state, world, emit):\n    raise RuntimeError('boom')\n",
        )
        world.advance_tick()
        log_lines = (root / "log" / "events.jsonl").read_text().splitlines()
        errors = [json.loads(x) for x in log_lines if json.loads(x).get("source") == "broken"]
        assert errors and errors[0]["to"] == "alpha"
        assert "boom" in errors[0]["payload"]["error"]


def test_apply_action_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        world = make_world(Path(tmp))
        assert world.apply_action("alpha", "observe_world", {}).startswith("tick:")
        assert world.apply_action("alpha", "create_object",
                                  {"name": "rock", "description": "a rock"}) == "created object 'rock'"
        assert world.apply_action("alpha", "send_message",
                                  {"to": "beta", "text": "hi"}) == "message sent to beta"
        assert world.apply_action("alpha", "send_message",
                                  {"to": "ghost", "text": "?"}).startswith("error:")
        assert world.apply_action("alpha", "no_such_action", {}).startswith("error:")


def test_subscriptions_filter_broadcasts_not_directs():
    with tempfile.TemporaryDirectory() as tmp:
        world = make_world(Path(tmp))
        world.inboxes = {name: [] for name in world.agents}  # clear genesis/join noise

        assert not world.set_subscriptions("beta", ["message"]).startswith("error:")
        assert world.set_subscriptions("beta", ["nonsense"]).startswith("error:")

        world.advance_tick()
        assert "tick" not in {e.kind for e in world.inboxes["beta"]}   # unsubscribed
        assert "tick" in {e.kind for e in world.inboxes["alpha"]}      # default intact

        world.inject("for everyone", to="all")
        assert not any(e.kind == "system" for e in world.inboxes["beta"])
        world.inject("for beta only", to="beta")
        world.send_message(source="alpha", to="beta", text="psst")
        texts = [e.payload.get("text") for e in world.inboxes["beta"]]
        assert "for beta only" in texts and "psst" in texts

        reloaded = World(root=world.root, quiet=True)
        assert reloaded.subscriptions["beta"] == ["message"]


def test_custom_timer_replaces_tick():
    with tempfile.TemporaryDirectory() as tmp:
        world = make_world(Path(tmp))
        world.inboxes = {name: [] for name in world.agents}
        world.set_subscriptions("beta", [])  # total silence from broadcasts
        world.create_object(
            creator="beta", name="alarm", description="chimes beta every 2 ticks", state={},
            behavior_code=(
                "def on_tick(state, world, emit):\n"
                "    if world['tick'] % 2 == 0:\n"
                "        emit({'chime': world['tick']}, to='beta')\n"
            ),
        )
        world.advance_tick()  # tick 1: nothing
        assert world.inboxes["beta"] == []
        world.advance_tick()  # tick 2: chime (direct), no tick broadcast
        assert [(e.kind, e.payload) for e in world.inboxes["beta"]] == [("object", {"chime": 2})]


# ---------------------------------------------------------------- sandbox

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
    assert not res.ok and res.state == {}, res


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


# ----------------------------------------------------------- server + SSE

def _get(url: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _drain(agent: C.WorldClient, n: int, timeout: float = 3.0) -> list[dict]:
    """Collect up to n world events (event is None); ends early on idle timeout."""
    out: list[dict] = []
    gen = agent.events(timeout=timeout)
    try:
        for m in gen:
            if m["event"] is None:
                out.append(m)
                if len(out) >= n:
                    break
    finally:
        gen.close()
    return out


def test_server_client_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        world = World(root=Path(tmp) / "w", quiet=True)
        server = WorldServer(world, tokens={"admin": "adm", "agents": {}}, port=0, tick_interval=0)
        server.start()
        url = f"http://{server.host}:{server.port}"
        try:
            # /spec is open and lists exactly the 7 world actions
            assert len(C.fetch_spec(url)) == 7

            aname, atok = C.register(url, "alpha")
            bname, btok = C.register(url, "beta")
            assert (aname, bname) == ("alpha", "beta")
            try:
                C.register(url, "alpha")
                assert False, "duplicate registration should fail"
            except RuntimeError as e:
                assert "409" in str(e)

            # auth: bad token rejected, agent token accepted
            assert _get(url + "/world", "nope")[0] == 403
            status, info = _get(url + "/world", atok)
            assert status == 200 and "alpha" in info["agents"]

            alpha = C.WorldClient(url, aname, atok)
            beta = C.WorldClient(url, bname, btok)

            # alpha streams hello + its pending events (genesis + "beta joined")
            evs = _drain(alpha, 2)
            kinds = {e["data"]["kind"] for e in evs}
            assert "genesis" in kinds and "system" in kinds, kinds
            genesis_id = next(e["id"] for e in evs if e["data"]["kind"] == "genesis")

            # beta narrows its subscription via the HTTP action endpoint
            assert not beta.act("set_subscriptions", {"kinds": ["message"]}).startswith("error:")
            assert alpha.act("create_object",
                             {"name": "well", "description": "a wishing well"}) == "created object 'well'"

            # admin advances time; alpha (subscribed) gets a tick, beta (not) does not
            req = urllib.request.Request(url + "/admin/step", data=b"{}", method="POST",
                                         headers={"Authorization": "Bearer adm"})
            with urllib.request.urlopen(req) as r:
                assert json.loads(r.read())["tick"] == 1
            with server.lock:
                assert "tick" in {e.kind for e in world.inboxes["alpha"]}
                assert "tick" not in {e.kind for e in world.inboxes["beta"]}

            # at-least-once: alpha never acked genesis, so a fresh stream replays it
            fresh = C.WorldClient(url, aname, atok)  # cursor 0
            assert any(e["data"]["kind"] == "genesis" for e in _drain(fresh, 1))
            # after acking through genesis, it is pruned and no longer replays
            alpha.ack(genesis_id)
            fresh2 = C.WorldClient(url, aname, atok)
            assert not any(e["data"]["kind"] == "genesis" for e in _drain(fresh2, 5, timeout=2.0))

            # turn notes from clients land in the world log
            beta.ack(0, note="hello from beta")
            assert '"kind": "turn"' in (world.root / "log" / "events.jsonl").read_text()
        finally:
            server.shutdown()


def test_server_rate_limit():
    with tempfile.TemporaryDirectory() as tmp:
        world = World(root=Path(tmp) / "w", quiet=True)
        server = WorldServer(world, tokens={"admin": "adm", "agents": {}},
                             port=0, tick_interval=0, rate_limit=3)
        server.start()
        url = f"http://{server.host}:{server.port}"
        try:
            name, token = C.register(url, "alpha")
            agent = C.WorldClient(url, name, token)
            for _ in range(3):
                assert not agent.act("observe_world", {}).startswith("error:")
            assert "429" in agent.act("observe_world", {})
        finally:
            server.shutdown()


def test_registration_gate():
    with tempfile.TemporaryDirectory() as tmp:
        world = World(root=Path(tmp) / "w", quiet=True)
        server = WorldServer(world, tokens={"admin": "adm", "agents": {}},
                             port=0, tick_interval=0, registration_token="sek")
        server.start()
        url = f"http://{server.host}:{server.port}"
        try:
            try:
                C.register(url, "alpha")
                assert False, "ungated registration should fail"
            except RuntimeError as e:
                assert "403" in str(e)
            name, token = C.register(url, "alpha", registration_token="sek")
            assert name == "alpha" and token
        finally:
            server.shutdown()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"ok: {test.__name__}")
    print("all tests passed")
