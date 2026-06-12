# Status

_Last updated: 2026-06-12 (rig restarted by Mangesh)_

## Where this is right now

**The Forge rig is up and fully operational** after ~8 weeks idle (last activity
2026-04-19). Mangesh started it via `scripts/start-smithy.sh` from his own
terminal at 16:28; tmux session `forge` with 3 windows:

- **main** — Anvil, Marshal, Assembly + forge-quench / forge-temper / forge-anneal,
  all booted; Start cascade fired automatically.
- **ui** — bellows :8080, poker :8001, intent :8003, timeline :8004 — all ports up.
- **comms** — pane up, cron wake installed (`*/5 * * * * scripts/comms-tick.sh`).

Note for future restarts: launching the script from a non-TCC-permitted process
(e.g. a Claude Bash tool) fails at the crontab step with "Operation not
permitted", and `set -e` then skips the Start cascade. Start it from a real
terminal, or send "Start" to the main panes manually afterward.

## Open items

- [ ] At shutdown in April, the last three submissions (t-536, t-487, t-537) were
      rejected by the gate for test failures; 1 task was stuck `in_progress`
      (patrol --fix reaps on Start). 26 tasks pending, budget 955/1543 heats used.
- [ ] Uncommitted working-tree state from April still present (state.json,
      worklog.tsv, persona memory files, etc.) — Assembly/agents to reconcile.

## Earlier today: /doctor permission fix

Fixed `.claude/settings.json` — invalid skipped rules `"Read **"/"Write **"/"Edit **"`
replaced with valid bare `"Read"/"Write"/"Edit"` (blanket allow, original intent).
Validated with jq. Fresh rig sessions pick this up automatically. Not yet committed.
