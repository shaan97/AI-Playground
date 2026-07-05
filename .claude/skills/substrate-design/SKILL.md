---
name: substrate-design
description: Design principles for the v2 GDS substrate — reach for this BEFORE adding or changing a primitive/effector/field, adding validation or an invariant, deciding whether logic belongs in the substrate (gds/, world/) or a client kernel (gds/agents, examples), or fixing a bug in the graph / topology / kernel / engine layers. Use it to sanity-check a design against the substrate's laws, or when a fix feels like a special-case patch and you suspect a missing invariant ("shouldn't this be a natural outcome of the design?").
---

# Designing the GDS substrate, principled

The v2 world (`v2/gds/`, north star `docs/UNIVERSE.md`) is a deliberately tiny
substrate. Its power comes from what it **refuses** to add, so most design work is
deciding *not* to add something, or moving a concern to the layer that owns the
truth. This skill is the decision procedure and the laws behind it. **Paths are
relative to the unit root `AI-Playground/`.**

Read this before writing substrate code or making a design call. It is short on
purpose; the laws do the work.

## The model in one paragraph

An **object is a stateful vertex** in a directed graph. An arc `X → Y` means "X
observes Y" — Y's state feeds X's transition. Every object has **one rule**:
`next_state ~ f(own_state, {out-neighbour states}, randomness)` — **local,
stochastic, synchronous** (double-buffered: read generation *t*, write *t+1*).
**Agents are just objects** whose `f` is an LLM (`gds/agents/llm.py`). **Creation is
the only structural primitive**; destruction, messaging, interaction, and death are
*emergent*. The world has no global directory — discovery goes through a **registry
hub** whose ledger lists handles (existence, not nature).

## The laws

