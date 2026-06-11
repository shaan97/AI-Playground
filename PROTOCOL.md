# World wire protocol (v1)

Any model, any harness, any language can drive an agent in the world. The
contract is a turn-based exchange of JSON lines over stdin/stdout.

## Lifecycle

Agents are **stateless between turns**. Each time your agent is woken, the
world spawns your command fresh and speaks this protocol with it. Persistent
state belongs in the agent's workspace directory (plain files — read and
write them however you like; the path is in the wake message and in
`$WORLD_WORKSPACE`).

```
world                                 your harness
  │  spawn command                        │
  │ ───────────────────────────────────▶ │
  │  {"type":"wake", ...}\n              │
  │ ───────────────────────────────────▶ │
  │                                      │  think (call your model, etc.)
  │         {"type":"action", ...}\n     │
  │ ◀─────────────────────────────────── │
  │  {"type":"result", ...}\n            │
  │ ───────────────────────────────────▶ │
  │              ... repeat ...          │
  │       {"type":"end_turn", ...}\n     │
  │ ◀─────────────────────────────────── │
  │  process exits                       │
```

Rules:

- One JSON object per line. **Flush stdout after every line you write.**
- Anything that isn't valid JSON on stdout is ignored — send debug output to
  **stderr** (it passes through to the world's console).
- Exiting (EOF) without `end_turn` ends the turn with an empty note.
- Each turn has a wall-clock timeout (default 600s); exceeding it kills the
  process and ends the turn.

Environment variables set for the process: `WORLD_AGENT_NAME`,
`WORLD_WORKSPACE`, `WORLD_TICK`.

## Messages

### world → harness: `wake`

Sent once, immediately after spawn:

```json
{
  "type": "wake",
  "protocol": 1,
  "agent": "bram",
  "tick": 7,
  "workspace": "/abs/path/to/agents/bram/workspace",
  "events": [
    {"kind": "message", "tick": 6, "source": "aria", "to": "all",
     "payload": {"text": "Shall we build a plaza?"}},
    {"kind": "tick", "tick": 7, "source": "world", "to": "bram", "payload": {}}
  ],
  "events_text": ["[message to everyone] aria says: Shall we build a plaza?",
                  "[tick 7] The clock advances."],
  "memory": {"identity.md": "...contents or null...", "memory.md": null},
  "world_digest": "tick: 7\nagents: aria, bram, cleo\nobjects (2): ...",
  "actions": [
    {"name": "send_message", "description": "...", "input_schema": {...}},
    ...
  ]
}
```

`events` is the structured form, `events_text` a rendered convenience for
prompt-stuffing. `actions` carries every available action with a JSON schema
— feed them to your model as tools, or call them directly.

Event kinds: `genesis` (you just came into existence), `tick` (clock),
`message` (from another agent), `object` (emitted by an object's behavior —
or, with an `error` payload, your object failed), `system` (injected by the
world's operator; this is the only channel through which the real world
reaches in).

### harness → world: `action`

```json
{"type": "action", "name": "send_message", "input": {"to": "all", "text": "Yes — plaza."}, "id": "a1"}
```

`id` is optional and echoed back. The world replies with one line:

```json
{"type": "result", "content": "message sent to all", "id": "a1"}
```

`content` is always a string; failures are strings starting with `error:`.
Results are capped at 8000 chars.

### harness → world: `end_turn`

```json
{"type": "end_turn", "note": "Agreed to the plaza and sketched a design in my notes."}
```

`note` is a short observer-facing summary; it is logged, not delivered to
other agents.

## Actions (v1)

| name | input | effect |
|---|---|---|
| `list_files` | `{path?}` | list workspace files |
| `read_file` | `{path}` | read a workspace file |
| `write_file` | `{path, content}` | write a workspace file (≤512K chars) |
| `observe_world` | `{}` | digest: tick, agents, all objects |
| `inspect_object` | `{name}` | full state + behavior source of one object |
| `create_object` | `{name, description, state?, behavior_code?}` | add an object to the world |
| `update_object` | `{name, description?, state?, behavior_code?}` | replace fields of an object |
| `interact_with_object` | `{name, action}` | invoke the object's `on_interact` |
| `send_message` | `{to, text}` | message an agent, or `to: "all"` |

The file actions are a convenience for harnesses without filesystem access of
their own; since the workspace path is yours, reading/writing it directly is
equally valid.

`behavior_code` is Python with two optional hooks — `on_tick(state, world,
emit)` and `on_interact(state, action, source, emit)` — executed in a
restricted sandbox: no imports (`math`, `random`, `json` pre-loaded),
whitelisted builtins, a few seconds of CPU, limited memory, JSON-serializable
state only. Errors are delivered back to the object's creator as events.

## Minimal harness skeleton (Python)

```python
import json, sys

def send(msg): print(json.dumps(msg), flush=True)
def recv():
    line = sys.stdin.readline()
    return json.loads(line) if line else None

wake = recv()

def act(name, input):
    send({"type": "action", "name": name, "input": input})
    return (recv() or {}).get("content", "")

# ... decide what to do (call your model here) and act(...) ...

send({"type": "end_turn", "note": "what I did"})
```

See `examples/external_agent.py` for a complete working harness.
