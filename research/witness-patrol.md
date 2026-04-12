# Witness-Style Patrol for Stall Recovery

**Task:** t-386 (ini-009, research) · heat 805 · 2026-04-12

## Problem statement

The Forge's nudge-driven loop is self-sustaining until it isn't. The failure
mode we've seen and want to catch:

1. `queue` has pending tasks
2. no task is `in_progress` (no `.forge-checkpoint.json`)
3. Forge has "Waiting for task…" printed but no nudge arrives
4. Marshal has no queued nudges from Forge
5. the worklog's last row is hours old

Neither side is broken — they're each *politely idle*, waiting for a nudge
the other won't send. Today nothing detects this. A human has to notice and
tell Anvil, who tells Marshal, who pushes a task. We want a **Witness**:
something that watches the whole loop from outside, diagnoses stuck-ness, and
escalates.

## 1. Stuck-state detector

Canonical stuck signature (all must hold):

| Predicate | Source |
|---|---|
| `queue` contains ≥1 `status=="pending"` task | `state.json` |
| no task has `status=="in_progress"` | `state.json` |
| `.forge-checkpoint.json` does not exist | filesystem |
| `.smithy-nudge-queue/forge.jsonl` is empty or absent | filesystem |
| `.smithy-nudge-queue/marshal.jsonl` is empty or absent | filesystem |
| worklog's last `timestamp` ≥ N minutes ago | `worklog.tsv` tail |

"All idle" = the union of predicates 2–5 (nobody is working, nobody has been
pinged). "Stale heat" = predicate 6 with N = 30 min (default; tunable).

Edge cases:
- **Empty queue** → not stuck; normal idle. Reporting this as stuck would be
  noise.
- **Budget exhausted** → not stuck; Marshal intentionally stopped queuing.
  Check `budget.used >= budget.total_heats` first and short-circuit.
- **In-flight checkpoint older than N minutes** → different failure (crashed
  mid-heat). Existing patrol already catches "stuck in_progress" (cli.py:1372);
  reuse don't duplicate.

## 2. Role placement: Marshal vs. new Witness

**Recommendation: fold into `smithy patrol --fix` for v1; extract a Witness
role only if activation requirements outgrow patrol's cadence.**

Rationale:
- Patrol is already the "validate state + auto-repair" layer. Adding one more
  check fits the existing mental model exactly.
- A separate Witness agent/persona would need its own tmux window, its own
  CLAUDE.md, its own spawn discipline in Anvil. That's three new moving
  parts for one detector.
- The action policy (self-nudge → force-pop → alert) is all flat-file work —
  no LLM reasoning needed. No justification for a dedicated agent.
- Marshal *already does* the prioritization; forcing Marshal to self-diagnose
  its own inaction is a conflict-of-interest the way "writers grading their
  own work" is. Patrol is neutral; it just checks facts.

When to reconsider: if we want ambient observation every 60s (faster than
any human-triggered patrol), a dedicated Witness daemon becomes necessary.
That's a v2 shift; not today.

## 3. Activation mechanism

**Recommendation: hybrid — piggyback on `end-heat` + human-triggered `patrol --fix`.**

| Mechanism | Pro | Con | Verdict |
|---|---|---|---|
| Cron (external) | Always-on; decoupled | External dependency (violates "no external orchestrator" constraint from identity.md) | ❌ |
| Hook | None — hooks were removed (cli.py:919, t-262) | Dead surface | ❌ |
| Piggyback on `end-heat` | Zero new infra; every heat revalidates | Only fires when something is *not* stuck (heats are running) | ⚠️ partial |
| Piggyback on `queue-pop` | Fires when Forge actively asks | Same blind spot as end-heat | ⚠️ partial |
| Human-triggered via `smithy patrol --fix` | Already exists; run on respawn | Requires human initiative | ✅ backstop |
| Dedicated daemon/Witness agent | Catches pure-idle stall without human | New process discipline | future work |

The piggyback paths catch the **"I just finished and nothing came back"**
variant. The respawn path catches the **"the whole thing has been dead for
hours"** variant. Between them, most stalls are caught.

Implementation: add check 6 to `smithy patrol`. On `--fix`, tier the action
per §4 below. Also wire a lightweight `stuck-check` invocation into
`end-heat`'s post-nudge path so a just-completed heat can detect that its
nudge was swallowed.

## 4. Actions policy (tiered)

On detected stuck-state, escalate in tiers; move up a tier only if the prior
tier has been tried and cooled (§5):

1. **Self-nudge.** Append a synthetic message to the stuck-side's nudge queue
   (`marshal.jsonl` or `forge.jsonl`) saying `stuck_detected: please act`.
   Equivalent to the cycle that *should* have happened — just triggered
   from outside. No state mutation.
2. **Force-pop.** If Forge is idle and queue has tasks, synthesize a
   `queue-pop` event: write an entry to `forge.jsonl` that includes the
   top-scheduler task id, so Forge's drain-nudges picks it up directly
   without needing Marshal to `queue-push` first. Marshal hears about it
   post-hoc via the next `end-heat` nudge.
3. **Alert human.** Append a bold line to `feedback.md` and/or broadcast
   via SendMessage from Marshal to team-lead: `"Loop stalled for N min;
   patrol escalated to tier 3; human review."` This is the last resort —
   the loop is supposed to be self-sustaining.

