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

## 4. Start All Personas

The Smithy runs three personas in a tmux session — Anvil (your interface), Marshal (allocator), and Forge (worker):

```bash
cd ~/projects/my-app

# Option A: One command (creates tmux session with all three)
smithy start-all

# Option B: Manual (start Anvil, it spawns the others)
cd personas/anvil && claude
> Start
```

`smithy start-all` creates a `smithy2` tmux session with three windows. Each runs Claude Code. Tell Anvil "Start" and it spawns Marshal and Forge as Agent Teams teammates.

## 5. Queue Tasks and Watch Them Execute

The workflow is queue-driven:

```bash
# Add tasks to the queue
smithy add-task implementation "Build the CLI parser"
smithy add-task testing "Write tests for CLI parser"

# Marshal prioritizes and pushes to Forge
smithy set-next-tasks t-001 t-002       # Marshal does this automatically

# Forge pops and executes
smithy queue-pop                        # Forge does this in its loop
```

When Forge finishes a heat, `end-heat` auto-nudges Marshal. Marshal re-prioritizes, calls `set-next-tasks` which auto-nudges Forge. The cycle is nudge-driven, not poll-driven.

If a persona is mid-heat when nudged, the nudge queues to `.smithy-nudge-queue/<persona>.jsonl` and drains on the next idle:

```bash
smithy nudge forge "New priority task available"   # Queues if busy
smithy drain-nudges forge                          # Read + clear queued nudges
```

## 6. Review the Work

While the Forge runs (or after):

```bash
# Quick status
smithy status

# Detailed stats
smithy stats

# See what happened
git log --oneline -20

# List active windows
smithy sessions

# Read the AAR
cat outbox.md
```

## 7. Use Bellows (Dashboard)

```bash
cd bellows
FORGE_PROJECTS_DIR=~/projects uv run uvicorn app:app --port 8080
# Open http://localhost:8080
```

Bellows shows: project cards, activity feeds, decision queues, initiative board, morning briefings.

## 8. Give Feedback

Write to `feedback.md`:
```markdown
## 2026-04-11
- The tests need more edge cases
- CLI output should be colorized
```

The Forge reads feedback at the start of each run and creates fix tasks.

## 9. Steer with Themes + Initiatives

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

## 10. Stop and Resume

```bash
# Graceful shutdown (sends /exit to each Claude session)
smithy stop-all

# Or kill immediately
smithy stop-all --kill

# Resume later
smithy start-all
# In Anvil: "Start"
```

The Smith picks up from the handoff, reads new feedback/inbox, and keeps going.

## Key Principles

- **Prose is the orchestrator** — CLAUDE.md + protocol files, no framework
- **Flat files** — everything inspectable with `cat`
- **Git is the substrate** — every heat commits
- **Budget-bounded** — never exceeds allocated heats
- **Nudge-driven** — personas nudge each other, queue when busy
- **Self-directed** — generates tasks when queue is empty
