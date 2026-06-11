"""The world kernel: scheduler, event routing, object registry, persistence.

The kernel is deliberately minimal and non-spatial. It knows about ticks,
agents, objects, and events — nothing else. Geography, physics, economies,
institutions: if the world is to have them, the agents must build them out
of objects and conventions.

Time is decoupled from agency: `advance_tick()` is the world's heartbeat
(objects act, a tick event is broadcast), while agents may be driven either
in lockstep (`step()`/`run()`, local mode) or at their own pace by remote
clients (server mode — see world/server.py), which read their inboxes with
cursors and acknowledge what they've consumed.

Event routing rule: events addressed to a specific agent are ALWAYS
delivered; broadcast events are delivered only to agents subscribed to that
event kind (default: all kinds). This lets agents silence the clock without
becoming unreachable.

Everything is persisted under one data directory, so a world can be stopped,
inspected with ordinary file tools, and resumed:

    <root>/
        meta.json               # tick/seq counters, roster, subscriptions, inboxes
        agents/<name>/workspace # each agent's private filesystem
        objects/<name>/         # world objects (manifest/state/behavior)
        log/events.jsonl        # append-only log of everything that happened
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .agent import AgentRuntime
from .events import GENESIS, MESSAGE, OBJECT, SYSTEM, TICK, Event
from .objects import WorldObject

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

EVENT_KINDS = [GENESIS, TICK, MESSAGE, OBJECT, SYSTEM]
MAX_INBOX = 1000

GENESIS_TEXT = (
    "The world is empty. You are one of {n} agents: {names}. Nothing exists yet "
    "except you, the other agents, and the clock. What this world becomes — its "
    "shape, its contents, its rules — is up to all of you to decide together."
)


class World:
    def __init__(self, root: Path, connector_factory, agent_names: list[str], quiet: bool = False):
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
            agent_names = meta["agents"]  # roster is fixed for a world's lifetime
            saved_inboxes = meta.get("inboxes", {})
            saved_subs = meta.get("subscriptions", {})
            self._genesis_done = meta.get("genesis_done", True)
        else:
            self.tick = 0
            self.seq = 0
            self._genesis_done = False

        self.agents: dict[str, AgentRuntime] = {
            name: AgentRuntime(
                name=name,
                workspace=self.root / "agents" / name / "workspace",
                connector=connector_factory(index, name),
                world=self,
            )
            for index, name in enumerate(agent_names)
        }
        self.objects: dict[str, WorldObject] = {
            path.name: WorldObject(path)
            for path in sorted((self.root / "objects").iterdir())
            if (path / "manifest.json").exists()
        }
        # Undelivered events survive across runs, so nothing said on a run's
        # final tick (or while a remote agent was offline) is lost.
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
                    "genesis_done": self._genesis_done,
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
        """Consume an agent's inbox up to (and including) `cursor`. Used by
        remote clients; lockstep mode consumes inboxes wholesale instead."""
        self.inboxes[name] = [e for e in self.inboxes[name] if e.seq > cursor]
        self._save_meta()

    # -------------------------------------------------------------- main loop

    def ensure_genesis(self) -> None:
        if self._genesis_done:
            return
        text = GENESIS_TEXT.format(n=len(self.agents), names=", ".join(self.agents))
        self._say(f"=== genesis: {len(self.agents)} agents enter an empty world ===")
        for name in self.agents:
            self.publish(Event(kind=GENESIS, tick=0, source="world", to=name, payload={"text": text}))
        self._genesis_done = True
        self._save_meta()

    def inject(self, text: str, to: str = "all") -> None:
        """Operator channel: the only way the real world reaches into this one.

        Queues a system event (delivered on the recipients' next wake) and
        persists it, so injection works even between runs.
        """
        self.publish(Event(kind=SYSTEM, tick=self.tick, source="world", to=to, payload={"text": text}))
        self._save_meta()
        self._say(f"  [world -> {to}] {text}")

    def advance_tick(self) -> None:
        """One heartbeat: objects act, then the tick is broadcast. Does not
        schedule agents — lockstep mode does that in step(); in server mode
        agents are remote clients acting on their own cadence."""
        self.tick += 1
        self._say(f"\n=== tick {self.tick} ===")
        snapshot = self.snapshot()
        for obj in list(self.objects.values()):
            for event in obj.run_tick(snapshot, self.tick):
                self._say(f"  {event.render()}")
                self.publish(event)
        self.publish(Event(kind=TICK, tick=self.tick, source="world", to="all"))
        self._save_meta()

    def run(self, ticks: int) -> None:
        """Lockstep mode: heartbeat + every agent takes a turn, each tick."""
        self.ensure_genesis()
        for _ in range(ticks):
            self.step()

    def step(self) -> None:
        self.advance_tick()
        for name, agent in self.agents.items():
            inbox = self.inboxes[name]
            self.inboxes[name] = []
            if not inbox:
                continue  # nothing to perceive (e.g. unsubscribed from ticks)
            note = agent.take_turn(inbox)
            self.record_turn(name, note)
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
            f"agents: {', '.join(self.agents)}",
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

    # ------------------------------------------------------- agent-facing API

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
            return f"error: no such agent {to!r} (agents: {', '.join(self.agents)}, or 'all')"
        self.publish(
            Event(kind=MESSAGE, tick=self.tick, source=source, to=to, payload={"text": text})
        )
        self._say(f"  [{source} -> {to}] {text}")
        return f"message sent to {to}"
