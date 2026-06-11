"""The model- and harness-neutral agent API.

This module is the single source of truth for what an agent can do in the
world. Connectors (Claude, external processes, mocks, ...) adapt these
specs to their own format; the kernel dispatches them uniformly.

A turn is expressed as a "wake" payload (build_wake) plus a dispatch function
`(action_name, input_dict) -> result_str`. Anything that can consume the wake
payload and call dispatch can be an agent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import AgentRuntime
    from .events import Event
    from .kernel import World

PROTOCOL_VERSION = 1

MEMORY_FILES = ("identity.md", "memory.md")


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    input_schema: dict

    def to_dict(self) -> dict:
        return asdict(self)


ACTIONS: list[ActionSpec] = [
    ActionSpec(
        name="list_files",
        description=(
            "List files in your private workspace. Returns relative paths. "
            "Call this to see what your past self left for you."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Subdirectory to list, relative to workspace root. Defaults to the root.",
                }
            },
        },
    ),
    ActionSpec(
        name="read_file",
        description="Read a file from your private workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace root."}
            },
            "required": ["path"],
        },
    ),
    ActionSpec(
        name="write_file",
        description=(
            "Write (create or overwrite) a file in your private workspace. "
            "Use this to maintain identity.md, memory.md, plans, and scratch notes."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace root."},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        },
    ),
    ActionSpec(
        name="observe_world",
        description=(
            "Get a digest of the world: current tick, the agents that exist, and "
            "every object with its description, creator, and a preview of its state."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ActionSpec(
        name="inspect_object",
        description=(
            "Inspect one object in full detail: manifest, complete state, and its "
            "behavior code if it has any."
        ),
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Object name."}},
            "required": ["name"],
        },
    ),
    ActionSpec(
        name="create_object",
        description=(
            "Create a new object in the world. Objects are how the world gains "
            "substance: places, artifacts, institutions, games — whatever you and "
            "the other agents decide should exist. State is free-form JSON; "
            "behavior_code is an optional Python module defining on_tick and/or "
            "on_interact (see your instructions for the contract and sandbox limits)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique object name. Lowercase, hyphens/underscores, no spaces.",
                },
                "description": {
                    "type": "string",
                    "description": "What this object is and why it exists. Other agents read this.",
                },
                "state": {
                    "type": "object",
                    "description": "Initial JSON state. Defaults to an empty object.",
                },
                "behavior_code": {
                    "type": "string",
                    "description": (
                        "Optional Python source defining on_tick(state, world, emit) "
                        "and/or on_interact(state, action, source, emit)."
                    ),
                },
            },
            "required": ["name", "description"],
        },
    ),
    ActionSpec(
        name="update_object",
        description=(
            "Update an existing object's description, state, and/or behavior code. "
            "Provided fields fully replace the old values. Anyone may update any "
            "object, but coordinate with its creator first when it isn't yours."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "description": {"type": "string", "description": "New description."},
                "state": {"type": "object", "description": "Replacement JSON state."},
                "behavior_code": {
                    "type": "string",
                    "description": "Replacement behavior module source.",
                },
            },
            "required": ["name"],
        },
    ),
    ActionSpec(
        name="interact_with_object",
        description=(
            "Interact with an object that defines on_interact. `action` is free-form "
            "JSON the object's code will receive; the object's return value comes "
            "back to you. Use inspect_object first to learn what actions it supports."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "action": {"type": "object", "description": "Free-form JSON action payload."},
            },
            "required": ["name", "action"],
        },
    ),
    ActionSpec(
        name="set_subscriptions",
        description=(
            "Choose which kinds of BROADCAST events wake you. Events addressed "
            "directly to you (direct messages, your objects' errors, object "
            "events emitted to your name) are ALWAYS delivered regardless. "
            "Default: all kinds. Unsubscribe from 'tick' to sleep until "
            "something actually happens; if you still want a time signal, build "
            "your own — e.g. an object whose on_tick emits an event addressed "
            "to you every N ticks."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kinds": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["genesis", "tick", "message", "object", "system"],
                    },
                    "description": "The broadcast event kinds you want to receive.",
                }
            },
            "required": ["kinds"],
        },
    ),
    ActionSpec(
        name="send_message",
        description=(
            "Send a message to another agent (delivered when they next wake) or "
            "broadcast to everyone with to='all'. This is how the world is "
            "negotiated — use it generously."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient agent name, or 'all' to broadcast.",
                },
                "text": {"type": "string", "description": "Message text."},
            },
            "required": ["to", "text"],
        },
    ),
]


def anthropic_tools() -> list[dict]:
    """Render the action specs as Anthropic tool definitions."""
    return [
        {"name": a.name, "description": a.description, "input_schema": a.input_schema}
        for a in ACTIONS
    ]


def build_wake(agent: "AgentRuntime", events: list["Event"], world: "World") -> dict:
    """The neutral turn payload handed to whatever harness drives this agent."""
    memory = {}
    for filename in MEMORY_FILES:
        path = agent.workspace / filename
        memory[filename] = path.read_text() if path.exists() else None
    return {
        "type": "wake",
        "protocol": PROTOCOL_VERSION,
        "agent": agent.name,
        "tick": world.tick,
        "workspace": str(agent.workspace.resolve()),
        "events": [e.to_dict() for e in events],
        "events_text": [e.render() for e in events],
        "memory": memory,
        "world_digest": world.digest(),
        "subscriptions": list(world.subscriptions.get(agent.name, [])),
        "actions": [a.to_dict() for a in ACTIONS],
    }
