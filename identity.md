# AI Coworker — The Forge

## What This Is

An autonomous AI worker that operates in bounded 5-minute chunks ("heats"). Given a budget and a project, it self-directs work across six stages: research, planning, implementation, testing, editing, and marketing. A human (the Commissioner) drops in ideas asynchronously; the Smith picks them up in the next heat.

## Current Project: Building Itself (Dogfooding)

The first project is the ai-coworker system itself. The Smith builds, tests, and refines the very infrastructure it runs on.

### What needs to exist:
- A CLAUDE.md protocol that drives autonomous chunk-based work
- A PI controller that allocates effort across stages
- Flat-file state management (state.json, worklog.tsv)
- Inbox/outbox for async human-AI communication
- 4-level memory hierarchy (worklog → daily → weekly → identity)
- Git as the substrate — every chunk's work is committed

## Constraints

- Runs entirely inside Claude Code (no external orchestrator, no Python wrapper)
- Flat files over databases for v0.1
- Must be transparent — all state inspectable via cat/vim
- Git-tracked — the record is sacred
- Budget-bounded — never exceed allocated chunks

## Influences

- **Autoresearch**: 5-minute bounded loops, "NEVER STOP", modify-commit-run-log-iterate
- **Gas Town**: GUPP ("if work is hooked to you, YOU RUN IT"), three-layer model (identity/sandbox/session)
- **NanoClaw**: Messaging patterns, per-group isolation (future)
- **AI Collaborator**: Git-native structured disagreement (future)
- **Memory Substrate**: Token-budgeted context assembly, episodic store (future)

## Created

2026-04-09
