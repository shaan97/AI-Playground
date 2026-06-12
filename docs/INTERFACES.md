# Public interface specification

Behavioral contracts for every public surface of this project. Written to be
testable black-box: everything below is a promise about observable behavior,
not about implementation. (Wire formats are in PROTOCOL.md; this document
covers the Python API and CLI surfaces.)

Result-string convention: agent-facing operations return human-readable
strings; failures are strings starting with `"error:"`. Kernel-level
failures (unknown object, bad name, jail violation) use the `error:` prefix.
A *behavior hook's own* failure or absence is reported descriptively instead
(see §WorldObject) — it is information from the world, not an API error.

---

## world.events

`Event` — dataclass with fields:

| field | type | meaning |
|---|---|---|
| `kind` | str | one of `"genesis"`, `"tick"`, `"message"`, `"object"`, `"system"` |
| `tick` | int | tick at which the event occurred |
| `source` | str | `"world"`, an agent name, or an object name |
| `to` | str | `"all"` (broadcast) or an agent name (direct) — default `"all"` |
| `payload` | dict | free-form JSON-serializable payload — default `{}` |
| `seq` | int | global sequence number; `0` until assigned by `World.publish` |

Methods: `to_dict() -> dict` (all six fields); `render() -> str` — a one-line
human-readable form. Stable render properties: a genesis render contains
`[genesis]`; a tick render contains `[tick N]`; a message render contains the
source name and the payload text; an object event whose payload has an
`"error"` key renders mentioning the error; a system render contains the
payload text.

Module constants: `GENESIS`, `TICK`, `MESSAGE`, `OBJECT`, `SYSTEM` — the kind
strings above.

---

## world.protocol

- `ACTIONS: list[ActionSpec]` — `ActionSpec` has `name`, `description`,
  `input_schema` (JSON Schema dict) and `to_dict()`. The action set is the
  9 actions in PROTOCOL.md (`list_files`, `read_file`, `write_file`,
  `observe_world`, `inspect_object`, `create_object`, `update_object`,
  `interact_with_object`, `send_message`) plus `set_subscriptions`.
- `anthropic_tools() -> list[dict]` — each entry has `name`, `description`,
  `input_schema`, matching ACTIONS one-to-one.
- `build_wake(agent, events, world) -> dict` — the wake payload. Keys:
  `type` (`"wake"`), `protocol` (int, `1`), `agent`, `tick`, `workspace`
  (absolute path string), `events` (list of event dicts), `events_text`
  (list of rendered strings, same length/order), `memory` (dict with keys
  `"identity.md"` and `"memory.md"`, value = file content string or None if
  absent), `world_digest` (str), `subscriptions` (list of kind strings),
  `actions` (the ActionSpec dicts).

---

## world.kernel

`World(root, connector_factory, agent_names, quiet=False)`

- `root`: data directory (`pathlib.Path` or str); created if needed.
- `connector_factory(index: int, name: str) -> Connector | None` — called
  once per agent; may return None when no local brain is needed (server mode).
- `agent_names`: roster for a NEW world. For an existing world (a `meta.json`
  is present in root), the persisted roster wins and the argument is ignored.
- `quiet=True` suppresses console narration.

Attributes: `tick: int`, `seq: int`, `agents: dict[name, AgentRuntime]`
(insertion order = roster order), `objects: dict[name, WorldObject]`,
`inboxes: dict[name, list[Event]]`, `subscriptions: dict[name, list[str]]`.

**Event routing (`publish(event)`):**
1. Assigns the next global sequence number (`seq` starts at 0; first
   published event gets `seq == 1`) and appends the event to the log.
2. `to == "all"`: delivered to every agent EXCEPT the source agent, and only
   if `event.kind` is in that agent's subscriptions.
3. `to == <agent name>`: always delivered, regardless of subscriptions.
4. `to` naming no known agent: logged but delivered to no one (no error).

Default subscriptions: all five kinds. Per-agent inboxes are capped at 1000
events (oldest dropped beyond that).

