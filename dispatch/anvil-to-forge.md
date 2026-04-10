# Dispatch: Anvil → Forge

Anvil writes direction here. Forge reads on startup and uses it to guide autonomous work.

## 2026-04-10 16:00 — Direction: Wire Smithy CLI Into Forge Runs (10 heats)

### What We Decided
The smithy CLI has 15 commands and 152 tests, but Forge is still manually editing state.json and worklog.tsv. That defeats the purpose. Every bookkeeping operation must go through the CLI so counters, cursors, and statuses are guaranteed correct.

### Commander's Intent
```json
{
  "intent": "Replace ALL manual state edits in the Forge protocol with smithy CLI calls",
  "success_looks_like": "Forge can run 10+ heats without ever directly editing state.json or worklog.tsv — all mutations go through smithy commands",
  "tone": "Critical infrastructure — break nothing, test everything",
  "boundaries": ["The protocol files are the source of truth for how Forge works", "The smithy CLI is the only writer of state.json and worklog.tsv"],
  "not_this": ["Don't add new CLI features — wire what exists", "Don't change the heat loop logic — just change how state is written"]
}
```

### Implementation Plan

**Heats 1-3: Rewrite protocol/loop.md to use smithy CLI**

Replace every manual state edit with a smithy command:

| Current (manual) | New (smithy CLI) |
|---|---|
| Read state.json, compute allocator math | `smithy allocate` → returns recommended stage |
| Find ready task, set status to in_progress | `smithy pick-task <stage>` → returns task, marks in_progress |
| Write checkpoint file | `smithy start-heat <stage> --task <task_id>` → writes checkpoint |
| Increment budget.used, update stage stats, compute value_ema, append worklog | `smithy end-heat <value> <signal> "<notes>"` → all bookkeeping atomically |
| Read feedback.md after cursor, update cursor | `smithy process-feedback` → returns new entries, updates cursor |
| Read inbox.md after cursor, update cursor | `smithy process-inbox` → returns new entries, updates cursor |
| git add + git commit | `smithy commit "[stage] description"` |
| Check budget exhausted | `smithy status --json` → includes budget remaining |
| Write handoff at end | `smithy handoff` |
| Resume from handoff | `smithy resume` |
| Validate state | `smithy patrol` |

The protocol should read like:
```
Step 1: Load Context
  Run `smithy resume` (if handoff exists)
  Run `smithy patrol` (validate state)
  Run `smithy status` (get current state)
  Run `smithy process-feedback` (check for new feedback)
  Run `smithy process-inbox` (check for new inbox messages)
  Read identity.md, STRATEGY.md, MEMORY_DAILY.md (context — read-only)

Step 3: Run the Allocator
  Run `smithy allocate` → gives you the stage

Step 4: Pick a Task
  Run `smithy pick-task <stage>` → gives you the task

Step 5: Execute
  Run `smithy start-heat <stage> --task <task_id>`
  Do the work (~4 minutes)
  Run `smithy commit "[stage] description"`

Step 6: Log the Heat
  Run `smithy end-heat <value> <signal> "<notes>"`

Step 8: Check Budget
  Run `smithy status --json` → check budget.remaining
  If 0: run `smithy handoff` and STOP
  Else: go to Step 1
```

**Heats 4-5: Rewrite protocol/logging.md**
- Remove all manual state.json update instructions
- Remove manual worklog.tsv append instructions
- Replace with: "Run `smithy end-heat` — it handles everything"
- Keep the self-assessment guide and signal classification (those inform the *inputs* to smithy end-heat)

**Heats 6-7: Rewrite protocol/allocator.md**
- Remove inline allocator math (benefit scores, PI controller, integral updates)
- Replace with: "Run `smithy allocate` — it runs the wavefront algorithm and returns the recommended stage"
- Keep the *explanation* of how the allocator works (for understanding) but mark the math as "implemented in smithy CLI"

**Heats 8-9: Stress test — run 2 real heats using the new protocol**
- Run 2 actual heats on this project using only smithy commands for state changes
- Verify: state.json is correct after each heat, worklog has right entries, no manual edits needed
- Fix any gaps discovered

**Heat 10: AAR + update all project templates**
- Update `smithy init` scaffolding to generate protocol files that use smithy CLI
- AAR covering: what worked, what needed fixing, any remaining gaps
- Update README with the new workflow

### Key Rule for Forge After This
**NEVER directly edit state.json or worklog.tsv.** If you need to change state, there must be a smithy command for it. If no command exists, flag it — don't work around it.

### Constraints
- The smithy CLI is at `smithy/` — run via `uv run smithy <command>`
- All existing tests must still pass after protocol changes
- Run `smithy patrol` after each heat during the stress test to verify consistency

### Budget
10 heats

## 2026-04-10 15:00 — Direction: Rename Everything (2 heats)

### What We Decided
Two renames across the entire codebase:
1. **ai-coworker → Smithy** (the project name)
2. **Commissioner → Bellows** (the UI app)

### Commander's Intent
```json
{
  "intent": "Rename consistently everywhere — code, docs, config, templates, dispatch, state files",
  "success_looks_like": "No remaining references to 'ai-coworker' or 'Commissioner' anywhere except git history",
  "tone": "Mechanical — find and replace, verify nothing breaks",
  "boundaries": ["Don't rename the directory itself yet — just content references", "Don't change functionality"],
  "not_this": ["Don't refactor anything else while renaming"]
}
```

### Heat 1: Commissioner → Bellows
- `commissioner/` directory rename to `bellows/`
- `commissioner/app.py` — FastAPI title
- `commissioner/pyproject.toml` — package name
- `commissioner/templates/base.html` — page title
- `commissioner/README.md` — all references
- `design/2026-04-09-commissioner-app-design.md` — rename file + update content
- `dispatch/chisel-to-forge.md` — all references
- `dispatch/anvil-to-forge.md` — all references
- `STRATEGY.md` — all references
- `inbox.md` — all references
- `outbox.md` — all references
- `state.json` — task descriptions
- `CHANGELOG.md` — all references
- `feedback.md` — all references
- `README.md` — all references

