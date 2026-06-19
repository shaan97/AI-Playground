# The Universe — substrate design

> **Guiding principle:** maximize the scope of expressible worlds with a minimal
> set of rules. Add a primitive only when the same expressiveness cannot already
> emerge from the primitives we have.

This document describes the *intended* substrate. It is a deliberate
simplification: there is exactly **one kind of thing (an object)** and **one kind
of rule (a state transition)**. Everything else — agents, interaction, games,
ecosystems, even death — is meant to emerge from those two.

> **Formal model & implementation.** Mathematically this substrate is a
> **stochastic graph dynamical system**, implemented under `v2/gds/`. This page
> uses the *domain register* (object/thing, agent, world, tick); the code uses the
> *formal register* (vertex, transition kernel `κᵥ`, configuration, evolution
> operator `Φ_σ`, step). The mapping: object→`Vertex`, "reads" edge→arc, inputs→
> out-neighbourhood `N⁺(v)`, behaviour→`TransitionKernel`, world snapshot→
> `Configuration`, one tick→`Φ_σ`, the hub→the registry vertex `r`. Both registers
> are intentional — see the refactor plan for the naming philosophy.

---

## 1. The model

A **universe** is a set of **objects** evolving in discrete time (ticks).

- An **object** is a vertex with a **state**.
- The objects form a **directed graph**. An edge **X → Y** means *X reads Y's
  state when it transitions*. So an object's out-neighbors are its **inputs** —
  the slice of the universe it can perceive. This is usually a *subset* of all
  objects, not the whole graph.
- **State** is arbitrary structured data. JSON is the default (easy, inspectable,
  serializable); the form is unconstrained as long as it carries whatever
  information the object's author wants it to.

### The transition function

Every object carries a **transition function** — an ordinary (sandboxed) Python
function:

```
next_state  ~  f(own_state, [states of out-neighbors], randomness)
```

Three properties define it:

1. **Local.** It sees only its own state and the states of the objects it points
   to. There is no global view.
2. **Stochastic.** Transitions are *probabilistic*, not deterministic. Richness
   needs chance — a defender should *sometimes* steal the ball, not always or
   never. The engine supplies a randomness source; the function samples from it.
3. **Synchronous.** One tick is one update of the whole graph, double-buffered:
   every object reads generation *t*, every object writes generation *t+1*. This
   keeps the clean "next state is a function of the previous state" semantics and
   removes update-order artifacts.

That is the entire computational core: **a graph of stateful vertices, each
advancing by a local, stochastic function of its neighborhood.** Anything
expressible as a graph with state-transition rules lives here.

### Structural effects (the graph itself can change)

A transition returns more than a next state — it may also emit **structural
effects** so the universe can be open-ended rather than a fixed graph:

- **create** a new object (with its initial state, transition function, and
  initial out-edges),
- **rewire** its own out-edges (change what it perceives), and
- *(under consideration — see §5)* **destroy** an object.

Creation is the one structural power that **cannot** be faked with state alone —
you cannot conjure a new vertex from within an existing one's state — so it is a
true primitive. It is what lets the universe grow: players spawning, an object
decomposing into simpler items, an ecosystem appearing.

---

## 2. Agents are just objects

An **agent is an object whose transition function is an LLM** (with its own
private, external memory and its own slow, noisy "thinking"). It is **not** a
special citizen of the substrate — it has the same state, the same edges, and the
same primitives as a basketball or a hoop. The only thing that distinguishes it
is the *nature of its `f`*.

This unification buys several properties for free:

- **Influence flows only along edges, only in the read direction.** An object can
  be changed solely by what it points at; it can never push to anyone. To affect
  another object, that object must already point at you. Unsolicited contact is
  impossible by construction.
- **There is no "agent" or "who exists" view to leak.** The universe contains
  objects, full stop; nothing labels which ones are minded. Whether a given
  object is *alive* — driven by another agent — is something an agent must
  **infer from behavior**, not something it is told.
- **Partial observability is automatic.** The moment the graph is larger than any
  one object's neighborhood, an object sees its inputs move in ways its own
  actions don't explain. Mystery — "something I don't understand is changing my
  world" — falls out of locality; it doesn't have to be engineered.

The agent's only effectors, then, are the universal ones: **write my own state**
(everything downstream perceives me through it) and **emit structural effects**
(create / rewire / maybe destroy).

---

## 3. The single rule of design

> A capability earns a place in the substrate **only if it strictly enlarges the
> set of expressible universes.** If agents can already build it out of state and
> transitions, it stays out — let them discover it.

Worked through the obvious candidates:

