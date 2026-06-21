"""`LLMKernel` — a vertex whose transition kernel is an LLM (an *agent*).

An agent is just an object whose ``κᵥ`` is a model. Each `evaluate` is one of the
agent's turns: it is shown its own state and what it observes, and it acts through
the same substrate effectors any vertex has — set its next state, rewire its own
out-arcs, or create a new thing — expressed as model tool calls.

The model is injected as a ``chat(messages, tools) -> assistant_message`` callable
(OpenAI-style), so the kernel is model-agnostic and testable with a scripted stub.
Optional *private tools* (e.g. ``run_command``) are the agent's own affordances:
their results feed back into the loop and they do NOT touch the world.

STATUS: interface stub for TDD — body lands in the Phase 3 implementation.
"""

from __future__ import annotations

import json
from typing import Callable

from ..configuration import State
from ..digraph import Vertex
from ..kernel import PENDING, LocalKernel, Result, Step, TransitionKernel
from ..topology import AddArc, AddVertex, RemoveArc

# A private-tool entry: {"spec": <function-spec dict>, "handler": callable(args)->str}.
PrivateTools = dict

DEFAULT_SYSTEM = (
    "You are a vertex in a world of objects. Each turn you are shown your own "
    "state and the states you observe. Act through the provided tools: call "
    "set_state to update your own state (your memory), add_arc/remove_arc to "
    "choose what you observe, and add_vertex to create a new thing. When you are "
    "finished, stop calling tools."
)


def _substrate_tool_specs() -> list[dict]:
    """OpenAI-style function specs for the built-in substrate effectors."""
    def fn(name, desc, props, required=()):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(required)},
        }}

    return [
        fn("set_state", "Set your own next state.",
           {"state": {"type": "object", "description": "Your new state (JSON)."}}, ["state"]),
        fn("add_arc", "Observe another vertex (add an out-arc from yourself).",
           {"target": {"type": "string"}}, ["target"]),
        fn("remove_arc", "Stop observing a vertex.",
           {"target": {"type": "string"}}, ["target"]),
        fn("add_vertex", "Create a new vertex with an initial state and behaviour code.",
           {"state": {"type": "object"}, "code": {"type": "string"},
            "observes": {"type": "array", "items": {"type": "string"}}}, ["state", "code"]),
    ]


class LLMKernel(TransitionKernel):
    """A transition kernel driven by an injected `chat` model boundary.

    Args:
        chat: ``chat(messages: list[dict], tools: list[dict]) -> dict`` returning
            an assistant message ``{"content": str|None, "tool_calls": [...]}``.
        system: optional system-prompt string (a default is used otherwise).
        max_rounds: max model calls per `evaluate` (loop cap).
        tools: optional private tools, ``{name: {"spec": ..., "handler": ...}}``.
    """

    def __init__(
        self,
        chat: Callable[[list, list], dict],
        *,
        system: str | None = None,
        max_rounds: int = 6,
        tools: PrivateTools | None = None,
        recorder: Callable[[list], None] | None = None,
    ):
        self.chat = chat
        self.system = system
        self.max_rounds = max_rounds
        self.tools = dict(tools or {})
        # Optional sink for the per-turn transcript (the `messages` list). Purely
        # observational — it never affects what the agent does or returns, so the
        # substrate's semantics are unchanged whether or not one is attached. The
        # viewer uses it to render agent trajectories.
        self.recorder = recorder

    # ------------------------------------------------------------------ prompt

    def _render(self, state: State, inputs: dict[Vertex, State]) -> str:
        # Present only facts — the vertex's own state and what it observes. Any
        # framing/instruction is left to the system prompt, so a caller can give
        # an agent as little or as much guidance as they want.
        return (
            "Your state:\n" + json.dumps(state, default=str)
            + "\n\nYou observe:\n" + json.dumps(inputs, default=str)
        )

    def _tool_specs(self) -> list[dict]:
        specs = list(_substrate_tool_specs())
        for entry in self.tools.values():
            spec = entry.get("spec")
            if spec is not None:
                specs.append({"type": "function", "function": spec})
        return specs

    # -------------------------------------------------------------- one turn

    def evaluate(self, state: State, inputs: dict[Vertex, State]) -> Result:
        # system is None -> use the default; system "" -> no system message at all
        # (lets a caller hand the agent essentially nothing). A non-empty string
        # is used verbatim.
        system = DEFAULT_SYSTEM if self.system is None else self.system
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": self._render(state, inputs)})
        tool_specs = self._tool_specs()

        next_state = state
        updates: list = []

        for _ in range(self.max_rounds):
            try:
                reply = self.chat(messages, tool_specs)
            except Exception:
                # An unreachable / failing model means the agent did not act this
                # step — it simply holds its state (timing as part of dynamics).
                return PENDING

            reply = reply if isinstance(reply, dict) else {"content": str(reply)}
            calls = reply.get("tool_calls") or []
            messages.append({"role": "assistant", **reply})
            if not calls:
                break

            for call in calls:
                fn = call.get("function", {}) if isinstance(call, dict) else {}
                name = fn.get("name")
                raw = fn.get("arguments", "{}")
                cid = call.get("id", "") if isinstance(call, dict) else ""
                try:
                    args = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
                except (json.JSONDecodeError, TypeError, ValueError):
                    messages.append({"role": "tool", "tool_call_id": cid,
                                     "content": "error: arguments were not valid JSON"})
                    continue

                result = self._apply(name, args, updates)
                next_state = result.get("state", next_state)
                messages.append({"role": "tool", "tool_call_id": cid, "content": result["content"]})

        if self.recorder is not None:
            # Best-effort: a broken sink must never break the agent's turn.
            try:
                self.recorder(messages)
            except Exception:
                pass

        return Step(next_state, tuple(updates))

    def _apply(self, name, args: dict, updates: list) -> dict:
        """Handle one tool call. Substrate effects append to `updates`; private
        tools run their handler. Returns {"content": <feedback>, optionally
        "state": <new next_state>}."""
        if name == "set_state":
            return {"content": "ok", "state": args["state"]} if "state" in args else {"content": "ok"}
        if name == "add_arc":
            target = args.get("target")
            if target is not None:
                updates.append(AddArc(target))
            return {"content": "ok"}
        if name == "remove_arc":
            target = args.get("target")
            if target is not None:
                updates.append(RemoveArc(target))
            return {"content": "ok"}
        if name == "add_vertex":
            updates.append(AddVertex(
                initial_state=args.get("state", {}),
                kernel=LocalKernel(args.get("code", "")),
                out_arcs=frozenset(args.get("observes", [])),
            ))
            return {"content": "ok"}
        if name in self.tools:
            try:
                return {"content": str(self.tools[name]["handler"](args))}
            except Exception as exc:  # private tool failure is reported, not fatal
                return {"content": f"error: {exc!r}"}
        return {"content": f"error: unknown tool {name!r}"}
