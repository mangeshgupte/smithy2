---
name: phantom-heat-done-t519-leak
description: Phantom "HEAT_DONE forge-01 h1 (no task) nudge test" messages in Marshal's pane are the t-519 test-isolation leak, not a real forge
metadata:
  type: project
---

Periodic `HEAT_DONE 🟢 forge-01 h1 · (no task) · "nudge test"` messages arriving at Marshal's pane are NOT a stale agent or cron job. They are the t-519 test-isolation leak: smithy's test suite sends real tmux nudges to the live Marshal pane, with fixture defaults (forge-01, heat 1, summary "nudge test"). They fire every time a forge's witness gate runs the suite.

**Diagnosis path (2026-06-12):** checked crontab, launchd, repo greps — all clean; t-519's own task description named the leak.

**How to apply:** ignore the messages; they stop when t-519 lands. If they persist after t-519 is complete, that's a new problem.
