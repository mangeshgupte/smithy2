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

## 2026-04-11 12:10 — HOOK_DONE Heat 672

- **Task**: t-254 — smithy list-tasks command
- **Stage**: implementation
- **Outcome**: complete
- **Value**: 0.8
- **Notes**: Implemented list-tasks with --status/--stage/--initiative/--limit filters. Sorts by priority then ID. Resolves initiative titles from initiatives list. Tested all filter combos.

## 2026-04-11 12:21 — HOOK_DONE Heat 673

- **Task**: t-258 — Marshal hook mechanism
- **Stage**: implementation
- **Outcome**: complete
- **Value**: 0.8
- **Notes**: Added write/read/delete_marshal_hook to state.py, hook-marshal/check-marshal-hook/unhook-marshal CLI commands. .marshal-hook.json in .gitignore. All tested.

## 2026-04-11 12:27 — HOOK_DONE Heat 674

- **Task**: t-255 — smithy set-priority command
- **Stage**: implementation
- **Outcome**: complete
- **Value**: 0.8
- **Notes**: Implemented set-priority with validation (task exists, priority 0-3). Returns updated task + old_priority.

## 2026-04-11 12:46 — HOOK_DONE Heat 675

- **Task**: t-256 — smithy set-next-tasks command
- **Stage**: implementation
- **Outcome**: complete
- **Value**: 0.8
- **Notes**: Accepts variable task IDs, validates all exist and are pending, writes ordered list to state.json. Per-ID error details on failure.

## 2026-04-11 12:58 — HOOK_DONE Heat 676

- **Task**: t-262 — Unified task queue
- **Stage**: implementation
- **Outcome**: partial
- **Value**: 0.7
- **Notes**: Implemented queue/queue-push/queue-pop/queue-clear commands. Old hook commands still present for backward compat. Remaining: remove old hooks from state.py/cli.py, update end-heat/patrol, update protocol/loop.md and persona CLAUDE.md files.

## 2026-04-11 13:10 — HOOK_DONE Heat 677

- **Task**: t-259 — Marshal always-on loop
- **Stage**: editing
- **Outcome**: complete
- **Value**: 0.8
- **Notes**: Rewrote Marshal CLAUDE.md for always-on model with 3-step loop, queue-based commands, priority rules, startup sequence. ini-015 (Marshal agent) tasks complete.
