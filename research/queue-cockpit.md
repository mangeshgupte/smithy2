# Queue Cockpit — Design (t-375)

**Date:** 2026-04-12, heat 788
**Origin:** Team-lead ask via Marshal. Primary UI for per-task steering — the view humans land on when they want to reshape Forge's next moves. `ini-016` tracks the feature.

Poker ranks initiatives; Upcoming manages cross-project pins; the initiative deep-dive is a read surface. None of these is where you'd live for 10 minutes adjusting a sprint. The cockpit fills that gap: **one dense, filterable, gesture-heavy table of every task with its scheduler-assigned order visible and every steering lever one click away.**

---

## Nine framing questions

### Q1 — Layout: table vs card grid vs split view

**Verdict: dense table with optional collapsible detail drawer (the TaskDetail drawer from t-374).**

Card grids (Poker style) optimize for *glancing at a few* and *dragging rank* — neither dominates here. A queue cockpit is read by someone who already knows which task they want to touch and just needs to find it fast. Tables make that *trivial*: ~40-column-width rows, 30-50 visible at once, rapid scan + keyboard navigation.

Split view (left list + right detail pane) was the runner-up but burns horizontal real estate for an already-sparse detail page. Reuse the drawer instead — it slides in on demand, doesn't fight for space when collapsed.

Rejected:
- **Card grid** — pretty, wasteful; doesn't scale past ~30 tasks.
- **Kanban-by-stage** — Poker already does this indirectly via stage progress; the cockpit's value is *cross-stage* steering.

### Q2 — State sync: reuse Poker SSE or new endpoint

**Verdict: reuse Poker's existing `/events` SSE stream. Don't spin a new endpoint.**

Poker already broadcasts `state-changed` on every mutation (`ui-priority-poker/app.py:~290`). The cockpit lives in the same web process (or mirrors via SSE from another port), so subscribing is one `new EventSource('/events')` plus a refresh handler. Creating a parallel stream would fork the invalidation contract — two places that need updating whenever a mutation type is added.

If we later split the cockpit to its own port (doubtful — the steering-UI sprawl is already a concern), the SSE client pattern stays the same; only the origin URL changes via env var.

### Q3 — Gesture design: inline buttons vs kebab vs both

**Verdict: hybrid. Inline for the top-3 most-used (priority bump, defer toggle, pin). Kebab for the rest.**

Measurements from real use (Poker drawer, Upcoming):
- **Priority set/clear** — most frequent. Inline arrow buttons `↑ ↓` on every row; click = set `human_priority` relative to current. `✕` clears.
- **Defer/un-defer** — second. Status toggle icon `⏸ / ▶` inline.
- **Pin in Upcoming** — third. Inline `📌` button.
- **Delete, set-reason, open-in-Poker, open-in-Intent, reorder-in-ini, override-stage** — kebab menu `⋯` → dropdown.

Why not all-inline: the row is already 10 columns wide. Every additional button steals from desc truncation, which hurts the "scan for the right task" loop worse than the occasional extra click on a rare action.

Why not all-kebab: forcing two clicks on the *most common* action is a regression from Poker's current single-click priority bump.

### Q4 — Columns

**Locked column set** (in order, left-to-right):

```
▸  id    stage   status    M:p#   you:p#    reason(trunc)   initiative    age   desc(trunc)   ⋯
```

- **▸** — expand toggle → opens TaskDetail drawer in-place.
- **id** — `t-042`, click → drawer deep-link (`?task=`).
- **stage** — `implementation` pill colored per stage.
- **status** — `pending / in_flight / deferred / complete`.
- **M:p#** — Marshal's computed priority. Not editable here.
- **you:p#** — `human_priority`; inline `↑ ↓ ✕`.
- **reason** — truncated to 40 chars, hover for full. Editable via kebab.
- **initiative** — `ini-009` link → Bellows deep-dive page.
- **age** — heats since created, derived from worklog first-mention or state heat at creation.
- **desc** — truncated. Hover = full; click = drawer.
- **⋯** — kebab for long-tail actions.

No `priority_reason` full column — it's usually too long to scan inline. One column less, hover is enough.

### Q5 — Row order: from scheduler, not reimplemented

**Verdict: /api/cockpit returns rows in the exact order Marshal's scheduler produces them. Cockpit does not sort.**

