# Gas Town Extension Points

*Heat 481 research | 2026-04-10*

## Location

Gas Town codebase is at `/Users/mangesh/vibes/understand/gastown/repo/` (Go + TOML).

## Polecat Type System

Polecats are NOT monolithic. Three independent layers:
- **Identity** (permanent): Agent bead in Dolt, CV chain (work history), mailbox
- **Sandbox** (persistent across assignments): Git worktree at `~/gt/<rig>/polecats/<name>/`
- **Session** (ephemeral): Claude context window — dies via handoff, crash, compaction (this is normal)

**Four lifecycle states**: Working, Idle, Stuck, Zombie (discovered by polling, not tracked by events).

## Rig Type System

Rigs are projects. Each rig has standard agent directories: `polecats/`, `crew/`, `refinery/`, `witness/`, `mayor/`. No plugin-based extensibility — agent types are preset-defined (Claude, Gemini, Codex, Cursor, etc.) via a central registry in `internal/config/agents.go`.

## Plugin/Hook System

- **Hooks**: Lifecycle automation installed in agent config dir (`.claude/settings.json`). SessionStart, PreToolUse, Stop. Static, not runtime-extensible.
- **Plugins**: TOML-defined automation dispatched by Deacon Dog. Gate types: cooldown, cron, condition, event, manual. Execute via dogs (infrastructure helpers), NOT polecats.
- **Formulas**: TOML-defined step sequences (workflow, convoy, expansion, aspect). Embedded in gt binary. Topological sort for dependencies.

## Key Insight for Smithy

Gas Town does NOT use Go interfaces for type extensibility. "Agent type" is an enum in a central registry. Adding a new agent = one registry entry + hook template. There's no way to "register" a Forge-polecat as a custom type without modifying Gas Town's Go code.

**However**: the polecat lifecycle (hook work → execute → gt done) maps directly to Forge's heat loop (start-heat → work → end-heat). The main gap is that Gas Town uses Dolt for state and Forge uses flat JSON files.
