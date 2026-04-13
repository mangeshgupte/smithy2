# scripts/

Reproducible session + workflow helpers for The Forge rig.

## tmux-layout.sh

Lays out a tmux session named `forge` with one pane per agent:
Anvil (left, full height), then Marshal / Assembly / Forges stacked in the
right column. Forge panes scale automatically from
`state.parallel.forges[]`.

```bash
scripts/tmux-layout.sh             # attach or create
scripts/tmux-layout.sh --force     # kill existing and recreate
scripts/tmux-layout.sh --dry-run   # print panes that would be created
```

Each pane starts in `<worktree>/personas/<role>/` so claude picks up the
role-specific `CLAUDE.md`, and so no agent other than Assembly is operating
on `main` directly (the worktree invariant). Override the launcher via
`FORGE_CLAUDE=""` to leave panes empty or `FORGE_CLAUDE=/path/to/claude`
to point at a specific binary. Override the session name via
`FORGE_SESSION`. The script reads `state.json` to pick up the current
Forge roster, so growing the rig (adding a new Forge to
`parallel.forges[]`) is a state edit + `--force` relaunch, not a script
edit.
