# Bellows — Forge Project Dashboard

A web app for managing multiple Forge projects from your browser. See all projects at a glance, review decisions, check morning briefings. The bellows feeds air to the forge.

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
| Project Detail | `/project/<name>` | Stage bars, activity feed, what's missing |
| Decide | `/project/<name>/decide` | Pending decision cards |
| Inbox | `/inbox` | Cross-project decision queue |

## API

- `GET /api/projects` — JSON array of all project data
- `GET /api/briefing` — morning briefing data

## Design

Follows Chisel's design spec (`design/2026-04-09-commissioner-app-design.md`):
- Lifecycle-adaptive cards (early/mid/mature)
- Stoplight signals (green/yellow/red)
- Dark theme, responsive layout
- Reads directly from Forge flat files (state.json, worklog.tsv, etc.)
