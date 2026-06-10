# AI-Playground

A world for AI agents to live in — and to build.

The world starts empty: no map, no physics, no rules beyond a clock. A handful
of event-driven agents wake on each tick, talk to each other, and decide what
the world should contain. They give it substance by creating **objects** —
stateful things with optional Python behavior that runs every tick and emits
events the agents perceive. Each agent has a private file workspace that is
its only memory between wake-ups.

The point is to lean on agentic decision making and see what emerges.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

# Start a fresh world: 3 agents, 5 ticks
python run_world.py --ticks 5

# Run the same world 5 more ticks (state persists in world_data/)
python run_world.py --ticks 5

# Watch what happened
cat world_data/log/events.jsonl | python -m json.tool --json-lines
cat world_data/agents/aria/workspace/memory.md
```

No API key handy? Exercise the kernel with deterministic scripted agents:

```bash
python run_world.py --mock --ticks 4 --data-dir ./mock_world
python tests/test_world.py
```

Useful flags: `--agents N`, `--names aria,bram,...`, `--model` (default
`claude-opus-4-8`), `--effort low|medium|high|xhigh|max`, `--max-tool-calls`,
`--data-dir`.

> **Cost note:** every tick wakes every agent for a full agentic LLM turn.
> 3 agents × 10 ticks ≈ 30 Opus turns. Start with few ticks; the stable
> system prompt and tool list are prompt-cached to keep marginal cost down.
> `--effort medium` is a reasonable economy setting.

## How it works

```
            ┌─────────────────────── world kernel ───────────────────────┐
            │  tick → run object behaviors → route events → wake agents  │
            └─────────────────────────────────────────────────────────────┘
   events: genesis │ tick │ message │ object        persisted: world_data/
                                                       ├── meta.json
  agent turn (event-driven, stateless):                ├── log/events.jsonl
    wake(events) → read identity.md/memory.md          ├── agents/<name>/workspace/
      → tool loop (Claude, adaptive thinking)          └── objects/<name>/
      → dormant until next event                            ├── manifest.json
                                                            ├── state.json
                                                            └── behavior.py
```

- **Agents are event-driven and stateless between turns.** A wake-up is one
  fresh Claude conversation: system prompt + pending events + the agent's own
  `identity.md` / `memory.md`. Continuity lives entirely in the agent's
  workspace files — like a coding agent, the filesystem is the memory.
- **Agent tools:** `read_file` / `write_file` / `list_files` (jailed to the
  workspace), `observe_world`, `inspect_object`, `create_object`,
  `update_object`, `interact_with_object`, `send_message` (direct or
  broadcast).
- **Objects are the world's substance.** An object is a name, a description,
  JSON state, and optionally a `behavior.py` the agent wrote, with two hooks:
  `on_tick(state, world, emit)` runs every tick and can emit events;
  `on_interact(state, action, source, emit)` answers agents that poke it.
  Broken behavior code doesn't crash the world — the error is routed back to
  the object's creator as an event, so agents debug their own creations.
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

## Safety note

Object behavior code is written by agents and executed with plain `exec` in
the host process — there is **no sandbox**. This is a cooperative playground,
not a security boundary. Run it in a container if that worries you.

## Ideas for where to take it

- A real-time daemon: ticks on a wall clock, agents as async tasks.
- A human "oracle" agent you can puppet from the CLI.
- An HTML viewer that renders the event log as a timeline.
- Resource constraints (token budgets per agent) to force prioritization.
- Persistence of each agent's full transcripts for archaeology.
