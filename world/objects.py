"""World objects: stateful things agents build, made of state + behavior code.

An object lives on disk as a directory:

    objects/<name>/
        manifest.json   # name, description, creator, created_tick
        state.json      # free-form JSON state
        behavior.py     # optional Python module written by an agent

behavior.py may define either or both hooks:

    def on_tick(state, world, emit):
        '''Called every tick. Mutate `state` in place, or return a dict to
        replace it. `world` is a read-only snapshot. `emit(payload, to="all")`
        publishes an event that agents will perceive.'''

    def on_interact(state, action, source, emit):
        '''Called when an agent interacts with this object. `action` is the
        JSON the agent sent, `source` is the agent's name. The return value
        is shown to the interacting agent.'''

Hooks run in an isolated sandbox subprocess (see world/sandbox.py and
SAFETY.md): whitelisted builtins, no imports, CPU/memory limits, wall-clock
timeout. Failures never crash the world — they are routed back to the
object's creator (or the interacting agent) as events/messages so agents can
debug their own creations.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import sandbox
from .events import OBJECT, Event


class WorldObject:
    def __init__(self, root: Path):
        self.root = root
        manifest = json.loads((root / "manifest.json").read_text())
        self.name: str = manifest["name"]
        self.description: str = manifest.get("description", "")
        self.creator: str = manifest.get("creator", "unknown")
        self.created_tick: int = manifest.get("created_tick", 0)
        self.state: dict = {}
        state_path = root / "state.json"
        if state_path.exists():
            self.state = json.loads(state_path.read_text())

    # ------------------------------------------------------------------ disk

    @classmethod
    def create(
        cls,
        objects_root: Path,
        name: str,
        description: str,
        creator: str,
        created_tick: int,
        state: dict | None = None,
        behavior_code: str | None = None,
    ) -> "WorldObject":
        root = objects_root / name
        root.mkdir(parents=True)
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "description": description,
                    "creator": creator,
                    "created_tick": created_tick,
                },
                indent=2,
            )
        )
        (root / "state.json").write_text(json.dumps(state or {}, indent=2))
        if behavior_code:
            (root / "behavior.py").write_text(behavior_code)
        return cls(root)

    def save_state(self) -> None:
        (self.root / "state.json").write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False)
        )

    def update(
        self,
        description: str | None = None,
        state: dict | None = None,
        behavior_code: str | None = None,
    ) -> None:
        if description is not None:
            self.description = description
            manifest = json.loads((self.root / "manifest.json").read_text())
            manifest["description"] = description
            (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2))
        if state is not None:
            self.state = state
            self.save_state()
        if behavior_code is not None:
            (self.root / "behavior.py").write_text(behavior_code)

    @property
    def behavior_code(self) -> str | None:
        path = self.root / "behavior.py"
        return path.read_text() if path.exists() else None

    # -------------------------------------------------------------- behavior

    def _events_from(self, emitted: list[dict], tick: int) -> list[Event]:
        return [
            Event(
                kind=OBJECT,
                tick=tick,
                source=self.name,
                to=str(e.get("to", "all")),
                payload=dict(e.get("payload", {})),
            )
            for e in emitted
        ]

    def run_tick(self, world_snapshot: dict, tick: int) -> list[Event]:
        """Run on_tick in the sandbox if present. Returns events to publish
        (including a behavior-error event sent to the creator on failure)."""
        code = self.behavior_code
        # Cheap textual fast path: skip spawning a sandbox for objects that
        # clearly have no on_tick hook.
        if not code or "def on_tick" not in code:
            return []
        res = sandbox.run_hook(code=code, hook="on_tick", state=self.state, world=world_snapshot)
        if not res.ok:
            return [
                Event(
                    kind=OBJECT,
                    tick=tick,
                    source=self.name,
                    to=self.creator,
                    payload={"error": res.error},
                )
            ]
        if res.missing:
            return []
        self.state = res.state
        self.save_state()
        return self._events_from(res.emitted, tick)

    def interact(self, action: dict, source: str, tick: int) -> tuple[str, list[Event]]:
        """Run on_interact in the sandbox. Returns (result text for the
        caller, emitted events)."""
        code = self.behavior_code
        if not code or "def on_interact" not in code:
            return (f"Object '{self.name}' has no on_interact hook; nothing happened.", [])
        res = sandbox.run_hook(
            code=code, hook="on_interact", state=self.state, action=action, source=source
        )
        if not res.ok:
            return (f"Interaction with '{self.name}' raised an error: {res.error}", [])
        if res.missing:
            return (f"Object '{self.name}' has no on_interact hook; nothing happened.", [])
        self.state = res.state
        self.save_state()
        text = (
            json.dumps(res.result, ensure_ascii=False, default=str)
            if res.result is not None
            else "ok"
        )
        return text, self._events_from(res.emitted, tick)
