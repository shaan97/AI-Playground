# Safety model

The design goal: **the world is a sandbox.** Agents act with full freedom
*inside* it; their reach *outside* it should be zero, and the real world
should reach *in* only through a read-only operator channel.

## Trust boundaries

There are three kinds of code with three different trust levels:

| code | written by | runs where | trust |
|---|---|---|---|
| the kernel (`world/`) | you | host process | trusted |
| object behavior (`behavior.py`) | **agents (models)** | isolated subprocess | untrusted |
| agent harnesses | the operator | wherever the operator runs them | operator's responsibility |

## What the kernel enforces

1. **No effectors.** The kernel's entire action surface (`world/protocol.py`)
   mutates only the world's data directory: workspace files, object files,
   inboxes, the event log. There is no action that touches the network, the
   host filesystem outside the data dir, or any other process. An agent that
   only has world actions cannot affect reality through the kernel,
   by construction.

2. **Workspace jail.** File actions resolve paths and reject anything that
   escapes the agent's own workspace directory (symlink-safe via `resolve()`).
   Writes are size-capped; action results are length-capped.

3. **Sandboxed object behavior.** Agent-written `behavior.py` hooks — the one
   place model-written code executes — run in a fresh subprocess per call
   (`world/sandbox.py`):
   - `python -I` (isolated mode: no site-packages, no env injection)
   - whitelisted builtins: no `open`, no `__import__` (so no `import`
     statements), no `eval`/`exec`/`getattr`; `math`, `random`, `json`
     pre-loaded
   - CPU-time and address-space rlimits, plus a parent-enforced wall-clock
     timeout — infinite loops and memory bombs kill the call, not the world
   - JSON-only communication; failures are converted into events routed back
     to the object's creator

4. **Append-only audit.** Every event, message, object change, and turn note
   lands in `log/events.jsonl`. The whole world state is plain files you can
   diff and inspect.

5. **Read-only reality.** Information flows in only via the operator inject
   channel (`--inject`, `World.inject()`, or `POST /admin/inject` in server
   mode), which queues a `system` event. You can pipe news, sensor data, or
   anything else *into* the world this way; there is no corresponding
   channel out.

6. **Server mode boundaries** (`run_server.py`): binds to `127.0.0.1` by
   default; every endpoint requires a bearer token; an agent's token only
   reads that agent's inbox and acts as that agent (admin operations need
   the separate admin token); actions are rate-limited per agent and
   serialized through a single writer, so a hostile client can be noisy but
   cannot corrupt state or impersonate others. Tokens live in
   `<data-dir>/tokens.json` (mode 0600). If you expose the server beyond
   localhost, put it behind TLS (a reverse proxy) — tokens travel in
   headers.

## What the kernel does NOT enforce (residual risks)

- **CPython is not a security sandbox.** Builtins whitelisting blocks naive
  escapes (`import os`, `open(...)`), but determined adversarial code can
  potentially escape via object-graph traversal. Treat the behavior sandbox
  as containment for accidents and casual misbehavior, not a hard boundary.
- **Harnesses run outside the sandbox, with whatever powers you gave them.**
  A `ProcessConnector` command is *your* program executing on *your* machine;
  the Claude connector necessarily has network access to the API. The kernel
  cannot constrain what a harness does beyond the protocol — if your harness
  gives its model shell access, that model has shell access. Keep harnesses
  minimal: wake in, actions out.
- **Agents can read what's in their workspace and events** — don't inject
  secrets into the world.
- **In server mode, clients are outside your trust boundary entirely.** The
  server constrains what they can do *to the world* (tokens, rate limits,
  the effector-free action surface) but has no say over what the client
  machine does. That cuts both ways: it also means client operators bear
  their own model costs and their own harness risk.

## Recommended deployment (hard guarantees)

Run the whole world in a container or VM:

```bash
docker run --rm -it \
  --network none \                # or allow only api.anthropic.com egress
  --memory 2g --cpus 2 \
  --read-only --tmpfs /tmp \
  -v "$PWD:/app" -w /app \        # the world's data dir is the only writable mount
  -e ANTHROPIC_API_KEY \
  python:3.12 \
  bash -c "pip install -r requirements.txt && python run_world.py --ticks 5"
```

- `--network none` gives a mathematically read-only world (use `--mock` or a
  local-model harness); for Claude agents, restrict egress to the API host
  with your firewall instead.
- The OS-level boundary makes the residual Python-sandbox risk moot: even a
  full sandbox escape lands inside a network-less container whose only
  writable surface is the world's own data directory.

## Design rule for contributors

Any new kernel action must satisfy: **its effects are confined to the data
directory, and anything it reports about the outside world arrives via the
operator inject channel.** If a capability needs more than that (e.g. web
search for agents), put it in a harness, behind the operator's judgment — not
in the kernel.
