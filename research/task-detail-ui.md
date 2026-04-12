# Task Detail UI — Design Sketch

**Task:** t-323 (research, ini-009). Design the affordance that answers "what's the full story on this task?" when a user sees a row like `t-042 add CI workflow M:p1 · ini-003 rank=1 + poker you:p5 [↓]` and wants more context.

## Decision summary

- **Form factor:** side drawer (right-slide), NOT modal, NOT dedicated page.
- **Click target:** task-id cell (`.drawer-task-id`), plus keyboard `Enter` on focused row. Not the whole row — the row already owns the `↓` and `you:pN` click targets.
- **Scope:** read-mostly. One mutation affordance (set/clear `human_priority`) matching what the row already offers. Everything else is a link out.
- **Close:** ESC, click-outside, or explicit `×`. URL gets `?task=t-042` so the view is linkable and back-button works.

## Why a drawer

**Modal.** Heavy. Blocks background. Kills the "keep Poker open while Forge runs" use case. Most rejections of Poker as "not glanceable" traced back to modals in other tools. Skip.

**Dedicated page (`/task/t-042`).** Over-indexes on permanence. Task detail is ephemeral — you peek, you close. A full page forces a navigation transition and loses the initiative context. Also duplicates Bellows' per-project views. Skip.

**Side drawer.** Preserves the Poker board as the spatial anchor (initiatives still visible, ordering intact), slides in over the right 40% of viewport, URL-syncs so deep-linking works, dismisses instantly. Matches the "glance layer above the board" mental model we already have for the per-initiative drawer. This is the winner.

Drawer stacks cleanly with the initiative drawer: if the initiative drawer is expanded and a task within it is clicked, the task drawer overlays from the right. ESC closes task first, then initiative.

## Fields (top to bottom)

Grouped into three bands. Compact typography — this is a detail pane, not a dashboard.

### Band 1 — Identity (always visible)

- **`task.id`** — mono, large (e.g. `t-042`)
- **`task.desc`** — full text, wraps, no truncation
- **`task.stage`** — pill badge, color-coded by stage (research=blue, impl=green, testing=yellow, editing=purple, marketing=orange)
- **`task.status`** — `pending` | `in_progress` | `complete` — dot + label

### Band 2 — Priority (the point of the view)

- **`task.priority` (M:pN)** — Marshal's number
- **`task.human_priority` (you:pN | —)** — editable inline (number input + `clear` button). Same semantics as the row `↓` button: POST `/api/task/{id}/human-priority` with `{value: int|null}`.
- **`task.priority_reason`** — ≤40 char string, read-only, mono. Tooltip on hover explains the signal vocab.
- **`task.initiative_id`** → link to Poker card (scrolls board, flashes the card)
- **`task.blocked_by`** — list of task IDs; each links to the same drawer (replaces current content)

### Band 3 — History

- **Priority-change events** — chronological list. Each row: `YYYY-MM-DD HH:MM · source (marshal|human|system) · p{from}→p{to} · reason`. This is new — it requires either a `task.history` array on the task or a derived log. See impl notes below.
- **Worklog mentions** — every `worklog.tsv` row where `task_id == t-042`. Columns: `heat · stage · value · notes`. Collapsed by default if >5 rows; "Show all" expands.
- **Commits** — optional stretch. Parse `git log --grep="t-042"` and list `sha · subject`. Defer to a follow-up; the worklog already captures most of this via the `notes` column.

## Click target — why the id cell, not the whole row

The row already has two click targets: `↓` (downrank) and `you:pN` value (toggle/edit). Making the whole row a link-to-detail creates fighting affordances — user misclicks `↓` meaning to open detail, or vice versa. Solution:

- **`.drawer-task-id`** is the detail target. Styled underlined-on-hover, cursor:pointer.
- **`.drawer-task-desc`** is also a detail target (shares the click handler — long text invites wanting more).
- Everything else (`M:pN`, `priority_reason`, `you:pN`, `↓`) keeps its current behavior.
- Keyboard: `Enter` on a focused row opens detail; `j`/`k` navigate between rows; `ESC` closes.

