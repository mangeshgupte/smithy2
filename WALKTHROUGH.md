# Getting Started with The Smithy

A complete walkthrough: from zero to autonomous AI worker in 5 minutes.

## 1. Install

```bash
cd smithy/
pip install -e smithy/    # Install the CLI
smithy --help             # Verify: should show 28 commands
```

## 2. Create a Project

```bash
smithy init my-app --target ~/projects/my-app
```

This creates:
- `CLAUDE.md` — protocol hub (tells Claude Code how to work)
- `protocol/` — loop.md, allocator.md, logging.md, reporting.md
- `state.json` — budget, stages, queue, themes, initiatives
- `identity.md` — describe your project + commander's intent
- `worklog.tsv` — append-only heat log
- `inbox.md` / `outbox.md` / `feedback.md` — async communication

## 3. Describe Your Project

Edit `identity.md`:

```markdown
# my-app

## What This Is
A todo app with natural language input.

## Commander's Intent
- Intent: Build a clean, functional CLI todo app
- Success looks like: User can add, list, complete, and delete tasks
- Tone: Simple and well-tested
- Boundaries: No database — flat file storage
- Not this: No web UI, no cloud sync
```

## 4. Start the Forge

```bash
cd ~/projects/my-app
claude                    # Start Claude Code
> Run 20 heats.          # Tell it to work
```

The Smith will:
1. Read your intent from `identity.md`
2. Use the wavefront allocator to pick what stage to work on
3. Research, plan, implement, test, edit, and document — all autonomously
4. Commit every heat with `[stage] description`
5. Stop after 20 heats and save a handoff

## 5. Review the Work

While the Forge runs (or after):

```bash
# Quick status
smithy status

# Detailed stats
smithy stats

# See what happened
git log --oneline -20

# Read the AAR
cat outbox.md
```

## 6. Use Bellows (Dashboard)

```bash
cd bellows
FORGE_PROJECTS_DIR=~/projects uv run uvicorn app:app --port 8080
# Open http://localhost:8080
```

Bellows shows: project cards, activity feeds, decision queues, initiative board, morning briefings.

## 7. Give Feedback

Write to `feedback.md`:
```markdown
## 2026-04-11
- The tests need more edge cases
- CLI output should be colorized
```

The Forge reads feedback at the start of each run and creates fix tasks.

## 8. Steer with Themes + Initiatives

```bash
# Create a strategic theme
smithy add-theme "Core Features"

# Propose an initiative under it
smithy propose th-001 "User Auth" "Add login/logout with session tokens"

# Approve it (Forge won't work on it until approved)
smithy approve ini-001

# Tasks linked to initiatives are gated by approval
smithy add-task implementation "Login route" --initiative ini-001
```

## 9. Continue Working

```bash
> Run 20 heats.    # Extend the budget anytime
```

The Smith picks up from the handoff, reads new feedback/inbox, and keeps going.

## Key Principles

- **Prose is the orchestrator** — CLAUDE.md + protocol files, no framework
- **Flat files** — everything inspectable with `cat`
- **Git is the substrate** — every heat commits
- **Budget-bounded** — never exceeds allocated heats
- **Self-directed** — generates tasks when queue is empty
