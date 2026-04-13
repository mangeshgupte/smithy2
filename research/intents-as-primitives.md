# Intents as Primitives — Design Study (Reframe)

**Task:** t-405 (ini-017, research) · 2026-04-13
**Supersedes:** `research/intent-hierarchy.md` (kept as counter-proposal)
**Companion notes:** `research/intent-schema-gaps.md` (t-384 seed audit),
`research/intent-template-library.md`

## Thesis (the reframe)

`intent-hierarchy.md` modeled intent as a **level-aware concept**: project
intent inherits down through initiatives into tasks, resolver walks up
until it finds non-null text, editors switch "mode" depending on which
level you're editing. That model smuggles a hierarchy into a field.

**Reframe, 2026-04-12:** intent is a **primitive**, not a level. Every
unit of work — project, initiative, task — has the *same-shape* intent
field. A single nullable string. No level distinction in storage.
Whether the project's intent happens to be the "umbrella" for an
initiative's intent is a property of the view, not of the data.

The hierarchy is still useful — but as **one view among several**, not
as the schema.

## 1. Schema

One additive field, same shape, on three already-existing unit types:

```jsonc
{
  "commander_intent": { ... },            // unchanged (project-level intent)
  "initiatives": [
    {"id": "ini-016", "title": "Queue Cockpit",
     "intent": "Give the human a way to steer work async",
     "intent_source": "t-384",
     "intent_updated_at": "2026-04-12T..."}
  ],
  "queue": [
    {"id": "t-389", "initiative_id": "ini-016",
     "intent": null,
     "intent_source": null,
     "intent_updated_at": null}
  ]
}
```

Every `intent*` triple is the same shape. No `intent_override`, no
"inherit" flag — the absence of value simply means "unstated." A
view may choose to fall back to a container's intent when displaying
a unit with null intent, but that's rendering, not storage.

### Why not a hierarchy in storage

- **Testability.** A flat primitive makes `gap-audit` trivial: scan all
  units, report which have `intent is None`. A hierarchy model has to
  re-answer "what counts as empty" at every level.
- **Symmetry.** New unit types (e.g. a "project" row in a multi-project
  world, or "themes" if they ever matter) get the same field for free.
  No resolver changes.
- **Drift detection.** Comparing a unit's intent to its actual worklog
  activity is level-agnostic work — easier when the text lives in one
  place per unit, not scattered across inherited fields.

### Reconciliation with today

| Today | Now | Action |
|---|---|---|
| `identity.md § Commander's Intent` prose | `state.commander_intent` structured field | Unchanged from prior proposal. Identity.md is a rendered mirror. |
| `intents.json` flat history | `state.commander_intent.history[]` | Unchanged. |
| `state.initiatives[].intent` (t-384) | Same, plus `intent_source`, `intent_updated_at` | Schema-additive. |
| `state.initiatives[].description` | Kept separate | Description = what it IS; intent = why it MATTERS. |
| **NEW: `state.queue[].intent`** | Nullable string per task | Null by default. Populated by inline edit or by auto-discovery. |

## 2. Views (not resolvers)

There is no "resolver" because there is no hierarchy to resolve. Views
answer questions about the primitive field from different angles.

### View A — Chain (the prior doc's resolver, demoted)

```
task(t-389).intent
  → initiative(ini-016).intent
    → commander_intent.text
```

Rendered as a breadcrumb when displaying a task: "Why this task? → Why
this initiative? → Why the project?". Useful for a human opening a
task drawer and wanting context. Not the access path, just one panel.

### View B — Search by content

Full-text over all `intent` fields (project, initiative, task). Given
a topic string, find which units articulate an intent that mentions
it. Catches cases like "two initiatives both claim the same intent in
different words" or "this task shares intent language with ini-003 but
lives under ini-009."

### View C — Gap audit

List units where `intent is None`. Prioritize by recency-of-activity
(units with recent work but no intent are the highest-leverage gaps).
This view is impossible to compute honestly in a hierarchy model —
"null at task level means inherit" hides the gap.

### View D — Drift detection

For each unit with non-null intent, compare the intent text to the unit's
actual artifacts (description + recent worklog rows + commit messages).
A semantic drift score surfaces units whose work has wandered from what
they said they'd do. Runs the same way at every level because the field
is the same shape everywhere.

### View E — Rollup (optional)

Given an initiative, emit a paragraph that states the initiative's
intent, the project's intent, and the set of task-level intents
belonging to it. Useful for a weekly retro or a stakeholder update. A
template, not a resolver.

## 3. Editor UX

**No level switcher.** The editor is inline. Wherever a unit is
displayed — task row in Cockpit, initiative card in Poker, project
strip in Bellows — there's an inline-edit affordance for *that unit's*
intent field. Same widget, three surfaces.

Specifically:

- **Cockpit task row**: clickable intent cell. Empty shows `(no intent)`
  in dim text; click to edit; Enter/blur saves.
- **Poker initiative card**: intent chip at the top. Same inline edit.
- **Bellows project header**: same.

