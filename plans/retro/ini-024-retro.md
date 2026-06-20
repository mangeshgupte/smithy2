# ini-024: Liveness via reconciliation — Retrospective

**Closed:** 2026-06-20 *(pending `smithy complete-initiative`)*
**Heat cost:** 21 heats (no cap set)
**Task count:** 18 shipped / 0 abandoned *(4 reject-cycles rolled into merged retries — see appendix)*
**Successor:** none — future reconciliation/liveness work files as a new initiative (or theme task) when substantial
**Author:** Anvil (prose, 2026-06-20) + forge-temper (data, task t-610)

## Summary

Made state.json + git branches the single source of truth and demoted the
queues (`.assembly-queue.jsonl`, `next_tasks`, nudges) to a fast-path cache that
is no longer load-bearing for correctness. Every agent's idle tick now runs a
Kubernetes-style reconcile pass — derive "what should I be doing?" from truth and
act, even if the cache says nothing — so lost nudges, missing jsonl, and stale
queue files became non-events instead of rig freezes. The class of bugs that
motivated it (zombie-submitted, missing-jsonl, starving-forge — three distinct
incidents on 2026-04-18 sharing one root cause) is structurally gone, and the
audit that proves it (patrol check #19, ghost-complete branches) closed at **0
discrepancies** on 2026-06-19.

## What shipped

**Phase 1 — reconcile core (T1–T3):**
- **t-494** — Assembly tick reconciles from truth (scans `state.queue` for submitted branches when `.assembly-queue.jsonl` is empty/missing) — `ece7c88`
- **t-495** — `smithy claim-task` CLI: the atomic CAS `pending → in_progress` primitive sibling Forges race on — `b53951a`
- **t-496** — Forge reconciliation protocol (claim-task backstop after an empty `queue-pop`) + end-to-end tests — `1e0949a`

**Phase 2 — Marshal + docs (T4–T5):**
- **t-497** — Marshal `next_tasks` invariant / `reconcile-next-tasks` repopulation (landed via the namespace-form retry) — `c75e5c5`
- **t-498** — "Truth vs. Cache" section written into all four protocol docs (`protocol/loop.md` + forge/marshal/assembly CLAUDE.md) — `860367f`

**Reliability-hardening tail:**
- **t-541** — `queue-pop` atomically claims the popped task (fixes a silent-drop liveness bug) — `c3fa1f9`
- **t-544** — patrol reap guard: verify liveness (task status + checkpoint mtime) before orphan reap; start/end-heat maintain registry status — `4ed1dfb`
- **t-552** — ghost-complete reconciliation patrol check (#19), gate-hardened re-merge — `e8a3b97`
- **t-560** — `complete-task` refuses over unmerged branches (`--force` audits); `resubmit-task` re-enqueues existing branches — `3560a8e`
- **t-569** — anchor the end-heat cap-warning outbox write at the main repo root (not the worktree) — `61fd2cb`
- **t-574** — anchor the dispatch-next reject-loop inbox note at the main repo root — `316e7b6`
- **t-577** — re-gate the `claim-task → start-heat` resume seam — `4ea3a08`
- **t-581** — anchor the persona nudge queue to the main repo root (`load_state` auto-redirects worktree → canonical) — `1a94cd4`
- **t-582** — patrol starvation count excludes `blocked_by`-incomplete tasks — `320c700`

**Ghost-branch cleanup (check #19 → 0):**
- **t-584** — disposition pass 1: pruned 5 confirmed-landed branches, flagged 3 false-completes, held 5 for review; table in `plans/ghost-branch-reconciliation.md` — `8346d94`
- **t-588** — disposition of 3 false-completes (resubmitted t-432; flagged t-463 / t-474) — `ac3eec9`
- **t-590** — disposition pass 2: pruned 5 superseded/obsolete, resubmitted t-472, held t-463 (check #19: 13 → ~1) — `32b22d8`
- **t-591** — finished reconciliation: check #19 = 0 (11 pruned / 2 resubmitted-merged) — `56726c8`

## What worked (keep doing)

**Structural fix over whack-a-mole.** The design's load-bearing insight: three
2026-04-18 incidents (heat 989 zombie-submitted; heat 887 empty next_tasks with
9 pending; heat 887 missing jsonl with submitted branches) shared *one* root —
the cache can diverge from truth and nothing reconciles them. Rather than add a
patrol check per divergence class (the t-491/t-493 path), reconciliation made the
whole class impossible. This is the heuristic to repeat: when N incidents share a
root cause, fix the sharing; detectors are a fallback, not the fix.

**Two-layer separation: nudge = *when*, truth = *what*.** Keeping the nudge as a
sub-second fast path while reconciliation is the correctness backstop meant zero
happy-path latency regression *and* self-healing when hints are lost. The same
separation ini-015's retro flagged — reconciliation took over correctness, the
nudge stayed as optimization — is now real, not aspirational.

**`claim-task` as a dedicated atomic-CAS primitive (t-495).** Choosing a clean
CLI contract (CAS pending→in_progress under the shared lock) over reusing
file-locks (design open-Q #2) gave a testable primitive that lets sibling Forges
race for the same task safely. It's the seam the whole Forge-side self-dispatch
hangs on.

**Patrol kept as the audit layer, not retired.** Reconciliation makes bugs
impossible; patrol *proves* it. Check #19 (ghost-complete: status=complete but
branch unmerged + absent from queue) is the receipt — it surfaced a silent
backlog of 12+ ghost branches and drove it to 0. Mechanism + audit together is
stronger than either alone.

## What didn't (stop doing)

**The audit shipped ~2 months after the mechanism, so a silent backlog grew.**
The core landed 2026-04-18/19 (t-494–t-498), but the ghost-complete audit (check
#19, t-552) didn't merge until 2026-06-19 — and by then 13 ghost-complete
branches had accumulated, needing **four** sequential disposition passes
(t-584→t-588→t-590→t-591) to clear (11 pruned / 2 resubmitted). **Lesson:** ship
a reconciliation mechanism *with* its audit check in the same wave — the gap
between "it should be impossible now" and "we can prove it" is exactly where the
silent backlog accumulates.

**Root-anchoring was a recurring sub-bug, rediscovered file-by-file.** Three
separate live-coordination writes were still anchored to the raw *worktree* root
instead of canonical main: end-heat cap-warning outbox (t-569), dispatch-next
reject-loop inbox note (t-574), persona nudge queue (t-581) — the same class as
the earlier t-419/t-454. Each made cross-worktree coordination silently fail.
**Lesson:** "anchor to canonical main root" should be one helper every
coordination write flows through, not a fix re-applied per file each time it
bites. (t-581 confirmed state.json/assembly-queue/worklog were already anchored;
the nudge queue was the last hold-out.)

**Two tasks bounced on the staging-venv environment class, not on content.**
t-497 hit the namespace-import divergence (`from smithy.X` vs
`from smithy.smithy.X`) at the Assembly gate; t-552 bounced *twice* on the
staging-venv / collection-error pattern before merging. Neither was a real
defect — the same env-coupling that bit ini-025's t-504. Docs/structural tasks
keep paying a gate-environment tax.

## Carry-forward

- **Design contract:** `plans/liveness-reconciliation-design.md` (why, principle, agent-by-agent reconcile predicates, 3-phase rollout).
- **Disposition record:** `plans/ghost-branch-reconciliation.md` (the check-#19 cleanup table + counts).
- **Protocol docs:** the "Truth vs. Cache" section landed in all four protocol docs (t-498) — `protocol/loop.md` + `personas/{forge,marshal,assembly}/CLAUDE.md`.
- **CLI primitives:** `smithy claim-task` (atomic CAS), `smithy reconcile-next-tasks` (Marshal invariant), `complete-task` unmerged-branch guard + `resubmit-task` (t-560).
- **Standing audit:** patrol check #19 (ghost-complete) — keep it green; a non-zero count means reconciliation has a hole.
- **Memories:** [[project_state_json_per_worktree]] (t-581 — load_state auto-redirects worktree→canonical), [[project_claim_task_start_heat_seam]] (the claim→start-heat seam, re-gated by t-577), [[project_cold_start_false_zombies]] (stale heartbeats ≠ zombies — verify from truth), and the gate-tax pair [[project_import_style_staging_venv]] / [[project_collection_error_kills_gate]].

## What's next

**No direct successor.** The convergence story is complete: all three agents
self-dispatch from truth, the motivating bug class is structurally dead, and the
audit confirms it. **Phase 3 is the one design item left, and it is deferred by
design** — "evaluate whether to remove `.assembly-queue.jsonl` and `next_tasks`
entirely; keep as optimization if measurable latency improvement, remove
otherwise." Recommendation: **keep them.** Now that they're non-load-bearing,
they are a harmless fast path; removing them is churn for marginal benefit and
the design explicitly permits keeping them. Capture Phase 3 as a closed decision,
not an open loop. Future reconciliation maintenance files as a theme task or new
initiative per the succession rule.

## Metrics appendix

| task   | stage          | heats | result   | sha       |
|--------|----------------|------:|----------|-----------|
| t-494  | implementation | 1     | merged   | `ece7c88` |
| t-495  | implementation | 1     | merged   | `b53951a` |
| t-496  | implementation | 1     | merged   | `1e0949a` |
| t-497  | implementation | 2     | merged   | `c75e5c5` |
| t-498  | marketing      | 1     | merged   | `860367f` |
| t-541  | implementation | 1     | merged   | `c3fa1f9` |
| t-544  | implementation | 1     | merged   | `4ed1dfb` |
| t-552  | implementation | 3     | merged   | `e8a3b97` |
| t-560  | implementation | 1     | merged   | `3560a8e` |
| t-569  | implementation | 1     | merged   | `61fd2cb` |
| t-574  | implementation | 1     | merged   | `316e7b6` |
| t-577  | implementation | 1     | merged   | `4ea3a08` |
| t-581  | implementation | 1     | merged   | `1a94cd4` |
| t-582  | implementation | 1     | merged   | `320c700` |
| t-584  | implementation | 1     | merged   | `8346d94` |
| t-588  | implementation | 1     | merged   | `ac3eec9` |
| t-590  | implementation | 1     | merged   | `32b22d8` |
| t-591  | implementation | 1     | merged   | `56726c8` |
| **total** | **18 tasks** | **21** | **0 abandoned** | — |

**Window & cadence.**

- Earliest worklog entry under ini-024: **2026-04-18** (t-494, the Assembly-reconcile core).
- Two distinct waves. **Core (T1–T5)** landed **2026-04-18 → 04-19** (t-494–t-498, heats h895–929) — the reconciliation mechanism itself, built and merged in ~2 days. **Hardening tail** landed **2026-06-12 → 06-19** (h1236–1377), eight weeks later: the audit (check #19, t-552), the root-anchoring fixes (t-569/574/581), seam/guard hardening (t-560/577/582/544/541), and the four-pass ghost-branch cleanup (t-584 → t-588 → t-590 → t-591).
- Calendar span: **~62 days** (2026-04-18 → 06-19) — but the gap *is* the story (see "What didn't"): the mechanism shipped in April, the audit that proves it didn't land until mid-June, and the silent ghost-complete backlog accumulated in between.
- Reject cycles: **4** total across 18 tasks — t-497 ×1 (h913, namespace-import), t-552 ×2 (h1345 + h1359, staging-venv / collection-error), t-588 ×1 (h1371); the other 15 tasks clean. No task exceeded 2 reject cycles; every reject rolled into a merged retry (0 abandoned).

> **Data-fill note (t-610).** Figures match current `state.json`: ini-024 `heats_used=21`, `status=approved`, 18 complete tasks; `closed_at`/`heat_cost_total`/`retro_path` still null — hence the *(pending `smithy complete-initiative`)* marker on the Closed line. Per-task `heats` counts distinct Forge work-heat worklog rows (val>0 submissions; reject and merge bookkeeping rows excluded), so it absorbs each rework retry: t-497=2 (1 reject → 1 rework), t-552=3 (2 rejects → 2 reworks); t-588's ×1 reject was a `resubmit-task` of the existing branch with no new work heat, so it stays 1. Appendix sum **21** equals the charged `heats_used` (**21**) *exactly* — every ini-024 task ran in the per-task-branch era, so attribution is precise (no pre-branch approximation gap like ini-015's). The remaining closure step is the human running `smithy complete-initiative ini-024 --retro plans/retro/ini-024-retro.md`.
