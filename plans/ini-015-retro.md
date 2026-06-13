# ini-015: Marshal agent — Retrospective

**Closed:** 2026-04-19 *(pending `smithy complete-initiative`)*
**Heat cost:** 28 heats (budgeted 25)
**Task count:** 32 complete / 0 abandoned *(rejects rolled into merged retries, see appendix)*
**Successor:** none — future Marshal maintenance work files as new initiatives when substantial (per ini-025 locked decisions)
**Author:** Anvil (prose, 2026-04-19) + `<forge-id>` (data, task t-506)

## Summary

Replaced the wavefront allocator (a deterministic PI controller picking next-task from stage stats) with **Marshal**: a persistent Claude session that synthesizes steering signals — theme rankings, initiative rank/budget, priority poker, blocked_by deps, worklog recency, human priorities — into an ordered dispatch queue. Marshal is now a permanent member of the rig roster, running in its own tmux window, woken by nudges, writing `next_tasks` that Forge pops from. The strategic architecture is settled: Anvil (strategy) → Marshal (ordering) → Forge (execution).

## What shipped

*Sequenced by task id; see appendix for full task-by-task breakdown with merge shas.*

*32 tasks under the original initiative window (2026-04-11 → 04-19), plus 2 maintenance tasks filed under ini-015 after the first closure draft. Merge-sha column is `—` for t-241–t-262: their work landed in untagged `[stage] description` commits on 2026-04-11, before the `[stage] t-XXX:` commit convention was adopted at t-263 (itself an ini-015 deliverable).*

**Original initiative (32):**

- **t-241** (implementation) — Marshal: persona scaffold — sha=—
- **t-242** (implementation) — Marshal: CLI + communication protocol — sha=—
- **t-243** (editing) — Marshal: update Forge protocol — sha=—
- **t-244** (implementation) — Marshal: Bellows + steering UI integration — sha=—
- **t-245** (testing) — Prioritizer: end-to-end test — sha=—
- **t-247** (implementation) — Hook file I/O in state.py — sha=—
- **t-248** (implementation) — Hook CLI commands — sha=—
- **t-249** (implementation) — Wire hook into end-heat and patrol — sha=—
- **t-250** (editing) — Update Forge protocol and persona for hook model — sha=—
- **t-251** (implementation) — Create Marshal persona — sha=—
- **t-252** (implementation) — Create dispatch channels + .gitignore update — sha=—
- **t-253** (testing) — Hook mechanism tests — sha=—
- **t-254** (implementation) — smithy list-tasks command — sha=—
- **t-255** (implementation) — smithy set-priority command — sha=—
- **t-256** (implementation) — smithy set-next-tasks command — sha=—
- **t-257** (editing) — Forge always-on loop — sha=—
- **t-258** (implementation) — Marshal hook mechanism — sha=—
- **t-259** (editing) — Marshal always-on loop — sha=—
- **t-260** (implementation) — Generalize hook mechanism — sha=—
- **t-261** (implementation) — Hook queue: allow multiple hooked tasks — sha=—
- **t-262** (implementation) — Unified task queue: collapse hook + next_tasks into one mechanism — sha=—
- **t-263** (implementation) — smithy nudge command + tmux session convention — sha=`5353411`
- **t-264** (implementation) — Wire nudge into queue-push — sha=—
- **t-265** (implementation) — Wire nudge into Marshal→Forge dispatch — sha=—
- **t-266** (implementation) — Nudge queue for busy sessions — sha=—
- **t-275** (testing) — Integration test Marshal+Forge flow end-to-end — queue-push triggers nudge, Forge pop… — sha=`3dbf81f`
- **t-276** (editing) — Marshal persona CLAUDE.md final pass — ensure startup, message-driven loop, and prior… — sha=`863ad75`
- **t-277** (editing) — Anvil persona CLAUDE.md — update for Agent Teams spawn protocol, remove dispatch refe… — sha=`e6c6fc1`
- **t-295** (editing) — Forge persona CLAUDE.md update — align with Agent Teams architecture, SendMessage pat… — sha=`b238c43`
- **t-303** (marketing) — Marshal retrospective — Agent Teams experiment from the prioritizer seat: what worked… — sha=`3acb8c6`
- **t-308** (editing) — Delete legacy dispatch/ directory (5 files: anvil-to-forge.md etc.) + remove any CLI… — sha=`78c712f`
- **t-479** (implementation) — Marshal: never block on stdin — escalate to inbox.md + nudge Anvil, then proceed with… — sha=`11bbf70`

