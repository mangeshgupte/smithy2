# Multi-forge Priority Poker — design brief

**Task:** t-430 (research + planning)
**Filed:** 2026-04-17 (Anvil, after observing N=3 hardening-sprint friction)
**Scope:** research + planning only — implementation tasks are deferred to
`plans/multi-forge-poker-plan.md`.

## 1. Problem

Priority Poker (`ui-priority-poker/app.py` backed by
`state.initiatives[].rank`) is the human's main knob for expressing
what matters. Marshal reads it as **Priority Rule #3** in
`personas/marshal/CLAUDE.md`: "Higher-ranked initiatives' tasks come
first."

Poker was designed against a **single-Forge** rig. On 2026-04-17 we
switched the production rig to **N=3 Forges + Assembly** and within a
few hours five of Poker's implicit assumptions broke in ways that
matter for throughput and correctness.

## 2. The five broken assumptions

### 2.1 Serial-consumption assumption

Poker expresses rank as a single total order over initiatives. With one
Forge that's fine — it works the top initiative until it runs out of
tasks, then the next. With three Forges, a strict total order
**serializes work that could legitimately run in parallel**.

*Example (2026-04-17 hardening sprint):* ini-018 (parallel Forges)
produced a burst of mutually-independent tasks — scripts/tmux-stop.sh
(t-412), scripts/nudge.sh docs (t-413), patrol check #9 (t-423), check
#10 (t-424). These touch disjoint files. A lane-aware dispatcher would
have put three of them in flight simultaneously; today's Marshal walked
them one at a time until it ran out of Forge-id hints to round-robin.

### 2.2 No contention model

Nothing on the initiative tells Marshal (or Assembly) which initiatives
step on each other. Two top-ranked initiatives both touching
`smithy/cli.py` guarantees an Assembly rebase conflict — rejected merge,
re-queue, wasted work.

*Example:* t-419 (state.json anchoring) and t-422 (assembly-queue
anchoring) — both edit `state.py`'s path helpers. Running in parallel
would have produced a conflict; only Anvil's manual serialization kept
them merging cleanly.

### 2.3 No per-initiative parallelism semantics

Some initiatives are inherently safe to parallelise (ini-018: separate
scripts, separate tests); some must serialize (a refactor that unwinds
a common helper across 30 call sites). Today's Poker exposes **one
knob** — rank — which conflates "do this first" with "do this alone."

### 2.4 No Forge affinity

Context compounds. forge-quench has been the primary driver of
smithy/cli.py refactors across t-411, t-414, t-419, t-422 — it carries
the mental model. Round-robin dispatch throws that away; forge-anneal
(me, at t-423) has to re-derive main_repo_root / assembly_queue_path /
per-task-branch conventions on every touch. Affinity-preserving
dispatch would route cli.py tasks to forge-quench while other Forges
pick up disjoint work.

*Concrete cost:* on 2026-04-17 my t-423 branch fell ~16 commits behind
main because the rig repeatedly dispatched cli.py work to me without
context, and I inlined `main_repo_root` resolution because my worktree
hadn't seen t-419 yet. forge-quench would have used the helper
directly.

### 2.5 Assembly back-pressure invisible

Assembly is the single integrator. When its drain rate falls below the
dispatch rate — any reject, any rebase hiccup, any pane crash — the
queue grows silently. Poker keeps Marshal pushing new work as fast as
Forges drain. Without a pressure signal Marshal can't differentiate
"Forges are moving" from "Forges are moving and Assembly is drowning."

*Example:* the 2026-04-12 rig deadlock (root-caused 2026-04-17) —
state.json wasn't anchored to main root, so Assembly's queue drained
zero entries for hours while Forges kept submitting to worktree-local
queues. Patrol check #9 (t-423, just landed) is a compensating control;
Poker itself still has no back-pressure concept.

## 3. Design options

### Option A — Lanes

Split the board into N lanes (one per Forge). Human ranks each lane
separately.

+ Clear mental model.
+ No contention because each lane is its own queue.
- Forces the human to do Marshal's job of load-balancing.
- Breaks the "one board, one ordering" ritual Poker was built around.
- No cross-lane parallelism signal — lane-local serial becomes
  global serial again if one lane drains faster.

### Option B — Affinity-tagged single Poker

Keep the single ranking. Add per-initiative `affinity: [forge-id]` as an
advisory hint. Marshal prefers affine Forges but falls back.

+ Minimal UI surface change (one chip per initiative).
+ Preserves the human's drag-to-rank ritual.
- Doesn't solve contention (two `cli.py` initiatives with the same
  affinity still conflict).
