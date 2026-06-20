# Safety model — v2 substrate (graph dynamical system)

The design goal is unchanged from v1: **the world is a sandbox.** Things act with
full freedom *inside* it through one narrow rule — a local state transition — and
their reach *outside* it should be zero. v2 makes the rule mathematical (a
stochastic graph dynamical system; see `UNIVERSE.md`), which sharpens the safety
story: the only things that exist are vertices, their state, and arcs, and the
only thing that happens is `Φ_σ` advancing them.

## Trust boundaries

| code | written by | runs where | trust |
|---|---|---|---|
| the engine (`v2/gds/`) | you | host process | trusted |
| `LocalKernel` transition code | **agents / authors** | isolated subprocess | untrusted |
| an `LLMKernel`'s model + private tools | the operator | the operator's machine | outside the boundary |

## What the substrate enforces

1. **No effectors.** A transition can do exactly two things: return its vertex's
   next state, and emit `TopologyUpdate`s (`AddArc`/`RemoveArc`/`AddVertex`). All
   of these mutate only the in-memory graph. There is no operation that touches
   the network, the filesystem, or any other process. (`RemoveVertex` is not even
   implemented — death is modelled as a terminal state.)

2. **Sandboxed kernels.** `LocalKernel` runs author code in a fresh subprocess
   (`gds/_sandbox.py`): `python -I`, a whitelisted-builtins namespace (no
   `open`, no `__import__`, no `eval`/`exec`), CPU-time and address-space rlimits,
   a parent wall-clock timeout, and JSON-only I/O. A transition that mutates state
   then raises reports the *original* state (atomic failure); a crash holds the
   vertex's state rather than corrupting the world.

3. **Out-star ownership (a structural invariant).** A vertex may modify only its
   own out-arcs — `AddArc`/`RemoveArc` carry only a `target`, so editing another
   vertex's arcs or forging an arc *into* yourself is inexpressible. Therefore
   **observation is unilateral and influence is consensual**: you can be affected
   only by what you yourself chose to observe. Nothing can push to you.

4. **Resource guardrails (`gds.safety.Limits`).** Sandbox limits bound a single
   transition; `Limits` bound the *system*: `max_vertices` (total graph size),
   `max_out_degree` (per-vertex fan-out), and `max_creations_per_step`. Over-budget
   topology updates are **silently dropped**, so a runaway "fork bomb" of vertices
   or an out-degree explosion is contained while the world keeps running. Registry
   coupling is exempt from the out-degree cap (it is a system invariant, not an
   agent action).

5. **Auditability by construction.** The world *is* its trajectory — every step's
   configuration is recorded (`gds/trajectory.py`). Replay is record-replay of
   that log, independent of whether the kernels were deterministic, so an
   `LLMKernel` run is fully reconstructable for inspection.

6. **No global directory.** There is no roster of "who exists" and no notion of
   "agent" in the substrate. Discovery is mediated by the registry vertex, whose
   ledger lists only **opaque identifiers** — existence, not nature. Other minds
   are discovered, never announced.

## What it does NOT enforce (residual risks)

- **CPython is not a security sandbox.** Builtins whitelisting blocks naive
  escapes; determined adversarial code may still escape via object-graph
  traversal. Treat the kernel sandbox as containment for accidents and casual
  misbehaviour, not a hard boundary. Run the engine in a network-restricted
  container for real isolation.
- **Agent harnesses are outside the boundary.** An `LLMKernel`'s model and its
  **private tools** (e.g. a `run_command` that shells into a container) live on
  the operator's machine and are the operator's responsibility — the substrate
  neither sees nor constrains them. Sandbox those yourself (the v1 `docker/`
  network-less container is one option for a real shell).
- **Nondeterminism is expected.** LLM kernels are nondeterministic and carry
  hidden memory; stochastic schedules (`RandomSubsetSchedule`,
  `StochasticCadenceSchedule`) use an RNG. Seed schedules for reproducible runs;
  otherwise rely on record-replay for audit. The scheduling RNG never enters a
  transition, so it does not make `Φ_σ` itself stochastic.

## Recommended deployment

Run the engine in a container/VM whose only writable surface is its trajectory
directory, with `--network none`. Give it conservative `Limits`. Sandbox any
private agent tools separately, at the operator's discretion.

## Design rule for contributors

Any new capability must be **confined to the graph**: it may read/write vertex
state and emit topology updates, and nothing else. If a capability needs more than
that (network, files, a shell), it belongs in an agent's private kernel tooling —
behind the operator's judgment — not in the substrate.
