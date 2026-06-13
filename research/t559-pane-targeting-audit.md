# t-559 — pane_title-keyed pane targeting audit (follow-up to t-554)

**Heat 1358, forge-temper, 2026-06-12.**

## Premise

The Claude Code TUI continuously overwrites a pane's `#{pane_title}` with
its status line. So any tooling that *discovers/selects a pane by title*
silently never hits — the latent bug t-554 fixed in `smithy`'s
`_resolve_pane` (now keys on `#{pane_start_path}` first, title secondary).
t-559 sweeps the rest of the shell tooling for the same pattern.

## Method

`grep -rn 'pane_title|list-panes|list-windows|select-pane|#{pane_'` across
`scripts/` and repo-wide for `pane_title`.

## Findings — shell tooling is CLEAN (no title-keyed pane matching)

| Script | Pane/window discovery | Verdict |
|---|---|---|
| `nudge.sh` | `#{pane_start_path}` (+ current_path fallback) | ✅ t-554-correct |
| `restart-ui.sh` | `#{pane_start_path}` (+ current_path fallback) | ✅ t-554-correct |
| `stop-smithy.sh` | `#{window_name}` (grep -qx) + `#{pane_id}` | ✅ window names stable |
| `autopilot-tick.sh` | `#{window_name}` | ✅ stable |
| `comms-tick.sh` | `#{window_name}` | ✅ stable |
| `start-smithy.sh` | `pane_id` captured at creation (`-P -F '#{pane_id}'`); sets titles with `select-pane -T` (stamping, not matching) | ✅ no discovery-by-title |

- **No shell script reads `#{pane_title}`.** Repo-wide, the only
  `pane_title` reference is `smithy/smithy/cli.py:3303` — the `_resolve_pane`
  function, where t-554 already made title a *secondary* key. That is the
  canonical correct implementation and out of scope for a shell guard.
- **Window names are stable.** The `#{window_name}` matchers are safe because
  windows are created with explicit `-n` names (`new-session -n main`,
  `new-window -n "$FORGE_UI_WINDOW"`, …), which disables tmux
  `automatic-rename` for those windows — unlike pane titles, the TUI does not
  overwrite them.
- `forge-status.sh` (named speculatively in the ticket) does not exist.

## Deliverable — regression guard

`tests/test_t559_pane_title_guard.py`: parametrized over `scripts/*.sh`,
fails if any script references `pane_title` outside a comment. Locks in the
clean state so new shell tooling can't reintroduce title-keyed matching;
points violators at the correct patterns (pane_start_path / stable
window_name / creation-time pane_id / `smithy nudge`).

## No code changes needed

The audit found nothing to fix — the tooling already follows the
t-554-correct pattern. The value of this heat is the guard that keeps it
that way.
