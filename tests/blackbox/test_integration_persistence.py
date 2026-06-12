"""Integration: persistence and resume semantics (docs/INTERFACES.md §world.kernel,
Persistence) plus object-failure routing (§world.objects)."""
import json

from conftest import none_factory

from world.connectors import MockConnector
from world.kernel import World


def mock_factory(index, name):
    return MockConnector(builder=(index == 0))


# -------------------------------------------------------------------- resume

def test_resume_restores_tick_seq_roster_subscriptions_objects(tmp_path):
    w1 = World(tmp_path, mock_factory, ["aria", "bram"], quiet=True)
    w1.run(3)
    assert not w1.set_subscriptions("bram", ["message", "system"]).startswith("error:")
    assert not w1.create_object("aria", "obelisk", "tall and dark",
                                state={"height": 9}).startswith("error:")
    tick1, seq1 = w1.tick, w1.seq
    del w1

    # different agent_names argument: persisted roster must win
    w2 = World(tmp_path, mock_factory, ["xeno", "yara", "zulu"], quiet=True)
    assert list(w2.agents) == ["aria", "bram"]
    assert w2.tick == tick1
    assert w2.seq == seq1
    assert set(w2.subscriptions["bram"]) == {"message", "system"}
    assert "obelisk" in w2.objects
    assert w2.objects["obelisk"].state == {"height": 9}
    assert w2.objects["obelisk"].description == "tall and dark"
    assert "beacon" in w2.objects  # mock builder's object survived too


def test_genesis_idempotent_across_restarts_and_inboxes_survive(tmp_path):
    w1 = World(tmp_path, none_factory, ["aria", "bram"], quiet=True)
    w1.ensure_genesis()
    assert len(w1.inboxes["aria"]) == 1
    del w1

    w2 = World(tmp_path, none_factory, ["aria", "bram"], quiet=True)
    # undelivered genesis events survived the reload
    assert [e.kind for e in w2.inboxes["aria"]] == ["genesis"]
    assert [e.kind for e in w2.inboxes["bram"]] == ["genesis"]
    # and ensure_genesis is idempotent across process restarts
    w2.ensure_genesis()
    assert len(w2.inboxes["aria"]) == 1


def test_inject_into_not_running_world_survives_reload(tmp_path):
    w1 = World(tmp_path, none_factory, ["aria"], quiet=True)
    w1.inject("operator note: comet sighted", to="all")
    del w1  # never ran; inject must have persisted immediately

    w2 = World(tmp_path, none_factory, ["aria"], quiet=True)
    box = w2.inboxes["aria"]
    assert any(e.kind == "system" and
               "comet sighted" in json.dumps(e.payload) for e in box)


def test_meta_json_documented_keys(tmp_path):
    w = World(tmp_path, mock_factory, ["aria", "bram"], quiet=True)
    w.run(1)
    meta = json.loads((tmp_path / "meta.json").read_text())
    for key in ("tick", "seq", "agents", "genesis_done", "subscriptions", "inboxes"):
        assert key in meta, key


# ----------------------------------------------------- object failure routing

BROKEN_TICK = (
    "def on_tick(state, world, emit):\n"
    "    raise ValueError('boom-on-tick')\n"
)


def test_on_tick_failure_routed_directly_to_creator(tmp_path):
    w = World(tmp_path, none_factory, ["aria", "bram"], quiet=True)
    assert not w.create_object("aria", "bomb", "unstable", state={"fuse": 3},
                               behavior_code=BROKEN_TICK).startswith("error:")
    w.advance_tick()
    # creator got a direct object event with an "error" payload key
    errs = [e for e in w.inboxes["aria"]
            if e.kind == "object" and "error" in e.payload]
    assert len(errs) >= 1
    assert errs[0].to == "aria"
    # non-creator got no error event
    assert not any(e.kind == "object" and "error" in e.payload
                   for e in w.inboxes["bram"])
    # the object's state is left unchanged
    assert w.objects["bomb"].state == {"fuse": 3}


def test_on_tick_timeout_also_routed_to_creator(tmp_path):
    w = World(tmp_path, none_factory, ["aria"], quiet=True)
    code = "def on_tick(state, world, emit):\n    while True:\n        pass\n"
    w.create_object("aria", "spinner", "spins forever", state={"v": 1},
                    behavior_code=code)
    w.advance_tick()
    errs = [e for e in w.inboxes["aria"]
            if e.kind == "object" and "error" in e.payload]
    assert len(errs) >= 1
    assert w.objects["spinner"].state == {"v": 1}


def test_on_interact_failure_reported_to_caller_not_creator(tmp_path):
    w = World(tmp_path, none_factory, ["aria", "bram"], quiet=True)
    code = ("def on_interact(state, action, source, emit):\n"
            "    raise RuntimeError('boom-on-interact')\n")
    w.create_object("aria", "trap", "snaps shut", behavior_code=code)
    r = w.interact_with_object("bram", "trap", "poke")
    # hook's own failure is descriptive information, not an API error
    assert isinstance(r, str) and r
    assert not r.startswith("error:")
    # ...but it does report that something went wrong
    assert "boom-on-interact" in r or "error" in r.lower() or "fail" in r.lower()


def test_healthy_on_tick_persists_new_state_and_emits(tmp_path):
    w = World(tmp_path, none_factory, ["aria", "bram"], quiet=True)
    code = ("def on_tick(state, world, emit):\n"
            "    state['count'] = state.get('count', 0) + 1\n"
            "    emit({'count': state['count']})\n")
    w.create_object("aria", "counter", "counts ticks", behavior_code=code)
    w.advance_tick()
    w.advance_tick()
    assert w.objects["counter"].state["count"] == 2
    # state persisted on disk too
    disk = json.loads((tmp_path / "objects" / "counter" / "state.json").read_text())
    assert disk["count"] == 2
    # emitted object events were published (broadcast -> both agents)
    for name in ("aria", "bram"):
        assert any(e.kind == "object" and e.source == "counter"
                   for e in w.inboxes[name]), name
