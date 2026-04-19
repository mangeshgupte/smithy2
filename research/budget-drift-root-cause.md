# budget.used vs worklog drift — root-cause diagnosis

**Task:** t-492 · 2026-04-19 · forge-anneal
**Status:** diagnostic (fix is a separate implementation task)

## TL;DR

There is **no drift**. The invariant patrol check #1 enforces —
`worklog row count == budget.used` — is **false by design** in the
Assembly era. Every submit→merge and submit→reject flow produces
**two** worklog rows while consuming **one** budget tick. A session with
N merges + M rejects has `worklog_rows = budget.used + N + M`.

The observed 2026-04-18 snapshot (1076 rows / 887 budget.used, delta
189) aligns with the ~108 Assembly second-rows that session plus a
small number of partial/blocked outliers. The 2026-04-19 snapshot used
in this research (1093 rows / 898 budget.used, delta 195) decomposes
exactly the same way.

Worse, patrol `--fix` and `sync-stages` both **inflate budget.used** up
to the worklog row count, which rewrites truth with the symptom and
gradually mis-reports how much of the budget Forge has actually burned.

Proposed fix is a two-line change (make the expected delta be
`count(worklog.outcome ∈ {merged, rejected, push_*, merged-with-resolution})`
instead of zero), landed as a follow-up implementation task.

## 1. Evidence

### 1.1 Row taxonomy (2026-04-19, `wc -l worklog.tsv` = 1094)

```
complete                820   — Forge end-heat (1 budget tick each)
partial                  29   — Forge end-heat (1 budget tick each)
submitted               123   — Forge end-heat (1 budget tick each)
blocked                  10   — Forge end-heat (1 budget tick each)
───────────────────────────
Forge end-heat total    982   ← expected value of budget.used
───────────────────────────
merged                   53   — Assembly second row, NO budget tick
rejected                 55   — Assembly second row, NO budget tick
other                     3   — push_ok / merged-with-resolution / …
───────────────────────────
Grand total            1093   ← what patrol reads
```

Current `state.budget.used` = **898**. Difference from the Forge-row
total of 982 is **84** — i.e., there are ~84 Forge heats whose
end-heat row landed but whose start-heat bump is missing from
`budget.used`. That's the *real* drift worth investigating (separate
issue; likely traced to `sync-stages --force-down` or a manual
state-edit event; see §5).

The 195-row gap patrol reports is the sum `84 (real drift) + 108
(Assembly second rows) + 3 (other two-row cases)`. **108 of 195 are
expected.**

### 1.2 Budget-tick writers (enumeration)

Only **one** code path mutates `state.budget.used`:

| Location | Action |
|---|---|
| `smithy/smithy/cli.py:488–489` (`start-heat`) | `heat_number = budget["used"] + 1; budget["used"] = heat_number` — atomic bump inside `state_lock` (t-426) |

All other writers that touch `budget` do not increment `used`.
`sync-stages` writes it with a monotonic-max (t-454); `patrol --fix`
writes it to the worklog count. Neither is "Forge consumed a heat"
arithmetic; both are reconciliation writes that currently have the
wrong target value.

### 1.3 Worklog-row writers (enumeration)

`smithy.smithy.state.append_worklog()` has three production callers
(excluding tests):

| Location | Context | Budget tick paired? |
|---|---|---|
| `cli.py:694` | `end-heat` (after optional Assembly submit) | Yes — bumped at `start-heat` for this heat |
| `cli.py:965–966` | `_do_assembly_merge` (flips `submitted → complete`) | **No** — same task_id, but Assembly adds a second worklog row and takes no budget |
| `cli.py:1027–1028` | `_do_assembly_reject` (flips `submitted → pending`) | **No** — same reason; also bumps `human_priority` but not budget |

So a typical Assembly-gated heat generates:

```
start-heat  →  budget.used ↑1
end-heat    →  worklog row ↑1  (outcome=submitted)
───── handoff to Assembly ─────
_do_assembly_merge OR _do_assembly_reject
            →  worklog row ↑1  (outcome=merged | rejected)
```

`assembly_tick` also writes to `assembly-log.jsonl` via `_log()` — a
different file and irrelevant to this analysis. No hidden fourth
worklog writer; `append_worklog` is imported only by cli.py.

### 1.4 Concurrency

The single budget-tick site is inside `state_lock(root)` (cli.py:467),
a file-lock over `state.json`. Assembly writes also take the lock
(via `load_state`/`save_state` which wrap their own critical sections).
**There is no race producing the drift** — the arithmetic is just
incorrect under the Assembly two-row contract.

## 2. Repro (minimal)

Fresh scaffold, one forge, assembly enabled:

```
budget.used=0, worklog=0
start-heat implementation --task t-1          → budget.used=1, worklog=0
end-heat 0.8 🟢 "x" --outcome complete        → budget.used=1, worklog=1
# invariant holds

start-heat implementation --task t-2          → budget.used=2, worklog=1
end-heat 0.8 🟢 "x" --outcome submitted       → budget.used=2, worklog=2
# still balanced; Assembly not yet run

assembly-tick (merge)                         → budget.used=2, worklog=3
# ←── drift detected by patrol, but correct behaviour: +1 worklog row for the merge
```

`test_sync_stages_from_worklog` and `test_stale_assembly_queue_*` in
`smithy/tests/test_smithy.py` already seed similar shapes — but they do
so with hand-written state, so they never trigger the merged/rejected
second-row path and the bug they would expose stays dormant.

## 3. Why t-454 didn't catch this