**Time and turns:**
- `ensure_genesis()` — first call on a fresh world publishes one direct
  `genesis` event per agent (tick 0, source `"world"`); idempotent across
  calls and process restarts.
- `advance_tick()` — increments `tick`, runs every object's `on_tick`
  (publishing whatever they emit), then publishes ONE broadcast `tick` event.
  Does not wake agents.
- `step()` — `advance_tick()`, then each agent with a non-empty inbox takes
  one turn (its inbox is consumed wholesale). Agents with empty inboxes are
  skipped.
- `run(ticks)` — `ensure_genesis()` + `ticks` × `step()`. `run(0)` is valid.
- `ack(name, cursor)` — removes the agent's inbox events with
  `seq <= cursor` (server-mode consumption).
- `record_turn(name, note)` — appends a turn record to the log.

**Operator channel:** `inject(text, to="all")` publishes a `system` event and
persists immediately (an injection into a world that is not running survives
to the next run).

**Agent-facing operations** (also reachable via `AgentRuntime.dispatch`):

- `set_subscriptions(name, kinds) -> str` — replaces the agent's broadcast
  filter. Unknown kind → `error:` string, subscriptions unchanged. Valid
  call returns a non-error string and persists across reloads. `[]` is valid
  (silence all broadcasts).
- `create_object(creator, name, description, state=None, behavior_code=None)
  -> str` — object names must match `[a-z0-9][a-z0-9_-]*`; invalid name or
  duplicate → `error:` string. Success creates `objects/<name>/` on disk.
- `update_object(actor, name, description=None, state=None,
  behavior_code=None) -> str` — provided fields fully replace old values;
  unknown object → `error:`. Any agent may update any object.
- `inspect_object(name) -> str` — includes the object's name, creator,
  description, full state, and behavior source (if any); unknown → `error:`.
- `interact_with_object(actor, name, action) -> str` — unknown object →
  `error:`. Object without an `on_interact` hook → a descriptive string
  saying nothing happened (NOT `error:`-prefixed). Hook return value comes
  back JSON-encoded (`"ok"` if the hook returned None). Events emitted by
  the hook are published.
- `send_message(source, to, text) -> str` — `to` must be `"all"` or a known
  agent; otherwise `error:`.
- `digest() -> str` — human-readable; contains the current tick, every agent
  name, and every object's name and description.
- `snapshot() -> dict` — `{"tick", "agents": [names], "objects": {name:
  {"description", "state"}}}`; state is a deep copy (mutating it does not
  affect the world).

**Persistence.** Everything lives under `root`:

- `meta.json` — keys `tick`, `seq`, `agents`, `genesis_done`,
  `subscriptions`, `inboxes` (undelivered events as dicts).
- `agents/<name>/workspace/` — agent files.
- `objects/<name>/` — `manifest.json` (`name`, `description`, `creator`,
  `created_tick`), `state.json`, optional `behavior.py`.
- `log/events.jsonl` — append-only JSON lines: every published event dict,
  plus records with `kind` in `turn`, `object_created`, `object_updated`,
  `interaction`, `subscriptions`, `inbox_overflow`.

Constructing a `World` on an existing root resumes it exactly: tick, seq,
roster, subscriptions, objects, and undelivered inbox events all survive.

---

## world.agent

`AgentRuntime(name, workspace, connector, world)` — normally constructed by
`World`; tests reach it via `world.agents[name]`.

`dispatch(action_name: str, action_input: dict) -> str` — executes one
protocol action as this agent. Contracts:

- Unknown action name → `error:` string. Internal exceptions are caught and
  returned as `error:` strings (dispatch never raises).
- Results longer than 8000 chars are truncated (with a truncation marker).
- `write_file` content over 512,000 chars → `error:`.
- File paths resolve inside the agent's workspace only; any path escaping it
  (e.g. `../`) → `error:` string. Parent directories are auto-created on
  write. `read_file` of a missing file → `error:`. `list_files` returns
  newline-separated relative paths, or `(empty)`.
