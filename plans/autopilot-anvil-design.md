# Autopilot Anvil — Design

**Status:** draft (Anvil, 2026-04-19)
**Principle:** *Anvil should handle recurring rig issues without human input; the human sees only what genuinely needs their judgment.*
**Initiative:** new ini-026 *Autopilot Anvil — autonomous operations layer*

## Why

The Smithy calls itself an "autonomous AI worker," but today Anvil is the last human-in-the-loop. Observed 2026-04-19 across ~30 heats of active work: roughly 80% of my interactions with the human were *me repeating the same recovery patterns* — nudge stuck forges, resolve zombie submitted tasks, answer Marshal's silent-stdin questions, kill phantom tmux sessions, requeue after accidental state mutations. The other 20% were genuinely strategic (should we add forges, design Comms, close ini-015).

If Anvil can run the 80% autonomously, the human only sees the 20% that warrants their attention.

## Goals

- Rig keeps running + tasks keep clearing without babysitting
- Recurring failure patterns (zombie submitted, starvation, silent Marshal, missing jsonl) get fixed on their own
- Genuinely ambiguous or strategic decisions get *parked* for human review, not forced to front of attention
- Anvil's interactive role (explain the record, brainstorm strategy) is preserved — this is additive, not replacement

## Non-goals

- Not replacing the human's strategic judgment — autopilot is explicitly bounded
- Not replacing Comms — Comms is periodic reporting; autopilot is periodic action
- Not a fully AI-run rig — the human still owns intent, priorities, budget, new initiatives
- Not a substitute for the liveness chain (ini-024) — autopilot is top-level recovery; ini-024 is agent-level self-healing. They stack.

## Locked decisions (from brainstorm)

1. **Cron-driven tick** — reuses Comms's cron lifecycle infrastructure (t-482 comms-tick.sh pattern, t-483 cron install/uninstall). Tick every 10 minutes by default (tunable via env).
2. **Anvil pane runs it** — autopilot is a MODE of the existing Anvil persona, not a new persona. Strategic judgment stays in one place; file-based state carries context across ticks.
3. **Context clears each tick** (same pattern as Comms — locked earlier: each wake is independent; continuity comes from reading state files).
4. **Allow-listed action surface** — autopilot may perform only a finite, documented list of operations. Anything outside goes to deferral.
5. **Deferral file** for human-needed decisions (`deferred.md` at repo root) — append-only log reviewed by human on return.
6. **Rising-edge notifications** only for anomalies that warrant immediate human attention (halt toggle, budget low, starvation lasting 3+ cycles). Routine stuff stays silent in logs.

## Architecture

```
                system cron (*/10 * * * *)
                           │
                           ▼
               scripts/autopilot-tick.sh
                           │
                    (guards: rig up? halt off? pane alive?)
                           │
                           ▼
         scripts/nudge.sh anvil "<autopilot prompt>"
                           │
                           ▼
               Anvil tmux pane (/clear, then work)
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
      detect anomalies  decision     log to
      (patrol + pane   matrix:       autopilot.log
      + state diffs)   fix | defer
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          nudge, etc.   deferred.md   osascript
          (file-based   append        (rising-edge
          actions)      entry         only)
```

## Anomaly detectors (what each tick looks for)

Read from `state.json`, `worklog.tsv`, `.assembly-queue.jsonl`, each forge + marshal + assembly pane tail (via `tmux capture-pane`):

| # | Name | Signal | Safe to auto-fix? |
|---|---|---|---|
| A1 | **zombie submitted** | task status=`submitted` + branch exists in git + not in assembly jsonl | yes — nudge Assembly to reconcile |
| A2 | **starvation** | forge idle + next_tasks empty + pending work exists + halt off | yes — nudge Marshal to repopulate |
| A3 | **silent Marshal prompt** | Marshal pane tail ends in `❯ ` + Marshal idle >2min | conditional — if question is answerable via state (zombie task status, priority call), auto-answer; else defer |
| A4 | **jsonl missing/stale** | `.assembly-queue.jsonl` absent while submitted tasks exist | yes — nudge Assembly to reconcile |
| A5 | **phantom tmux session** | `tmux ls` shows `smithy*` session alongside `forge` | yes — kill phantom |
| A6 | **orphaned task** (assigned_forge set, not in next_tasks, not in_progress, unblocked) | state scan | yes — queue-push to restore dispatch |
| A7 | **stuck in_progress** | task in_progress >30min without worklog activity from assigned forge | defer — patrol already reaps; if patrol not firing, note in deferred |
| A8 | **repeat rejections** | same task_id rejected ≥3 times in last 30 worklog entries | defer — human needs to decide if task is obsolete, scope too large, or broken |
| A9 | **budget low** | `budget_remaining / budget_total < 0.10` | defer — human budget call; notification fires |
| A10 | **halt flag toggled** | `parallel.halt_flag` changed since prior tick state snapshot | defer — notification fires |
| A11 | **test isolation leak** | Marshal/Assembly pane contains literal fixture strings like `forge-01`, `h1`, `"nudge test"` | log-only — t-519 tracks structural fix |
| A12 | **all forges idle w/ work available** (lasts 2 ticks) | cross-forge scan | escalate — nudge all forges + file issue if recurring |

