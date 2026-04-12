# Activity Side-Panel — Design (t-349)

**Date:** 2026-04-12, heat 770
**Origin:** `research/steering-patterns-retrospective.md` §6 #1 ("Unified violations/activity side-panel"). Revisited now that (a) constraints are retired (v1.8) and (b) `steering.log` exists (v1.9). The "violations" framing is obsolete; the "activity" framing is feasible and cheap.

---

## Framing questions

Six questions to answer before impl:

1. **What goes in it?** — pins, defers, deletes, reorders, recently-shipped tasks, or all of the above?
2. **Which UIs host it?** — Poker only, Poker + Timeline, or all 4 steering UIs?
3. **How fresh?** — poll every N seconds, SSE, or manual refresh?
4. **How wide is the time window?** — last 20 events, last 24h, last N heats?
5. **Is it read-only?** — or does it support click-to-jump / click-to-undo?
6. **Where does attribution stop?** — Forge's per-heat commits included, or only human-originated events?

---

## Answers

### Q1 — Content

The panel feeds from **two sources**, not one:

- **`steering.log`** (human events): pin/unpin/reorder, defer/undefer, human_priority flips, deletes
- **`worklog.tsv` tail** (Forge events): last N heats with their stage, task_id, value, signal

Unifying both answers "what's been happening?" — the entire point of the panel. Constraints are gone; violations are a non-concept; attribution is now the organizing idea.

### Q2 — Host UIs

**Start with Poker and Timeline only.**

- **Poker** has the most natural affinity — the panel *is* the activity around the tasks Poker shows. Already where most human steering originates.
- **Timeline** benefits from the timeline framing — events align naturally with the heat x-axis (and we already have markers from t-340 that the panel can row-echo in text form).
- **Intent Editor** is low-activity (edits are rare, themes/initiatives change slowly). Skip.
- **Bellows** has its own overview — a side-panel would compete with the activity feeds it already renders.

**Retro §6 #1's original framing included all three steering UIs.** Narrowing to two reduces sync surface by a third and matches where users actually need it.

### Q3 — Freshness

