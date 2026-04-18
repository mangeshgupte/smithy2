---
name: human_priority must be int, not string
description: When filing tasks to state.queue, set human_priority as an int (0-9), not a "p1"/"p2" string — Assembly's reject path does arithmetic on it
type: feedback
---

When filing tasks into `state.queue`, the `human_priority` field **must be an integer** (typically 0 = p0 blocker, 1 = p1, 2 = p2, etc.), **not a string** like `"p1"` or `"p2"`.

**Why:** `_do_assembly_reject` in `smithy/smithy/cli.py:826` does `hp = task.get("human_priority") or 0; task["human_priority"] = hp + 5` to bump priority on rejection. String + int raises TypeError, crashing the reject path and halting Assembly's merge loop. I triggered this on 2026-04-18 by filing ini-019/020/021 tasks with `'p1'`/`'p2'` strings — 3 queue entries got stuck mid-reject (t-445, t-443, t-431) and Assembly went idle with BLOCKED heartbeat until t-455 normalized the field.

**How to apply:** When writing tasks via Python edit of state.json, use `'human_priority': 0` (p0 blocker), `1` (p1), `2` (p2). Never `'p0'`/`'p1'`/`'p2'` as strings. The `priority` field (different from `human_priority`) is already an int. Once t-455 lands a normalizer, this rule relaxes — but until then, strict ints.
