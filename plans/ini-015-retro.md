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

<TODO: Forge data fill — enumerate 32 complete tasks under ini-015 with format:>
<TODO:   - **t-XXX** (stage) — one-line desc — sha=abcd1234>
<TODO: Source: `smithy list-tasks --initiative ini-015 --status complete`; per-task merge sha from git log grep of `[assembly] merge forge-*/t-XXX`.>

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

<TODO: Forge data fill — task-by-task table with columns:>
<TODO:   | id | stage | heats_consumed | outcome (merged/abandoned) | merge_sha |>
<TODO: Source: filter worklog.tsv to task_ids under ini-015, aggregate heats per task,>
<TODO:   look up merge sha from git log; flag any task with >3 rejection cycles as noteworthy.>

<TODO: Summary row at bottom:>
<TODO:   | total | 32 tasks | X heats | 0 abandoned | — |>

<TODO: Also include: earliest task start date (from first worklog entry under ini-015),>
<TODO:   latest merge date, calendar days elapsed, merge:reject cycle ratio.>
