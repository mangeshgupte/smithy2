---
name: initiative-budget-cap-hand-edit
description: initiative budget_cap has no CLI setter — edit-initiative only covers parallelism/affinity/touches; hand-edit state.json
metadata:
  type: project
---

`smithy edit-initiative` (t-440) only supports `--parallelism`, `--affinity`, `--touches`. There is no CLI verb for `budget_cap` — raising an initiative's heat cap requires a hand edit of `state.json` (`.initiatives[].budget_cap`). Plain int, no cascade invariants, so hand-editing is safe — unlike rank/priority/status which need the CLI ([[feedback_prefer_cli_over_hand_edit]]).

**How to apply:** when Marshal reports an initiative over cap with dispatchable p0s, do a fast single read-modify-write of state.json (rig is live; minimize the race window), verify with jq, then nudge Marshal.
