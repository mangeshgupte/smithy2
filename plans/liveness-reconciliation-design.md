# Liveness via Reconciliation — Design

**Status:** draft (Anvil, 2026-04-18)
**Principle:** *If work exists, it gets done.* State.json + git branches are the sources of truth. Queues and JSONL files are caches (fast-path optimization, not correctness).
**Initiative:** TBD (candidate: new ini-024 *Liveness & Convergence*, or fold under ini-018 *Parallel Forges* since it's the same substrate)

## Why

In one session (2026-04-18) three distinct incidents shared a single root cause: **agents react to hints (queues, nudges, pushes); when hints are wrong/missing/lost, the rig freezes even though the truth says there's work.**

- **Heat 989:** 3 tasks (t-450/t-463/t-472) stuck `submitted` in state.json; Assembly queue drained them silently; Forges couldn't advance
- **Heat 887:** `next_tasks=[]` with 9 pending tasks in queue; forge-anneal idle with nothing to do; Marshal had simply stopped dispatching
- **Heat 887 (concurrent):** `.assembly-queue.jsonl` missing from disk while 2 tasks had `status=submitted` and branches existed in git; Assembly saw empty jsonl and idled

Each was patched individually (zombie status flips, direct nudges, manual merges). The underlying failure pattern repeats because **the cache (queue/jsonl/next_tasks) can diverge from the truth (state.json status + git branches) and nothing reconciles them.**

Patrol-based detection (t-491 starvation, t-493 jsonl-leak) is valuable but whack-a-mole: every new divergence class needs a new check. A structural fix makes the whole class of bugs impossible.

## Principle

**Kubernetes-style reconciliation:** every agent's idle tick performs a *source-of-truth scan* — derives what it should be doing from state.json + git, not from a queue file. Queues remain as optimization (saves work when hints are correct) but are no longer load-bearing for correctness.

## Goals

- Forge idle + pending work exists + forge is eligible → forge starts work (no Marshal push required)
- Assembly idle + submitted branch exists → Assembly merges it (no jsonl entry required)
- Marshal idle + pending tasks exist + forges idle → next_tasks repopulated (no nudge required)
- Lost nudges, missing jsonl, stale queue files become non-events: agents reconverge on next tick

## Non-goals

- Marshal's optimization role (priority computation, cross-forge load balancing) is *not* changed — Marshal still drives the optimization layer
- Nudge channel is *not* removed — it's the fast path; reconciliation is the correctness backstop
- No overhaul of state.json schema, worklog format, or git-merge flow
- Not replacing patrol — patrol remains the audit/observability layer

## Architecture

Two layers, clearly separated:

**Fast path (unchanged):** nudges arrive → agent wakes → checks queue/jsonl → acts on fresh hint. Sub-second latency. Saves polling cost in the happy path.

**Correctness path (new):** on every idle tick (with or without a nudge), agent runs a reconciliation pass:
- Read current state.json
- Derive "what should I be doing?" from truth (task statuses + branches on disk)
- If there's work, do it — even if queue/jsonl says otherwise

```
                  ┌─── nudge ──────────────► wake ──► check queue/jsonl ──► act
                  │                                        │
                  │                                        └─ no hints ─┐
                  │                                                      ▼
   agent idle ────┤                                            reconcile pass
                  │                                                      │
                  └─── idle tick (timer) ─────────────► reconcile pass  ─┤
                                                                         ▼
                                          scan state.json + git ──► act if work exists
```

## Agent-by-agent reconcile predicate

### Assembly

**Current behavior:** tick reads `.assembly-queue.jsonl`, processes one entry or idles.

**New behavior:** after jsonl check, if jsonl was empty, scan `state.queue` for any task with `status=submitted` AND its per-task branch exists in git (`forge-<id>/<task-id>`) — if found, process directly via `assembly-rebase → assembly-test → assembly-merge/reject`, same as a jsonl-driven tick.

**Claim atomicity:** none needed — Assembly is singleton; no race.

**Cost per idle tick:** one state.json read + N `git rev-parse --verify <branch>` checks. <200ms typically.

### Forge

**Current behavior:** idle waits for nudge; nudge contents or queue-pop tells it what task to start.

**New behavior:** after nudge-queue check, if empty, reconcile:
1. Read state.json
2. Find tasks where `status=pending` AND (`assigned_forge=<my-id>` OR `assigned_forge is None`) AND no blocked_by unmet
3. Rank by priority + recency; pick top
4. Atomic claim: CAS from `status=pending → status=in_progress` with `assigned_forge=<my-id>` (reject if another forge beat us)
5. On successful claim, start the heat

**Claim atomicity:** required — multiple forges may scan concurrently. Two options:
- **(A)** File-lock on `state.json` during read-modify-write (standard; probably already exists for state.json writes)
- **(B)** New `smithy claim-task --forge <id>` CLI that performs the CAS server-side and returns the claimed task or None. Cleaner API; testable.

Recommend (B) — extends existing CLI vocabulary (`queue-pop`, `queue-push`) naturally.

**Cost per idle tick:** one state.json read + one conditional write. ~100ms.

### Marshal

**Current behavior:** computes next_tasks on nudge; when uncertain, blocks on stdin (being fixed by t-479).

**New behavior:** every idle tick, check invariant:
- If any forge is idle AND `next_tasks` is empty AND `queue` has eligible pending tasks AND halt is off AND budget remains → repopulate `next_tasks` with top-K dispatchable tasks (K = number of idle forges)

If this invariant is continuously maintained, Forge reconciliation rarely fires (Marshal populates first, Forge pops from next_tasks via fast path). Forge reconciliation becomes the safety net when Marshal stalls.

**Cost per idle tick:** reuses existing priority-walk algorithm.

## Implementation plan

**T1. Assembly reconciliation** *(smallest surface, biggest win)*
- Modify Assembly's tick loop: after reading `.assembly-queue.jsonl`, if it was empty, scan `state.queue` for `submitted` tasks with valid branches; process the first one directly.
- No CLI changes; just alter the tick's dispatch predicate.
- Tests: (a) empty jsonl + submitted task with branch → processed; (b) empty jsonl + submitted task without branch → skipped (don't create ghost work); (c) both jsonl and state agree → jsonl path wins (fast path preserved); (d) multiple submitted tasks → process one per tick (same pace as current).

**T2. `smithy claim-task --forge <id>` CLI**
- Atomic CAS from pending→in_progress with the forge's id stamped.
- Returns claimed task JSON on success; exit 1 + empty result on race/no-work.
- Uses the existing state.json file-lock infrastructure (same pattern as queue-push).
- Tests: (a) happy path claim; (b) two concurrent claims for same task → one wins, one gets nothing; (c) no eligible task → empty result; (d) forge not in roster → error; (e) task assigned to different forge → respected (no cross-forge claim).

**T3. Forge reconciliation**
- Modify Forge's idle behavior (`personas/forge/CLAUDE.md` loop step): after nudge-queue check, if no hint, call `smithy claim-task --forge <my-id>`. If a task is returned, start the heat.
- Protocol-level change; code-side is the new CLI (T2).
- Tests: (a) empty nudge + pending task with my assigned_forge → claimed; (b) empty nudge + pending task with no assigned_forge → claimed; (c) empty nudge + pending task assigned to another forge → not claimed; (d) empty nudge + empty queue → stay idle.

**T4. Marshal next_tasks invariant**
- Marshal's tick loop checks: if `next_tasks=[]` AND idle forges exist AND pending tasks eligible → repopulate.
- Eligible = not blocked, right stage, respects affinity/touches from ini fields.
- Tests: (a) invariant holds after each merge (which consumes from next_tasks); (b) halted rig → no repopulation; (c) budget exhausted → no repopulation; (d) all forges busy → no-op.

**T5. Queue/jsonl semantics documented as cache**
- Update `protocol/loop.md` and each persona CLAUDE.md to state explicitly: "state.json task status + git branches are truth; queues/jsonl are caches. Agents reconcile on every idle tick."
- Remove any protocol language that treats queues as load-bearing for correctness.
- Purely documentation; no code change.

**T6. Patrol integration (defense in depth)**
- Keep t-491 (starvation detection) and t-493 (jsonl-leak detection) — they run periodically as a crosscheck. But now `--fix` is almost never needed because reconciliation self-heals.
- Patrol becomes the audit layer: if patrol raises a convergence issue, it means reconciliation has a bug (we investigate), not that the rig is broken for users.

## Rollout

**Phase 1 (this sprint):** T1 + T2 + T3. Assembly and Forge self-heal. Most common failure modes (zombie submitted, starvation) are structurally fixed.

**Phase 2 (next sprint):** T4 + T5. Marshal's invariant maintenance + documentation.

**Phase 3 (future):** Evaluate whether to remove `.assembly-queue.jsonl` and `next_tasks` entirely — keep as optimization if measurable latency improvement, remove otherwise.

Budget estimate: T1 ~1 heat, T2 ~2 heats, T3 ~1 heat, T4 ~2 heats, T5 ~1 heat. **Total ~7 heats.**

## Open questions for human

1. **Initiative** — new ini-024 or fold under ini-018 (Parallel Forges)? My recommendation: ini-024. It's a distinct architectural principle deserving its own rank slot, not a sub-feature of ini-018.
2. **Claim mechanism** — (A) file-lock reuse or (B) new `claim-task` CLI? My recommendation: (B). Cleaner contract, testable without file-system mocking.
3. **Forge reconciliation frequency** — every idle tick, or throttled (e.g., every 30s when idle)? My recommendation: every idle tick. Cost is negligible (~100ms) and makes the convergence property clean to reason about. Throttling reintroduces the "queue stale for N seconds" failure surface.
4. **Is (q) this and (p) the patrol checks running in parallel** — yes; (p) already filed (t-491, t-493, t-492). (p) remains useful as an *audit layer* that flags when reconciliation itself is buggy. Keep both tracks running.
