# Cross-Project Upcoming Tasks View — Design Study

**Task:** t-327 (research, ini-009). The v1.8 steerability arc (t-312→t-319) made per-project ranking work. The human's next ask: "I run multiple Forge projects from Bellows. I want one list of upcoming tasks across all of them, orderable, with pin-to-top semantics, so I can sequence my *day* — not just each project's queue."

This doc answers the six framing questions, proposes a schema + UX, and drops impl task candidates in retro format (value thesis per) for Marshal to scope.

---

## (1) Does Bellows enumerate multi-project today?

**Yes, read-only.** `bellows/forge_reader.py:325 discover_projects(base_dir)` walks `FORGE_PROJECTS_DIR` (default `~/vibes`), picks every immediate subdir containing `state.json`, runs `read_project()` on each, and sorts by `(signal red<yellow<green, -budget.used desc)`. Bellows has no write path to task queues today — all mutations go through `smithy` CLI invoked in a specific project dir, or through the steering UIs pointed at `FORGE_PROJECT_DIR`.

So the capability exists to **read** tasks across projects. Nothing writes cross-project state yet. Home page (`/`) shows project cards with signal+decisions+budget; `/briefing` collates decisions. No "tasks across projects" surface exists.

---

## (2) Global ordering — schema options

Three candidates:

### (a) New top-level `global_rank` field on each task
Each task gets an optional integer `global_rank` (null by default). `null` means "not pinned globally — use local sort." Non-null means "this task is globally position N among pinned tasks." Render order = `pinned by global_rank ascending` then per-project queued tasks interleaved.

**Pros:** Clean, obvious, mirrors `human_priority` semantics. Ordering survives local edits.
**Cons:** Storing global state inside per-project `state.json` creates a sync problem — the Upcoming view has to read N files and merge. Possibility of duplicate global_ranks if two projects get concurrent writes.

### (b) Derived order from existing fields
Order by `(human_priority ?? +inf, priority, project_name, id)`. No new field. Global pin = set `human_priority=0` on task. Demote = higher number.

**Pros:** Zero schema change. All existing UIs already respect `human_priority`. Auto-clear on complete already works.
**Cons:** Can't express "this task is #1 globally, that task is #1 locally" — one sticky value has to serve both roles. If `human_priority=0` means "global top," then local top has to start at 1, and a project with no global pins has to invent its own scale.

### (c) Separate `~/vibes/.upcoming.json` global index file
File at `FORGE_PROJECTS_DIR/.upcoming.json`: `{"pinned": ["<project>/t-042", "<project>/t-017"], "updated_at": "..."}`. Upcoming view reads this + each project's state.json to resolve.

**Pros:** One source of truth for global order. Mutations are single-file atomic writes. No schema change to state.json. Easy to audit.
**Cons:** Task can disappear (completed, deleted) and leave a dangling ID. Needs GC. Writes require knowing the project dir from a task ID — needs either `{project}/{task}` compound keys (ugly but explicit) or a separate lookup.

**Recommendation: (c) + compound keys.** Keep per-project `human_priority` semantics pure (local ordering only — what v1.8 shipped). Add a global layer that sits *above* the local one and composes by: `(globally_pinned_rank ?? +inf, human_priority ?? +inf, priority, id)`. One file, one writer at a time (Bellows), no per-project schema bump. Stale entries: GC on read — if the resolved task is complete or missing, drop it with a one-line toast.

---

## (3) Poker coupling — immediate re-score vs tick?

Two edge cases to consider:

- **User drags task A to global top** while project X's Poker is open in another tab, showing task A mid-queue. Does Poker reflect the pin instantly?
- **User completes task A in project X's Forge loop**. Does the global Upcoming list drop it within seconds or wait for refresh?

### Option: immediate re-score
Writing to `.upcoming.json` bumps its mtime. Every UI that cares (Poker, Timeline, Upcoming) watches the file via the same SSE `state-changed` pattern we already have for per-project state.json. This adds a second watched path per UI.

### Option: tick
Upcoming UI polls every 5s (like Timeline does for `/api/current-heat`). Poker ignores the global layer entirely — it shows local order only, and "globally pinned" is a badge applied at render time by reading `.upcoming.json` once per page load.

