# ini-020 R2 — Current Assembly merge path (annotated inventory)

**Task:** t-449 · research heat 976 · 2026-04-18 · forge-anneal

Captures the end-to-end path a *submitted* per-task branch travels from
Forge → Assembly → `main` today, so ini-020 batching can slot in with
surgical precision. All line refs are against the MAIN repo
(`/Users/mangesh/vibes/smithy2/smithy/smithy/...`) at the time of this
heat — my worktree's copy is stale by design (Assembly hasn't merged
forge-anneal yet).

## 1. Files in play

| Purpose | Path |
|---|---|
| Assembly git primitives (rebase, merge, auto-resolve) | `smithy/smithy/assembly.py` |
| Assembly CLI + orchestration (`assembly-tick`, `_do_assembly_merge/reject`) | `smithy/smithy/cli.py` |
| Canonical queue path helpers | `smithy/smithy/state.py` |
| Assembly persona (operator, not mechanism) | `personas/assembly/CLAUDE.md` + `IDENTITY.md` |
| Append-only queue | `.assembly-queue.jsonl` (MAIN repo root) |
| Append-only audit log | `assembly-log.jsonl` (MAIN repo root) |

Everything is anchored to the MAIN repo root via `main_repo_root(...)` —
worktree-local copies of these paths are bugs (t-419 / t-422 incident).

## 2. Flow overview

```
Forge: end-heat (outcome→submitted)
   └── cli.py:685-705   append row to .assembly-queue.jsonl
        {forge_id, task_id, heat, branch, sha, submitted_at}
   └── cli.py:744-754   nudge Assembly pane ("ASSEMBLY_QUEUE: ...")

Assembly pane (human-free, nudge-driven):
   smithy assembly-tick            # drain ONE entry end-to-end
   └── cli.py:1013-1145   assembly_tick_cmd — the full pipeline
       (1) rebase forge-id/task-id onto main        assembly.py:43-122
       (2) if conflict: try_auto_resolve            assembly.py:339-366
              MILD = {worklog.tsv, state.json}      assembly.py:285
              SEVERE  → reject                       cli.py:1076-1088
       (3) pytest in forge worktree                 assembly.py:149-160
              red → reject                           cli.py:1103-1108
       (4) merge --no-ff into main, delete branch   assembly.py:163-226
              + advisory `git push origin main`    assembly.py:201-225
       (5) _do_assembly_merge  → state flip        cli.py:924-953
              worklog row (merged/✅) + rebind      cli.py:946-951
       (6) nudge Marshal (ASSEMBLY_MERGED: ...)     cli.py:1135-1138
       (7) _pop_queue → remove entry from JSONL    cli.py:1160-1164

   Re-invoke until `{"status": "empty"}`, then
   smithy assembly-heartbeat                        cli.py:345-360
```

One tick drains one entry. Persona CLAUDE.md codifies the loop-until-empty
drain cadence (`personas/assembly/CLAUDE.md:73-87`).

## 3. Phase-by-phase annotation

### 3.1 Submit (writer side, inside end-heat)

`cli.py:684-705` — runs only when `effective_outcome == "submitted"`
(i.e. `assembly.enabled` is true AND outcome was `complete`). Uses the
**Forge's worktree** cwd to read HEAD/branch, not the main repo. Appends
one JSON line to `assembly_queue_path(root)` (`state.py:73-82`, always
`<main>/.assembly-queue.jsonl`).

`cli.py:744-754` — directly after, nudges the Assembly pane via
`_nudge_persona("assembly", ...)` and emits an `assembly_nudged`
rig-events row. No Marshal nudge override here — Marshal gets the
HEAT_DONE nudge regardless (`cli.py:738-739`).

Entry shape:

```json
{"forge_id": "...", "task_id": "t-XXX", "heat": N,
 "branch": "<forge-id>/t-XXX", "sha": "…", "submitted_at": "…"}
```

### 3.2 Drain entry point — `assembly-tick`

`cli.py:1013-1046` — reads the **first** line of the JSONL (FIFO), parses,
reserves `rest = lines[1:]` so a successful tick can rewrite only after
all steps finish. In `--dry-run`, emits `would_process` and exits without
touching anything (`cli.py:1043-1046`).

Telemetry: `assembly_tick_begin` emitted before work
(`cli.py:1053-1055`); terminal event is `assembly_tick_merged` or
`assembly_tick_rejected` with `latency_ms` (`cli.py:1066-1068`,
`cli.py:1140-1143`).

### 3.3 Rebase

`assembly.py:43-122` — `rebase_forge_branch(root, forge_id, task_id,
base="main")`.

- **t-456:** must explicitly `git checkout <forge-id>/<task-id>` before
  rebasing. Prior behaviour rebased whatever the worktree currently had
  checked out and collided when the Forge had already moved on to a new
  task.
- **t-464:** unconditionally stashes dirty worktree state (not only when
  switching branches) — `state-sync.sh` routinely mutates `state.json` in
  the Forge's worktree so every on-target rebase was dirty on 2026-04-18
  (ini-020 motivator #1: Forge and Assembly co-writing the same worktree
  is structurally fragile).
