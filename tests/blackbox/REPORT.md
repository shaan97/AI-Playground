# Black-box test suite report

Suite written exclusively from `docs/INTERFACES.md` (primary spec),
`PROTOCOL.md`, `README.md`, and `SAFETY.md`. No implementation source under
`world/`, the CLI entry points, `examples/`, or `tests/test_world.py` was
read. The public modules are imported and the CLIs invoked as subprocesses —
interface use only.

Final result: **107 passed, 1 failed** (the failure is a deliberate
spec-discrepancy keeper, see below). Full run: `pytest tests/blackbox -q`,
~20 s.

## Coverage map

### Unit (in-process, single module, `test_unit_*.py`)

- **`test_unit_events.py`** — `Event` field set and documented defaults
  (`to="all"`, `payload={}`, `seq=0`); `to_dict()` carries exactly the six
  fields; one-line `render()`; the five stable render properties (genesis
  `[genesis]`, `[tick N]`, message source+text, object `error` payload
  mentioned, system payload text); the five module kind constants.
- **`test_unit_protocol.py`** — `ACTIONS` is exactly the 10 documented
  actions; `ActionSpec` shape and `to_dict()`; `anthropic_tools()` matches
  ACTIONS one-to-one in name/order/schema; `build_wake` full key contract
  (type/protocol/agent/tick, absolute workspace path, events as dicts with
  parallel `events_text`, `memory` with both keys and None-when-absent vs
  contents-when-present, `world_digest`, default subscriptions, action dicts).
- **`test_unit_sandbox.py`** — mutation-in-place vs returned-dict state
  replacement; `missing` flag; `emitted` shape incl. `to` default;
  `on_interact` result/action/source plumbing; world snapshot visibility;
  hook exception → `ok=False` + error (caller survives); syntax errors;
  blocked `import`/`open`/`eval`/`exec`/`getattr`; pre-loaded
  `math`/`random`/`json`; whitelisted builtins + exception handling + class
  definitions; infinite loop killed (`cpu_seconds=1`, `wall_timeout=4`);
  `emit` rejects non-dict payloads; non-JSON-serializable state coerced via
  `str`. Inbox-cap test skipped per instructions; sandbox calls kept to a
  few dozen to stay within the time budget.
- **`test_unit_kernel.py`** — fresh-world attributes (roster order, default
  subscriptions, tick/seq = 0); root auto-creation; `publish` seq assignment
  starting at 1 + log append; broadcast source-exclusion; subscription
  filtering; direct-delivery-always; unknown-`to` logged but undelivered (no
  error); `set_subscriptions` unknown-kind error leaves state unchanged, `[]`
  valid; `ensure_genesis` one direct genesis per agent at tick 0, idempotent;
  `advance_tick` (+1 tick, ONE broadcast tick event, agents not woken);
  `step` wakes only non-empty inboxes and consumes them wholesale; `run(0)`;
  `ack` cursor semantics; `record_turn` log record; `inject` broadcast and
  direct; `create_object` success/disk layout/manifest keys, name-regex
  rejections, duplicate rejection; `update_object` full-field replacement,
  any-agent update, unknown error; `inspect_object` contents and unknown
  error; `interact_with_object` unknown error, hookless descriptive
  non-error, JSON-encoded return, `"ok"` on None, emitted events published;
  `send_message` broadcast/direct/unknown; `digest` contents; `snapshot`
  shape + deep-copy isolation.
- **`test_unit_agent.py`** — unknown action `error:`; dispatch never raises
  on malformed inputs; 8000-char result truncation with marker; 512,000-char
  write cap (and the exact boundary being allowed); workspace jail for
  relative-escape and absolute paths on read and write; parent-dir
  auto-creation; missing-file read error; `list_files` `(empty)` and
  newline-separated relative paths; world actions delegating with the
  dispatching agent as actor (object creator, message source, subscriptions)
  and `error:` passthrough.

### Integration (multi-component, in-process, `test_integration_*.py`)

- **`test_integration_lockstep.py`** — `World.run` with `MockConnector`s:
  genesis writes `identity.md`/`memory.md`, later wakes append `Turn` lines,
  first-wake greeting broadcast, builder's `beacon` (creator, even-tick
  `pulse` events in the log, non-builder interaction reflected in
  `touches`), tick/seq/meta.json agreement after a run.
