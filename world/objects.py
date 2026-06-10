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

NOTE: behavior code is executed with plain `exec` — this is a sandbox-free
playground for cooperative agents, not a security boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

from .events import OBJECT, Event

_BEHAVIOR_HOOKS = ("on_tick", "on_interact")


class BehaviorError(Exception):
    pass


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
        self._module_cache: tuple[str, dict] | None = None

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
            self._module_cache = None

    @property
    def behavior_code(self) -> str | None:
        path = self.root / "behavior.py"
        return path.read_text() if path.exists() else None

    # -------------------------------------------------------------- behavior

    def _hooks(self) -> dict:
        code = self.behavior_code
        if not code:
            return {}
        if self._module_cache and self._module_cache[0] == code:
            return self._module_cache[1]
        namespace: dict = {}
        try:
            exec(compile(code, f"<{self.name}/behavior.py>", "exec"), namespace)
        except Exception as exc:  # syntax or import-time errors
            raise BehaviorError(f"behavior failed to load: {exc!r}") from exc
        hooks = {k: v for k, v in namespace.items() if k in _BEHAVIOR_HOOKS and callable(v)}
        self._module_cache = (code, hooks)
        return hooks

    def run_tick(self, world_snapshot: dict, tick: int) -> list[Event]:
        """Run on_tick if present. Returns events to publish (including a
        behavior-error event sent to the creator on failure)."""
        emitted: list[Event] = []

        def emit(payload: dict, to: str = "all") -> None:
            emitted.append(
                Event(kind=OBJECT, tick=tick, source=self.name, to=to, payload=dict(payload))
            )

        try:
            hooks = self._hooks()
            on_tick = hooks.get("on_tick")
            if on_tick is None:
                return []
            result = on_tick(self.state, world_snapshot, emit)
            if isinstance(result, dict):
                self.state = result
            self.save_state()
        except Exception as exc:
            return [
                Event(
                    kind=OBJECT,
                    tick=tick,
                    source=self.name,
                    to=self.creator,
                    payload={"error": repr(exc)},
                )
            ]
        return emitted

    def interact(self, action: dict, source: str, tick: int) -> tuple[str, list[Event]]:
        """Run on_interact. Returns (result text for the caller, emitted events)."""
        emitted: list[Event] = []

        def emit(payload: dict, to: str = "all") -> None:
            emitted.append(
                Event(kind=OBJECT, tick=tick, source=self.name, to=to, payload=dict(payload))
            )

        try:
            hooks = self._hooks()
            on_interact = hooks.get("on_interact")
            if on_interact is None:
                return (
                    f"Object '{self.name}' has no on_interact hook; nothing happened.",
                    [],
                )
            result = on_interact(self.state, action, source, emit)
            self.save_state()
            text = json.dumps(result, ensure_ascii=False, default=str) if result is not None else "ok"
            return text, emitted
        except Exception as exc:
            return f"Interaction with '{self.name}' raised an error: {exc!r}", []
