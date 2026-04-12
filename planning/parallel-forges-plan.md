# Parallel Forges — Implementation Plan

**Task:** t-394 (ini-018, planning) · heat 807 · 2026-04-12
**Blocked by:** t-393 (research) — completed commit `c45a829`
**Status:** DRAFT — surface to Anvil for human review before any impl heat
is pushed. No task on the list below should enter the queue until Anvil
signs off.

## Why review-gate this plan

Parallel Forges is a rig-level change: two+ Forge sessions running
concurrently, a new Assembly teammate, schema mutations to state.json,
branch-and-merge discipline that didn't exist yesterday. Every decision
locks in behavior that's painful to unwind. The plan has three open
questions from t-393 that only Anvil can answer (§Open Questions below);
impl waits on those.

## Shutdown-first

Before we turn on N=2, we must know we can turn it **off** safely.
Shutdown is the most under-specified piece of any multi-agent system, and
the one that bites during incidents. Order:

1. **Halt flag**: Marshal reads `state.parallel.halt`. If `true`, stops
   assigning new tasks — but does not kill in-flight work.
2. **Drain in-flight heats**: each Forge completes its current heat
   normally (commit, end-heat, log). No force-kill.
3. **Drain Assembly**: merges everything in `.assembly-queue.jsonl`, then
   idles.
4. **Verify quiesce**: all `parallel.forges[].status == "idle"`;
   `.assembly-queue.jsonl` empty; no checkpoints present.
5. **Persist sentinel**: write `.shutdown.json` with ts/reason/final IDs.
   Restart reads it and knows to rehydrate vs. cold-start.
6. **Hard-kill recovery**: on next start, Witness sweeps stale
   checkpoints and reclaims zombie Forges via `forge-reset`.

Task I0 below is "build shutdown first, turn on N=2 last." Non-negotiable.

## Ordered tasks (dependency order, retro-format)

Each task has a **thesis** (why it matters), **scope** (heat estimate),
**depends_on**, and **definition of done**. `I` = impl, `T` = tests,
`D` = docs.

---

### I0 — Shutdown + sentinel machinery (value: **high**, prereq)

**Thesis:** You cannot safely bring up what you cannot bring down. This
lands first so every later step is reversible with one command. It's also
purely additive at N=1 — zero behavior change until we flip the halt flag.

**Scope:** 1 heat. Touches: `smithy/cli.py` (new `smithy halt`, `smithy
resume-rig`, `smithy shutdown-status`), `state.json` schema adds
`parallel.halt` bool.

**Depends on:** nothing.

**Done when:** `smithy halt` sets the flag, Marshal reads it before
assign; `smithy resume-rig` clears it; test fixture proves a running Forge
can quiesce within one heat of flag set.

---

### I1 — Schema + per-Forge namespacing (value: **high**, prereq)

**Thesis:** Lets everything downstream assume N≥1. No behavior change at
N=1 — the default registry has one Forge, its checkpoint file renames
from `.forge-checkpoint.json` → `.forge-01-checkpoint.json`, nudge queue
from `forge.jsonl` → `forge-01.jsonl`. This is a rename-only migration
heat, verifiable with patrol.

**Scope:** 1 heat. Touches: `smithy/state.py` (read/write checkpoint with
forge_id argument), `smithy/cli.py` (drain-nudges, queue-push,
queue-pop, end-heat; all accept `--forge <id>` with default `forge-01`),
`state.json` gains `parallel.max_forges: 1` + `parallel.forges[]`.

**Depends on:** I0.

**Done when:** all smithy commands accept `--forge` flag; patrol clean at
N=1 with renamed files; 3 new tests covering the rename and flag plumbing.

---

### I2 — `smithy forge-spawn` + `forge-reset` CLI (value: **high**)

**Thesis:** Operational controls must exist before Assembly can be built,
because Assembly's recovery path uses `forge-reset`. Also: `forge-spawn`
is how Anvil actually starts a second Forge, which we need to demo N=2.

**Scope:** 1 heat. Touches: `smithy/cli.py`, `smithy/parallel.py` (new
module). `forge-spawn` creates `.worktrees/forge-NN/`, git worktree add,
registers in `state.parallel.forges[]`. `forge-reset` clears checkpoint,
re-queues assigned task, logs to steering.

**Depends on:** I1.

**Done when:** spawn two Forges, verify `.worktrees/forge-02/` exists;
reset reclaims a zombie Forge in a fixture; 4 new tests.

---

### I3 — Assembly teammate scaffolding (value: **medium**, shell only)

