# Ghost-Branch Reconciliation (patrol check #19) — t-584

**Date:** 2026-06-19 · **Forge:** forge-anneal · **Heat:** 1368

Reconciles the ghost-complete `forge-<id>/t-XXX` branches flagged by patrol
check #19. All listed tasks are `status=complete`, so this is **branch-cruft
cleanup + false-complete DETECTION**, not status correction.

## TL;DR / counts

| disposition | count | branches |
|---|---|---|
| **pruned** (confirmed landed in main) | **5** | temper/t-445, quench/t-450, anneal/t-537, quench/t-537, temper/t-537 |
| **🚨 false-complete** (work absent from main — possibly LOST) | **3** | anneal/t-432, anneal/t-463, anneal/t-474 |
| **superseded / landed-differently** (functionality in main via later work; safe to prune after human confirm) | **3** | quench/t-457, quench/t-469, quench/t-561 |
| **needs review** (recent or ambiguous) | **2** | anneal/t-535, quench/t-472 |

13 `forge-*/t-*` branches reconciled. **Check #19 count drops 13 → 8.** The
remaining 8 need an Anvil/human decision (none safe to auto-delete per the
guardrail: never delete a branch whose diff is unconfirmed-in-main).

## Method

For each branch: `git cherry main <branch>` (patch-id — survives Assembly's
rebase-merge sha change) + presence of a real work/merge commit in main's log +
file-existence check in main. **Note:** `git diff main...<branch> | git apply
--reverse --check` proved unreliable for *confirming landed* — it false-negatives
when main later evolved the touched files (e.g. temper/t-445 has an explicit
`[assembly] merge` commit in main yet reverse-apply reported NOT-IN-MAIN). So
landed = (cherry all `-`) **AND** (work/merge commit present in main).

## Pruned — confirmed landed (5)

| branch | evidence | sha (pre-delete) |
|---|---|---|
| forge-temper/t-445 | cherry all `-`; main has `acb72b3 [assembly] merge forge-temper/t-445 → main` | 92a732a |
| forge-quench/t-450 | cherry `-`; main has `b9869c4 [planning] t-450`; reverse-apply IN-MAIN | b4859d1 |
| forge-anneal/t-537 | cherry `-`; main has `fd5c835 [implementation] t-537` | 86bc212 |
| forge-quench/t-537 | cherry `-`; same patch in main (`fd5c835`) | 35f2d3e |
| forge-temper/t-537 | cherry `-`; same patch in main (`fd5c835`) | 027190a |

(Shas recorded for recoverability; all are reachable from main, so recovery is
not needed.)

## 🚨 FALSE-COMPLETE — possibly LOST work, DO NOT DELETE (3)

These tasks are `status=complete` but their work is **absent from main** (the
file the branch adds does not exist in main, and no work commit references the
task). The branch is the **only copy** of this work.

| branch | adds | evidence work is NOT in main |
|---|---|---|
| **forge-anneal/t-432** | `scripts/forge-status.sh` (+ test) — per-forge status dashboard | `scripts/forge-status.sh` MISSING in main; no commit mentions t-432; cherry `+1` |
| **forge-anneal/t-463** | `scripts/tmux-layout.sh` (+ cli.py, test) — Bellows as managed tmux window + patrol check #13 | `scripts/tmux-layout.sh` MISSING in main; only *ops* commits mention t-463; cherry `+1`. (cli.py bellows/patrol functionality partly exists via ini-022 — but the t-463 script + check is absent.) |
| **forge-anneal/t-474** | `hooks/forge-auto-clear.sh` + `.claude/settings.json` (+ test) — ini-021 forge auto-clear hook + kill switch | `hooks/forge-auto-clear.sh` MISSING in main; no commit mentions t-474; cherry `+1` |

**Recommendation (Anvil/human):** decide per task — re-implement / `resubmit-task`
the branch to re-gate, or accept as abandoned and correct status. Until then the
branches are **retained** (deleting would lose the only copy).

## Superseded / landed-differently — prune after human confirm (3)

Functionality appears present in main via later work; the branch's *exact* diff
is absent. Not lost, just redundant. Held (guardrail) pending confirmation.

| branch | task | why likely superseded |
|---|---|---|
| forge-quench/t-457 | Assembly staging-worktree decoupling (assembly.py, cli.py) | main's assembly.py has the staging-worktree machinery (ini-020 batched staging / t-570) — the t-457 goal is met differently |
| forge-quench/t-469 | Assembly stashes dirty main before merge | main's assembly.py has stash logic; ops commit `ce5a2dc` references the "main stash-pop fix" for t-469 → landed under a different commit |
| forge-quench/t-561 | `[testing] t-561` canonicalize refs (+ stacked `[editing] t-527`) | main HAS `c93ccb2 [testing] t-561` and the t-527 edits — this branch is a stale **pre-rebase variant**; work is in main |

