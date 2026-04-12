# Initiative Deep-Dive Page — Design (t-362)

**Date:** 2026-04-12, heat 781
**Origin:** Team-lead ask via Marshal. Per-initiative page showing intent + all tasks (grouped) + upcoming-for-this-initiative. Poker initiative-title click navigates there. `ini-009` tracks the feature.

---

## Six framing questions

### Q1 — Route location

**Verdict: Bellows `/project/{name}/initiative/{ini-id}`.**

Bellows already hosts `/project/{name}`, `/project/{name}/board`, `/project/{name}/decide`, `/project/{name}/direct`, `/project/{name}/diff` (bellows/app.py:109, 123, 156, 256, 343). The route pattern, nav, SSE, and project-resolution helpers are already in place — another segment costs nothing.

Rejected alternatives:
- **Poker `/initiative/{id}`** — forces per-UI duplication. Poker is ranking-focused; a deep read surface belongs on the dashboard.
- **Standalone ui-initiative app** — a fifth port for a read-mostly surface doesn't clear the bar.

### Q2 — Intent schema

**Audit of `state.json` initiatives today (smithy2, 15 initiatives):**

```
union keys: budget_cap, description, heats_used, id, planned_end,
            planned_start, rank, status, theme_id, title, viewed_at
```

**There is no `intent` field.** "Intent" in practice = the `description` text. The Intent Editor UI writes `description` on apply; nothing writes a separate field. Checking the codebase: zero readers of `initiatives[].intent`.

**Recommendation:** For v1 the deep-dive page renders `description` under an "Intent" heading. No schema migration. If/when the team wants narrative intent separated from a one-line summary, introduce `long_intent: str?` additive and fall through to `description` when absent. The deep-dive will be the primary surface that makes the gap legible, which is the right time to decide.

**"Edit in Intent Editor" link:** The Intent Editor (`ui-intent-editor` :8003) doesn't have per-initiative deep-link today, but it does render theme/initiative cards. Link should point to `URL_INTENT` root with `?focus=<ini-id>` as a hint anchor; Intent Editor can wire the scroll later (small follow-up). Avoid blocking the deep-dive on an Intent-Editor change.

### Q3 — Upcoming-per-initiative source

**Verdict: filter `.upcoming.json` by `initiative_id` resolved via the queue — do NOT introduce a per-initiative pin list.**

`.upcoming.json` today holds a flat `pinned[]` of compound keys `{project_name, task_id, rank}` (`bellows/app.py:440-486`). Each pinned task resolves back to a queue row; each queue row carries an `initiative_id`. So:

```
upcoming_for_initiative(ini_id) =
   [row for row in resolve_upcoming()
    if queue_row(row.task_id).initiative_id == ini_id]
```

**Why not a separate per-initiative pin list:**
- Duplicates the single source of truth (`.upcoming.json`).
- Cross-initiative pin ordering lives globally — per-initiative lists force a synchronization dance.
- Filtering is O(pins), which is trivial even at 100+ pins.

The existing `_resolve_upcoming` helper already returns `pinned_live`; the deep-dive route just filters that list.

### Q4 — Tasks section

**Grouping, in order:**
1. **In-flight** (status=in_flight or .forge-checkpoint match)
2. **Upcoming (pinned)** — the filtered `.upcoming.json` subset
3. **Queued** — status=pending, not pinned
4. **Deferred** — status=deferred
5. **Shipped** — status=complete, newest-first

**Columns per row:**
`[task_id] [desc] [stage] M:p{priority} [· priority_reason] [you:{hp}] [↓]`

Same schema as Poker's drawer rows (ui-priority-poker/templates/_task_row.html) — reuse the partial rather than redefine the layout. One column table across all groups; section headers between groups.

