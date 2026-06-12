# Anvil's Memory

Index of durable learnings. One line per entry. Keep under 200 lines.

Entry types: `user`, `project`, `reference`. Entries live alongside this file with frontmatter.

<!-- Example entry line (delete when real entries land):
- [Human prefers bullet lists](user_list_preference.md) — concise enumeration over prose in status reports
-->
- [human_priority must be int, not string](feedback_human_priority_int.md) — do not set `'p1'`/`'p2'` strings on new tasks; pre-existing queue uses ints and _do_assembly_reject does `hp + 5` → TypeError on strings
- [Assembly must never block Forge throughput](feedback_assembly_decoupled_from_forge.md) — Assembly operates in its own workspace; Forge never waits for merge
- [Bootstrap coupling pattern for Assembly deadlocks](feedback_bootstrap_coupling_pattern.md) — one-time Forge pause to land Assembly-bug fixes through still-buggy Assembly
- [Prefer structural fixes over symptom patches](feedback_prefer_structural_fixes.md) — when multiple bugs share a root cause (global state), fix the sharing
- [Angle brackets break inline bash -c](feedback_angle_brackets_bash.md) — use heredoc for scripts containing placeholders like <forge-id>
- [Prefer CLI over hand-editing state.json for fields with invariants](feedback_prefer_cli_over_hand_edit.md) — rank/priority/status changes need cascade housekeeping
- [Marshal silently waits at interactive prompt](feedback_marshal_silent_question.md) — when Marshal can't decide, it asks via stdout and blocks invisibly; check pane 2 first when forges look idle
- [Smithy CLI nudge mis-routes on dual tmux sessions](project_smithy_cli_session_mismatch.md) — phantom `smithy2` session causes silent jsonl fallback; forges sit idle while Marshal believes it dispatched
- [Post-unblock "stuck vs working" status format](feedback_post_unblock_status_format.md) — after any intervention, deliver per-agent live state + outstanding risks; "I nudged it" is not enough
- [Always nudge Marshal after filing tasks](feedback_nudge_marshal_after_filing.md) — Marshal only re-reads state on nudge/tick; silent filings leave tasks invisible; batch-nudge with priority hints
- [Never run queue-pop from Anvil context](feedback_no_queue_pop_from_anvil.md) — queue-pop mutates state; inspection must be via reading state.json directly, not CLI probing
- [Bootstrap merge must pair git merge with complete-task](feedback_bootstrap_merge_complete_task_pair.md) — git merge alone leaves state.json pending; always follow with smithy complete-task in same batch
- [Phantom forge-01 HEAT_DONEs = t-519 test leak](project_phantom_heat_done_t519.md) — smithy tests nudge live Marshal pane on every gate run; ignore until t-519 lands
- [budget_cap has no CLI setter](project_budget_cap_hand_edit.md) — edit-initiative won't do it; fast hand-edit of state.json is the sanctioned path
