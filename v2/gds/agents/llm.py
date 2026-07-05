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
        fn("set_state",
           "Replace your own state for next turn. This is your only memory AND the "
           "only thing others can perceive about you: any object observing you reads "
           "exactly this. The object you pass REPLACES your current state (it is not "
           "merged), so include everything you want to keep.",
           {"state": {"type": "object",
                      "description": "Your full new state as a JSON object."}}, ["state"]),
        fn("add_arc",
           "Start observing another object, so its state appears in what you see on "
           "future turns. `target` is an identifier — matched exactly, so use a name "
           "from the registry's ledger verbatim (names are case-sensitive). The arc "
           "takes effect next turn; if `target` names no existing object it is "
           "refused and the world tells you so next turn. Observing is one-way and "
           "silent: the target is not notified and cannot see you unless it observes "
           "you back.",
           {"target": {"type": "string",
                       "description": "Identifier of the object to start observing."}},
           ["target"]),
        fn("remove_arc",
           "Stop observing an object you currently observe (its state will no longer "
           "appear in what you see).",
           {"target": {"type": "string",
                       "description": "Identifier of the object to stop observing."}},
           ["target"]),
        fn("add_vertex",
           "Create a new object in the world. You must give it a `name` — a short "
           "human-readable label (e.g. \"logger\", \"counter\") that becomes its "
           "identifier, so you and others can find and read it later (a matching or "
           "similar name is added automatically if yours is already taken). From "
           "next turn it exists alongside you (discoverable via the registry). Its "
           "behaviour is `code`: Python source defining a function "
           "`transition(state, inputs, emit)` that returns the object's next state "
           "each turn (`state` is its own state, `inputs` maps each observed object "
           "to its state, and `emit({...})` queues effects like "
           "{'op':'add_arc','target':...} or {'op':'add_vertex',...}). Only "
           "math/random/json are available — no imports, files, or network. Return "
           "None to keep the current state.",
           {"name": {"type": "string",
                     "description": "Short human-readable label for the new object "
                                    "(letters, digits, underscores)."},
            "state": {"type": "object",
                      "description": "The new object's initial state (JSON)."},
            "code": {"type": "string",
                     "description": "Python source defining transition(state, inputs, emit)."},
            "observes": {"type": "array", "items": {"type": "string"},
                         "description": "Identifiers the new object should observe from birth."}},
           ["name", "state", "code"]),
    ]


