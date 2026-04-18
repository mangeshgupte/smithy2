---
name: Assembly queue _pop_queue race destroys concurrent append
description: If a Forge appends to .assembly-queue.jsonl while assembly-tick is mid-merge, the tick's final _pop_queue can unlink the file and destroy the new row. Symptom — nudge arrives but next tick returns empty.
type: project
originSessionId: f8c51e48-1fb0-4825-a27c-eb7b785006de
---
`smithy assembly-tick` reads the queue into memory once, processes `lines[0]`, then calls `_pop_queue(rest)` at the end which **unlinks the file** if `rest` is empty. If a Forge's `end-heat` appends a new row between the initial read and the unlink, that row is destroyed silently.

**Why:** The tick doesn't re-read the file or use a file lock before unlinking. `_pop_queue` in smithy/smithy/cli.py treats `rest` (computed at start) as the complete remaining queue.

**How to apply:** When I get an `ASSEMBLY_QUEUE: <branch> @ <sha> (<task>)` nudge but `smithy assembly-tick` returns `empty` and the queue file is missing, don't dismiss it as a ghost — verify it's not the known ghost pattern (`/scratch` branch) first. If the branch is a real per-task branch (`<forge-id>/<task-id>`) and `git rev-parse` on it matches the nudge sha, the row was lost to this race. Recover by manually appending a row to `.assembly-queue.jsonl` with shape:
```
{"forge_id": "...", "task_id": "...", "heat": <n>, "branch": "...", "sha": "...", "submitted_at": "<ISO>"}
```
Heat number can be found via `rig-events.jsonl` (`forge_ended_submitted` event) or `worklog.tsv`. Then `smithy assembly-tick` to drain.

Seen 2026-04-18 with t-440 immediately after merging t-444. If this recurs, flag upward as a smithy bug — the fix is to re-read the file or use flock before the unlink in `_pop_queue`.