**`human_priority` display:** show `you:—` when null, `you:p{n}` otherwise. Click the task_id → opens the task drawer in place (inherits Poker's `?task=` param behavior; see Q6).

### Q5 — Poker click affordance

**Verdict: title-only click navigates.**

The card body already toggles drawer-expand on click (ui-priority-poker/templates/index.html:33). Wrapping the whole card in a nav click would break expand. Wrapping only `.card-title` in an `<a href>`:
- Preserves drag, expand, kill-button affordances.
- Matches existing pattern (task-id click in the drawer opens task detail).
- Discoverable via hover underline.

The weight badge and other meta stay inert. On hover, the title shows underline + pointer cursor.

### Q6 — Breadcrumb + `?task=` preservation

**Verdict: breadcrumb is a single back-link. `?task=` is preserved losslessly via existing task-drawer pattern.**

```
Poker → Build X (ini-001) → t-042 [drawer]
```

- **Crumb row** at top of deep-dive: `← Poker` (left), `ini-001 · Build X` (title), `Intent Editor ↗` (right).
- **Task click** on deep-dive row fires an XHR to `/api/task/{id}` and opens the same slide-in drawer Poker uses (task-detail.html partial). URL becomes `/project/x/initiative/ini-001?task=t-042`. Back-button in drawer closes; back-button in browser returns to Poker.
- **Deep-link:** landing on `.../initiative/ini-001?task=t-042` auto-opens the drawer on mount.

The task-drawer component currently lives in Poker's index.html. **To reuse on Bellows**, lift it into a shared partial or copy-paste the ~80 lines into the deep-dive template. Copy-paste is fine for v1 — the drawer has been stable since t-325, and the lift risks touching a stable piece for no immediate benefit.

---

## Wireframe

```
┌────────────────────────────────────────────────────────┐
│ ← Poker                                Intent Editor ↗ │
├────────────────────────────────────────────────────────┤
│                                                         │
│  ini-001 · Build X                   rank #1 · approved │
│  theme: Core Flow                        weight 3× · p0 │
│                                                         │
│  [ intent ]                                             │
│  Build out the golden-path auth flow covering signup,  │
│  login, password reset, and OAuth…                     │
│                                                         │
│  [ progress ]                                           │
│  ████████▓▓▓▓▓▓▓▓  7 / 20 heats                        │
│                                                         │
│ ──── TASKS ────                                         │
│                                                         │
│  In-flight (1)                                          │
│  ▸ t-042  impl  Wire OAuth handshake    M:p0  you:—   ↓│
│                                                         │
│  Upcoming (2)     [ ⭐ pinned via Bellows Upcoming ]    │
│  ▸ t-041  impl  Email verifier          M:p0  you:p0  ↓│
│  ▸ t-045  test  E2E login flow          M:p1  you:—   ↓│
│                                                         │
│  Queued (5)                                             │
│  ▸ t-049  impl  Reset flow redirect     M:p2  you:—   ↓│
│  …                                                      │
│                                                         │
│  Deferred (1)                                           │
│  ▸ t-050  impl  2FA (scope creep?)      M:p3  you:p999↓│
│                                                         │
│  Shipped (12)                           ▸ expand        │
│                                                         │
└────────────────────────────────────────────────────────┘
```

Right-rail: activity side-panel (same component as Poker), filtered to this initiative's task_ids — but gate on feedback from single-panel version first. Out of scope for v1.

---

## Impl candidates (retro format — value thesis per)

### t-363-candidate — Bellows route `/project/{name}/initiative/{id}` + data layer (impl, p1)
New FastAPI handler. Loads project state, finds the initiative by id, filters `queue[]` by `initiative_id`, calls `_resolve_upcoming()` and filters to this ini's tasks. Returns JSON at `/api/project/{name}/initiative/{id}` mirror for tests + headless consumers. 8-10 tests: 404 on unknown ini, empty state, task grouping, pinned filter, shipped ordering.

**Value thesis:** All reads consolidated in one handler. Once this lands, the render template is the cheap part — all the schema questions (Q3-Q4 resolution) are trapped behind tests. If any future "unified activity" or "per-initiative digest" work wants the same data, it imports the helper.

### t-364-candidate — Deep-dive template + task drawer copy-over (impl, p1)
Jinja template rendering the wireframe above. Copies the task-drawer partial from Poker (index.html:137-179 + associated JS) into a shared Bellows asset. Tests: HTML contains intent block, each group section renders when non-empty, `?task=` auto-opens drawer.

**Value thesis:** Shipping the UI without a template is vapor; shipping without the drawer breaks the promise of "click a task to inspect." Bundling keeps the v1 seam narrow — no cross-app component plumbing until there's a second consumer.

### t-365-candidate — Poker title → deep-dive link + route tests (impl, p2)
Wrap `.card-title` in `<a href="{URL_BELLOWS}/project/{project}/initiative/{id}">`. Plumb `URL_BELLOWS` + project name through to the template context. One regression test verifying the link exists and resolves per the env-var.

**Value thesis:** Turns the feature on without touching user habits. Anyone who doesn't click keeps their workflow; anyone who clicks gets the new surface. Zero-risk introduction.

### t-366-candidate — `?focus=<ini-id>` hint in Intent Editor (impl, p3)
Read `?focus=` on mount, scroll the matching card into view, highlight for 2s. Enables the deep-dive's "Intent Editor ↗" crumb to land usefully.

**Value thesis:** Closes the breadcrumb loop. Tiny scope (20 lines of JS + 1 CSS rule), but easy to defer until someone actually clicks the link and complains.

---

## Ship order

**t-363 → t-364 → t-365 → t-366 (optional).**

Total feasibility: 4-5 heats. t-363 (data + tests) is the heaviest box; t-364/365 are thin once the JSON is solid. t-366 is "when someone asks."

Non-goals:
- **No write endpoints.** The page is read-only; edits stay in Intent Editor + Poker + Bellows Upcoming.
- **No per-initiative side-panel** in v1 — reuse Poker's general activity panel via its existing link.
- **No Intent-Editor deep-link API** — hash anchor + best-effort scroll is enough.
