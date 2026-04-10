# Plan

## v0.1: Core Protocol — COMPLETE (heats 1-5)
## v0.2: Robustness + New Project Support — COMPLETE (heats 6-25)

## v0.3 Plan: Production Readiness

### Goal
Make The Forge reliable for real daily use. Session cycling, proper testing, protocol hardening.

### Tasks

| ID | Stage | Description | Effort | Blocked By |
|----|-------|-------------|--------|------------|
| t-013 | implementation | Wire up SessionEnd hook in .claude/settings.json | Small | |
| t-014 | implementation | Add /loop integration for auto-restart within session | Medium | |
| t-015 | testing | End-to-end test: run forge-init.sh on a fresh project, run 3 heats | Medium | |
| t-016 | editing | Protocol review: ensure all files consistent after 25 heats of edits | Small | |
| t-017 | planning | Design multi-project state isolation strategy | Small | |
| t-018 | research | Research how to measure actual value (not just self-assessment) | Small | |
| t-019 | implementation | Add allocator visualization to STRATEGY.md (wavefront chart) | Small | |
| t-020 | marketing | Write a "How The Forge Works" deep-dive doc | Medium | |

### What "done" looks like for v0.3
- Can start a fresh project via forge-init.sh and run 20 heats unattended
- SessionEnd hook wired up and distilling memory automatically
- Protocol reviewed and consistent
- At least one non-dogfood project attempted

## v0.4+ Outlook
- Telegram/Slack messaging sidecar
- AI Collaborator integration for design debates
- Dolt-backed task tracking (full beads)
- ChromaDB episodic store
- Web dashboard (htmx)