**Poll every 5s** (matches Timeline's existing cadence). SSE is overkill — the panel is a peripheral surface, not primary UI. A 5s lag on "what just got pinned" is fine.

Bonus: a single shared `/api/activity` endpoint on each host can be cached with a short TTL if load becomes a concern later. Start without caching.

### Q4 — Window

**Last 20 events, ordered newest-first.** Users who want more can click through to a full log view (`GET /api/steering-log` or `GET /api/project/<n>/steering-log`).

20 is enough to span a "recent working session" without scrolling. Below 10 feels sparse; above 30 becomes noise.

### Q5 — Read-only vs interactive

**Read-only in v1. Click-to-jump in v2.**

Interactivity is where bugs live. Start with a reliable read-only panel, measure whether users actually want to jump from an event to the task. If yes, add `<a href="/#task-<id>">` anchors. Don't build undo — `steering.log` is append-only for a reason, and the mutation endpoints already support inverse operations (unpin, undefer, etc.) directly.

### Q6 — Forge events in scope?

**Yes, with a clear visual separator.** The panel's value proposition is "what's happening" — excluding Forge heats cuts out 90% of motion. But mark them differently (different icon, muted color) so human steering stays legible.

---

## Proposed schema

Each panel entry is a struct with a common shape regardless of source:

```
{
  "when": "2026-04-12T10:30:00Z",
  "heat": 770,
  "origin": "steering" | "forge",
  "actor": "bellows-poker" | "forge" | "human:mangesh",
  "task_id": "t-347",
  "verb": "pinned" | "unpinned" | "deferred" | "completed" | "started" | "priority-set" | "deleted" | "reordered",
  "detail": "null → 0" | "0.85 🟢" | "rank 2" | ...,
  "source": "poker-drawer" | "worklog" | ...
}
```

The panel renderer just iterates the list and picks an icon + phrase per `verb`:

- `pinned` → 📌 "pinned t-347"
- `deferred` → ⏸ "deferred t-347"
- `completed` → 🟢 "completed t-347 (value 0.85)"
- `priority-set` → ↑ "set t-347 priority null → 0"

One-line entries. No nesting. No expansion. The full row is available via the corresponding API.

---

## Proposed API

One new endpoint per host UI (Poker and Timeline), identical shape:

```
GET /api/activity?limit=20&since=...
→ { "count": 20, "entries": [ {…}, {…}, … ] }
```

Implementation:
- Load `steering.log` (last N rows) and `worklog.tsv` (last N rows) filtered by `since`
- Merge, sort by `when` desc, truncate to `limit`
- Transform steering rows to `origin=steering`, worklog rows to `origin=forge`
- Lift verb from `field + before/after` pattern for steering rows; from `outcome + signal` for worklog rows

The helper lives in a shared module — `smithy/smithy/activity.py` or extend `steering_log.py` with a merged-view function. Prefer a new module so the per-row parsing rules are isolated from the append-only logger.

---

## Proposed UI

A narrow right-aligned column (~280px) on Poker and Timeline:

```
┌──────────── ACTIVITY ─────────┐
│ h770 · just now               │
│  🟢 forge completed t-347     │
│                                │
│ h769 · 1m ago                 │
│  📌 mangesh pinned t-347      │
│                                │
│ h768 · 3m ago                 │
│  ⏸ mangesh deferred t-340     │
│                                │
│ h767 · 5m ago                 │
│  🟢 forge completed t-346     │
│                                │
│ [ view full log → ]           │
└────────────────────────────────┘
```

- Heat + relative time header per entry
- Icon + actor + verb + task_id on one line
- No body text, no expansion
- `[ view full log ]` link → Bellows `/api/project/<n>/steering-log` full dump

Collapsed state = a single bar saying "N events · expand" for users who want maximum horizontal room.

---

## Non-goals

- **No global aggregation across projects.** The panel is project-scoped. Cross-project activity = Bellows's concern.
- **No per-user filtering.** X-Actor data is useful in retros, not in a 20-item panel.
- **No notifications / toasts.** The panel is passive. Big behavioral changes (budget exhaustion, task blocked) belong in existing decision queues.
- **No undo.** Mutations are reversible via their inverse endpoints; the log is append-only on purpose.

---

## Impl candidates (retro format — value thesis per)

### t-352-candidate — Shared `activity.py` merged-view helper (impl, p2)
New module `smithy/smithy/activity.py` with `read_activity(project_root, limit=20, since=None)` that merges steering.log + worklog.tsv tails into the common entry schema. Unit tests on the merge/sort/verb-mapping logic. No UI yet.

**Value thesis:** The merge logic is the hardest part. Landing it as a tested helper decouples schema questions from UI questions, and unlocks both Poker and Timeline panels in parallel. 80% of the bug surface for the whole feature, in one tightly-scoped module.

### t-353-candidate — `GET /api/activity` endpoint on Poker + Timeline (impl, p2)
Thin wrappers over the shared helper, one per UI. Consistent query surface (`limit`, `since`). Tests: empty-state, mixed steering/forge entries, verb mapping for all recognized patterns, large `limit` cap.

**Value thesis:** Locks the JSON contract before any frontend code exists. Frontend can be prototyped against `curl` output; backward-compatibility for the panel is now an API-versioning question, not a UI-refactoring question.

### t-354-candidate — Poker activity side-panel render (impl, p2)
Right-aligned column in `ui-priority-poker/templates/index.html` + CSS + JS fetch loop (5s poll). Read-only. `[view full log]` link to Bellows. Tests: HTML element present, JS polls the endpoint, entries render with correct icon per verb.

**Value thesis:** Poker is where humans spend the most time steering. Shipping here first validates the "is this useful?" question with the highest-leverage surface. If users don't use it on Poker, they won't use it anywhere.

### t-355-candidate — Timeline activity side-panel render (impl, p3)
Parallel to t-354 but on Timeline. Bonus: row echoes the same events the steering-trigger lane markers from t-340 already render, in textual form — accessibility win for users who can't see the markers or want to read on mobile.

**Value thesis:** Reuses the t-354 CSS/JS with near-zero incremental cost. Worth it once the Poker version is validated; skip if Poker panel shows low engagement.

### t-356-candidate — Click-to-jump task anchors (impl, p3)
Wrap `task_id` in entries with `<a href="#task-{id}">`. Poker task rows get `id="task-{id}"` anchors. On-click scrolls the main panel to the referenced task and briefly highlights it.

**Value thesis:** Only valuable if users have told us "I saw an event and wanted to go look at that task." Gate on user feedback — don't build on spec.

---

## Recommendation summary

**Ship order:** t-352 (helper) → t-353 (API endpoints) → t-354 (Poker render) → pause, gather feedback → t-355 (Timeline render) → t-356 (click-to-jump if warranted).

Total feasibility cost: roughly 4-5 heats across the full stack. The heaviest box is t-352 (parsing both log formats into a common shape); the others are thin wrappers once that exists.

**Decision needed from team-lead:** approve ship order, or pick a subset.