class LLMKernel(TransitionKernel):
    """A transition kernel driven by an injected `chat` model boundary.

    Args:
        chat: ``chat(messages: list[dict], tools: list[dict]) -> dict`` returning
            an assistant message ``{"content": str|None, "tool_calls": [...]}``.
        system: optional system-prompt string (a default is used otherwise).
        max_rounds: max model calls per `evaluate` (loop cap).
        tools: optional private tools, ``{name: {"spec": ..., "handler": ...}}``.
        continuous: if True (default), the kernel keeps ONE running conversation
            across steps — each step appends the new render and the agent's replies
            to the same message list, so the agent remembers prior turns directly
            (memory in the dialogue, as a normal chat agent). If False, every step
            is a fresh conversation reconstructed only from the vertex's own state
            (the substrate's stateless-between-turns default). The prompt is built
            here on the *client* side, so this continuity is the kernel's choice,
            not a substrate property. NB: continuous history is hidden kernel state
            not stored in the Configuration, so it is lost on record-replay/resume,
            and it grows each step (watch the model's context window on long runs).
    """

    def __init__(
        self,
        chat: Callable[[list, list], dict],
        *,
        system: str | None = None,
        max_rounds: int = 6,
        tools: PrivateTools | None = None,
        recorder: Callable[[list], None] | None = None,
        continuous: bool = True,
    ):
        self.chat = chat
        self.system = system
        self.max_rounds = max_rounds
        self.tools = dict(tools or {})
        self.continuous = continuous
        # The running conversation when continuous=True; spans the kernel's lifetime
        # (one per agent vertex, reused every step). Empty until the first turn.
        self._history: list = []
        # Substrate feedback about the PREVIOUS turn's effects (e.g. an arc refused
        # because its target does not exist), queued by `notify` and surfaced to
        # the model at the start of the next turn so it can self-correct.
        self._pending_notices: list[str] = []
        # Optional sink for the per-turn transcript (the `messages` list). Purely
        # observational — it never affects what the agent does or returns, so the
        # substrate's semantics are unchanged whether or not one is attached. The
        # viewer uses it to render agent trajectories.
        self.recorder = recorder

    # ---------------------------------------------------------------- feedback

    def notify(self, reasons) -> None:
        """Receive the engine's report on the PREVIOUS turn's effects.

        The engine calls this before the next `evaluate` when one of this vertex's
        emitted updates was refused (e.g. an `add_arc` whose target does not
        exist). The reasons are surfaced to the model on the next turn so it can
        correct course — closing the loop from the authoritative layer (which owns
        the object list) back up to the agent.
        """
        self._pending_notices.extend(str(r) for r in reasons)

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
        # This turn's user message: any substrate feedback about last turn's
        # refused effects, then the current observation.
        user_content = self._render(state, inputs)
        if self._pending_notices:
            notice = ("The world reports on your last turn:\n"
                      + "\n".join(f"- {r}" for r in self._pending_notices))
            user_content = notice + "\n\n" + user_content
            self._pending_notices = []
        # Continuous: continue the one running conversation (append this step's
        # render as the next user turn). Fresh: rebuild from system + render only.
        if self.continuous and self._history:
            messages = self._history
            turn_start = len(messages)
            messages.append({"role": "user", "content": user_content})
        else:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user_content})
            turn_start = 0
            if self.continuous:
                self._history = messages  # seed the running conversation
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
            # Best-effort: a broken sink must never break the agent's turn. Record
            # only THIS turn's messages (the slice added this step) so per-step
            # transcripts stay per-step even when the conversation is continuous.
            try:
                self.recorder(messages[turn_start:])
            except Exception:
                pass

        return Step(next_state, tuple(updates))

    def _apply(self, name, args: dict, updates: list) -> dict:
        """Handle one tool call. Substrate effects append to `updates`; private
        tools run their handler. Returns {"content": <feedback>, optionally
        "state": <new next_state>}.

        Note: substrate effects are *requests* applied at the end of the turn, so
        this only validates their shape. Whether an effect is legal (e.g. an arc's
        target actually exists) is decided authoritatively by the engine when it
        applies the update; any refusal is reported back to this kernel via
        `notify` and surfaced to the model on its next turn.
        """
        if name == "set_state":
            if "state" not in args:
                return {"content": "error: set_state requires 'state' parameter (your new state as JSON)"}
            state = args["state"]
            if not isinstance(state, dict):
                return {"content": f"error: 'state' must be a JSON object, not {type(state).__name__}"}
            return {"content": "ok", "state": state}
        if name == "add_arc":
            target = args.get("target")
            if target is None or not isinstance(target, str):
                return {"content": "error: add_arc requires 'target' parameter (a vertex identifier string)"}
            updates.append(AddArc(target))
            return {"content": "ok (requested — takes effect next turn if the object exists)"}
        if name == "remove_arc":
            target = args.get("target")
            if target is None or not isinstance(target, str):
                return {"content": "error: remove_arc requires 'target' parameter (a vertex identifier string)"}
            updates.append(RemoveArc(target))
            return {"content": "ok"}
        if name == "add_vertex":
            if "state" not in args:
                return {"content": "error: add_vertex requires 'state' parameter (the new vertex's initial state as JSON)"}
            if "code" not in args:
                return {"content": "error: add_vertex requires 'code' parameter (Python source defining transition(state, inputs, emit))"}
            code = args["code"]
            if not isinstance(code, str):
                return {"content": f"error: 'code' must be a string, not {type(code).__name__}"}
            observes = args.get("observes", [])
            if not isinstance(observes, list):
                return {"content": f"error: 'observes' must be an array of vertex identifiers, not {type(observes).__name__}"}
            try:
                out_arcs = frozenset(observes)
            except TypeError:
                return {"content": "error: 'observes' must contain only strings (vertex identifiers)"}
            name = args.get("name")
            if name is None or not isinstance(name, str) or not name.strip():
                return {"content": "error: add_vertex requires 'name' parameter (a short human-readable label for the new object, e.g. \"logger\")"}
            updates.append(AddVertex(
                initial_state=args.get("state", {}),
                kernel=LocalKernel(code),
                out_arcs=out_arcs,
                name=name,
            ))
            return {"content": f"ok — creating object named {name!r} (its exact id may be suffixed if the name is taken; check the registry next turn)"}
        if name in self.tools:
            try:
                return {"content": str(self.tools[name]["handler"](args))}
            except Exception as exc:  # private tool failure is reported, not fatal
                return {"content": f"error: {exc!r}"}
        return {"content": f"error: unknown tool '{name}' (available: set_state, add_arc, remove_arc, add_vertex)"}