This is the important bit. The scheduler's ranking algorithm (PI-controlled allocator + initiative rank + human_priority + priority) is the single source of truth for "what's next." Any resort at the UI layer creates a divergence — users would see a different order than Forge would actually pick.

`_compute_ranked_queue()` (Poker) or the equivalent stage-allocator output already produces ranked rows. Expose a helper, serialize it, done. **Client-side sort is permitted** only for alternative views (e.g., "sort by age") and must be a clearly-labeled override, not the default.

### Q6 — Filters (query-param driven)

**URL contract:** `/cockpit?stage=implementation&status=pending&initiative=ini-009&q=OAuth`

- `stage=<s>` — restrict to one stage
- `status=<s>` — `pending | in_flight | deferred | complete | archived`
- `initiative=<ini-id>` — one initiative
- `q=<text>` — substring match on desc (case-insensitive)

Filters are **server-side** (applied in the aggregator) so the scheduler-order guarantee holds post-filter. Multi-select (e.g., `stage=research,planning`) is a v2 concern — single-value covers 95% of use.

Permalink behavior: filter state lives in URL only; no cookies / localStorage. Refresh preserves, bookmark shares.

### Q7 — Bulk actions: separate task

**Verdict: explicitly out of scope for v1.**

Bulk defer / bulk human_priority / bulk move-to-initiative are genuinely useful but require a selection model (checkboxes, shift-click ranges, confirmation dialogs). That's a second page of surface area and correctness concerns. File as follow-up task if users ask.

### Q8 — Integration with TaskDetail class (t-374)

**The cockpit is the biggest consumer of TaskDetail yet.** Each row's data comes from:
- `TaskDetail.resolve(project_root, task_id)` when expanding the drawer.
- The aggregator `/api/cockpit` bulk-hydrates via a new `TaskDetail.list(project_root, filter=...)` classmethod that returns a `list[TaskDetail]` in scheduler order.

