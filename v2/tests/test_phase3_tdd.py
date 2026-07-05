import sys; from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from gds import Configuration, Digraph, GraphDynamicalSystem, FunctionKernel, Step, PENDING, AddArc, AddVertex, RemoveArc, LocalKernel, install_registry
from gds.agents.llm import LLMKernel

import json

# ---------------------------------------------------------------------------
# Tiny test harness (stdlib only)
# ---------------------------------------------------------------------------
_RESULTS = []


def run(name, fn):
    try:
        fn()
    except AssertionError as e:
        _RESULTS.append((name, "FAIL", str(e)))
        print(f"FAIL {name}: {e}")
    except Exception as e:  # noqa: BLE001
        _RESULTS.append((name, "ERROR", f"{type(e).__name__}: {e}"))
        print(f"ERROR {name}: {type(e).__name__}: {e}")
    else:
        _RESULTS.append((name, "ok", ""))
        print(f"ok   {name}")


# ---------------------------------------------------------------------------
# Scripted chat stub
# ---------------------------------------------------------------------------
class ScriptedChat:
    """A stateful callable returning queued assistant messages and recording
    every (messages, tools) it was invoked with."""

    def __init__(self, replies):
        # replies: list of assistant-message dicts to return in order.
        self._replies = list(replies)
        self.calls = []  # list of (messages, tools)

    def __call__(self, messages, tools):
        # Record a deep-ish snapshot of what we were handed.
        self.calls.append((messages, tools))
        if self._replies:
            return self._replies.pop(0)
        # Default: no tool calls -> ends the loop.
        return {"content": "done"}

    @property
    def call_count(self):
        return len(self.calls)


def tool_call(name, args, cid="c1"):
    return {"id": cid, "function": {"name": name, "arguments": json.dumps(args)}}


