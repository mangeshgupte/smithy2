# Forge's Memory

Index of durable learnings. One line per entry. Keep under 200 lines.

Entry types: `feedback`, `project`, `reference`. Entries live alongside this file with frontmatter.

Operational rollups live in `MEMORY_DAILY.md` and `MEMORY_WEEKLY.md` (same directory); typed entries go here.

- [Non-primary checkpoint recovery](project_checkpoint_missing_recovery.md) — if end-heat reports missing `.forge-checkpoint-<id>.json` despite successful start-heat, reconstruct the file manually with heat/stage/task_id/git_head/timestamp; flag as bug
