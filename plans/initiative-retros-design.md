# Initiative Retros — Design

**Status:** draft (Anvil, 2026-04-19)
**Initiative:** TBD (candidate: new ini-025 *Initiative Retros & Closure*)

## What this is

A structured way to close initiatives with captured learnings. Today `smithy complete-initiative <id>` flips status to `complete` and nothing else — any retrospective is ad-hoc (only ini-019 has retros so far, hand-written as `plans/ini-019-retro-*.md`). This formalizes the pattern: every closure produces a retro artifact with prose (what we learned) and queryable metrics (heat cost, merge ratio, successor pointer).

First use case: **ini-015 (Marshal agent)** — 32/32 tasks complete, 28 heats vs 25 budgeted, Marshal fully operational. Ready to close and capture what we learned about replacing the wavefront allocator with an AI persona.

## Locked decisions (from brainstorm)

1. **Artifact shape**: markdown retro at `plans/ini-<id>-retro.md` + queryable fields in state.json (pointer, closure_date, heat_cost_total, successor_ini optional)
2. **Authorship**: Anvil drafts the prose skeleton (strategic synthesis); a Forge "editing" task populates the mechanical data sections (merge shas, task counts, heat metrics); human reviews + flips status via CLI
3. **Succession**: binary `status=complete`; optional `successor_ini` pointer when there's a direct continuation (e.g. ini-018 → ini-024); no `maintenance` status — future maintenance work gets its own new initiative when substantial

## Goals

- Every closed initiative produces a retro (forcing function via CLI)
- Retros are findable: predictable path + Bellows renders them on the initiative detail page
- Prose captures the *non-obvious* — what worked, what didn't, what carries forward
- Metrics are queryable (budget overrun patterns, ratio of closed vs abandoned, heat-cost trends)
- Low friction — closing an initiative should take one reasonable sitting, not be an event

## Non-goals

