# Parallel Forges — Design

**Task:** t-393 (ini-018, research) · heat 806 · 2026-04-12

## Problem statement

Today The Forge is a singleton: one Forge session, one heat at a time,
linearized through `state.queue`. We want to run **N parallel Forges** so
independent tasks can progress concurrently. MVP target: N=2.

This doc captures the mechanics, schema, and risks. Gas Town has prior art
for parallel autonomous agents; citations below steal what applies and note
what we'd need to re-invent.

## 1. Gas Town prior art (citations)

From `research/gas-town-autonomy-memory-gap.md`, `research/gas-town-comms-mapping.md`,
`research/gas-town-extension-points.md`:

| Concept | Gas Town shape | Applicability |
|---|---|---|
| **Polecats** | Three-layer entity: Identity (Dolt bead + CV + mailbox) / Sandbox (persistent git worktree at `~/gt/<rig>/polecats/<name>/`) / Session (ephemeral) | Maps directly to our Forges: stable identity, persistent worktree, ephemeral session context. |
| **max_polecats back-pressure** | Scheduler-level capacity cap on concurrent polecats | Maps to `state.parallel.max_forges`. |
| **Four lifecycle states** | Working / Idle / Stuck / Zombie (polled) | Maps to per-Forge `status` field; Stuck + Zombie need the Witness (t-386). |
| **Refinery / Assembly** | "Automated PR management with conflict resolution" as first-class subsystem | We need an equivalent: Assembly teammate (§4). |
| **Witness** | Observer role; replaces Anvil as coordinator; directive "discover, don't track" — patrol by scanning state, not reading dispatch files | Directly reusable; aligns with t-386 patrol-based witness recommendation. |
| **GUPP** | "If hooked, you run it" — no confirmation, no serialization in Gas Town | Applies per-Forge; no mutual exclusion needed since Marshal assigns distinct tasks to distinct Forges. |
| **Handoff protocol** | Message-passing solves session cycling | Reusable for crash recovery per Forge. |
| **Formula topological sort** | Tasks can have dependencies, fan-out/join patterns are expected | Our `blocked_by` is the same primitive; Marshal must respect it when dispatching across N Forges. |

**Gaps in Gas Town docs we have to fill ourselves:** merge-queue cadence,
conflict policy, shutdown/quiesce, crew role hierarchy. Not solved upstream.

## 2. Worktree layout

```
smithy2/                              # lead worktree (main branch)
├── .worktrees/
│   ├── forge-01/                     # forge-01's persistent worktree
│   │   └── ...all repo files...
│   └── forge-02/
│       └── ...
├── state.json                        # SHARED (see §6 for concurrency)
├── worklog.tsv                       # SHARED — append-only, all Forges write
├── .forge-01-checkpoint.json         # per-Forge checkpoint (renamed from singleton)
├── .forge-02-checkpoint.json
├── .smithy-nudge-queue/
│   ├── forge-01.jsonl                # per-Forge nudge queue
│   ├── forge-02.jsonl
│   └── marshal.jsonl
└── ...
```

**Shared vs. per-worktree decision:**
- `state.json` — **shared**, single source of truth for queue/assignment/budget.
- `worklog.tsv` — **shared**, append-only. Concurrent appends are safe with
  `O_APPEND` flag; POSIX guarantees atomicity for writes <PIPE_BUF.
- Git repo `.git` — **shared** (worktrees are the standard mechanism); each
  Forge has its own branch checked out.
- `intents.json`, `identity.md`, `STRATEGY.md` — shared, read-only during heats.
- Checkpoints + nudge queues — **per-Forge** (namespaced by ID).

## 3. Branch strategy + merge cadence

**Recommendation: per-heat branch, merged at end-heat.** Branch naming:
`forge-NN/h<heat>-<task-id>`.

| Option | Pro | Con | Verdict |
|---|---|---|---|
| Per-heat branches, merge at end-heat | Small diffs; easy rollback of one heat; clear provenance | N+1 merges/day per Forge; may pile up if Assembly is slow | ✅ |
| Per-session branches, merge at session end | Fewer merges | One broken heat rolls back the whole session; long-lived divergence | ❌ |
| Everyone on main, rebase before commit | No merge layer | Guaranteed conflicts at N≥2; rebase-dance eats budget | ❌ |

End-heat flow (per Forge): commit on its branch → push/refpath → append a
row to `.assembly-queue.jsonl` saying `heat done, ready for merge`. Assembly
picks up from there (§4).

## 4. Assembly role (new teammate)

**Assembly is a teammate, spawned like Marshal and Forge.** Duties per cycle:

1. Drain `.assembly-queue.jsonl` for ready heats.
2. For each in FIFO order:
   - `git rebase main` on the Forge's branch.
   - **Conflict policy:** abort rebase; notify that Forge; mark heat as
     `assembly_blocked` in state.json; log to steering. Forge must resolve in
     the next heat or skip. Never auto-resolve.
   - Run `python3 -m pytest -q`. On fail: reject, mark `assembly_failed`,
     notify Forge and Marshal.
   - On pass: `git merge --ff-only` into main.
