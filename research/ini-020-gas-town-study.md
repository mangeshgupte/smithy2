# ini-020 R1 — Gas Town Refinery batch+bisect study

**Task:** t-448 · research heat 877 · 2026-04-19 · forge-temper
**Pairs with:** `research/ini-020-assembly-current-path.md` (R2, current smithy Assembly)
**Source repo:** `/Users/mangesh/vibes/understand/gastown/repo` (Steve Yegge, `steveyegge/gastown`)

## 1. Purpose

R1 is the outside-reference half of ini-020. Before we change smithy's
Assembly to batch+bisect, map the Gas Town Refinery pattern in its own
terms, then list the concrete adaptations smithy needs. R2 (companion
doc) is the inventory of what we have today; R3 will be the design.

## 2. Where Refinery lives in the Gas Town codebase

All refinery code is Go, under `internal/refinery/`:

| File | Role |
|---|---|
| `types.go` | `MergeRequest`, `MRStatus`, `MRPhase` FSM, failure taxonomy |
| `manager.go` | Queue (sourced from beads issues, not git), start/stop, reject, post-merge cleanup |
| `batch.go` | `BatchConfig`, `AssembleBatch`, `BuildRebaseStack`, `ProcessBatch`, `bisectBatch`/`bisectRight` |
| `engineer.go` | Worker loop — claim, prepare, merge, gates. Also `acquireMainPushSlot` (merge lock) |
| `score.go` | MR scoring: priority + age + convoy age + retry penalty |

CLI glue: `internal/cmd/refinery.go` (+ `internal/protocol/refinery_handlers.go`).

## 3. The MR state machine

MRs are beads issues (label `gt:merge-request`) with two overlaid
status vocabularies (`types.go:46-101`):

- **Beads status (coarse, external):** `open → in_progress → closed`
- **Refinery phase (fine, internal):** `ready → claimed → preparing →
  prepared → merging → merged` (plus `rejected`, `failed→ready`)

```
ready  ──► claimed ──► preparing ──► prepared ──► merging ──► merged   (terminal)
  ▲                       │             │            │
  │                       ▼             ▼            ▼
  └───── failed ◄─────────┴─── rejected (terminal)   failed
```

`ValidatePhaseTransition` (`types.go:103-118`) enforces the graph
programmatically — explicit FSM, not implicit. Claims have a 30-minute
default TTL (`DefaultClaimTTLMinutes`), so a dead Engineer releases its
claim on its own.

Failure taxonomy (`types.go:250-301`) is meaningful: `conflict`,
`tests_fail`, `build_fail`, `flaky_test`, `push_fail`, `fetch_fail`,
`checkout_fail`. `ShouldAssignToWorker()` gates whether to bounce back
to the polecat (yes on content failures; no on push/fetch —
infra-retry).

## 4. The batch+bisect algorithm (the part we're adopting)

`ProcessBatch` (`batch.go:197-286`) is the 6-step pipeline:

```
batch (n MRs, pre-scored, ready)
  │
  ▼
Step 1: BuildRebaseStack(target ← MR1 ← MR2 ← ... ← MRn)
          │  per-MR: checkConflicts → squash-merge onto running stack
          │  on conflict: reset to baseSHA, rebuild without the offender,
          │               push offender to `conflicts[]`
          ▼
Step 2: runBatchGates() on stack tip   ──► green? ──► Step 3 (happy path)
                                               red?  ──► Step 4
Step 3: fastForwardBatch — push target. Merge commit = current HEAD.
          (acquires a cross-process "merge slot" if pushing default branch)
Step 4: if RetryBatchOnFlaky: resetAndRebuildStack, re-run gates
          ── green? → Step 3
          ── red?   → Step 5
Step 5: bisectBatch(stack, target) — binary search for culprit(s)
Step 6: if good subset non-empty: rebuild, verify, Step 3 on the good subset
          culprits go back as `result.Culprits` (rejected one-by-one upstream)
```

### 4.1 Stack construction (`BuildRebaseStack`, lines 97-172)

- Merge strategy: **squash-merge**, not `--no-ff`. One commit per MR on
  top of the target, so the stack is linear and each MR's content is
  isolated for bisection.
- Conflict handling is greedy: on detection (`CheckConflicts` before
  attempting), reset to `baseSHA` and rebuild the stack with the prior
  MRs minus the offender. Offender → `conflicts[]`.
- `getMergeMessage` pulls the branch's commit message; falls back to a
  generated string including the source issue id.

### 4.2 Bisection (`bisectBatch` + `bisectRight`, lines 394-506)

Two-phase binary search:

1. Split batch into `left` and `right` halves. Rebuild stack with `left`
   only, run gates.
