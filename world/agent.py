"""Agent runtime: workspace, turn prompt construction, and tool dispatch.

The "brain" (LLM or scripted mock) is injected; the runtime owns everything
deterministic — the file workspace jail and the mapping from tool calls to
world mutations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .events import Event
from .prompts import TOOLS, system_prompt

if TYPE_CHECKING:
    from .kernel import World

MAX_RESULT_CHARS = 8000


class Brain(Protocol):
    def run_turn(
        self,
        system: str,
        user_prompt: str,
        tools: list[dict],
        dispatch,
    ) -> str:
        """Run one agentic turn. `dispatch(name, input) -> str` executes a tool.
        Returns the agent's final text."""
        ...


class AgentRuntime:
    def __init__(self, name: str, workspace: Path, brain: Brain):
        self.name = name
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.brain = brain
        self._world: "World | None" = None

    # ----------------------------------------------------------------- turns

    def take_turn(self, events: list[Event], world: "World") -> str:
        self._world = world
        try:
            prompt = self._render_turn_prompt(events, world)
            return self.brain.run_turn(
                system=system_prompt(self.name),
                user_prompt=prompt,
                tools=TOOLS,
                dispatch=self._dispatch,
            )
        finally:
            self._world = None

    def _render_turn_prompt(self, events: list[Event], world: "World") -> str:
        parts = [f"# Tick {world.tick} — you have been woken", "", "## Events"]
        parts += [f"- {e.render()}" for e in events] or ["- (none)"]
        for filename in ("identity.md", "memory.md"):
            path = self.workspace / filename
            if path.exists():
                parts += ["", f"## Your {filename}", path.read_text()]
            else:
                parts += [
                    "",
                    f"## Your {filename}",
                    "(does not exist yet — consider creating it with write_file)",
                ]
        parts += ["", "## World digest", world.digest()]
        parts += [
            "",
            "Act now using your tools. When you are done, end with a brief note "
            "about what you did this turn.",
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------- workspace

    def _resolve(self, rel_path: str) -> Path:
        path = (self.workspace / rel_path).resolve()
        if not path.is_relative_to(self.workspace.resolve()):
            raise ValueError(f"path escapes workspace: {rel_path}")
        return path

    # ---------------------------------------------------------- tool dispatch

    def _dispatch(self, tool_name: str, tool_input: dict) -> str:
        try:
            result = self._dispatch_inner(tool_name, tool_input)
        except Exception as exc:
            return f"error: {exc!r}"
        if len(result) > MAX_RESULT_CHARS:
            result = result[:MAX_RESULT_CHARS] + "\n... (truncated)"
        return result

    def _dispatch_inner(self, tool_name: str, tool_input: dict) -> str:
        world = self._world
        assert world is not None, "tool dispatched outside a turn"

        if tool_name == "list_files":
            root = self._resolve(tool_input.get("path", "."))
            if not root.exists():
                return "(empty)"
            entries = sorted(
                str(p.relative_to(self.workspace))
                for p in root.rglob("*")
                if p.is_file()
            )
            return "\n".join(entries) or "(empty)"

        if tool_name == "read_file":
            path = self._resolve(tool_input["path"])
            if not path.exists():
                return f"error: no such file: {tool_input['path']}"
            return path.read_text()

        if tool_name == "write_file":
            path = self._resolve(tool_input["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tool_input["content"])
            return f"wrote {tool_input['path']} ({len(tool_input['content'])} chars)"

        if tool_name == "observe_world":
            return world.digest()

        if tool_name == "inspect_object":
            return world.inspect_object(tool_input["name"])

        if tool_name == "create_object":
            return world.create_object(
                creator=self.name,
                name=tool_input["name"],
                description=tool_input["description"],
                state=tool_input.get("state"),
                behavior_code=tool_input.get("behavior_code"),
            )

        if tool_name == "update_object":
            return world.update_object(
                actor=self.name,
                name=tool_input["name"],
                description=tool_input.get("description"),
                state=tool_input.get("state"),
                behavior_code=tool_input.get("behavior_code"),
            )

        if tool_name == "interact_with_object":
            return world.interact_with_object(
                actor=self.name,
                name=tool_input["name"],
                action=tool_input.get("action", {}),
            )

        if tool_name == "send_message":
            return world.send_message(
                source=self.name,
                to=tool_input["to"],
                text=tool_input["text"],
            )

        return f"error: unknown tool {tool_name!r}"