This matches the GitHub issues list pattern — title clicks open, action buttons stay independent.

## Backend shape — what `GET /api/task/{id}` needs to return

Input to t-324 scoping:

```json
{
  "task": { ...full task object from state.queue... },
  "initiative": { "id": "ini-003", "title": "...", "rank": 1 } | null,
  "history": [
    {"ts": "2026-04-12T11:20:00Z", "source": "marshal", "field": "priority", "from": null, "to": 1, "reason": "ini-003 rank=1 + poker"},
    {"ts": "2026-04-12T11:34:00Z", "source": "human",   "field": "human_priority", "from": null, "to": 5, "reason": "you:p5"}
  ],
  "worklog": [
    {"heat": 741, "stage": "editing", "value": 0.85, "signal": "🟢", "timestamp": "...", "notes": "..."},
    ...
  ]
}
```

**History source:** we don't store a history array on tasks today. Two options for t-324:

1. **Derive from worklog** — every heat writes `task_id` and we can infer priority-change events at commit boundaries. Cheap, no schema change, but lossy (priority changes between heats aren't captured).
2. **Append to `task.history[]`** — add a new field, mutate in `set_priority` / `queue-push` / `set-next-tasks` / `set-human-priority`. Accurate but schema bump.

**Recommendation for t-324:** start with (1) — derive from worklog for display, and the `priority_reason` string is the canonical current explanation. If users complain "I want to see every change," we do (2) later. This matches the v1.8 stance on `completed_at` ("don't schema-bump until a real case forces it").

## Non-goals (out of scope for t-325)

- No inline desc editing. Task description changes via `smithy add-task` / future CLI. Drawer is read-mostly.
- No "reassign initiative" affordance. Rare, and the wrong level for this view.
- No blocked_by editing. Same reasoning — CLI-level operation.
- No commits list. Defer to follow-up.

## Wireframe (ASCII)

```
┌─ Priority Poker ────────────────────────┬─ Task Detail ──────────────┐
│ #1 ini-003 Testing Infra  3×          ▼│ t-042                  [×] │
│   └─ drawer                             │ ───────────────────────── │
│      In-flight                          │ add CI workflow for pytest │
│      t-042 add CI workflow M:p1 you:—  ←│                            │
│      Queued (3)                         │ [impl] [pending]          │
│      t-043 coverage.xml    M:p2 you:—  │                            │
│      Shipped (1)                        │ PRIORITY                  │
│        ...                              │   Marshal: p1             │
│                                         │   You:    p5  [clear]     │
│ #2 ini-005 Auth  2×                    │   Reason: ini-003 rank=1  │
│                                         │           + poker         │
│                                         │   Initiative: ini-003 →   │
│                                         │   Blocked by: none        │
│                                         │                            │
│                                         │ HISTORY                   │
│                                         │   2026-04-12 11:20        │
│                                         │   marshal · p?→p1         │
│                                         │   (ini-003 rank=1+poker)  │
│                                         │   2026-04-12 11:34        │
│                                         │   human · hp:null→p5      │
│                                         │                            │
│                                         │ WORKLOG (2)               │
│                                         │   h741 editing 🟢 0.85    │
│                                         │   "drawer containment..." │
└─────────────────────────────────────────┴────────────────────────────┘
```

## Open questions for t-324/325

- **URL convention:** `?task=<id>` at the poker page, or `/task/<id>` as a separate route that renders the full Poker + drawer? I lean `?task=<id>` — back button stays on Poker.
- **Focus behavior:** when drawer opens via click, focus should land on `×` (matches Radix/headlessui conventions for dismissable panels).
- **Mobile:** <600px drawer becomes full-width bottom sheet. Low priority — Poker is laptop-first.

## Recommendation for t-324

Start with `GET /api/task/{id}` returning the shape above. Derive history from worklog (option 1). Tests: not-found 404, basic shape, worklog filter by task_id, history ordering. No frontend wiring yet — that's t-325.