### Heat 2: ai-coworker → Smithy
- `STRATEGY.md` — project name, title, all references
- `CLAUDE.md` — project references
- `identity.md` — if it references ai-coworker
- `state.json` — `"project": "smithy"`
- `README.md` — all references
- `CHANGELOG.md` — all references
- `dispatch/*.md` — all references
- `inbox.md` / `outbox.md` — all references
- `personas/anvil/CLAUDE.md` — if it references ai-coworker
- `personas/chisel/CLAUDE.md` — if it references ai-coworker
- `personas/forge/CLAUDE.md` — if it references ai-coworker
- `smithy/` CLI — if package references ai-coworker
- `pyproject.toml` — if it exists at root
- Verify: `grep -ri "ai-coworker" .` and `grep -ri "commissioner" .` return nothing (except git history)

### Constraints
- Run `smithy validate` (or equivalent) after to make sure nothing broke
- Test that Bellows app still starts: `cd bellows && uv run uvicorn app:app --port 8080`
- Commit each rename separately: `[editing] Rename Commissioner to Bellows` and `[editing] Rename ai-coworker to Smithy`

### Budget
2 heats

## 2026-04-10 14:00 — Direction: Adopt Gas Town Patterns (Approach B)

### What We Decided
Research complete. Approach B confirmed: adopt Gas Town's best patterns into Smithy without taking the dependency. Smithy stays independent, flat-file, Python-based. Cherry-pick what works, contribute innovations back later.

### Commander's Intent
```json
{
  "intent": "Make Smithy more robust by adopting Gas Town's proven patterns for session cycling, validation, and handoff",
  "success_looks_like": "smithy handoff and smithy patrol commands working, session cycling reliable, protocol updated to use them",
  "tone": "Infrastructure — careful, well-tested",
  "boundaries": ["Stay on flat JSON — no Dolt yet", "Use the smithy CLI for all new commands", "Don't change Gas Town's code"],
  "not_this": ["No multi-agent coordination yet", "No Go code", "No forking Gas Town"]
}
```

### Implementation Plan

**Heats 1-4: `smithy handoff` (session cycling)**
- Save session context to a handoff file when a session ends (or budget exhausts)
- Include: last heat number, active task, allocator state, key decisions made, what to do next
- On next session startup, `smithy resume` reads the handoff and restores context
- Replaces the current fragile "read state.json and guess where we were" pattern
- Integrate with the SessionEnd hook
- Tests