2. If `left` is green → culprit is somewhere in `right`. Switch to
   `bisectRight(knownGood=left, right)` which tests sub-batches of
   `right` **cumulatively on top of** `knownGood` — critical: this
   catches MRs that are fine alone but break when stacked with an
   earlier MR.
3. If `left` is red → recurse `bisectBatch(left)`. Then re-test
   `leftGood + right` to see if `right` is innocent given the reduced
   `left`.

So: `O(log N)` gate runs in the common single-culprit case, more when
culprits are tangled; each test run includes a full `resetAndRebuildStack`
(checkout target, `reset --hard origin/<target>`, replay squash-merges).

### 4.3 Flaky-test retry (`RetryBatchOnFlaky`, default `true`)

Before bisecting, retry the full batch one more time. A single transient
failure doesn't blame an innocent MR. Cheap (one extra full-batch run)
and high value for flake-prone suites.

### 4.4 Merge slot (`acquireMainPushSlot`)

When pushing to the default branch, Refinery acquires a cross-process
"merge slot" lock (named slot in shared state; see `engineer.go` for
the primitive). Only one Engineer holds it at a time, so multiple
Engineers batching in parallel don't race each other's pushes. Released
in a `defer` around the push.

## 5. BatchConfig — the tunables

`batch.go:10-35`:

```go
BatchConfig{
  MaxBatchSize:      5,          // tradeoff: throughput vs bisect cost
  BatchWaitTime:     30 * time.Second,  // wait for batch to fill
  RetryBatchOnFlaky: true,       // one free retry before blaming anyone
}
```

`AssembleBatch` (`batch.go:58-88`) also honours per-MR `BlockedBy`
pointers — if A blocks B, B is skipped unless A is already in the same
batch (so A will land first when the batch pushes). This is stacked-PR
support without extra plumbing.

## 6. Deliberate Gas Town choices we should not adopt

| Choice | Why it's theirs, not ours |
|---|---|
| Beads (Dolt SQL) as queue source of truth | smithy's queue is `state.json` + `.assembly-queue.jsonl`; changing that is out of ini-020 scope and also overkill (queue size O(100), not O(10k)) |
| MR priority scoring by age + convoy + retry | smithy already has `human_priority` + initiative rank + priority_reason; Marshal sets order |
| `MRPhase` 8-state FSM in storage | smithy's `status: pending/submitted/complete` + the audit log line is already enough; the FSM is a reasonable *future* refactor but orthogonal to the batching win |
| Beads-label failure taxonomy (`needs-rebase`, `needs-fix`) | smithy routes rejections back through Marshal rather than tagging the task; the taxonomy could still inform Marshal's `priority_reason` (e.g. bucket rejections into conflict/tests/build for Marshal to act on) |
| Multiple Engineers with a push-slot lock | smithy has exactly one Assembly. No concurrent pushers → no slot needed for v1. Worth reconsidering if we ever split Assembly into per-theme instances |
| Squash-merge per MR | smithy currently does `--no-ff` with a readable message; batch+bisect doesn't *require* squash (see §7.2) |

## 7. Adaptations smithy needs

### 7.1 Staging worktree (already in R2's design, confirmed by Refinery's pattern)

Refinery runs stack+gates in a dedicated working directory
(`refineryRigDir`). It never writes to the worker's (polecat's)
worktree during merge. Direct map: ini-020 phase 1 creates
`.worktrees/_assembly-staging` and moves all rebase/merge/pytest calls
there. `rebase_forge_branch`, `run_tests_in_worktree`,
`ff_merge_forge_branch` all get re-pointed to the staging worktree.

This **alone** eliminates the t-464 stash hack (Forge worktrees no
longer mutate under Assembly's feet) and the t-461/t-460 venv-rebind
dance (staging worktree owns its own venv).

### 7.2 Stack construction — port, don't squash

We can keep `--no-ff` per-task merge commits (Assembly's current
convention — the `[assembly] merge <branch> → main` stamp is useful)
and still batch+bisect. Refinery's squash choice is a readability
tradeoff (one commit per MR), not a correctness requirement. Proposal:

1. Start staging from `main`.
2. For each per-task branch in the batch: `git merge --no-ff` it onto
   staging (not `main` directly) with smithy's existing auto-resolve for
   `worklog.tsv` + `state.json`.
3. On merge-time conflict: reset staging to the last good SHA, push
   offender to `conflicts[]`, continue.
4. Run pytest once on staging's tip.
5. On green: ff `main` to staging's SHA (single `git push`).
6. On red: same bisect algorithm as Refinery, operating on the same
   `--no-ff` merges instead of squash-merges.

The mild-resolve logic (§3.4 of R2) re-runs per-branch during
stage-assembly — same code, new cwd.

### 7.3 Bisect helper — start simple

Refinery's `bisectBatch + bisectRight` handles the case where
`leftGood + right` still fails (MRs that interact only across the
split). For smithy v1, a simpler **linear drop-one** bisect is a
reasonable starting point:

```
for i in range(len(batch)):
    rebuild stack with batch[:i] + batch[i+1:]
    if gates green: culprit = batch[i], remaining = batch minus i, done
```

- Complexity: `O(N)` gate runs worst case vs Refinery's `O(log N)`
  amortized. For `MaxBatchSize=5`, the gap is 5 vs ~3 — worth the
  simpler code.
- We can port Refinery's log-N bisect in a follow-up once the
  infrastructure is in place and we're sure batching pays (per R2 §7
  open question 2 — unmeasured pytest runtime).