- Returns `{"status": "clean" | "conflict" | "error", [files], [stash_ref]}`.

`conflicted_files(wt)` at `assembly.py:288-293` — grep for `UU/AA/DU/UD/AU/UA`
porcelain prefixes.

### 3.4 Auto-resolve (mild conflicts only)

`assembly.py:339-366` — `try_auto_resolve`.

- `_MILD_PATHS = {"worklog.tsv", "state.json"}` (`assembly.py:285`).
- Any file outside that set → immediate `{"status": "severe"}` and the
  tick rejects (`cli.py:1077-1078`, `1084-1087`).
- `worklog.tsv` resolver (`assembly.py:296-327`): union of `ours + theirs`
  rows, preserving the append-only discipline.
- `state.json` resolver (`assembly.py:330-336`): take `--theirs` (main
  wins; Marshal's queue is authoritative, branch-local runtime mutations
  are treated as ephemeral).
- Loop in `cli.py:1082-1090` handles the case where `continue_rebase`
  surfaces *another* conflict on the next picked-up commit — re-runs
  `try_auto_resolve` each time; breaks on `"nothing"`, rejects on
  `"severe"`.

### 3.5 Test gate

`assembly.py:149-160` — `run_tests_in_worktree`. Default command
`["python3", "-m", "pytest", "-q"]`; `--tests-cmd` override available.
600-second timeout. Reads cwd = Forge's worktree (critical: tests run
against rebased branch, which pulls the current `smithy/` package from
*that* worktree's `.venv` after t-461).

Red test ⇒ reject with last 3 output lines as the reason
(`cli.py:1103-1108`). Note: the rebase isn't aborted — the branch is
already linear, so the reject just leaves the worktree on the new base
and a follow-up heat can re-run.

### 3.6 Merge

`assembly.py:163-226` — `ff_merge_forge_branch`.

- `git checkout <base>` in the MAIN repo (`cli.py` passes `root`).
- `git merge --no-ff --no-edit -m "[assembly] merge <branch> → <base>"`.
  Readable final stamp even though the branch is already linear.