3. On merge success: append to `worklog.tsv` an `outcome=merged` row with the
   merge sha; nudge Marshal (queue may have opened up on unmet `blocked_by`).

Lifecycle: Assembly runs its own loop, similar cadence to Marshal. Idle
drain cycle every 30s; wakes on explicit nudge. One Assembly is sufficient
for N≤~8 Forges; beyond that, investigate parallel Assemblys with a
branch-space partitioning scheme.

## 5. Marshal dispatch across N Forges

Schema diff to `state.json`:

```jsonc
{
  "parallel": {
    "max_forges": 2,
    "forges": [
      {"id": "forge-01", "status": "working",
       "current_task": "t-393", "current_heat": 806,
       "started_at": "2026-04-12T14:52:00Z",
       "last_heartbeat": "2026-04-12T14:55:30Z"},
      {"id": "forge-02", "status": "idle",
       "current_task": null, "current_heat": null,
       "started_at": null, "last_heartbeat": "2026-04-12T14:53:10Z"}
    ]
  },
  "queue": [
    {"id": "t-400", "...": "...",
     "assigned_forge": null},        // NEW: null = unassigned, else forge id
    {"id": "t-401", "...": "...",
     "assigned_forge": "forge-01"}
  ]
}
```

**Assignment algorithm (Marshal):** rank tasks via existing scheduler_key,
then walk top-of-queue down; skip any task whose `blocked_by` overlaps with
another Forge's `current_task`-and-its-dependents; assign to the first idle
Forge. Respects `blocked_by` transitively. Per-forge `queue-pop` still reads
the same state but filters on `assigned_forge == self.id`.

## 6. state.json concurrency

Existing `_save_state_checked(state, mtime)` uses mtime precondition and
raises 409 on mismatch (t-307, t-316). For N=2–4 this is almost certainly
sufficient: collisions happen only when two Forges end heats within
milliseconds of each other, and the retry (reload + re-apply + save) will
succeed on the second try 99%+ of the time.

**For N≥5 or when Assembly is also a writer:** add a small advisory lock
using `fcntl.flock(LOCK_EX)` wrapped around the read-modify-write in
`_save_state_checked`. Still a flat-file mechanism; no new dependency.

Recommendation: **ship N=2 with 409+retry; revisit lock at N=4+**. Write a
retry-loop test that hammers state.json from 4 threads and confirms no
lost updates.

## 7. Nudge cycle at N

- **Forge → Marshal**: per-Forge file (`marshal.jsonl` already exists; add
  `sender` field to each line so Marshal knows which Forge is reporting).
- **Marshal → Forge**: per-Forge file (`forge-NN.jsonl`). Targeted, not
  broadcast — each Forge only processes its own queue.
- **Broadcast** (`to: "*"`): reserved for genuine all-hands signals (budget
  exhausted, shutdown, human override). Rare.

**Witness becomes critical** at N≥2. Detection surface expands: any Forge
can stall independently; Assembly can stall; Marshal can deadlock trying to
assign around a `blocked_by` graph. The witness-patrol design from t-386
ports directly but needs a per-Forge stuck-state check (6 predicates
applied per Forge).

## 8. Failure modes + reset-one-forge procedure

| Mode | Detection | Recovery |
|---|---|---|
| Single Forge session crash (zombie) | checkpoint exists, last_heartbeat > 15 min | Witness tier-1: respawn the Forge; tier-2: `smithy forge-reset forge-NN` clears checkpoint + marks task back to `pending` + clears `assigned_forge`. |
| All Forges stuck | §5's stuck detector per Forge × N | Witness tier-3: alert human. |
| Assembly stuck | `.assembly-queue.jsonl` backlog > 3 OR last Assembly heartbeat > 10 min | Respawn Assembly; queue survives in file. |
| Merge conflict loop (same branch rebased repeatedly) | `assembly_blocked` count > 2 for one task | Reject task: mark `status=assembly_rejected`, require human review. |
| `blocked_by` starvation (Forge B waits on Forge A who is stuck) | Assignment algorithm detects orphan waiter | Witness re-assigns A's task to another idle Forge or resets it. |

`smithy forge-reset <id>` (new CLI command): atomic procedure — delete
checkpoint → set `parallel.forges[N].status = "idle"` → clear
`current_task` / `current_heat` → for task assigned to that Forge, set
`assigned_forge = null` and `status = "pending"` → log to steering.

## 9. MVS (N=2 first)

Minimum viable slice:

1. Add `parallel` schema block to state.json (N=1 initially, no behavior change).
2. Add `assigned_forge` field to queue entries; Marshal respects it.
3. Rename checkpoint + nudge queue files to be Forge-ID-namespaced.
4. Git worktree scaffolding: `smithy forge-spawn <id>` CLI creates
   `.worktrees/forge-NN/` and registers in state.
5. Assembly teammate: new persona + spawn from Anvil; simplest possible
   merge loop (no parallel Assembly yet).
6. Marshal dispatch update: handle N=1 then N=2.
7. Tests: two-forge dry run on a sandbox state, verify no lost updates.

