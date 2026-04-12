# Intent Hierarchy — Design Study

**Task:** t-385 (ini-017, research) · heat 808 · 2026-04-12
**Companion notes:** `research/intent-schema-gaps.md` (t-384 seed audit)

## Thesis

We say "intent" a lot. The word points at three different things in three
different places today:

1. `identity.md § Commander's Intent` — project-level, human-maintained prose.
2. `intents.json` — flat project-level history, written by Intent Editor.
3. `state.initiatives[].intent` — per-initiative prose seeded in t-384.
4. `state.initiatives[].description` — historically "the intent in disguise."

If nothing binds these, the word becomes a vibe. Marshal can't score a task
"against intent" because there's no canonical function `intent(task)`.
This doc proposes a hierarchy — project → initiative → (task) — with a
deterministic resolver and a thin editor story so the noun means something.

## 1. Schema

### Proposed canonical layout

```jsonc
{
  "commander_intent": {
    "text": "Create an AI collaborator who can run autonomously…",
    "updated_at": "2026-04-12T…",
    "source": "t-384"        // task or "human"
  },
  "themes": [
    {"id": "th-002", "name": "Collaboration research",
     "intent": null}          // optional; if null, inherit from commander
  ],
  "initiatives": [
    {"id": "ini-016", "theme_id": "th-003", "title": "Queue Cockpit",
     "intent": "Give the human a way to ensure…",  // MAY be null
     "intent_source": "t-384",
     "intent_updated_at": "2026-04-12T…"}
  ],
  "queue": [
    {"id": "t-389", "initiative_id": "ini-016",
     "intent_override": null  // tasks almost never override; null means inherit}
  ]
}
```

### Reconciliation with today

| Today | Proposed | Action |
|---|---|---|
| `identity.md § Commander's Intent` prose | `state.commander_intent` structured field | Keep identity.md as human-readable mirror; canonical is state. Write-through on Intent Editor save. |
| `intents.json` flat history | `state.commander_intent.history[]` (optional) | Migrate; keep file for one version as fallback; stop writing new entries to it. |
| `state.initiatives[].intent` (t-384 seed) | Same field, plus `intent_source` and `intent_updated_at` | Schema-additive. |
| `state.initiatives[].description` | Unchanged, kept separate | Description = what it IS; intent = why it MATTERS. Lint: flag description-reused-as-intent via substring match. |

### Theme layer: needed?

**Leaning: no, not initially.** Themes (`state.themes`) today are a coarse
bucket (Tutor Content / Collaboration research / UI experimentation). If
we add theme-level intent, resolution becomes project → theme → initiative
→ task — four layers. Overkill for 3 themes and 17 initiatives.

Introduce only when a theme's initiatives start wanting to share an intent
that isn't the project's. Hook is reserved (`theme.intent` field in schema
above) but not required.

### Sub-initiative layer: emphatically no

Tasks already belong to initiatives. Tasks can `intent_override` when
exceptional. Adding a sub-initiative layer between is premature
categorization — we have no evidence the two-level hierarchy is
insufficient.

## 2. Inheritance & resolver

Pure, deterministic, no I/O once state is loaded:

```python
def resolve_intent(state, *, task_id=None, initiative_id=None):
    """Return {text, level, source_id} for a given scope.

    Resolution order (most specific wins, fall back to parent):
        task.intent_override
        → initiative.intent (for task's initiative_id or given initiative_id)
        → theme.intent (for that initiative's theme_id)
        → commander_intent.text
    Returns None only when commander_intent is absent (misconfigured state).
    """
    if task_id:
        task = _find_task(state, task_id)
        if task and task.get("intent_override"):
            return {"text": task["intent_override"],
                    "level": "task", "source_id": task_id}
        initiative_id = task.get("initiative_id") if task else initiative_id

    if initiative_id:
        ini = _find_initiative(state, initiative_id)
        if ini and ini.get("intent"):
            return {"text": ini["intent"],
                    "level": "initiative", "source_id": initiative_id}
        theme_id = ini.get("theme_id") if ini else None
        if theme_id:
            theme = _find_theme(state, theme_id)
            if theme and theme.get("intent"):
                return {"text": theme["intent"],
                        "level": "theme", "source_id": theme_id}

    ci = state.get("commander_intent") or {}
    if ci.get("text"):
        return {"text": ci["text"], "level": "project", "source_id": None}
    return None
```

### Invariants

- No I/O. Pure over state dict. Unit-testable with json fixtures.
- Deterministic. Same state + same task_id = same result, always.
- Never synthesizes text. If nothing at any level has content, returns
  `None`. Caller decides what to render.
