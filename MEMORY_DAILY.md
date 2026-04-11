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