## Allow-listed actions (autopilot may do these)

1. `scripts/nudge.sh <agent> "<msg>"` — wake any pane with contextual message
2. `smithy complete-task <id>` — only for zombie submitted where merge sha exists in git log
3. `smithy queue-push <task-id> --forge <id>` — restore orphaned dispatch
4. `smithy set-priority <id> <n>` — only downgrade-for-stability (raise priority number); never lower
5. `smithy set-next-tasks <...>` — only during starvation recovery, using the existing priority-walk
6. `tmux kill-session -t <name>` — only for `smithy*` phantom sessions NOT matching the live `FORGE_SESSION`
7. `smithy add-task` — only for recurring pattern detection (e.g. "3rd zombie jsonl this day → file t-X fix ticket"). Dedup by pattern signature.
8. Append to `deferred.md`, `autopilot.log`
9. Fire `osascript -e 'display notification'` on rising-edge anomalies (A9, A10, A12)

**Explicitly forbidden** (always defer):
- Modify `budget.total_heats` (standing rule)
- Flip halt flag
- Reject initiatives or close them
- Modify `state.parallel.max_forges` or forge roster
- File `--initiative` for a new initiative (propose/approve — human territory)
- Commit/push to main (standing rule)
- Delete any file that isn't a known disposable (e.g., phantom tmux session is OK; state.json is not)

## Deferral file — `deferred.md`

Append-only markdown. Each entry:

```markdown
## 2026-04-19T03:45:00Z · A8 repeat-rejections
**Context:** t-472 has been rejected 6 times (heats 911-917). Recurring cause unclear from logs — tests pass locally for forge, fail under Assembly.
**Autopilot did not:** mark complete (not merged anywhere), reject initiative, or change scope. Needs human judgment on whether to split, rewrite, or obsolete.
**Related:** t-507 (sibling in ini-019), memory `project_forge_local_pass_assembly_reject`.
**Severity:** moderate — blocks ini-019 advancement but doesn't block rig.
---
```

Severity tags: `low` (log-only), `moderate` (review before next session), `high` (notification fires + review within 24h), `urgent` (notification + wake human if possible).

Rotation: `deferred.md` caps at ~500 entries; oldest auto-archive to `deferred-archive/YYYY-MM.md`.

## Decision matrix (the tick's core logic)

Pseudocode:

```
for anomaly in detect_all():
    action = match anomaly.type:
        A1 | A2 | A4 | A5 | A6 → safe_fix (action_fn)
        A3 → if answerable_from_state(pane_text): safe_fix; else defer
        A7 → defer (patrol territory)
        A8 → defer (human judgment)
        A9 | A10 | A12 → defer + notify
        A11 → log_only
    if action == safe_fix:
        result = action_fn(anomaly.context)
        log(anomaly, "auto-fixed", result)
    elif action == defer:
        append_deferred(anomaly, severity=classify(anomaly))
        if severity >= high: notify(anomaly)
    elif action == log_only:
        log(anomaly, "noted, no action")
```

Each anomaly type has exactly one registered detector + action. Adding a new anomaly is a code change (file → review → merge), not runtime config — keeps the action surface explicit and auditable.

## Lifecycle

- **Install:** `start-smithy.sh` appends crontab line `*/10 * * * * /path/to/scripts/autopilot-tick.sh`. Idempotent.
- **Tick wrapper** (`scripts/autopilot-tick.sh`): exits 0 silently if (1) no forge tmux session, (2) `halt_flag=true`, (3) Anvil pane missing. Otherwise `scripts/nudge.sh anvil "<autopilot-mode prompt>"`.
- **Uninstall:** `stop-smithy.sh` removes the crontab line.
- **Manual invocation:** `scripts/autopilot-tick.sh --force` for testing/debugging. Also `smithy autopilot --once` CLI for explicit human-triggered run.

## Anvil autopilot-mode prompt

The prompt nudge.sh sends to Anvil on each tick. Self-contained (context clears each wake):