- Cycle-free by construction. Graph is a tree (task → ini → theme →
  project). No cycles possible.
- Returns `{text, level, source_id}` always — callers can render level
  badges ("from initiative ini-016") without re-walking the tree.

### Tests (at least)

- Task with override → task level.
- Task without override, initiative with intent → initiative level.
- Initiative without intent, theme with intent → theme level.
- All empty except commander → project level.
- All empty → `None`.
- Unknown task_id → falls through to commander.
- Cycle-impossible: test that state with circular theme refs doesn't loop.

## 3. Auto-discovery

When a new initiative is created, it has no intent. Options to fill:

### Mechanism comparison

| Mechanism | When runs | Pro | Con | Verdict |
|---|---|---|---|---|
| **Research heat** | Marshal queues an explicit research task | Rich; can read task descs + commits + worklog; LLM in the loop | Costs a heat; delayed | ✅ for initiatives needing depth |
| **CLI synth** (`smithy intent-synth <ini>`) | Human or Marshal invokes on demand | Fast; no LLM cost | Rule-based = brittle; text will be bad | ⚠️ useful as first-pass, not final |
| **Forge self-reflection at creation** | Inline when `add-initiative` runs | Cheap (one LLM call); happens naturally | Adds latency to creation; quality depends on context at that moment | ⚠️ tempting but brittle |
| **Human draft** (current default) | Intent Editor prose | Best signal | Requires human time | ✅ always the fallback |

**Recommendation: tiered.**

1. On `add-initiative`, run the rule-based CLI synth first. Produces a
   placeholder like *"[auto-placeholder] Play with different UIs…"* —
   marked clearly as auto-generated.
2. Surface an "auto-generated — review" banner in Intent Editor and
   Poker drawer, pushing the human to refine.
3. When an initiative accumulates ≥5 tasks and still has placeholder
   intent, Marshal queues an `intent-audit` research heat: Forge reads
   the tasks, worklog, and commits for that initiative and proposes a
   refined intent. Human approves via Intent Editor.

### Rule-based synth (seed implementation)

```python
def synth_intent(initiative, tasks, worklog_rows, commits):
    # Trivial: derive a one-sentence draft from the title + top verbs in tasks
    title = initiative.get("title", "")
    desc = initiative.get("description", "")
    # Take the first sentence of description if present; fall back to title.
    first = (desc.split(".")[0] or title).strip()
    return f"[auto-placeholder] {first}."
```

Not magical. The value is the *process*: every initiative has a
non-empty intent field from day one, and a visible placeholder shames us
into writing the real thing.

## 4. Editor UX

### Option A — Level switcher in Intent Editor (recommended)

```
┌────────────────────────────────────────────────────────┐
│ Intent Editor                                          │
│ [ Project │ Theme: Collab │ Initiative: ini-016 ▼ ]    │
│                                                        │
│ Editing: ini-016 Queue Cockpit                         │
│                                                        │
│ ┌────────────────────────────────────────────────┐    │
│ │ Give the human a way to ensure that individual │    │
│ │ task assignments conform to the high-level     │    │
│ │ intent the human has, and gives a way to…      │    │
│ └────────────────────────────────────────────────┘    │
│                                                        │
│ Inherits from: Project (auto-falls-back if cleared)    │
│ Last edited: t-384 · 2026-04-12                        │
│ [ Save ]  [ Revert ]  [ Clear (use parent) ]           │
└────────────────────────────────────────────────────────┘
```

**Why:** one place to find + edit intent. Switcher makes hierarchy
visible. "Clear" reveals inheritance. Users learn the model.

### Option B — Inline edit on initiative deep-dive (reject)

Editing intent in Poker's drawer or Bellows' deep-dive feels convenient
but fragments the surface: four places to look for "where is intent
edited?" is three too many. Deep-dive should *display* intent with a
"↗ edit in Intent Editor" link, not carry the editor itself.

### Display-only surfaces (see §5)

- Poker initiative drawer: show resolved intent + level badge.
- Queue Cockpit task drawer: show resolved intent + level badge.
- Bellows initiative deep-dive: read-only prose + link to Intent Editor.

## 5. Display

### Breadcrumb format

`Project → Theme: Collab → ini-016 Queue Cockpit`

Render inline above the intent text so the reader knows which level they
are seeing. When the level is `project`, render just `Project`.

### Short-vs-full

- **Collapsed by default** when length > 140 chars (roughly one tweet).
  Click-to-expand ("show more"). Tooltip on hover renders first 280.
- **Always-full in Intent Editor.**
- **Cockpit inline panel:** collapsed with expand. Adds 1 line to the
  panel, not a new row.

### Level badge

Small chip next to the intent text:

