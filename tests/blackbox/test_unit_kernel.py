"""Unit tests for world.kernel.World per docs/INTERFACES.md §world.kernel."""
import copy
import json

from conftest import RecordingConnector, none_factory, read_log_records

from world.events import Event
from world.kernel import World


def make_world(tmp_path, names=("aria", "bram")):
    return World(tmp_path, none_factory, list(names), quiet=True)


def inbox_kinds(world, name):
    return [e.kind for e in world.inboxes[name]]


# ----------------------------------------------------------- basic structure

def test_fresh_world_attributes(tmp_path):
    w = make_world(tmp_path)
    assert w.tick == 0
    assert w.seq == 0
    assert list(w.agents) == ["aria", "bram"]  # insertion order = roster order
    assert w.objects == {}
    assert w.inboxes["aria"] == [] and w.inboxes["bram"] == []
    # default subscriptions: all five kinds
    for name in ("aria", "bram"):
        assert set(w.subscriptions[name]) == {
            "genesis", "tick", "message", "object", "system"}


def test_root_directory_created_if_needed(tmp_path):
    root = tmp_path / "deep" / "world"
    make_world(root)
    assert root.is_dir()


# -------------------------------------------------------------- publish/seq

def test_publish_assigns_sequence_numbers_starting_at_one(tmp_path):
    w = make_world(tmp_path)
    e1 = Event(kind="message", tick=0, source="aria", payload={"text": "a"})
    e2 = Event(kind="message", tick=0, source="aria", payload={"text": "b"})
    w.publish(e1)
    w.publish(e2)
    assert e1.seq == 1
    assert e2.seq == 2
    assert w.seq == 2


def test_publish_appends_to_event_log(tmp_path):
    w = make_world(tmp_path)
    w.publish(Event(kind="message", tick=0, source="aria", payload={"text": "logme"}))
    recs = read_log_records(tmp_path)
    assert any(r.get("kind") == "message" and r.get("payload", {}).get("text") == "logme"
               for r in recs)


def test_broadcast_excludes_source_agent(tmp_path):
    w = make_world(tmp_path)
    w.publish(Event(kind="message", tick=0, source="aria", to="all",
                    payload={"text": "hi"}))
    assert inbox_kinds(w, "bram") == ["message"]
    assert w.inboxes["aria"] == []


def test_broadcast_filtered_by_subscriptions(tmp_path):
    w = make_world(tmp_path)
    r = w.set_subscriptions("bram", ["message"])
    assert not r.startswith("error:")
    w.publish(Event(kind="tick", tick=1, source="world", to="all"))
    assert inbox_kinds(w, "bram") == []          # tick filtered out
    assert inbox_kinds(w, "aria") == ["tick"]    # aria still subscribed
    w.publish(Event(kind="message", tick=1, source="aria", to="all",
                    payload={"text": "yo"}))
    assert inbox_kinds(w, "bram") == ["message"]


def test_direct_events_always_delivered_regardless_of_subscriptions(tmp_path):
    w = make_world(tmp_path)
    assert not w.set_subscriptions("bram", []).startswith("error:")
    w.publish(Event(kind="tick", tick=1, source="world", to="bram"))
    assert inbox_kinds(w, "bram") == ["tick"]
    # and not delivered to anyone else
    assert inbox_kinds(w, "aria") == []


def test_publish_to_unknown_agent_is_logged_but_undelivered(tmp_path):
    w = make_world(tmp_path)
    w.publish(Event(kind="message", tick=0, source="aria", to="ghost",
                    payload={"text": "anyone?"}))  # must not raise
    assert w.inboxes["aria"] == []
    assert w.inboxes["bram"] == []
    assert w.seq == 1  # still sequenced and logged
    recs = read_log_records(tmp_path)
    assert any(r.get("to") == "ghost" for r in recs)


# ---------------------------------------------------------- set_subscriptions

def test_set_subscriptions_unknown_kind_is_error_and_unchanged(tmp_path):
    w = make_world(tmp_path)
    before = list(w.subscriptions["aria"])
    r = w.set_subscriptions("aria", ["message", "weather"])
    assert r.startswith("error:")
    assert list(w.subscriptions["aria"]) == before


def test_set_subscriptions_empty_list_is_valid(tmp_path):
    w = make_world(tmp_path)
    r = w.set_subscriptions("aria", [])
    assert not r.startswith("error:")
    assert list(w.subscriptions["aria"]) == []


# ------------------------------------------------------------ time and turns

def test_ensure_genesis_publishes_one_direct_genesis_per_agent(tmp_path):
    w = make_world(tmp_path)
    w.ensure_genesis()
    for name in ("aria", "bram"):
        box = w.inboxes[name]
        assert len(box) == 1
        e = box[0]
        assert e.kind == "genesis"
        assert e.tick == 0
        assert e.source == "world"
        assert e.to == name
    # idempotent within a process
    w.ensure_genesis()
    assert len(w.inboxes["aria"]) == 1


