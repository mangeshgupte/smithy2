---
name: _do_assembly_reject TypeError on string human_priority
description: Rejection path in smithy/smithy/cli.py:826-827 does `hp + 5` where hp is task.human_priority; crashes with TypeError when priority is a string like "p1"/"p2" (current schema for most new tasks).
type: project
---

```python
hp = task.get("human_priority") or 0
task["human_priority"] = hp + 5   # TypeError: str + int
```

**Why it matters:** This path fires for every reject (rebase error, severe conflict, test failure). When it crashes, the tick raises, the queue row is NOT popped, the assembly-log gets no reject entry, and Marshal is never nudged. Assembly becomes stuck on the first un-rejectable task.

**Schema drift:** `state.json` has a mix — older tasks use int priorities (3, 20); newer tasks (t-440s onward) use string `"p0"/"p1"/"p2"/"p3"`. The reject code assumes int.

**How to apply:**
- When triage says "Assembly stuck after crash in `_do_assembly_reject`", this is the bug.
- Do NOT work around by normalizing state.json — priorities carry meaning (`p1` ≠ `1`).
- Escalate to a Forge task. Suggested fix shape: convert string priorities like `"p1"` → int bump (`priority_reason` notes the string form), OR keep string and bump a parallel numeric field. Either way, `_do_assembly_reject` must be schema-aware before bumping.

**Related design flaw surfaced at the same time:** `rebase_forge_branch` (smithy/smithy/assembly.py:40) rebases the Forge worktree's *currently checked-out* branch, not the per-task branch. When Forge has moved on to its next task with unstaged changes, rebase errors → reject path → crash (the `hp + 5` bug compounds this). Fix: `rebase_forge_branch` should `git checkout <forge-id>/<task-id>` first, stash or refuse if dirty.

First seen: 2026-04-18 draining post-t-444 queue (t-446/t-445/t-443/t-431 stuck).
