# ini-021 R1 — Context Reset baseline

**Task:** t-451 · heat 978 · 2026-04-18 · forge-anneal

**Hypothesis (from ini-021):** Forge session context between tasks is
not load-bearing. Every durable output already persists on disk (code,
state, worklog, memory, checkpoint). Cross-task context accumulation
causes pollution and unnecessary token burn.

**R1 scope:** coarse baseline from existing records + instrumentation
proposal for the telemetry ini-021 R2/R3 will need. Depends on ini-019
landing clean token telemetry to reach full precision; what follows is
what we can measure *now*.

## 1. What we can measure today

No token-level telemetry exists. `rig-events.jsonl` is lifecycle-only
(16 event types, none context-related — confirmed against the ini-019
R1 inventory at `research/ini-019-metrics-inventory.md`). No transcript
archive is collected. Scrollback accumulation is visible only through
proxies:

| Proxy | What it approximates | Caveat |
|---|---|---|
| Consecutive heats in one Forge session (no `/clear`) | Accumulated context growth | No token count; scrollback ≠ tokens 1:1 |
| Worklog notes length (all time) | Output the model emitted per heat | Downstream-only; doesn't capture input scrollback |
| Cross-task id mentions in notes | Prior-task context bleeding into current-task output | Proxy for attention-span pollution |
| Retry counts on same task/forge | Work Assembly bounced (may correlate with context confusion) | Confounded by test flakes + stale-install (t-460/t-461) |
| Session duration (gap >1h = new session) | Longest uninterrupted context window | Gap threshold chosen arbitrarily |

## 2. Survey — last 60 heats (worklog rows 840-899, 2026-04-18)

### 2.1 Outcome mix by Forge

| Forge | Heats | submitted | merged | rejected | partial | blocked |
|---|---|---|---|---|---|---|
| forge-anneal | 15 | 10 | 0 | 0 | 1 | 4 |
| forge-quench | 34 | 5 | 9 | 14 | 3 | 3 |
| forge-temper | 8 | 7 | 0 | 0 | 1 | 0 |

**Methodological caveat (critical):** `merged` and `rejected` rows are
written by `_do_assembly_merge` / `_do_assembly_reject`
(`cli.py:924-1010`). The `forge_id` column for these rows reflects the
*Assembly pane's* detected cwd, which is the MAIN repo root → resolves
to `primary_forge_id(state)` = **forge-quench**. So forge-quench's 14
"rejects" are an attribution artifact: most describe Assembly rejecting
branches authored by other Forges. The retry narrative in §2.3 carries
the real authorship.

### 2.2 Reject rate vs session length (all time, all forges)

| Forge | Session | Heats | Rejects | Reject % |
|---|---|---|---|---|
| forge-anneal | 5 (last) | 18 | 0 | 0.0% |
| forge-anneal | 1-4 | ≤5 | 0 | 0.0% |
| forge-quench | 2 | 40 | 11 | 27.5% |
| forge-quench | 3 | 10 | 2 | 20.0% |
| forge-quench | 4 | 7 | 3 | 42.9% |
| forge-quench | 5 (last) | 43 | 14 | 32.6% |
| forge-temper | 5 (last) | 13 | 0 | 0.0% |
| forge-temper | 1-4 | ≤4 | 0 | 0.0% |

**Read with the caveat above in mind** — the reject rate on
forge-quench mostly reflects Assembly's output attribution, not
forge-quench's own context pollution. But the *session length* signal
is real: only forge-quench has crossed 40 heats in a single session,
and that's also where Assembly (sharing the forge-quench cwd)
accumulates its biggest transcripts. Forge-anneal at 18 heats and
forge-temper at 13 show zero rejects.

### 2.3 Retry cascades (same task, same forge, ≥2 starts)

| Forge | Task | Starts |
|---|---|---|
| forge-quench | t-431 | 5 |
| forge-quench | t-456 | 3 |
| forge-quench | t-457 | 3 |
| forge-anneal | t-460 | 3 |
| forge-anneal | t-461 | 3 |
| forge-anneal | t-463 | 3 |
| forge-quench | t-441 | 2 |
| forge-quench | t-448 | 2 |
| forge-temper | t-448 | 2 |
| forge-anneal | t-449 | 2 |

