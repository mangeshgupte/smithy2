# ini-020 — Batched-staging Assembly — Design Spec

**Status:** design complete (t-450, forge-quench, 2026-04-18)
**Revises:** the one-task-at-a-time tick model from t-399 I4.
**Depends on:** t-448 (Refinery research), t-449 (current-path inventory).
**Lands after:** ini-020 Phase 1 (already live — `ensure_staging_worktree`,
`rebase_task_branch`, `ff_merge_forge_branch(source_ref=…)`, `assembly_tick`
routed through staging per t-475).

## Intent

Keep the invariant that Forge never waits for Assembly; bundle N>1 submitted
branches into one merge-into-staging → test → ff-merge cycle. On a green
batch we land N commits with a single test run. On a red batch we bisect,
isolate the single breaker, reject it, and re-land the green subset.

## (a) Staging workspace layout

```
<main-repo>/
├── state.json                                     (shared, main-root canon)
├── worklog.tsv
├── .assembly-queue.jsonl                          (durable submit queue)
└── .worktrees/
    ├── forge-quench/                              (Forge cwd)
    ├── forge-temper/
    ├── forge-anneal/
    └── _assembly-staging/                         (Assembly's private)
        ├── .venv/                                 (uv, editable smithy)
        ├── smithy/  ...                           (same tree as main)
        └── <rebased per-task branches land here>
```

- `_assembly-staging/` is created on first tick by `ensure_staging_worktree`
  (already shipped). It starts detached at `main`; each batch resets it to
  current `main` before merging the batch's branches.
- `_assembly-staging/.venv/` is created the first time the batch run needs
  it (see (b)). Not tracked in git; lives entirely inside the worktree.

## (b) Venv lifecycle

States: `absent → fresh → reused`.

- **Create** on first tick that needs to run tests. Use `uv venv .venv` then
  `uv pip install -e ./smithy`.
- **Reuse** across ticks as long as `smithy/**` is unchanged between the
  previous batch's post-merge `main` tip and this batch's post-merge tip.
  (Hash the tree with `git ls-tree -r HEAD smithy/`.) Most heats don't
  touch `smithy/`, so the common case is reuse.
- **Recreate** when the hash changes. Blow away `.venv/`, re-run
  `uv venv` + `uv pip install -e ./smithy`. Bump `venv_recreate_count`.
- **Invariant**: no test run without a verified-fresh venv. If hash
  computation fails, recreate (conservative).

## (c) Batch window policy

The batcher decides whether to start a merge cycle.

```
depth = count_lines(.assembly-queue.jsonl)
n_forges = len(state.parallel.forges)

if depth >= 2:
    go()                # full batch
elif depth == 1:
    if idle_for_s >= 60:
        go()            # singleton fallback (the N=1 case)
    else:
        wait_tick()     # give siblings a chance to land
else:
    idle()              # queue empty
```

- `idle_for_s` resets when a new row is appended.
- N=1 fallback is a plain single-task merge: reset staging to main, merge
  the one ref, test, ff-merge. No bisect arithmetic.
- Back-pressure (t-442) keeps `depth ≤ 2 × n_forges`, so the batcher never
  chews through unbounded queues.

## (d) Merge-into-staging algorithm

```python
def run_batch(root, queue_entries):
    wt = ensure_staging_worktree(root)
    reset_staging_to_main(wt)                  # hard reset + clean
    merged = []                                # (entry, staging_ref, status)
    for entry in queue_entries:                # order = submit order
        res = cherry_apply(wt, entry.branch)   # see below
        if res.status == "clean":
            merged.append((entry, res.sha, "clean"))
            continue
        if res.status == "mild":
            auto_resolve(wt, res.files)
            merged.append((entry, res.sha, "mild"))
            continue
        # severe → single-task reject, keep batching the rest
        assembly_reject(entry, reason=res.detail)
        reset_staging_to(wt, sha=merged[-1].sha if merged else "main")
    return merged
```

- `cherry_apply` = `git merge --no-ff --no-edit <entry.branch>` **into the
  running tip** (not into fresh main each time). This preserves the
  rebase-linearity invariant from t-456's `rebase_task_branch` because
  every entry's branch was already rebased onto main during submit.
- "reset staging to last-good merge" on a severe conflict lets the batch
  continue past the bad actor without re-running the N-1 merges we
  already validated conflict-free.

## (e) Conflict classification

- **Trivial / auto-resolve** (post-t-399 classification, unchanged):
  `worklog.tsv` (append-only union), `state.json` (take main; Marshal's
  queue edits are the authority). Auto-resolve via `try_auto_resolve`.
- **Severe** (anything else): reject the single task — Marshal retries
  it after the offender is out of the batch. Never reject the whole
  batch.

## (f) Test invocation

