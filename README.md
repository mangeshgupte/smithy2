# The Smithy

An autonomous AI worker that runs inside Claude Code. Give it a budget, point it at a project, walk away. It works.

```
cd my-project
claude
> Run 20 heats.
```

The Smith operates in bounded 5-minute units called "heats." Each heat: pick a stage, do one task, commit, log, repeat. No orchestrator. No Python wrapper. Just prose protocol files that Claude Code follows.

## What It Does

The Smith self-directs across six stages — research, planning, implementation, testing, editing, marketing — using a **wavefront allocator** that moves effort through the pipeline like a wave. Early heats are heavy on research. As understanding builds, effort flows to planning, then implementation, then testing. No hardcoded phase transitions.

You communicate asynchronously. Drop ideas in `inbox.md`. Read status in `outbox.md`. Edit `feedback.md` to steer quality. The Smith processes all of it at the top of each heat.

## The Smithy CLI

All bookkeeping goes through `smithy`, a Python CLI that keeps state deterministic:

```
smithy init          # Scaffold a new project
smithy start-heat    # Begin a heat (update counters, read feeds)
smithy allocate      # Wavefront allocator recommends a stage
smithy end-heat      # Close a heat (log, update state, self-assess)
smithy commit        # Git commit with [stage] prefix
smithy patrol --fix  # Find and fix state inconsistencies
smithy status        # At-a-glance project summary
```

28 commands total. 172 tests across all projects. Install: `pip install -e smithy/`

## Bellows

A FastAPI dashboard for managing Forge projects from a browser. Morning briefings, decision queues, activity feeds, direct commands.

```
cd bellows && uv run uvicorn app:app --port 8080
```

## Personas

Two Claude Code sessions, two roles:

| Persona | Role | Start |
|---------|------|-------|
| **Anvil** | Your interface. Explains state, brainstorms strategy, dispatches work. | `cd personas/anvil && claude` |
| **Forge** | The autonomous worker. Runs heats, commits code, writes logs. | `cd personas/forge && claude` |

Anvil sets direction in `dispatch/anvil-to-forge.md`. Forge reports back in `dispatch/forge-to-anvil.md`. Flat files, no magic.

## Getting Started

```bash
# From the Smithy repo:
smithy init my-project ~/projects/my-project --with-personas

# Describe your project:
vim ~/projects/my-project/identity.md

# Start:
cd ~/projects/my-project/personas/forge
claude
> Run 20 heats.
```

## Built With The Smithy

The Smithy dogfoods itself. Over 600 heats, it built:

- **The Smithy protocol** — the system you're reading about
- **AI Tutor** — 5 subjects (Python, Math, English, Logic, Creative Writing), user sessions, PWA offline, SM-2 spaced repetition, teach-it-back, 111 tests
- **Bellows** — project dashboard with initiative board, live run indicator, stage-colored activity feeds, segmented budget bars, tap-to-decide

## Design Principles

- **Prose is the orchestrator.** CLAUDE.md + protocol files. No framework.
- **Flat files.** state.json, worklog.tsv, markdown. Inspect with `cat`.
- **Git is the substrate.** Every heat commits. The record is sacred.
- **Budget-bounded.** Never exceeds allocated heats. Say "Run N" to extend.
- **Self-directed.** Generates its own tasks when the queue runs dry.
