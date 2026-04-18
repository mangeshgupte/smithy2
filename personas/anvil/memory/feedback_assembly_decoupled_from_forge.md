---
name: Assembly must never block Forge throughput
description: Any fix where Forge waits for Assembly is wrong — Forge idle time is the expensive resource; Assembly must operate in its own workspace
type: feedback
---

When designing Assembly↔Forge interactions, Assembly must **never** require the Forge to wait, stay on a branch, or otherwise pause work. Forge idle cycles are the expensive resource — we have 3 Forges producing at ~5min/heat, Assembly merges at ~1min; even brief Forge blocking is capacity death.

**Why:** 2026-04-18 on bug t-456 (Assembly's `rebase_forge_branch` runs in the Forge's worktree, fails when Forge has moved on), my first-pass fix told Forges to stay on the fix branch until merge completed. Human (correctly) pushed back: that wastes a lot of cycles. Right design: Assembly operates in its own `.worktrees/_assembly-staging`, snapshots the task branch ref into a local `_merge-<task-id>` ref, rebases there, merges from the staging ref. Forge never waits.

**How to apply:** When a bug or feature involves Assembly touching a Forge's worktree, default answer is NO. Refactor so Assembly works off branch refs (git worktrees share refs across all worktrees). Any scheme that requires Forge to pause, wait, or stay on a specific branch post-submit is an architectural smell. The Forge should be free to submit, move on, and be queue-popping the next task within seconds.