```
uv run --project _assembly-staging python -m pytest -q \
    smithy/tests/ tests/
```

- Run inside staging's venv so smithy resolves to staging's editable
  install, not main's (t-460 hazard).
- Single run per batch, post-merge. Red test result triggers (h).
- Timeout: 10 min (same as today's `run_tests_in_worktree`).
- Output truncated to last 4k chars in the log stream.

## (g) On-green flow

1. `git -C <main-root> checkout main`
2. `git merge --no-ff --no-edit _merge-batch-<stamp>`
    — staging's tip is a linear chain of the N merges; this is a
    fast-forward-equivalent with one merge commit for the batch.
3. For each `(entry, sha, status)` in `merged`:
   - `_do_assembly_merge(root, entry.task_id, sha, resolution=(status=="mild"))`
   - append `merged` row to `assembly-log.jsonl`
   - delete the Forge's per-task branch (`-D`, matches t-475 pattern)
   - nudge Marshal with `ASSEMBLY_MERGED: <task_id>`
4. `git push origin main` (best-effort, t-438 semantics).
5. `.assembly-queue.jsonl.pop_n(len(merged))` — atomic rewrite.
6. Emit `assembly_batch_merged` rig-event with `batch_size=N`.

## (h) On-red flow (bisect)

```python
def bisect_batch(wt, merged):                   # merged in merge order
    # Binary-search on the N merge commits. The test shim is our
    # already-produced pytest result: it ran against the whole batch
    # and came back red. We now re-run it against progressively
    # smaller prefixes.
    bad = len(merged) - 1
    good = -1                                   # empty prefix always green
    while bad - good > 1:
        mid = (bad + good) // 2
        reset_staging_to(wt, sha=merged[mid].sha)
        if run_tests(wt).passed:
            good = mid
        else:
            bad = mid
    offender_entry = merged[bad].entry
    green_prefix   = merged[:bad]               # may be []
    return offender_entry, green_prefix
```

- Worst case: `ceil(log2(N)) + 1` extra pytest runs. For N=4 that's 3;
  for N=8 that's 4. A single run takes ~80s on this project today, so a
  red 4-batch costs ~4 min instead of the green path's 80s.
- `assembly_reject(offender_entry.task_id, reason="batch-bisect isolated")`.
- If `green_prefix` is non-empty, run the on-green flow on that prefix.
  The remaining post-offender entries stay in `.assembly-queue.jsonl` and
  get retried on the next tick (they'll re-batch without the offender).
- Emit `assembly_batch_bisect` rig-event with
  `batch_size=N`, `narrowed_to=1`, `green_landed=len(green_prefix)`.

## (i) Failure modes + rollback

- **Staging worktree missing** → `ensure_staging_worktree` recreates.
  No state to lose; staging is disposable.
- **Venv corrupt** (failed `uv pip install`, missing interpreter) →
  `rm -rf .venv` + recreate; `venv_recreate_count += 1`. If the second
  attempt fails, reject the batch with `venv_broken: <detail>` and
  alert Marshal.
- **Mid-batch error** (subprocess crash, OOM) → `git reset --hard main`
  on staging, drop the `_merge-batch-*` ref, leave the queue intact.
  Next tick re-batches from scratch.
- **`.assembly-queue.jsonl` stale rows** (Forge submitted, branch
  vanished) → drop the row during the validation pre-pass; the bad
  submitter is already orphaned, nothing to reject.
- **Push failure** (origin rejected, network) → merge already landed
  locally; push stays advisory (t-438). Surface under `result["push"]`
  and continue.

## (j) Metric hooks

Emit as rig-events; surface on `smithy stats` follow-up:

| key | when | meaning |
|---|---|---|
| `batch_size` | on batch start | how many entries went in |
| `batch_outcome` | on batch end | `green` \| `bisect` \| `aborted` |
| `bisect_invoked` | counter | number of batches needing bisect |
| `narrowed_to` | on bisect | always 1 in current design (the offender) |
| `green_landed_after_bisect` | on bisect | size of the green prefix merged |
| `venv_recreate_count` | counter | how often we rebuilt the venv |
| `batch_latency_ms` | on batch end | start-to-ff-merge wall time |
| `tests_runs_per_batch` | on batch end | 1 (green) or `1 + ceil(log2(N)) + 1` (bisect upper bound) |

## Follow-up tasks (not in this spec)

- Implement batcher + cycle (implementation ticket; est 2-3 heats).
- Implement bisect shim with retry-on-flaky (est 1 heat).
- Wire the metric hooks into `smithy stats` and the Bellows Assembly panel.
- Retire `rebase_forge_branch` once the CLI `assembly-rebase` subcommand
  is gone or redirected (legacy, marked in assembly.py docstring).