**L1 — Minimality. Add a primitive only if it strictly enlarges the set of
expressible worlds.** Before adding an effector, field, or op, ask: can this already
be built from objects + a convention? If yes, don't add it. Anchors: `RemoveVertex`
is deferred (death = a terminal "dead" state that reproduces its behaviour); there is
no message primitive (coordination is stigmergic — objects read each other's state).

**L2 — Observation is unilateral; influence is consensual.** An object may modify
**only its own state and its own out-star** (its arcs, new vertices it creates). It
can never write another object's state or add an arc *into* itself. Enforce this **by
type** where you can: `AddArc`/`RemoveArc` carry only a `target`; the source is always
the acting vertex, so a cross-object edit is *inexpressible* (`gds/topology.py`). When
tempted to let X change Y, invert it: let Y choose to observe X.

**L3 — Information locality.** A vertex knows only what it observes (its
out-neighbours) plus any registry ledger it reads. **Never hand a kernel the global
roster** or another object's internals. If a feature "needs to see everything," model
that thing as an *observable object* others can read (that is exactly what the
registry is), not as a substrate privilege. Existence is public via the ledger;
*nature* is not.

**L4 — Enforce invariants at the authoritative layer; don't patch symptoms.** When a
check is needed, put it where the ground truth lives, and make correctness **fall out
of a structural property** rather than a bespoke guard. Smell: you're writing an
explicit comparison in a *client* to catch something the *substrate* should make
impossible. Ask: **"what single invariant, enforced once, makes this bug
inexpressible?"** (Worked example below.)

**L5 — Errors propagate up; illegal ≠ over-budget.** When the authoritative layer
**refuses** an illegal/malformed request, record it and route it back to the actor so
it can self-correct — don't swallow it silently. Contrast: resource guardrails
(`gds/safety.py` `Limits`) *are* silently dropped by convention, because over-budget
is legal-but-capped, not illegal. Illegal/malformed → propagate; over-budget → drop.

**L6 — Substrate vs client. Keep the world minimal and LLM-free; put agent smarts
client-side.** `gds/` (and `world/`) is stdlib-only — no models, prompts, or memory.
A **world rule** (an invariant every object must obey) belongs in the substrate; an
**agent affordance** (help an agent not make mistakes) belongs in the kernel/client
(`gds/agents`, `examples/`). Don't leak one into the other.

**L7 — Timing is part of the dynamics.** A transition may return `PENDING` ("not
ready this step — hold my state", `gds/kernel.py`). How long something takes is itself
a modelled quantity. Use the schedule (`gds/schedule.py`) / `PENDING`, not ad-hoc
timing hacks.

**L8 — Test-first from the interface spec.** Write tests from the spec before
implementing (`v2/tests/test_phase*_tdd.py`). When you change a rule, update the tests
that encoded the *old* contract **and add a negative/regression test** for the new
one. A green suite after a spec change is also proof of the new spec.

**L9 — Validate empirically.** Reasoning about emergent behaviour is unreliable — run
an actual Gemma world and audit it (the **audit-runs** skill). Distinguish "absence of
the bug" from "captured the corrected behaviour"; say which you have.

## Decision procedure

About to add or change something in the substrate? Walk these in order:

1. Can existing primitives + a convention already express it? → if yes, stop (L1).
2. Does it let an object touch state/arcs that aren't its own? → redesign so the
   affected party opts in by observing (L2).
3. Does a kernel need to see beyond its neighbours + the ledger? → model the "global"
   thing as an observable object (L3).
4. Is it a guard against an illegal state? → find the invariant that makes that state
   inexpressible and enforce it where the ground truth lives (L4).
5. If a request can be refused, how does the actor find out? → propagate it up (L5).
6. Is this a world rule (→ substrate) or an agent affordance (→ client kernel)? (L6)
7. Write/adjust the spec tests first; add a negative test (L8).
8. Run a real world and audit (L9).

## Worked example — the dangling-arc bug (teaches L4, L5, L6)

**Symptom.** An agent created an object it named `collector` (the engine slugifies
labels to lowercase) but later referenced `Collector`. The arc was silently made to a
vertex that did not exist, so the agent's intended observation returned nothing, with
no feedback. In older runs this shows up as "phantom arcs."

**The wrong first fix** (don't do this): an explicit case-sensitive existence check
*inside the LLM kernel*, comparing the target against the agent's ledger view. It was
wrong four ways — a checklist of L4/L6 violations:
- it patched **one of three doors** (agent `add_arc`, a newborn's `observes` list, and
  a `LocalKernel` object emitting `add_arc`) — the other two still dangled;
- it put a **world concern in the client** (L6);
- it framed plain **set-membership as a "case-sensitive check"** (a bespoke guard
  where a structural property belonged);
- it was actually **stricter than the truth** — it would reject an arc to a vertex
  created last step that wasn't yet in the agent's (one-step-stale) ledger view.

**The right fix.** Name the missing invariant: the graph never guaranteed
`A ⊆ V×V` — `Digraph.with_arc` only ensured the *source* existed, so any path could
create an arc to a non-existent *target*. Enforce it **once, at the authoritative
layer** (`gds/topology.py::apply`, which holds the real vertex set): refuse an
`AddArc`/newborn observe-arc whose target isn't a vertex, and record the refusal in
`ApplyResult.rejected`. **Case-sensitivity falls out of exact set membership** — no
special check. Then **propagate** (L5): the engine (`gds/evolution.py`) collects
refusals per actor and delivers them to that vertex's kernel via an optional
`notify()` hook before its next turn; `LLMKernel.notify` surfaces them to the model
("The world reports on your last turn: …") so it self-corrects. One invariant, at the
source, closes all three doors and makes the bug inexpressible — the correctness is
now a property of the graph, not a guard in the agent.

## Smells that you're fighting the design

- A validation check in a client kernel about **world state** → likely a substrate
  invariant (L4/L6).
- Your fix touches "the tool," but the **same illegal state can arise another way** →
  symptom patch; find the invariant (L4).
- A new field/effector added "just in case" → does it *strictly* enlarge expressible
  worlds? (L1)
- Reaching for the **global vertex set inside a kernel** → information-locality
  violation; model it as an observable (L3).
- Silently dropping something **illegal** → the actor can't learn; propagate (L5).
- "It compiles and tests pass" but you **never ran a world** → validate empirically
  (L9).

## See also

- `docs/UNIVERSE.md` — the north star / full rationale; `docs/SAFETY-v2.md`.
- **audit-runs** skill — run + audit a real Gemma world (L9).
- **run-universe-viewer** skill — watch a run live.
