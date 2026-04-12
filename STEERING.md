# Steering UIs

Three ways to direct Forge without micromanaging. Each UI is a different mental model for the same goal: shaping what autonomous work gets done and in what order.

You don't tell Forge which file to edit. You tell it what matters — by ranking, describing, or scheduling. It figures out the rest.

## Philosophy

Traditional project management is imperative: assign tasks, track hours, review PRs. Forge's steering is declarative: express priorities, describe outcomes. The system translates your intent into executable work.

**Ranking over constraints.** We previously shipped a Constraints UI (hard caps/floors per stage). It was retired 2026-04-12 — hard constraints are brittle, over-specify, and hide the preference signal that ranking already carries. If research matters less than testing, the answer is to rank testing-tasks above research-tasks, not to cap research. See `research/steering-patterns-retrospective.md` §7.

Each remaining UI targets a different cognitive style:

- **Poker** — "These three things matter most. Do them in this order."
- **Intent** — "I want user auth and data export. Break that down and make it happen."
- **Timeline** — "Auth starts at heat 50 and finishes by heat 70. Export comes after."

Use one. Use all three. They write to the same `state.json` — changes from any UI are visible to all others and picked up by Forge on the next heat.

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Poker     │  │   Intent    │  │  Timeline   │
│  :8001      │  │   :8003     │  │   :8004     │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┴────────────────┘
                        │
                state.json (read/write)
                        │
           ┌────────────┴────────────┐
           │         Forge           │
           │  (reads on next heat)   │
           └─────────────────────────┘
```

Each UI is a standalone FastAPI app. No shared database, no message queue — just a JSON file on disk. This means:

- **Zero coordination overhead.** Any UI can read or write at any time.
- **Inspectable state.** `cat state.json | jq .initiatives` shows exactly what the UIs see.
- **SSE live updates.** Each UI watches `state.json` for modifications and pushes `state-changed` events to the browser via `/events`.
- **JSON API.** Each UI exposes `GET /api/state` for programmatic access.

## Quick Start

```bash
# Install dependencies (once)
pip install fastapi uvicorn jinja2

# Start all 3 UIs (each in a separate terminal):
cd ui-priority-poker && uvicorn app:app --port 8001 &
cd ui-intent-editor  && uvicorn app:app --port 8003 &
cd ui-timeline       && uvicorn app:app --port 8004 &

# Or use smithy start-all to launch everything in tmux
smithy start-all
```

Set `FORGE_PROJECT_DIR` to point each UI at your project:

```bash
export FORGE_PROJECT_DIR=~/projects/my-project
```

---

## Priority Poker

**Port:** 8001 | **Metaphor:** Drag cards to rank. Rank IS steering.

The simplest steering interface. Initiatives appear as draggable cards. Drag them up to increase priority, down to decrease it. Forge works top-down through the ranked list.

### Features

- **Drag-and-drop reordering** with smooth animations, rotation on drag, and visual feedback
- **Weight badges** showing budget allocation (weight 1 = primary, weight 2 = secondary)
- **Status filtering** — approved/active initiatives in the main list, proposed ones in a separate section for approval
- **Approve/reject** proposed initiatives with single-click buttons
- **Forge activity indicator** showing current heat and task when Forge is running
- **Mobile-responsive** with touch support for drag operations

### state.json fields

| Field | Read/Write | Purpose |
|-------|-----------|---------|
| `initiatives[].rank` | Write | Updated on drag reorder |
| `initiatives[].status` | Read/Write | Filters display; updated on approve/reject |
| `themes[].name` | Read | Displays theme label on cards |
| `queue[]` | Read | Counts pending/complete tasks per initiative |

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Render poker board |
| POST | `/reorder` | Persist new rank order (JSON: `{order: [id, ...]}`) |
| POST | `/approve/{id}` | Move initiative to approved status |
| POST | `/reject/{id}` | Move initiative to rejected status |
| GET | `/api/state` | JSON: ranked initiatives with task counts |
| GET | `/events` | SSE stream for live updates |

---

## Intent Editor

**Port:** 8003 | **Metaphor:** Write outcomes, system creates tasks.

The most high-level steering interface. Write what you want in natural language — the system decomposes it into themes and initiatives, then creates them in `state.json`. Think of it as "commit message for the future."

### Features

- **Natural-language input** — write outcomes as bullet points with bold theme headers and sub-bullet initiatives
- **Automatic decomposition** — parses markdown bullets into a tree of themes and initiatives
- **Selective creation** — checkboxes let you pick which decomposed items to create
- **Template buttons** for common intent patterns
- **Inline editing** of existing theme and initiative names
- **Delete with cascade** — removing a theme deletes all its initiatives
- **Intent history** — past intents preserved and reloadable
- **Identity.md sync** — applied intents update the Commander's Intent section

### Input format

```markdown
- **Auth System**
  - User registration and login
  - OAuth integration