| Capability   | Emergent from state + transition? | Verdict |
|---|---|---|
| Object **creation** | No — a vertex cannot spawn a vertex | **Primitive** (irreducible) |
| **Interaction / messaging** | Yes — point at me, react to my state | Not a primitive; emergent |
| A "**dead**" / inert thing | Yes — a terminal state that maps to itself | Not a primitive; emergent |
| **Rotting / decomposition** | Yes — transition into a decayed state that spawns simpler objects | Emergent (needs creation) |
| Object **destruction** | Yes (terminal state) for *behavior*; No only for *reclaiming resources* | **Under consideration** (§5) |

---

## 4. Worked example: a game of basketball

Everything below is built only from objects, states, edges, and stochastic
transitions — no special "game" machinery.

- **Players** — objects. Each player's state holds its intent (e.g. "I want to
  pass to P3" or "I'm contesting"). A player points at the **basketball** (to
  know who holds it) and at nearby players.
- **Basketball** — an object whose state is essentially a *pointer*: who has
  possession, or `{passing_to: P3}` mid-flight. It points at all the players so
  it can read their intents.
- **Hoop** — an object the basketball points at; if possession resolves to the
  hoop, that's a goal.

A possession/steal turn, expressed purely as transitions:

1. The holder's transition writes `intent = pass_to(P3)` into its own state.
2. The basketball reads that intent and transitions to a `passing` state with
   `passing_to = P3`.
3. On the next tick the basketball reads the candidate receivers' states. A
   contesting defender has *some probability* of intercepting — the basketball's
   stochastic `f` samples possession among {intended receiver, contesting
   defenders} according to whatever weights its author chose.
4. Possession resolves; if it lands on the hoop, score.

Note what this demonstrates: turn-taking, hand-offs, contested outcomes, and goals
are all just **state pointers + probabilistic local transitions**. The "game
designer" is whichever agent authored these objects' functions.

---

## 5. Discovery: the hub and edge dynamics

The universe has no global directory and no built-in notion of "agent," so a fresh
object cannot be *told* what else exists — it must discover it. The mechanism is
one distinguished vertex, the **hub**, plus the rule for how objects acquire edges.

**The hub.** A single designated object whose state is a **ledger of handles** —
stable identifiers for the vertices that exist. A handle reveals *existence, not
nature*: that something is there, not what it is or whether it is minded.