Hard no-go: don't silently reset state (no touching `budget.used`, no
deleting tasks). Tiered escalation, every action logged to `steering.log`.

## 5. Livelock guard

Failure to avoid: a broken nudge queue means tier-1 self-nudge runs on every
patrol invocation, sending 50 nudges in an hour and burning context.

Per-target cooldown, stored in `state.json → patrol.last_witness_action`:

```jsonc
"patrol": {
  "last_witness_action": {
    "forge": {"tier": 1, "ts": "2026-04-12T14:03:17Z"},
    "marshal": {"tier": 1, "ts": "2026-04-12T14:03:17Z"}
  }
}
```

Rules:
- Tier N can only fire if `now - last_ts > cooldown[N]`.
- Default cooldowns: t1 = 5 min, t2 = 15 min, t3 = 60 min.
- Tier resets to 1 after a successful heat is logged (confirmed unstuck).
- Two consecutive tier-3 alerts without an intervening successful heat →
  stop escalating; set `patrol.witness_muted = true`; require human to clear.

## 6. Testing

Synthetic stall fixture:

```python
def test_witness_detects_stall(tmp_project):
    # Arrange: a pending task, no checkpoint, empty nudge queues, an
    # old worklog tail. Stock stall.
    seed_state(tmp_project, queue=[pending_task("t-1")])
    write_worklog(tmp_project, last_ts=minutes_ago(45))
    # Act
    result = patrol(tmp_project, fix=True)
    # Assert: witness fired tier-1, nudge appeared in forge queue.
    assert result["witness"]["stuck"] is True
    assert result["witness"]["tier_fired"] == 1
    assert read_nudge_queue(tmp_project, "forge") != []
```

Additional fixtures:
- Budget-exhausted → not stuck.
- Empty queue → not stuck.
- Fresh worklog tail → not stuck.
- Stuck + cooldown active → skipped, reported.
- Stuck + 3 consecutive tier-3 alerts → muted.

## 3–5 implementation candidates (retro-format with value theses)

### C1 — Add stuck-state detector to `smithy patrol` (value: **high**)

**Thesis:** This is the core win. Without a detector, nothing else matters.
All predicates are already computable from flat files we read anyway. Single
new function `_check_stall(project_dir)` added to `smithy/cli.py` patrol
block; returns `{stuck: bool, reasons: list[str]}`. No state mutation in
this candidate — report-only — so rollout is safe.

**Scope:** ~1 heat. Implementation + unit test per §6 table.

### C2 — Tier-1 self-nudge action on `--fix` (value: **high**)

**Thesis:** Detection without action is just an alarm nobody hears. Tier-1
is the smallest safe action (just writes to the nudge queue, which is a file
both sides are designed to tolerate). Requires §5's cooldown to be live.

**Scope:** ~1 heat. Adds `_witness_self_nudge(persona)` helper; updates
`state.patrol.last_witness_action`; logs to steering.log.

### C3 — Piggyback patrol invocation in `end-heat` (value: **medium**)

**Thesis:** Most stalls are triggered by a dropped nudge *right after* a
heat completes (the moment when both sides expect the other to act). Running
the detector in the `end-heat` tail — only when `--no-nudge` was not passed
and the nudge queue check fails — catches the loop's most common failure
point without adding cadence.

**Scope:** ~0.5 heat; requires C1 landed. Just one call site addition.

### C4 — Tier-2 force-pop (value: **medium**, risk: **higher**)

**Thesis:** When tier-1 nudges don't unstick things, the issue is Marshal
isn't pushing. Force-pop bypasses Marshal by writing the top-scheduler task
directly to Forge's queue. Valuable, but touches multiple files and needs
careful rollback if the next end-heat reports value=0 (misqueued work).

**Scope:** ~1 heat; defer until C1-C3 ship and we see real stalls hitting
tier-1 repeatedly.

### C5 — Livelock/cooldown tracking in state.json (value: **high**, prereq)

**Thesis:** Without §5's cooldown, C2 is an infinite-nudge footgun. This is
a prerequisite for C2; scope it as its own candidate so the schema addition
is reviewable in isolation.

**Scope:** ~0.5 heat. Adds `state.patrol.last_witness_action`, patrol
helpers `_witness_can_fire(persona, tier)`, `_witness_record(persona, tier)`.
Schema-additive, no migration.

## Recommended shipping order

C1 → C5 → C2 → C3 → (C4 deferred, evaluate after 1 week of C1-C3 in prod).

Total: 3 implementation heats minimum (C1, C5, C2/C3 combined) to get a
live, safe tier-1 witness covering the high-value stall case.

## Open questions for Anvil

1. **Alert channel for tier-3.** Write to feedback.md, SendMessage to
   team-lead, or both? Feedback.md persists across sessions; SendMessage is
   live. Leaning toward both; Anvil's call.
2. **Should tier-3 halt the loop?** (i.e., set a global `halt` flag). My
   instinct is no — keep Forge/Marshal running in case tier-2 eventually
   works — but if Anvil wants a hard stop, this is the hook.
3. **Stale-heat threshold N.** Proposed 30 min for tier-1 trigger. Could be
   as low as 10 min or as high as 2 hrs depending on how long a normal heat
   can legitimately take (some research heats run ~8 min).
