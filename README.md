# The Smithy

An autonomous AI worker that runs inside Claude Code. Give it a budget, point it at a project, walk away. It works.

**New here?** → [QUICKSTART.md](QUICKSTART.md) (5 min) · [WALKTHROUGH.md](WALKTHROUGH.md) (narrative) · [STEERING.md](STEERING.md) (UIs)

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
smithy init          # Scaffold a new project (see --template=<shape>)
smithy start-heat    # Begin a heat (update counters, read feeds)
smithy allocate      # Wavefront allocator recommends a stage
smithy end-heat      # Close a heat (log, update state, self-assess)
smithy commit        # Git commit with [stage] prefix
smithy patrol --fix  # Find and fix state inconsistencies
smithy status        # At-a-glance project summary
smithy up            # Launch the tmux rig (--force, --dry-run, --session NAME)

# Queue & coordination
smithy queue-push    # Add a task to the next_tasks queue
smithy queue-pop     # Claim the next task from the queue
smithy set-next-tasks # Set ordered task list (Marshal → Forge)
smithy list-tasks    # List tasks with filters (status, stage, limit)

# Attribution & retros
smithy steering-retro      # Weekly digest: pins, ships, pin→ship lag, by-actor
                           #   --since=7d|24h|ISO, --format=markdown|json

# Session management
smithy start-all     # Launch smithy2 tmux session with all personas
smithy stop-all      # Gracefully stop all persona sessions
smithy sessions      # List active persona windows
smithy nudge         # Send a message to a persona (queues if busy)
smithy drain-nudges  # Read and clear queued nudges for a persona
```

30+ commands total. Install: `pip install -e smithy/`

## Bellows

A FastAPI dashboard for managing Forge projects from a browser. Morning briefings, decision queues, initiative board, activity sparklines, direct commands.

```
cd bellows && uv run uvicorn app:app --port 8080
```

## Steering UIs

Three standalone FastAPI apps for directing Forge — each a different steering metaphor. All read/write `state.json` directly; Forge picks up changes on the next heat. See [STEERING.md](STEERING.md) for full documentation.

```bash
# Start all 3 (each in its own terminal or tmux pane):
cd ui-priority-poker   && uvicorn app:app --port 8001
cd ui-intent-editor    && uvicorn app:app --port 8003
cd ui-timeline         && uvicorn app:app --port 8004
```

| UI | Port | What it does |
|----|------|-------------|
| **Priority Poker** | 8001 | Drag-to-reorder initiative cards. Rank determines what Forge works on next. Weight badges show budget allocation. Proposed initiatives appear in a separate section for approval/rejection. |
| **Intent Editor** | 8003 | Write natural-language outcomes. The system decomposes them into themes and initiatives. Select which to create, apply to state. History of past intents preserved. |
| **Timeline View** | 8004 | Gantt-style bars for each initiative. Drag endpoints to allocate budget across heats. Overlap detection shows parallel work. Range slider for viewport control. |

### How they connect

Each UI sets `FORGE_PROJECT_DIR` to locate the project's `state.json`. Default: the parent of the UI directory.

```
state.json ←→ Steering UIs (read/write initiatives, themes)
     ↓
  Forge (reads on next heat via smithy queue-pop)