**t-431 narrative** (forge-quench, single contiguous session):
submitted → rejected (test) → rework → rejected (same test) →
cherry-pick retry → rejected × 2 → abandon per human steer → partial
→ submitted (retry) → blocked (human steer) → submitted → rejected
(MEMORY.md conflict) → final submit → rejected (test). Five end-heats
on the same task_id in one pane. The rejection reasons drift: early
rejects are the real failure, later rejects introduce *new* problems
(severe MEMORY.md conflict — a classic context-artifact collision
only possible because the Forge kept editing its persona memory
across retries). This is the cleanest candidate evidence for
**cross-task-within-same-task** context accumulation leading to
collateral damage. Confounded by the t-458 memory-subdir fix landing
mid-stream.

### 2.4 Cross-task mentions in notes

25 of 60 heats (42%) reference a task id other than their own. Sample:

- `forge-temper own=t-448 mentions=t-450, t-457, t-460` — a research
  heat on t-448 that discusses three other tasks in its notes.
- `forge-anneal own=t-449 mentions=t-438, t-442, t-456` — research
  heat with deliberate cross-task references (inventory doc). Legit.
- `forge-anneal own=t-463 mentions=t-464` — preemption note; legit.

Mentions are often legitimate (research cross-references, preemption
notes), so mention-count alone is a **weak** signal. It's a proxy
for the model *knowing about* other tasks, not proof the context is
hurting outcomes. Only 3 of 17 rejects in the window followed a
cross-mention heat — small n, no strong signal.

### 2.5 Stale-branch / dirty-rebase signals (all time)

Pattern matches in all 900 worklog notes:

| Pattern | Hits |
|---|---|
| `rebase error` | 3 |
| `unstaged changes` | 4 |
| `severe conflict` | 4 |
| `stale (install|binary|worktree|bind)` | 1 |
| `wrong branch` / `on main` / `on scratch` | 5 |
| `/scratch\b` | 2 |

These are all symptomatic of worktree/branch identity drift — a
category ini-021 cites ("stale branch name in prompt"). They account
for ~19 rejections in Assembly's log historically. Low absolute
count, but every one wastes a heat, and the t-464 fix
(`rebase_forge_branch` unconditional stash) exists because exactly
this symptom class blocked the rig on 2026-04-18.

## 3. Symptoms in rig-events (lifecycle side)

`rig-events.jsonl` (505 rows) has zero context-size fields. Events
usable as indirect signals:

- `forge_started` and `forge_ended_*` span cover in-flight duration,
  but not scrollback.
- `queue_push` and `queue_pop` intervals hint at Forge idle time,
  which is when context *could* be cleared.
- `assembly_tick_rejected` has `reason` — 21 in the window, but
  attributed to Assembly not to the authoring Forge's
  context-at-submit-time.

No existing event tells us "Forge X was at approximately N tokens
when it submitted task Y". This is the measurement gap ini-021 R2+
must close before the auto-clear A/B can be evaluated honestly.

## 4. Proposed instrumentation — minimum for A/B evaluability

Goal: attach a coarse context-pressure reading to every `end-heat`
so the A/B plan (one Forge auto-clears on clean end-heat, one
doesn't, ~20 heats each) has a measurable y-axis.

### 4.1 Fields to capture

At `end-heat` time, in the Forge's pane, emit a new rig-event
`forge_context_snapshot` with:

| Field | Source (coarse) | Source (clean, ini-019) |
|---|---|---|
| `heat`, `task_id`, `forge_id`, `ts` | existing end-heat args | same |
| `scrollback_lines` | `wc -l` of Claude Code transcript file (cwd resolved via `CLAUDE_CODE_TRANSCRIPT_PATH` if exposed, else sessions dir) | same |
| `char_count` | `wc -c` of same | same |
| `token_estimate` | `char_count ÷ 4` heuristic | Anthropic API usage count from Claude Code's own records |
| `minutes_since_session_start` | env-provided `FORGE_SESSION_STARTED_AT` or heat-count × mean-heat-duration | same |
| `heats_since_clear` | counter persisted to `.forge-checkpoint-<id>.json`, reset on `/clear` | same |
| `auto_compact_fired` | scan transcript for `compact` sentinel; else `null` | Claude Code hook on compact event |
| `cross_task_mentions_in_notes` | regex `t-\d{3}` count − 1 if own task id present | same |

All coarse fields are self-measurable by `smithy end-heat` in this
heat's worktree today — no hook dependency.

### 4.2 Landing shape

- New helper `_snapshot_context(root, forge_id)` in `cli.py`, called
  just before the existing `_emit_rig_event(root, f"forge_ended_...")`
  call (`cli.py:730-732`). Emits `forge_context_snapshot` either as a
  separate JSONL row or nested under the existing `forge_ended_*`
  fields. R2 decides; nesting is denser, separate row is easier to
  replay-filter.
- One env var to turn it off for Assembly's own pane (which doesn't
  go through end-heat but should still report heartbeat-time
  snapshots — a deferred nice-to-have).