**Explicitly deferred from MVS:** advisory locks, parallel Assembly,
blocked_by-transitive starvation detector, N>2 scaling.

## 10. Shutdown analysis — what must freeze

Ordered shutdown (pause-the-world, not kill-the-world):

1. **Freeze Marshal dispatch**: `state.parallel.halt = true`. Marshal sees
   this on next wake and stops assigning new tasks.
2. **Drain in-flight heats**: each Forge completes its current heat normally.
   No force-kill; any running heat commits, ends, and then idles.
3. **Drain Assembly**: process all pending merges. After its queue is
   empty, Assembly idles.
4. **Verify**: all `parallel.forges[].status == "idle"`; `.assembly-queue.jsonl`
   empty.
5. **Persist shutdown sentinel**: write a `.shutdown.json` with timestamp +
   reason + final Forge IDs. Restart reads this and knows to rehydrate.

Hard-kill (crash or human aborts): Witness on next start detects checkpoints
of dead sessions, marks them `zombie`, runs `forge-reset` per §8. Worklog
is append-only so history is intact; in-flight git branches remain on disk
and can be recovered manually if needed.

## 11. ASCII sequence diagram (N=2, happy path)

```
           Anvil       Marshal       Forge-01      Forge-02      Assembly
             │            │              │             │             │
 start ─────►│            │              │             │             │
             │─spawn─────►│              │             │             │
             │─spawn──────┼─────────────►│             │             │
             │─spawn──────┼──────────────┼────────────►│             │
             │─spawn──────┼──────────────┼─────────────┼────────────►│
             │            │              │             │             │
             │            │─assign t-A──►│             │             │
             │            │─assign t-B───┼────────────►│             │
             │            │              │─do work─    │─do work─   │
             │            │              │─ commit ────┼─ commit ────┼──►
             │            │              │ end-heat    │ end-heat    │
             │            │              │─nudge──────►│             │
             │            │◄─nudge──────┼─────────────┼────────┬────┤
             │            │              │             │        │    │
             │            │              │             │        │rebase t-A
             │            │              │             │        │pytest
             │            │              │             │        │ff-merge
             │            │◄─merged t-A─┼─────────────┼────────┤    │
             │            │              │             │        │rebase t-B
             │            │              │             │        │pytest
             │            │              │             │        │ff-merge
             │            │◄─merged t-B─┼─────────────┼────────┘    │
             │            │─reassign t-C─►             │             │
             │            │─reassign t-D─┼────────────►│             │
             │            │   (…loop…)   │             │             │
```

## 12. Risk table

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | state.json lost update under concurrent writes | Medium | High | §6 mtime+409 retry; add fcntl lock at N≥4 |
| R2 | Merge conflicts eat budget (rebase dance) | High at N=2 | Medium | §4 abort-on-conflict + human review gate; never auto-resolve |
| R3 | Assembly backlog grows unboundedly | Low | High | §8 monitor queue depth; respawn; consider parallel Assemblys |
| R4 | Zombie Forge checkpoint blocks reassignment | Medium | High | Witness heartbeat + `forge-reset` |
| R5 | `blocked_by` starvation (A stuck, B waits) | Medium | Medium | Witness detects waiter; reset or reassign A's task |
| R6 | Nudge queue growth from broadcast spam | Low | Low | Per-forge nudge queues (§7); broadcast only on signals |
| R7 | Budget accounting drift across N Forges | Medium | Medium | `smithy patrol --fix` already reconciles against worklog; extend to per-forge stats |
| R8 | Anvil can't tell which Forge did what | High initially | Low | Commit subject includes forge id: `[implementation][forge-01] t-XXX:…` |
| R9 | Forge picks up task already merged (race) | Medium | Medium | `assigned_forge` nulls only on successful merge; Marshal checks before assigning |
| R10 | Graceful shutdown takes too long (stuck heat) | Low | Medium | §10 timeout: tier-up to forge-reset after 10 min of halt+unresponsive |

## Open questions for Anvil

1. **Assembly: teammate agent or CLI tool?** Design above assumes a teammate.
   An alternative is a pure CLI daemon (no LLM context) that just runs
   rebase/pytest/merge. Cheaper, but loses the ability to write useful
   commit messages or escalate intelligently. My lean: teammate for MVS.
2. **Per-heat branch is verbose.** Consider squashing on merge (`--squash`)
   to keep main's log clean. Tradeoff: lose the per-heat granular provenance.
3. **N=2 or N=3 for MVS?** N=2 exposes concurrency bugs; N=3 exposes
   assignment-fairness bugs. Start at 2; scale once stable.

## Recommended implementation slice (3-5 heats)

- C1 (~1h): schema + per-Forge checkpoint/nudge namespacing (no behavior change at N=1).
- C2 (~1h): `smithy forge-spawn` + `forge-reset` CLI; Assembly persona
  scaffolding (empty loop).
- C3 (~1h): Assembly merge loop (rebase → pytest → ff-merge → log).
- C4 (~1h): Marshal dispatch update + first N=2 dry run.
- C5 (~1h): Two-forge sandbox tests; stuck-state detection per Forge.
