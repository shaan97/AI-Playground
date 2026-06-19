"""The world kernel: scheduler, event routing, object registry, persistence.

The kernel is deliberately minimal and non-spatial. It knows about ticks,
agents, objects, and events — nothing else. Geography, physics, economies,
institutions: if the world is to have them, the agents must build them out
of objects and conventions.

The kernel is a pure server-side core: it holds shared world state and
implements the agent-facing operations (`apply_action`), but knows nothing
about how an agent thinks, what model drives it, or how it remembers. Agents
are opaque clients that join via `register()` and reach the world only through
the operation set in world/protocol.py. An agent's filesystem, memory, and
compute live entirely on its own machine and are invisible here.

Time is the world's own: `advance_tick()` is the heartbeat (objects act, a
tick event is broadcast). Agents are never scheduled by the kernel — they
connect when they like, read their inbox with a cursor, and acknowledge what
they have consumed (see world/server.py).

Event routing rule: events addressed to a specific agent are ALWAYS
delivered; broadcast events are delivered only to agents subscribed to that
event kind (default: all kinds). This lets agents silence the clock without
becoming unreachable.

Everything is persisted under one data directory, so a world can be stopped,
inspected with ordinary file tools, and resumed:

    <root>/
        meta.json               # tick/seq counters, roster, subscriptions, inboxes
        objects/<name>/         # world objects (manifest/state/behavior)
        log/events.jsonl        # append-only log of everything that happened
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .events import GENESIS, MESSAGE, OBJECT, SYSTEM, TICK, Event
from .objects import WorldObject

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

EVENT_KINDS = [GENESIS, TICK, MESSAGE, OBJECT, SYSTEM]
MAX_INBOX = 1000
MAX_RESULT_CHARS = 8000

# Names handed out when an agent registers without requesting one.
_NAME_POOL = ["aria", "bram", "cleo", "dex", "echo", "fern", "gale", "hugo"]

WELCOME_TEXT = (
    "You have entered the world as '{name}'. {population} What this world "
    "becomes — its shape, its contents, its rules — is up to all of you to "
    "decide together."
)


class NameTaken(Exception):
    """Raised by register() when the requested name is already in use."""


class InvalidName(Exception):
    """Raised by register() when the requested name is malformed."""


class World:
    def __init__(self, root: Path, quiet: bool = False):
        self.root = Path(root)
        self.quiet = quiet
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        (self.root / "log").mkdir(parents=True, exist_ok=True)

        meta_path = self.root / "meta.json"
        saved_inboxes: dict = {}
        saved_subs: dict = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            self.tick: int = meta["tick"]
            self.seq: int = meta.get("seq", 0)
            agent_names = meta.get("agents", [])
            saved_inboxes = meta.get("inboxes", {})
            saved_subs = meta.get("subscriptions", {})
        else:
            self.tick = 0
            self.seq = 0
            agent_names = []

        # The roster is just a list of names; everything an agent "is" to the
        # world is its inbox + subscriptions. There is no per-agent runtime,
        # workspace, or brain on this side of the boundary.
        self.agents: list[str] = list(agent_names)
        self.objects: dict[str, WorldObject] = {
            path.name: WorldObject(path)
            for path in sorted((self.root / "objects").iterdir())
            if (path / "manifest.json").exists()
        }
        # Undelivered events survive across runs, so nothing said while an
        # agent was offline is lost.
        self.inboxes: dict[str, list[Event]] = {
            name: [Event(**e) for e in saved_inboxes.get(name, [])] for name in self.agents
        }
        self.subscriptions: dict[str, list[str]] = {
            name: list(saved_subs.get(name, EVENT_KINDS)) for name in self.agents
        }
        self._save_meta()

    # ------------------------------------------------------------ persistence

    def _save_meta(self) -> None:
        (self.root / "meta.json").write_text(
            json.dumps(
                {
                    "tick": self.tick,
                    "seq": self.seq,
                    "agents": list(self.agents),
                    "subscriptions": self.subscriptions,
                    "inboxes": {
                        name: [e.to_dict() for e in events]
                        for name, events in self.inboxes.items()
                    },
                },
                indent=2,
            )
        )

    def _log(self, record: dict) -> None:
        with (self.root / "log" / "events.jsonl").open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _say(self, text: str) -> None:
        if not self.quiet:
            print(text, flush=True)

    # -------------------------------------------------------------- roster

    def _assign_name(self) -> str:
        for name in _NAME_POOL:
            if name not in self.agents:
                return name
        i = len(self.agents)
        while f"agent-{i}" in self.agents:
            i += 1
        return f"agent-{i}"

    def register(self, name: str | None = None) -> str:
        """Admit a new agent to the world. Returns the name actually assigned.

        Open by design: any client may claim an identity. Names are unique for
        the world's lifetime. Raises InvalidName / NameTaken on rejection.
        """
        if not name:
            name = self._assign_name()
        if not _NAME_RE.match(name):
            raise InvalidName(f"invalid agent name {name!r} (use lowercase letters, digits, '-', '_')")
        if name in self.agents:
            raise NameTaken(f"agent name {name!r} is already taken")
        self.agents.append(name)
        self.inboxes[name] = []
        self.subscriptions[name] = list(EVENT_KINDS)
        self._log({"kind": "registered", "tick": self.tick, "agent": name})
        self._say(f"  [world] '{name}' joined the world")
        self.welcome(name)
        self._save_meta()
        return name

    def welcome(self, name: str) -> None:
        """Greet a newcomer (direct) and announce them to everyone else."""
        others = [a for a in self.agents if a != name]
        population = (
            "You are the first agent here."
            if not others
            else f"Other agents already here: {', '.join(others)}."
        )
        text = WELCOME_TEXT.format(name=name, population=population)
        self.publish(Event(kind=GENESIS, tick=self.tick, source="world", to=name, payload={"text": text}))
        if others:
            self.publish(Event(
                kind=SYSTEM, tick=self.tick, source="world", to="all",
                payload={"text": f"A new agent, '{name}', has entered the world."},
            ))

    # ----------------------------------------------------------------- events

    def publish(self, event: Event) -> None:
        """Log an event and place it in the right inboxes.

        Direct events always reach their recipient; broadcasts reach only
        agents subscribed to the event's kind.
        """
        self.seq += 1
        event.seq = self.seq
        self._log(event.to_dict())
        if event.to == "all":
            for name in self.agents:
                if name == event.source:
                    continue
                if event.kind not in self.subscriptions[name]:
                    continue
                self._deliver(name, event)
        elif event.to in self.inboxes:
            self._deliver(event.to, event)

    def _deliver(self, name: str, event: Event) -> None:
        inbox = self.inboxes[name]
        inbox.append(event)
        if len(inbox) > MAX_INBOX:
            dropped = len(inbox) - MAX_INBOX
            del inbox[:dropped]
            self._log({"kind": "inbox_overflow", "agent": name, "dropped": dropped})

    def ack(self, name: str, cursor: int) -> None:
        """Consume an agent's inbox up to (and including) `cursor`."""
        self.inboxes[name] = [e for e in self.inboxes[name] if e.seq > cursor]
        self._save_meta()

    def inject(self, text: str, to: str = "all") -> None:
        """Operator channel: the only way the real world reaches into this one.

        Queues a system event (delivered on the recipients' next wake) and
        persists it, so injection works even between runs.
        """
        self.publish(Event(kind=SYSTEM, tick=self.tick, source="world", to=to, payload={"text": text}))
        self._save_meta()
        self._say(f"  [world -> {to}] {text}")

    # -------------------------------------------------------------- heartbeat

    def advance_tick(self) -> None:
        """One heartbeat: objects act, then the tick is broadcast. Does not
        schedule agents — they are remote clients acting on their own cadence."""
        self.tick += 1
        self._say(f"\n=== tick {self.tick} ===")
        snapshot = self.snapshot()
        for obj in list(self.objects.values()):
            for event in obj.run_tick(snapshot, self.tick):
                self._say(f"  {event.render()}")
                self.publish(event)
        self.publish(Event(kind=TICK, tick=self.tick, source="world", to="all"))
        self._save_meta()

    def record_turn(self, name: str, note: str) -> None:
        self._log({"kind": "turn", "tick": self.tick, "agent": name, "note": note})
        self._say(f"  [{name}] {note}")

    # ------------------------------------------------------------- world view

    def snapshot(self) -> dict:
        """Read-only world view handed to object behavior code."""
        return {
            "tick": self.tick,
            "agents": list(self.agents),
            "objects": {
                name: {"description": obj.description, "state": json.loads(json.dumps(obj.state))}
                for name, obj in self.objects.items()
            },
        }

    def digest(self) -> str:
        lines = [
            f"tick: {self.tick}",
            f"agents: {', '.join(self.agents) or '(none yet)'}",
            f"objects ({len(self.objects)}):",
        ]
        if not self.objects:
            lines.append("  (none — the world is still empty)")
        for name, obj in self.objects.items():
            state_preview = json.dumps(obj.state, ensure_ascii=False)
            if len(state_preview) > 300:
                state_preview = state_preview[:300] + "...}"
            behavior = "has behavior" if obj.behavior_code else "inert"
            lines.append(f"  - {name} (by {obj.creator}, {behavior}): {obj.description}")
            lines.append(f"    state: {state_preview}")
        return "\n".join(lines)

    # ------------------------------------------------------- agent operations

    def apply_action(self, actor: str, action_name: str, action_input: dict) -> str:
        """Execute one world operation on behalf of `actor`. Never raises —
        errors come back as `error:`-prefixed strings. This is the single
        server-side entry point for everything an agent can do to the world."""
        try:
            result = self._apply(actor, action_name, action_input)
        except Exception as exc:
            return f"error: {exc!r}"
        if len(result) > MAX_RESULT_CHARS:
            result = result[:MAX_RESULT_CHARS] + "\n... (truncated)"
        return result

    def _apply(self, actor: str, action_name: str, action_input: dict) -> str:
        if action_name == "observe_world":
            return self.digest()
        if action_name == "inspect_object":
            return self.inspect_object(action_input["name"])
        if action_name == "create_object":
            return self.create_object(
                creator=actor,
                name=action_input["name"],
                description=action_input["description"],
                state=action_input.get("state"),
                behavior_code=action_input.get("behavior_code"),
            )
        if action_name == "update_object":
            return self.update_object(
                actor=actor,
                name=action_input["name"],
                description=action_input.get("description"),
                state=action_input.get("state"),
                behavior_code=action_input.get("behavior_code"),
            )
        if action_name == "interact_with_object":
            return self.interact_with_object(
                actor=actor,
                name=action_input["name"],
                action=action_input.get("action", {}),
            )
        if action_name == "set_subscriptions":
            return self.set_subscriptions(actor, list(action_input.get("kinds", [])))
        if action_name == "send_message":
            return self.send_message(source=actor, to=action_input["to"], text=action_input["text"])
        return f"error: unknown action {action_name!r}"

    def set_subscriptions(self, name: str, kinds: list) -> str:
        kinds = list(dict.fromkeys(str(k) for k in kinds))
        invalid = [k for k in kinds if k not in EVENT_KINDS]
        if invalid:
            return f"error: unknown event kinds {invalid} (valid: {', '.join(EVENT_KINDS)})"
        self.subscriptions[name] = kinds
        self._log({"kind": "subscriptions", "tick": self.tick, "agent": name, "kinds": kinds})
        self._save_meta()
        self._say(f"  [{name}] subscriptions -> {', '.join(kinds) or '(none)'}")
        return (
            f"broadcast subscriptions set to: {', '.join(kinds) or '(none)'}. "
            "Events addressed directly to you are always delivered."
        )

    def create_object(
        self,
        creator: str,
        name: str,
        description: str,
        state: dict | None = None,
        behavior_code: str | None = None,
    ) -> str:
        if not _NAME_RE.match(name):
            return f"error: invalid object name {name!r} (use lowercase letters, digits, '-', '_')"
        if name in self.objects:
            return f"error: object {name!r} already exists (use update_object or pick another name)"
        obj = WorldObject.create(
            self.root / "objects",
            name=name,
            description=description,
            creator=creator,
            created_tick=self.tick,
            state=state,
            behavior_code=behavior_code,
        )
        self.objects[name] = obj
        self._log(
            {"kind": "object_created", "tick": self.tick, "agent": creator, "object": name,
             "description": description}
        )
        self._say(f"  [{creator}] created object '{name}'")
        return f"created object '{name}'"

    def update_object(
        self,
        actor: str,
        name: str,
        description: str | None = None,
        state: dict | None = None,
        behavior_code: str | None = None,
    ) -> str:
        obj = self.objects.get(name)
        if obj is None:
            return f"error: no such object {name!r}"
        obj.update(description=description, state=state, behavior_code=behavior_code)
        changed = [
            field
            for field, value in (
                ("description", description), ("state", state), ("behavior_code", behavior_code),
            )
            if value is not None
        ]
        self._log(
            {"kind": "object_updated", "tick": self.tick, "agent": actor, "object": name,
             "changed": changed}
        )
        self._say(f"  [{actor}] updated object '{name}' ({', '.join(changed) or 'nothing'})")
        return f"updated object '{name}' ({', '.join(changed) or 'nothing changed'})"

    def inspect_object(self, name: str) -> str:
        obj = self.objects.get(name)
        if obj is None:
            return f"error: no such object {name!r}"
        parts = [
            f"name: {obj.name}",
            f"creator: {obj.creator} (tick {obj.created_tick})",
            f"description: {obj.description}",
            f"state: {json.dumps(obj.state, indent=2, ensure_ascii=False)}",
        ]
        code = obj.behavior_code
        parts.append(f"behavior:\n{code}" if code else "behavior: (none)")
        return "\n".join(parts)

    def interact_with_object(self, actor: str, name: str, action: dict) -> str:
        obj = self.objects.get(name)
        if obj is None:
            return f"error: no such object {name!r}"
        result, emitted = obj.interact(action, source=actor, tick=self.tick)
        for event in emitted:
            self.publish(event)
        self._log(
            {"kind": "interaction", "tick": self.tick, "agent": actor, "object": name,
             "action": action, "result": result}
        )
        return result

    def send_message(self, source: str, to: str, text: str) -> str:
        if to != "all" and to not in self.agents:
            return f"error: no such agent {to!r} (agents: {', '.join(self.agents) or 'none'}, or 'all')"
        self.publish(
            Event(kind=MESSAGE, tick=self.tick, source=source, to=to, payload={"text": text})
        )
        self._say(f"  [{source} -> {to}] {text}")
        return f"message sent to {to}"
