"""Agent runtime: workspace jail and action dispatch.

The decision-making half (the "connector" — Claude, an external harness
process, a scripted mock, ...) is injected; the runtime owns everything
deterministic — the file workspace jail and the mapping from protocol
actions to world mutations.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .connectors import Connector
from .events import Event
from .protocol import build_wake

if TYPE_CHECKING:
    from .kernel import World

MAX_RESULT_CHARS = 8000
MAX_FILE_CHARS = 512_000


class AgentRuntime:
    def __init__(self, name: str, workspace: Path, connector: Connector):
        self.name = name
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.connector = connector
        self._world: "World | None" = None

    # ----------------------------------------------------------------- turns

    def take_turn(self, events: list[Event], world: "World") -> str:
        self._world = world
        try:
            wake = build_wake(self, events, world)
            return self.connector.take_turn(wake, self.dispatch)
        finally:
            self._world = None

    # ------------------------------------------------------------- workspace

    def _resolve(self, rel_path: str) -> Path:
        path = (self.workspace / rel_path).resolve()
        if not path.is_relative_to(self.workspace.resolve()):
            raise ValueError(f"path escapes workspace: {rel_path}")
        return path

    # --------------------------------------------------------------- actions

    def dispatch(self, action_name: str, action_input: dict) -> str:
        try:
            result = self._dispatch_inner(action_name, action_input)
        except Exception as exc:
            return f"error: {exc!r}"
        if len(result) > MAX_RESULT_CHARS:
            result = result[:MAX_RESULT_CHARS] + "\n... (truncated)"
        return result

    def _dispatch_inner(self, action_name: str, action_input: dict) -> str:
        world = self._world
        assert world is not None, "action dispatched outside a turn"

        if action_name == "list_files":
            root = self._resolve(action_input.get("path", "."))
            if not root.exists():
                return "(empty)"
            entries = sorted(
                str(p.relative_to(self.workspace))
                for p in root.rglob("*")
                if p.is_file()
            )
            return "\n".join(entries) or "(empty)"

        if action_name == "read_file":
            path = self._resolve(action_input["path"])
            if not path.exists():
                return f"error: no such file: {action_input['path']}"
            return path.read_text()

        if action_name == "write_file":
            content = action_input["content"]
            if len(content) > MAX_FILE_CHARS:
                return f"error: content too large ({len(content)} chars; max {MAX_FILE_CHARS})"
            path = self._resolve(action_input["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"wrote {action_input['path']} ({len(content)} chars)"

        if action_name == "observe_world":
            return world.digest()

        if action_name == "inspect_object":
            return world.inspect_object(action_input["name"])

        if action_name == "create_object":
            return world.create_object(
                creator=self.name,
                name=action_input["name"],
                description=action_input["description"],
                state=action_input.get("state"),
                behavior_code=action_input.get("behavior_code"),
            )

        if action_name == "update_object":
            return world.update_object(
                actor=self.name,
                name=action_input["name"],
                description=action_input.get("description"),
                state=action_input.get("state"),
                behavior_code=action_input.get("behavior_code"),
            )

        if action_name == "interact_with_object":
            return world.interact_with_object(
                actor=self.name,
                name=action_input["name"],
                action=action_input.get("action", {}),
            )

        if action_name == "send_message":
            return world.send_message(
                source=self.name,
                to=action_input["to"],
                text=action_input["text"],
            )

        return f"error: unknown action {action_name!r}"
