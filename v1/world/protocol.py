"""The world's operation set — the narrow, common API every agent speaks.

This module is the single source of truth for what an agent can do *to the
world*. It says nothing about how an agent thinks, remembers, or perceives:
those live entirely behind the client. The kernel implements these operations
(see World.apply_action); clients invoke them by name over HTTP.

The operations are world-only by design — there are deliberately no
file/memory/workspace actions. An agent's filesystem and memory are its own
business, on its own machine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    input_schema: dict

    def to_dict(self) -> dict:
        return asdict(self)


ACTIONS: list[ActionSpec] = [
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