**Recommendation: tick, with one small lie.** The Upcoming view polls `.upcoming.json` + all project state.json mtimes via a single Bellows `/api/upcoming` endpoint (Bellows does the walking, returns a merged+sorted list). Frontend polls every 3-5s. Poker *shows* a small 📌 badge on pinned tasks (reading `.upcoming.json` once at page load) but doesn't try to keep it live — the per-project local view is the source of truth for the local user, and the pin badge is a courtesy. This keeps each UI's watch-set simple: poker watches its own state.json, Upcoming polls Bellows.

---

## (4) "Remove" semantics

When the user clicks `×` or drags a task out of the Upcoming list, what happens?

Four possible meanings, pick one:

- **Deprioritize** — set `human_priority` very high, still in per-project queue, gone from Upcoming. *Rejected:* reaches into per-project state, conflates global and local.
- **Defer** — add a `deferred_until` field. *Rejected:* we don't have time semantics anywhere else; introducing them here just for this view is overkill.
- **Delete** — `task.status = rejected` or remove from `queue[]`. *Rejected:* destructive, surprising, and the user probably only meant "not today."
- **Unpin** — remove from `.upcoming.json` pinned list. Task stays in its project queue at whatever local rank it already had. *Winner.*

So: "remove" == "unpin from Upcoming." The task is not touched. If the user wants it gone from the project too, they do that in Poker.

To make intent clear, render unpin as `×` on the right of each row with tooltip "Unpin from Upcoming (task stays in project)."

---

## (5) Drag-to-top interaction with `human_priority`

This is the trickiest one.

**Scenario:** Task t-042 in project X has `human_priority=5` locally (you want it soon in X). You also drag it to globally #1 in Upcoming. What happens next when Marshal in X picks a task?

**Answer: nothing changes locally.** Global pin does not leak into per-project scheduling. Marshal in X keeps picking based on `(human_priority or +inf, priority, id)`. Global pin only affects the *cross-project list ordering* shown in Upcoming. It's a calendar/day-planning layer, not a scheduler override.

Why: if a global pin silently rewrote per-project `human_priority`, we'd destroy the user's local ordering as a side effect of cross-project sequencing. The feature would punish the user for using it. So separate them.

**Consequence:** A task can be globally #1 but locally not-next-up, because its project has three other human-pinned tasks ahead of it. That's fine — the Upcoming view shows *what the user intends to get to in order*, not what Forge will execute next in each project. Those are different questions.

**If we want a "force this task to be the next pick in its project too" affordance:** expose it as a separate action — "Drag to top + pin locally" — which writes both `.upcoming.json` and per-project `human_priority=0`. Don't make it the default of a drag.

---

## (6) Surface — new Bellows page vs new UI?

The existing steering UIs (Poker, Intent, Timeline) each own one project via `FORGE_PROJECT_DIR` env var. Cross-project is architecturally Bellows' turf — Bellows already enumerates projects, already has its own port (8080), already has a home page with project cards.

**Recommendation: new Bellows route `/upcoming`.** Slots in next to `/` (home) and `/briefing`. Nav: "Projects · Upcoming · Morning Briefing." Render uses Bellows' existing Jinja templates and CSS. Endpoint `/api/upcoming` returns the merged list as JSON.

A fifth steering UI would be overkill — Upcoming is read-mostly with one write (pin/unpin), and the "one UI per concern" principle doesn't buy us isolation here because Upcoming fundamentally needs to see all projects.

---

## Wireframe

```
┌─ Bellows ──────────────────────────────────────────────────────────┐
│  Projects  ·  Upcoming  ·  Morning Briefing                        │
├────────────────────────────────────────────────────────────────────┤
│  UPCOMING TASKS — 7 pinned · 23 queued across 3 projects           │
│                                                                     │
│  📌 PINNED (drag to reorder)                                        │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ ≡ #1 smithy2/t-325   Task detail drawer wire     [impl] ×  │   │
│  │ ≡ #2 tasq-cli/t-042  CI workflow                 [impl] ×  │   │
│  │ ≡ #3 smithy2/t-326   E2E task detail test        [test] ×  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  UP NEXT (per-project, not pinned)                                 │
│  smithy2         t-328  Next poker polish          M:p1 you:— 📌  │
│  tasq-cli        t-043  coverage.xml               M:p2 you:— 📌  │
│  vibes-agents    t-017  chief-of-staff ident       M:p1 you:p5 📌 │
│  …more                                                             │
└────────────────────────────────────────────────────────────────────┘
```