**Thesis:** Empty loop before the real logic — lets Anvil spawn Assembly
like Marshal/Forge and get a heartbeat. De-risks the spawn discipline
before the merge logic adds more surface to debug.

**Scope:** 0.5 heat. Touches: new `personas/assembly/` dir with CLAUDE.md,
skeleton loop that drains `.assembly-queue.jsonl` and no-ops each item.

**Depends on:** I1.

**Done when:** Anvil's TeamCreate can spawn Assembly; Assembly reads its
own CLAUDE.md; heartbeat lands in `parallel.assembly.last_heartbeat`.

---

### I4 — Assembly merge loop (value: **high**) *(amended 2026-04-12)*

**Thesis:** This is the heart of parallelism. Rebase → pytest → attempt
merge. **Assembly uses LLM-level judgment** on conflicts: resolve when
reasonable (no semantic contradiction, small surface, tests green
post-resolution); discard the branch and requeue the task when not.

**Scope:** 3 heats (was 2; scope expanded by resolution path + lifecycle
rewire). Touches: `personas/assembly/*`, `smithy/parallel.py` (git ops),
new `assembly-log.jsonl` audit, `smithy end-heat` lifecycle change,
Marshal scheduler reads `submitted` status.

**Conflict policy (amended):**
- **Reasonable conflict** → Assembly attempts resolution, re-runs tests,
  ff-merges if green. Merge indicator `🔀 merged-with-resolution`.
- **Unreasonable conflict** → Assembly discards the branch (pruned), task
  status flips back to `pending` with `priority_reason="assembly
  rejected: <reason>"` and a small priority bump (+5 hp) to avoid lossy
  loops. Worklog row: `outcome=rejected reason=<conflict>`.
- **When in doubt, defer** — Assembly's judgment call.

**Task lifecycle (amended — CRITICAL):**
- Forge `end-heat` commits to branch → task status `submitted` (NOT
  `complete`).
- Assembly's successful merge → `complete`.
- Assembly's rejection → back to `pending` (requeued, bumped).
- Worklog gets **two rows** per task:
  - `H_NN outcome=submitted value=🟢/🟡/🔴` (Forge)
  - `H_NN outcome=merged commit=<sha>` OR `outcome=merged-with-resolution
    commit=<sha>` OR `outcome=rejected reason=<…>` (Assembly)
- Merge indicator (✅ / 🔀 / 🚫) is separate from Forge's value score.

**Marshal scheduler impact:** `submitted` status is "not available, not
blocking, awaiting merge." Requeued tasks get +5 hp bump.

**Depends on:** I3, I2.

**Done when:** fixtures cover (a) clean merge, (b) resolution-success,
(c) resolution-attempted-then-abandoned, (d) full-reject + requeue +
bump; `submitted` state flows through Marshal correctly; worklog
two-row pattern lands; 8 new tests (was 6).

**Post-I7 polish (flagged, not in this task):** attribution/retro
tooling needs updating for the two-row lifecycle.

---

### I5 — Marshal dispatch across N Forges (value: **high**)

**Thesis:** Without this, N=2 is just N=1 with a spare Forge sitting
idle. Adds `assigned_forge` field, per-Forge `queue-pop` filter, and the
assign-skip-for-blocked_by-transitive rule.

**Scope:** 1.5 heats. Touches: `personas/marshal/*` (dispatch logic),
`smithy/cli.py` (`queue-pop` filter), `state.json` queue entries.

**Depends on:** I1, I4.

**Done when:** dry run with 2 Forges + 3 independent tasks has both
Forges working in parallel; test proves `blocked_by` honors cross-Forge
dependencies.

---

### I6 — Per-Forge Witness integration (value: **high**)

**Thesis:** Stuck-state detector from t-386 must apply per Forge at N≥2.
Without this, a single zombie Forge can eat the loop and nobody notices.

**Scope:** 1 heat. Touches: `smithy/cli.py` patrol block; depends on
witness-patrol work from t-386 (if still TBD, merge plans).

**Depends on:** I1, ideally I5; soft-depends on t-386's C1/C5 candidates.

**Done when:** synthetic two-Forge stall (one zombie) fires tier-1
witness for that Forge only; healthy Forge keeps running.

---

### I7 — N=2 sandbox test + documentation (value: **medium**, acceptance)

**Thesis:** Integration test for the full loop. Two Forges, real tasks,
Assembly running, Witness enabled. Proves it works end-to-end in a
fixture before we ever turn it on in the real rig.

**Scope:** 1 heat. Touches: `tests/test_parallel_forges.py`,
`STRATEGY.md` update, `WALKTHROUGH.md` "Running N=2" section.

