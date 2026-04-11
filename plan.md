# Plan: Intent Hierarchy

*2026-04-10 — Anvil*

Add three-level steering to The Smithy: Themes (strategic direction), Initiatives (scoped efforts needing approval), Tasks (atomic work). The human steers by reordering themes and approving/rejecting initiatives. Forge only works on tasks from approved initiatives or standalone tasks. Bellows gets a board view.

## Scope
- **In**: state.json schema, CLI commands, allocator gating, Bellows board, protocol updates
- **Out**: Migrating existing 150+ tasks into initiatives, appetite mechanics, PRD templates

## Decisions
- Emergency injects (standalone tasks, no initiative_id) bypass all gating — priority 0 always eligible
- Initiative hitting budget cap warns in outbox.md, doesn't auto-pause
- Completing an initiative does NOT auto-complete its remaining tasks
- Dispatch file stays as Anvil's decision journal, not an operational input for Forge

## Data Model

### state.json additions

```json
{
  "themes": [
    {"id": "th-001", "name": "Infrastructure quality", "rank": 1, "status": "active"},
    {"id": "th-002", "name": "Tutor UX", "rank": 2, "status": "active"}
  ],
  "initiatives": [
    {
      "id": "ini-001",
      "theme_id": "th-001",
      "title": "Task context field",
      "description": "Add optional context field to tasks so they're self-contained.",
      "status": "proposed|approved|active|done|rejected",
      "budget_cap": null,
      "heats_used": 0
    }
  ]
}
```

### Task field addition

```json
{
  "id": "t-145",
  "initiative_id": "ini-001",
  ...existing fields...
}
```

- `initiative_id` absent or null = standalone task, always eligible
- Task with `initiative_id` only eligible if initiative status is "approved" or "active"

## CLI Commands

### Themes
- `smithy add-theme <name>` — appends with next rank
- `smithy reorder-themes <id> <new_rank>` — shifts others
- `smithy pause-theme <id>` / `smithy activate-theme <id>`
- `smithy list-themes` — all themes with rank and status

### Initiatives
- `smithy propose <theme_id> <title> <description>` — status="proposed", optional `--budget-cap N`
- `smithy approve <id>` — status="approved"
- `smithy reject <id>` — status="rejected"
- `smithy complete-initiative <id>` — status="done"
- `smithy list-initiatives` — grouped by status, optional `--theme <id>` filter

### Task updates
- `smithy add-task` gets `--initiative <id>` (validates initiative exists and is approved/active)
- `smithy pick-task` gates: only tasks where initiative_id is null OR initiative is approved/active. First pick from an initiative sets it to "active".

## Allocator Changes

- Queued-task bonus (+0.07/task) only counts eligible tasks (approved/active initiative or standalone)
- Theme rank bonus: tasks from rank-1 theme get 1.5x on their stage's queued-task bonus

## Protocol Changes

### loop.md Step 4
- Document pick-task initiative gating
- "If no ready tasks and proposed initiatives exist, flag in outbox.md"

### Anvil CLAUDE.md
- Replace dispatch workflow with initiative workflow
- Anvil proposes initiatives, human approves in Bellows or CLI

## Bellows UI

### /project/{name}/board route
- Kanban columns: Proposed | Approved | Active | Done
- Initiative cards: title, theme tag, tasks (done/total), heats_used/budget_cap
- Approve/reject buttons on proposed cards
- Click to expand and see tasks

### API endpoints
- `POST /project/{name}/initiative/{id}/approve`
- `POST /project/{name}/initiative/{id}/reject`

### forge_reader.py
- Extract initiatives, group tasks by initiative_id
- Compute initiative progress (tasks done / total)

### home.html
- Proposed-initiative count badge on project cards

## Task Breakdown (15 heats)

1. Data model + validation (2 heats)
2. Theme CLI commands (1 heat)
3. Initiative CLI commands (2 heats)
4. Task CLI updates: --initiative, pick-task gating (2 heats)
5. Allocator: gate bonus, theme rank bonus (1 heat)
6. Protocol: loop.md, anvil CLAUDE.md (1 heat)
7. Bellows forge_reader: initiatives + task grouping (1 heat)
8. Bellows board route + template (2 heats)
9. Bellows endpoints + home badge (1 heat)
10. Testing: CLI, Bellows, end-to-end (2 heats)