## Needs review (2)

| branch | task | note |
|---|---|---|
| forge-anneal/t-535 | t-516 rework — namespace imports fix (cli.py, test_t442, test_t516) | NOT in main; **recent** but likely **OBSOLETE** — import style was re-canonicalized by t-539/t-549 (`smithy.X`), so resubmitting the old import fix would conflict/be redundant. Recommend: confirm the t-516 backpressure-multiplier work landed elsewhere, then prune; do NOT blind-resubmit. |
| forge-quench/t-472 | fix `hooks/teammate-idle.sh` (+ test) | `hooks/teammate-idle.sh` EXISTS in main, but no commit mentions t-472 and cherry `+1` — the specific fix is **unconfirmed** in main's version. Recommend: diff the branch's hook change vs main's current hook to decide landed-or-not. |

## Follow-ups proposed to Marshal

1. **Anvil/human triage of the 3 false-completes** (t-432, t-463, t-474) — real
   possibly-lost work. Highest signal.
2. After confirmation, a cleanup pass can prune the 3 superseded branches
   (t-457, t-469, t-561) and t-535 to drive check #19 to 0.
3. Consider a status correction for any task confirmed abandoned (complete →
   not-complete) so the queue reflects truth.

---

# t-588 — Final disposition of the 3 false-completes

Re-confirmed each against **current main** (post-t-584 merge). All 3 deliverable
files remain MISSING from main.

| branch | disposition | action taken | reason / evidence |
|---|---|---|---|
| **forge-anneal/t-432** (scripts/forge-status.sh) | ✅ STILL-WANTED → **RESUBMITTED** | `resubmit-task t-432` → status `submitted`, branch `forge-anneal/t-432@e264a564` enqueued for Assembly | main's `cli.py:4781` reap-suggestion literally says *"Inspect the pane (scripts/forge-status.sh)…"* — a **dangling reference to a script main expects but lacks**. Branch applies CLEAN to current main. Re-gating restores the per-forge dashboard + fixes the broken reference. (No per-forge *dashboard* exists in `smithy status`/`stats`/`sessions`.) |
| **forge-anneal/t-463** (tmux-layout.sh + patrol check #13) | SPLIT — layout SUPERSEDED, **patrol check = genuine GAP → FRESH RE-IMPL** | flag Anvil; branch **kept** as reference (do NOT prune); not resubmitted | `scripts/tmux-layout.sh` superseded by `scripts/start-smithy.sh` (91 tmux ops builds the layout). BUT main's `smithy patrol` has **NO bellows-window-health check** (only 2 unrelated "bellows" refs). The check is real missing coverage. Branch does **NOT apply clean** (stale cli.py base) → don't force-resubmit. **Recommend Anvil file a fresh task:** "add a bellows-window-health check to `smithy patrol` on current main," using forge-anneal/t-463's check#13 as the reference impl. |
| **forge-anneal/t-474** (hooks/forge-auto-clear.sh + settings.json) | ⚠️ NEEDS ANVIL DECISION (resubmit vs obsolete) | flag Anvil; **neither** resubmitted nor pruned | main has **no** forge context-reset/auto-clear hook (the `TaskCompleted` hook just runs `smithy complete-task`; cli.py:4530 only *describes* a manual `/clear` workflow). Branch applies CLEAN → resubmittable. **BUT** the persona `CLAUDE.md` was rewritten this session and **dropped the `/clear`-hook / auto-clear references** — a strong signal ini-021 auto-clear was **intentionally deprecated**. Strategic call → **Anvil decides**: resubmit if still wanted, else reclassify complete→obsolete. Per Marshal: do NOT blind-resubmit. |

**No `obsolete` status command exists** (`complete-task` only) — any complete→obsolete
reclassification must be done by Marshal/Anvil, not Forge.

### check #19 trajectory
- After t-584: 13 → 8 (pruned 5 landed).
- After t-588: t-432 resubmitted (clears to **7** once Assembly merges it). t-463 +
  t-474 remain flagged pending Anvil decisions.
- Still-open from t-584 (out of t-588 scope, need their own disposition pass):
  t-457, t-469, t-561 (likely-superseded → prune after confirm), t-535 (obsolete),
  t-472 (ambiguous). Surfacing for a follow-up cleanup task.