- **Data Pipeline**
  - CSV import
  - Real-time streaming
```

Bold bullets become themes. Indented sub-bullets become initiatives (status: proposed).

### state.json fields

| Field | Read/Write | Purpose |
|-------|-----------|---------|
| `themes[]` | Read/Write | Created from decomposition, editable, deletable |
| `initiatives[]` | Read/Write | Created as proposed, editable, deletable (cascade on theme delete) |

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Render editor with current intent and decomposition |
| POST | `/apply` | Create selected themes/initiatives from decomposition |
| POST | `/edit-theme/{id}` | Rename a theme (JSON: `{name}`) |
| POST | `/edit-initiative/{id}` | Rename an initiative (JSON: `{title}`) |
| POST | `/delete-theme/{id}` | Delete theme + cascade to initiatives |
| POST | `/delete-initiative/{id}` | Delete single initiative |
| GET | `/api/state` | JSON: themes, initiatives, current intent |
| GET | `/events` | SSE stream for live updates |

---

## Timeline View

**Port:** 8004 | **Metaphor:** Drag bar endpoints to allocate budget across time.

A Gantt-style view where each initiative is a horizontal bar. Drag the start or end to schedule when work happens. See overlaps (parallel work) and gaps (cool-down periods) at a glance.

### Features

- **Draggable bar endpoints** — adjust `planned_start` and `planned_end` per initiative
- **Overlap detection** — overlapping bars highlighted with heat count
- **Budget info** — remaining heats displayed in the header
- **Range slider** — scroll through the full project timeline; viewport auto-clamps to 20-300 heats
- **Status filtering** — only approved/active initiatives shown (proposed/rejected hidden)
- **Task counts** — pending and complete tasks per initiative
- **Batch updates** — multiple initiatives updated in a single POST

### state.json fields

| Field | Read/Write | Purpose |
|-------|-----------|---------|
| `initiatives[].planned_start` | Read/Write | Bar start position (heat number) |
| `initiatives[].planned_end` | Read/Write | Bar end position (heat number) |
| `initiatives[].status` | Read | Filters to approved/active only |
| `budget.used` | Read | Current progress marker |
| `budget.total_heats` | Read | Timeline bounds |
| `queue[]` | Read | Task counts per initiative |

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Render timeline (optional `?start=N&end=M` for viewport) |
| POST | `/update` | Persist bar positions (JSON: `{updates: [{id, start, end}, ...]}`) |
| GET | `/api/state` | JSON: initiative progress data |
| GET | `/events` | SSE stream for live updates |

---

## Cross-UI Navigation

All 4 UIs share a nav bar at the top of the page with links to every other UI plus Bellows. The current page is highlighted.

URLs are configurable via environment variables:

| Variable | Default | UI |
|----------|---------|-----|
| `URL_POKER` | `http://localhost:8001` | Priority Poker |
| `URL_INTENT` | `http://localhost:8003` | Intent Editor |
| `URL_TIMELINE` | `http://localhost:8004` | Timeline View |
| `URL_BELLOWS` | `http://localhost:8080` | Bellows dashboard |

Bellows project pages also include steering links in their tab navigation.

## Testing

Tests across the 3 UIs:

```bash
python3 -m pytest tests/test_steering_uis.py -v

# By UI:
python3 -m pytest tests/test_steering_uis.py::TestPriorityPoker   # 15 tests
python3 -m pytest tests/test_steering_uis.py::TestTimeline        # 19 tests
python3 -m pytest tests/test_steering_uis.py::TestIntentEditor    # 16 tests
```

Tests use Starlette's `TestClient` with temporary `state.json` fixtures. No running server required.
