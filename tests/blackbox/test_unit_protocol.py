"""Unit tests for world.protocol per docs/INTERFACES.md §world.protocol."""
import pathlib

from conftest import none_factory

from world import protocol
from world.events import Event
from world.kernel import World

EXPECTED_ACTIONS = {
    "list_files",
    "read_file",
    "write_file",
    "observe_world",
    "inspect_object",
    "create_object",
    "update_object",
    "interact_with_object",
    "send_message",
    "set_subscriptions",
}


def test_actions_is_the_documented_ten():
    names = [spec.name for spec in protocol.ACTIONS]
    assert len(names) == 10
    assert set(names) == EXPECTED_ACTIONS
    assert len(set(names)) == 10  # no duplicates


def test_action_spec_shape():
    for spec in protocol.ACTIONS:
        assert isinstance(spec.name, str) and spec.name
        assert isinstance(spec.description, str) and spec.description
        assert isinstance(spec.input_schema, dict)
        d = spec.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == spec.name
        assert d["description"] == spec.description
        assert d["input_schema"] == spec.input_schema


def test_anthropic_tools_match_actions_one_to_one():
    tools = protocol.anthropic_tools()
    assert isinstance(tools, list)
    assert len(tools) == len(protocol.ACTIONS)
    assert [t["name"] for t in tools] == [s.name for s in protocol.ACTIONS]
    for tool, spec in zip(tools, protocol.ACTIONS):
        assert isinstance(tool["description"], str) and tool["description"]
        assert tool["input_schema"] == spec.input_schema


def test_build_wake_shape(tmp_path):
    world = World(tmp_path, none_factory, ["aria", "bram"], quiet=True)
    agent = world.agents["aria"]
    evs = [
        Event(kind="message", tick=1, source="bram", to="aria",
              payload={"text": "hi"}, seq=3),
        Event(kind="tick", tick=2, source="world", to="all", seq=4),
    ]
    wake = protocol.build_wake(agent, evs, world)

    assert wake["type"] == "wake"
    assert wake["protocol"] == 1
    assert wake["agent"] == "aria"
    assert wake["tick"] == world.tick
    # workspace: absolute path string
    assert isinstance(wake["workspace"], str)
    assert pathlib.Path(wake["workspace"]).is_absolute()
    # events: list of event dicts, events_text parallel renders
    assert isinstance(wake["events"], list) and len(wake["events"]) == 2
    assert wake["events"][0]["kind"] == "message"
    assert wake["events"][0]["payload"] == {"text": "hi"}
    assert isinstance(wake["events_text"], list)
    assert len(wake["events_text"]) == len(wake["events"])
    assert all(isinstance(t, str) for t in wake["events_text"])
    assert "hi" in wake["events_text"][0]
    # memory: both keys present, None when files are absent
    assert set(wake["memory"]) == {"identity.md", "memory.md"}
    assert wake["memory"]["identity.md"] is None
    assert wake["memory"]["memory.md"] is None
    # digest / subscriptions / actions
    assert isinstance(wake["world_digest"], str)
    assert wake["subscriptions"] == ["genesis", "tick", "message", "object", "system"] or \
        set(wake["subscriptions"]) == {"genesis", "tick", "message", "object", "system"}
    assert wake["actions"] == [s.to_dict() for s in protocol.ACTIONS]


def test_build_wake_includes_memory_file_contents(tmp_path):
    world = World(tmp_path, none_factory, ["aria"], quiet=True)
    agent = world.agents["aria"]
    ws = tmp_path / "agents" / "aria" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "identity.md").write_text("I am aria.")
    wake = protocol.build_wake(agent, [], world)
    assert wake["memory"]["identity.md"] == "I am aria."
    assert wake["memory"]["memory.md"] is None
