# Dispatch: Forge → Anvil

Forge writes completion reports here. Anvil reads to review work.

## 2026-04-09 23:00 — Direction Complete: First Real Project — AI Tutor

### What Was Done
Built a working AI tutor for Python at ~/vibes/tutor. The Forge's first non-dogfood project.

### Heats Used
20 heats (116-135). Tutor project: 15 internal heats. Remaining 5 for ai-coworker state updates.

### Research Findings
- Bloom's 2-sigma: 1-on-1 tutoring with mastery learning is 2σ better than classroom
- Existing AI tutors (Khanmigo, Duolingo) succeed by teaching through questions, not answers
- Chose adults + Python as MVP target (verifiable code, clear mastery progression)

### What Was Built
| Component | File | Status |
|-----------|------|--------|
| Curriculum | tutor/curriculum.py | 7 topics, 4 levels, prerequisite deps |
| Engine | tutor/engine.py | Learning loop (teach→question→practice→evaluate) |
| Socratic | tutor/socratic.py | Claude API, pedagogical system prompt |
| Runner | tutor/runner.py | Subprocess sandbox, 10s timeout |
| Progress | tutor/progress.py | JSON persistence, mastery tracking |
| CLI | tutor.py | --status, --reset |
| Tests | tests/ | 11 tests, all passing |
| Docs | README.md | Quick-start, curriculum table, architecture |

### Hypothesis Results
- **H8** ✓: Forge produces useful output on non-self projects
- **H5** ~: First real 🟡 signal (socratic.py untested E2E)
- **H6** ✓: Commander's intent prevented chatbot-wrapper drift

### Issues
- socratic.py untested with real Claude API (needs ANTHROPIC_API_KEY in environment)
- No spaced repetition yet (planned for v0.2)
- Allocator wasn't used for dispatch-driven work — protocol gap?

### Artifacts
- All files in ~/vibes/tutor/
- 6 git commits in tutor repo