- Not a project post-mortem process (those live elsewhere if needed)
- Not retroactive on all past initiatives — backfill is explicitly out of scope; only new closures go through the process. (Optional: ini-019's existing retros can be linked in state.json as a one-off migration.)
- Not a performance review mechanism — retros are about *the work*, not *the workers*
- Not a gate on new related work — a new initiative can start while the old one's retro is in flight

## Artifact structure

### `plans/ini-<id>-retro.md` template

```markdown
# <ini-id>: <title> — Retrospective

**Closed:** YYYY-MM-DD
**Heat cost:** N heats (budgeted M)
**Task count:** K shipped / R rejected / A abandoned
**Successor:** <ini-id or "none; maintenance via new initiatives as needed">
**Author:** Anvil (prose) + <forge-id> (data, task t-XXX)

## Summary

<2-3 sentences: what the initiative was, what's different in the world now that it's done>

## What shipped

<bulleted list of concrete deliverables, each with a task id + merge sha. Filled by Forge data task.>

## What worked (keep doing)

<non-obvious patterns, judgment calls that paid off, techniques validated. Anvil prose.>

## What didn't (stop doing)

<dead ends, premature abstractions, rework cycles, bugs that recurred. Anvil prose.>

## Carry-forward

<concrete learnings that apply to future work — pointer to memories created, protocol docs updated, conventions codified. Anvil prose.>

## What's next

<either: "Successor is <ini-id>: <reason>" OR: "No direct successor. Future <domain> work files as a new initiative when substantial; small fixes go to theme-<id> without initiative attribution.">

## Metrics appendix

<table of task-by-task breakdown: id, stage, heats, merge-or-reject, sha. Filled by Forge.>
```

### state.json schema addition

Under each initiative object:

```json
{
  "id": "ini-015",
  "status": "complete",
  "retro_path": "plans/ini-015-retro.md",
  "closed_at": "2026-04-19T00:00:00Z",
  "heat_cost_total": 28,
  "successor_ini": null
}
```

Fields added: `retro_path`, `closed_at`, `heat_cost_total`, `successor_ini`. All `null` until closure.

## Closure flow

1. **Decide to close** — human signals (e.g., "ini-015 is done, let's close it"). Anvil verifies: all tasks under the ini are `complete`, no open pending/in_progress/submitted rows. If any open, either flip them to obsolete/reject explicitly or hold off.
2. **Anvil drafts prose skeleton** — reads the record (worklog filtered to this ini, git log of merged shas, memories tagged with ini context, plans/ docs referencing this ini). Produces `plans/ini-<id>-retro.md` with all prose sections filled and data sections marked `<TODO: Forge data fill>`.
3. **Anvil files a Forge retro-data task** — stage `editing`, description: "fill metrics + task-by-task appendix in plans/ini-<id>-retro.md per retro template". Anvil includes a pointer to which state.json queries the Forge should run.
4. **Forge completes the data fill** — runs the queries, fills the metrics sections, submits.
5. **Assembly merges** the retro into main via standard flow.
6. **Human reviews** — reads the merged retro in Bellows (renders on initiative detail page via t-501 markdown). Edits prose if needed (commits directly to main — retros are human territory, no Assembly gate needed for edits).
7. **Human closes** — `smithy complete-initiative <id> --retro plans/ini-<id>-retro.md [--successor <other-id>]`. CLI validates: file exists, path matches convention, status was `active`/`approved`; writes state.json fields.

## CLI changes

```
smithy complete-initiative <id> --retro <path> [--successor <ini-id>]
```

- `--retro <path>` **required** — file must exist at the path; CLI reads it to capture `closed_at` (git author-date of the file's introduction if committed, else now) and `heat_cost_total` from state.json (not the retro — source of truth)
- `--successor <ini-id>` **optional** — must reference an existing initiative; target must be `approved` or `active`
- Escape hatch: `--force-no-retro` — closes without retro (for edge cases; flag logged in rig-events)

Current `smithy complete-initiative <id>` signature is preserved as `--force-no-retro` equivalent with a deprecation warning.

## Implementation tickets

T1. **Schema + CLI** — add `retro_path`, `closed_at`, `heat_cost_total`, `successor_ini` to state.json initiative schema; extend `complete-initiative` with `--retro` (required), `--successor` (optional validated against roster), `--force-no-retro` (escape). Tests for each flag + validation path. *(1 heat, implementation, under ini-025)*

T2. **Retro template + docs** — drop `plans/TEMPLATE-initiative-retro.md` (canonical template; new closures copy it). Document the flow in `identity.md` and `personas/anvil/CLAUDE.md`. *(1 heat, planning)*

T3. **Anvil retro-drafting procedure** — documented steps Anvil follows (not code): read state.json for ini scope, grep worklog for task IDs, git log merged shas, scan memories for tagged learnings, produce prose skeleton. Could be a skill (`/retro-draft <ini-id>`) later; for v1 just CLAUDE.md documentation. *(0 heats — docs included in T2)*

T4. **Bellows retro rendering** — initiative detail page renders `retro_path` file below the existing sections. Blocked on t-501 (markdown rendering). Graceful degrade: if t-501 not merged, render as `<pre>` with t-500's whitespace preservation. *(1 heat, editing, blocked on t-500)*

T5. **Shakedown on ini-015** — first real use. Anvil drafts `plans/ini-015-retro.md` prose (this session or next). Files the data-fill task. Assembly merges. Human closes via new CLI. Validates the template + flow end-to-end. Any template revisions from the shakedown land as T6. *(Anvil + 1 Forge heat)*

T6. **Template v2 based on shakedown** — optional follow-up if shakedown reveals template issues. *(may be 0 heats)*

**Total budget: ~4-5 heats** across T1-T5.

## Open questions

1. **Initiative for this work** — new ini-025, or fold under ini-016 (Queue Cockpit)? My recommendation: new ini-025. Retros aren't a UI feature, they're a process/protocol feature.
2. **Retro required for `rejected` initiatives?** — if an initiative is explicitly rejected, is there value in a retro? My take: optional. Rejection already implies "we decided not to pursue"; the reason lives in the rejection action itself. But `--retro` could be *allowed* (not required) on reject for cases like ini-001 (rejected after exploration) where the lessons matter.
3. **Backfill for ini-019** — it already has retros at `plans/ini-019-retro-*.md`. One-off migration: set `retro_path` on ini-019 pointing at whichever of the existing docs is canonical. 5-minute task, tack onto T1.
4. **Ini-018 and ini-022 also effectively done?** — ini-018 (Parallel Forges) has shipped 50+ heats; ini-022 (Rig Startup & Lifecycle) has the ui window + venv pre-boot. Worth considering parallel closure shakedowns. Humans's call.