The "level" of what you're editing is implied by *where* you're
editing. No mode, no dropdown.

### Auto-discovery (per-unit, not per-level)

t-384 seeded initiative intents from artifact corpora. That code was
already per-unit (one unit, one corpus, one intent proposal). The
reframe means it applies to tasks too without changes: a task's
corpus is `{description, worklog rows for this task_id, commit
messages mentioning the task id}`. Same discovery, same shape, same
widget.

### Validation

- **`intent` is a string or null**, up to ~300 chars. Enforce in
  `validate_state`.
- **`intent_source`**: task id (`t-XXX`), or `"human"`, or `"auto"`.
- **Lint: description-as-intent.** If `intent` text is ≥80% substring
  overlap with `description`, flag (not block) — encourages writing
  about *why*, not restating *what*.

## 4. Migration

Phase 1 (this week): ship the field.

- `state.initiatives[].intent` already exists (t-384). Add
  `intent_source` + `intent_updated_at` alongside.
- Add `state.queue[].intent` (+ source + updated_at) as nullable
  fields; default null for all existing tasks.
- Extend `validate_state` with the lint.

Phase 2: wire the inline editor on Cockpit task rows and Poker
initiative cards. Reuse the existing t-384 auto-discovery job to
seed initiative intents when missing. Add a "seed intent from task
artifacts" button for tasks that have accumulated activity.

Phase 3: build the views.

1. Chain panel in the task drawer (reuses existing display code).
2. Gap-audit widget in Bellows (dashboard): "Units with no intent:
   N; recent activity: …"
3. Search-by-content: extend the existing Cockpit search to cover
   intent text.
4. Drift detection: background job, surfaces a signal on the unit
   when drift > threshold.

## 5. Rebuttal of `intent-hierarchy.md`

The prior doc's strongest arguments were:

- **"Without a hierarchy, how does Marshal score a task against
  intent?"** It scores against *the task's own intent first*, falling
  back to the initiative's when null. That's a view, not a resolver —
  a 3-line function, no level machinery needed.
- **"The resolver is pure and testable."** True, but the resolver
  only exists because storage has holes. Remove the holes (make the
  field present on every unit) and the resolver collapses to a null
  check.
- **"Themes might want intent someday."** If so, `theme.intent` is
  just another same-shape field. No change to the storage model.
- **"Sub-initiative layer emphatically no."** Still no — but the new
  model makes this a non-issue because layers aren't storage.

The argument for the reframe that the prior doc missed: **the hierarchy
model optimizes for reading one task, not for auditing the whole
corpus**. Gap audits, drift detection, and search are first-class
operations; chain is one of several views. Primitives compose;
hierarchies don't.

## 6. Implementation candidates (revised)

| # | Candidate | Value-thesis | Cost |
|---|---|---|---|
| 1 | Schema: `intent` + `intent_source` + `intent_updated_at` on `queue[]` | Field exists everywhere, unlocks gap-audit and inline-edit. | 1 heat |
| 2 | Inline-edit widget (Cockpit task + Poker initiative + Bellows project) | One UX for all units — reduces editor cognitive load vs. switching modes. | 2 heats |
| 3 | Gap-audit widget in Bellows | Makes "which units are unstated" visible; prioritizes auto-discovery queue. | 1 heat |
| 4 | Chain breadcrumb in task drawer | Preserves the prior doc's "context on hover" use case. | 1 heat |
| 5 | Search-by-content over intent text | Surfaces semantic overlap / misplacement across units. | 1 heat |
| 6 | Drift-detection job (worklog vs intent) | Catches units that have drifted from their stated purpose. | 3 heats |
| 7 | Description-as-intent lint | Cheap sanity rail; encourages writing about *why*. | 0.5 heat |

Recommended order: 1 → 7 → 3 → 2 → 4 → 5 → 6. (Schema + lint first
because they're stable targets for everything else; gap-audit early
because it drives the inline-editor workload; views 4/5/6 after the
editing surface exists.)

## 7. Round-trip with the t-384 seed corpus

The t-384 seed produced prose intent for ~14 initiatives. Under the
reframe, those entries land unchanged in `initiatives[].intent` — no
migration needed for existing rows. Running the same auto-discovery
against tasks produces candidate `queue[].intent` values; the
inline-editor surface lets a human accept/refine them. The corpus
round-trips cleanly because the field shape is identical to what t-384
already writes.

## 8. Open questions

- **Should tasks default to inheriting visibly?** A task with null
  intent can still be displayed with the initiative's intent shown in
  a dim "(inherited)" chip. That's a view choice — I'd lean yes for
  Cockpit rows (reduces clutter) and no for the task detail drawer
  (forces the human to decide whether this task needs its own).
- **Drift threshold.** Cosine similarity on embeddings is the obvious
  tool, but the threshold is subjective. Ship without a threshold;
  surface the top-N drifters weekly and let the human tune.
- **History retention.** Every intent edit creates an audit row. For
  tasks that churn, this could bloat. Cap at last 5 per unit, roll off
  older entries to `intents.json` archive.
