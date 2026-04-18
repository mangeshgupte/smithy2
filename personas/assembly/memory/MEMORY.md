# Assembly's Memory

Index of durable learnings. One line per entry. Keep under 200 lines.

Entry types: `feedback`, `project`. Entries live alongside this file with frontmatter.

- [Ghost ASSEMBLY_QUEUE nudges](project_forge_ghost_nudge_stale_smithy.md) — nudge + no queue row + `/scratch` branch = stale pre-t-420/t-422 Forge binary; ignore the task, flag for rebind
- [Queue _pop_queue race](project_assembly_queue_pop_race.md) — concurrent Forge append during assembly-tick can be destroyed by the final unlink; if nudge branch sha matches, re-append the row
- [Reject path TypeError on "p1" priority](project_assembly_reject_hp_typeerror.md) — `hp + 5` crashes on string human_priority; compounds with rebase_forge_branch targeting wrong branch; both block the loop
- [Poisoned smithy install → pytest collection errors](project_poisoned_smithy_install_tests.md) — global editable install bound to a Forge worktree on an old branch causes Assembly pytest to ImportError; rebind to main after every merge
