---
name: Smithy CLI nudge mis-routes when multiple tmux sessions exist
description: Smithy's internal nudge_forge() picks the wrong tmux session and silently falls back to .smithy-nudge-queue/forge.jsonl; forges never wake
type: project
---

When more than one tmux session matches the smithy CLI's session-detection heuristic (e.g., a phantom `smithy2` session left over from a prior run alongside the live `forge` session), smithy's `nudge_forge()` picks the wrong one, finds no matching panes, and silently writes dispatch messages to `.smithy-nudge-queue/forge.jsonl` as a fallback. Forges idling on tmux nudges never wake; Marshal believes it dispatched.

Observed 2026-04-18 heat 989: a stale `smithy2` session from Apr 11 (1 generic zsh window) was still alive. Marshal's `queue-push` calls for t-448, t-474, t-479, t-480 all queued to the jsonl side-channel. Forges sat idle for ~25min until Anvil nudged them directly via `scripts/nudge.sh` (which pins `FORGE_SESSION=forge` and works correctly). Phantom session killed; tracked as t-489 under ini-022 for the structural fix.

**Why:** Smithy's CLI tmux-detection logic predates `scripts/nudge.sh` and doesn't pin to the canonical `forge` session. The jsonl fallback was meant to be defensive but is actually silent failure — no error surfaces.

**How to apply:**
1. When forges are idle but `next_tasks` is populated and halt is off, **check `tmux ls`** — if a `smithy*` session exists alongside `forge`, that's the cause. Kill the phantom session: `tmux kill-session -t <name>`.
2. Inspect `.smithy-nudge-queue/forge.jsonl` to confirm — recent entries with `"Task t-XXX queued"` messages mean Marshal tried to dispatch and the nudge mis-routed.
3. Recovery: `scripts/nudge.sh <forge-id> "queue-pop and proceed"` for each idle forge. They'll then read state.json + the jsonl and pick up.
4. **Don't** edit the jsonl directly to "replay" nudges — forges read it on their idle poll, but the tmux-wake is what triggers the poll. Use scripts/nudge.sh.