Key interactions:
- Drag rows within PINNED to reorder → POST `/api/upcoming/reorder` with new `pinned: [...]` list
- `×` on pinned row → POST `/api/upcoming/unpin` with task ref
- `📌` on "Up Next" row → POST `/api/upcoming/pin` (appends to bottom of pinned)
- Click task id/desc → route to that project's Poker with `?task=<id>` (reuses t-325's deep link)

---

## Schema diff

**New file:** `$FORGE_PROJECTS_DIR/.upcoming.json`

```json
{
  "version": 1,
  "pinned": [
    {"project": "smithy2", "task_id": "t-325"},
    {"project": "tasq-cli", "task_id": "t-042"}
  ],
  "updated_at": "2026-04-12T18:22:00Z"
}
```

**No changes** to per-project `state.json` schema. Pinned-set GC happens on read in `/api/upcoming` — stale entries (completed, rejected, missing) are filtered out and the file is re-written atomically if the filtered list differs.

---

## Impl candidates (retro format — value thesis per)

### t-328-candidate — Bellows `/api/upcoming` endpoint + `.upcoming.json` read/GC (impl, p1)
Read all project state.json files, join against `.upcoming.json`, filter stale pinned entries, return `{pinned: [...], up_next: [...]}` sorted by (global pin rank, then per-project `human_priority or +inf, priority`). Atomic GC-write if filter changed anything. Unit tests: happy path, stale-entry GC, missing .upcoming.json (treat as empty).

**Value thesis:** Everything else depends on this endpoint. Without it, the UI can't render anything. Low-risk, small diff, fully tested.

### t-329-candidate — Bellows `/upcoming` page + Jinja template (impl, p1)
Render the wireframe above against `/api/upcoming`. Drag-to-reorder uses the same pattern as Poker's drag-drop (already shipped, proven). Pin/unpin buttons post to new endpoints (scoped to t-330). ESC closes nothing — this is a page, not a drawer. URL: `http://localhost:8080/upcoming`.

**Value thesis:** This is the thing the user asked for. Uses proven patterns from Poker for drag. Reads once per page + polls every 5s.

### t-330-candidate — Pin/unpin/reorder POST endpoints + tests (impl, p2)
`POST /api/upcoming/pin`, `POST /api/upcoming/unpin`, `POST /api/upcoming/reorder` — all mutate `.upcoming.json` under mtime precondition (reuse the pattern from v1.8). 409 on concurrent write. Tests: pin happy, duplicate pin (no-op), unpin happy, unpin-unknown (no-op), reorder with unknown id (skip), concurrent-write 409.

**Value thesis:** Completes the interaction loop. Small, testable, mtime-safe like the v1.8 UI endpoints.

### t-331-candidate — 📌 badge on Poker rows for globally-pinned tasks (impl, p3)
One-line-at-page-load read of `.upcoming.json`; if the current project has pins, render `📌` after `you:pN` on those drawer rows. No live update (see Q3 tick recommendation). Small CSS + template tweak.

**Value thesis:** Closes the loop — the user can see in Poker "yep, this one's also pinned globally," preventing the "where did my pin go?" confusion. Low urgency, tiny diff.

### t-332-candidate — E2E test (testing, p2)
Scaffold two tmp projects, pin a task from each, verify `/api/upcoming` returns them in pinned order; complete one, verify GC removes it on next read; unpin the other, verify empty state; reorder, verify ordering reflects in next GET.

**Value thesis:** Prevents regressions in the merge/GC logic — this is the one place bugs cause silent data loss (wrong task drops off Upcoming mysteriously).

---

## Non-goals for this feature

- No per-day scheduling / calendar integration. "Upcoming" means "in intended order," not "by deadline."
- No cross-project dependencies (task A in project X blocks task B in project Y). Schema doesn't support it and the use case is hypothetical.
- No mobile. Bellows is desktop-only today, keep it that way.
- No automatic pin expiry / cleanup beyond "task completed" GC.

---

## Recommendation summary for Marshal

**Ship order:** t-328 → t-329 → t-330 → t-332 → t-331 (badge is last because it's polish).

**Schema stance:** NEW file `.upcoming.json`, NO changes to `state.json`. Matches v1.8's "don't schema-bump unless forced" discipline.

**Coupling stance:** Global pin is a *sequencing* layer, not a *scheduling* override. Per-project Marshal keeps picking locally as it does today. Poker's 📌 is informational-only, refreshes on page reload.

**Blast radius:** entirely new Bellows routes + one new JSON file in `FORGE_PROJECTS_DIR`. No existing code paths modified. Rollback = delete the file + route.
