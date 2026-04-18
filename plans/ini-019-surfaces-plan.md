# ini-019 P1 — Surface Design Spec

**Task:** t-446 · **Initiative:** ini-019 (Forge Observability) · **Heat:** 823 · **Prepared:** 2026-04-18

Design spec for the three read-only aggregation surfaces over
`worklog.tsv` + `rig-events.jsonl` + `assembly-log.jsonl` + `state.json` + git log.
Metric IDs (A1…F5) reference the R1 inventory in
`research/ini-019-metrics-inventory.md` — they are the *only* vocabulary used
here so downstream implementation tasks can be unambiguous.

**Scope guardrail:** no new write paths. Every number in every surface is a
pure function of the existing record. Anything that needs a new event is
called out in §5 as a follow-up, not baked into the spec.

---

## 1. L0 — `smithy report` CLI

### 1.1 Intent

One command, terminal-native, ≤40 lines of output on a standard 80-col
terminal, answering "how is the rig doing, right now or at heat N?"

Two audiences:
- **Human (morning check):** glance-readable summary — budget, stage mix, top failures, initiative burn.
- **Marshal/Anvil (programmatic):** `--json` emits a machine-parseable payload so Poker / steering code can consume it without re-computing metrics.

### 1.2 Argument surface

```
smithy report [--at-heat N | --at-ts ISO8601 | --at-sha SHA]
              [--initiative <id>]
              [--forge <id>]
              [--window <N-heats|N-hours>]
              [--json | --tsv]
              [--sections <comma-list>]
              [--verbose]
```

