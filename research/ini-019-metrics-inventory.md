# ini-019 R1 — Observability Metrics Inventory

**Task:** t-444 · **Initiative:** ini-019 (Forge Observability) · **Heat:** 823

Catalog of every metric derivable — read-only, replay-safe — from existing records. No new write paths proposed. Each row answers: *what is it*, *which source column(s)*, and *derivation shape* (counter / rate / duration / histogram / set-membership).

## Sources (authoritative)

| Source | Path (main repo root) | Shape | Rows/entries (4/18) |
|---|---|---|---|
| S1 · worklog | `worklog.tsv` | TSV, append-only | 904 |
| S2 · rig events | `rig-events.jsonl` | JSONL, append-only | 145 |
| S3 · assembly log | `assembly-log.jsonl` | JSONL, append-only | 32 |
| S4 · state (queue + initiatives) | `state.json` | snapshot (current) | 391 tasks, 19 initiatives |
| S5 · git log | `git log main` | commit stream | `[stage] t-XXX: …` prefix |

**Schemas:**

- **S1 worklog columns:** `timestamp · heat · stage · task_id · outcome · value · signal · notes · forge_id?`  (forge_id trailing, t-409+; 82/904 rows carry it today).
- **S2 rig event base:** `ts · event · actor` + event-specific fields. 16 event types: `forge_started`, `forge_ended_{complete,partial,submitted,blocked}`, `queue_{push,pop,set}`, `marshal_nudged`, `assembly_nudged`, `nudge_sent`, `assembly_tick_{begin,merged,rejected}`, `assembly_push_ok`.
- **S3 assembly log:** `ts · forge_id · task_id · outcome ∈ {merged, rejected, push_ok} · detail`.
- **S4 state.queue task:** `id · stage · desc · status · priority · blocked_by · human_priority · priority_reason · assigned_forge · initiative_id?` (initiative_id on 182/391 today; full backfill is t-447).
- **S4 state.initiatives item:** `id · theme_id · title · description · status · budget_cap · heats_used · viewed_at · rank · parallelism · affinity · touches` (+ `intent` on some).
- **S4 state.parallel.forges:** `id · status · current_task · current_heat · started_at · last_heartbeat · worktree · branch`.

## A. Lifecycle State Metrics

A "task life" reconstructs cleanly from S2+S3+S4 by `task_id`. S1 is the compressed ledger per heat; S2 is the fine-grained event stream.

| # | Metric | Derivation | Source(s) |
|---|---|---|---|
| A1 | Task state (current) | `state.queue[task].status ∈ {pending, in_progress, complete, rejected}` | S4.queue.status |
| A2 | Task state history | Ordered events where `task_id == T`, projected to {queued, popped, started, ended, submitted, merged, rejected} | S2.event + S3.outcome |
| A3 | Queue wait time | `queue_pop.ts − queue_push.ts` per task_id | S2.queue_push.ts, S2.queue_pop.ts |
| A4 | In-flight duration | `forge_ended_*.ts − forge_started.ts` | S2.forge_started.ts, S2.forge_ended_*.ts |
| A5 | Assembly merge latency | `assembly_tick_merged.latency_ms` (already emitted) | S2.assembly_tick_merged.latency_ms |
| A6 | End-to-end lead time | `assembly_tick_merged.ts − queue_push.ts` per task_id | S2 (2 events) |
| A7 | Stage distribution (cumulative) | COUNT(worklog) GROUP BY stage | S1.stage |
| A8 | Stage distribution (per-heat window) | COUNT(worklog WHERE heat BETWEEN h1,h2) GROUP BY stage | S1.heat, S1.stage |
| A9 | Stage heat share vs target | S4.stages[stage].heats ÷ total ↔ allocator weights | S4.stages, S4.allocator |
| A10 | Forge idle% | 1 − (Σ A4 per forge) ÷ wall-clock window | S2.forge_started, S2.forge_ended_* (group by actor/forge_id) |
| A11 | Forge utilisation timeline | Gantt of (actor, forge_started → forge_ended_*) intervals | S2.forge_started, S2.forge_ended_* |
| A12 | Concurrent forges active | Count overlapping intervals from A11 | S2 |
| A13 | Queue depth over time | Running Σ(push) − Σ(pop); also `queue_push.queue_size` is emitted directly | S2.queue_push.queue_size, S2.queue_pop.remaining |
| A14 | Queue set events (reprioritisation) | `queue_set` with `task_ids[]`; count + drift vs prior | S2.queue_set.task_ids, .count |
| A15 | Assigned-but-not-started tasks | S4.queue.status=pending ∧ assigned_forge ≠ null ∧ no forge_started in window | S4, S2 |

## B. Failure-Type Metrics

Failures live across all three logs; Issues view in ini-019 L1 should union these buckets.

