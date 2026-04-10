# Information Compression Layers

The reporting stack has 5 layers. The human reads the lightest layer that answers their question. Each deeper layer adds detail.

## L0: Signal (per heat)

**Format**: 🟢/🟡/🔴 + 1-line summary (in worklog.tsv and dashboard)

**Classification** (from `protocol/logging.md`):
- 🟢 Green: value ≥ 0.7, completed normally, no uncertainty
- 🟡 Yellow: value < 0.7, progress stalled, or moderate uncertainty
- 🔴 Red: rollback, blocked > 5 heats, high uncertainty, or intent deviation

**When to read**: Always visible in the dashboard. Human scans for yellow/red — green means "fine, skip."

## L1: Run Summary (per run)

**Format**: 3-5 line summary in `outbox.md` at end of run

**Contents**: Stages worked, tasks completed, key decisions, signal counts (🟢×N, 🟡×M, 🔴×K)

**When to read**: After each run completes. Takes 30 seconds.

## L2: Dashboard (on demand)

**Format**: `./forge-status.sh` output

**Contents**: Budget, stage progress bars, last 10 heat signals, alerts (stalled stages, blocked tasks, integral extremes, low queue), recent commits, what's missing.

**When to read**: When curious about the project state. Takes 1 minute.

## L3: Artifacts (spot-check)

**Format**: Key files changed in the run — listed in the AAR (`aar/<date>.md`)

**Contents**: Files created/modified, decisions made (from commit messages), things the Forge is unsure about.

**When to read**: When L0/L1 flags something yellow/red. Review the actual artifacts to assess quality. Takes 5-10 minutes.

## L4: Full Log (investigation)

**Format**: `worklog.tsv` + `MEMORY_DAILY.md` + `git log`

**Contents**: Every heat logged with stage, task, outcome, value, signal, notes. Full memory. Full git history.

**When to read**: Rarely — for deep investigation, debugging, or understanding historical decisions.

## Flow

```
Normal:     L0 (scan signals) → done
Curious:    L0 → L2 (forge-status) → done
Concerned:  L0 → L1 (run summary) → L3 (artifacts) → maybe L4
Debugging:  L4 (full log + git log)
```

The human should never need to read L4 during normal operation. If they do, the upper layers failed to surface the right information.
