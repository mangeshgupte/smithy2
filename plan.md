# Plan

## v0.1 Status: Core Protocol Complete

All original v0.1 tasks done (t-001 through t-004). Additional features added: idea pipeline, heat dashboard, idea status tracking, vocabulary standardization, anti-windup for PI controller. Protocol tested with 10 scenarios (all pass). README shipped.

**v0.1 remaining work:**
- Prune completed tasks from state.json queue (housekeeping)
- Final protocol review for consistency after all edits
- Test fresh-session resume (can a new Claude Code session pick up from state.json?)

## v0.2 Plan: Robustness + New Project Support

### Goal
Make The Forge usable for projects other than itself. Add session resilience.

### Tasks (priority order)

| ID | Stage | Description | Effort |
|----|-------|-------------|--------|
| t-005 | implementation | Checkpoint file (.forge-checkpoint.json) before risky work | Small |
| t-006 | implementation | SessionEnd hook for automatic memory distillation | Medium |
| t-007 | implementation | Project template: script to scaffold Forge files in a new directory | Small |
| t-008 | planning | Design multi-project state isolation (state per project or shared?) | Small |
| t-009 | testing | Fresh-session resume test: stop, start new session, verify continuity | Medium |
| t-010 | editing | Prune completed tasks/ideas from state.json (or archive them) | Small |
| t-011 | marketing | Quick-start guide: "Set up The Forge for your project in 2 minutes" | Small |

### Dependencies
- t-006 depends on t-005 (checkpoint file needed before SessionEnd hook)
- t-007 depends on t-008 (template needs to know multi-project strategy)
- t-009 can run independently (manual test)

## v0.3+ Outlook

- /loop integration for medium runs (20-50 heats)
- External cron + SessionEnd for long runs (50+ heats)
- Telegram/Slack messaging sidecar
- AI Collaborator integration for design debates
- ChromaDB episodic store (v0.6)
