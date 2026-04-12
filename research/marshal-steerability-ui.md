# Marshal Steerability UI — Design Study

Commissioned by Marshal (via t-309, ini-009). Audits Priority Poker for the human-rank vs agent-priority distinction and sketches a path to give the human one-gesture downrank of Marshal's decisions without breaking Poker's "rank is steering" metaphor.

## 1. The Gap Marshal Named

There are **two** prioritization signals in the system, and right now they live on different objects:

| Signal | Lives on | Who writes | Units |
|---|---|---|---|
| **Human rank** | `initiatives[].rank` | Human (via Poker drag) | 1..N ordering |
| **Agent priority** | `queue[].priority` | Marshal (via CLI/logic) | integer tier (1 highest, 3 low) |

Poker shows initiatives ranked by human, annotated with task-count aggregates. Marshal sees the queue. **Neither surface shows both signals on the same atoms.** Consequences:

- The human can't see that Marshal dropped task t-310 from priority 1 to priority 3 this morning — invisible in Poker (which doesn't show tasks at all) and invisible in Bellows (which shows decisions but not priority changes).
- The human can't one-gesture *override* a Marshal priority call. The only lever is reordering *initiatives* in Poker, which indirectly reshapes which initiative Marshal pulls tasks from, but does NOT touch `queue[].priority` on a specific task.
- Completed tasks vanish from Poker's task-count badge, which is correct for volume signal but erases history — the human can't glance-review "what did Marshal ship on this initiative since I last looked?"

The design task: give the human a surface where initiative-rank (goal-level) and task-priority (atom-level) are **co-visible**, with a one-gesture override.

## 2. Poker Audit — What It Does Well

- **Rank IS steering** (already validated by retro §3). Drag-to-reorder is the lightest possible gesture.
- **Filters noise** aggressively: proposed/rejected/completed initiatives are partitioned, not mixed.
- **Theme grouping** via `theme_id` gives cheap hierarchy without a tree widget.
- **Forge activity indicator** (pulsing heat label) tells the human whether their steering is about to bite.
- **SSE-driven live updates** mean Marshal's writes appear within 2s — no refresh needed.

## 3. Poker Audit — What's Missing For Task-Level Steering

- **Tasks are opaque.** `ini["task_count"]` is the only task signal; `tasks` is populated in the route but templates only render counts.
- **No `queue[].priority` awareness.** The initiative card has no "this initiative's tasks are currently priority 1 across the board" summary.
- **No completed-task history.** Status-filter drops completed tasks; no way to see "tasks Marshal shipped since my last visit."
- **No per-task gesture.** Poker has initiative-level gestures only (reorder, approve, reject). To downrank a task, you'd need a different surface.
- **No sign of Marshal's reasoning.** If Marshal downranked a task due to a blocker, the human sees the effect but not the cause.

## 4. Design Sketch — Two Options

### Option A: Extend Poker (augmented card)

Each initiative card expands on click to reveal a **task drawer** with three sections:

```
┌─ 🃏 Auth System                               (rank 1, 8 tasks) ─┐
│   weight ●●○○                              pulse: heat 724 [impl]│
│                                                                   │
│   ▾ IN FLIGHT (2)                                                 │
│     ⭐ t-291  Build login flow           M:p1 · you:——            │
│     ⭐ t-293  OAuth callback             M:p1 · you:——            │
│                                                                   │
│   ▾ QUEUED (4)                                                    │
│     ○  t-301  Session store              M:p2 · [↓downrank]       │
│     ○  t-302  Rate-limit tests           M:p3 · [↓downrank]       │
│                                                                   │
│   ▾ SHIPPED SINCE LAST VISIT (2)        [dismiss all]             │
│     ✓  t-289  Add bcrypt                 heat 722, 🟢             │
│     ✓  t-290  Password reset UI          heat 723, 🟢             │
└───────────────────────────────────────────────────────────────────┘
```

Gestures added:
- **Click row → expand** the drawer.
- **[↓downrank]** button on queued row → POST `/task/{id}/downrank`, writes `human_priority: <current+1>` onto the task. The human override is a *separate field* from Marshal's `priority` — both co-visible ("M:p1 · you:p3"), and Marshal's scheduler respects `max(priority, human_priority)`.
- **[dismiss all]** on shipped section → stamps `viewed_at` on the initiative, clearing the badge.

