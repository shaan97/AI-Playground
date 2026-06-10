"""Brains: the decision-making half of an agent.

ClaudeBrain runs a manual tool-use loop against the Claude API.
MockBrain is a deterministic scripted brain so the kernel can be exercised
(and tested) without an API key.
"""

from __future__ import annotations

DEFAULT_MODEL = "claude-opus-4-8"


class ClaudeBrain:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str | None = None,
        max_tool_iterations: int = 16,
        max_tokens: int = 16000,
        client=None,
    ):
        import anthropic  # lazy so --mock runs don't require the SDK

        self.model = model
        self.effort = effort
        self.max_tool_iterations = max_tool_iterations
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic()

    def run_turn(self, system: str, user_prompt: str, tools: list[dict], dispatch) -> str:
        messages: list[dict] = [{"role": "user", "content": user_prompt}]
        # The system prompt and tool list are byte-stable across every turn of
        # every run, so a cache breakpoint on the system block caches both.
        system_blocks = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

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


class MockBrain:
    """Scripted brain for offline runs and tests.

    On its first wake it writes identity/memory files and broadcasts a
    greeting; the designated builder also creates a pulsing beacon object.
    On later wakes it appends to memory and, if it sees a beacon pulse,
    interacts with the beacon.
    """

    def __init__(self, builder: bool = False):
        self.builder = builder
        self.turn = 0

    def run_turn(self, system: str, user_prompt: str, tools: list[dict], dispatch) -> str:
        self.turn += 1
        if self.turn == 1:
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

        prior = dispatch("read_file", {"path": "memory.md"})
        dispatch(
            "write_file",
            {"path": "memory.md", "content": prior + f"Turn {self.turn}: woke again.\n"},
        )
        if "pulse" in user_prompt and not self.builder:
            dispatch("interact_with_object", {"name": "beacon", "action": {"touch": True}})
            return "Felt the beacon pulse and touched it."
        return "Updated my memory."
