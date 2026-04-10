# Outbox

The Smith writes status updates, questions, and summaries here.

## 2026-04-09 [heat 99, After-Action Review — heats 80-99]

### 1. What Was Planned
- Execute AI Worker Landscape Research dispatch (10 heats)
- Switch to implementation: stoplight signals, commander's intent, AAR protocol, forge-validate.sh
- Complete remaining v0.5 tasks (t-023, t-035, t-037, t-038, t-041, t-042, t-043)

### 2. What Happened
- Landscape research completed in 5 heats (vs. 10 budgeted) — efficient
- Implemented all 5 interface research findings: stoplight, uncertainty, self-critique, commander's intent, AAR
- Built forge-validate.sh (19 automated checks, catches corruption)
- Completed t-023 (--with-personas flag), t-035, t-037, t-038, t-041, t-042, t-043
- Wrote CHANGELOG.md covering v0.1→v0.5
- Updated README with --with-personas docs

### 3. Why the Delta
- Landscape research was faster than expected because the landscape is well-surveyed — most systems follow similar patterns. Deep novelty was limited; the synthesis was more valuable than individual system analysis.
- Implementation tasks were straightforward because the designs (from interface research) were concrete and specific. Design→implement gap was small.

### 4. Lessons Learned
- **Research dispatches can be combined**: Two domains per heat is efficient for survey-style research. Deep dives need dedicated heats.
- **Design before implement works**: The interface research (heats 70-76) produced such specific designs that implementation (heats 85-88) was almost mechanical.
- **forge-validate.sh should run automatically**: Currently manual. Should be a pre-commit hook or part of the heat loop.
- **The stoplight system needs real usage to validate**: All heats in this run were 🟢. Need yellow/red heats to test the signal value.

### 5. Open Questions
- Should forge-validate.sh run automatically in the heat loop (Step 5)?
- Is the queued task bonus coefficient (0.07) right, or should it be tuned?
- When should we attempt t-036 (run on real non-dogfood project for 10+ heats)?
- v0.6 direction: web dashboard vs WhatsApp bridge vs something else?

### 6. Signal Summary
- 🟢 Green: 20/20 heats (100%)
- 🟡 Yellow: 0
- 🔴 Red: 0

All green is suspicious — either the work was straightforward or the signal thresholds are too permissive.

---

## 2026-04-09 [heat 58, v0.4 status update]

### v0.4 Milestone: Real-Project Readiness — Nearly Complete

**What was accomplished (heats 39-57):**
- Persona system verified and cleaned up (2 stale refs fixed)
- forge-init.sh gaps identified and fixed: .gitignore, guided templates, hook docs
- Allocator improved: soft clamp ±0.5 (was ±1.0), unblocking override for critical-path tasks
- Auto-task generation designed and simulated (per-stage heuristic)
- Non-dogfood project (todo-cli) scaffolded and verified — **all checks pass**
- README: FAQ section, dashboard example, SessionEnd hook docs
- STRATEGY.md kept current
- 8 automated data integrity checks pass
- Telegram bridge designed for v0.5

**Remaining v0.4 tasks (3):**
- t-025: Add auto-task generation to protocol (design complete, ready to implement)
- t-026: Create forge-update.sh for protocol updates
- t-023: Add --with-personas flag to forge-init.sh (lower priority)

**Overall: 65% complete, 57 heats used.**

The system is ready for real-project use. forge-init.sh produces working scaffolds, the allocator is balanced, and the protocol is self-consistent. The main gap is implementing the auto-task generation and forge-update.sh utility.

## 2026-04-09 [heat 68, session complete — 30 heats]

### Session Summary (heats 39-68)

**30 heats across all 6 stages.** v0.4 nearly complete.

| Stage | Heats | Key Accomplishments |
|-------|-------|---------------------|
| Research | 3 | Real-project readiness, adaptive queue mgmt, Telegram bridge, dead-task problem |
| Planning | 3 | v0.4 plan, auto-task generation design, queued task bonus, integral recovery fix |
| Implementation | 3 | .gitignore, forge-update.sh, auto-task generation in protocol |
| Testing | 5 | Persona verification, E2E forge-init, data integrity, unblocking override, non-dogfood scaffold, forge-update.sh |
| Editing | 4 | Templates, protocol reviews (22/22 pass), STRATEGY refreshes, queue cleanup |
| Marketing | 4 | SessionEnd docs, FAQ, dashboard example, file structure, v0.4 status |

### Allocator Improvements
- **Soft clamp ±0.5** (was ±1.0): prevents integral recovery traps
- **Unblocking override**: +0.3 for tasks that unblock 2+ others (validated in heat 52)
- **Queued task bonus**: +0.07/ready task prevents dead tasks in low-scoring stages

