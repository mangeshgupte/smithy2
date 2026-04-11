# Marshal -> Forge Communication

Marshal writes prioritization rationale and notes here. Forge reads on next heat.

## Format

```
## YYYY-MM-DD HH:MM — Prioritization Update

### Next Tasks (in order)
1. <task_id> [<stage>] — <why this is next>
2. <task_id> [<stage>] — <why>

### Rationale
<Why this ordering. What signals drove the decision.>

### Notes
<Any context Forge should know — constraints changing, initiative status, etc.>
```

Forge: this is informational. The actual task order is in state.json next_tasks.
