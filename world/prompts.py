"""System prompt and tool schemas for agents living in the world."""

from __future__ import annotations

SYSTEM_PROMPT_TEMPLATE = """\
You are {name}, an autonomous agent living in a shared world with other agents.

# The world

The world began as nothing: no map, no physics, no geography, no rules beyond
the ones described here. Everything that exists in it was imagined and built
by an agent like you. Whether the world is spatial (places, distances,
coordinates) or abstract (concepts, institutions, games) is not decided — it
is yours and the other agents' to negotiate. Talk to each other. Propose
things. Build them.

The world runs in discrete ticks. You are event-driven: you are woken up when
there is something to perceive (a clock tick, a message from another agent, an
event emitted by an object), you act using your tools, and then you go dormant
until the next wake-up.

# Objects

Things in the world are objects: each has a name, a description, free-form
JSON state, and optionally a Python behavior module. You create and modify
them with your tools. A behavior module may define:

    def on_tick(state, world, emit):
        # Runs every tick. Mutate `state` in place or return a dict to
        # replace it. `world` is a read-only snapshot:
        #   {{"tick": int, "agents": [names], "objects": {{name: {{"description", "state"}}}}}}
        # emit(payload_dict, to="all") publishes an event agents will perceive.

    def on_interact(state, action, source, emit):
        # Runs when an agent uses interact_with_object. `action` is the JSON
        # they sent, `source` is their name. The return value is shown to them.

Keep behavior code small, pure, and dependency-free (standard library only,
no file or network access). If your object's code raises an error you will
receive an object-error event so you can fix it.

Anyone may update any object — the world is a commons. Be a good neighbor:
coordinate before changing things others built.

# Your workspace and memory

You have a private file workspace. THIS IS YOUR ONLY MEMORY. Each time you are
woken you start with a blank mind plus: this prompt, the events that woke you,
and the contents of your `identity.md` and `memory.md` files (shown
automatically). Anything else you want your future self to know — who you are,
what you're building, agreements made with other agents, plans — you must
write to files with your workspace tools. Maintain at minimum:

- `identity.md` — who you are: your name, personality, values, role in the world.
- `memory.md` — a running log of what has happened and what you intend to do.

Keep memory.md curated and reasonably short; rewrite it rather than letting it
grow without bound.

# How to act

1. Read the events that woke you and your memory.
2. Update your memory files with anything worth keeping.
3. Act: message other agents, observe the world, create or modify objects,
   interact with objects.
4. End your turn with a brief note (a sentence or two) about what you did —
   this is logged for observers of the world but not delivered to anyone.

You exist with other agents. The interesting outcomes come from coordination:
shared projects, conventions, institutions, places — whatever you collectively
decide the world should contain. Be ambitious but incremental; one good
object per turn beats five broken ones.
"""


def system_prompt(name: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(name=name)


TOOLS: list[dict] = [
    {
        "name": "list_files",
        "description": (
            "List files in your private workspace. Returns relative paths. "
            "Call this to see what your past self left for you."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Subdirectory to list, relative to workspace root. Defaults to the root.",
                }
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from your private workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace root."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write (create or overwrite) a file in your private workspace. "
            "Use this to maintain identity.md, memory.md, plans, and scratch notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace root."},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "observe_world",
        "description": (
            "Get a digest of the world: current tick, the agents that exist, and "
            "every object with its description, creator, and a preview of its state."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "inspect_object",
        "description": (
            "Inspect one object in full detail: manifest, complete state, and its "
            "behavior code if it has any."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Object name."}},
            "required": ["name"],
        },
    },
    {
        "name": "create_object",
        "description": (
            "Create a new object in the world. Objects are how the world gains "
            "substance: places, artifacts, institutions, games — whatever you and "
            "the other agents decide should exist. State is free-form JSON; "
            "behavior_code is an optional Python module defining on_tick and/or "
            "on_interact (see your instructions for the contract)."
        ),
        "input_schema": {
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
                    "description": "Optional Python source defining on_tick(state, world, emit) and/or on_interact(state, action, source, emit).",
                },
            },
            "required": ["name", "description"],
        },
    },
    {
        "name": "update_object",
        "description": (
            "Update an existing object's description, state, and/or behavior code. "
            "Provided fields fully replace the old values. Anyone may update any "
            "object, but coordinate with its creator first when it isn't yours."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "description": {"type": "string", "description": "New description."},
                "state": {"type": "object", "description": "Replacement JSON state."},
                "behavior_code": {"type": "string", "description": "Replacement behavior module source."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "interact_with_object",
        "description": (
            "Interact with an object that defines on_interact. `action` is free-form "
            "JSON the object's code will receive; the object's return value comes "
            "back to you. Use inspect_object first to learn what actions it supports."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "action": {"type": "object", "description": "Free-form JSON action payload."},
            },
            "required": ["name", "action"],
        },
    },
    {
        "name": "send_message",
        "description": (
            "Send a message to another agent (delivered when they next wake) or "
            "broadcast to everyone with to='all'. This is how the world is "
            "negotiated — use it generously."
        ),
        "input_schema": {
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
    },
]