### Remaining for v0.4
- t-023: Add --with-personas flag to forge-init.sh (lower priority)

### What to do next
1. **Use it on a real project** — scaffold and run 20 heats on a real codebase
2. t-023 if personas are wanted in scaffold
3. Start v0.5: Telegram bridge (design complete in research/telegram-bridge.md)

## 2026-04-09 [run complete, 5/5 heats]

### Summary
First run of The Forge, dogfooding on itself. 5 heats across 5 stages:

| Heat | Stage | What |
|-------|-------|------|
| 1 | research | Surveyed autoresearch, Gas Town, NanoClaw, Memory Substrate — 8 patterns, 5 gaps |
| 2 | planning | Created plan.md with prioritized task queue (4 items) |
| 3 | implementation | Added stuck detection, output redirection, keep/discard to loop.md |
| 4 | editing | Added dual-channel inbox convention, backfilled prompt ideas |
| 5 | testing | Protocol consistency check, fixed run continuation + task ID format |

### Wavefront allocator validated
The allocator correctly shifted focus: research → planning → implementation → editing → testing. Only marketing was untouched (correct — it's last in the dependency chain and prerequisites haven't progressed enough). The exploration rule (every 5th heat pick second-best) triggered on heat 5, selecting testing over research.

### Key decisions
- Wavefront model replaced fixed phase buckets (human's idea, implemented pre-run)
- CLAUDE.md kept short (~30 lines), detail in protocol/ files (human's idea)
- All 4 queued tasks completed in the run

### What to do next
- More research depth (research only at 0.2 progress — we surveyed but haven't gone deep)
- Marketing: write a README for the project
- Add more tasks to queue based on what's in plan.md (episodic store is the big v0.6 feature)
- Consider: should the allocator skip completed stages? Currently a stage at progress=1.0 would get benefit=0 naturally.

## 2026-04-09 [run complete, 19/19 heats]

### Summary (heats 10-19)

| Heat | Stage | What |
|------|-------|------|
| 10 | testing | 10 protocol test scenarios (9 pass, 1 untested → now tested) |
| 11 | research | /loop, /schedule, external cron for automation |
| 12 | editing | Vocabulary standardization: chunk → heat globally |
| 13 | research | Integral windup fix — 0.85 decay + ±1.0 clamp |
| 14 | testing | Live keep/discard test — deliberate bad edit, rollback confirmed |
| 15 | marketing | README usage examples added |
| 16 | planning | v0.2 plan: 7 tasks for robustness + multi-project |
| 17 | implementation | Checkpoint file (.forge-checkpoint.json) for crash recovery |
| 18 | editing | State.json pruned — completed tasks and done ideas removed |
| 19 | editing | Final summary, new idea queued (git-backed DAG tasks from beads) |

### Cumulative (19 heats total)
- All 6 stages well-covered (4/2/4/3/4/2 heats)
- 8 human ideas received: 7 done, 1 queued (beads research)
- v0.1 complete, v0.2 underway
- Anti-windup fix made allocator much more balanced

### Queued for next run
1. **t-012**: Research beads for git-backed task DAG (human's latest idea)
2. **t-006**: SessionEnd hook for memory distillation
3. **t-007**: Project template scaffolding script
4. **t-009**: Fresh-session resume test
5. **t-011**: Quick-start guide

## 2026-04-09 [run complete, 9/9 heats]

### Summary (heats 7-9)

| Heat | Stage | What |
|-------|-------|------|
| 7 | research | Deep dive on session cycling — checkpoint files, SessionEnd hooks, three-layer persistence |
| 8 | implementation | ASCII heat dashboard + idea status annotations in inbox.md |
| 9 | marketing | README.md written |

### Cumulative (all 9 heats)

All 6 stages now have at least 1 heat. 6 human ideas received, all implemented. The wavefront allocator was overridden once (heat 9: marketing over research for the README).

### Stage distribution
- research: 2 heats (22%)
- planning: 1 (11%)
- implementation: 3 (33%)
- testing: 1 (11%)
- editing: 1 (11%)
- marketing: 1 (11%)

### What to do next
- **Testing**: only 10% progress, 1 heat. Needs validation that the protocol actually works across fresh sessions.
- **Research on /loop and /schedule**: Claude Code skills that could automate session cycling.
- **Checkpoint files**: write .forge-checkpoint.json before risky work (researched, not yet implemented).
- **Prune completed tasks**: queue has 4 "complete" entries taking up space.