def test_advance_tick_increments_and_broadcasts_one_tick_event(tmp_path):
    w = make_world(tmp_path)
    w.advance_tick()
    assert w.tick == 1
    assert inbox_kinds(w, "aria") == ["tick"]
    assert inbox_kinds(w, "bram") == ["tick"]
    assert w.inboxes["aria"][0].source == "world"
    assert w.inboxes["aria"][0].to == "all"


def test_advance_tick_does_not_wake_agents(tmp_path):
    conns = {}

    def factory(i, name):
        conns[name] = RecordingConnector()
        return conns[name]

    w = World(tmp_path, factory, ["aria", "bram"], quiet=True)
    w.advance_tick()
    assert conns["aria"].wakes == []
    assert conns["bram"].wakes == []


def test_step_wakes_nonempty_inboxes_and_consumes_them(tmp_path):
    conns = {}

    def factory(i, name):
        conns[name] = RecordingConnector()
        return conns[name]

    w = World(tmp_path, factory, ["aria", "bram"], quiet=True)
    # bram silences all broadcasts -> empty inbox after the tick -> skipped
    w.set_subscriptions("bram", [])
    w.publish(Event(kind="message", tick=0, source="bram", to="aria",
                    payload={"text": "psst"}))
    w.step()
    assert len(conns["aria"].wakes) == 1
    assert len(conns["bram"].wakes) == 0
    wake = conns["aria"].wakes[0]
    kinds = [e["kind"] for e in wake["events"]]
    assert "message" in kinds and "tick" in kinds  # inbox consumed wholesale
    assert w.inboxes["aria"] == []


def test_run_zero_ticks_is_valid_and_runs_genesis(tmp_path):
    w = make_world(tmp_path)
    w.run(0)
    assert w.tick == 0
    assert inbox_kinds(w, "aria") == ["genesis"]


def test_ack_removes_events_up_to_cursor(tmp_path):
    w = make_world(tmp_path)
    for txt in ("one", "two", "three"):
        w.publish(Event(kind="message", tick=0, source="bram", to="aria",
                        payload={"text": txt}))
    seqs = [e.seq for e in w.inboxes["aria"]]
    assert seqs == [1, 2, 3]
    w.ack("aria", 2)
    assert [e.seq for e in w.inboxes["aria"]] == [3]


def test_record_turn_appends_turn_record_to_log(tmp_path):
    w = make_world(tmp_path)
    w.record_turn("aria", "I pondered the void.")
    recs = read_log_records(tmp_path)
    turns = [r for r in recs if r.get("kind") == "turn"]
    assert turns
    assert any("I pondered the void." in json.dumps(r) for r in turns)


# ------------------------------------------------------------------- inject

def test_inject_publishes_system_event(tmp_path):
    w = make_world(tmp_path)
    w.inject("it is raining", to="all")
    for name in ("aria", "bram"):
        box = w.inboxes[name]
        assert len(box) == 1
        assert box[0].kind == "system"
        assert "it is raining" in json.dumps(box[0].payload)


def test_inject_direct_to_one_agent(tmp_path):
    w = make_world(tmp_path)
    w.inject("only for you", to="bram")
    assert inbox_kinds(w, "bram") == ["system"]
    assert inbox_kinds(w, "aria") == []


# ------------------------------------------------------------------- objects

def test_create_object_success_and_disk_layout(tmp_path):
    w = make_world(tmp_path)
    r = w.create_object("aria", "lamp-1", "a small lamp", state={"lit": False})
    assert not r.startswith("error:")
    assert "lamp-1" in w.objects
    obj_dir = tmp_path / "objects" / "lamp-1"
    assert obj_dir.is_dir()
    manifest = json.loads((obj_dir / "manifest.json").read_text())
    assert manifest["name"] == "lamp-1"
    assert manifest["creator"] == "aria"
    assert "description" in manifest and "created_tick" in manifest
    assert json.loads((obj_dir / "state.json").read_text()) == {"lit": False}


def test_create_object_invalid_names_rejected(tmp_path):
    w = make_world(tmp_path)
    for bad in ("Bad", "has space", "-leading", "_leading", "Ümlaut", ""):
        r = w.create_object("aria", bad, "nope")
        assert r.startswith("error:"), bad
        assert bad not in w.objects


def test_create_object_duplicate_rejected(tmp_path):
    w = make_world(tmp_path)
    assert not w.create_object("aria", "rock", "a rock").startswith("error:")
    r = w.create_object("bram", "rock", "another rock")
    assert r.startswith("error:")


def test_update_object_replaces_provided_fields_only(tmp_path):
    w = make_world(tmp_path)
    w.create_object("aria", "chest", "a chest", state={"a": 1, "b": 2})
    r = w.update_object("aria", "chest", state={"c": 3})
    assert not r.startswith("error:")
    obj = w.objects["chest"]
    assert obj.state == {"c": 3}            # full replacement, not merge
    assert obj.description == "a chest"     # untouched field survives
    r = w.update_object("aria", "chest", description="a sturdy chest")
    assert not r.startswith("error:")
    assert w.objects["chest"].description == "a sturdy chest"
    assert w.objects["chest"].state == {"c": 3}


