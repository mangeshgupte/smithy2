# Dispatch: Marshal -> Forge

Marshal writes rationale and notes here. Documentation only — operational dispatch is via `.forge-hook.json`.

## Format

```
## YYYY-MM-DD HH:MM — Hook Set

### Task
<task_id> [<stage>] — <description>

### Rationale
<Why this task is next. What signals drove the decision.>

### Queue (next 5)
1. <task_id> — <why>
2. <task_id> — <why>
...
```

Forge: this is informational. Your work comes from `smithy check-hook`, not this file.