- World actions delegate to the corresponding `World` methods above with
  this agent as actor.

---

## world.objects

`WorldObject` — loaded from an object directory. Public attributes: `name`,
`description`, `creator`, `created_tick`, `state` (dict), `behavior_code`
(str or None).

Behavior hooks (written by agents, executed sandboxed — see §sandbox):

- `on_tick(state, world, emit)` — runs each tick via `World.advance_tick`.
  May mutate `state` in place or return a dict that replaces it; the new
  state is persisted. `world` is the kernel `snapshot()`. `emit(payload,
  to="all")` publishes an `object`-kind event with this object as source.
- `on_interact(state, action, source, emit)` — runs on
  `interact_with_object`; return value is shown to the caller.

Failure routing: if a hook raises, times out, or fails to load during a
tick, the world publishes an `object` event addressed DIRECTLY to the
object's **creator** with an `"error"` key in the payload; the object's
state is left unchanged. An `on_interact` failure is reported in the
interaction result string to the caller instead.

---

## world.sandbox

`run_hook(code, hook, state, world=None, action=None, source=None,
cpu_seconds=5, memory_bytes=512*1024*1024, wall_timeout=10.0) -> HookResult`

`HookResult` fields: `ok: bool`, `missing: bool` (hook not defined in code),
`state: dict` (resulting state; original state on failure), `emitted:
list[dict]` (each `{"payload": dict, "to": str}`), `result` (on_interact
return value), `error: str | None`.

Sandbox guarantees (each a testable property):

- Runs in a separate process; the calling process always survives.
- `import` statements fail (no `__import__`); `open` is unavailable;
  `eval`/`exec`/`getattr` are unavailable. `math`, `random`, and `json` are
  pre-loaded globals. Common data/maths builtins (`len`, `range`, `sorted`,
  `sum`, standard exception types, class definition) work.
- An infinite loop or CPU burn is killed (CPU rlimit and/or `wall_timeout`)
  and reported as `ok=False` with a non-empty `error`.
- `emit` rejects non-dict payloads (the hook errors).
- State and emitted payloads must be JSON-serializable (non-serializable
  values are coerced via `str`).

---

## world.connectors

`Connector` protocol: `take_turn(wake: dict, dispatch) -> str` where
`dispatch(action_name, input_dict) -> str`. The return value is the agent's
end-of-turn note.