Pros: leverages existing Poker UX, one place to steer. Cons: card gets visually heavy; Poker's "minimalist ranking" identity dilutes.

### Option B: New "Marshal's Desk" surface

A fifth steering UI at port 8005, showing the **task queue** flat, sorted by effective priority, with Marshal's priority and the human's override side-by-side:

```
┌ Marshal's Desk ──────────────────────────────── queue depth: 14 ┐
│                                                                 │
│  effective  M-priority  human  task                             │
│      1          1         —    t-291 Build login flow           │
│      1          1         —    t-293 OAuth callback             │
│      2          2         —    t-301 Session store     [↓] [↑]  │
│      3          3         —    t-302 Rate-limit tests  [↓] [↑]  │
│  ─── shipped today ──────────────────────────────────────────── │
│                 2        ✓     t-290 Password reset UI  heat 723│
│                 1        ✓     t-289 Add bcrypt         heat 722│
└─────────────────────────────────────────────────────────────────┘
```

Gestures:
- **[↓][↑]** per row → one-click nudge of `human_priority`.
- Shipped-today section acts as audit log.
- Optional: filter by initiative (links back to Poker).

Pros: task-level steering has its own dedicated cognitive space; keeps Poker clean as the "goals" board. Cons: adds a fifth UI (nav widens, doc burden grows), splits human's attention between two surfaces.

## 5. Recommendation

**Option A, with a cautious scope.**

Reasoning:
1. **Retrospective §4 and §7 already warned:** "should we build a fifth UI" should be gated on "does it answer a question none of the existing four does?" — and Option B doesn't really answer a new question. It just shows the same data (queue) at a different granularity. That's not a new mode; it's a zoom level.
2. **The "extend" concern ("Poker gets heavy") is solvable by default-collapsed drawers.** The card stays minimal in its resting state. Expansion is opt-in per-card, per-session.
3. **Option A preserves the shared-substrate win from retro §1.** Everything stays written to `state.json` (new field: `queue[].human_priority`, `initiatives[].viewed_at`). No new server, no new nav link to port-sweep in six months.
4. **The "one-gesture downrank" is genuinely lightweight** in Option A — already within a card the human has opened. Option B's row buttons aren't cheaper; they just live in a different frame.

If we build Option A and it feels heavy after a week of use, that's the signal to split out Option B — but *only then*, and only with the drawer UI deleted from Poker on extraction. Don't build both.

## 6. Scope For A Concrete Task

If the recommendation sticks, the minimum ship is:

1. **state.json schema:** add optional `queue[].human_priority` (int, default null) and `initiatives[].viewed_at` (ISO timestamp, default null).
2. **Marshal scheduler change:** when sorting the queue, use `effective = min(human_priority or inf, priority)` (lower=higher-priority in current convention).
3. **Poker backend:** expand `index()` to attach tasks grouped by (in_flight / queued / shipped-since-viewed) to each initiative dict; new endpoints `POST /task/{id}/downrank`, `POST /initiative/{id}/mark-viewed`.
4. **Poker template:** expandable drawer per card with the three sections and gestures.
5. **Tests:** drawer render, downrank write, viewed_at stamp, filtering.

Estimate: 3-4 heats (1 schema/backend, 1-2 template, 1 tests). Nothing touches Marshal's core logic except the sort key.

## 7. Open Questions (For Anvil/Marshal)

- **Should human downrank be sticky or decay?** If the human downranks a task and Marshal replans an hour later, does the override still bind? Proposal: sticky until the task completes or the human clears it.
- **How does this interact with blocked_by?** Today `blocked_by` is a hard block; human_priority is a soft nudge. Probably orthogonal, but worth a test.
- **Do we show Marshal's *reasoning* too?** Out of scope for this study, but a natural next step: a one-line "why this priority" string Marshal writes when it sets priority. Requires Marshal CLI change.

## 8. References

- `ui-priority-poker/app.py` — current implementation (174 LOC)
- `research/steering-patterns.md` §3 — "ranking IS steering" argument
- `research/steering-patterns-retrospective.md` §7 — "should we build a fifth UI" guardrail
- Retro §6 candidates — this closes #6 (steering→outcome attribution) partially by making Marshal's priority decisions visible
- State shape: `state.json` queue entries currently `{id, stage, desc, status, priority, blocked_by}` — no `human_priority` field yet
