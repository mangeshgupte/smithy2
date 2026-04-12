# Daily Memory

## 2026-04-10

### Heats 461-470: Bug Fix + Smithy Init

**Syntax highlighting bug** (h461-462): Python highlighter was breaking non-Python examples (English Vocabulary showed raw `<span>` tags). Fixed by adding `data-subject` attribute to example blocks and scoping syntax.js selector to `[data-subject="python"]` only.

**Smithy init** (h463): Replaced forge-init.sh with `smithy init <project-name>` command. Scaffolds all files (state.json, worklog.tsv, identity.md, STRATEGY.md, feedback.md, inbox.md, etc.) with validated initial state. Supports `--with-personas` flag.

**Smithy CLI now has 12 commands:**
start-heat, end-heat, validate, status, allocate, pick-task, process-feedback, process-inbox, add-task, complete-task, commit, init

### Key Stats
- 142 tests (111 tutor + 12 commissioner + 19 smithy)
- All feedback processed and annotated (feedback cursor at 89)
- Smithy fully dogfooded for 20 consecutive heats (441-470)

- [h473 implementation] Test memory write from smithy CLI

- [h476 editing] Heats 471-480: smithy init tests (4), memory-write command, CHANGELOG v0.9, 146 total tests. All feedback processed. Smithy has 13 commands.

- [h511 testing] Stress test: full protocol via smithy CLI validated. Patrol clean after both heats.

- [h524 implementation] Heats 518-524: Visual design sprint started. Subject cards redesigned (5px accent, topic badges), Commissioner activity feed colorized (6 stage colors), monospace font unified, empty states polished, button system standardized (6 utility classes). 13 tasks planned, 5 completed.

- [h530 implementation] Heats 525-530: Visual design sprint mid-point. 9/13 tasks complete. Commissioner: segmented budget bar (stage breakdown), stage-colored activity feed. Tutor: exercise feedback polish (result icon + pop animation), button system, welcome card, CHANGELOG v1.1. All 152 tests pass.

- [h536 planning] Heats 531-536: Visual design sprint complete. All 13 tasks done. Commissioner: decision cards (critical pulse, 5px borders), segmented budget bar, empty states. Tutor: review session polish (slide-in, celebration screen), README updated. Full regression: 152 tests pass, patrol clean. STRATEGY updated to h535.

- [h552 implementation] Heats 544-552: Bellows rename complete (commissioner → bellows). 4th tutor subject: Logic & Critical Thinking (7 topics, 23 exercises, purple accent). Naming: project is 'the-smithy', dashboard is 'Bellows'. Bellows README comprehensive (6 screens). Direct tab: 6 quick-action buttons. 158 tests, patrol clean.

- [h583 implementation] Heats 576-583: Intent hierarchy system built. Data model (themes + initiatives + task linking), Theme CLI (4 commands), Initiative CLI (5 commands), task gating (--initiative, pick-task filters, auto-activate, heats_used tracking). Bellows forge_reader exposes themes/initiatives/intent. Protocol updated. 168 tests (45 smithy), patrol clean.

## 2026-04-11

- [h600 implementation] Heats 591-600: Major sprint. Creative Writing (5th subject, 10 topics, 26 exercises). User sessions (cookie-based, per-user progress/cards). smithy init fixed (CLAUDE.md, protocol files, identity template, post-init guidance). Stats page. Bellows live indicator. smithy stats command (28th). 172 tests. 600 heats milestone.

- [h628 implementation] Heats 614-628: UI polish sprint. Allocator reads constraints (budget_cap suppresses, floor boosts). Timeline drag (left/right/middle edges). Intent Editor delete (cascade). Priority Poker: expand on click (desc+progress+tasks), visual weight, allocation badges, approve proposals. Constraint Board: toggle, quick templates. English Vocab expanded (10 topics). User page progress bar. Bellows STRATEGY viewer. Exercise timer. 172 tests, 4 steering UIs verified.

- [h650 implementation] Heats 644-650: Dolt evaluation (defer, abstraction ready). Achievement badges (8 types, auto-checked). 7 steering UI tests. Bellows sparkline (last 20 heats). README updated with steering UIs table. smithy export (29th cmd). 179 tests total.

- [h660 implementation] Heats 651-659: Cleared 5 stale tasks (t-223, t-230, t-227, t-232, t-246). Marshal system: next-task CLI (30th cmd), dispatch files (forge-to-marshal, marshal-to-forge), protocol updated (next-task first, allocator fallback), Bellows upcoming heats section. Timeline: range control replaces zoom buttons, rich tooltips, overlap detection. Intent Editor: selective apply with checkboxes. SSE /events endpoint on all 4 UIs. 179 tests still passing.

- [h666 implementation] Heats 661-666: Intent Editor history (intents.json snapshots) + templates (4 presets) + export as CLI. Tutor daily goal (progress.py: set/get/increment/history, home widget with sparkline). Hook system: state.py (write/read/delete_hook), CLI (hook/check-hook/unhook = 31st-33rd cmds), wired into end-heat (auto-clear) and patrol (stale hook + GUPP checks, now 7 checks). 53 smithy tests, 111 tutor tests.

- [h726 implementation] Session 721-726: closed 4 of retro §6's 6 candidate tasks in one sweep — parser round-trip test (t-305), Bellows per-heat diff view with id-keyed flattening (t-306), Marshal-steerability UI design study (t-309 recommends extending Poker over 5th UI), and schema_version + optimistic-concurrency primitives in smithy.state (t-307). Key insight: the retro-to-implementation loop was unusually tight because the retro itself listed concrete, scoped candidates with clear value theses — Marshal could triage them straight into p1 tasks with no rewriting. This suggests retros that end in 'candidate tasks with rationale' compound far better than retros that end in 'things to consider.' Also surfaced: queue-pop occasionally returns a just-completed task on the first call after end-heat (stale dispatch ordering); a second pop returns the real next task. Flagged to Marshal but not debugged — low-impact workaround.

- [h761 reliability] state.json corruption one-off: trailing garbage (`_version": 1\n}\n`) appended after a valid close, left the file unparseable. Forge recovered via raw_decode truncation at heat 761 and kept moving. Writer identity not captured. t-316 put mtime preconditions + 409 on every mutating endpoint, so a stale-writer overwrite shouldn't produce this shape — more consistent with a mid-write crash or a CLI path that bypasses the checked-save helper. Not burning a heat yet per team-lead; if it recurs, open a research heat to identify which writer missed the precondition and whether fsync/atomic-replace is needed on the write side.
