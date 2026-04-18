# t-454 — budget.used non-monotonic drift RCA

**Status:** initial findings only (heat 977 was preempted by t-470 retry directive — to be continued)
**Filed:** 2026-04-18
**Observed:** Anvil reconciled budget.used 892 → 903 at commit 64eedda; within ~24m, state.json showed used=824 (a 79-heat decrease without rollback).

## Top suspect: `smithy sync-stages` with stale worktree-local worklog

`sync-stages` (smithy/smithy/cli.py:2515-2553) does this:

```python
worklog_path = root / "worklog.tsv"          # ← root is ctx.obj["root"]
...
total_heats = len(lines) - 1
state["budget"]["used"] = total_heats        # ← absolute set, not max()
save_state(root, state)                      # state.json IS canonical to main (t-419)
```

`root` comes from `find_project_root` (state.py:48) which walks up from cwd
to the first `state.json`. From a worktree's cwd, that's the **worktree's**
state.json directory. So `root / "worklog.tsv"` is the worktree's local
worklog file — which can lag main if the Forge hasn't pulled.

`save_state(root, state)` then routes through `state_json_path` →
`main_repo_root` → writes to MAIN's state.json. Result: **MAIN's
budget.used gets overwritten with the worktree's stale worklog count.**

This matches the symptom exactly:
- Main worklog had 903 entries → reconciled to 903.
- forge-X's worktree had a copy at 824 entries (lagging).
- forge-X ran `sync-stages` from its worktree → wrote 824 → main's state.json.

## Why this is asymmetric to other anchors

t-419/t-422 anchored the *write* targets (state.json, .assembly-queue.jsonl,
nudge queues). But `sync-stages` *reads* worklog.tsv from `ctx.obj["root"]`,
which still resolves to the worktree's directory. The state.py docstring at
line 67 even claims "worklog.tsv was already anchored this way (t-409)" —
but that anchor only applies to *writes* (end-heat appends to MAIN's
worklog). Reads in sync-stages and patrol use the worktree path.

## Reproduction (hypothesized — to verify next heat)

```bash
# In a Forge worktree:
git fetch origin && git reset --hard origin/main~50    # rewind worklog by 50 entries
smithy sync-stages                                      # reads stale worklog
cat $MAIN_REPO/state.json | jq .budget.used             # ← dropped by 50
```

## Recommended fix (for next-heat write-up)

Two options, ordered by safety:

1. **Anchor the read.** In `sync-stages` and `patrol`, replace
   `root / "worklog.tsv"` with `worklog_path(root)` where
   `worklog_path()` = `main_repo_root(root) / "worklog.tsv"`. Same pattern
   as `state_json_path`. Smallest blast radius.

2. **Make `budget.used` monotonic.** In sync-stages: `state["budget"]["used"]
   = max(state["budget"]["used"], total_heats)`. Belt-and-suspenders
   against any other write path that might decrement. Trade-off:
   legitimate downward reconciles (rare) require a `--force` flag.

Recommendation: do both. (1) is the structural fix; (2) is a guardrail
against the next variant of this bug.

## Other suspects (not yet investigated)

- (b) Stale Forge worktree writeback despite t-419 — unlikely; t-419 wrote
  via `state_json_path` so all writes target MAIN. But worth grepping
  `save_state` callers that bypass it.
- (c) `patrol --fix` reversing reconcile — possible. patrol check #1
  (cli.py:2566-2576) sets `budget.used = worklog_heats` from
  `root / "worklog.tsv"` — same worktree-read bug as sync-stages.
- (d) Marshal cached value — needs Marshal pane log inspection. Lower
  prior given (a) and (c) are sufficient explanations.

## Next-heat tasks

- Verify reproduction on a sandbox repo.
- Grep all `root / "worklog.tsv"` reads — every one is a candidate for the
  drift bug. Likely need one helper `worklog_path()` + replace at all sites.
- Write the patch + tests (hp-bumped task for ini-019 follow-up).