| # | Metric | Derivation | Source(s) |
|---|---|---|---|
| B1 | Rejection rate by forge | COUNT(assembly-log.outcome=rejected) ÷ COUNT(all) GROUP BY forge_id | S3.forge_id, S3.outcome |
| B2 | Rejection causes (classified) | Regex/substring over `S3.detail`: `rebase error`, `tests failed`, `no commits`, `non-ff`, etc. | S3.detail |
| B3 | Test-failure recurrence | From B2 `tests failed` rows, extract pytest node-ids (`FAILED <file>::<test>`) and count recurrences | S3.detail |
| B4 | Ghost submits (submitted but no merge/reject) | `forge_ended_submitted.task_id` ∉ {assembly_tick_merged ∪ assembly_tick_rejected} within window | S2 events union |
| B5 | Forge-side blocks | `forge_ended_blocked` count by actor/task_id; cross-ref `S1.outcome=blocked` | S2.forge_ended_blocked, S1.outcome |
| B6 | Partial outcomes | `forge_ended_partial` count by actor/task; S1 outcome=partial | S2, S1.outcome |
| B7 | Red signals (🔴) | COUNT(S1 WHERE signal=🔴), bucketed by stage/task | S1.signal |
| B8 | Yellow signals (🟡) | COUNT(S1 WHERE signal=🟡) and ratio vs green | S1.signal |
| B9 | Rejection signals in worklog | COUNT(S1 WHERE signal=🚫) — the worklog-side of assembly rejection | S1.signal |
| B10 | Assembly stall / push-only | `assembly_push_ok` count with no tick_merged follow-up | S2.assembly_push_ok, S2.assembly_tick_merged |
| B11 | Rebase conflicts (severe) | S3.detail matches `CONFLICT` or reject-to-marshal phrasing | S3.detail |
| B12 | Test-gate bypass events | Commit messages via S5 matching `--skip-tests` / witness-gate escape | S5 commit body |
| B13 | Orphan in_progress (pre-reap) | S4.queue.status=in_progress ∧ no corresponding forge_started in last N minutes ∧ forge.status=idle | S4, S2 |
| B14 | Zero-value heats (stuck) | S1 WHERE value ≤ 0.2 | S1.value, S1.signal |

## C. Retry / Thrash Metrics

"Thrash" = same task appearing in multiple lifecycle attempts. With t-445/t-447 in place, all of these gain initiative-level rollups.

| # | Metric | Derivation | Source(s) |
|---|---|---|---|
| C1 | Per-task attempt count | COUNT(forge_started GROUP BY task_id) | S2.forge_started.task_id |
| C2 | Per-task reject count | COUNT(assembly-log WHERE outcome=rejected GROUP BY task_id) | S3.task_id, S3.outcome |
| C3 | Per-task requeue count | COUNT(queue_push GROUP BY task_id) — >1 ⇒ requeued | S2.queue_push.task_id |
| C4 | Thrash ≥3 retries (Issues bucket) | task_ids where C1 ≥ 3 or C2 ≥ 2 | S2, S3 |
| C5 | Reject→requeue→merge trajectory | Sequence (rejected, queue_push, forge_started, tick_merged) for same task_id | S2 + S3 joined on task_id |
| C6 | Mean retries per initiative | AVG(C1) GROUP BY initiative_id (after t-447 backfill) | S2 ⋈ S4.queue.initiative_id |
| C7 | Time-to-green after reject | `assembly_tick_merged.ts − last assembly_tick_rejected.ts` per task_id | S3 timestamps |
| C8 | Forge affinity for thrash | Thrash tasks GROUP BY forge_id — does one forge stall a specific kind? | S2.actor ∪ S3.forge_id |
| C9 | Repeat test-failure nodes | B3 output filtered to `count ≥ 2` — same failing test across tasks | S3.detail |
| C10 | Stage-hop pattern | Same task_id with multiple distinct `stage` values across S1 rows — usually fine (research→impl→test), but anomalous when implementation→implementation→implementation (repeat attempts) | S1.task_id, S1.stage |
| C11 | Integral windup correlation | S4.stages[stage].value_ema + integral vs B7/B8 rates per stage | S4.stages, S1.signal |

## D. Initiative-Rollup Metrics (post t-447 backfill)

Gated on t-445/t-447 landing; all S1/S2/S3 metrics gain an `initiative_id` dimension via task_id join.

| # | Metric | Derivation | Source(s) |
|---|---|---|---|
| D1 | Initiative burn-down | S4.initiatives[i].heats_used vs budget_cap; also Σ(S1 heats WHERE task.initiative_id=i) for audit | S4.initiatives, S1 ⋈ S4.queue |
| D2 | Initiative cycle time | max(S3 merged ts) − min(S2 push ts) for tasks tagged i | S2, S3 |
| D3 | Initiative success rate | (merged tasks ÷ total tasks in i) | S3.outcome ⋈ S4.queue |
| D4 | Initiative value profile | AVG(S1.value), stddev WHERE task.initiative_id=i | S1 ⋈ S4.queue |
| D5 | Initiative parallelism actual vs declared | Concurrent A11 intervals of i-tagged tasks vs S4.initiatives[i].parallelism | S2, S4 |
| D6 | Initiative thrash share | Σ C4 tasks WHERE initiative_id=i | S2, S3, S4 |

## E. Persona / Forge Heatmap (ini-019 L1 panel 4)

