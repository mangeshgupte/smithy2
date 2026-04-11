# Bellows — Forge Project Dashboard

A web app for managing multiple Forge projects from your browser. See all projects at a glance, review decisions, check morning briefings, and send direction to Forge. The bellows feeds air to the forge.

## Quick Start

```bash
cd bellows
uv run uvicorn app:app --port 8080

# Open http://localhost:8080
```

Set `FORGE_PROJECTS_DIR` to point to your projects directory (defaults to `~/vibes`):
```bash
FORGE_PROJECTS_DIR=~/my-projects uv run uvicorn app:app --port 8080
```

## Screens

| Screen | URL | Purpose |
|--------|-----|---------|
| Home | `/` | Project cards sorted by signal (red → yellow → green) |
| Morning Briefing | `/briefing` | Catch-up view: needs-you, progress, notable |
| Inbox | `/inbox` | Cross-project decision queue |
| Project Detail | `/project/<name>` | Stage bars, budget, activity feed |
| Decide | `/project/<name>/decide` | Pending decision cards with approve/defer/reject |
| Direct | `/project/<name>/direct` | Commander's intent, feedback, free-form messaging |

### Home

Grid of project cards showing:
- Stoplight signal (green/yellow/red) based on recent heat signals
- Overall progress percentage
- Stage progress bars (color-coded per stage)
- Last active timestamp
- Bottleneck indicator (stage furthest behind)

### Morning Briefing

Executive summary for daily catch-up:
- **Needs attention**: projects with yellow/red signals or pending decisions
- **Progress snapshot**: heats run, progress deltas
- **Notable activity**: significant events across projects

### Inbox

Cross-project decision queue sorted by priority. Shows all pending decisions across all Forge projects in one place.

### Project Detail (Activity tab)

- **Stage bars**: Color-coded (purple=research, blue=planning, green=impl, yellow=testing, orange=editing, red=marketing)
- **Budget**: Segmented bar showing heat breakdown by stage with legend
- **Activity feed**: Day-grouped heats with stage-colored left borders, signal dots, expandable details

### Decide tab

Pending decisions with priority badges (critical/high/medium):
- Critical decisions pulse with animation
- Stage-colored badges
- Approve / Defer / Reject buttons with hover color feedback
- Optional custom context field
- Undo last decision

### Direct tab

- **Commander's intent**: Current project direction from identity.md
- **Feedback**: Write feedback that Forge reads on next run (writes to feedback.md)
- **Messages**: Free-form messaging to Forge (writes to inbox.md)

## API

- `GET /api/projects` — JSON array of all project data
- `GET /api/briefing` — morning briefing data

## How It Works

Bellows reads directly from Forge flat files — no database, no sync:
- `state.json` — budget, stages, queue, progress
- `worklog.tsv` — heat history for activity feed
- `feedback.md` — human feedback (Bellows writes, Forge reads)
- `inbox.md` — async messages (Bellows writes, Forge reads)
- `identity.md` — commander's intent display

## Design

- Dark theme (#0d1117 background)
- 6 stage colors (purple, blue, green, yellow, orange, red)
- Mobile-first responsive layout (max-width 600px)
- Bottom tab bar navigation
- 12 tests for forge_reader
