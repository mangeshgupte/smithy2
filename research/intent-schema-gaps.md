# Intent Schema Gaps (t-384 seeding)

Seeded three explicit intents today (project-level + ini-016 + ini-012). The
existing data model doesn't have a first-class home for "an intent," so the
seed had to stretch what's there. This note captures the gaps for t-385
(intent primitives research) and downstream implementation tasks.

## What we added

1. **`state.initiatives[].intent`** — new free-text field on initiative records.
   Not read by any code yet; it's a corpus for auto-discovery (t-385 research)
   and a target for UI surfacing (Poker drawer, Cockpit inline panel).
2. **`state.intents[]`** — new top-level list. Entries shape:
   ```jsonc
   {
     "id": "intent-project",        // or "intent-ini-016"
     "scope": "project",            // "project" | "initiative"
     "scope_id": null,              // initiative id when scope == "initiative"
     "text": "...",
     "source": "t-384",             // task that seeded it
     "created_at": "2026-04-12T..." // ISO ts
   }
   ```
3. **`identity.md` Commander's Intent** — added a canonical top-line bullet
   pointing at the project-level intent text. Legacy "Build a reliable..."
   framing kept as a second bullet for continuity.
4. **`intents.json`** — appended the project-level text to the existing flat
   history (what Intent Editor reads/writes).

## Gaps t-385 should resolve

- **Three stores, one concept.** Intent lives in `identity.md`,
  `intents.json`, and now `state.intents[]` + `state.initiatives[].intent`.
  Nothing cross-validates. An edit in one doesn't propagate.
- **No scoping primitive.** `intents.json` is a flat project-scoped history;
  `state.intents[]` has `scope` but no version/lifecycle (superseded_by,
  active_from, active_to). t-385 should decide whether intents are ranked,
  versioned, or immutable-append-only.
- **No link between intent and initiative/task.** If the project-level intent
  is "responsive to human steers," which initiatives serve it? Today you'd
  infer from theme/initiative titles. A structured link would let Marshal
  score proposals against intent alignment (ini-017 premise).
- **No API.** Intent Editor reads identity.md; no `GET/POST /api/intents`
  surface; Cockpit can't render an intent column until one exists.
- **No schema migration path.** Adding `intent` to existing initiative records
  worked because json dicts tolerate missing keys, but this isn't guarded — a
  patrol check for "initiative without intent" would surface the hole.

## Corpus seeded (ready for t-385 auto-discovery work)

- project: "Create an AI collaborator who can run autonomously..."
- ini-016 Queue Cockpit: "Give the human a way to ensure that individual task
  assignments conform to the high-level intent..."
- ini-012 Four UIs: "Play with different UIs which would inform a good way of
  adopting steerability."

Three data points isn't much, but t-385 is research — it should read the 14
other initiatives' descriptions to decide whether `description` is already
"the intent" in disguise, or whether intent needs a distinct field.
