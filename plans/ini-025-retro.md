# ini-025: Initiative retros & closure — Retrospective

**Closed:** 2026-06-19 *(pending `smithy complete-initiative`)*
**Heat cost:** 7 heats (budgeted ~4–5; no hard cap)
**Task count:** 4 shipped / 0 abandoned *(3 reject-cycles rolled into merged retries — see appendix)*
**Successor:** none — future retro/closure work files as a new initiative (or theme task) when substantial
**Author:** Anvil (prose, 2026-06-19) + forge-temper (data, task t-595)

## Summary

Turned `smithy complete-initiative` from a bare status-flip into a closure
*ritual* that captures what was learned. Every closed initiative now produces a
`plans/ini-<id>-retro.md` artifact — Anvil-authored prose (what worked, what
didn't, what carries forward) plus a Forge-filled metrics appendix — and four
queryable state.json fields (`retro_path`, `closed_at`, `heat_cost_total`,
`successor_ini`) the CLI writes and Bellows renders. The system was proven by
closing its first real initiative through it: **ini-015 (Marshal) closed
2026-06-20 with a full retro** — and this very document is the system being run
on itself.

## What shipped

- **t-503** — retro/closure schema on every initiative (`retro_path`, `closed_at`, `heat_cost_total`, `successor_ini`) + `complete-initiative` closure flags (`--retro` / `--successor` / `--force-no-retro`) — `3101033`
- **t-504** — retro template (`TEMPLATE-initiative-retro.md`) + closure-flow docs (`identity.md` lifecycle, `personas/anvil/CLAUDE.md` drafting procedure) — `4128146`
- **t-505** — Bellows renders the Retrospective section on the initiative detail page (defensive file-read: path-traversal / directory / absolute-path guards + `<pre>` degrade) — `f2b3ccb`
- **t-506** — shakedown: filled the ini-015 retro data sections, closing the first real initiative through the new flow — `0aba398`

## What worked (keep doing)

**The two-author split held up (Anvil prose + Forge data).** The design's core
bet — Anvil does strategic synthesis, a Forge fills the mechanical data behind
`<TODO: Forge data fill>` markers — was validated on the ini-015 shakedown
(t-506). The seam is clean and the division mirrors the Anvil-spec /
Forge-implement pattern that already worked across ini-015's 35 tasks. A future
Smith can trust this split for any doc that mixes judgment with bookkeeping.

**Dogfooding before declaring done (T5 shakedown on ini-015).** The shakedown
wasn't ceremonial. Building the machinery (T1–T4) and *immediately closing a
real initiative through it* (t-506 → ini-015 closed 2026-06-20) is what proved
the CLI writes the right state.json fields and Bellows renders the artifact.
Build-then-use-once should be the default acceptance bar for any process feature
— a green test suite would not have caught a broken end-to-end closure flow.

**CLI as the sole writer of closure fields.** `complete-initiative` is the only
thing that writes `retro_path`/`closed_at`/`heat_cost_total`/`successor_ini`;
nobody hand-edits them in state.json. And `heat_cost_total` is sourced from
state.json, *not* from the retro prose — the document describes, the record
decides. This source-of-truth discipline is why the header on a retro can drift
from live state (as ini-015's did, see its data-fill note) without corrupting
anything: the CLI re-reads truth at closure.

**Defensive-from-the-start Bellows render (t-505).** Retro loading shipped with
path-traversal, directory, and absolute-path guards, plus a graceful-degrade to
`<pre>` if markdown rendering wasn't available. A user-facing file-read path
hardened on day one rather than after an incident.

## What didn't (stop doing)

**t-504 bounced for ~7 weeks on environment, not content.** It is a *pure-docs*
task — a markdown template plus CLAUDE.md/identity.md prose, zero code — so it
cannot have a legitimate test failure. Yet it was rejected twice: first on the
staging-venv namespace-import divergence (h936: `from smithy.X` vs
`from smithy.smithy.X`, the t-489/t-539 hazard), then on a *pre-existing
collection error in an unrelated test* (h953: `test_t455_normalize_hp` ERROR —
the "one bad import aborts the whole staging suite" pattern). It finally landed
2026-06-12 (h1323), ~7 weeks after first submission (2026-04-19). **Lesson:** a
docs-only change should never gate on the full test suite it didn't touch — this
is the recurring "disjoint failures = environment" + "collection error kills the
gate" pair, and here it stalled a 1-heat task for seven weeks.

**Ticket-number drift muddied the trace.** The design enumerated T1–T6, but the
worklog/commits labeled t-505 as "T3" when it's design-T4 (Bellows render), and
the real T3 (the Anvil drafting procedure) was silently folded into t-504/T2.
The mapping is recoverable but only by reading prose. **Lesson:** when folding
or renumbering tickets, record the merge in the worklog note — don't let the
design's ticket numbers and the executed task labels drift apart.

**The cobbler's children: it never closed itself.** ini-025 built the closure
machinery in April–June and then sat `status=approved` with all four tasks
complete from 2026-06-12 until this draft (2026-06-19) — the system that exists
to close initiatives was the one initiative left open. (This retro fixes it.)

## Carry-forward

- **Contract:** `plans/initiative-retros-design.md` — locked decisions, goals/non-goals, closure flow.
- **Template:** `plans/TEMPLATE-initiative-retro.md` — copy on every closure (canonical, from t-504).
- **Lifecycle doc:** `identity.md` §"Initiative Lifecycle" — where closure fits end-to-end.
- **Drafting steps:** `personas/anvil/CLAUDE.md` §"Closing Initiatives" — Anvil's part of the flow (the documented T3 procedure; could become a `/retro-draft` skill later).
- **CLI:** `complete-initiative --retro/--successor/--force-no-retro` is the sole writer of closure fields; `heat_cost_total` always from state.json.
- **Environment-hazard memories that explain the t-504 churn** (already durable, point here): [[project_collection_error_kills_gate]], [[project_disjoint_failures_mean_environment]], [[project_import_style_staging_venv]], [[project_staging_venv_bound_to_main]]. The standing fix when a docs/disjoint task bounces: one gate-unblock task, hold the rest, Assembly resubmits blameless rejects.

## What's next

**No direct successor.** The retro/closure system is feature-complete: schema +
CLI, template + docs, Anvil drafting procedure, Bellows rendering, all validated
by a real closure (ini-015). The one explicitly-deferred follow-up is the
`/retro-draft <ini-id>` skill (design T3 — "could be a skill later; for v1 just
CLAUDE.md documentation"); it files as a new task when the manual procedure
proves worth automating. Adjacent loose end (belongs to *ini-019's* closure, not
this one): design open-question #3 — back-fill `retro_path` on ini-019, whose
retro docs (`plans/ini-019-retro-applied.md`, `-map.md`) exist on disk but were
never wired into state. Future retro-system maintenance files as a theme task or
new initiative per the locked succession decision.

## Metrics appendix

| task   | stage          | heats | result   | sha       |
|--------|----------------|------:|----------|-----------|
| t-503  | implementation | 2     | merged   | `3101033` |
| t-504  | planning       | 3     | merged   | `4128146` |
| t-505  | editing        | 1     | merged   | `f2b3ccb` |
| t-506  | editing        | 1     | merged   | `0aba398` |
| **total** | **4 tasks** | **7** | **0 abandoned** | — |

**Window & cadence.**

- Earliest worklog entry under ini-025: **2026-04-19** (t-503 first submit).
- Latest merge: **2026-06-12** (t-504 and t-506 landed within ~35 min of each other).
- Calendar span: **~54 days** (2026-04-19 → 2026-06-12) — but the machinery was front-loaded: t-503 (schema) and t-505 (Bellows render) both built *and* merged on **2026-04-19**. The entire long tail is t-504, the pure-docs task that bounced ~7 weeks on environment (see "What didn't"), with t-506 (the ini-015 shakedown) gated behind the finished machinery and landing the same day t-504 finally did.
- Reject cycles: **3** total across 4 tasks — t-503 ×1 (h912, staging-venv namespace), t-504 ×2 (h936 namespace, h953 collection-error); t-505 and t-506 clean. No task exceeded 2 reject cycles; every reject rolled into a merged retry (0 abandoned).

> **Data-fill note (t-595).** Figures match current `state.json`: ini-025 `heats_used=7`, `status=approved`, 4 complete tasks; `closed_at`/`heat_cost_total`/`retro_path` still null — hence the *(pending `smithy complete-initiative`)* marker on the Closed line. Per-task `heats` counts distinct Forge work-heat worklog rows (val>0 submissions; reject and merge bookkeeping rows excluded), so it absorbs each reject-and-retry: t-503=2 (1 reject → 1 retry), t-504=3 (2 rejects → 2 retries), t-505=1, t-506=1. Appendix sum **7** equals the initiative's charged `heats_used` (**7**) *exactly* — unlike ini-015's pre-per-task-branch approximation, every ini-025 task ran in the per-task-branch era, so attribution is precise. The remaining closure step is the human running `smithy complete-initiative ini-025 --retro plans/ini-025-retro.md`.