- **`test_integration_persistence.py`** — reload restores tick/seq/roster
  (persisted roster beats the constructor argument)/subscriptions/objects;
  genesis idempotence across restarts with undelivered inboxes surviving;
  `inject` into a never-run world surviving reload; `meta.json` documented
  key set; `on_tick` failure (raise and timeout) routed as a direct `object`
  event with an `error` payload to the **creator** only, object state
  unchanged; `on_interact` failure reported descriptively (non-`error:`) to
  the caller; healthy `on_tick` state persistence (memory + `state.json`)
  and emitted-event broadcast.
- **`test_integration_connectors.py`** — raw `ProcessConnector` contract via
  inline `python -c` harnesses: full wake/action/result/end_turn round trip
  with non-JSON stdout ignored; `WORLD_AGENT_NAME`/`WORLD_WORKSPACE`/
  `WORLD_TICK` env vars; EOF-without-`end_turn` yields a note;
  `turn_timeout` kill yields a note mentioning the timeout; string-command
  form accepted. Then `examples/external_agent.py` driven inside a 2-agent
  lockstep world: identity/memory files, `guestbook` creation, and
  signatures after message wakes.
- **`test_integration_server.py`** — `load_or_create_tokens`
  (shape, disk file, preserve-and-extend); `WorldServer(port=0,
  tick_interval=0)` + real HTTP on 127.0.0.1: 403 for missing/wrong tokens
  with JSON body, agent-token scoping (other agents' endpoints, `/admin/*`),
  admin-token scoping (agent endpoints), `GET /world` with any valid token;
  404 for unknown agent and unknown route; long-poll 200 + `cursor` =
  max seq vs bodyless 204; at-least-once redelivery of unacked wakes; ack
  consumption via `POST /turns`; actions endpoint 200 `{"content"}` incl.
  `error:` passthrough as HTTP 200; malformed JSON body 400; per-agent rate
  limit 429; `POST /admin/step` `{"tick"}` and `/admin/inject` `{"ok":
  true}` with delivery verified; `set_subscriptions` over HTTP changing
  tick delivery (204 after unsubscribe) while direct injects still wake the
  agent; `WorldClient.run(max_wakes=1)` driving a `MockConnector`
  (server-side workspace files, ack consumption, return count),
  `client.dispatch` proxying, and non-200 → `error:` string mapping.

### End-to-end (CLI subprocesses, `test_e2e_*.py`)

- **`test_e2e_run_world.py`** — `run_world.py --mock` fresh world (exit 0,
  meta tick/roster/genesis, workspace files, builder's beacon on disk);
  resume in the same `--data-dir` (tick 3 → 5, roster preserved);
  `--ticks 0 --inject` (time frozen, system event in the log and in the
  persisted inboxes, perceived on the next run); `--agent-cmd` with the
  reference external harness (guestbook, identity/memory); `--config` with
  a mixed mock-builder + process world (both harnesses' artifacts present).
- **`test_e2e_server_client.py`** — `run_server.py` on a pre-picked free
  port with `--tick-interval 0`, readiness probed via `tokens.json` +
  `GET /world`; tokens read from `<data-dir>/tokens.json`; `run_client.py
  --mock --max-wakes 1` consuming the genesis wake (exit 0, server-side
  workspace files); admin inject + step over HTTP; a second one-wake client
  run appending to memory; live `GET /world` state; SIGTERM shutdown with
  `meta.json` persisted.

## Partitioning rationale

- **Unit** = one documented surface at a time, in-process, no cross-module
  assertions beyond what the contract itself names (e.g. `create_object`'s
  disk layout is part of its contract).
- **Integration** = two or more components interacting in-process (kernel ×
  connectors, kernel × sandbox failure routing, server × HTTP × client),
  still hermetic per test (tmp dirs, ephemeral ports, `tick_interval=0`).
- **E2E** = the documented CLI surfaces as real subprocesses with
  `sys.executable`, temp `--data-dir`s, free ports, and bounded timeouts —
  asserting only on exit codes, on-disk artifacts, and the HTTP API.

## Spec ambiguities noticed (tests use the reading shown; not failures)

1. **`interact_with_object` on a None-returning hook.** "Hook return value
   comes back JSON-encoded (`"ok"` if the hook returned None)" — the
   parenthetical can be read as `json.dumps("ok")` (i.e. the 4-char text
   `"ok"`) or as the literal result string `ok`. The implementation returns
   bare `ok`; I judged the literal-string reading the more natural prose
   interpretation and assert `r == "ok"`
   (`test_unit_kernel.py::test_interact_none_return_is_ok`). Worth a
   clarifying sentence in the spec.
2. **403 vs 404 precedence.** For `/agents/<unknown>/wake` no token can be
   "the right token", so auth-scoping ("an agent's token is valid only for
   that agent's endpoints" → 403) and "unknown agent name in the path →
   404" pull in opposite directions. The implementation answers 404 (the
   reading I asserted, sending a valid other-agent token), but the spec
   doesn't state check order.
3. **`on_interact` failure text.** "Reported in the interaction result
   string" doesn't say what the string contains; I assert it is non-empty,
   not `error:`-prefixed, and mentions the failure loosely (exception text
   or the words error/fail). The implementation includes the exception
   text.
4. **EOF-without-`end_turn` note.** "Yields a note saying so" specifies no
   wording; I only assert a non-empty string note. (The timeout case *does*
   promise the note mentions the timeout, which I assert.)
5. **Persistence granularity.** Only `inject` is documented to persist
   "immediately"; whether e.g. a bare `publish`/`send_message` on an
   otherwise idle world hits disk before the next run/save is unspecified.
   I tested inbox survival only through documented-durable paths
   (`ensure_genesis`, `inject`, `run`).
6. **`HookResult.error` type.** Spec says `error: str | None`; in the
   failure cases I exercised the field is truthy and stringifiable, and my
   one `isinstance(res.error, str)` assertion passes on the path it tests;
   other paths may carry exception objects — the spec could pin this down.

## SPEC DISCREPANCIES (tests kept failing on purpose)

1. **`test_unit_sandbox.py::test_hook_exception_reports_error_and_keeps_state`**

   Spec (§world.sandbox, `HookResult`): "`state: dict` (resulting state;
   **original state on failure**)".

   Observed: for

   ```python
   def on_tick(state, world, emit):
       state['x'] = 1
       raise ValueError('boom')
   ```

   `run_hook(code, "on_tick", {"orig": True}, world={"tick": 1})` returns
   `ok=False` and a non-empty `error`, but
   `state == {'orig': True, 'x': 1}` — the **partially mutated** state, not
   the original `{'orig': True}`.

   Why the test is right: the spec sentence is unambiguous — on failure the
   result's `state` is the *original* state. The kernel evidently honors the
   spirit at its own level (my §world.objects test confirms the persisted
   object state is left unchanged after a failed `on_tick`), which is only
   safe if callers can rely on `HookResult.state` being the pre-call state
   on failure — or if every caller independently discards it, in which case
   the documented field contract is still violated for any direct user of
   `world.sandbox.run_hook`. The test asserts the documented contract and is
   kept failing; the fix belongs in the sandbox (return the untouched input
   state when `ok` is False) or in the spec.

   **Resolution (post-review):** adjudicated as an implementation bug — the
   sandbox now snapshots the input state and returns it untouched on
   failure. The test passes unmodified. Spec ambiguities 1, 2, and 6 above
   were also pinned down in docs/INTERFACES.md to match the asserted
   readings.

## Hermeticity notes

- Every test uses pytest `tmp_path`; nothing touches `world_data/` or the
  repo tree.
- In-process servers bind `port=0`; subprocess servers use a
  bind-then-close free port; all traffic is 127.0.0.1.
- No API keys; `ClaudeConnector` is never constructed.
- All servers/subprocesses are shut down in `finally`/context managers;
  subprocess calls carry bounded timeouts.
- Long-polls use `wait` ≤ 5 s; server tests use `tick_interval=0` +
  `/admin/step`; clients use `--max-wakes`. Full suite ≈ 20 s.