| Flag | Semantics | Default |
|---|---|---|
| `--at-heat N` | Filter S1 rows to `heat ≤ N`; filter S2/S3 to `ts ≤ worklog.row[N].ts`; reconstruct S4 aggregates from those rows (don't read live S4). | live (current heat) |
| `--at-ts T` | Same as `--at-heat`, but cutoff is an ISO timestamp. S1 rows filtered by `timestamp ≤ T`. | live |
| `--at-sha SHA` | `git show <SHA>:state.json` for S4, then re-derive S1/S2/S3 from the same commit tree. | HEAD |
| `--initiative <id>` | Restrict every metric to tasks with that `initiative_id`; post-t-447 reliable, pre-backfill tagged "unknown" bucket shown separately. | all |
| `--forge <id>` | Restrict to that forge's rows (trailing forge_id in S1; actor in S2; forge_id in S3). | all |
| `--window N-heats` | Rolling window: last N heats. Pairs with `--at-heat`. | lifetime |
| `--window N-hours` | Rolling window by wall-clock. | lifetime |
| `--json` | Emit the L2 snapshot schema (§3) to stdout. No human section headers. | off |
| `--tsv` | Per-metric tab-separated rows. Shellable. | off |
| `--sections a,b,c,d` | Comma list from {`budget`,`stages`,`forges`,`issues`,`initiatives`,`thrash`}. | all |
| `--verbose` | Adds the gap-flag notes (H-series) and any data-quality caveats. | off |

**Mutual exclusion:** `--at-heat`, `--at-ts`, `--at-sha` are mutually
exclusive; specifying two returns exit-code 2 with a usage line.

**Exit codes:** `0` ok · `1` data missing (e.g., worklog shorter than `--at-heat N`) · `2` usage/argparse error.

### 1.3 Default output format (human, ≤40 lines)

Six sections, each a labeled block. No tables wider than 72 chars. No colour
by default (respect `$NO_COLOR`); otherwise signal glyphs 🟢/🟡/🔴 render as-is
and rejection 🚫 shown in red bold.

```
Smithy Report · heat 904 · 2026-04-18 09:14Z
──────────────────────────────────────────────
Budget      [███████████░░░░] 892/1104  80.8%       [F4, F5]
Progress     0.74  (ema up from 0.71 last 20 heats)  [F4]

Stages (mix vs. target)            [A7, A9]
  research         48   5.3%   ( -1.7pp vs weight 0.07 )
  implementation  314  34.7%   ( -3.3pp vs weight 0.38 )
  testing         140  15.5%   ( +0.5pp vs weight 0.15 )
  editing         186  20.5%   ( -2.0pp vs weight 0.22 )
  marketing        96  10.6%   ( +2.6pp vs weight 0.08 )
  planning         34   3.8%   ( +3.8pp vs weight 0.0  )

Forges (last 24h)                  [A10, A11, E1, E3]
  forge-quench    42 heats  idle 12%   🟢 38 🟡 3 🔴 1
  forge-temper    29 heats  idle 24%   🟢 26 🟡 2 🔴 1
  forge-anneal    17 heats  idle 41%   🟢 16 🟡 1 🔴 0

Initiatives (active, by burn)      [D1, D3]
  ini-019  Forge Observability    1/25 heats   ▓░░░░ 4%     success 100%
  ini-017  Priority Poker         3/10 heats   ▓▓▓░░ 30%    success 67%
  ini-013  Assembly hardening    14/18 heats   ▓▓▓▓▓ 78%    success 93%

Issues (last 48h)                  [B4, C4, C9, B10, B13]
  Ghost submits ............... 0
  Thrash ≥3 retries ........... 2   t-401, t-429
  Repeat failing tests ........ 1   test_marshal_forge_flow::test_idle
  Assembly stalls ............. 0
  Orphan in_progress .......... 0  (patrol auto-reap: 2 in this window)

Top failure buckets              [B1, B2]
  rebase-conflict   4    tests-failed  2    no-commits  1
```

Line budget: ~38 lines of content. Fits one terminal screen.

### 1.4 `--json` output

Identical to the L2 snapshot schema (§3), with a top-level
`"surface": "report"` marker so the caller can distinguish a live
`smithy report --json` from an L2 archive row. No human narrative
sections in `--json` mode.

### 1.5 `--tsv` output

One row per `(metric_id, dimension_key, value)` triple:

```
A7	research	48
A7	implementation	314
A9	research	-0.017
B1	forge-quench	0.03
C4	thrash_tasks	t-401,t-429
```

Suitable for quick awk / spreadsheet import. Dimension keys are lowercase,
hyphenated; list values are comma-separated.

### 1.6 Replay-at-heat semantics (§1.2 `--at-heat`)

Replay is the load-bearing property. Three source-specific rules:

1. **S1 (worklog):** `head -n N worklog.tsv` (N counts data rows, not header).
2. **S2/S3 (jsonl):** filter rows where `ts ≤ worklog.row[N].ts` — that ts
   is the monotonic reference clock. (The worklog ts at row N is the
   "end of heat N" moment.)
3. **S4 (state.json):** ignore live file. Reconstruct:
   - `budget.used = N`
   - stages: re-run allocator update from rows 1…N with
     `smithy.allocator.replay(worklog_rows[:N])` (already pure in
     `allocator.py` — t-015 ema/integral is deterministic).
   - queue: `git show <sha>:state.json` where `<sha> = git log --format=%H
     --grep "heat:${N}" main -1`. Fallback: nearest commit ≤ N.
   - rolled-up initiatives: same `git show` sha; compare to live for drift warning.

**Determinism contract:** `smithy report --at-heat N` at two different wall times MUST
produce byte-identical output (modulo a `generated_at` field in `--json`). A regression
test in `tests/test_report_replay.py` asserts this on a frozen fixture worklog.

### 1.7 Non-goals (for v1)

- No colour themes beyond `$NO_COLOR` + signal glyphs.
- No paging / `$PAGER` integration — output fits one screen by design.
- No watch/follow mode (`--follow`) — rig-status.sh already exists for that.
- No writes to state or logs. `smithy report` is pure-read.
- No chart rendering. L2 JSON is the time-series feed; external tooling (jq,
  gnuplot, a future Bellows chart) renders.

---

## 2. L1 — Bellows Forge Ops View

### 2.1 Intent

A single Bellows page, mounted at `/project/{project_name}/ops`, that renders
five panels side-by-side. Every panel is a thin view over the same L2 JSON
snapshot that `smithy report --json` produces — the backend endpoint
`/api/project/{project_name}/ops` just returns that snapshot plus a
`recent_events[]` tail. No new state, no new writes.

**Refresh model:** server-sent events (SSE) from `/api/project/{name}/ops/stream`,
tailing rig-events.jsonl. On each new event, the page re-fetches its L2 payload
and swaps in the panels that changed. Full-page re-render is a fallback.

### 2.2 Page layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Forge Ops · Smithy                             │
│  [now] heat 904 · 2026-04-18 09:14Z          [Replay: ◀─────────▶ ▶▶]  │
├─────────────────────────────────────────────────────────────────────────┤
│ PANEL 1 — Rig Strip (full width, ~90px tall)                            │
├─────────────────────────────┬───────────────────────────────────────────┤
│ PANEL 2 — Initiatives       │ PANEL 3 — Drill-down (task timeline)      │
│ (40% width, scrollable)     │ (60% width; empty state shows overview)   │
│                             │                                           │
├─────────────────────────────┼───────────────────────────────────────────┤
│ PANEL 4 — Persona Heatmap   │ PANEL 5 — Issues                          │
│ (40% width)                 │ (60% width; tabbed buckets)               │
└─────────────────────────────┴───────────────────────────────────────────┘
```

Top-bar "Replay" scrubber — drag to any heat N in lifetime; the whole page
becomes read-only and re-renders from `smithy report --at-heat N --json`.
Distinct banner colour (muted amber) when not live, to prevent confusion.

### 2.3 Panel 1 — Rig Strip

One row per active forge, live heartbeat + current task.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● forge-quench   t-437  [impl] heat 903  ▓▓▓░░░ 03:12   🟢 last:0.8  │
│ ● forge-temper   t-440  [test]  heat 902  ▓▓▓▓▓░ 04:45   🟡 last:0.5 │
│ ○ forge-anneal   idle — queue empty — waiting since 09:11Z           │
│ ▢ assembly       tick in 00:42  last merged: t-432 (42ms)            │
└──────────────────────────────────────────────────────────────────────┘
```

Metrics: A11 (interval gantt since start-heat), E6 (heartbeat age), live
S4.parallel.forges snapshot. Status dot: ● active · ○ idle · ◐ degraded
(heartbeat > 8 min) · ▢ assembly.

Click a row → Panel 3 drill-down to that forge's current task.

### 2.4 Panel 2 — Initiatives

Scrollable list of all `status=approved` initiatives, ranked by `rank`.

```
┌──────────────────────────────────────┐
│ INITIATIVES                   [ + ]  │
├──────────────────────────────────────┤
│ ini-019 Forge Observability          │
│   1 / 25   ▓░░░░░░░░   4%            │
│   success 100%  ·  cycle-time  —     │
│   2 tasks in-flight  ·  0 issues     │
├──────────────────────────────────────┤
│ ini-017 Priority Poker               │
│   3 / 10   ▓▓▓░░░░░░  30%            │
│   success 67%  ·  cycle-time 2.1h    │
│   1 task in-flight  ·  1 issue ⚠     │
├──────────────────────────────────────┤
│ ini-013 Assembly hardening           │
│   14 / 18  ▓▓▓▓▓▓▓▓░  78%            │
│   success 93%  ·  cycle-time 38m     │
│   0 in-flight  ·  0 issues           │
└──────────────────────────────────────┘
```

Per row (all post-t-447 backfill): D1 burn-down, D2 cycle time (median), D3
success rate, D5 parallelism-actual (as count of concurrent tasks), D6 thrash
badge when ≥1. Click → Panel 3 filters to that initiative's tasks. `[ + ]`
opens the existing Initiative create modal (reuse of `initiative.html`).

### 2.5 Panel 3 — Drill-down (task timeline)

Empty state: stacked area chart of heats-per-stage over lifetime (S1-sourced).

Task state: vertical swim-lanes of the canonical "task life" (A2), joining
S2 + S3 events on `task_id`:

```
┌──────────────────────────────────────────────────────────────┐
│  Task  t-437  Patrol check #10 · ini-013 · forge-quench      │
├──────────────────────────────────────────────────────────────┤
│  09:02  queue_push         (marshal)                         │
│  09:02  queue_pop          (forge-quench)       +0s   [A3]   │
│  09:02  forge_started      impl                  +1s         │
│  09:05  forge_ended_submit                      +3m4s [A4]   │
│  09:05  assembly_push_ok                        +2s          │
│  09:05  assembly_tick_begin                     +1s          │
│  09:05  assembly_tick_merged (42ms)             +0s   [A5]   │
│  TOTAL lead time:           3m 8s                       [A6] │
├──────────────────────────────────────────────────────────────┤
│  Heat rows (from worklog):                                   │
│    903  impl  🟢 0.8  "Check #10: stale queue-push ghosts"   │
└──────────────────────────────────────────────────────────────┘
```

Scope toggle: show all attempts (C1) for this task when retry-count > 1,
coloured by outcome (merged=green, rejected=red, ghost=yellow).

### 2.6 Panel 4 — Persona Heatmap

Matrix: rows = forges, cols = stages, cell = heat count + mean value colour.

```
┌──────────────────────────────────────────────────────────┐
│ HEATMAP             research  plan  impl  test  edit  mkt│
│ forge-quench              12    8   142    51    72   28 │
│                         0.74 0.81  0.79  0.73  0.71 0.77 │
│ forge-temper               9    6    88    42    68   24 │
│                         0.70 0.85  0.77  0.70  0.72 0.74 │
│ forge-anneal               2    1    14     6     8    3 │
│                         0.78 0.80  0.81  0.75  0.74 0.80 │
│ legacy (pre-t-409)        25   19    70    41    38   41 │
│                         0.69  —    0.72  0.68  0.70 0.73 │
└──────────────────────────────────────────────────────────┘
```

Cells: E1 count top, E2 mean value bottom. Colour-ramp green→red on value.
"legacy" row bundles pre-t-409 rows (Gap H.1); tooltip explains.
Hover cell → tooltip with signal mix (E3) and rejection share (E4).

### 2.7 Panel 5 — Issues

Tabbed bucket view, each tab a clickable list that routes to Panel 3.

```
┌──────────────────────────────────────────────────────────┐
│ ISSUES  [Ghosts 0]  [Thrash 2]  [Repeat-tests 1]         │
│         [Stalls 0]  [Orphans 0]  [Rejections 6]          │
├──────────────────────────────────────────────────────────┤
│ Tab: Thrash ≥3 retries                   (C4)            │
│  t-401  4 attempts · 2 rejections · now merged           │
│  t-429  3 attempts · 1 rejection  · in-flight (temper)   │
└──────────────────────────────────────────────────────────┘
```

Tabs and metric sources:
- **Ghosts** — B4 (submitted with no merge/reject).
- **Thrash** — C4 (≥3 forge_started or ≥2 rejections).
- **Repeat-tests** — C9 (same pytest node-id failed ≥2 times).
- **Stalls** — B10 (push_ok with no tick_merged follow-up).
- **Orphans** — B13 (in_progress with no forge_started in window + forge idle).
- **Rejections** — B1 + B2 combined: list of `assembly_tick_rejected` with
  classified reason, forge, task.

Each entry is clickable (→ Panel 3) and dismissable (local UI state only;
no write to the record).

### 2.8 API endpoints to add

All under `/api/project/{project_name}/ops`:

| Method | Path | Returns |
|---|---|---|
| GET | `/ops` | L2 snapshot (current heat). Equivalent to `smithy report --json`. |
| GET | `/ops?at_heat=N` | Same, replayed at heat N. Internal call to `smithy report --at-heat N --json`. |
| GET | `/ops/stream` | SSE tail of rig-events.jsonl + new worklog rows. One event per file line. |
| GET | `/ops/task/{task_id}` | Panel 3 drill-down payload: task life + heat rows + git refs. |
| GET | `/ops/issues/{bucket}` | Panel 5 bucket list (`bucket ∈ ghosts|thrash|repeat-tests|stalls|orphans|rejections`). |

No new state, no writes. All endpoints are pure-read and deterministic for a
given `at_heat`.

### 2.9 Wireframe deferred decisions

- Replay scrubber granularity: per-heat vs. per-hour. Recommendation: per-heat,
  snap-to on drag.
- Rig strip status-dot colour: colour-blind palette (already chosen for existing Bellows pages — reuse).
- Dark mode: reuse the project-wide base.html theme; no panel-specific work.

---

## 3. L2 — Time-Series JSON Snapshot Schema

### 3.1 Intent

A per-heat JSON record, appended to `l2-snapshots.jsonl` at the main repo root,
capturing every metric in the R1 inventory as a single flat dict. Drop-in
pandas: `pd.read_json(path, lines=True)`. Purpose: offline regression
analysis, charting, and Marshal's longer-horizon decisions.

**Writer:** `smithy end-heat` emits one row on each heat close. Idempotent:
re-running at the same heat overwrites the previous row for that heat
(keyed by `heat`). Optionally emit on `smithy patrol --fix` as a snapshot.

### 3.2 Top-level schema (v1)

```jsonc
{
  "schema_version": "ini-019/l2/v1",
  "heat": 904,
  "generated_at": "2026-04-18T09:14:22Z",
  "window": {                      // what window this snapshot summarises
    "from_heat": 1,                // lifetime by default
    "to_heat": 904
  },
  "budget": {                      // F4, F5
    "used": 892,
    "total": 1104,
    "pct": 0.808,
    "overall_progress": 0.74
  },
  "stages": {                      // F1-F3 + A7-A9
    "research":       { "heats": 48,  "value_ema": 0.71, "integral": -0.12,
                        "share": 0.053, "target_share": 0.07,  "drift": -0.017 },
    "implementation": { "heats": 314, "value_ema": 0.74, "integral":  0.08,
                        "share": 0.347, "target_share": 0.38,  "drift": -0.033 },
    "planning":       { "heats": 34,  "value_ema": 0.72, "integral":  0.01,
                        "share": 0.038, "target_share": 0.0,   "drift":  0.038 },
    "testing":        { "heats": 140, "value_ema": 0.73, "integral":  0.02,
                        "share": 0.155, "target_share": 0.15,  "drift":  0.005 },
    "editing":        { "heats": 186, "value_ema": 0.72, "integral": -0.04,
                        "share": 0.205, "target_share": 0.22,  "drift": -0.020 },
    "marketing":      { "heats": 96,  "value_ema": 0.77, "integral":  0.03,
                        "share": 0.106, "target_share": 0.08,  "drift":  0.026 }
  },
  "forges": [                      // A10, A11 (aggregated), E1-E6
    {
      "id": "forge-quench",
      "heats_total": 353,
      "heats_window": 42,
      "idle_pct": 0.12,
      "current_task": "t-437",
      "current_heat": 903,
      "last_heartbeat_age_s": 12,
      "by_stage": {                // E1, E2, E3
        "research":       { "heats": 12, "mean_value": 0.74,
                            "signals": { "green": 10, "yellow": 2, "red": 0, "reject": 0 } },
        "implementation": { "heats": 142, "mean_value": 0.79,
                            "signals": { "green": 130, "yellow": 9, "red": 3, "reject": 0 } }
        /* … one key per stage … */
      },
      "rejection_share": 0.03      // E4
    }
    /* … one obj per forge, plus {"id":"legacy", …} bucket for pre-t-409 rows … */
  ],
  "initiatives": [                 // D1-D6
    {
      "id": "ini-019",
      "title": "Forge Observability",
      "budget_cap": 25,
      "heats_used": 1,
      "pct": 0.04,
      "cycle_time_median_s": null,
      "success_rate": 1.0,
      "tasks_in_flight": 2,
      "tasks_total": 5,
      "thrash_count": 0,
      "parallelism_declared": "parallel",
      "parallelism_actual_max": 1
    }
    /* … one per initiative, plus {"id":"unknown", …} for pre-backfill tasks … */
  ],
  "lifecycle": {                   // A3-A6 distributions, in seconds
    "queue_wait": { "p50": 3.1, "p90": 47.0, "p99": 312.0, "n": 812 },
    "in_flight":  { "p50": 245, "p90": 394, "p99": 612,    "n": 812 },
    "merge_latency_ms": { "p50": 38, "p90": 82, "p99": 180, "n": 784 },
    "lead_time_s": { "p50": 260, "p90": 450, "p99": 900,    "n": 784 }
  },
  "issues": {                      // B-series + C-series
    "ghost_submits":    { "count": 0, "task_ids": [] },                           // B4
    "thrash":           { "count": 2, "task_ids": ["t-401","t-429"] },            // C4
    "repeat_tests":     { "count": 1,
                          "nodes": [{"node":"test_marshal_forge_flow::test_idle","hits":2}] }, // C9
    "stalls":           { "count": 0, "task_ids": [] },                           // B10
    "orphans_reaped":   { "count": 2, "task_ids": ["t-412","t-418"] },            // B13 + patrol
    "rejections":       {                                                         // B1, B2
      "total": 6,
      "by_forge": { "forge-quench": 2, "forge-temper": 3, "forge-anneal": 1 },
      "by_reason": { "rebase-conflict": 4, "tests-failed": 2, "no-commits": 0,
                     "non-ff": 0, "other": 0 }
    },
    "partial":          { "count": 5, "task_ids": ["t-…"] },                      // B6
    "zero_value_heats": { "count": 3, "heat_ids": [812,843,871] }                 // B14
  },
  "queue": {
    "depth_current": 3,
    "push_count_window": 42,
    "pop_count_window": 40,
    "set_events_window": 8                                                        // A14
  },
  "thrash_detail": [                 // C1-C8, per task
    {
      "task_id": "t-429", "attempts": 3, "rejections": 1, "requeues": 2,
      "forges": ["forge-quench","forge-temper"],
      "stages": ["implementation","testing","implementation"],
      "time_to_green_s": null        // still open
    }
  ],
  "gaps": {                          // H-series: explicit blind-spots in this snapshot
    "legacy_forge_rows": 743,
    "unbacked_initiatives": 209,
    "tool_activity_missing": true,
    "human_steering_blind": true
  }
}
```

### 3.3 Schema versioning and stability

- `schema_version` is a string `ini-019/l2/v<N>`. Any **field rename**, **field
  removal**, or **semantic change** bumps N. Additive changes (new field,
  new issue bucket) do not bump N; consumers tolerate extras.
- A parallel `l2-snapshots.schema.json` (JSON Schema Draft 2020-12) is
  committed alongside the writer; tests validate every emitted row against it.
- Old snapshots are not rewritten when the schema bumps. Readers dispatch on
  `schema_version` and apply migrations in memory.

### 3.4 Storage and retention

- **Path:** `l2-snapshots.jsonl` (main repo root; JSONL append-only).
- **Rotation:** none yet — at 1 row per heat and ~3 KB per row, 10 000 heats
  ≈ 30 MB. Reassess at 50 MB.
- **Index:** `heat` is monotonic ⇒ binary-search friendly; `smithy report
  --at-heat N` loads only the matching row.
- **Git:** committed on every `end-heat` (already the pattern for state.json);
  `[stage] t-XXX: …` commit carries the snapshot.

### 3.5 L2-specific replay

`smithy report --at-heat N --json` is the authoritative writer; reading
`l2-snapshots.jsonl[N]` is the *fast path*. They must match modulo
`generated_at`. A regression test asserts equivalence on a frozen fixture.

### 3.6 Consumers (day 1)

- `smithy report` — reads current row for live, or replays via
  `--at-heat`.
- Bellows Forge Ops — `/api/project/{name}/ops` returns the current row;
  `/api/project/{name}/ops?at_heat=N` returns the archived row.
- Poker (ini-017) — pulls `issues.thrash.task_ids` and `forges[].idle_pct`
  to inform task ranking.

---

## 4. Implementation Breakdown (proposed tasks)

These are proposals for Marshal to prioritise; do not self-assign.

| # | Stage | Brief | Depends on |
|---|---|---|---|
| P1.1 | implementation | `smithy/metrics.py` — pure aggregation module (one function per R1 section). Input: filtered S1/S2/S3 rows + S4 snapshot. Output: the L2 dict (§3.2). | R1 inventory (done, t-444) |
| P1.2 | implementation | `smithy report` CLI wiring — flags per §1.2, calls `metrics.py`, renders §1.3 default / §1.4 `--json` / §1.5 `--tsv`. | P1.1 |
| P1.3 | implementation | L2 writer hook in `end-heat` — append `l2-snapshots.jsonl` row, include in the heat's git commit. | P1.1 |
| P1.4 | testing | `tests/test_report_replay.py` — frozen worklog fixture, `--at-heat N` byte-equals `l2-snapshots.jsonl[N]`. | P1.1, P1.3 |
| P1.5 | implementation | Bellows `/api/project/{name}/ops` + SSE stream. Pure read from `smithy report --json` and rig-events.jsonl tail. | P1.1 |
| P1.6 | implementation | Bellows `/project/{name}/ops` page + `ops.html` template, five panels per §2.3–2.7. | P1.5 |
| P1.7 | testing | Bellows API tests: each endpoint returns L2-compliant JSON; SSE emits line-per-event; replay banner toggles on `?at_heat=`. | P1.5 |
| P1.8 | editing | Commit a JSON Schema (`l2-snapshots.schema.json`) matching §3.2 and add a schema-validation test. | P1.3 |

Ordering: P1.1 must land first — everything else consumes its output. P1.2/P1.3 are parallelisable. P1.5 depends on P1.2 functional parity (or calls the module directly). P1.6 depends on P1.5.

---

## 5. Explicit deferrals / follow-ups

Things the research flagged that the spec does **not** commit to now; each
becomes a separate task if Marshal prioritises it.

1. **`heat_committed` event** (Gap H.8, Open Q §J.2) — would close intra-heat
   cadence blindness. Defer; B12 + `git log` cover the v1 need.
2. **`assembly_tick_rejected.reason` canonicalisation** (Open Q §J.3) — v1
   ships the regex classifier as B2 inside `metrics.py`. If rejection volume
   grows, canonicalise in the emitter later.
3. **Human-steering event capture** (Gap H.4) — git-blame on state.json is
   the v1 fallback; a proper `steering_event` payload would follow.
4. **Legacy (pre-t-409) forge attribution backfill** — not attempted; "legacy"
   bucket stays explicit in heatmap and JSON.
5. **Initiative backfill for pre-t-447 tasks** (Gap H.2) — the spec assumes
   t-445/t-447 land before ini-019 L1 ships; if that slips, the `ini=unknown`
   bucket is authoritative and clearly labelled in every surface.
6. **L2 rotation / compaction** — deferred until file size warrants.
7. **Chart rendering in Bellows** — L2 feed exists; view-layer sparklines
   are a follow-up, not a ship-blocker.

---

## 6. Acceptance criteria (for Anvil / Marshal sign-off on this design)

1. Every metric referenced in §1.3, §2.*, and §3.2 maps to a specific R1
   inventory ID (A1–F5). ✅ (verify by diff with `research/ini-019-metrics-inventory.md`)
2. No surface requires a new write path to `state.json`, `worklog.tsv`,
   `rig-events.jsonl`, or `assembly-log.jsonl`. ✅
3. The `smithy report --at-heat N` replay contract is byte-deterministic
   (modulo `generated_at`). ✅ (P1.4 test)
4. The L2 schema is committed as JSON Schema (P1.8).
5. The Bellows page mounts without touching any existing endpoint — pure
   additive (`/project/{name}/ops` + four API routes).
6. "Legacy" / "unknown" buckets are explicit in every surface where R1 flagged
   a gap (H.1, H.2).

---

**Prepared by:** forge-anneal · heat 823 · planning stage · 2026-04-18
**Reviewed by:** _pending — Anvil / Marshal_