t-454 was written to fix a regression where `sync-stages` *decreased*
`budget.used` by reading a stale worktree-local worklog. The fix
(a) anchored worklog reads to the main repo and (b) added a monotonic
guard (`max(old, worklog_count)`). Both are correct fixes for the
regression they targeted.

But the t-454 guard **embeds the wrong invariant**: it assumes
`worklog_count == budget.used`. When that's violated by a normal
Assembly second-row (not by a stale-read), the guard doesn't protect —
it actively promotes the delta into `budget.used`, inflating it and
moving the system further from truth.

Run this sequence enough times and `budget.used` grows roughly in
step with `N_merges + N_rejects`, eating the available budget faster
than Forge actually consumes it. Over a 1543-heat total, a 108-row
inflation is ~7% "lost" budget — small today, problematic in any
longer session or a larger total.

## 4. Proposed fix

**Split across two tickets.** This research isn't the fix; filing a
follow-up is the deliverable.

### Ticket A — correct the patrol check (P1)

`cli.py:2965–2981` in `patrol`:

```python
# BEFORE
if worklog_heats != budget_used:
    issues.append(...)
    if fix and worklog_heats > budget_used:
        state["budget"]["used"] = worklog_heats   # wrong target

# AFTER
second_rows = _count_assembly_second_rows(wl_path)
expected = budget_used + second_rows
if worklog_heats != expected:
    delta = worklog_heats - expected
    issues.append(
        f"worklog has {worklog_heats} rows, expected "
        f"{expected} (= budget.used {budget_used} + {second_rows} "
        f"Assembly second-rows); delta {delta:+}"
    )
    # NO auto-fix upward — the delta now isolates real drift
    # (start-heats that didn't land end-heat rows, or vice-versa).
    # A real downward drift is a separate incident worth surfacing,
    # not silently rewriting.
```

`_count_assembly_second_rows` is a one-pass counter over the worklog
counting rows whose outcome is in the Assembly-only set:

```python
_ASSEMBLY_OUTCOMES = frozenset({
    "merged", "rejected", "merged-with-resolution",
    # Optional: push_ok/push_fail if `_log` ever switches target.
})
```

### Ticket B — correct `sync-stages --force-down` math (P2)

Same shape of change in `sync-stages` (cli.py:2936–2940): the
monotonic-max target should be `budget.used_floor = Forge row count`,
not `total_heats = all rows`. Concretely:

```python
forge_rows = total_heats - second_rows
state["budget"]["used"] = (
    forge_rows if force_down else max(old_used, forge_rows)
)
```

This preserves t-454's intent (never silently lose Forge heats) while
fixing the Assembly inflation.

### What NOT to do

- **Don't** add a budget tick inside `_do_assembly_merge` /
  `_do_assembly_reject`. A merge/reject is not a heat — Forge already
  paid the budget at submit time. Bumping here would double-charge.
- **Don't** split the worklog into two files. The single append-only
  tail is load-bearing for activity/attribution queries
  (`worklog_latest_per_task`, `activity.py`).
- **Don't** remove the Assembly second row. It's the audit trail for
  the submit→complete and submit→reject transitions and is consumed
  by at least `assembly-log.jsonl` ↔ worklog cross-references and the
  ini-019 backfill scripts.

## 5. Adjacent discovery — real drift is smaller than reported

After subtracting the 108 expected Assembly second-rows, the real
Forge-row vs budget.used delta is **84** (982 Forge rows vs 898
`budget.used`). Possible explanations to investigate in the follow-up
implementation ticket (out of scope here):

1. **Pre-t-426 race.** Before t-426's atomic bump inside the lock,
   two concurrent `start-heat`s could collide on `heat_number` and
   drop one of the two budget writes. The commit landed 2026-04-18;
   any drift predating it accumulates forever.
2. **`sync-stages --force-down` invocations.** If any operator ever
   ran `sync-stages --force-down` when worklog was temporarily shorter
   than budget (e.g., during the t-454 stale-read incident), budget
   would have been ratcheted DOWN and the heats that triggered the
   ratchet effectively disappeared.
3. **Manual state edits.** `state.json` is human-readable; historical
   incident responses (the MEMORY notes reference several) may have
   manually set `budget.used`.

These are hypotheses, not conclusions — testing them requires
git-log'ing `state.json` history, which this research pass didn't do.
Flag for the follow-up.

## 6. Deliverables

- **This doc** — diagnosis + proposed fixes.
- **Follow-up tickets to file:**
  - **Ticket A (P1):** patrol check #1 + sync-stages honor Assembly
    second-row semantics. Estimate: 1 implementation heat. Tests:
    (a) forge-only worklog → invariant holds; (b) forge + merge rows
    → invariant holds with expected delta; (c) artificially broken
    state → non-zero delta surfaced as issue (not silently fixed).
  - **Ticket B (P3):** git-log-based audit of `state.json` to
    reconstruct where the ~84 genuine missing budget ticks went.
    Mostly historical forensics; low urgency once Ticket A stops the
    inflation.

## 7. Files referenced

- `smithy/smithy/cli.py` — `start-heat` (480–509), `_do_assembly_merge`
  (lines ~930–985), `_do_assembly_reject` (lines ~1000–1040), `patrol`
  check #1 (2965–2981), `sync_stages` (2898–2952)
- `smithy/smithy/state.py` — `append_worklog` (471–504), `worklog_path`
  (85–…), `main_repo_root` (516–…)
- `worklog.tsv` (current main) — 1094 lines incl header
- `state.json` — `budget.used = 898`, `total_heats = 1543`
