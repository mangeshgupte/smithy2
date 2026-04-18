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