- Success path:
  - `delete_forge_branch` (`assembly.py:229-276`) — `-d` on success,
    restores Forge worktree to `<forge-id>/scratch` if the branch was
    checked out there (otherwise `git branch -d` fails with "used by
    worktree").
  - **Advisory push** (`assembly.py:201-225`) — best-effort
    `git push origin main`, 30s timeout, **never fails the merge**;
    outcome lands in `result["push"]` for downstream logging. Added
    t-438 because origin drifted 144 commits unpushed on 2026-04-18.

### 3.7 Post-merge state flip

`cli.py:924-953` — `_do_assembly_merge`.

- Reads `state.queue`, verifies task status is `submitted` (else error
  returned; caller doesn't currently check this — potential gap).
- Flips `status: submitted → complete`, clears `human_priority` and
  `priority_reason`.
- Appends the **second** worklog row (the first was written at
  end-heat with `submitted`). Outcome = `merged` or
  `merged-with-resolution`; signal = `✅` / `🔀`; stage coerced to
  `implementation`.
- `_rebind_smithy_install` (`cli.py:946-951`, t-460): best-effort rebind
  of the global editable `smithy` install to the just-merged main, so
  any pane that still uses the global python (Assembly's own pane, pre
  t-461 panes) sees fresh code. Best-effort, failures silent.

Nudges Marshal with `ASSEMBLY_MERGED: t-XXX merged on main
(sha=...). Re-prioritize downstream.` — fired on BOTH the live tmux
pane (`_nudge_persona`) and the durable file queue (`_queue_nudge`,
t-424) so a sleeping Marshal still picks it up.

### 3.8 Reject path

`cli.py:968-1010` — `_do_assembly_reject`.

- Verifies `status == "submitted"`; flips to `pending`.
- `human_priority += 5` with `normalize_human_priority` coercion
  (t-455 fix for `"p1"`-style strings that used to crash here).
- `priority_reason = f"assembly rejected: {reason}"[:40]`.
- Second worklog row: outcome=`rejected`, signal=`🚫`.
- Nudges **Marshal only** (design contract in
  `personas/assembly/CLAUDE.md:30-34`): route scheduling decisions
  through Marshal — never directly to the Forge. Both live tmux
  (`_nudge_persona`) and durable file queue (`_queue_nudge`).
- `assembly_tick._reject` wraps this with `abort_rebase` + `_log`
  + `_pop_queue` + telemetry (`cli.py:1061-1069`).

### 3.9 Pop + audit log

`_pop_queue(qpath, rest)` (`cli.py:1160-1164`): if `rest` is non-empty,
rewrites the whole file; otherwise `unlink(missing_ok=True)`. Called
**after** the merge/reject has successfully recorded — the queue row
is the last thing removed, so a crash mid-tick leaves the item for
the next tick.

`_log(root, forge_id, task_id, outcome, detail)` (`cli.py:1148-1157`):
append-only JSONL audit row `{ts, forge_id, task_id, outcome,
detail}`. Outcomes seen: `merged`, `rejected`, `push_ok`, `push_failed`.

Patrol check #9 (`cli.py:1868-1939`) reads queue + log and flags
entries > 300s old with no matching `rejected` row — the "Assembly
silently stuck" detector.

## 4. state.json interactions

| Caller | Writes | When |
|---|---|---|
| Forge `end-heat` | `queue[t].status = "submitted"`, `budget.used++`, stages, value_ema, allocator integral, `overall_progress` | Every heat |
| `_do_assembly_merge` | `queue[t].status = "complete"`, clears human_priority/reason | On merge |
| `_do_assembly_reject` | `queue[t].status = "pending"`, human_priority += 5, priority_reason | On reject |
| `assembly-heartbeat` | `parallel.assembly.last_heartbeat` | Every drain cycle |

Assembly itself (git ops) does **not** touch state.json — only the post-ops
helpers do, and each does a tight load → mutate → save at
`cli.py:925/939`, `cli.py:969/992`. The mild auto-resolve picks main's
version when state.json collides (§3.4) so branch-local state mutations
are deliberately lost.

## 5. Nudge routing

| Event | Target | Why |
|---|---|---|
| `ASSEMBLY_QUEUE` (end-heat submit) | Assembly pane | Wake drainer |
| `ASSEMBLY_MERGED` | Marshal | `blocked_by` may have opened |
| `ASSEMBLY_REJECTED` | Marshal (NOT Forge) | Scheduling owns reassign/split/deprioritize |
| `HEAT_DONE` | Marshal | Independent of Assembly, always fires |

Both Marshal-bound assembly nudges double-fire (live `_nudge_persona`
+ durable `_queue_nudge`) so an offline Marshal still sees them on
drain. The forge reject-back path codified in `parallel-forges-design.md`
as "Assembly nudges Forge on conflict" is superseded — current code
routes *everything* rejection-side through Marshal.

## 6. Where ini-020 batching slots in

The `assembly-tick` pipeline (`cli.py:1020-1145`) is the entry point,
but the **hardcoded single-branch rebase + single-worktree test run**
is what forces one-at-a-time cadence:

- `rebase_forge_branch` operates on the *Forge's* worktree
  (`_worktree(project_dir, forge_id)` at `assembly.py:25-26`).
- `run_tests_in_worktree` runs pytest in that same Forge worktree.
- `ff_merge_forge_branch` checks out `base` in `project_dir` (= MAIN
  repo), merges a single per-task branch.

Two structural changes ini-020 needs:

1. **Staging-worktree dedicated to Assembly** (`.worktrees/_assembly-staging`).
   - Replace `_worktree(project_dir, forge_id)` in the rebase/test path
     with a staging-worktree resolver. Forge worktrees become read-only
     from Assembly's POV; the t-464 stash hack stops being necessary.
   - New primitive: `stage_branches(project_dir, staging_wt,
     branches=[...])` that resets staging to `main` then `git merge`s
     each per-task branch into it in order.
2. **Batch test → merge**. One `run_tests_in_worktree` call on the
   staging worktree covers N branches. On green, `ff_merge_forge_branch`
   moves the *staging branch* (or a sequence of --no-ff merges) into
   main. On red, bisect across the N branches to isolate the breaker
   and reject only that one.

Touch points in this file (approximate, subject to R3 planning):

- **New helper** — `stage_branches` and a batched `try_auto_resolve`
  loop in `assembly.py` (right below `_MILD_PATHS`).
- **Assembly-tick becomes a batch drainer**:
  `cli.py:1036-1046` — read ALL lines (not just `lines[0]`), batch-cap
  by a new `--batch-size` flag.
- **Pytest gate** — keep `run_tests_in_worktree` but point at staging
  worktree.
- **Merge** — either replace `ff_merge_forge_branch` with an
  `ff_merge_staging` that rolls N per-task merge commits onto main as
  one atomic push, or keep ff_merge_forge_branch per branch and just
  amortize the pytest cost (simpler R3 option; decide there).
- **Reject bisect** — new helper; the single-branch reject path
  (`cli.py:1061-1069`, `_do_assembly_reject`) still applies to the
  isolated breaker.
- **Audit log** — `_log` gets a new `batch_id` field so humans can tell
  which merges were co-tested.

Non-touched by ini-020 R3 (per initiative description):
`MEMORY.md` collisions (orthogonal, tracked as t-458 and the
`feedback_no_persona_memory_commits.md` memory).

## 7. Open questions for R3 planning (not answered here)

1. Order-dependence — if branch B was built atop branch A's state and
   Assembly stages A before B, does `state.json → take main` still
   work? Probably yes (state is runtime, code is what tests exercise),
   but needs a concrete counter-example.
2. Test runtime — current single-branch pytest is ~X seconds
   (unmeasured in this heat). Batch amortization only pays if
   N * single-run ≫ one batch-run. Needs a timing sweep.
3. Bisect granularity — binary across N or linear drop-one? log2(N) vs
   N/2 average; implementation cost differs.
4. Advisory push cadence — current code pushes every merge
   (`assembly.py:201-225`). Batch means one push per batch; fine, but
   ensure `result["push"]` shape carries over.

These are inputs for the R3 task; R2's output (this doc) is the
annotated map.