**Late-filed maintenance under ini-015 (2):**

- **t-530** (implementation) — set-next-tasks only nudges the top task's assigned forge, leaving other pinned forges… — sha=`1ac0438`
- **t-534** (implementation) — Marshal reject-loop detector: stop re-dispatching a task that's failed 3 times with t… — sha=`034fc56`

## What worked (keep doing)

**Unified queue mechanism (t-262).** Collapsing the separate `.forge-hook.json` + `next_tasks` into one queue was the inflection point. Before: two paths, drift between them, unclear which was authoritative. After: one ordered list, one reader, one writer. This pattern (collapse duplicated state into a single source) recurred successfully in later ini-018 and ini-024 work — worth codifying as a general heuristic.

**Nudge channel as fast-path, state.json as truth (t-263 through t-266).** Nudges evolved from "write a dispatch file, hope Forge reads it" into "send a one-line tmux keypress to wake the target pane, the pane re-reads state.json." Clean separation: the nudge is *when*, state.json is *what*. This separation is the substrate ini-024 (liveness reconciliation) builds on — reconciliation replaces the nudge's *correctness role* while keeping it as fast-path optimization.

**Orphan reap in patrol (t-437).** Every Marshal cycle runs `patrol --fix` to reap `in_progress` tasks whose forges have moved on. This closed a whole class of "task wedged in_progress" bugs. Patrol became the sweeper; Marshal became free to focus on forward motion.

**Anvil-as-spec-author, Forge-as-implementer division of labor.** The tasks under ini-015 are mostly Anvil-written implementation specs with concrete acceptance criteria, and Forge cranked through them predictably. This division held up across 32 tasks with minimal rework — validating the three-role architecture before we relied on it for bigger initiatives.

## What didn't (stop doing)

**Agent Teams experiment (t-277, t-295, t-303).** Initial attempt: Marshal spawns Forge via Agent Teams' `SendMessage` instead of tmux panes. Didn't stick. File-based coordination (state.json, queues, worklog) was already the substrate by inertia and Rule 4 ("the record is sacred"); Agent Teams became a second, redundant channel. t-303 retrospective documented the reasons; switched back to tmux-native. **Lesson:** don't add a coordination channel when one exists and works — pick one, make it good.

**Hardcoded tmux session name (`smithy2`).** Surfaced 2026-04-18 heat 989 as a silent-failure bug: a phantom `smithy2` session alongside the live `forge` session caused all Marshal-issued nudges to silently fall through to `.smithy-nudge-queue/forge.jsonl`. Forges sat idle for 25min while Marshal thought it had dispatched. Filed as t-489 (priority 0, ini-022 rig-lifecycle). **Lesson:** never hardcode session names; respect an env var contract (`FORGE_SESSION=forge`) that `scripts/nudge.sh` already used correctly.

**Silent stdin-wait (t-479).** Observed 2026-04-18 heat 989: Marshal hit a decision it couldn't make (what to do with zombie-submitted tasks) and wrote a question to stdout, blocking on stdin. No entry in worklog, no patrol issue, no nudge to Anvil. All three forges sat idle 7m37s while Marshal waited invisibly. Filed t-479 to replace every stdin path with an escalate-and-proceed pattern (question → `inbox.md` + nudge Anvil + apply safe-default + continue loop). **Lesson:** an AI persona should never block on human input silently — either escalate visibly or pick a safe default. This pattern likely applies to other personas too.

**Over-budget closure (28 vs 25 heats, +12%).** Budget cap was optimistic. The overage came from late-session debugging (t-479, plus integration churn from t-265/t-266 nudge work) rather than scope creep. **Lesson:** scaffolding + CLI work estimates well; integration + cross-persona behavior adds a consistent ~10-15% tax. Bake that into future budget caps for similar initiatives.

## Carry-forward

- **Memory: `feedback_marshal_silent_question.md`** (personas/anvil/memory/) — check Marshal's pane first when forges look idle; answer via state mutation + nudge, never in-pane
- **Memory: `project_smithy_cli_session_mismatch.md`** (personas/anvil/memory/) — dual-tmux-sessions + hardcoded name = silent jsonl fallback
- **Memory: `feedback_nudge_marshal_after_filing.md`** (personas/anvil/memory/) — Marshal re-reads state only on nudge or tick; always nudge after `smithy add-task`
- **Memory: `feedback_post_unblock_status_format.md`** (personas/anvil/memory/) — after unblocking any rig component, deliver per-agent live-state table, not just "I nudged it"
- **Protocol: unified queue pattern** — collapse duplicate state to one source of truth (from t-262); now the default shape for all dispatch state
- **Protocol: nudge-as-fast-path, state-as-truth** — the substrate ini-024 builds on; continue applying to new coordination surfaces