- `from project` → muted gray
- `from initiative` → yellow (matches our "you" accent)
- `from task` (override) → orange (rare; alert-adjacent)

## 6. Drift detection (design only; impl out of scope)

The question is not "are tasks on-strategy?" — that's human judgment.
The question is "has the initiative's actual output drifted from its
stated intent over the last N heats?"

### Signals available today

- Worklog rows tagged by initiative (via task → initiative_id).
- Commit subjects include `[stage] t-XXX: description`.
- `value` self-assessment per heat.

### Candidate detectors

1. **Intent-vs-title drift:** every K heats, embed the initiative's
   intent and its last K worklog notes + commit subjects. If cosine
   similarity drops below threshold, flag. Cost: embedding API (not yet
   wired in).
2. **Volume drift:** if an initiative has a `budget_cap` and the
   last 20 heats spent exceed the cap's remainder, flag.
3. **Stalled-initiative detector:** no completed task in 30 heats and
   intent placeholder still present → nudge human.

All three are out of scope for t-385 impl. Record as follow-ups for
ini-017 phase 2.

## 4–6 impl candidates (retro-format, value theses)

### C1 — Schema migration + resolver (value: **high**, prereq)

**Thesis:** No downstream UI can render intent consistently without the
resolver. Landing C1 alone improves zero user experience — but unblocks
every other candidate. Pure code, fully unit-testable.

**Scope:** 1 heat. Adds `commander_intent` to state.json, migrates
`intents.json` history, adds `smithy.intent.resolve_intent()` + tests.
`identity.md` write-through hook in Intent Editor touched in passing.

### C2 — Intent Editor level switcher (value: **high**)

**Thesis:** The UX most visible to the human. Converts "intent is a file
I edit somewhere" into "intent is a tree I navigate." Depends on C1 for
the resolver to know what to render under each level.

**Scope:** 1.5 heats. Touches `ui-intent-editor/app.py` +
`ui-intent-editor/templates/index.html`. 3-level switcher, per-level
textarea, Save/Revert/Clear.

### C3 — Auto-synth placeholder on `add-initiative` (value: **medium**)

**Thesis:** Guarantees every initiative has non-empty intent from day one.
Placeholder `[auto-placeholder] …` text drives human curation. Low-risk
(text generation; no semantic claims).

**Scope:** 0.5 heat. Touches `smithy/cli.py` (`add-initiative`). Adds
`synth_intent()` per §3.

### C4 — Display surfaces: breadcrumb + level badge in Poker drawer and
Cockpit inline panel (value: **high**)

**Thesis:** Unless the user sees intent where they're making decisions
(Poker drawer to approve, Cockpit to reprioritize), the hierarchy is
invisible. This is where hierarchy pays for itself.

**Scope:** 1 heat. Touches Poker drawer template + Cockpit inline panel.
Reuses `resolve_intent()` via a new `/api/intent?task=<id>` endpoint.

### C5 — Patrol check: flag initiatives with placeholder intent older
than 30 heats (value: **medium**)

**Thesis:** Closes the loop on C3. Placeholders are shame-driving only if
the system nags when they persist. Soft accountability.

**Scope:** 0.5 heat. One new patrol check; no auto-fix — report-only.

### C6 — Intent-audit research heat trigger in Marshal (value:
**medium**, defer)

**Thesis:** Marshal queues an `intent-audit t-XXX` task when an
initiative has ≥5 tasks and its intent is still a placeholder. Gets human
back in the loop without them having to remember.

**Scope:** 1 heat. Touches Marshal dispatch logic. Requires C5's signal.

## Recommended shipping order

**C1 → C2 → C3 → C4 → C5 → C6**

C1 first because it's the spine. C2 gives the user something to touch.
C3 keeps forward-motion cheap. C4 makes hierarchy visible in work
surfaces. C5+C6 close the accountability loop.

Total: ~5.5 heats for C1-C5. C6 is +1 heat, ship after C5 is observed in
use.

## Open questions for Anvil

1. **identity.md dual-source of truth.** Intent Editor currently reads
   `identity.md § Commander's Intent`. Moving canonical to state is clean
   but Intent Editor UX changes. Retain the mirror (write state, also
   rewrite the identity.md section)? Or make identity.md read-only
   prose and show a "view current intent" link to Intent Editor?
2. **Migration of `intents.json`.** Move to `state.commander_intent.history[]`
   (up to 20 entries) or leave as a sidecar file indefinitely?
3. **Allow task-level override?** I've sketched `intent_override` as
   possible but discouraged. Ship disabled (field exists but editor
   can't set it) or ship enabled with a conspicuous warning? My lean:
   disabled in v1; re-enable after real evidence of need.
