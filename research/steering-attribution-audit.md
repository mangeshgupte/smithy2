# Steering Attribution Audit — Can We Show Steering-Shifted-Forge?

**Task:** t-337 (research, p2). The v1.8 steerability arc (t-312→t-319) shipped human_priority as a sticky signal and `priority_reason` as a closed-vocabulary field. The question for this audit: given the existing signals (state.json diff + human_priority + priority_reason + worklog), can we reconstruct a chain-of-custody from *human action in Poker* → *task reorder in queue* → *heat logged against that task*? If yes, show the attribution; if no, propose the smallest schema bump that makes it tractable.

This is the "prove my steering worked" audit. It matters because the entire value thesis of v1.8 rests on humans trusting that their pokes change what ships — if we can't audit that, steerability is a faith statement.

---

## Signals available today

| Signal | Location | What it captures | What it misses |
|---|---|---|---|
| `human_priority` | task.human_priority in state.json queue[] | *Current* sticky override value | No history — last-writer-wins, prior values lost |
| `priority_reason` | task.priority_reason | *Why* this priority (closed vocab: recency/poker/stage-balance/blocked-deps-clear) | Vocab conflates reasons (one field for mixed signals) |
| worklog.tsv | per-project flat file | Every heat — stage, task_id, outcome, value, signal, notes | Says *what* ran, not *why this task was picked* |
| Bellows `/diff?n=N` | HEAD vs HEAD~N of state.json | Field-level delta between commits | Only works if state.json is committed per-heat (it is, by convention) |
| git log on state.json | .git/ | Every commit's full diff + commit message | Commit messages are freeform — no structured reason |

## What we *can* already reconstruct

1. **Task-level reorder events.** Diffing two consecutive state.json commits shows `queue[i].human_priority` changes and `priority_reason` changes. If a task's `human_priority` flips from `null` to `0` in a given commit, that commit is a steering event.

2. **Which task ran next after a steering event.** The next worklog entry's `task_id` tells us what Forge picked. If the picked task is the one whose human_priority just changed, that's a direct causal signal.

3. **Temporal adjacency.** Commit timestamps + worklog timestamps give us "poker edit at T, task picked at T+N heats." Short N = tight loop; long N = weak signal.

## What we *cannot* reconstruct

1. **Who edited.** state.json has no author. Poker edits come from the human via a Bellows POST, but the write goes into Forge's project dir via file mutation — no user/session metadata is recorded. We can only say "state changed," not "Mangesh at 11:04 PT pinned t-042."

2. **Prior values of human_priority.** Only the current value lives in state.json. Past values exist in git history but not in a queryable structure — you'd reconstruct by walking `git log -p state.json` and pattern-matching.

3. **The causal counterfactual.** "Would Forge have picked t-042 anyway, even without the pin?" We don't log the scheduler's *alternatives considered*. Absent a before/after simulation, we can only observe "pin happened, task ran" — not "pin *caused* the task to run."

4. **Defer / undefer / delete events.** t-333 added these as lifecycle actions. Defer is captured in `status='deferred'` but no timestamp. Delete appends a worklog audit row (good). Undefer = silent.

## Feasibility verdict

**Partial yes.** We can build an Attribution Timeline UI *today* that shows:
- Every state.json commit where a task's `human_priority` or `priority_reason` changed (from git log -p).
- The worklog entry that ran next for the affected task_id.
- Elapsed heats between steering event and ship.

This answers ~70% of the "did my steering work?" question. The missing 30% is the counterfactual, the author identity, and the prior-value history — all of which require schema work to close cleanly.

**Without schema changes, the audit is usable but noisy.** Git-log-based reconstruction is CPU-cheap but textually fragile (any future field rename breaks the regex). Walking 800 commits to build a history takes <1s today but scales O(heats).

---

## Schema proposal — minimal viable change

If we want a canonical, queryable attribution record without brittle git-log parsing, the smallest durable bump is a new append-only file:

**New file:** `steering.log` at project root.

```tsv
timestamp	heat_when_changed	actor	task_id	field	before	after	source
2026-04-12T17:22:33Z	742	bellows-poker	t-325	human_priority	null	0	poker-drawer
2026-04-12T17:25:01Z	742	bellows-poker	t-325	priority_reason	(stage-balance)	you:p0	poker-drawer
2026-04-12T18:04:19Z	744	bellows-upcoming	t-328	upcoming_pinned	null	rank=1	upcoming-drawer
2026-04-12T19:30:00Z	749	bellows-poker	t-333	status	pending	deferred	poker-drawer-defer
```