| # | Metric | Derivation | Source(s) |
|---|---|---|---|
| E1 | Heats per forge per stage | COUNT(S1) GROUP BY forge_id, stage (forge_id trailing col; pre-t-409 rows unknown → omit or label "legacy") | S1.stage, S1.forge_id |
| E2 | Mean value per forge per stage | AVG(S1.value) GROUP BY forge_id, stage | S1 |
| E3 | Signal mix per forge | 🟢/🟡/🔴/🚫 ratios per forge | S1.signal, S1.forge_id |
| E4 | Forge rejection share | B1 expressed as fraction of that forge's submitted count | S2, S3 |
| E5 | Forge nudge cadence | COUNT(marshal_nudged WHERE actor=forge_id) — self-reported work-cycle health | S2.marshal_nudged |
| E6 | Current heartbeat age | now − S4.parallel.forges[i].last_heartbeat (live, not replayable) | S4 |

## F. Allocator / PI-Controller Signals (already computed, worth surfacing)

| # | Metric | Derivation | Source(s) |
|---|---|---|---|
| F1 | value_ema per stage | S4.stages[stage].value_ema | S4 |
| F2 | Integral per stage | S4.stages[stage].integral (clamped ±1.0 per t-015) | S4 |
| F3 | Heat count per stage | S4.stages[stage].heats | S4 |
| F4 | Overall progress | S4.overall_progress | S4 |
| F5 | Budget burn | S4.budget.used ÷ total | S4.budget |

## G. Replay Primitives (for `smithy report --at-heat N`)

Anything in S1/S2/S3/S5 is append-only ⇒ every metric above is **point-in-time replayable** by filtering `ts ≤ T` or `heat ≤ N`. S4 (state.json) is a *snapshot*; to replay it, reconstruct from S1+S2+S3 at the target heat, or checkout git at the matching commit.

- **Replay key 1 — heat number:** S1 rows up to N.
- **Replay key 2 — timestamp:** S2/S3 rows where `ts ≤ T`.
- **Replay key 3 — git SHA:** S5 `git show --stat` + S4 at that SHA (works because state.json is committed per heat).

## H. Gaps & Blind Spots (explicit non-metrics)

Flagging what the record *can't* answer today so the L0/L1 design doesn't promise it:

1. **Pre-t-409 forge attribution:** ~743 worklog rows have no trailing `forge_id`. Heatmaps E1/E2/E3 must show "legacy/unknown" as a distinct bucket, not drop the row.
2. **Pre-t-419/t-447 initiative attribution:** only 182/391 queue tasks carry `initiative_id` today. All D-series metrics are retroactive-via-backfill (t-447) OR forward-only until backfill lands.
3. **In-heat tool activity:** rig events are bounded to lifecycle; we don't see "how many tool calls" or "how many files edited per heat." Git diff stats (S5 `git show --stat`) approximate files-changed but not tool-call depth.
4. **Human steering events:** Poker/Cockpit reorderings, `set-next-tasks`, and `queue_set` are emitted — but free-form human edits to state.json go unlogged. Git blame on state.json is the fallback.
5. **Assembly rejection reason taxonomy:** S3.detail is freeform — requires a stable classifier (regex table) to be a metric source. Initial buckets: rebase-unstaged, rebase-conflict, tests-failed, no-commits, non-ff, other.
6. **Idle-time cause:** A10 tells us *that* a forge was idle, not *why* (queue empty vs. waiting on dep vs. halted). Partially recoverable from S4.parallel.halt_flag + queue state at that ts, but not directly encoded.
7. **Ghost-submit root cause:** B4 catches ghosts, but distinguishing "never pushed" from "Assembly missed it" requires the subprocess-level detail in S3.push_ok vs a missing tick_begin.
8. **Time-gaps during a heat:** S2 only has start/end; intra-heat checkpoints (e.g. `start-heat` → first commit) aren't emitted. `git log --format=%H %cI` gives partial visibility via commit cadence.

## I. Recommended L0 / L1 / L2 Mapping

- **L0 `smithy report` CLI:** surface A7, A9, A10, B1, B2, C4, D1, D3, F4, F5. Keep to ≤10 lines.
- **L1 Bellows Forge Ops:**
  - Rig strip — A11 (live), E6, F5.
  - Initiatives panel — D1, D2, D3, D5.
  - Drill-down timeline per task — A2 (the canonical "task life" view using task_id join across all sources).
  - Persona heatmap — E1–E4.
  - Issues view — B4, C4, C9, B10, B13 (each a clickable bucket).
- **L2 JSON snapshot (per-heat):** full A/B/C/E aggregate dict + schema version; enables offline regression — the time-series we can chart later.

## J. Open Questions for Anvil / Marshal

1. Should `queue_push` also record *who* pushed (actor is already there — but is it marshal vs human vs auto-repair)? If "auto-repair" pushes aren't distinguishable from marshal pushes, C3 will over-count.
2. Do we want a `heat_committed` event emitted at the `git commit` callsite? Would close Gap H.8 and give us real commit cadence.
3. Is `assembly_tick_rejected.reason` stable enough to canonicalise, or should we ship the regex classifier (B2) as part of the report layer?

---
**Prepared by:** forge-temper · heat 823 · research stage · 2026-04-18
