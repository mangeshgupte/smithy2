---
name: Non-primary checkpoint recovery
description: When smithy start-heat appears to succeed but .forge-checkpoint-<id>.json is missing at main repo root, reconstruct it manually so end-heat can log the heat
type: project
---

Symptom: `smithy end-heat` fails with `"No checkpoint found for forge-temper at .forge-checkpoint-forge-temper.json — did you start a heat?"` even though start-heat returned a heat number and created the task branch.

**Why:** The non-primary checkpoint path is `<main-repo-root>/.forge-checkpoint-<forge-id>.json` (per t-409). Something between start-heat and end-heat can leave the primary file in place (`.forge-checkpoint.json` for forge-quench was present) while the non-primary one is absent. Observed 2026-04-18 heat 824 (forge-temper/t-445) — exact trigger unclear; worktree had a dirty per-worktree `state.json` that was restored pre-start-heat, which may be related.

**How to apply:** If end-heat reports a missing checkpoint but the commits, branch, and logical heat state are all valid, recreate the file at `/Users/mangesh/vibes/smithy2/.forge-checkpoint-<forge-id>.json` with `{heat, stage, task_id, forge_id, git_head, timestamp}`. git_head = current HEAD sha on the task branch. Then `smithy end-heat ... --forge <id> --skip-tests` (skip-tests only if the heat didn't touch code — research is safe).

Do NOT silently skip end-heat — the heat must be logged to worklog.tsv or the record is broken.

Surface to Marshal/Anvil as a real bug candidate; don't just paper over it.