**Supersession note:** ini-024 (Liveness via reconciliation) extends Marshal in an important way: it removes Marshal from the *correctness* path by having Forge and Assembly self-dispatch from state.json + git on every idle tick. Post-ini-024, Marshal stalling or going silent (the t-479 failure mode) no longer freezes the rig — forges keep moving. Marshal remains the *optimization* layer (priority synthesis, load balancing, stage balance) but is no longer single-point-of-failure for dispatch. This is why no successor is needed here: ini-024 already covers the architectural next step, and everything else is incidental maintenance.

## What's next

**No direct successor.** Marshal is complete as an initiative: persona shipped, dispatch loop solid, nudge mechanism live, orphan reaping automatic. Future work on Marshal (bug fixes like t-479, new steering signals, maintenance) files as **new initiatives when the scope justifies one** or goes directly to theme-002 without initiative attribution for small paper-cut fixes (per ini-025 locked decisions). Ongoing architectural evolution is tracked under **ini-024 (Liveness via reconciliation)**, which makes the Marshal layer non-load-bearing for correctness.

## Metrics appendix

| id | stage | heats | outcome | merge_sha |
|----|-------|------:|---------|-----------|
| t-241 | implementation | 1 | merged | — |
| t-242 | implementation | 1 | merged | — |
| t-243 | editing | 1 | merged | — |
| t-244 | implementation | 1 | merged | — |
| t-245 | testing | 1 | merged | — |
| t-247 | implementation | 1 | merged | — |
| t-248 | implementation | 1 | merged | — |
| t-249 | implementation | 1 | merged | — |
| t-250 | editing | 1 | merged | — |
| t-251 | implementation | 1 | merged | — |
| t-252 | implementation | 1 | merged | — |
| t-253 | testing | 1 | merged | — |
| t-254 | implementation | 1 | merged | — |
| t-255 | implementation | 1 | merged | — |
| t-256 | implementation | 1 | merged | — |
| t-257 | editing | 1 | merged | — |
| t-258 | implementation | 1 | merged | — |
| t-259 | editing | 1 | merged | — |
| t-260 | implementation | 0 | merged | — |
| t-261 | implementation | 0 | merged | — |
| t-262 | implementation | 1 | merged | — |
| t-263 | implementation | 0 | merged | `5353411` |
| t-264 | implementation | 0 | merged | — |
| t-265 | implementation | 1 | merged | — |
| t-266 | implementation | 1 | merged | — |
| t-275 | testing | 1 | merged | `3dbf81f` |
| t-276 | editing | 1 | merged | `863ad75` |
| t-277 | editing | 1 | merged | `e6c6fc1` |
| t-295 | editing | 1 | merged | `b238c43` |
| t-303 | marketing | 0 | merged | `3acb8c6` |
| t-308 | editing | 0 | merged | `78c712f` |
| t-479 | implementation | 5 | merged | `11bbf70` |
| t-530 | implementation | 2 | merged | `1ac0438` |
| t-534 | implementation | 3 | merged | `034fc56` |
| **total** | **34 tasks** | **35** | **0 abandoned** | — |

**Window & cadence.**

- Earliest worklog entry under ini-015: **2026-04-11**.
- Latest merge (late-filed t-534): **2026-06-12**. Original-window close: **2026-04-19**.
- Calendar span (original window): **~8 days** (2026-04-11 → 04-19); the two maintenance tasks landed weeks later under the still-open initiative.
- Reject cycles: **5** total across 34 tasks (merge:reject ≈ **34:5**, ~15% of tasks saw ≥1 reject); no task exceeded 3 reject cycles.

> **Data-fill note (t-506).** Figures are reconciled against current state, which has drifted from the prose header above. Current `state.json`: ini-015 `heats_used=33`, `budget_cap=40`, `status=active`, **34** complete tasks — vs the header's *28 heats / budget 25 / 32 tasks / closed 2026-04-19* (Anvil's original-closure draft). The header reflects the first closure attempt; the initiative was later reopened, its cap raised to 40, and two maintenance tasks (t-530, t-534) added. Per-task `heats` count distinct Forge work-heat worklog rows (sum 35) and so differ slightly from the initiative's charged `heats_used` (33); attribution is approximate for the pre-per-task-branch era. **Anvil should reconcile the header numbers before `smithy complete-initiative ini-015` runs.**