```

All UIs include:
- **SSE live updates** (`/events`) — pages refresh when `state.json` changes
- **JSON API** (`/api/state`) — structured data for programmatic access
- **Refresh button** — manual reload in the header
- **Cross-UI nav bar** — links to all 3 UIs + Bellows, with active page highlighted

### Cross-UI navigation

The nav bar uses environment variables for URLs (useful when running on non-default ports):

```bash
export URL_POKER=http://localhost:8001
export URL_INTENT=http://localhost:8003
export URL_TIMELINE=http://localhost:8004
export URL_BELLOWS=http://localhost:8080
```

### Tests

Tests across all 3 UIs in `tests/test_steering_uis.py`:

```bash
python3 -m pytest tests/test_steering_uis.py -v
```

## Personas (Agent Teams)

Three personas coordinated via Claude Code Agent Teams — no dispatch files, no polling:

| Persona | Role |
|---------|------|
| **Anvil** | Your interface. Explains state, brainstorms strategy, sets direction. Spawns Marshal and Forge as teammates. |
| **Marshal** | The allocator. Computes priorities, orders the task queue, assigns work to Forge. |
| **Forge** | The autonomous worker. Pops tasks from the queue, runs heats, commits code, writes logs. |

Anvil spawns Marshal and Forge as Agent Teams teammates. Marshal uses `smithy set-next-tasks` to fill the queue. Forge uses `smithy queue-pop` to claim work. When a persona is mid-heat, nudges queue to `.smithy-nudge-queue/` and drain on next idle.

## Getting Started

```bash
# From the Smithy repo:
pip install -e smithy/
smithy init my-project --target ~/projects/my-project --with-personas

# Seed from a template shape (skip if you want a blank scaffold):
smithy init --list-templates           # see available shapes
smithy init my-project --target ~/projects/my-project --with-personas \
    --template cli                     # lib | cli | web | data-pipe | mobile | research

# Describe your project (templates pre-fill intent bullets + themes/initiatives):
vim ~/projects/my-project/identity.md

# Start all personas in tmux:
cd ~/projects/my-project
smithy start-all

# Or start manually:
cd ~/projects/my-project/personas/anvil
claude
> Start
```

`smithy start-all` creates a `smithy2` tmux session with anvil, forge, and marshal windows, each running Claude Code. Tell Anvil "Start" and it spawns the other two as teammates.

## Intent Templates

`smithy init --template=<shape>` pre-fills `identity.md` and `state.json` with sensible starting themes + initiatives for 6 common project shapes. Each template encodes the highest-risk failure mode for that shape as theme 1 (auth for web, schema for pipelines, offline for mobile).

| Template | For | Top theme |
|----------|-----|-----------|
| `lib` | Library / SDK | API Surface |
| `cli` | CLI tool | Command UX |
| `web` | Web app (product) | Golden-path flow |
| `data-pipe` | Data pipeline | Ingest & Schema |
| `mobile` | Mobile app | Offline & Sync |
| `research` | Exploratory research | Core Questions |

See `research/intent-template-library.md` for intent bullets + value-thesis per shape. Omit `--template` for a blank scaffold (backwards-compatible).

## Steering Attribution

Every human steering event (Poker priority flip, Bellows pin/reorder, Timeline tweak) writes a row to a per-project `steering.log` with `timestamp · heat · actor · task_id · field · before→after · source`. Three surfaces consume it:

- **Timeline UI** renders markers on the heat lane — hover for the attribution row
- **`GET /api/project/<name>/steering-log`** on Bellows returns rows filtered by `task_id` / `actor` / `since`
- **`smithy steering-retro --since=7d`** emits a weekly markdown digest: pins made, tasks shipped post-pin, avg pin→ship lag in heats, pure-allocator heats, by-actor breakdown

Pass `X-Actor: <name>` on any Bellows/Poker mutation request to override the default UI actor (useful for scripted or multi-agent pins).

## Built With The Smithy

The Smithy dogfoods itself. Over 700 heats, it built:

- **The Smithy protocol** — the system you're reading about
- **AI Tutor** — 5 subjects (Python, Math, English, Logic, Creative Writing), user sessions, PWA offline, SM-2 spaced repetition, teach-it-back, 111 tests
- **Bellows** — project dashboard with initiative board, live run indicator, stage-colored activity feeds, segmented budget bars, tap-to-decide

## Design Principles

- **Prose is the orchestrator.** CLAUDE.md + protocol files. No framework.
- **Flat files.** state.json, worklog.tsv, markdown. Inspect with `cat`.
- **Git is the substrate.** Every heat commits. The record is sacred.
- **Budget-bounded.** Never exceeds allocated heats. Say "Run N" to extend.
- **Self-directed.** Generates its own tasks when the queue runs dry.