**Heats 5-8: `smithy patrol` (discover-don't-track validation)**
- Gas Town's "discover, don't track" pattern: instead of trusting state.json, derive state from git history and worklog
- `smithy patrol` scans: git log, worklog.tsv, state.json — reports discrepancies
- Checks: heat count matches commits, task statuses match worklog outcomes, stage progress is plausible given worklog entries
- Can auto-fix simple discrepancies (e.g., task marked in_progress but worklog shows complete)
- Replaces/extends `smithy validate` with discovery-based checks
- Tests

**Heats 9-11: Session cycling in protocol**
- Update `protocol/loop.md` to use `smithy handoff` at budget exhaustion (Step 8)
- Update Step 1 context load to use `smithy resume` if handoff file exists
- Test: simulate a session end + new session, verify context survives
- Update `forge-init.sh` / `smithy init` to include handoff support

**Heats 12-13: Document Smithy ↔ Gas Town relationship**
- Update STRATEGY.md with the Approach B decision and rationale
- Add a section on what Smithy could contribute back (memory hierarchy, wavefront, AAR)
- Update research docs with "decision made" annotations

**Heats 14-15: Testing + AAR**
- Full integration test: init → run heats → handoff → resume → patrol → validate
- AAR covering what was adopted, what was deferred, what to do next

### Constraints
- All new functionality goes through the smithy CLI — no direct state edits
- Tests for every new command
- Write AAR at end

### Budget
15 heats

## 2026-04-10 13:00 — Direction: Research Gas Town Integration (5 heats)

### What We Decided
Smithy and Gas Town are converging architecturally. Before building more infrastructure (like the smithy CLI), we need to understand whether to build on top of Gas Town or stay independent. This research determines the path.

### Commander's Intent
```json
{
  "intent": "Determine whether Smithy should become a Gas Town rig type, fork Gas Town, or stay independent — with a concrete recommendation",
  "success_looks_like": "A research doc with architecture comparison, extension point analysis, and a clear recommendation with migration path",
  "tone": "Deep research — read the code, don't just skim READMEs",
  "boundaries": ["Research only — no implementation", "Gas Town is at ~/vibes/gt/ or nearby — find it"],
  "not_this": ["Don't redesign either system", "Don't start building anything"]
}
```

### Research Questions (5 heats)

**Heat 1: Gas Town extension points**
- How are polecat types defined? Can you add a custom type that runs a heat loop?
- How are rig types configured? What's the interface a rig must implement?
- Is there a plugin/hook system?
- Write findings to `research/gas-town-extension-points.md`

**Heat 2: State and persistence mapping**
- How would Smithy's state.json map to beads in Dolt?
- Could worklog.tsv become beads entries?
- Could the wavefront allocator read from Dolt instead of flat JSON?
- What's the migration path from flat files to Dolt?
- Write findings to `research/gas-town-state-mapping.md`

**Heat 3: Communication protocol mapping**
- How does Gas Town's mail protocol compare to inbox/outbox/dispatch?
- Could Anvil → Forge dispatch become mail messages?
- Could feedback.md become escalation protocol entries?
- How do nudges compare to the review-first-heat pattern?
- Write findings to `research/gas-town-comms-mapping.md`

**Heat 4: Autonomy + memory gap analysis**
- What prevents polecats from doing autonomous research today?
- What would a "forge-polecat" need that doesn't exist in Gas Town?
- How does Gas Town handle self-directed task generation (if at all)?
- Is the wavefront allocator compatible with Gas Town's allocation model?
- **Memory**: How do Gas Town agents remember across sessions? Do they have anything like MEMORY_DAILY/WEEKLY, STRATEGY.md, or worklog? Is memory embedded in beads history, or is it absent? Smithy has a 4-level memory hierarchy (L1 worklog → L2 daily → L3 weekly → L4 identity) with consolidation every 6 heats. How does Gas Town compare? If Gas Town agents lack persistent memory, this is a major gap — and one Smithy could contribute back.
- Write findings to `research/gas-town-autonomy-memory-gap.md`

**Heat 5: Synthesis and recommendation**
- Write `research/gas-town-integration-synthesis.md`:
  - Approach A (Smithy as Gas Town rig): feasibility, effort, what you gain/lose
  - Approach B (Adopt GT patterns into Smithy): feasibility, effort, what you gain/lose
  - Approach C (Fork Gas Town): feasibility, merge strategy, drift risk
  - **Recommendation**: which approach, why, and what the first 10 implementation heats would look like
  - How does this affect the smithy CLI plan? (Should it target Dolt instead of flat JSON?)

### Constraints
- All research stage — no implementation
- Read Gas Town's actual code, not just docs
- Be specific about file paths, interfaces, and code patterns
- The recommendation must be actionable — "do X in Y heats" not "consider Z"

### Budget
5 heats

## 2026-04-10 12:00 — Direction: Build the Smithy CLI (bookkeeping tool)

### What We Decided
The project is now called **Smithy**. The LLM keeps forgetting to update counters, cursors, and task statuses correctly (budget double-counting, feedback_cursor not read, tasks stuck in_progress). The fix: a `smithy` Python CLI that handles ALL state mutations. The LLM never directly edits state.json or worklog.tsv again — it calls `smithy` commands instead.

This is inspired by beads and gas town, which hide bookkeeping behind tool calls so it's deterministic and auditable.

### Commander's Intent
```json
{
  "intent": "Build a smithy Python CLI that makes all Forge bookkeeping deterministic — the LLM decides what to do, smithy handles the record-keeping",
  "success_looks_like": "Forge can run a full heat using only smithy commands for state changes, and every counter/cursor/status is guaranteed correct",
  "tone": "Infrastructure — careful, well-tested, this is the foundation everything runs on",
  "boundaries": ["Python CLI using click or argparse", "Reads/writes the same flat files (state.json, worklog.tsv, feedback.md)", "State validation on every call — reject impossible states"],
  "not_this": ["No database", "No daemon/server — just a CLI", "Don't change the file formats — same state.json schema, same worklog.tsv format"]
}
```

### The API

```
smithy start-heat <stage> [--task <task_id>]
  → Sets task to in_progress (if specified)
  → Writes .forge-checkpoint.json
  → Returns: heat number, stage, task details, context summary
  → Validates: budget not exhausted, stage exists, task is ready

smithy end-heat <value> <signal> <notes> [--outcome complete|partial|blocked]
  → Increments budget.used
  → Increments stage heats
  → Updates stage progress (prompted or auto-estimated)
  → Computes value_ema: 0.7 * old + 0.3 * new
  → Updates allocator integral (with ±0.5 clamp)
  → Appends worklog.tsv row
  → Marks task complete (if outcome=complete)
  → Updates overall_progress
  → Deletes checkpoint
  → Validates: checkpoint exists, value in 0-1, signal is valid

smithy pick-task <stage>
  → Finds highest-priority ready task for stage
  → Returns task details as JSON
  → If no tasks: suggests one based on stage heuristics

smithy allocate
  → Runs the full wavefront allocator algorithm
  → Returns: recommended stage, benefit scores, debug info
  → Applies exploration rule (every 5th heat) and unblocking override

smithy process-feedback
  → Reads feedback.md lines after feedback_cursor
  → Returns new entries as structured JSON
  → Updates feedback_cursor in state.json
  → Same for inbox: smithy process-inbox

smithy commit <message>
  → git add + git commit with standardized format: [stage] message
  → Validates: something to commit

smithy validate
  → Runs all consistency checks (like forge-validate.sh but in Python)
  → Checks: used <= total, stage heats sum correctly, no orphan in_progress tasks,
    cursors are valid, worklog row count matches used, etc.
  → Returns pass/fail with details

smithy init <project_name> [--with-personas]
  → Replaces forge-init.sh — scaffolds a new project
  → Creates all files with correct initial state

smithy status
  → Prints the L0/L1 status summary
  → Replaces forge-status.sh
```

### Implementation Plan

**Heats 1-3: Core CLI + state mutations**
- Set up Python package (click-based CLI, `pyproject.toml`)
- Implement `start-heat`, `end-heat`, `validate`
- State validation on every write (reject impossible states)
- Tests for each command

**Heats 4-5: Allocator + task management**
- Implement `allocate` (port wavefront algorithm from prose to Python)
- Implement `pick-task`
- Tests

**Heats 6-7: Feedback + inbox processing**
- Implement `process-feedback`, `process-inbox`
- Cursor management with validation
- Tests

**Heats 8-9: Commit, init, status**
- Implement `commit`, `init` (replacing forge-init.sh), `status`
- Tests

**Heat 10: Protocol update**
- Update `protocol/loop.md` to use `smithy` commands instead of direct state edits
- Update `protocol/logging.md` to reference smithy
- Update CLAUDE.md

### Where it lives
`smithy/` directory at the project root (`~/vibes/ai-coworker/smithy/`). Use `uv` for all dependency management — `pyproject.toml` + `uv.lock`. Run via `uv run smithy <command>`. No pip.

### Constraints
- Every command must validate state before AND after mutation
- JSON output for all commands (parseable by LLM)
- Human-readable output to stderr (for debugging)
- Comprehensive test suite — this is the foundation
- Write an AAR at end

### Budget
10 heats

## 2026-04-10 10:00 — Direction: Tutor App UI Redesign (mobile-first)

### What We Decided
Chisel designed a mobile-first app for the AI Tutor, borrowing patterns from Recall Rhino and adapting them for Socratic dialogue, student-created flashcards, and multi-exercise-type sessions. The full design spec is at `~/vibes/tutor/design/2026-04-10-tutor-app-design.md` and the dispatch summary is at `~/vibes/tutor/dispatch/chisel-to-forge.md`. Read both before starting.

This redesigns the tutor's current Jinja2 web UI into a mobile-first app with a Learn → Create → Review → Refine loop.

### Commander's Intent
```json
{
  "intent": "Rebuild the tutor UI as a mobile-first app following Chisel's design spec, with three-tab navigation (Learn, Create, Review) and the full learning loop",
  "success_looks_like": "A working web app at localhost where a student can: complete a Socratic lesson, create flashcards from what they learned, and review those cards via spaced repetition — all from a phone browser",
  "tone": "Implementation-heavy. The design is done — build it. Follow the spec closely.",
  "boundaries": ["Follow Chisel's design spec", "Mobile-first — must work well on phone browser", "Keep existing backend/API intact where possible", "Student-created flashcards are the core innovation — don't skip this"],
  "not_this": ["Don't redesign what Chisel decided", "Don't build a native app — web only", "Don't add more curriculum content — focus on the app workflow per human feedback"],
  "references": ["~/vibes/tutor/design/2026-04-10-tutor-app-design.md", "~/vibes/tutor/dispatch/chisel-to-forge.md", "~/vibes/rr/ (Recall Rhino — reference implementation for review patterns)"]
}
```

### Key Design Decisions (from spec)
- **Three-tab nav**: Learn, Create, Review — no deeper nesting
- **Wrong answers use Review Yellow (#FFEB3B), not red** — Socratic philosophy, yellow says "let's explore that"
- **Students create their own flashcards** — system only generates drill cards for pure memorization
- **AI reviews student cards** — suggests improvements after save, Socratic even in creation mode
- **Sky Blue (#ADD8E6) container** for all AI/Socratic speech — consistent visual identity
- **Subject accent bars** — 3px colored left border (Orange=Python, Teal=Math, Green=English)
- **Session memory** — resume where you left off after interruption
- **One daily notification max** — at the student's usual review time
- **Visual system: Recall Rhino palette** — Recall Gray (#708090), Playful Teal (#00BCD4), Energy Orange (#FF9800), Focus Green (#4CAF50), Review Yellow (#FFEB3B), Alert Red (#F44336), Sky Blue (#ADD8E6). See `~/vibes/rr/instructions/design-system.md` for full reference.

### Phase 1 — Core Loop (priority)
1. Three-tab navigation shell (Learn, Create, Review)
2. Learn tab: subject landing → topic preview → exercise session with Socratic moments
3. Create tab: deck overview → card author with AI review
4. Review tab: stats landing → card player with type-specific rendering

### Phase 2 — Screens & UX (from Chisel spec, not yet built)
5. **Topic Preview screen** — prereqs with lock/check, mastery threshold, estimated time, "Start Lesson"
6. **Exercise Session shell** — type-specific rendering: code sandbox (Run + Check), math input with CPA manipulatives (fraction bars, base-10 blocks), free response with voice input
7. **Socratic Moment container** — Sky Blue (#ADD8E6) bg, lightbulb icon, 1-2 follow-up exchanges, never says "wrong", dynamic AI follow-ups based on specific misconception
8. **Session Summary** — results, mastery status, "What You Nailed" / "What to Revisit", primary CTA is "Create Flashcards" (nudge while fresh)
9. **Card Author upgrade** — three-field form (key idea, test question, answer), AI review after save with improvement suggestions and related card prompts
10. **Review Session card player** — concept cards with 4-button self-rating (Forgot/Hard/Good/Easy), drill cards requiring typed input (no "show answer"), "show my trick" hint for drill cards with student mnemonics
11. **Review Summary** — recall stats, strong/weak areas, card rewrite suggestions closing the Refine loop

### Phase 3 — Visual & Polish
12. **Recall Rhino visual system** — full palette (Recall Gray, Playful Teal, Energy Orange, Focus Green, Review Yellow, Sky Blue), card surfaces, shadows, animations (correct flash green, wrong flash yellow, Socratic slide-up)
13. **Session memory** — resume interrupted sessions with one tap
14. Streak counter and daily notification logic
15. Offline card caching
16. **"Teach it back" mode** — unlocks after mastery, student explains concept, AI evaluates

### Constraints
- Read the full design spec (`~/vibes/tutor/design/2026-04-10-tutor-app-design.md`) — it has ASCII wireframes for every screen
- This replaces the current Jinja2 UI, not supplements it
- Keep the existing FastAPI backend and subject plugin architecture
- Existing Python and Singapore Math curricula must continue working
- DO NOT add more curriculum — focus on the app experience
- Write an AAR every ~20 heats

### Budget
50 heats

## 2026-04-10 03:00 — Direction: Commissioner Polish (10 heats)

### What We Decided
After the protocol fix and tutor redesign, bring the Commissioner app up to Chisel's spec. Focus on the missing interactive pieces.

### Commander's Intent
```json
{
  "intent": "Make the Commissioner app fully interactive — decisions, activity feed, and steering all working",
  "success_looks_like": "Tap-to-decide works on decision cards, Activity tab shows heat feed with auto-summarization, feedback from Direct tab flows to projects",
  "tone": "Implementation-heavy, polish what exists",
  "boundaries": ["Follow Chisel's original design spec", "Web only, laptop-first"],
  "not_this": ["Don't add new screens", "Don't redesign"]
}
```

### Tasks
1. **t-051: Tap-to-decide** (priority 0) — Decision cards get option buttons, POST handler writes decision to project's inbox.md, 5-min undo, confirmation message
2. **Activity tab** — Reverse-chronological heat feed from worklog.tsv, collapsible cards (already started), auto-summarization of older days
3. **Cross-project Inbox** — Pull all pending decisions across all projects into a single queue, actionable inline
4. **Notification tier logic** — Badge counts on tabs, tier classification (push/quiet/in-app) based on decision priority
5. **Visual system: Recall Rhino palette** — Apply the RR design system (colors, typography, spacing, shadows, interactive states). See updated `design/2026-04-09-commissioner-app-design.md` Visual Design section. Reference `~/vibes/rr/instructions/design-system.md` for the source palette.
6. **Responsive check** — Test all screens on phone browser, note what breaks in AAR

### Constraints
- Work on the Commissioner project (inside ai-coworker)
- Reference `design/2026-04-09-commissioner-app-design.md` for specs
- Write AAR at end

### Budget
10 heats

## 2026-04-10 02:00 — Direction: Fix Feedback Protocol (critical bug)

### What We Decided
The tutor project's protocol never got the feedback.md integration from heats 166-170. Forge has been running 68 heats on the tutor without ever reading feedback.md. Human feedback (card creation, priority shift to workflow) was ignored because the protocol literally doesn't tell Forge to read the file. This is a critical protocol bug.

### Commander's Intent
```json
{
  "intent": "Fix the feedback loop so all Forge projects reliably process human feedback",
  "success_looks_like": "Tutor's protocol reads feedback.md, review-first-heat processes new entries, feedback tasks get priority 0, and the human's pending feedback is acted on",
  "tone": "Surgical fix. Don't refactor — patch the gap.",
  "boundaries": ["Fix both ai-coworker and tutor protocols", "Don't change anything else"],
  "not_this": ["Don't redesign the feedback system", "Don't work on the tutor app itself — just the protocol"]
}
```

### Three Fixes

**Fix 1: Sync tutor's loop.md (1 heat)**
Add to `~/vibes/tutor/protocol/loop.md` Step 1 context load:
```
- `feedback.md` — human feedback to act on (first heat of run = review heat)
```
Add the review-first-heat block after stuck detection (copy from ai-coworker's loop.md lines 22-30).

**Fix 2: Add feedback_cursor to state.json (1 heat)**
Add `"feedback_cursor": 0` to both ai-coworker and tutor state.json. Update the review-first-heat protocol in BOTH projects' loop.md:
- On review heat, read feedback.md lines after `feedback_cursor`
- After processing, update `feedback_cursor` to current line count
- This replaces the ambiguous "first heat of a run" trigger with an explicit cursor, same pattern as inbox_cursor

**Fix 3: Feedback tasks get priority 0 (same heat as Fix 2)**
Update the review-first-heat protocol in BOTH loop.md files:
- Tasks generated from feedback.md get `"priority": 0` (highest — above any existing task)
- Add to the protocol text: "Feedback tasks represent explicit human direction. They MUST be prioritized above allocator-generated tasks. Set priority 0."

**Fix 4: Process the pending tutor feedback (1 heat)**
After fixes 1-3 are in place, run a review heat on the tutor project that actually reads feedback.md and:
- Processes the card creation feedback → generates tasks with priority 0
- Processes the "STOP curriculum, focus on workflow" directive → removes or deprioritizes curriculum tasks, generates workflow tasks with priority 0
- Annotates all processed entries with `→ reviewed in heat N`

Also update `forge-init.sh` to include feedback.md in the context load list and the review-first-heat block, so future scaffolded projects get it automatically.

### Constraints
- Work on ai-coworker protocol files first (heats 1-2), then tutor protocol (heat 3)
- Test by verifying feedback_cursor works: write a test entry, confirm it gets picked up
- This is a 3-heat fix, not a redesign

### Budget
3 heats

## 2026-04-10 01:00 — Direction: Generic Multi-Subject Tutor (500 heats)

### What We Decided
The tutor is currently Python-only with a CLI. It needs to become a **generic multi-subject tutor** served as a website. The architecture should support any subject — Python, Grade 3 Singapore Math, college biochemistry, etc. Each subject is a "skill" with its own curriculum, exercises, and pedagogical approach.

We already have one subject (Python). We're adding **Grade 3 Mathematics (Singapore Math)** as the second subject to prove the architecture generalizes.

### Commander's Intent
```json
{
  "intent": "Transform the tutor from a single-subject CLI into a multi-subject web app where users pick a skill and learn interactively",
  "success_looks_like": "A web app at localhost where a user can choose Python or Singapore Math Grade 3, and get a full Socratic tutoring experience in either subject",
  "tone": "Research first, then build methodically. This is a long run — 500 heats. Take time to get the architecture right before scaling subjects.",
  "boundaries": ["Keep the existing Python curriculum working throughout", "Singapore Math Grade 3 must follow actual Singapore Math pedagogy (CPA approach)", "Web app — not CLI"],
  "not_this": ["Don't just slap a web wrapper on the CLI", "Don't hardcode subjects — the architecture must make adding a new subject easy", "Don't build a course marketplace — this is a learning tool, not a platform"],
  "references": ["Current tutor at ~/vibes/tutor/", "Singapore Math CPA (Concrete-Pictorial-Abstract) approach", "Khan Academy's mastery model"]
}
```

### Phase 1: Research (heats 1-5)
Research these questions and write findings to `research/`:

1. **Multi-subject architecture** — How should the curriculum be structured so adding a new subject is just adding a directory/config, not changing the engine? Look at how Duolingo, Khan Academy, and Anki handle multi-subject content.

2. **Singapore Math Grade 3** — What's the actual curriculum? The CPA (Concrete-Pictorial-Abstract) approach. What topics are covered? Number sense, addition/subtraction to 10000, multiplication/division, fractions, measurement, geometry, word problems. How does this map to a skill tree?

3. **Web framework** — The tutor is currently Python. What's the simplest way to serve it as a web app? FastAPI + HTMX (like Commissioner)? Or something else? Consider: interactive code execution for Python, math rendering (LaTeX/MathJax), visual manipulatives for Singapore Math.

4. **Pedagogical differences by subject** — Python needs a code sandbox. Math needs visual representations, step-by-step worked examples, and word problems. How does the tutoring engine adapt its approach per subject? What's generic vs subject-specific?

5. **Synthesis** — Write `research/multi-subject-synthesis.md` with the architecture recommendation, subject schema, and implementation plan.

### Phase 2: Build (heats 6+)
After research, the allocator takes over. Key milestones:
- Subject plugin architecture (curriculum as data, engine as generic)
- Web app with subject selection
- Python curriculum migrated to plugin format
- Singapore Math Grade 3 curriculum (following CPA)
- Interactive exercises: code sandbox for Python, math input for Math
- Progress tracking per subject per user
- Mastery-based progression (don't advance until concept is solid)

### Constraints
- This is a 500-heat run. Pace accordingly — research deeply, build carefully, test thoroughly.
- The Forge is working on the **tutor project** (`~/vibes/tutor/`), not ai-coworker. Use that project's state.json and worklog.
- Use feedback.md if you need human input — the review-first-heat will pick it up.
- Write AARs every ~50 heats for the human to check in on.
- Signal honestly — this is a complex project, expect some 🟡 heats.

### Budget
500 heats

## 2026-04-10 00:00 — Direction: Iteration Tooling (3 stages)

### ⚠️ Budget Fix (do this FIRST)
There was a double-counting bug: both Anvil and Forge were incrementing `budget.total_heats`. Anvil has been fixed (will no longer edit budget). On this run, **reset `budget.total_heats` to `budget.used + N`** where N is the heats for this run (5). Do NOT add N to the current inflated total. This is a one-time correction. Going forward, only Forge manages the budget number.

### What We Decided
The Forge can build things, but the human can't efficiently iterate on them. The feedback loop is broken — there's no structured way to say "fix this" and have it flow into Forge work. We're building the iteration infrastructure in 3 stages across all 3 projects.

### Commander's Intent
```json
{
  "intent": "Build the tooling that lets the human iterate on any Forge project with minimal friction",
  "success_looks_like": "The human can give feedback on tutor or commissioner from one place, and Forge acts on it in the next run without manual dispatching",
  "tone": "Infrastructure work — careful, well-tested, protocol-level changes",
  "boundaries": ["Each stage must work independently", "Don't break existing protocol", "Keep flat-file architecture"],
  "not_this": ["Don't build multi-project Forge yet — that's stage 3, later", "Don't over-engineer — feedback.md is a file, not a database"],
  "references": ["protocol/loop.md", "commissioner/app.py", "dispatch/chisel-to-forge.md"]
}
```

### Stage 1: Feedback Protocol (5 heats on ai-coworker)

**Heat 1 — implementation:** Add `feedback.md` to the protocol.
- Template: human writes freeform feedback, Forge reads it
- Format: dated entries like inbox.md, but project-specific and focused on "what's wrong / what to improve"
- Add `feedback.md` to `forge-init.sh` scaffold so every new project gets one
- Update CLAUDE.md to reference it

**Heat 2 — implementation:** Add review-first-heat to `protocol/loop.md`.
- When feedback.md has new entries, the FIRST heat of a run is a "review heat"
- Review heat: read feedback → examine the relevant code/output → generate prioritized fix tasks → add to queue
- Stage = "planning", but driven by human feedback rather than allocator
- If no new feedback, skip review and proceed normally

**Heat 3 — testing:** Validate the feedback loop.
- Write test feedback to the dogfood project's feedback.md
- Run a heat, verify it picks up the feedback and generates tasks
- Verify forge-init.sh creates feedback.md for new projects

**Heat 4 — editing:** Update all docs.
- protocol/logging.md — document feedback.md format
- README — add feedback section
- STRATEGY.md — update

**Heat 5 — marketing:** Backfill feedback.md for tutor and commissioner.
- Create feedback.md in ~/vibes/tutor/ with the human's feedback ("questions too easy", "good for a first attempt, needs iteration")
- Create feedback.md in commissioner/ with known gaps (no tap-to-decide, no Direct tab)
- These are ready for the next Forge run on those projects

### Stage 2: Commissioner Feedback UI (5 heats on Commissioner)

**After stage 1 is done.** Add feedback input to the Commissioner's Direct tab:
- Per-project text/voice input that writes to that project's feedback.md
- Show recent feedback entries so the human can see what they've already said
- "Send feedback" button that appends to the file
- This makes Commissioner the single iteration hub

### Stage 3: Multi-Project Forge (later, not now)

Deferred. Design only after stages 1 and 2 are validated.

### Constraints
- Start with Stage 1 only (5 heats)
- Stage 2 will be dispatched separately after Stage 1 is confirmed working
- Don't touch tutor or commissioner code in Stage 1 (except creating their feedback.md files)
- Write an AAR at the end

### Budget
5 heats (Stage 1 only)

## 2026-04-09 23:00 — Direction: Build the Commissioner App

### What We Decided
Chisel designed a mobile-first operational app for managing multiple Forge projects. The full design spec is at `design/2026-04-09-commissioner-app-design.md` and the dispatch summary is at `dispatch/chisel-to-forge.md`. Read both before starting.

This is the second real project (after AI Tutor) and a natural evolution — the Forge building its own management interface.

### Commander's Intent
```json
{
  "intent": "Build a working Commissioner web app that lets one person manage 5-10 Forge projects from their laptop, with an eye toward phone usability",
  "success_looks_like": "A functional web prototype (localhost) with Morning Briefing, Home (lifecycle cards), and Decide tab working end-to-end against real Forge state files. Viewable on laptop and phone browser.",
  "tone": "Focused, implementation-heavy. The design is done — build it.",
  "boundaries": ["Follow Chisel's design spec closely", "Web app first — must work well on laptop, should be usable on phone browser", "No backend infrastructure yet — read directly from Forge flat files for the prototype"],
  "not_this": ["Don't redesign what Chisel already decided", "Don't build all 6 screens at once — prioritize the core loop", "No native mobile app yet — web only for now"],
  "references": ["design/2026-04-09-commissioner-app-design.md", "dispatch/chisel-to-forge.md"]
}
```

### Focus Areas

**Phase 1 — Core loop (heats 1-8):**
1. Scaffold the project (new directory, forge-init.sh)
2. Home screen with lifecycle-adaptive project cards reading from real state.json files
3. Morning Briefing screen (needs-you, progress deltas, notable)
4. Decide tab — decision cards with tap-to-decide

**Phase 2 — Steering + polish (heats 9-15):**
5. Direct tab — free-form input, quick actions, intent editor
6. Activity tab — heat feed with auto-summarization
7. Cross-project Inbox
8. Notification tier logic

### Technical Notes
- **Web app** — build with a lightweight web framework (Next.js, Vite+React, or even plain HTML/JS). Must run on localhost.
- For the prototype, read directly from Forge's flat files (state.json, worklog.tsv, outbox.md, dispatch files). A simple Node/Python file server is fine.
- **Laptop-first, phone-aware.** Design for a laptop browser as the primary experience. Use responsive CSS so it's usable (not perfect) on a phone browser. At the end of the build, note in the AAR what would need to change for a true mobile-native experience — this helps us assess the complexity of going to phone later.
- The design spec has ASCII wireframes for every screen — follow them closely, adapting the mobile-first layout to work on wider screens too

### Constraints
- Chisel's design decisions are final for this build. If something seems wrong, flag it in the AAR, don't redesign.
- Signal honestly — 🟡 if a screen is harder to implement than expected, 🔴 if you're blocked.
- Write an AAR at the end.

### Budget
15 heats

## 2026-04-09 22:00 — Direction: First Real Project — AI Tutor

### What We Decided
The Forge has been building itself for 99 heats. It's time for the acid test: build something real. The human chose an **AI tutor** — a tool that helps people learn new things. The audience is either kids or adults (university-level). The first few heats should research and decide which angle to take.

This run tests 6 hypotheses simultaneously:
- **H8**: Does Forge produce useful output on a non-self project?
- **H9**: Can the human assess quality in under 2 minutes?
- **H10**: Do Forge's decisions align with the intent?
- **H5**: Do stoplights compress oversight info?
- **H6**: Does commander's intent maintain coherence?
- **H7**: Does the AAR capture the "why"?

### Commander's Intent
```json
{
  "intent": "Build an AI tutor that helps people learn new things effectively",
  "success_looks_like": "A working prototype that a real person could use to learn a topic, with a clear pedagogical approach",
  "tone": "exploratory first, then focused — research the space before committing to an approach",
  "boundaries": ["No paid API dependencies for the MVP", "No complex infrastructure — keep it runnable locally"],
  "not_this": ["Don't build a generic chatbot wrapper", "Don't build a quiz-only app — learning is more than testing"],
  "references": ["Socratic method", "spaced repetition", "Bloom's 2-sigma problem", "Khan Academy's mastery approach"]
}
```

### Focus Areas

**Heats 1-3 (research):**
- What makes tutoring effective? (Bloom's 2-sigma, zone of proximal development, mastery learning)
- Existing AI tutors — what works, what doesn't (Khan Academy AI, Khanmigo, Duolingo, Synthesis, Quizlet AI)
- Kids vs adults — different needs, different approaches. Recommend one to start with.
- What's a good first subject domain to prototype with?

**Heats 4-5 (planning):**
- Pick the audience and domain based on research
- Design the core learning loop (how does a session flow?)
- Define the MVP scope — what's the minimum that demonstrates real tutoring?

**Heats 6+ (implementation, testing, etc.):**
- Build it. The allocator handles stage selection from here.
- Use `forge-init.sh` to scaffold the project in a new directory

### Setup
- Scaffold the tutor project using `forge-init.sh` in a new directory (e.g., `../../projects/ai-tutor/` or a sibling directory — Smith decides)
- This is a SEPARATE project from ai-coworker. It has its own state.json, worklog, etc.
- But run it from the Forge persona — the protocol is the same

### Constraints
- This is the first non-dogfood project. If the protocol has gaps, document them — that's valuable data for H8.
- Write an AAR at the end — this is the first real test of H7.
- Be honest in stoplights — if you're uncertain, say 🟡. We need real signal, not all-green theater.

### Budget
15 heats

## 2026-04-09 21:00 — Direction: Hypothesis Tracking + Reporting Formalization

### What We Decided
The human chose Version 2 (Hypothesis-Led, Intent as Context) as the standard status report format. Anvil's CLAUDE.md has been updated. A Hypotheses table has been added to STRATEGY.md. Forge needs to:

1. Update `protocol/reporting.md` to document the Version 2 status format as the L1/L2 reporting standard
2. Ensure the Hypotheses table in STRATEGY.md gets maintained — when a hypothesis changes status (validated, invalidated, inconclusive), update it during the regular STRATEGY refresh
3. Add a note in `protocol/logging.md` reminding the Smith to update hypothesis status when a heat produces evidence for or against a hypothesis

### Constraints
- Small task — 2 heats max
- Don't change the status format itself (Anvil owns that), just document it in protocol/reporting.md
- The Hypotheses table is the source of truth for Anvil's status reports

### Budget
2 heats

## 2026-04-09 20:00 — Direction: Operationalize Human-AI Interface

### What We Decided
The interface synthesis (`research/human-ai-interface-synthesis.md`) identified 5 models. The human reviewed it and said "looks good, operationalize it." Implement all 5 in priority order.

### Implementation Plan (follows the synthesis recommendation)

**Heats 1-2: Stoplight Dashboard (#3) + Uncertainty Signaling (#5)**
- Add a `signal` field to each heat in the worklog: 🟢 / 🟡 / 🔴
  - 🟢: value ≥ 0.7, completed normally, no issues
  - 🟡: value < 0.7, progress stalled, deviation from intent, or moderate uncertainty
  - 🔴: rollback, blocked > 5 heats, allocator anomaly, or high uncertainty
- Add an `uncertainty` field to each heat: certain / moderate / uncertain
- Update `protocol/logging.md` to include both fields in the worklog format
- Update the ASCII dashboard to show signals per heat (replace or augment current display)
- Uncertain heats auto-escalate to 🟡 or 🔴

**Heats 3-4: Commander's Intent (#2)**
- Add an `intent` section to the dispatch format (or identity.md) with fields:
  - `intent`: one sentence — what success looks like
  - `boundaries`: what NOT to do
  - `tone`: careful/aggressive/exploratory
  - `references`: examples or analogues to follow
- Update `protocol/loop.md` to read intent at the start of each heat
- Forge should reference intent when generating tasks and making keep/discard decisions
- If a heat's work doesn't serve the intent, it gets 🟡

**Heats 5-6: After-Action Review (#4)**
- Create `aar/` directory
- Generate `aar/YYYY-MM-DD-HH.md` at end of each run (when budget exhausted, Step 8)
- Template: What was planned → What happened → Why the delta → Lessons learned → Open questions
- Update `protocol/loop.md` to include AAR generation as part of the budget-exhausted path
- AAR replaces the current outbox run summary (or supplements it)

**Heats 7-8: Information Compression Layers (#1)**
- Formalize the L0-L4 layer structure in a new `protocol/reporting.md`
- L0: signal + 1-line per heat (already done by heats 1-2)
- L1: 3-line run summary in outbox (already exists, refine)
- L2: `forge-status` script — reads state.json, worklog, shows dashboard on demand
- L3: key artifacts list (files changed, decisions made) — add to AAR
- L4: full worklog + memory (already exists)
- Document when the human should read each layer

### Constraints
- These are implementation + editing heats — modify protocol files, logging, loop
- Test each change by verifying it works within the same run (the Forge is dogfooding)
- Keep changes backward-compatible with existing worklog format (add fields, don't remove)
- Reference the synthesis doc for details on each model

### Budget
8 heats

## 2026-04-09 18:00 — Direction: Human-AI Interface Research

### The Problem
The human cannot effectively assess whether the changes Forge makes are good. The current interface (Anvil chat + inbox.md) handles direction-setting and status reporting, but lacks structure for:
- Evaluating quality of work at the right abstraction level
- Understanding *why* decisions were made, not just *what* was done
- Giving feedback that actually shapes future work
- Maintaining strategic coherence across many heats

We need a higher-level structure for the ideas being tried. The current system works for mechanics (dispatching, logging) but fails at meaning (is this the right thing? is it working?).

### What To Research
All 10 heats should be **research stage**. Generate diverse ideas for how the human-AI interface could work, drawing from **varied domains**:

1. **Corporate governance** — How do boards oversee CEOs? What's the reporting cadence, what metrics matter, how do they evaluate without micromanaging? (quarterly reviews, KPIs, exception-based reporting)

2. **Research labs / academia** — How do PIs supervise PhD students and postdocs? Lab meetings, paper drafts, milestone reviews, the thesis committee model. What works about the advisor relationship?

3. **Military command structures** — Commander's intent, mission-type tactics (Auftragstaktik), after-action reviews. How do you give direction without specifying every step?

4. **Animal colonies** — How do ant colonies, bee hives, and slime molds coordinate without centralized control? Stigmergy (communication through environment modification), pheromone trails, waggle dances. What can distributed intelligence teach us?

5. **Open source projects** — How do maintainers review contributions from strangers? PRs, RFC processes, design docs, LGTM culture. What makes code review actually work?

6. **Venture capital / startup boards** — How do investors monitor portfolio companies? Board decks, metrics dashboards, the "don't call me unless it's bad" model. What's the right information density?

7. **Newsroom editorial** — How do editors manage reporters? Story pitches, editorial judgment, kill decisions, the desk structure. Layers of editorial review without bottlenecking.

8. **Organizational research** — Span of control theory, principal-agent problem, information asymmetry, delegation frameworks (RACI, etc.). What does the research say about effective oversight?

9. **Pair programming / mob programming** — Real-time collaboration models. Driver/navigator, thinking aloud, the role of the observer. When is tight coupling better than loose?

10. **Creative industries** — How do directors work with cinematographers, producers with showrunners, architects with contractors? The brief, the dailies, the review. Creative control at a distance.

For each domain, capture:
- The core insight about oversight/interface
- How information flows between the "overseer" and the "doer"
- What makes it work (or fail)
- A concrete idea for how The Forge could adopt it

### Deliverables
- Individual research docs in `research/` for each domain
- **Synthesis doc**: `research/human-ai-interface-synthesis.md` — top 5 interface models worth prototyping, with pros/cons and a recommendation for which to try first

### Constraints
- Stay in research stage — no implementation
- Think divergently first, then converge in the synthesis
- Don't just describe what exists — propose concrete mechanisms for The Forge
- Each idea should be specific enough that Forge could implement it in 2-3 heats

### Budget
10 heats

## 2026-04-09 16:00 — Direction: AI Worker Landscape Research

### What We Decided
Deep research sweep on the current state of autonomous AI workers — what exists, how they're architected, and what big ideas are emerging. The Forge has been building itself in relative isolation; it's time to map the landscape and identify what we're missing, what we're doing differently, and what ideas are worth stealing.

### Focus Areas
All 10 heats should be **research stage**. Cover these areas:

1. **Existing AI worker/agent frameworks** — Devin, SWE-Agent, OpenHands, Sweep, Aider, Claude Code itself, Cursor Agent, Windsurf, Codex CLI, etc. What's their architecture? How do they loop? How do they manage state?
2. **Orchestration patterns** — How do multi-agent systems coordinate? (CrewAI, AutoGen, LangGraph, Agency Swarm, etc.) What's working, what's hype?
3. **Memory and persistence** — How do long-running agents handle memory? Episodic stores, vector DBs, summarization chains, scratchpads. What's beyond flat files?
4. **Task decomposition and planning** — How do agents break down work? Tree-of-thought, plan-and-execute, ReAct, reflexion. What planning architectures actually work at scale?
5. **Self-improvement and evaluation** — How do agents assess their own output? LATS, self-reflection, reward models, human-in-the-loop signals.
6. **Big ideas and frontier thinking** — What's the boldest stuff being tried? Continuous learning, tool creation, world models, agent-to-agent delegation.

For each system or pattern, capture: architecture, key insight, limitation, and relevance to The Forge.

### Constraints
- Stay in research stage — no implementation, no protocol changes
- Write findings to `research/` as structured markdown docs
- Cite sources where possible (repos, papers, blog posts)
- End with a synthesis doc: `research/landscape-synthesis.md` summarizing top 5 ideas worth adopting

### Budget
10 heats