- Doesn't solve parallelism semantics (serial-required initiatives
  still look parallel-eligible to the dispatcher).

### Option C — Two-layer Initiative + Task Poker

Two boards: initiative-level (strategic, as today) + task-level
(tactical, showing currently-dispatchable tasks).

+ Maximum control.
- Doubles the human's workload. Human has to re-rank tasks every time
  the queue shifts.
- The task list is a generated artifact; making it directly rankable
  creates a dual source of truth between `queue[]` and the board.
- Rejected on UX grounds.

## 4. Recommendation — hybrid B + C-lite

Keep the single-board Poker. Add three advisory fields per initiative
and make Marshal's dispatch a constraint walk instead of a linear
scan. The three fields default to today's behavior, so every existing
initiative keeps working.

### 4.1 Schema additions (`state.initiatives[]`)

| Field | Type | Default | Semantics |
|---|---|---|---|
| `parallelism` | `"serial"` \| `"parallel"` | `"parallel"` | If `serial`, at most one Forge may be on any task from this initiative at a time. |
| `affinity` | `[forge-id]` | `[]` (any) | If non-empty, tasks prefer one of these Forges. Fallback to any Forge only if none of the listed Forges is available. |
| `touches` | `[path-glob]` | `[]` (no claim) | Advisory contention claim. If `parallelism=serial` and another in-flight task's `touches` overlaps, Marshal waits. |

All three are backward-compatible. An initiative with no poker metadata
behaves exactly like today: parallel, any Forge, no contention claim.

### 4.2 Marshal dispatch — constraint walk

For each idle Forge, Marshal walks initiatives **by rank**:

1. Skip if `parallelism = serial` and another Forge is already in-flight
   on this initiative.
2. Skip if `affinity` is non-empty, this Forge isn't in the list, **and**
   a listed Forge is currently idle (i.e., affinity is preferential, not
   hard — the task still gets picked up by a non-affine Forge if no
   affine Forge is available).
3. Skip if `parallelism = serial` and `touches` overlaps with the
   `touches` of any in-flight task from **any** initiative.
4. Find the top-priority unblocked task in this initiative and dispatch.

This is a small change — the existing single-initiative scan becomes a
filter-and-scan. The data it reads already lives in `state.json`; the
new fields just add three predicates.

### 4.3 Assembly back-pressure

Global circuit breaker. Before dispatching new work:

```
if len(.assembly-queue.jsonl) >= 2 * N_forges:
    pause dispatch; service in-flight only
```

Keeps the queue bounded at 2× the Forge count so transient
Assembly slowdowns don't cascade into runaway backlog. Reuses the
queue file that patrol check #9 (t-423) already consumes for staleness
detection — one source of truth.

### 4.4 UI — Priority Poker

Card changes only; drag-to-rank stays exactly as it is.

```
┌────────────────────────────────────────────────────────┐
│ ▤ ini-018 — parallel Forges                      r=1 │
│    [parallel] [any forge] ~not contended             │
│    6 tasks open · 3 in-flight · 2 done                │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ ▤ ini-022 — cli.py observability refactor        r=2 │
│    [serial] [forge-quench] ~touches smithy/cli.py    │
│    4 tasks open · 1 in-flight                         │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ ▤ ini-020 — doc sweep                            r=3 │
│    [parallel] [any forge] ~not contended             │
│    12 tasks open                                      │
└────────────────────────────────────────────────────────┘
```

Three compact chips on each card — parallelism, affinity, touches —
click to edit. The human doesn't *have* to touch them (defaults are the
status-quo). They exist so a human who knows "this one touches
cli.py, serialize it" can say so in one click.

## 5. What this preserves vs. enables

**Preserves.** Poker is still the ordering ritual. Drag-to-rank works.
Marshal still reads `rank` as its primary priority signal. Existing
initiatives with no metadata keep running exactly as they do today.

**Enables.** Three independently-parallel initiatives can run on three
Forges. Contended initiatives auto-serialize. Forge context is
preserved where the human knows affinity matters. Assembly drain rate
caps dispatch rate; no more silent backlog growth.

## 6. Non-goals (defer to future)

* **Auto-suggested `touches`.** It would be cheap to infer a starting
  glob list from task descriptions, but a bad auto-suggestion is worse
  than an empty default. File separately if the UX warrants it.
* **Per-task parallelism overrides.** Everything here is initiative-
  scoped. Task-level overrides can layer later without schema churn.
* **Multi-Assembly.** This doc assumes one integrator. If we ever need
  parallel Assembly (different subtrees, different main branches),
  that's a separate design.

## 7. Implementation plan

See `plans/multi-forge-poker-plan.md` — four ordered tasks, ready for
Marshal to queue.
