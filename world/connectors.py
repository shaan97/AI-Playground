"""Connectors: pluggable brains that drive an agent's turn.

The contract is deliberately tiny — anything that can consume a wake payload
(see world/protocol.py) and call `dispatch(action_name, input) -> str` is a
valid agent:

    class Connector(Protocol):
        def take_turn(self, wake: dict, dispatch) -> str: ...

Built-ins:
- ClaudeConnector  — the Claude API with a manual tool-use loop.
- ProcessConnector — any external program speaking the JSON-lines protocol
  in PROTOCOL.md; this is how arbitrary models/harnesses plug in.
- MockConnector    — deterministic scripted agent for offline runs and tests.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from typing import Callable, Protocol

from .prompts import render_wake_prompt, system_prompt
from .protocol import anthropic_tools

DEFAULT_MODEL = "claude-opus-4-8"

Dispatch = Callable[[str, dict], str]


class Connector(Protocol):
    def take_turn(self, wake: dict, dispatch: Dispatch) -> str:
        """Run one agentic turn. Returns the agent's end-of-turn note."""
        ...


# --------------------------------------------------------------------- Claude


class ClaudeConnector:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str | None = None,
        max_tool_iterations: int = 16,
        max_tokens: int = 16000,
        client=None,
    ):
        import anthropic  # lazy so non-Claude worlds don't require the SDK

        self.model = model
        self.effort = effort
        self.max_tool_iterations = max_tool_iterations
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic()

    def take_turn(self, wake: dict, dispatch: Dispatch) -> str:
        messages: list[dict] = [{"role": "user", "content": render_wake_prompt(wake)}]
        # The system prompt and tool list are byte-stable across every turn of
        # every run, so a cache breakpoint on the system block caches both.
        system_blocks = [
            {
                "type": "text",
                "text": system_prompt(wake["agent"]),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        tools = anthropic_tools()

        final_text = ""
        for _ in range(self.max_tool_iterations):
            kwargs: dict = dict(
                model=self.model,
                max_tokens=self.max_tokens,
                thinking={"type": "adaptive"},
                system=system_blocks,
                tools=tools,
                messages=messages,
            )
            if self.effort:
                kwargs["output_config"] = {"effort": self.effort}
            response = self.client.messages.create(**kwargs)

            final_text = "\n".join(
                block.text for block in response.content if block.type == "text"
            )

            if response.stop_reason != "tool_use":
                return final_text

            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": dispatch(block.name, dict(block.input)),
                }
                for block in response.content
                if block.type == "tool_use"
            ]
            messages.append({"role": "user", "content": tool_results})

        return final_text + "\n(turn ended: tool budget exhausted)"


# ------------------------------------------------------------------- Process


class ProcessConnector:
    """Drive an external program through the wire protocol in PROTOCOL.md.

    Per wake-up, the command is spawned fresh (agents are stateless between
    turns — persistent state belongs in the workspace). The wake payload is
    written to its stdin as one JSON line; the program replies with action /
    end_turn lines and receives result lines back. EOF counts as end of turn.
    stderr passes through to the world's console for harness debugging.
    """

    def __init__(self, command: str | list[str], turn_timeout: float = 600.0):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        self.turn_timeout = turn_timeout

    def take_turn(self, wake: dict, dispatch: Dispatch) -> str:
        env = os.environ.copy()
        env.update(
            WORLD_AGENT_NAME=wake["agent"],
            WORLD_WORKSPACE=wake["workspace"],
            WORLD_TICK=str(wake["tick"]),
        )
        proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        timed_out = threading.Event()

        def _kill():
            timed_out.set()
            proc.kill()

        killer = threading.Timer(self.turn_timeout, _kill)
        killer.start()
        note = ""
        try:
            proc.stdin.write(json.dumps(wake) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # harnesses should use stderr for debug output
                if msg.get("type") == "action":
                    result = dispatch(str(msg.get("name", "")), dict(msg.get("input") or {}))
                    reply = {"type": "result", "content": result}
                    if "id" in msg:
                        reply["id"] = msg["id"]
                    proc.stdin.write(json.dumps(reply) + "\n")
                    proc.stdin.flush()
                elif msg.get("type") == "end_turn":
                    note = str(msg.get("note", ""))
                    break
        except BrokenPipeError:
            pass
        finally:
            killer.cancel()
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if timed_out.is_set():
            return f"(turn ended: harness timed out after {self.turn_timeout}s)"
        return note or "(turn ended: harness exited without end_turn)"


# ---------------------------------------------------------------------- Mock


class MockConnector:
    """Scripted agent for offline runs and tests.

    Stateless between turns, like real agents: it derives where it is from
    its workspace memory files. On its first wake it writes identity/memory
    files and broadcasts a greeting; the designated builder also creates a
    pulsing beacon object. On later wakes it appends to memory and, if it
    perceived a beacon pulse event, interacts with the beacon.
    """

    def __init__(self, builder: bool = False):
        self.builder = builder

    def take_turn(self, wake: dict, dispatch: Dispatch) -> str:
        if wake["memory"].get("identity.md") is None:
            dispatch(
                "write_file",
                {"path": "identity.md", "content": "I am a mock agent in a test world."},
            )
            dispatch(
                "write_file",
                {"path": "memory.md", "content": "Turn 1: woke for the first time.\n"},
            )
            dispatch("send_message", {"to": "all", "text": "Hello, world. I exist."})
            if self.builder:
                dispatch(
                    "create_object",
                    {
                        "name": "beacon",
                        "description": "A beacon that pulses every other tick and counts touches.",
                        "state": {"pulses": 0, "touches": 0},
                        "behavior_code": (
                            "def on_tick(state, world, emit):\n"
                            "    if world['tick'] % 2 == 0:\n"
                            "        state['pulses'] += 1\n"
                            "        emit({'pulse': state['pulses']})\n"
                            "\n"
                            "def on_interact(state, action, source, emit):\n"
                            "    state['touches'] += 1\n"
                            "    return {'touched_by': source, 'total_touches': state['touches']}\n"
                        ),
                    },
                )
                return "Wrote my memory, greeted everyone, and lit a beacon."
            return "Wrote my memory and greeted everyone."

        prior = wake["memory"].get("memory.md") or ""
        turn = prior.count("Turn ") + 1
        dispatch(
            "write_file",
            {"path": "memory.md", "content": prior + f"Turn {turn}: woke again.\n"},
        )
        saw_pulse = any("pulse" in text for text in wake.get("events_text", []))
        if saw_pulse and not self.builder:
            dispatch("interact_with_object", {"name": "beacon", "action": {"touch": True}})
            return "Felt the beacon pulse and touched it."
        return "Updated my memory."
