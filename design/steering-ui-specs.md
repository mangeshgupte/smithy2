# Steering UI Specs

Four standalone FastAPI apps, each a different steering metaphor. All read/write state.json.

---

## UI A: Priority Poker

**Metaphor**: Drag-to-rank card stack. Ranking IS steering.

### Layout
```
┌─────────────────────────────────┐
│  Priority Poker — the-smithy    │
├─────────────────────────────────┤
│                                 │
│  ┌─── 1 ──────────────────────┐ │
│  │ 🟢 Logic Subject Expansion │ │
│  │ th-001 · 3 heats · 0 tasks │ │
│  └────────────────────────────┘ │
│                                 │
│  ┌─── 2 ──────────────────────┐ │
│  │ 🔵 Tutor Auth              │ │
│  │ th-001 · 0 heats · 2 tasks │ │
│  └────────────────────────────┘ │
│                                 │
│  ┌─── 3 ──────────────────────┐ │
│  │ 🟡 PWA Offline             │ │  
│  │ th-002 · 5 heats · done    │ │
│  └────────────────────────────┘ │
│                                 │
│  [Kill zone — drag here to      │
│   reject an initiative]         │
│                                 │
└─────────────────────────────────┘
```

### Tech
- **Backend**: FastAPI, reads state.json, writes initiative ranks on reorder
- **Frontend**: HTML + vanilla JS drag-and-drop (HTML5 Drag API or sortable.js CDN)
- **State**: Each initiative gets a `rank` field. Rank 1 = top priority
- **Allocation weight**: Rank 1 → 3× queued-task-bonus, Rank 2 → 2×, rest → 1×

### Data flow
1. Page loads → reads state.json → renders cards sorted by rank
2. Human drags card → JS sends POST /reorder with new order
3. Backend writes updated ranks to state.json
4. Forge's allocator reads ranks next heat → adjusts scoring

### Files
- `ui-priority-poker/app.py` — 2 routes: GET / (render), POST /reorder (save)
- `ui-priority-poker/templates/index.html` — single page with drag-and-drop
- `ui-priority-poker/static/style.css` — dark theme matching Bellows

---

## UI B: Constraint Board

**Metaphor**: ATC-style boundaries. Direct through constraints, not commands.

### Layout
```
┌─────────────────────────────────┐
│  Constraint Board — the-smithy  │
├─────────────────────────────────┤
│                                 │
│  Active Constraints:            │
│                                 │
│  ┌────────────────────────────┐ │
│  │ ⏱ Budget: research ≤ 5h   │ │
│  │ ■■■■░ 4/5 heats           │ │
│  └────────────────────────────┘ │
│                                 │
│  ┌────────────────────────────┐ │
│  │ 📊 Floor: testing ≥ 15%   │ │
│  │ Currently: 18% ✓          │ │
│  └────────────────────────────┘ │
│                                 │
│  ┌────────────────────────────┐ │
│  │ 🚫 Exclude: don't touch   │ │
│  │ tutor/ this sprint         │ │
│  └────────────────────────────┘ │
│                                 │
│  [+ Add constraint]            │
│                                 │
│  Violations: none ✓            │
└─────────────────────────────────┘
```

### Constraint Types
1. **Budget cap**: "Stage X ≤ N heats" or "Initiative Y ≤ N heats"
2. **Floor**: "Stage X ≥ N% of total" 
3. **Exclude**: "Don't work on <path/subject/stage>"
4. **Deadline**: "Initiative X done by heat N"

### Tech
- **Backend**: FastAPI, stores constraints in state.json `constraints` list
- **Frontend**: HTML forms for adding constraints, cards for active ones
- **Enforcement**: Forge reads constraints in Step 1, skips tasks that would violate

### Files
- `ui-constraint-board/app.py` — CRUD routes for constraints
- `ui-constraint-board/templates/index.html`
- `ui-constraint-board/static/style.css`

---

## UI C: Timeline View

**Metaphor**: Gantt-style interactive timeline. Drag bar endpoints to allocate.

### Layout
```
┌───────────────────────────────────────────┐
│  Timeline — the-smithy                     │
├────┬──────────────────────────────────────┤
│    │ h600    h610    h620    h630   h640  │
│    │  |       |       |       |      |   │
│ A  │ ■■■■■■■■■■■░░░░░░░░░░            │
│ B  │          ■■■■■■■■■■■■■■           │
│ C  │                   ■■■■■■■■■■■■■■  │
│    │  |       |       |       |      |   │
├────┴──────────────────────────────────────┤
│ Budget: 40 heats remaining                │
│ A: 11h planned | B: 14h planned | C: 14h │
└───────────────────────────────────────────┘
```

### Tech
- **Backend**: FastAPI, stores `planned_start` and `planned_end` on initiatives
- **Frontend**: HTML + CSS for bars, JS for drag endpoints
- **Visual**: Each initiative = horizontal bar. Width = budget allocation. Position = sequencing.

### Files
- `ui-timeline/app.py`
- `ui-timeline/templates/index.html`
- `ui-timeline/static/style.css`

---

## UI D: Intent Editor

**Metaphor**: Natural language → structured decomposition. Think in outcomes.

### Layout
```
┌─────────────────────────────────┐
│  Intent Editor — the-smithy     │
├─────────────────────────────────┤
│                                 │
│  Your Intent:                   │
│  ┌────────────────────────────┐ │
│  │ Build a tutor app with 5   │ │
│  │ subjects. Each subject has │ │
│  │ Socratic lessons, cards,   │ │
│  │ and spaced review. Ship    │ │
│  │ a PWA that works offline.  │ │
│  └────────────────────────────┘ │
│  [Decompose]                    │
│                                 │
│  Decomposition:                 │
│  ┌────────────────────────────┐ │
│  │ Theme: Tutor Content       │ │
│  │  └ Init: 5th subject       │ │
│  │  └ Init: Exercise expansion│ │
│  │ Theme: Tutor Infrastructure│ │
│  │  └ Init: PWA offline       │ │
│  │  └ Init: User sessions     │ │
│  └────────────────────────────┘ │
│  [Apply to state.json]          │
│                                 │
└─────────────────────────────────┘
```

### Tech
- **Backend**: FastAPI, POST /decompose calls Claude API to break intent into themes+initiatives
- **Frontend**: Textarea for intent, tree view for decomposition, edit/delete buttons
- **State**: On "Apply", creates themes+initiatives+tasks in state.json

### Files
- `ui-intent-editor/app.py`
- `ui-intent-editor/templates/index.html`
- `ui-intent-editor/static/style.css`

---

## Shared Design Principles

1. **Dark theme** matching Bellows (#0d1117 bg, same palette)
2. **Standalone apps** — each runs on its own port, reads same state.json
3. **No Forge changes** — all UIs write to state.json, Forge reads it
4. **< 200 lines per UI** — these are prototypes, not products
5. **Vanilla JS** — no frameworks, just HTML5 APIs
