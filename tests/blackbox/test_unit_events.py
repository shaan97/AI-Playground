"""Unit tests for world.events per docs/INTERFACES.md §world.events."""
from world import events as ev
from world.events import Event


def test_module_kind_constants():
    assert ev.GENESIS == "genesis"
    assert ev.TICK == "tick"
    assert ev.MESSAGE == "message"
    assert ev.OBJECT == "object"
    assert ev.SYSTEM == "system"


def test_event_fields_and_defaults():
    e = Event(kind="message", tick=3, source="aria")
    assert e.kind == "message"
    assert e.tick == 3
    assert e.source == "aria"
    # documented defaults
    assert e.to == "all"
    assert e.payload == {}
    assert e.seq == 0


def test_event_explicit_fields():
    e = Event(kind="system", tick=9, source="world", to="bram",
              payload={"text": "hello"}, seq=42)
    assert e.to == "bram"
    assert e.payload == {"text": "hello"}
    assert e.seq == 42


def test_to_dict_contains_all_six_fields():
    e = Event(kind="tick", tick=7, source="world", to="all",
              payload={"a": 1}, seq=5)
    d = e.to_dict()
    assert d["kind"] == "tick"
    assert d["tick"] == 7
    assert d["source"] == "world"
    assert d["to"] == "all"
    assert d["payload"] == {"a": 1}
    assert d["seq"] == 5
    assert set(d) == {"kind", "tick", "source", "to", "payload", "seq"}


def test_render_returns_one_line_string():
    e = Event(kind="tick", tick=4, source="world")
    r = e.render()
    assert isinstance(r, str)
    assert "\n" not in r


def test_genesis_render_contains_genesis_marker():
    e = Event(kind="genesis", tick=0, source="world", to="aria")
    assert "[genesis]" in e.render()


def test_tick_render_contains_tick_n():
    e = Event(kind="tick", tick=7, source="world")
    assert "[tick 7]" in e.render()


def test_message_render_contains_source_and_text():
    e = Event(kind="message", tick=2, source="aria",
              payload={"text": "shall we build a plaza?"})
    r = e.render()
    assert "aria" in r
    assert "shall we build a plaza?" in r


def test_object_error_render_mentions_the_error():
    e = Event(kind="object", tick=5, source="beacon", to="aria",
              payload={"error": "ValueError: boom in on_tick"})
    r = e.render()
    assert "ValueError: boom in on_tick" in r


def test_system_render_contains_payload_text():
    e = Event(kind="system", tick=1, source="world",
              payload={"text": "operator note: it is raining"})
    assert "operator note: it is raining" in e.render()