`TaskDetail.list()` spec:
- Reads `state.json` queue once.
- Applies filters (stage/status/initiative/q).
- Does NOT reconstruct from worklog for list view (worklog-only entries have status=archived which users usually don't want cluttering the queue; filter-in via `status=archived` when needed).
- Attaches `age_heats` (derived from `budget.used` at creation, or lazy = None).
- Returns ordered per scheduler (same ranking Poker's drawer uses).

This avoids N+1 worklog reads for 100-row views.

### Q9 — Relationship to Poker + Upcoming + initiative deep-dive

**Four coexist, each strongest at a different zoom level:**

| UI            | Scope            | Primary use                          |
|---------------|------------------|--------------------------------------|
| Poker         | initiatives      | rank initiatives; expand to see tasks|
| Upcoming      | cross-project    | pin "do these next" across projects  |
| Deep-dive     | one initiative   | read ledger of one init's work       |
| **Cockpit**   | one project's queue | bulk steer tasks, change priorities |

The **row component is shared** between deep-dive and cockpit — same `_task_row.html` partial (t-364 already copy-pasted it once; this makes the case to lift it into a shared `templates/_partials/` directory).

Cross-links:
- Cockpit task_id → drawer (same as deep-dive)
- Cockpit initiative_id → deep-dive page
- Cockpit `open in Poker ↗` kebab entry
- Poker drawer `edit in Cockpit ↗` link (new — future polish)

---

## Wireframe

```
┌────────────────────────────────────────────────────────────────────────┐
│ Queue Cockpit — smithy2          stage[▼ any]  status[▼ pending]     │
│                                  ini[▼ any]    search: [ OAuth  ]   │
├────────────────────────────────────────────────────────────────────────┤
│ ▸ t-042 impl  pending  M:p0  you:p0 ↑↓✕  "ini-009 rank=1" ini-009 3h Wire OAuth…   ⋯ │
│ ▸ t-041 impl  pending  M:p0  you:—  ↑↓✕  —               ini-009 3h Email verifier ⋯ │
│ ▸ t-049 impl  pending  M:p2  you:—  ↑↓✕  "catch-up"      ini-009 1h Reset redirect ⋯ │
│ ▸ t-050 impl  deferred M:p3  you:— ↑↓✕  "scope creep"    ini-009 5h 2FA        ⋯ │
│ …                                                                      │
│  (108 visible · filtered from 312 total)                              │
└────────────────────────────────────────────────────────────────────────┘
```

Expand arrow `▸` slides open the TaskDetail drawer above/below the row (or as side-aside on wide screens). Close restores the flat list.

---

## Impl candidates (retro format — value thesis per)

### t-376-candidate — `TaskDetail.list()` aggregator + `/api/cockpit` endpoint (impl, p1)

Extend `smithy/smithy/task_detail.py` with classmethod `TaskDetail.list(project_root, *, stage=None, status=None, initiative=None, q=None, order="scheduler")` returning `list[TaskDetail]`. New Poker handler `GET /api/cockpit` wraps it, serializes via `to_api_dict()`, returns `{"rows": [...], "total": n, "filtered": m}`. Tests: filters (each independently + combined), empty-project, archived-exclusion default, order matches scheduler output from Poker's existing ranker.

**Value thesis:** Lift once, use twice. Once `TaskDetail.list()` exists, the cockpit render is pure template work, AND the initiative deep-dive could optionally adopt it for consistency. Tests trap the filter contract before any UI depends on it.

### t-377-candidate — Cockpit page template + gesture wiring (impl, p1)

`ui-priority-poker/templates/cockpit.html` + `/cockpit` handler. Renders the table per wireframe, consumes `/api/cockpit` for data, subscribes to `/events` for live refresh. Inline `↑ ↓ ✕` for human_priority reuse existing `/api/task/{id}/human-priority` POST (no new backend). Defer toggle reuses `/api/task/{id}/defer` / `/undefer`. Kebab populates dynamically with the long-tail actions. Drawer expand reuses TaskDetail drawer markup from Poker index.html (lift to `_task_drawer.html` partial as part of this task). Tests: page renders, filter params round-trip in URL, row action POSTs fire against correct endpoints (via mocked fetch).

**Value thesis:** Ships the actual UI. Depends on t-376 but not on any Bellows/Intent refactor. Visible feature completion point.

### t-378-candidate — Shared `_task_row.html` + `_task_drawer.html` partials (impl, p2)

Lift the task-row markup currently duplicated in Poker index.html (initiative drawer rows) + Bellows initiative.html into `ui-priority-poker/templates/_partials/`. Consume from Poker + Bellows + new cockpit. Tests: each consuming template still renders correctly after the lift (pure refactor, zero behavior change).

**Value thesis:** Pays down the template duplication debt before it triples with the cockpit. If deferred, the cockpit gets a third copy and any row-schema change needs three edits. Better as a separate task than bundled — clean diff, easy to revert if something breaks.

### t-379-candidate — Age derivation + polish (impl, p3)

Compute `age_heats` per task from worklog first-seen heat (fallback to state's `budget.used` at creation). Kebab menu items (set-reason, override-stage). Keyboard nav (`j/k` to move rows, `Enter` to expand drawer). Empty-state copy. 2-heats of polish + 2 tests.

**Value thesis:** Quality-of-life after the feature works. Deferrable — if users never ask for age or keyboard nav, we save the heats.

### t-380-candidate — Bulk actions (impl, p3, optional)

Selection checkboxes + bulk-defer, bulk-set-human-priority, bulk-move-initiative. Confirmation dialog. New POSTs `/api/tasks/bulk-defer`, `/api/tasks/bulk-human-priority`. Tests heavy here — bulk ops corrupt state faster than single-task ops if anything slips. Scope: 3-4 heats alone.

**Value thesis:** Real force-multiplier for sprint reshuffles. But genuinely big (selection UX + new endpoints + careful atomic-write tests) and optional — don't bundle.

---

## Ship order

**t-376 → t-377 (MVP is live here) → t-378 → t-379 → t-380 (optional).**

Total feasibility: 4-5 heats for MVP through t-377. t-378 is a 1-heat refactor. t-379 is 2 heats polish. t-380 stands alone (3-4 heats) if we do it.

Non-goals for v1:
- **No re-ranking in the cockpit** (use Poker for that).
- **No cross-project view** (Upcoming owns that).
- **No initiative editing** (Intent Editor owns that).
- **No server-side search debouncing** — URL-param filter is simple enough.
- **No saved views / presets** — URL is the save state.

Open questions (park until data):
- Does infinite scroll matter at 300+ tasks, or is server-side pagination enough? Measure first.
- Should archived tasks show at all without explicit filter? Gut says no, but check with human once cockpit ships.
