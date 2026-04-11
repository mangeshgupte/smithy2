# Dispatch: Forge -> Marshal

Forge writes HOOK_DONE here after completing hooked work. Marshal reads and writes the next hook.

## Format

```
## YYYY-MM-DD HH:MM — HOOK_DONE Heat N

- **Task**: <task_id> — <description>
- **Stage**: <stage>
- **Outcome**: complete|partial|blocked
- **Value**: <0.0-1.0>
- **Notes**: <what happened, what was learned>
```

Marshal: on seeing HOOK_DONE, re-read all steering signals, recompute ordering, write next hook. Clear processed entries.