def assistant(content=None, tool_calls=None):
    msg = {"content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


# ---------------------------------------------------------------------------
# Test 1: set_state
# ---------------------------------------------------------------------------
def test_set_state():
    chat = ScriptedChat([
        assistant(tool_calls=[tool_call("set_state", {"state": {"mood": "curious"}})]),
        assistant(content="done"),
    ])
    k = LLMKernel(chat)
    result = k.evaluate({"mood": "old"}, ())
    assert result is not PENDING, "expected a Step, got PENDING"
    assert isinstance(result, Step), f"expected Step, got {type(result)}"
    assert result.next_state == {"mood": "curious"}, f"next_state={result.next_state!r}"
    assert tuple(result.updates) == (), f"updates should be empty, got {result.updates!r}"


# ---------------------------------------------------------------------------
# Test 2: no tool calls -> unchanged state
# ---------------------------------------------------------------------------
def test_no_tool_calls():
    chat = ScriptedChat([assistant(content="just thinking out loud")])
    k = LLMKernel(chat)
    state = {"x": 1}
    result = k.evaluate(state, ())
    assert isinstance(result, Step), f"expected Step, got {type(result)}"
    assert result.next_state == {"x": 1}, f"next_state={result.next_state!r}"
    assert tuple(result.updates) == (), f"updates should be empty, got {result.updates!r}"


# ---------------------------------------------------------------------------
# Test 3a: add_arc / remove_arc produce the right effects
# ---------------------------------------------------------------------------
def test_add_remove_arc_effects():
    chat = ScriptedChat([
        assistant(tool_calls=[
            tool_call("add_arc", {"target": "v9"}, cid="a1"),
            tool_call("remove_arc", {"target": "v3"}, cid="a2"),
        ]),
        assistant(content="done"),
    ])
    k = LLMKernel(chat)
    # evaluate just emits the requested effects; whether a target exists is decided
    # authoritatively by the engine at apply time, not here.
    result = k.evaluate({}, ())
    assert isinstance(result, Step), f"expected Step, got {type(result)}"
    updates = tuple(result.updates)
    add = [u for u in updates if isinstance(u, AddArc)]
    rem = [u for u in updates if isinstance(u, RemoveArc)]
    assert len(add) == 1, f"expected one AddArc, got {updates!r}"
    assert len(rem) == 1, f"expected one RemoveArc, got {updates!r}"
    assert add[0].target == "v9", f"AddArc target={add[0].target!r}"
    assert rem[0].target == "v3", f"RemoveArc target={rem[0].target!r}"
    # call order preserved
    assert isinstance(updates[0], AddArc) and isinstance(updates[1], RemoveArc), \
        f"effects out of call order: {updates!r}"


# ---------------------------------------------------------------------------
# Test 3b: end-to-end out-star changes in a GDS (no reverse arc)
# ---------------------------------------------------------------------------
def test_add_arc_end_to_end():
    # Actor "A" decides to add an arc to "B"; should never add the reverse.
    chat = ScriptedChat([
        assistant(tool_calls=[tool_call("add_arc", {"target": "B"})]),
        assistant(content="done"),
        assistant(content="done"),
        assistant(content="done"),
    ])
    actor = LLMKernel(chat)
    config = Configuration(
        Digraph.of({"A": set(), "B": set()}),
        {"A": {}, "B": {"v": 0}},
    )
    gds = GraphDynamicalSystem(config, {"A": actor, "B": FunctionKernel(lambda s, i: Step(s))})
    gds.step()
    out_A = set(gds.config.digraph.out_neighbours("A"))
    out_B = set(gds.config.digraph.out_neighbours("B"))
    assert "B" in out_A, f"A should observe B after add_arc, out(A)={out_A!r}"
    assert "A" not in out_B, f"reverse arc must not appear, out(B)={out_B!r}"


# ---------------------------------------------------------------------------
# Test 4a: add_vertex effect carries a LocalKernel
# ---------------------------------------------------------------------------
def test_add_vertex_effect():
    code = "def transition(state, inputs):\n    return state\n"
    chat = ScriptedChat([
        assistant(tool_calls=[tool_call("add_vertex", {
            "name": "child",
            "state": {"born": True},
            "code": code,
            "observes": ["A"],
        })]),
        assistant(content="done"),
    ])
    k = LLMKernel(chat)
    result = k.evaluate({}, ())
    assert isinstance(result, Step), f"expected Step, got {type(result)}"
    adds = [u for u in tuple(result.updates) if isinstance(u, AddVertex)]
    assert len(adds) == 1, f"expected one AddVertex, got {result.updates!r}"
    av = adds[0]
    assert isinstance(av.kernel, LocalKernel), f"kernel should be LocalKernel, got {type(av.kernel)}"
    assert av.initial_state == {"born": True}, f"initial_state={av.initial_state!r}"
    assert "A" in set(av.out_arcs), f"out_arcs should include A, got {av.out_arcs!r}"
    assert av.name == "child", f"name hint should be carried, got {av.name!r}"


# ---------------------------------------------------------------------------
# Test 4b: add_vertex end-to-end with registry coupling
# ---------------------------------------------------------------------------
def test_add_vertex_end_to_end_registry():
    code = "def transition(state, inputs):\n    return state\n"
    chat = ScriptedChat([
        assistant(tool_calls=[tool_call("add_vertex", {
            "name": "child",
            "state": {"born": True},
            "code": code,
            "observes": [],
        })]),
        assistant(content="done"),
        assistant(content="done"),
        assistant(content="done"),
    ])
    actor = LLMKernel(chat)
    config = Configuration(Digraph.of({"A": set()}), {"A": {}})
    gds = GraphDynamicalSystem(config, {"A": actor})
    registry = install_registry(gds)
    gds.step()
    verts = set(gds.config.digraph.vertices())
    # The agent named its child; the engine should use that as the label.
    assert "child" in verts, f"named child 'child' should exist, got {verts!r}"
    # Originals plus the registry plus exactly one minted child.
    minted = [v for v in verts if v not in ("A",) and v != registry]
    assert len(minted) == 1, f"expected exactly one minted child, got {minted!r} (all={verts!r})"
    child = minted[0]
    out_child = set(gds.config.digraph.out_neighbours(child))
    out_reg = set(gds.config.digraph.out_neighbours(registry))
    coupled = (registry in out_child) and (child in out_reg)
    assert coupled, (
        f"child must be registry-coupled: out(child)={out_child!r} out(reg)={out_reg!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: multi-round private tool
# ---------------------------------------------------------------------------
def test_multi_round_private_tool():
    handler_calls = []

    def run_command(args):
        handler_calls.append(args)
        return "linux-result"

    tools = {
        "run_command": {
            "spec": {
                "name": "run_command",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                },
            },
            "handler": run_command,
        }
    }

    chat = ScriptedChat([
        # Round 1: call the private tool.
        assistant(tool_calls=[tool_call("run_command", {"cmd": "uname"})]),
        # Round 2: call set_state embedding the result string.
        assistant(tool_calls=[tool_call("set_state", {"state": {"os": "linux-result"}})]),
        # Round 3: no tool calls -> stop.
        assistant(content="done"),
    ])
    k = LLMKernel(chat, tools=tools)
    result = k.evaluate({"os": "unknown"}, ())

    assert isinstance(result, Step), f"expected Step, got {type(result)}"
    assert len(handler_calls) == 1, f"handler should be called once, got {handler_calls!r}"
    assert handler_calls[0] == {"cmd": "uname"}, f"handler args={handler_calls[0]!r}"
    assert chat.call_count >= 2, f"expected at least 2 chat calls, got {chat.call_count}"
    assert result.next_state == {"os": "linux-result"}, f"next_state={result.next_state!r}"

    # The 2nd chat call's messages must contain the handler result string.
    second_messages = chat.calls[1][0]
    blob = json.dumps(second_messages, default=str)
    assert "linux-result" in blob, "result string not fed back into round-2 messages"


# ---------------------------------------------------------------------------
# Test 6a: chat raises -> PENDING
# ---------------------------------------------------------------------------
def test_chat_raises_pending():
    def boom(messages, tools):
        raise RuntimeError("model down")

    k = LLMKernel(boom)
    result = k.evaluate({"keep": "me"}, ())
    assert result is PENDING, f"expected PENDING, got {result!r}"


# ---------------------------------------------------------------------------
# Test 6b: PENDING vertex keeps its state across a step
# ---------------------------------------------------------------------------
def test_pending_keeps_state():
    def boom(messages, tools):
        raise RuntimeError("model down")

    actor = LLMKernel(boom)
    config = Configuration(Digraph.of({"A": set()}), {"A": {"v": 42}})
    gds = GraphDynamicalSystem(config, {"A": actor})
    gds.step()
    assert gds.config.state_of("A") == {"v": 42}, \
        f"PENDING vertex should keep state, got {gds.config.state_of('A')!r}"


# ---------------------------------------------------------------------------
# Test 7: max_rounds cap
# ---------------------------------------------------------------------------
def test_max_rounds_cap():
    class AlwaysToolCall:
        def __init__(self):
            self.calls = 0

        def __call__(self, messages, tools):
            self.calls += 1
            return assistant(tool_calls=[tool_call("set_state", {"state": {"n": self.calls}})])

    chat = AlwaysToolCall()
    k = LLMKernel(chat, max_rounds=3)
    result = k.evaluate({}, ())
    assert isinstance(result, Step), f"expected a Step, got {result!r}"
    assert chat.calls <= 3, f"chat called {chat.calls} times, exceeds max_rounds=3"
    assert chat.calls >= 1, "chat should be called at least once"


# ---------------------------------------------------------------------------
# Test 8: malformed arguments -> skipped, no crash
# ---------------------------------------------------------------------------
def test_malformed_arguments_skipped():
    bad_call = {"id": "x1", "function": {"name": "add_arc", "arguments": "not-json{{"}}
    good_call = tool_call("add_arc", {"target": "v7"}, cid="x2")
    chat = ScriptedChat([
        assistant(tool_calls=[bad_call, good_call]),
        assistant(content="done"),
    ])
    k = LLMKernel(chat)
    result = k.evaluate({}, ())
    assert isinstance(result, Step), f"expected Step, got {type(result)}"
    adds = [u for u in tuple(result.updates) if isinstance(u, AddArc)]
    assert len(adds) == 1, f"malformed call should be skipped; got adds={adds!r}"
    assert adds[0].target == "v7", f"good AddArc target={adds[0].target!r}"


# ---------------------------------------------------------------------------
# Test 9: isinstance of TransitionKernel + instantiable
# ---------------------------------------------------------------------------
def test_isinstance_transition_kernel():
    from gds import TransitionKernel
    chat = ScriptedChat([assistant(content="done")])
    k = LLMKernel(chat)
    assert isinstance(k, TransitionKernel), "LLMKernel must be a TransitionKernel"
    # If instantiation above succeeded, the abstractmethod is satisfied.
    assert hasattr(k, "evaluate"), "LLMKernel must expose evaluate"


# ---------------------------------------------------------------------------
# Test 10: integration -> agent observes a vertex it didn't create
# ---------------------------------------------------------------------------
def test_integration_agent_observes_child():
    # Creator: makes exactly one named child on its first step, then idles.
    creator_chat = ScriptedChat([
        assistant(tool_calls=[tool_call("add_vertex", {
            "name": "widget",
            "state": {"kind": "child"},
            "code": "def transition(state, inputs):\n    return state\n",
            "observes": [],
        })]),
    ] + [assistant(content="idle")] * 20)
    creator = LLMKernel(creator_chat)

    # Agent: discovers what exists by reading the registry's ledger (a list of
    # identifiers), then observes each — id-shape-agnostic, so it works whether
    # labels are opaque (v1) or named (widget). Skips itself and the registry.
    class GreedyAgent:
        def __call__(self, messages, tools):
            import re
            ids = set()
            for m in messages:
                content = str(m.get("content") or "") if isinstance(m, dict) else ""
                for ledger in re.findall(r'"ledger"\s*:\s*\[([^\]]*)\]', content):
                    ids |= set(re.findall(r'"([^"]+)"', ledger))
            calls = []
            for vid in sorted(ids - {"agent", "registry"}):
                calls.append(tool_call("add_arc", {"target": vid}, cid="g" + vid))
            if calls:
                return assistant(tool_calls=calls)
            return assistant(content="nothing to do")

    agent = LLMKernel(GreedyAgent())

    config = Configuration(
        Digraph.of({"creator": set(), "agent": set()}),
        {"creator": {}, "agent": {}},
    )
    gds = GraphDynamicalSystem(config, {"creator": creator, "agent": agent})
    install_registry(gds)

    # Run a generous number of steps so creation + observation can settle.
    gds.run(10)

    verts = set(gds.config.digraph.vertices())
    # The creator named its child "widget"; the engine uses the name as the label.
    assert "widget" in verts, f"creator should have minted the named child, vertices={verts!r}"
    out_agent = set(gds.config.digraph.out_neighbours("agent"))
    assert "widget" in out_agent, (
        f"agent should end up observing child 'widget'; out(agent)={out_agent!r}"
    )


# ---------------------------------------------------------------------------
# Run everything
# ---------------------------------------------------------------------------
def main():
    tests = [
        ("set_state", test_set_state),
        ("no_tool_calls", test_no_tool_calls),
        ("add_remove_arc_effects", test_add_remove_arc_effects),
        ("add_arc_end_to_end", test_add_arc_end_to_end),
        ("add_vertex_effect", test_add_vertex_effect),
        ("add_vertex_end_to_end_registry", test_add_vertex_end_to_end_registry),
        ("multi_round_private_tool", test_multi_round_private_tool),
        ("chat_raises_pending", test_chat_raises_pending),
        ("pending_keeps_state", test_pending_keeps_state),
        ("max_rounds_cap", test_max_rounds_cap),
        ("malformed_arguments_skipped", test_malformed_arguments_skipped),
        ("isinstance_transition_kernel", test_isinstance_transition_kernel),
        ("integration_agent_observes_child", test_integration_agent_observes_child),
    ]
    for name, fn in tests:
        run(name, fn)

    n_ok = sum(1 for _, s, _ in _RESULTS if s == "ok")
    n_fail = sum(1 for _, s, _ in _RESULTS if s == "FAIL")
    n_err = sum(1 for _, s, _ in _RESULTS if s == "ERROR")
    print("-" * 60)
    print(f"total={len(_RESULTS)} ok={n_ok} FAIL={n_fail} ERROR={n_err}")
    sys.exit(0 if (n_fail == 0 and n_err == 0) else 1)


if __name__ == "__main__":
    main()
