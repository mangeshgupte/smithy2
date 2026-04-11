# Dispatch: Forge → Anvil

## 2026-04-10 — Sprint Complete: Bellows Rename + Logic Subject (12 heats)

### What Was Done
12 heats (544-555): Bellows rename, 4th tutor subject (Logic & Critical Thinking), system polish.

### Key Deliverables
1. **Bellows rename** — commissioner → bellows in app, templates, CSS, pyproject, README
2. **Logic subject** — 7 topics, 23 exercises, 5 levels (patterns → argument analysis)
3. **Project identity** — ai-coworker → the-smithy in state.json, identity.md
4. **Bellows README** — comprehensive docs for all 6 screens
5. **Direct tab** — 6 quick-action buttons in 3-col grid
6. **Topic review mode** — 🔄 button on completed topics for practice replay

### Stats
- 158 tests pass (111 tutor + 12 bellows + 35 smithy)
- 4 tutor subjects (Python, Math, English, Logic)
- 18 smithy commands
- Patrol clean, no stale references

### What I Need From Anvil
Nothing blocking. Suggestions for next sprint:
- Dolt backend research (multi-agent future)
- PWA offline caching for tutor
- User authentication
- More subjects (Science? Creative Writing?)

## 2026-04-10 — Sprint Start: Visual Design (20 heats)

### Context
Budget extended to 537 (20 new heats). Previous sprint (500-517) wired smithy CLI into all protocol files. System is mature (90% progress, 517 heats, 152 tests).

### Sprint Focus
Human priority: **visual design**. 13 tasks created across Tutor and Commissioner apps:
- Tutor: subject card redesign, empty states, button consistency, exercise feedback, review polish, monospace fix
- Commissioner: activity feed, budget visualization, decision cards, empty states
- Cross-cutting: visual regression testing, README updates, CHANGELOG v1.0

### First Results (Heat 518-519)
- Sprint planned with concrete task backlog
- Tutor subject cards redesigned: 5px accent bars, topic count badges, taller progress bars, stronger gradients

### What I Need From Anvil
Nothing blocking. Sprint is self-directed from here. Will report back at heat 537 or if blocked.

## 2026-04-10 17:30 — Direction Complete: Adopt Gas Town Patterns (Approach B)

### What Was Done
15 heats (486-500) implemented the three core Gas Town patterns:

1. **smithy handoff + resume** (h486): Save session context to `.forge-handoff.json`, restore on next session, auto-consume. Includes last heats, pending tasks, context notes, next steps.

2. **smithy patrol** (h487): Discover-don't-track validation with 5 checks: worklog count, stuck tasks, stage sum, orphan checkpoint, cursor bounds. Auto-fix mode (`--fix`).

3. **Protocol updated** (h489): Step 0 (resume+patrol on session start), Step 1 (smithy commands for status/feedback/inbox), Step 8 (handoff on budget exhaustion).

4. **STRATEGY updated** (h490): Approach B decision documented, Gas Town relationship section.

### Tests
6 new tests for handoff/patrol. 29 smithy tests total. 152 tests across all projects.

### Smithy CLI — 15 Commands
start-heat, end-heat, validate, status, allocate, pick-task, process-feedback, process-inbox, add-task, complete-task, commit, init, memory-write, handoff, resume, patrol

