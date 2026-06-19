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

---

# t-590 — Disposition pass #2 (the 5 still-open + Anvil's t-474 ruling)

Re-confirmed each against current main (cherry + work-commit + file/functionality).

| branch | disposition | action | evidence |
|---|---|---|---|
| forge-quench/t-457 | SUPERSEDED → **PRUNED** | `git branch -D` (was e882c32) | main's assembly.py has the staging-worktree machinery (21 refs) + the `.worktrees/_assembly-staging` worktree exists (ini-020 batched staging). t-457's decoupling goal is met. |
| forge-quench/t-469 | SUPERSEDED → **PRUNED** | `git branch -D` (was 1f6513d) | main's assembly.py has stash logic (16 refs); ops commit `ce5a2dc` landed the "main stash-pop fix". |
| forge-quench/t-561 | LANDED-DIFFERENTLY → **PRUNED** | `git branch -D` (was 29b4377) | main has `c93ccb2 [testing] t-561` + the t-527 edits; branch was a stale pre-rebase variant. |
| forge-anneal/t-535 | OBSOLETE → **PRUNED** (no resubmit) | `git branch -D` (was c1ba80b) | t-516 backpressure-multiplier IS in main (39 refs, landed elsewhere); the namespace-import rework was re-canonicalized by t-539/t-549 → resubmit would conflict/be redundant. |
| **forge-quench/t-472** | ⚠️ **NOT ambiguous — LIVE BUGFIX, not in main → RESUBMITTED** | `resubmit-task t-472` (→ submitted, @19788391) | main's `hooks/teammate-idle.sh` STILL reads `state.get('tasks', [])` — the schema key is `'queue'`, so the idle hook always sees **0 pending** (broken). t-472 fixes `tasks`→`queue`; applies clean. A real not-landed fix, NOT superseded. |
| forge-anneal/t-474 | OBSOLETE (Anvil ruling) → **PRUNED** | `git branch -D` (was 9f1563c) | Anvil decided ini-021 forge-auto-clear is deprecated (CLAUDE.md rewrite dropped the /clear-hook). Pruned per decision. |

## Final reconciliation summary (original 13 ghost branches)
- **Pruned 10** (landed/superseded/obsolete): t-445, t-450, t-537×3 (t-584); t-457, t-469, t-561, t-535, t-474 (t-590).
- **Resubmitted 2** (still-wanted, applied clean): **t-432** (forge-status.sh — main dangling-refs it; now merged) and **t-472** (teammate-idle.sh live bugfix — in Assembly queue).
- **Held 1**: forge-anneal/t-463 — bellows-window-health patrol check is a genuine coverage gap; branch is stale (won't apply). Kept as the reference impl for a fresh re-implementation.

**Remaining ghost branches: 2** (t-472 clears on merge; t-463 clears when the fresh bellows-patrol-check task lands) → check #19 driven **13 → ~1** (t-463).

## Open items for Anvil / Marshal
1. **File the fresh "bellows-window-health patrol check" task** (use forge-anneal/t-463 as reference), then prune t-463.
2. **Reclassify complete→obsolete** (no CLI command — needs Marshal/Anvil) for the pruned-but-genuinely-obsolete tasks: t-535, t-474 (optionally t-457/t-469/t-561) so queue status reflects truth, not just branch absence.

---

# t-591 — FINISH: check #19 == 0 ✅

The two held items from t-588/t-590 both landed on main since pass #2:

| item | status | confirmation |
|---|---|---|
| **t-589** (fresh bellows-window-health patrol check, Anvil-filed from t-463) | MERGED `70fb862` / `c08abb9` | main's `smithy patrol` now runs **20 checks** (was 19); cli.py bellows refs 2 → 20. The t-463 bellows gap is **filled**. |
| **forge-anneal/t-463** | **PRUNED** (was a8954e0) | bellows concern covered by t-589 (#20); tmux-layout.sh concern superseded by start-smithy.sh. Work confirmed in main → safe to delete. |
| **t-472** (teammate-idle `tasks`→`queue` fix) | MERGED `8f8294d` | main's `hooks/teammate-idle.sh` now reads `state.get('queue', [])` — the live bug is fixed. Branch already deleted by Assembly on merge. |

### Final confirmation (`smithy patrol`)
- **checks_run: 20** · **ghost-branch (check #19) discrepancies: 0** ✅
- No `forge-*/t-*` branches remain for any of the original 11 ids.
- `clean: false` overall, but the 2 remaining discrepancies are **unrelated** to ghost branches and **out of t-591 scope**:
  1. `comms-tick.sh cron line missing while rig is up` — Comms cron not installed.
  2. `bellows tmux window 'bellows' missing while rig is up` — the Bellows dashboard/API is down. *(This is t-589's brand-new check #20 working as intended — flagging a real ops issue.)*
  → flagged to Marshal/Anvil separately.

## Reconciliation CLOSED
Original 13 ghost branches: **11 pruned** (t-445, t-450, t-537×3, t-457, t-469, t-561, t-535, t-474, t-463) · **2 resubmitted→merged** (t-432 forge-status.sh, t-472 teammate-idle fix). **check #19 = 0.**

Residual (queue-cosmetic, not check #19): complete→obsolete reclassification for the
genuinely-obsolete tasks (t-535/t-474/…) still has no CLI and was **not** done via a
raw state.json edit (live-state race risk / "no direct edits" invariant) — left for
Marshal/Anvil. Pruning already removed the ghost aspect, and each pruned task's
capability is either in main or ruled obsolete, so `complete` is not misleading.