### 7.4 Flaky-retry: adopt as-is

Cheap, obviously-right. One extra full-batch pytest run on red before
blaming anyone. Enable by default.

### 7.5 Conflict skip during stage assembly

Matches R2's existing `try_auto_resolve` — `MILD_PATHS` stays the same
(`worklog.tsv`, `state.json`). What's new: on severe conflict at
stage-assembly time, reject the offender **individually** (not the
batch), reset staging, continue building with the rest.

### 7.6 Reject routing — unchanged

Refinery pokes the worker directly (`notifyWorkerRejected` in
`manager.go:567-578`) via `gt nudge`. Smithy has an explicit policy to
route all rejections through Marshal (`feedback_only_assembly_writes_main.md`
and `personas/assembly/CLAUDE.md:30-34`). Keep that. Batch rejection
produces N individual `_do_assembly_reject` calls, each nudging Marshal
once — same as today, just more of them per tick.

### 7.7 Batch metadata in audit log

Refinery doesn't stamp a batch id (MRs are in beads with per-MR
phases). Smithy should: `_log` gets a `batch_id` field so a human
reading `assembly-log.jsonl` can tell which merges were co-tested and
therefore co-validated. Cheap and high value for debugging.

### 7.8 Patrol check addition

Refinery's equivalent of our patrol check #9 is implicit (beads issues
with phase != terminal + claim TTL expiry). For smithy, add a patrol
check that flags stage branches that started a rebuild but never
pushed/rejected — catches "Assembly died mid-bisect" without needing a
claim TTL (since Assembly is a singleton).

## 8. What ini-020 R3 still needs to decide

These are open questions R1 surfaces but does not answer — they
belong in the design heat, not here:

1. **Batch size.** Refinery's default is 5. Smithy's pytest runtime is
   unmeasured (R2 §7.2). Set a provisional default (3?) and a flag
   override; tune after the first week.
2. **Merge strategy.** `--no-ff` per-task inside staging vs squash.
   Recommend `--no-ff` (preserves Assembly's commit-message convention,
   makes per-task attribution identical to today) unless bisection
   complexity pushes us toward squash.
3. **BlockedBy handling.** Smithy tasks have `blocked_by`; today
   Marshal is responsible for not queueing a blocked task. In a batch
   world we could be stricter — exclude a task from the batch if its
   blocker is not already in the same batch (Refinery's
   `AssembleBatch` check). Worth one sentence in the design; very
   little code.
4. **Order-dependence.** R2 §7.1: does "take main" for `state.json`
   conflicts still work when branch B is built atop branch A's state
   inside a batch? Unlikely to matter (state.json is runtime; tests
   exercise code), but a concrete counter-example test case should
   land with the code.
5. **Bisect variant.** Linear drop-one first, log-N later — or just
   port Refinery's version now? Depends on whether R3 wants a minimum
   viable batch or a "finished" batch.

## 9. TL;DR for R3

- **Core pattern transfers cleanly.** Refinery's 6-step pipeline maps
  onto smithy with three missing primitives: staging worktree,
  stack-assembly helper, bisect helper.
- **Don't adopt:** beads, Dolt, MR-phase FSM, push-slot lock, squash
  requirement, priority scoring. Those solve Gas Town's multi-rig,
  multi-Engineer, multi-agent-writer problems; smithy has none of them.
- **Do adopt:** staged builds, one gates-run per batch, flaky-retry,
  bisect-on-red, per-MR conflict skip, batch-id in the audit log.
- **Biggest single win (already in ini-020 phase 1):** staging
  worktree. Eliminates two tax-gotchas (t-464 stash, t-460 install
  rebind) before we even get to batching.
- **Biggest risk:** bisect complexity + test-run flakiness interacting
  — amortization only pays if the happy path dominates. Measure
  pytest runtime in R3 before finalizing `MaxBatchSize`.