- `MockConnector(builder=False)` — deterministic scripted agent, stateless
  between turns (derives its phase from the wake's `memory`):
  - First wake (no `identity.md` yet): writes `identity.md` and `memory.md`,
    broadcasts a greeting. If `builder=True`, also creates an object named
    `beacon` whose `on_tick` broadcasts a `{"pulse": N}` payload on even
    ticks and whose `on_interact` counts touches in state key `"touches"`.
  - Later wakes: appends a line to `memory.md` (`Turn N: ...`); a
    non-builder that perceives a pulse event interacts with the beacon.
- `ProcessConnector(command, turn_timeout=600.0)` — spawns `command` (string
  or argv list) fresh per wake and speaks PROTOCOL.md over stdio. Sets env
  vars `WORLD_AGENT_NAME`, `WORLD_WORKSPACE`, `WORLD_TICK`. EOF without
  `end_turn` yields a note saying so; exceeding `turn_timeout` kills the
  process and yields a note mentioning the timeout. Non-JSON stdout lines
  are ignored; stderr passes through.
- `ClaudeConnector(...)` — requires Anthropic credentials; OUT OF SCOPE for
  offline tests.

---

## world.server

`load_or_create_tokens(root, agent_names) -> dict` — returns
`{"admin": str, "agents": {name: str}}`, creating/extending
`<root>/tokens.json` (new tokens are generated for unknown agents; existing
ones are preserved).

`WorldServer(world, tokens, host="127.0.0.1", port=8470,
tick_interval=600.0, rate_limit=120)`

- `port=0` binds an ephemeral port; the bound address is `server.host` /
  `server.port`.
- `tick_interval` seconds between automatic heartbeats; `0` disables the
  ticker (time then advances only via `POST /admin/step`).
- `rate_limit`: max actions per agent per rolling minute.
- `start()` — non-blocking; runs genesis if needed, serves in background
  threads. `serve_forever()` — blocking variant. `shutdown()` — stops and
  persists. `server.lock` — acquire it before inspecting `world` from a
  test while the server is live.

HTTP API: see PROTOCOL.md §Remote mode for routes and payloads. Additional
testable contracts:

- Wrong/missing bearer token → 403 with a JSON error body. An agent's token
  is valid only for that agent's endpoints; the admin token only for
  `/admin/*`; `GET /world` accepts any valid token.
- Unknown agent name in the path → 404. Unknown route → 404.
- `GET /agents/<n>/wake?wait=S` long-polls up to S seconds (capped at 120):
  200 + wake payload (with extra `cursor` int field = max seq included) as
  soon as the inbox is non-empty, else 204 with no body.
- Events remain queued until acked via `POST /agents/<n>/turns` with
  `{"note", "cursor"}` → at-least-once delivery: an unacked wake's events
  appear again in the next wake.
- `POST /agents/<n>/actions` with `{"name", "input"}` → 200
  `{"content": str}` (the dispatch result, including `error:` strings —
  action failures are NOT HTTP errors). Exceeding the rate limit → 429.
- `POST /admin/step` → 200 `{"tick": int}`; `POST /admin/inject` with
  `{"text", "to"?}` → 200 `{"ok": true}`.
- Malformed JSON body → 400.

## world.client

`WorldClient(server_url, agent, token, connector, wait=60.0, quiet=False)`

- `dispatch(action_name, input) -> str` — proxies one action over HTTP;
  non-200 responses come back as `error:` strings.
- `run(max_wakes=None) -> int` — long-poll loop: on each wake payload,
  drives `connector.take_turn`, then posts the turn note and cursor ack.
  Returns after `max_wakes` wakes (None = run forever). 204s don't count.

---

## CLI surfaces

All exit 0 on success. Worlds persist in `--data-dir` (default
`world_data/`) and resume on re-invocation.

- `python run_world.py` — lockstep mode. Key flags: `--ticks N` (default 5;
  0 valid), `--agents N` / `--names a,b,c`, `--mock` (scripted agents,
  offline; agent index 0 is the builder), `--agent-cmd CMD` (every agent
  driven by an external PROTOCOL.md harness), `--config FILE` (JSON list of
  per-agent specs: `{"name", "harness": "claude"|"process"|"mock",
  "command"?, "model"?, "effort"?, "builder"?}`), `--data-dir PATH`,
  `--inject TEXT` + `--inject-to NAME|all` (queue a system event before
  running). Claude harness without credentials → non-zero exit with a clear
  message.
- `python run_server.py` — serve a world. Flags: `--names/--agents`,
  `--host` (default 127.0.0.1), `--port` (default 8470), `--tick-interval S`
  (default 600), `--rate-limit N`, `--data-dir`. Prints per-agent tokens and
  writes `tokens.json` into the data dir. Runs until SIGINT/SIGTERM.
- `python run_client.py` — one agent as a client. Flags: `--server URL`,
  `--agent NAME`, `--token T` (or env `WORLD_TOKEN`), `--mock` /
  `--agent-cmd CMD` / (default: Claude), `--wait S`, `--max-wakes N`.
- `examples/external_agent.py` — reference PROTOCOL.md harness (stdlib
  only). At genesis it writes `identity.md`, broadcasts a greeting, and
  creates an object named `guestbook` (with an `on_interact` that appends
  entries). On a wake containing `message` events it signs the guestbook.
  On quiet wakes it just ends its turn. Always appends a line to
  `memory.md` in its workspace.
