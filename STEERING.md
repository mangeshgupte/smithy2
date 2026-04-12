# Steering UIs

Four ways to direct Forge without micromanaging. Each UI is a different mental model for the same goal: shaping what autonomous work gets done, in what order, under what constraints.

You don't tell Forge which file to edit. You tell it what matters — by ranking, bounding, describing, or scheduling. It figures out the rest.

## Philosophy

Traditional project management is imperative: assign tasks, track hours, review PRs. Forge's steering is declarative: express priorities, set constraints, describe outcomes. The system translates your intent into executable work.

Each UI targets a different cognitive style:

- **Poker** — "These three things matter most. Do them in this order."
- **Constraints** — "Don't spend more than 15 heats on research. Testing must get at least 20%."
- **Intent** — "I want user auth and data export. Break that down and make it happen."
- **Timeline** — "Auth starts at heat 50 and finishes by heat 70. Export comes after."

Use one. Use all four. They write to the same `state.json` — changes from any UI are visible to all others and picked up by Forge on the next heat.

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Poker     │  │ Constraints │  │   Intent    │  │  Timeline   │
│  :8081      │  │   :8082     │  │   :8083     │  │   :8084     │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
       └────────────────┴────────────────┴────────────────┘
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

# Start all 4 UIs (each in a separate terminal):
cd ui-priority-poker   && uvicorn app:app --port 8081 &
cd ui-constraint-board && uvicorn app:app --port 8082 &
cd ui-timeline         && uvicorn app:app --port 8083 &
cd ui-intent-editor    && uvicorn app:app --port 8084 &

# Or use smithy start-all to launch everything in tmux
smithy start-all
```

Set `FORGE_PROJECT_DIR` to point each UI at your project:

```bash
export FORGE_PROJECT_DIR=~/projects/my-project
```

---

## Priority Poker

**Port:** 8081 | **Metaphor:** Drag cards to rank. Rank IS steering.

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

## Constraint Board

**Port:** 8082 | **Metaphor:** Set boundaries, not commands. ATC-style guardrails.

Instead of telling Forge what to do, tell it what NOT to do. Set budget caps, stage floors, and exclusion rules. The board flags violations in real time — red banners when a constraint is breached, green when all are satisfied.

### Features

- **Three constraint types:** budget cap (max heats per stage), floor (minimum heats), exclusion (skip a stage entirely)
- **Real-time violation detection** with banner alerts
- **Click-to-edit** constraint values, descriptions, and stages inline
- **Toggle active/inactive** without deleting — paused constraints are dimmed
- **Smart suggestions** for uncovered stages
- **Quick templates** for common constraint patterns

### state.json fields

| Field | Read/Write | Purpose |
|-------|-----------|---------|
| `constraints[]` | Read/Write | Full CRUD — add, edit, remove, toggle |
| `stages{}` | Read | Current heat counts for violation checking |

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Render constraint board with violation status |
| POST | `/add` | Add a new constraint (form: type, stage, value, description) |
| POST | `/remove/{id}` | Delete a constraint |
| POST | `/toggle/{id}` | Toggle active/inactive |
| POST | `/edit/{id}` | Edit value, stage, or description (JSON) |
| GET | `/api/state` | JSON: constraints with violation status |
| GET | `/events` | SSE stream for live updates |

---

## Intent Editor

**Port:** 8084 | **Metaphor:** Write outcomes, system creates tasks.

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

**Port:** 8083 | **Metaphor:** Drag bar endpoints to allocate budget across time.

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
| `URL_CONSTRAINTS` | `http://localhost:8002` | Constraint Board |
| `URL_INTENT` | `http://localhost:8003` | Intent Editor |
| `URL_TIMELINE` | `http://localhost:8004` | Timeline View |
| `URL_BELLOWS` | `http://localhost:8000` | Bellows dashboard |

Bellows project pages also include steering links in their tab navigation.

## Testing

66 tests across all 4 UIs:

```bash
python3 -m pytest tests/test_steering_uis.py -v

# By UI:
python3 -m pytest tests/test_steering_uis.py::TestPriorityPoker     # 15 tests
python3 -m pytest tests/test_steering_uis.py::TestConstraintBoard    # 16 tests
python3 -m pytest tests/test_steering_uis.py::TestTimeline           # 19 tests
python3 -m pytest tests/test_steering_uis.py::TestIntentEditor       # 16 tests
```

Tests use Starlette's `TestClient` with temporary `state.json` fixtures. No running server required.
