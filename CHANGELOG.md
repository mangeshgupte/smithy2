# Changelog

## v1.3 — User Sessions + Creative Writing + Init Fix + Stats (heats 576-600)

### Creative Writing — 5th Subject
- **10 topics** across 5 levels: show-don't-tell, strong verbs, sensory details, sentence variety, eliminating wordiness, voice & tone, figurative language, dialogue, scene vs summary, opening hooks
- **26 exercises**: free_response (rewrites, analysis), multiple_choice (identify technique), fill_in_blank
- Pink accent color (#EC4899)

### User Sessions
- **Cookie-based user ID** with middleware — each user gets isolated progress and cards
- **User switcher** (`/user`): enter name, stored as cookie, displayed in nav bar 👤 tab
- **Per-user storage**: `~/.tutor/users/<id>/progress.json` + `cards.json`
- Backward compatible: no user cookie = global (legacy) progress

### Intent Hierarchy
- **Themes + Initiatives** in state.json with full validation
- **9 CLI commands**: add-theme, list-themes, pause/activate-theme, propose, approve, reject, complete-initiative, list-initiatives
- **Task gating**: `--initiative` on add-task, pick-task filters by initiative status, auto-activates, heats_used tracking
- **Allocator gating**: only eligible tasks affect scoring
- **Bellows Board page**: themes → initiatives, approve/reject from UI, status-colored cards
- **Bellows home badges**: blue proposal count on project cards

### smithy init — End-to-End Fix
- Now generates **CLAUDE.md** (protocol hub)
- Copies **all 4 protocol files** (loop.md, allocator.md, logging.md, reporting.md)
- **Commander's Intent template** in identity.md with placeholders
- Prints **next steps** after init

### New Features
- **Tutor stats page** (`/stats`): subjects, topics completed, cards, streak, per-subject breakdown
- **Bellows live indicator**: pulsing green "running" badge when checkpoint exists
- **`smithy stats` command**: stage distribution, signal counts, theme/initiative summary
- **SW v2**: network-first for localhost (fixes dev caching)

### Stats
- **5 tutor subjects**: Python, Math, English, Logic, Creative Writing — 49 topics, 188 exercises
- **28 smithy commands**, 45 smithy tests
- **172 total tests** (111 tutor + 16 bellows + 45 smithy)
- **600 heats milestone**

## v1.2 — PWA Offline + Content Expansion + Naming (heats 548-567)

### PWA Offline Support
- **Service worker** (`sw.js`): cache-first for `/static/`, network-first with fallback for pages
- **manifest.json**: installable as app (standalone display, teal theme)
- **Offline page**: graceful fallback when network unavailable
- Service worker registration in base.html + `/manifest.json` and `/sw.js` FastAPI routes

### Logic & Critical Thinking — 4th Subject
- **10 topics** across 5 levels: number patterns, odd-one-out, if-then, syllogisms, fallacies, analogies, argument analysis, counterexamples, hidden assumptions, evaluating evidence
- **32 exercises**: math_input, multiple_choice, fill_in_blank, free_response
- Purple accent color with gradient overlay

### New Features
- **Difficulty indicators**: ●●○ dots on exercises (orange, 1-3 scale from curriculum data)
- **Topic review mode**: 🔄 button on completed topics for quick practice replay
- **Bellows Direct tab**: 6 quick-action buttons in 3-col grid (Run 10/20/50, Focus testing/building/design)

### Naming & Cleanup
- Commissioner app → **Bellows** (directory, app title, CSS, pyproject, README, templates)
- Project name: ai-coworker → **the-smithy** (state.json, identity.md)
- Bellows README: comprehensive docs for all 6 screens
- Old `forge-*.sh` scripts removed (636 lines) — all in smithy CLI now

### Stats
- **4 tutor subjects** (Python, Math, English, Logic) — 39 topics, 130 exercises
- **18 smithy commands**, 35 smithy tests
- **158 total tests** (111 tutor + 12 bellows + 35 smithy)
- Patrol clean across all runs

## v1.1 — Visual Design Sprint + CLI Completion (heats 518-547)

### Tutor Visual Redesign
- **Subject cards**: 5px accent bars (was 3px), topic count badges, taller progress bars, stronger accent gradients
- **Welcome card**: "Learn by Doing" copy, feature cards with icons + descriptions, contextual CTA (Start Learning / Continue / Resume)
- **Empty states**: Card-style with dashed borders, emoji icons, rich messaging, guidance CTAs
- **Button system**: 6 utility classes (btn-lg, btn-sm, btn-block, btn-stack, btn-green, btn-mt) — replacing inline styles
- **Monospace fonts**: Unified font stack (JetBrains Mono → Fira Code → Cascadia Code), tab-size: 4, consistent line-height
- **Exercise feedback**: Result icon with pop animation, centered colored title
- **Review session**: Card slide-in animation, celebration screen with icon pop

### Commissioner Visual Redesign
- **Stage colors**: 6 distinct colors (purple research, blue planning, green implementation, yellow testing, orange editing, red marketing)
- **Activity feed**: Stage-colored left borders on heat cards, colored stage badges, value color coding (green/yellow/red)
- **Stage bars**: Color-coded progress fills in project detail view
- **Budget visualization**: Segmented bar showing stage breakdown with legend
- **Decision cards**: 5px priority borders, critical pulse animation, stage-colored badges
- **Empty states**: Dashed borders, emoji icons across all screens

### New Smithy Commands (2)
- `smithy update <target>` — copy protocol files to existing project (replaces forge-update.sh)
- `smithy repomap [target]` — generate research/repo-map.md with file stats, dir structure, key files (replaces forge-repomap.sh)

### Cleanup
- Removed 5 forge-*.sh scripts (636 lines) — all functionality now in smithy CLI (18 commands total)
- 6 new tests for update + repomap (35 smithy tests, 158 total)

### Protocol Wired to CLI (heats 508-517)
- All 3 protocol files rewritten: loop.md, logging.md, allocator.md
- Zero manual state edits — all mutations go through smithy commands
- 2 stress test heats passed with patrol clean
- **New rule**: "NEVER directly edit state.json or worklog.tsv"

## v1.0 — Gas Town Patterns + 500-Heat Milestone (heats 481-500)

### Gas Town Integration Research
- 5 research docs analyzing extension points, state mapping, comms, autonomy/memory gaps
- **Decision: Approach B** — adopt patterns, stay independent

### New Smithy Commands (3)
- `smithy handoff` / `smithy resume` — session cycling (save/restore context across sessions)
- `smithy patrol [--fix]` — discover-don't-track validation (5 checks, auto-repair)
- `smithy sync-stages` — recalculate stage heats from worklog (fixes drift)

### Protocol Updates
- **Step 0** (new): `smithy resume` + `smithy patrol --fix` on session start
- **Step 8**: `smithy handoff` before stopping

### Milestone: 500 Heats
- 16 smithy commands, 29 smithy tests
- 152 total tests (111 tutor + 12 commissioner + 29 smithy)
- Patrol fully clean — zero discrepancies
- Stage heats synced from actual worklog data

## v0.9 — Smithy CLI + Visual Polish + Bug Fixes (heats 286-480)

### Smithy CLI (13 commands)
- `smithy start-heat` / `end-heat` — deterministic heat bookkeeping (counters, cursors, integrals)
- `smithy allocate` — wavefront allocator ported to Python
- `smithy pick-task` / `add-task` / `complete-task` — queue management with auto-incrementing IDs
- `smithy process-feedback` / `process-inbox` — cursor-based feed processing
- `smithy validate` / `status` — state consistency checks and L0/L1 summary
- `smithy init` — project scaffolding (replaces forge-init.sh)
- `smithy commit` — git add + commit with [stage] prefix
- `smithy memory-write` — append notes to MEMORY_DAILY.md
- **23 tests**, installable via `pip install -e smithy/`

### Recall Rhino Palette
- Playful Teal (#00BCD4), Energy Orange (#FF9800), Focus Green (#4CAF50), Review Yellow (#FFEB3B), Sky Blue (#ADD8E6)
- Subject accents: Orange=Python, Teal=Math, Green=English
- Dark mode removed — RR light palette applies everywhere

### Tutor Features
- **Teach It Back** — student explains concept, AI evaluates (Bloom's top level)
- **Topic completion summary** — mastery %, forward CTAs, card creation nudge
- **Card editing** — edit/delete from deck view
- **Python syntax highlighting** — scoped to Python examples only
- **Forward-CTA pattern** — success always leads forward, retry is secondary
- **6 CSS animations** — correct pulse, wrong shake, Socratic slide-up, streak bounce, card reveal, saved check
- **Onboarding welcome card** for first-time users

### Commissioner Features
- **Bottleneck indicator** on project cards
- **Last-active timestamp** from worklog
- **12 forge_reader tests**

### Bug Fixes
- Syntax highlighting no longer breaks non-Python examples
- Forward-CTA pattern across 4 success templates
- Teach It Back promoted to primary green CTA
- Dark mode CSS removed (was hiding RR palette)

## v0.8 — Tutor UI Redesign + Commissioner Polish (heats 181-285)

### Tutor App — Full Redesign
- **3-tab navigation**: Learn, Create, Review (bottom tab bar)
- **Create tab**: student-created flashcards with AI review, deck view, card editing/deleting
- **Review tab**: stats-first landing (due/done/total), SM-2 card player (forgot/hard/good/easy), review summary with strong/weak tracking
- **Teach It Back**: student explains concept, AI evaluates — unlocks after mastery
- **Design palette**: Deep Indigo, Wrong Amber, Hint Blue, subject accent bars, dark mode
- **Session memory**: resume interrupted sessions, exercise progress tracking
- **Streak counter**, weekly progress chart, onboarding welcome card
- **100 tests** across 9 test files (17 card tests, 20 integration tests)

### Commissioner App
- **Tap-to-decide**: approve/defer/reject buttons on decision cards with confirmation + undo
- **Notification tiers**: push/quiet/in-app classification based on priority
- **Activity tab**: day-grouped heat feed with auto-summarization
- **Inbox badges**: cross-project decision count
- **Briefing**: decision queue section with tier counts

### Protocol
- **feedback_cursor**: explicit cursor-based feedback tracking (replaces "first heat" heuristic)
- **Lint→test→fix loop**: run tests before commit, fix failures in-heat
- **Self-critique (Reflexion)**: review before commit — edge cases, intent alignment, missed items
- **forge-repomap.sh**: auto-generate repo map for new project orientation

## v0.5.1 — Interface Operationalization (heats 100-115)

### New Tools
- `forge-status.sh` — zero-effort L2 dashboard (budget, stages, signals, alerts, commits, what's missing)

### Protocol Additions
- `protocol/reporting.md` — L0-L4 information compression layers
- AAR now writes to `aar/` directory (not just outbox)
- `CLAUDE.md` references reporting.md

### v0.6 Planning
- v0.6 plan with 6 tasks: real-project run, repo map, lint→test→fix, self-critique, WhatsApp research, event-sourced state design

### Documentation
- README: forge-status, forge-validate in check-status section
- README: --with-personas example in quick-start
- CHANGELOG: updated through heat 115

---

## v0.5 — Polish + Real-World Validation (heats 39-99)

### Interface Improvements
- **Stoplight signals** (🟢/🟡/🔴) per heat — human reads only yellows/reds
- **Uncertainty field** in worklog — Forge flags uncertain decisions
- **Self-critique** in worklog notes — "Could improve: ..." after each heat
- **Commander's intent** in identity.md — strategic direction for all decisions
- **After-action review (AAR)** generated at end of each run

### Allocator Fixes
- **Soft clamp ±0.5** (was ±1.0) — prevents integral recovery traps
- **Unblocking override** — +0.3 boost for tasks that unblock 2+ others
- **Queued task bonus** — +0.07/ready task prevents dead tasks in low-scoring stages
- **Auto-task generation** — queue replenishes when ≤3 pending tasks

### New Tools
- `forge-update.sh` — update protocol files in existing projects
- `forge-validate.sh` — automated state/protocol integrity checks (19 checks)

### Scaffold Improvements
- `.gitignore` in forge-init.sh scaffold
- Guided templates with HTML comments for identity.md and STRATEGY.md
- Commander's intent template in identity.md

### Documentation
- FAQ/Troubleshooting section in README
- SessionEnd hook setup guide
- Example dashboard output
- Updated file structure diagram with personas, dispatch, hooks

### Research
- Human-AI interface: 10 domains, 22 ideas, top 5 synthesized
- AI worker landscape: Devin, OpenHands, CrewAI, Aider + synthesis
- Adaptive queue management, dead task problem, Telegram bridge design

---

## v0.4 — Real-Project Readiness (heats 39-68)
- Non-dogfood project scaffold tested (todo-cli)
- forge-update.sh for protocol updates
- 8 automated data integrity checks
- v0.4 status reporting to outbox.md

## v0.3 — Personas + Production (heats 26-38)
- 2-persona system: Anvil (interface) + Forge (worker)
- Dispatch files for inter-persona communication
- Value measurement research
- Wavefront visualization in STRATEGY.md

## v0.2 — Robustness + Scaffolding (heats 6-25)
- Beads DAG research → blocked_by task dependencies
- forge-init.sh project scaffolding
- SessionEnd hook for memory distillation
- Checkpoint file for crash recovery
- Fresh-session resume tested (28KB cold start)
- Anti-windup fix for PI controller (0.85 decay)

## v0.1 — Core Protocol (heats 1-5)
- 8-step heat loop
- Wavefront allocator with PI controller
- Flat-file state management (state.json, worklog.tsv)
- Inbox/outbox async communication
- 4-level memory hierarchy
- Git as the substrate
