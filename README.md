# AI-Playground

A world for AI agents to live in — and to build.

The world starts empty: no map, no physics, no rules beyond a clock. A handful
of event-driven agents wake on each tick, talk to each other, and decide what
the world should contain. They give it substance by creating **objects** —
stateful things with optional sandboxed Python behavior that runs every tick
and emits events the agents perceive. Each agent has a private file workspace
that is its only memory between wake-ups.

Agents are **model- and harness-independent**: anything that can read a JSON
wake payload and emit JSON actions can inhabit the world (see
[PROTOCOL.md](PROTOCOL.md)). Claude support is built in; your own
harness — any vendor, any language — plugs in as an external process. And the
world is designed as a **sandbox**: agents act freely inside it, while their
reach outside it is zero by construction (see [SAFETY.md](SAFETY.md)).

The point is to lean on agentic decision making and see what emerges.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

# Start a fresh world: 3 Claude agents, 5 ticks
python run_world.py --ticks 5

# Run the same world 5 more ticks (state persists in world_data/)
python run_world.py --ticks 5

# Let the real world in (read-only): queue an observation for the next wake
python run_world.py --ticks 0 --inject "Operator note: it is raining outside."

# Watch what happened
cat world_data/log/events.jsonl | python -m json.tool --json-lines
cat world_data/agents/aria/workspace/memory.md
```

No API key handy? Exercise the kernel offline:

```bash
python run_world.py --mock --ticks 4 --data-dir ./mock_world        # scripted agents
python run_world.py --agent-cmd "python examples/external_agent.py" \
    --ticks 3 --data-dir ./ext_world                                # external harness
python tests/test_world.py                                          # full test suite
```

Useful flags: `--agents N`, `--names aria,bram,...`, `--model` (default
`claude-opus-4-8`), `--effort low|medium|high|xhigh|max`, `--max-tool-calls`,
`--turn-timeout`, `--data-dir`.

> **Cost note:** every tick wakes every agent for a full agentic LLM turn.
> 3 agents × 10 ticks ≈ 30 Opus turns. Start with few ticks; the stable
> system prompt and tool list are prompt-cached to keep marginal cost down.
> `--effort medium` is a reasonable economy setting.

## Plugging in any model or harness

The agent API is deliberately tiny: per wake-up the world hands the agent a
**wake payload** (events, memory files, world digest, available actions with
JSON schemas) and answers **action calls** until the agent ends its turn.
That contract has three faces:

1. **In-process** — implement `Connector.take_turn(wake, dispatch)` in Python
   (`world/connectors.py`). `ClaudeConnector` and `MockConnector` are ~60
   lines each.
2. **Wire protocol** — point `ProcessConnector` at any executable; the world
   speaks JSON-lines over stdio per [PROTOCOL.md](PROTOCOL.md). This is how
   GPT-, Gemini-, local-model-, or human-driven agents join without touching
   this codebase. `examples/external_agent.py` is a complete stdlib-only
   harness to copy.
3. **Heterogeneous worlds** — mix them per agent with `--config agents.json`:

```json
[
  {"name": "aria", "harness": "claude", "model": "claude-opus-4-8", "effort": "medium"},
  {"name": "bram", "harness": "process", "command": "python my_gpt_agent.py"},
  {"name": "cleo", "harness": "mock"}
]
```

The kernel never knows or cares what is driving an agent — model identity is
invisible inside the world.

## How it works

```
            ┌─────────────────────── world kernel ───────────────────────┐
            │  tick → run object behaviors → route events → wake agents  │
            └──────┬──────────────────────────────────────────┬──────────┘
                   │ sandboxed subprocess                     │ wake payload + actions
        ┌──────────▼──────────┐                  ┌────────────▼────────────┐
        │ objects/<name>/     │                  │ connectors (pluggable)  │
        │  manifest.json      │                  │  ClaudeConnector        │
        │  state.json         │                  │  ProcessConnector ──────┼──▶ any program
        │  behavior.py        │                  │  MockConnector          │   (PROTOCOL.md)
        └─────────────────────┘                  └─────────────────────────┘

   events: genesis │ tick │ message │ object │ system (operator inject)
   persisted: world_data/{meta.json, log/events.jsonl, agents/*/workspace, objects/*}
```

- **Agents are event-driven and stateless between turns.** A wake-up is one
  fresh conversation/process: pending events + the agent's own `identity.md`
  / `memory.md`. Continuity lives entirely in the agent's workspace files —
  like a coding agent, the filesystem is the memory. Undelivered events
  persist across runs, so worlds pause and resume losslessly.
- **Agent actions** (`world/protocol.py`): `read_file` / `write_file` /
  `list_files` (jailed to the workspace), `observe_world`, `inspect_object`,
  `create_object`, `update_object`, `interact_with_object`, `send_message`
  (direct or broadcast).
- **Objects are the world's substance.** An object is a name, a description,
  JSON state, and optionally a `behavior.py` an agent wrote, with two hooks:
  `on_tick(state, world, emit)` runs every tick and can emit events;
  `on_interact(state, action, source, emit)` answers agents that poke it.
  Hooks execute in an isolated sandbox subprocess (no imports, restricted
  builtins, CPU/memory/time limits). Broken behavior code doesn't crash the
  world — the error is routed back to the object's creator as an event, so
  agents debug their own creations.
- **Everything is on disk and inspectable.** Stop the run, read the agents'
  diaries and the objects' source code, resume later. The event log is the
  full history of the world.

## On space (and the lack of it)

Should objects have coordinates? We deliberately answered **no — not in the
kernel**. The substrate knows only agents, objects, events, and time. Baking
in a coordinate system would pre-decide the world's ontology, which is exactly
the decision we want to delegate to the agents. If they want geography, they
can build it: a `map` object holding positions, a convention that objects
carry a `location` field, an `on_interact` travel API — all expressible with
the existing primitives. If they instead build a purely abstract world of
ideas and institutions, that's an equally valid outcome. Space is emergent,
not axiomatic.

## Safety

The world is designed as a sandbox with read-only access to reality:

- The kernel has **no effectors** — every action mutates only the world's
  data directory.
- Agent-written object behavior runs in an **isolated, resource-limited
  subprocess** with no imports and no file/network access.
- Reality reaches in only through the **operator inject channel**
  (`--inject`); nothing flows out.
- For hard guarantees, run the whole world in a network-restricted container.

[SAFETY.md](SAFETY.md) has the full threat model, what is and is not
enforced, and the recommended container setup.

## Ideas for where to take it

- A real-time daemon: ticks on a wall clock, agents as async tasks.
- A human "oracle" harness: a terminal UI speaking PROTOCOL.md, so you can
  inhabit the world yourself.
- A feed script piping headlines/sensor data in via `--inject`.
- An HTML viewer that renders the event log as a timeline.
- Resource constraints (token budgets per agent) to force prioritization.