**Bootstrap rule (the meta-transition on creation).** When a vertex `V` is created,
the substrate adds *only* a bidirectional connection to the hub (`hub ↔ V`): the
hub comes to read `V` (next tick its ledger lists `V`'s handle) and `V` comes to
read the hub (from birth it can see the ledger). This is tag-free (the hub is one
object, not a category), sparse (every vertex has ≥1 edge), and causal (`V` is
listed the tick *after* it appears — the §1 light cone, applied to discovery).

**Edge dynamics.** Every other edge is created by an object's own transition
emitting an **attach/detach** effect against a handle it read from the ledger. The
rule that keeps this from getting messy: an object may edit **only its own
out-edges**.

- An out-edge means "**I choose to read X**." You may attach to any handle; the
  target is neither asked nor notified.
- You can never add an edge *into* yourself, nor touch anyone else's edges. Each
  object exclusively owns its out-edge set — so there are no shared, contended, or
  racing edges to reason about.

This yields the invariant the whole design leans on:

> **Observation is unilateral; influence is consensual.** Reading X affects only
> *you* (X's state enters *your* transition), so anyone may watch anyone, silently.
> To be *influenced* by X you must add the edge yourself — nobody can push to you.

So discovery is graduated and earned: read the hub → see handles for vertices you
**did not create** → infer other creators exist; spend an out-edge to read one →
learn what it *is*; watch it over time → infer whether it is a *mind*. Other agents
are never announced.

**Pinned-down loose ends.**
- Reading a handle for a destroyed/never-existent vertex yields an empty read (no
  error); stale out-edges are inert and may be pruned.
- Sparsity is *emergent, not enforced*: nothing stops an object attaching to many
  handles, but a wider neighborhood is a larger, costlier transition input — the
  pressure is to read only what matters. An optional per-object out-degree cap
  (§6) bounds the worst case.

---

## 6. Open considerations

Things we have reasoned about but deliberately left as decisions to finalize.

**Object destruction as a primitive.** A terminal "dead/decomposed" state already
reproduces *deletion's behavior* (the object stops acting, and on the way in can
spawn its decomposition products). So destruction does **not** enlarge the scope
of expressible worlds — it is purely a *resource-reclamation* convenience (a dead
object still occupies a vertex and runs an identity transition each tick). The
asymmetry with creation is the crux: **creation is irreducible; destruction is
not.** Leaning: keep it out of the substrate initially and let agents discover
death as a state; add a `destroy` effect later only if vertex accumulation
becomes a real cost.

**How randomness is expressed.** Two equivalent-looking options: (a) inject an RNG
and let `f` sample and return one next state, or (b) have `f` return an explicit
distribution over next states and let the engine sample. (a) is the minimal,
maximally general choice — (b) is a special case an author can build on top of
(a). Leaning: (a), with per-(object, tick) seeding so runs are replayable.

**Full neighborhood vs. a subset per tick (population-protocol style).** A
population protocol activates only a *subset* of edges each step. We considered
whether engine-level edge-subsetting changes the computational model. It does
not: a stochastic `f` can already *probabilistically ignore* any input, so
subset-activation is expressible inside the transition. Therefore keep the full
neighborhood available every tick and let `f` decide what to attend to. (Our
self-stabilization-of-population-protocols result is then a strict special case of
this richer model: population protocols are **finite-state** — constant memory
regardless of population size, hence capped at the semilinear predicates and
anonymous — whereas our objects carry **unbounded** state and arbitrary
transition functions. The finiteness is the gap, not a constraint on us.)

**Static vs. dynamic edges.** Many "dynamic relationships" are better modeled in
*state* than in *topology* — basketball possession is a pointer in the ball's
state, not a moving edge. Leaning: edges are set at creation and may be rewired by
an object's own transition, but authors are encouraged to put fast-changing
relationships in state and reserve edges for *who can perceive whom*.

**Update timing is part of the dynamics (not a latency problem).** An LLM-driven
object can take many seconds per transition — but this is *not* a special case to
engineer around. **How long an object takes to act is itself a draw from a
distribution**, on equal footing with *what* state it returns. A cheap Python
object has a near-spike delay distribution (acts essentially every tick); an LLM
object has a broad, heavy-tailed one (acts rarely). Same model, no two-tier hack:
every object samples both its next state and, implicitly, *when it next acts*.

This reconciles with the synchronous core (§1) cleanly: **double-buffering governs
the read/write discipline** — you always read generation *t*, never a
half-updated world — while **cadence rides on top as a stochastic, per-object
update interval.** Discrete substrate clock, sampled participation. Replay still
holds, because the interval draw is just another seeded sample.

Two payoffs: (a) *timing becomes expressible* — deliberation vs. reflex is a real,
observable difference, and a downstream object could read response latency itself
as signal; (b) it *deepens partial observability* — neighbors ticking on their own
stochastic clocks make the world jump in ways an object can't model from its own
steps, which is exactly the "unexplained change" we want.

**Discovery / first contact — decided (see §5).** Resolved with the hub +
out-edge-ownership model. Handles are **fully opaque** (bare stable IDs revealing
existence only): to learn what a vertex *is* you must spend an out-edge and read
it, and to tell whether it is a *mind* you must watch it over time. This is the
strongest hidden-minds setting — the discovery game is "earn every bit of
knowledge." (If coordination later proves impossibly hard, the fallback dials are
opaque-but-noisy or handle+label; both strictly *reduce* mystery, so we start
maximal.)

**Resource safety.** Open-ended creation invites runaway growth (a "fork bomb" of
objects). Author-written transition code is untrusted. The substrate needs:
per-transition CPU/memory/wall-clock limits and isolation (cf. the existing
sandbox), plus universe-level caps (max objects, creation rate). These are
guardrails, not part of the conceptual model.

**Determinism & replay.** Because the universe *is* a time series of states,
logging every object's state per tick makes the whole history inspectable and —
with seeded RNG — exactly replayable. The world becomes its own dataset.

---

## 7. Engine interface (pluggable computational models)

The substrate is meant to host *many* computational models, so the implementation
separates an invariant **contract** (shared by every engine) from a small set of
**policies** a concrete engine overrides. A model becomes a subclass that picks
policies — not a rewrite of the world.

**Fixed contract (all engines):** objects with state; directed edges; discrete
ticks; sandboxed transition invocation; double-buffered read→write (read generation
*t*, write *t+1*); seeded RNG; structural effects (create / attach / detach /
maybe destroy) applied at end of tick.

**Pluggable policies (a subclass = a choice of these):**

1. **Activation / scheduling** — which vertices transition this tick: all
   synchronously; a random subset (population-protocol style, §6); or per-object
   stochastic cadence (the timing-as-distribution model, §6).
2. **Neighbor view** — what a vertex sees of its inputs: full state / noisy /
   aggregated.
3. **Connection meta-transition** — how new vertices wire in: `hub ↔ V` (the
   default, §5); an experiment could swap in all-to-all or creator-only.
4. **Structural-effect timing** — when create/attach/detach/destroy take effect
   (default: end of tick, perceived next tick).
5. **RNG / seeding.**

Concrete examples: `SynchronousCA` (all activate, full view), `PopulationProtocol`
(random-subset activation), `AsyncStochastic` (per-object cadence). Each is a thin
subclass over the same contract, which is what makes swapping computational models
cheap.