### What Was Deferred
- Dolt backend (optional, for multi-agent future)
- Multi-agent coordination
- `smithy init` protocol file copying (currently scaffolds state but not protocol/*.md)

## 2026-04-10 16:30 — Direction Complete: Gas Town Integration Research

### What Was Done
5 research heats (481-485) produced 4 documents analyzing Gas Town's architecture and its relationship to Smithy.

### Research Findings

**Gas Town** is a Go-based multi-agent orchestration framework (65+ packages, Dolt-backed) designed for 20+ agents. **Smithy** is a single-agent self-directed system with flat-file state.

**Key gaps in Gas Town that Smithy fills:**
1. No wavefront allocator (work allocation is manual)
2. No persistent memory hierarchy (CV chain only — no STRATEGY.md, no consolidated learnings)
3. No budget system (agents work until done/stuck)
4. No self-assessment or quality signals per work unit
5. No AAR

**Key gaps in Smithy that Gas Town fills:**
1. No multi-agent coordination
2. No merge queue
3. No session cycling / handoff protocol
4. No Dolt-backed queryable state

### Recommendation: Approach B (Adopt Patterns)

Don't merge into Gas Town. Don't fork it. Cherry-pick the best patterns:
- Add `smithy handoff` for session cycling
- Add `smithy patrol` for discover-don't-track validation
- Research Dolt as optional backend later
- Continue flat-file CLI for now

Smithy's innovations (allocator, memory, self-assessment) could be contributed back to Gas Town to fill its strategic memory gap.

### Artifacts
- `research/gas-town-extension-points.md`
- `research/gas-town-state-mapping.md`
- `research/gas-town-comms-mapping.md`
- `research/gas-town-autonomy-memory-gap.md`
- `research/gas-town-integration-synthesis.md`

## 2026-04-10 02:20 — Direction Complete: Feedback Protocol Fix + Commissioner Polish + Tutor UI Redesign

### What Was Done
Three dispatch directions completed across 17 heats (181-197).

**1. Feedback Protocol Fix (2 heats, budgeted 3)**
- Added `feedback_cursor` to both ai-coworker and tutor state.json
- Updated both projects' loop.md with cursor-based review-first-heat
- Feedback tasks get priority 0 (highest)
- Processed pending tutor feedback → 5 new tasks created
- Updated forge-init.sh scaffold

**2. Commissioner Polish (6 heats, budgeted 10)**
- Tap-to-decide: approve/defer/reject buttons on decision cards with POST handler
- Confirmation banner with 5-min undo
- Activity tab: day-grouped heat feed with auto-summarization
- Inbox badges: cross-project decision count on tab bar
- All routes tested E2E, None bug fixed

**3. Tutor App UI Redesign (9 heats, budgeted 20)**
- Three-tab bottom navigation (Learn, Create, Review)
- Chisel design palette: Deep Indigo, Wrong Amber (not red), Hint Blue containers
- Learn Landing: subject cards with progress bars and "Continue →"
- Topic Preview: objectives, prereqs, estimated time, "Start Lesson"
- Create tab: cards.py storage engine, deck landing, card author form
- Review tab: stats-first landing (due/total boxes), SM-2 card player with 4-button rating
- Result page: Socratic hint-blue for wrong answers, "Create Flashcards" CTA on mastery
- Dark mode support via CSS media query

### Signal: 🟢×17

### Artifacts
- `commissioner/app.py` — tap-to-decide + undo routes, badge counts
- `commissioner/templates/decide.html` — actionable decision cards
- `commissioner/forge_reader.py` — day grouping, priority 0 decisions
- `tutor/tutor/cards.py` — student flashcard storage + SM-2
- `tutor/templates/` — 4 new templates (topic_preview, create, card_author, review_landing, review_play)
- `tutor/static/css/style.css` — full redesign to Chisel spec
- `protocol/loop.md` — feedback_cursor in both projects

---

## 2026-04-10 00:30 — Direction Complete: Iteration Tooling Stage 1

### What Was Done
Built the feedback protocol — the infrastructure for iterating on Forge projects.

| Heat | Stage | What |
|------|-------|------|
| 166 | impl | feedback.md template + forge-init.sh scaffold + CLAUDE.md reference |
| 167 | impl | review-first-heat in loop.md — feedback drives first heat of every run |
| 168 | test | 6/6 validation tests pass (exists, content, loop ref, context, CLAUDE, scaffold) |
| 169 | edit | README updated with feedback docs |
| 170 | mktg | Backfilled feedback.md for tutor + commissioner with human's real feedback |

### How It Works
1. Human writes feedback to `feedback.md` (freeform, dated entries)
2. On the first heat of the next run, Forge reads feedback → examines code → generates fix tasks
3. Fix tasks go into the queue, get picked by the allocator in subsequent heats
4. Human's feedback is annotated with "reviewed in heat N" for traceability

### Artifacts
- `feedback.md` — new file in protocol
- `protocol/loop.md` — review-first-heat logic added
- `CLAUDE.md` — references feedback.md
- `forge-init.sh` — scaffolds feedback.md for new projects
- `~/vibes/tutor/feedback.md` — backfilled with tutor feedback
- `commissioner/feedback.md` — backfilled with commissioner feedback

### Ready for Stage 2
Stage 2 (Commissioner Feedback UI) can begin — add feedback input to the Direct tab so the human can write feedback from the browser instead of editing files.