def test_update_object_any_agent_may_update(tmp_path):
    w = make_world(tmp_path)
    w.create_object("aria", "wall", "a wall")
    r = w.update_object("bram", "wall", description="a painted wall")
    assert not r.startswith("error:")
    assert w.objects["wall"].description == "a painted wall"


def test_update_object_unknown_is_error(tmp_path):
    w = make_world(tmp_path)
    assert w.update_object("aria", "ghost", description="x").startswith("error:")


def test_inspect_object_contents(tmp_path):
    w = make_world(tmp_path)
    code = "def on_interact(state, action, source, emit):\n    return 'hello-inspector'\n"
    w.create_object("aria", "shrine", "a quiet shrine",
                    state={"offerings": 7}, behavior_code=code)
    r = w.inspect_object("shrine")
    assert not r.startswith("error:")
    assert "shrine" in r
    assert "aria" in r
    assert "a quiet shrine" in r
    assert "offerings" in r and "7" in r
    assert "hello-inspector" in r  # behavior source included


def test_inspect_object_unknown_is_error(tmp_path):
    w = make_world(tmp_path)
    assert w.inspect_object("nothing").startswith("error:")


def test_interact_unknown_object_is_error(tmp_path):
    w = make_world(tmp_path)
    assert w.interact_with_object("aria", "ghost", "poke").startswith("error:")


def test_interact_without_on_interact_is_descriptive_not_error(tmp_path):
    w = make_world(tmp_path)
    w.create_object("aria", "stone", "an inert stone")
    r = w.interact_with_object("bram", "stone", "kick")
    assert isinstance(r, str) and r
    assert not r.startswith("error:")


def test_interact_result_is_json_encoded_return_value(tmp_path):
    w = make_world(tmp_path)
    code = ("def on_interact(state, action, source, emit):\n"
            "    return {'echo': action}\n")
    w.create_object("aria", "parrot", "repeats things", behavior_code=code)
    r = w.interact_with_object("bram", "parrot", "squawk")
    assert json.loads(r) == {"echo": "squawk"}


def test_interact_none_return_is_ok(tmp_path):
    # Spec: 'Hook return value comes back JSON-encoded ("ok" if the hook
    # returned None)' — the parenthetical gives the literal result string
    # for the None case (see REPORT.md, ambiguities).
    w = make_world(tmp_path)
    code = ("def on_interact(state, action, source, emit):\n"
            "    state['touches'] = state.get('touches', 0) + 1\n")
    w.create_object("aria", "bell", "a bell", behavior_code=code)
    r = w.interact_with_object("bram", "bell", "ring")
    assert r == "ok"
    assert w.objects["bell"].state == {"touches": 1}


def test_interact_emitted_events_are_published(tmp_path):
    w = make_world(tmp_path)
    code = ("def on_interact(state, action, source, emit):\n"
            "    emit({'ding': 1})\n"
            "    return 'rung'\n")
    w.create_object("aria", "gong", "a gong", behavior_code=code)
    w.interact_with_object("aria", "gong", "strike")
    # broadcast object event from the gong reaches the other agent
    box = w.inboxes["bram"]
    assert any(e.kind == "object" and e.source == "gong" and
               e.payload.get("ding") == 1 for e in box)


# ------------------------------------------------------------- send_message

def test_send_message_broadcast_and_direct(tmp_path):
    w = make_world(tmp_path)
    r = w.send_message("aria", "all", "hello everyone")
    assert not r.startswith("error:")
    assert any(e.payload.get("text") == "hello everyone" for e in w.inboxes["bram"])
    r = w.send_message("bram", "aria", "hello aria")
    assert not r.startswith("error:")
    assert any(e.to == "aria" and e.payload.get("text") == "hello aria"
               for e in w.inboxes["aria"])


def test_send_message_unknown_recipient_is_error(tmp_path):
    w = make_world(tmp_path)
    assert w.send_message("aria", "nobody", "hi").startswith("error:")


# ----------------------------------------------------------- digest/snapshot

def test_digest_contains_tick_agents_objects(tmp_path):
    w = make_world(tmp_path)
    w.create_object("aria", "fountain", "a marble fountain")
    w.advance_tick()
    d = w.digest()
    assert isinstance(d, str)
    assert "1" in d  # current tick
    assert "aria" in d and "bram" in d
    assert "fountain" in d and "a marble fountain" in d


def test_snapshot_shape_and_deep_copy(tmp_path):
    w = make_world(tmp_path)
    w.create_object("aria", "box", "a box", state={"items": ["coin"]})
    snap = w.snapshot()
    assert snap["tick"] == w.tick
    assert snap["agents"] == ["aria", "bram"]
    assert snap["objects"]["box"]["description"] == "a box"
    assert snap["objects"]["box"]["state"] == {"items": ["coin"]}
    # mutating the snapshot must not affect the world
    snap["objects"]["box"]["state"]["items"].append("dagger")
    snap2 = w.snapshot()
    assert snap2["objects"]["box"]["state"] == {"items": ["coin"]}
    assert w.objects["box"].state == {"items": ["coin"]}