**Depends on:** I5, I6.

**Done when:** sandbox test runs 5 simulated heats across 2 Forges; final
state has 5 merged commits, no duplicates, no lost heats, patrol clean.

## Dependency graph

```
I0 ──► I1 ──► I2 ──► I4 ──► I5 ──► I7
                │      ▲      │      ▲
                └► I3 ─┘      └► I6 ─┘
                       (I3 before I4)
```

I0 and I1 are serial prereqs. I2 and I3 can run in parallel (different
areas). I4 needs I2+I3. I5 needs I1+I4. I6 and I5 can run in parallel.
I7 is acceptance, last.

## Heat budget

| Task | Heats |
|---|---|
| I0 shutdown | 1 |
| I1 schema/namespacing | 1 |
| I2 spawn/reset CLI | 1 |
| I3 Assembly scaffold | 0.5 |
| I4 Assembly merge loop *(amended)* | 3 |
| I5 Marshal dispatch | 1.5 |
| I6 Per-Forge Witness | 1 |
| I7 Sandbox + docs | 1 |
| **Total** | **~10 heats** |

*I4 budget was 2, amended to 3 (2026-04-12) for conflict-resolution path
+ task-lifecycle rewire (`submitted` status, two-row worklog, +5 hp
requeue bump). Still under the 12-heat guard.*

~9 heats is 3× t-393's initial 5-heat MVS estimate. The delta is
shutdown machinery (not in the t-393 MVS), explicit tests, and Witness
integration. Shutdown is non-negotiable; Witness is earned by N≥2
criticality; tests are load-bearing. If Anvil wants the 5-heat version,
the trim is: fold I0 into I1, squash I3+I4, drop I6 (accept risk).

## Integration checklist (before I7 acceptance)

- [ ] `smithy halt` / `smithy resume-rig` work end-to-end
- [ ] All `smithy` commands accept `--forge <id>` (default forge-01)
- [ ] Checkpoint/nudge files are Forge-ID-namespaced
- [ ] `forge-spawn` creates worktree and registers in state.json
- [ ] `forge-reset` reclaims zombie Forge and re-queues task
- [ ] Assembly can be spawned via TeamCreate from Anvil
- [ ] Assembly reads its own CLAUDE.md (no cwd bug — enforce cd pattern)
- [ ] Assembly aborts on merge conflict, marks `assembly_blocked`
- [ ] Assembly rejects on test failure, marks `assembly_failed`
- [ ] Assembly logs merge sha to worklog on success
- [ ] Marshal dispatches to idle Forges only
- [ ] Marshal respects `blocked_by` across Forges
- [ ] Witness fires per-Forge; healthy Forges unaffected by zombie peer
- [ ] Commit subject format updated: `[stage][forge-NN] t-XXX: …`
- [ ] Patrol stats per-Forge: heats-used, last-heartbeat
- [ ] Two-Forge sandbox test passes
- [ ] STRATEGY.md + WALKTHROUGH.md updated
- [ ] No regression in existing 309-test suite

## Risks we're accepting at MVS (from t-393 §12)

| # | Risk | Acceptance reason |
|---|---|---|
| R1 (concurrency) | Medium likelihood at N=2 | mtime+409 retry proven at N=1; flock deferred |
| R3 (Assembly backlog) | Low at N=2 with one Assembly | depth monitor via patrol is cheap; revisit at N=4 |
| R10 (stuck shutdown) | Low; I0 includes a 10-min tier-up | explicit timeout documented |

Risks R2 (conflicts), R4 (zombies), R5 (starvation), R9 (race) are
actively mitigated by I4/I6 and the forge-reset CLI.

## Open questions that block impl

These must be answered by Anvil before I0 enters the queue:

1. **Assembly: teammate vs CLI daemon?** Plan assumes teammate. Human
   call; plan adapts with ~0.5 heat delta either way (teammate has more
   context ceiling, CLI has simpler lifecycle).
2. **Squash-on-merge vs preserve per-heat commits?** Affects I4 only.
   Default: preserve, because the per-heat provenance is the whole point
   of heat-level budget accounting.
3. **N=2 or N=3 for first trial?** Recommend N=2. N=3 only after a week
   of stable N=2.

## Notes for Marshal (when you queue these)

- Do **not** auto-queue until Anvil approves.
- Keep the dependency graph; don't reorder without re-reading this plan.
- At each `TASK_COMPLETE`, verify the Integration checklist item is
  checked — don't just trust the commit.
- Budget guard: if the total impl slice exceeds 12 heats cumulatively
  (3 heats of overrun), stop and surface to Anvil for a re-plan.