```
AUTOPILOT TICK. Clear context (/clear), then:
1. Read state.json, .assembly-queue.jsonl, tail -20 worklog.tsv, tail of each pane (Marshal, Assembly, forge-*).
2. Run `smithy patrol` and parse the JSON output.
3. For each anomaly detected, apply the decision matrix (plans/autopilot-anvil-design.md §Decision matrix). Action surface allow-list is §Allow-listed actions. Never step outside it.
4. For safe-fix actions: take them, log one line to autopilot.log.
5. For defer actions: append to deferred.md with severity. Fire osascript notification if severity >= high.
6. Emit a single one-line summary to autopilot.log: "TICK <timestamp> · N anomalies · K fixed · D deferred · U urgent".
7. Sleep (idle — no further action).
8. Do NOT engage interactively. Do NOT ask questions. If uncertain, defer.
```

Anvil interactive mode (human-driven) stays unchanged — this prompt flag switches to autopilot. Distinguish via prompt prefix.

## Relationship to adjacent work

- **ini-023 Comms** — reports state; autopilot *changes* state. Comms sends 5-min rhythm reports to human; autopilot runs 10-min rhythm actions on rig. Overlap: cron lifecycle (t-482/t-483 can be reused). Divergence: Comms is read-only, autopilot is write-allowed.
- **ini-024 Liveness** — agents self-heal (Forge claims work, Assembly reconciles jsonl, Marshal maintains next_tasks invariant). Once these land, anomalies A1/A2/A4/A6 from autopilot's matrix become rare or impossible — autopilot's load drops to mostly A3/A8/A9/A10 (the judgment-requiring cases). **Gate autopilot's rollout on at least t-494 + t-495 + t-496 landing** — otherwise autopilot fights the same bugs every tick instead of structural fixes resolving them.
- **Patrol** — autopilot reuses `smithy patrol` JSON output as its primary detector for A4/A6/A7 signals. Any new patrol check (t-491 starvation, t-493 jsonl leak) automatically enriches autopilot's signal.

## Implementation tickets

T1. **autopilot-tick.sh safety wrapper** — cron-fired script that guards (session up, halt off, pane alive) then nudges Anvil with the autopilot prompt. 4-gate pattern mirrors Comms's `comms-tick.sh` (t-482). ~1 heat. *(blocked on t-483 cron install plumbing already filed under ini-023 — same plumbing serves both)*

T2. **Decision matrix + detectors** — code in `smithy/smithy/autopilot.py` (new module): one detector function per A1-A12 anomaly, each returning `(detected: bool, context: dict, severity: str)`. Pure functions operating on state + pane captures. Tests per detector. ~2 heats.

T3. **Anvil autopilot-mode prompt + action library** — update `personas/anvil/CLAUDE.md` with a new "Autopilot mode" section that documents the prompt format, the allow-list, the deferral file format, and the "never step outside allow-list" discipline. No code; protocol documentation. ~1 heat.

T4. **Deferral file + notification plumbing** — `scripts/autopilot-append-deferred.sh` helper (or inline in Anvil's prompt-handling); `osascript` wrapper; `deferred-archive/YYYY-MM.md` rotation at ~500 entries. ~1 heat.

T5. **Bellows render of deferred.md** — new section in Bellows home showing recent deferred entries (severity-colored); click-through to full `deferred.md` viewer. Blocked on t-500 (whitespace) + t-501 (markdown rendering) for proper prose display. ~1 heat.

T6. **Rollout gate + shakedown** — gate on liveness chain (t-494, t-495, t-496) having landed. Run autopilot with `FORGE_AUTOPILOT_ENABLED=0` default; manual `smithy autopilot --once` invocation for shakedown. After 1 week of observation and 0 destructive actions, flip default to enabled. Document the rollout criteria in `plans/autopilot-anvil-design.md` §Rollout. ~0.5 heat (mostly ops).

**Total budget:** ~5-6 heats across T1-T6.

## Open questions

1. **Tick cadence** — 10min is my default. Too slow? Too fast? The liveness chain reduces the load on autopilot substantially; once it lands, 15min might be plenty. Revisit after shakedown.
2. **Notification channel** — macOS `osascript` for v1. Slack/email as potential add-on (separate initiative if wanted).
3. **Autopilot logging verbosity** — append every tick summary, or only when anomalies were found? My vote: every tick (even "clean" ticks) — gives you a heartbeat that autopilot is running.
4. **Override / pause mechanism** — `FORGE_AUTOPILOT_ENABLED=0` env disables at cron level. Also `.autopilot-paused` sentinel file as a human-accessible pause button? My vote: yes, add it — lets the human park autopilot without a crontab edit.
5. **Metrics** — count of anomalies detected / fixed / deferred per week → feed into ini-012 timeline dashboard (t-520) once it exists. Autopilot's own throughput becomes observable.
