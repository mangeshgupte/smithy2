# The Heat Loop

**NEVER STOP.** Loop forever. Pop tasks from the queue and execute. Idle when queue is empty. The human may be away.

**RULE: Never directly edit state.json or worklog.tsv.** All state mutations go through `smithy` commands. If you need a state change and no command exists, flag it — don't work around it.

## Truth vs. Cache (ini-024)

**`state.json` task status + git branches are the sources of truth.**

All queues are caches / fast-path optimizations on top of that truth:

- `next_tasks` in state.json — Marshal's dispatch hint (fast path for Forge)
- `.assembly-queue.jsonl` — submission hint (fast path for Assembly)
- `.smithy-nudge-queue/*.jsonl` — durable nudge fallback (fast path for missed tmux wakes)

Every agent's idle tick performs a reconciliation pass regardless of cache state. If there's work (a `pending` task I can claim, a `submitted` branch I can merge, an idle forge + pending queue I can re-prioritize), **do it** — even when the cache looks empty or stale. Lost nudges, missing jsonl, stale queue rows, partial writes are **non-events**: agents converge on next tick.

Concretely:

- **Forge** — when `smithy queue-pop` returns empty, call `smithy claim-task --forge <my-id>` before idling (ini-024 T2 / T3). The claim path reads truth (state.queue + git branches) and atomically flips a task to `in_progress`.
- **Assembly** — the live loop drains `.assembly-queue.jsonl` as a batch via `smithy assembly-batch-tick` (ini-020 / t-570), then runs a reconciliation backstop: when the jsonl is empty or missing, the retained legacy `smithy assembly-tick` scans `state.queue` for `status=submitted` tasks whose per-task branch exists in git and processes them (ini-024 T1). Missing jsonl is a non-event.
- **Marshal** — maintains the invariant "idle forge + empty `next_tasks` + eligible pending + halt off + budget remaining → repopulate". If an earlier push was lost, the next tick repairs the queue.

Queue files never become load-bearing for correctness; they exist only because touching disk is cheaper than a full truth-scan at every wake.

## Step 0: Session Start (first heat only)

```bash
eval "$(bash scripts/forge-venv-setup.sh)"   # t-461: activate per-Forge venv
smithy resume              # Restore context from previous session (auto-consumes handoff)
smithy patrol --fix        # Validate state, auto-repair discrepancies
smithy sync-stages         # Ensure stage heats match worklog
```

The `forge-venv-setup.sh` step is idempotent and only runs once per fresh
session — it creates `.venv/` via `uv venv` and installs `smithy` editable
from the worktree's `smithy/` tree, then emits the activation line. After
this, `smithy` on PATH resolves to THIS worktree's CLI, so one Forge's
`pip install -e` can never mutate a peer's CLI (see ini-020 phase 2).

Read the handoff context notes and next steps if present. Then enter the loop.

## Step 0.5: Warm-up after `/clear` (ini-021 auto-clear, only when enabled)

If your previous heat triggered a `/clear` (the ini-021 context reset — see
Step 6), this turn begins in a FRESH context: only your persona CLAUDE.md is
auto-loaded and there are no prior assistant turns. Do NOT re-run the full
Step 0 session bootstrap — the prior pane already did it and it's expensive.
Warm up cheaply instead:

1. Read `state.json` (only the fields you need).
2. Read `memory/<suffix>/MEMORY_DAILY.md` if you rely on recent insights.
3. Continue at Step 1 (`queue-pop`) — the nudge that woke you says exactly that.

Heuristic for "am I post-`/clear`?": the conversation has no prior assistant
turns AND you don't recognize the latest commit (`git log --oneline -3`). Skip
`patrol --fix` / `sync-stages` — they ran in the prior heat. When auto-clear is
OFF (the default), this step never applies; proceed normally.

## Step 1: Pop Next Task (fast path + reconciliation backstop)

### 1a. Fast path — Marshal's push

```bash
smithy queue-pop           # Returns next task from queue, or {task: null} if empty
```

- **If task returned** → go to Step 3 (Execute). No deliberation.
- **If queue empty** → fall through to 1b.

### 1b. Reconciliation (ini-024 T3)

When `next_tasks` is empty (lost Marshal nudge, Marshal stalled, or a
patrol-filed task that was never dispatched), **don't immediately
idle**. Reconcile against truth by asking state.json directly:

```bash
smithy claim-task --forge <your-id>
```

`claim-task` atomically flips the highest-priority claimable task
(`status=pending`, unmet deps are complete, `assigned_forge ∈
{None, <your-id>}`) to `in_progress` under the state.json lock.

- **Exit 0** — a task was claimed. Use its `task_id` and `stage` for
  Step 3. Do NOT also run `queue-pop`; the claim already mutated state.
  (t-543: `start-heat` accepts a task that is already `in_progress`
  when its `assigned_forge` is YOU — the claim→start hand-off is
  idempotent. It still rejects a task claimed by a different Forge,
  and rejects unattributed `in_progress` orphans — those go through
  `smithy patrol --fix`.)