**Fields:**
- `timestamp`: ISO-8601 UTC of the mutation.
- `heat_when_changed`: current `budget.used` at mutation time (anchors to Forge's progress timeline).
- `actor`: one of `bellows-poker`, `bellows-upcoming`, `bellows-intent`, `bellows-timeline`, `cli`, `forge` (Forge's own state mutations distinguished from steering).
- `task_id`: task affected, or `-` for initiative/theme edits (future extension).
- `field`: which field changed. For unpin, `upcoming_pinned` with after=null.
- `before` / `after`: JSON-encoded if complex, literal otherwise.
- `source`: UI component that made the edit, for fine-grained attribution.

**Write path:** every POST mutation endpoint in Bellows + Poker + Intent UIs appends one row per field touched. Wrap in a tiny helper `_log_steering(actor, task_id, field, before, after, source)`. Additive — no existing code needs to change its *state* mutation logic, only add a logging line.

**No schema bump to state.json.** Matches v1.8 discipline ("don't schema-bump unless forced"). steering.log is a *derivative* — loss of it doesn't corrupt state, only forfeits future attribution.

**Read path:** new Bellows endpoint `GET /api/project/{name}/steering-log?task_id=&since=` returns filtered rows as JSON. Timeline UI gets a new "Steering events" lane interleaved with worklog heats.

---

## What the Timeline UI would show

```
heat  stage           task     outcome   steering trigger
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
742   [editing]       t-325    🟢 0.85   ← poker: human_priority null→0 at h741
743   [impl]          t-325    🟢 0.9    ← continuing t-325
744   [testing]       t-328    🟢 0.8    ← poker: stage-balance (autoroute, no steering)
749   [impl]          t-333    🟢 0.85   ← poker: human_priority null→0 at h748
```

The critical column is the rightmost: every heat is annotated with its steering trigger (if any). Heats with no trigger ran off the allocator's stage-balance logic — which is the *absence* of steering, and equally important to see.

## Value thesis (per retro format)

**If we ship steering.log + Timeline attribution lane:** the human gets a weekly retro artifact — "here's what you steered toward, here's what shipped." That retro is the single best feedback loop for calibrating whether Poker edits are helping or hurting. Without it, humans use steering blind — they pin things and hope. *Low risk, medium diff (touches every mutation POST), high strategic value because it makes the steerability thesis falsifiable.*

**If we defer it:** attribution stays reconstructible ad-hoc via `git log -p state.json`, which is fine for one-off audits but falls apart for "what did I do this week?" dashboards. Attribution becomes a per-query archaeology project instead of a first-class surface. *Risk tier: the user can't prove to themselves that steering is working — confidence in v1.8 erodes over time without observable evidence.*

---

## Impl candidates (retro format — value thesis per)

### t-338-candidate — `steering.log` append-only file + shared logger helper (impl, p1)
Add a `log_steering(actor, task_id, field, before, after, source)` helper to a small shared utility module importable from all steering UIs + smithy CLI. Wire it into every POST mutation endpoint (Poker human-priority/defer/undefer/delete, Upcoming pin/unpin/reorder, Intent edits). File format = TSV matching the schema above. Unit tests per UI + one integration test that mutates via each endpoint and asserts a row landed.

**Value thesis:** This is the foundation. Without it, everything else is git-archaeology. One small helper, wired in ~8 places, unlocks the entire attribution pipeline.

### t-339-candidate — `GET /api/project/{name}/steering-log` endpoint (impl, p2)
Bellows endpoint that parses steering.log, optionally filtered by task_id / since / actor. Returns structured rows sortable by timestamp. Tests: no file (empty list), filters work, malformed rows skipped-with-warning not failed.

**Value thesis:** Exposes the raw attribution stream. Enables the UI without committing to a UI design. Future tools (weekly retro, agent self-audit) can all consume this.

### t-340-candidate — Timeline steering-trigger annotation (impl, p2)
Extend Timeline's heat rows with a "steering trigger" column. For each heat, look up the latest steering.log event affecting its `task_id` *before* the heat started. Render as "← poker: human_priority null→0" or "← (no steering)" inline. Small UI diff, large attribution clarity.

**Value thesis:** Closes the loop visually. The human sees "I edited this; here's what shipped as a result." Single-glance retro artifact.

### t-341-candidate — Weekly steering-retro export (research → marketing, p3)
Given steering.log + worklog, generate a weekly markdown summary: pins made, tasks shipped post-pin, average lag (heats) from pin → ship, heats with no steering trigger (pure allocator). Would land as a simple `smithy steering-retro --since=7d` CLI that emits markdown to stdout.

**Value thesis:** Turns attribution from a dashboard into a habit. The doc itself becomes a weekly check-in artifact — something the human reads on Monday to decide what to steer differently.

### t-342-candidate — Actor identity hook (impl, p3)
Today all Bellows POST mutations log `actor=bellows-<ui>`. Add optional `X-Actor` request header support so external tools (scripts, agents) can tag themselves. Default to the UI actor if header absent.

**Value thesis:** Future-proofs the log for multi-user / multi-agent scenarios. Low-urgency today (single-user) but near-zero cost to land while the logging code is fresh.

---

## Non-goals

- **No counterfactual simulation.** "Would Forge have picked this anyway?" requires running the scheduler in a what-if mode. Valuable but a different project.
- **No UI for editing steering.log.** Append-only is a feature, not a limitation — prevents revisionist edits.
- **No cross-project attribution aggregation.** Per-project log is enough to start; Bellows can aggregate views later without schema changes.
- **No replacement of git history.** steering.log complements git; it doesn't replace the full commit history that backs state.json.

---

## Recommendation summary

**Feasibility:** yes, partially today via git-log reconstruction, fully with a new `steering.log` append-only file.

**Ship order:** t-338 (steering.log + helper) → t-339 (read endpoint) → t-340 (Timeline annotation) → t-341 (weekly retro CLI) → t-342 (actor header).

**Schema stance:** NEW append-only file `steering.log`, NO changes to state.json. One helper function, eight wire-ups, zero existing mutations touched in behavior.

**Blast radius:** Additive only. Missing or corrupt steering.log degrades to "no attribution data" — never corrupts state. Rollback = delete file + revert helper imports.

**Biggest open question:** should the CLI (Forge's own state mutations via `smithy end-heat`, `smithy add-task`) also log to steering.log? Argument for: full picture, Forge's automated changes and human steering in one stream. Argument against: floods the log with routine heat-end writes, swamping the human-driven signal. Recommendation: **yes, log CLI writes too, but with actor=`forge`** so UIs can filter to actor∈(bellows-*, cli) to get just human-origin events.