- Zero schema changes to worklog.tsv — keep ini-019 R2's schema
  stable; context telemetry is a rig-events-only stream.

### 4.3 Not in scope for R1

- Per-task token attribution (would need Claude Code transcript
  parsing with message-boundary detection — ini-019 territory).
- Auto-compact detection (needs Claude Code hook coverage, not yet
  plumbed).
- Anthropic API usage reconciliation (parent-session accounting).

## 5. Baseline numbers to beat (A/B y-axis candidates)

For R2's evaluation plan, here are the headline numbers to track
delta against, pre-intervention:

| Metric | Baseline (last 60 heats) | Source |
|---|---|---|
| Reject rate (overall) | 28% (17/60) | §2.1 |
| Retry cascade depth (max) | 5 (t-431) | §2.3 |
| Heats with cross-task mentions | 42% (25/60) | §2.4 |
| Stale-branch / wrong-branch symptom rows (all time) | ≥11 | §2.5 |
| Longest uninterrupted session | 43 heats | §2.2 |
| Sessions with 0 rejects (when ≤13 heats) | all 7 short sessions | §2.2 |

The cleanest pre/post contrast will be **reject rate × median
session length**: ini-021's claim is that *reset cuts both
axes*. If the A/B Forge with auto-clear runs at similar value
scores and a lower reject rate, that's the win condition.

## 6. What changes when ini-019 lands

ini-019 R2 is working on backfill + token-level telemetry; once
live, the coarse fields in §4.1 should be replaced by:

- `tokens_in_context` (clean, from Claude Code records) — replaces
  `token_estimate`.
- `auto_compact_events` (counter, not sentinel scan) — replaces the
  null fallback.
- `per-message token breakdown` — enables "how much of the
  prior-task context is still live at task-submit time" which
  directly tests the ini-021 hypothesis.

R2 of ini-021 should commit to §4's coarse fields **plus** a
migration path that swaps them out for ini-019's clean counterparts
when available (field name compatibility, so dashboards don't have
to re-point).

## 7. Open questions for R2 planning

1. **Granularity** — one snapshot per end-heat, or one per
   significant transition (start-heat / end-heat / stuck-poll)?
2. **Transcript location** — is there a stable path for the Claude
   Code transcript, or does it require environment plumbing that's
   out of scope for this initiative?
3. **A/B assignment** — forge-anneal is the natural "auto-clear"
   arm since it has the shortest sessions today; forge-quench is
   the natural "control" arm but doubles as Assembly's pane, which
   complicates measurement. Third arm with forge-temper?
4. **Clear trigger definition** — "clean end-heat" per ini-021
   description includes `complete` and `submitted` but NOT
   `partial` / `blocked` / `rejected`. Confirm: is a
   `submitted→rejected` sequence treated as clean-clear-then-new
   context, or does the rejection-nudge that comes back during
   idle preserve the old context? The latter needs a second clear
   hook on nudge receipt.
5. **Persona re-load** — if we clear, does persona CLAUDE.md +
   IDENTITY.md + memory get re-read reliably, or do we need an
   explicit re-prime step?

## 8. Next step

R2 (new task, not yet created) should land the §4.2 instrumentation,
run 20 heats per arm with it in place, and produce
`research/ini-021-ab-results.md`. Until then, the coarse survey in
§2-3 is the signal we have. The cleanest qualitative finding is
§2.3's t-431 retry cascade — five starts on the same task in one
session, with later rejects introducing new collateral problems
(MEMORY.md conflict). That's the strongest existing evidence the
ini-021 hypothesis is worth testing.