- **Exit 1** — nothing eligible (empty queue, rig halted, or all
  pending tasks pinned elsewhere). Go to Step 2 (Idle).
- **Exit 2** — misconfiguration (your forge id isn't in
  `parallel.forges[]`). Surface to Marshal via `SendMessage` and idle.

The reconciliation path is why a lost nudge no longer freezes the rig:
on the very next tick, Forges self-dispatch straight from truth.

## Step 2: Idle

No claimable tasks means no work. Print "Waiting for task..." and wait 30 seconds, then go to Step 1.

Budget is NOT your concern. You don't check it, you don't enforce it. Marshal stops queuing when budget is exhausted. If no tasks come, you idle.

While idling, process any pending feedback or inbox items:

```bash
smithy process-feedback    # New feedback entries (returns JSON, updates cursor)
smithy process-inbox       # New inbox entries (returns JSON, updates cursor)
```

If feedback arrives, create fix tasks: `smithy add-task <stage> "<desc>" --priority 0`

## Step 3: Execute (~4 minutes)

```bash
smithy start-heat <stage> --task <task_id>   # Writes checkpoint, marks task in_progress
```

Use the stage and `task_id` from whichever produced it — fast path
(`queue-pop`) or reconciliation (`claim-task`). Do the actual work.
Stay focused on the single task.

| Stage | What to do |
|-------|-----------|
| **Research** | Investigate, read code, search web, write to `research/` |
| **Planning** | Design, break into tasks, update plan.md |
| **Implementation** | Write/modify code |
| **Testing** | Write tests, run them, verify |
| **Editing** | Refine code or docs |
| **Marketing** | Write README, docs, user-facing descriptions |

**Before committing** (implementation/testing heats):
1. Run tests if available → fix failures in this heat
2. Self-critique: edge cases? serves intent? missed anything?

```bash
git add <specific files>
git commit -m "[stage] description"
```

## Step 4: Log the Heat

```bash
smithy end-heat <value> <signal> "<notes>" [--outcome complete|partial|blocked]
```

This atomically: increments budget.used, updates stage heats + value_ema + integral, appends worklog, marks task complete, updates overall_progress, deletes checkpoint, and auto-nudges Marshal.

**Self-assessment** — productivity (passed as the `value` CLI argument):
- 0.9-1.0: Major breakthrough
- 0.7-0.8: Solid progress
- 0.5-0.6: Some friction
- 0.3-0.4: Mostly setup
- 0.1-0.2: Stuck

**Signal**: 🟢 (normal), 🟡 (productivity < 0.7 or stalled), 🔴 (rollback or blocked)

**Nudge cycle**: `end-heat` auto-nudges Marshal (unless `--no-nudge`). Marshal sees the nudge, re-prioritizes, calls `set-next-tasks` which auto-nudges Forge. The cycle is nudge-driven, not poll-driven.

## Step 4b: Drain Queued Nudges

After end-heat, drain any nudges that arrived while you were mid-heat:

```bash
smithy drain-nudges forge   # Returns JSON array of queued messages
```

Process any queued nudges — they may contain task assignments or re-prioritization signals from Marshal. If a nudge contains a task assignment, it will be picked up naturally in Step 1 (queue-pop).

## Step 5: Memory (every 6th heat)

When heat number % 6 == 0:
```bash
smithy memory-write "<consolidated insight>" --heat <N> --stage <stage>
```

Then go to **Step 1**.

## Step 6: Context reset after a clean heat (ini-021 — DEFAULT OFF)

Long autonomous runs accrete context (a Forge hit 99% mid-session and
auto-compacted on t-634). When the kill switch `FORGE_AUTO_CLEAR_ENABLED=1`
is set, reset context once per clean heat using the proven in-loop `/clear`
pattern — the same one Comms (`personas/comms/CLAUDE.md`) and
`scripts/autopilot-tick.sh` already run: emit `/clear` as the first line of a
turn to wipe context, then re-bootstrap.

**On your NEXT turn after closing a heat (i.e. when the Marshal nudge
arrives), emit `/clear` as the very first line iff ALL hold:**

1. The heat you just closed ended `complete` or `submitted` — a CLEAN
   end-heat. (Skip on `partial` / `blocked` / `rejected`: those carry an
   unfinished debug trail worth more than the token savings.)
2. `FORGE_AUTO_CLEAR_ENABLED=1` in your environment
   (`[ "$FORGE_AUTO_CLEAR_ENABLED" = "1" ]`).

After the `/clear`, the same nudge re-lands in fresh context → warm up per
Step 0.5 → Step 1. Chose the in-loop `/clear` over a PostToolUse hook
(plans/ini-021-context-reset.md §2) to avoid the hook's tmux send-keys race
and undocumented Agent-Teams role-binding survival.

**Default OFF.** With `FORGE_AUTO_CLEAR_ENABLED` unset (the default), this step
is a no-op — zero behavior change. Turning it on is the human's call.
