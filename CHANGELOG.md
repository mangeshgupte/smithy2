# Changelog

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
