# Multi-forge Poker — implementation plan

**Source brief:** `research/multi-forge-poker-design.md` (t-430)
**Status:** planning complete, tasks ready for Marshal to file.
**Ordering:** these tasks are ordered; each assumes the previous has
landed. Marshal should file and dispatch them **serially on the schema
change first, then the downstream three in parallel where Forges allow.**

## Task 1 — schema + defaults

**Stage:** implementation
**Estimated heats:** 1
**Parallelism:** must land first; blocks everything else.

Add three fields to each `state.initiatives[]` entry, wired into
`_apply_steerability_defaults` in `smithy/smithy/state.py` so existing
state.json files upgrade invisibly.

- `parallelism: "serial" | "parallel"` — default `"parallel"`.
- `affinity: [str]` — default `[]`.
- `touches: [str]` — default `[]`.

CLI plumbing:
- Extend `smithy add-initiative` (or the equivalent) with
  `--parallelism`, `--affinity`, `--touches`.
- Extend `smithy edit-initiative` / state-writing commands to accept the
  same flags.

Tests:
- Existing state.json (no metadata) loads and round-trips unchanged.
- New initiatives default to `parallel` / `[]` / `[]`.
- Invalid `parallelism` values are rejected at add-time.

Deliverable: schema landed on main + passing tests. Downstream tasks
can read the fields without defensive `.get(...)`.

## Task 2 — Marshal constraint walk

**Stage:** implementation
**Estimated heats:** 2
**Depends on:** Task 1.

Rewrite the initiative-selection portion of Marshal's dispatch (today's
Priority Rule #3 in `personas/marshal/CLAUDE.md` + the code behind
`smithy queue-pop --forge` / `smithy dispatch-next`). The new algorithm
(from the design brief §4.2):

For each idle Forge, walk initiatives by `rank`:

1. Skip if `parallelism == "serial"` and any in-flight task belongs to
   this initiative.
2. Skip if `affinity` is non-empty, the current Forge isn't in it, and
   any listed Forge is idle.
3. Skip if `parallelism == "serial"` and `touches` overlaps with any
   in-flight task's `touches` (task-level override falls back to the
   task's initiative's `touches`).
4. Find top-priority unblocked pending task in this initiative,
   dispatch, mark in-flight.

Tests:
- Three parallel initiatives + three idle Forges → all three dispatch.
- One serial initiative, two Forges → only one task in-flight at a time
  from it; the second Forge picks up the next initiative.
- Affinity preference: initiative with `affinity=[forge-quench]` +
  forge-quench idle + forge-anneal idle → forge-quench gets it;
  forge-anneal proceeds to next initiative.
- Affinity fallback: same initiative, forge-quench busy →
  forge-anneal picks it up.
- Touches collision: two serial initiatives both with `touches: ["smithy/cli.py"]`
  → only one in flight at a time even across initiatives.

Update `personas/marshal/CLAUDE.md` Priority Rule #3 to describe the
constraint walk and reference the new fields.

## Task 3 — Assembly back-pressure

**Stage:** implementation
**Estimated heats:** 1
**Depends on:** Task 1 (not Task 2; these two are parallel-safe).

In Marshal's dispatch entry points (`queue-pop`, `set-next-tasks`), add a
pre-flight check:

```python
depth = count_lines(assembly_queue_path(root))   # reuses t-422 helper
n_forges = len((state.get("parallel") or {}).get("forges") or [])
if depth >= 2 * max(1, n_forges):
    return {"dispatched": False, "reason": f"assembly-queue backpressure (depth={depth})"}
```

Mention the skip reason in the nudge to Forge so the operator can see
why no work dispatched.

Tests:
- depth < 2*N → dispatch proceeds normally.
- depth == 2*N → dispatch refused with `reason` containing
  "backpressure".
- depth > 2*N → same refusal.
- Patrol check #9 (t-423) still runs independently — these are distinct
  controls (staleness vs. depth) with the same data source.

## Task 4 — Priority Poker UI

**Stage:** implementation
**Estimated heats:** 1–2
**Depends on:** Task 1.

Extend the initiative card in `ui-priority-poker/app.py` with the three
advisory fields (see design brief §4.4 for the sketch):

- Parallelism chip — toggle between `parallel` / `serial`, small badge
  color-coded (green=parallel, amber=serial).
- Affinity chip — comma-separated `forge-id` list, editable inline;
  empty string clears.
- Touches chip — path-glob list, editable inline; empty clears.

Drag-to-rank is unchanged. Cards without any of the three fields set
show "parallel · any forge · no contention" in dim text so the defaults
are visible.

Tests:
- Load an initiative with all three set — chips render correct values.
- Edit each chip — POST persists, reload reflects the change.
- Drag-to-rank still reorders correctly after chip edits.
- Playwright smoke: open Poker, set `parallelism=serial` on one
  initiative, save, reload — chip color flips.

## Out of scope (future tasks, not filed yet)

- **Auto-suggested `touches`** from task descriptions + recent commits.
  Revisit once §1 lands and we see how often the human sets `touches`
  manually.
- **Per-task parallelism / touches overrides.** Today the initiative's
  fields apply to all its tasks. If one task in a serial initiative is
  safe to parallelise, we'd add `task.parallelism_override`.
- **Cross-Assembly routing.** Multi-Assembly would need a much deeper
  redesign; flag if we ever run into the need.
- **Persona-side back-pressure dashboard.** `scripts/forge-status.sh`
  (t-432) could show the Assembly depth chip; file separately.

## Dispatch order summary

```
Task 1 (schema)           ─────┐
                                ├── Task 2 (constraint walk)
                                ├── Task 3 (back-pressure)
                                └── Task 4 (UI)
```

Tasks 2, 3, 4 are parallel-safe among themselves once Task 1 is on
main.
