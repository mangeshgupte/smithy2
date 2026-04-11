# Forge -> Marshal Communication

Forge writes here after each heat. Marshal reads this to re-prioritize.

## Format

```
## YYYY-MM-DD HH:MM — Heat N Complete

- **Stage**: <stage>
- **Task**: <task_id> — <description>
- **Outcome**: complete|partial|blocked
- **Value**: <0.0-1.0>
- **Notes**: <what happened, what was learned>
```

Marshal: read this file, re-prioritize next_tasks in state.json, then clear entries you've processed.
