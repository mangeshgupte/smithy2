# Steering retro — first-run dogfood (t-344)

**Date:** 2026-04-12, heat 763
**Context:** `smithy steering-retro` landed as t-341 in heat 761. First real-data invocation against `smithy2` repo root (759 heats of worklog history, no pre-existing steering.log).

---

## Raw output

```
$ smithy steering-retro --since 30d

# Steering retro — since 2026-03-13T19:19:56Z

- **Pin events:** 0 across 0 unique task(s)
- **Tasks shipped:** 759
- **Shipped post-pin:** 0
- **Pure-allocator heats:** 762 (762/762 heats had no prior steering)
```

## Findings

### ✅ What worked

- CLI invoked cleanly, no crashes, no path issues.
- `--since 30d` parsing resolved to a concrete ISO cutoff and was echoed in the header.
- Missing `steering.log` handled silently (empty list) — good defensive behavior.
- `--format json` works as an alternative (confirmed via tests, not shown here).

### ❌ Gap 1 — "Tasks shipped" counter is meaningless for Forge's worklog

**Symptom:** 759 tasks shipped out of 763 heats. That's not real — most heats produce no net-new task completion, they just contribute partial progress. Every Forge heat logs `outcome=complete` for *heat completion*, not *task completion*.

**Root cause:** The retro counts every worklog row where `outcome=='complete'`. But Forge's worklog uses `outcome=complete` as "heat ended cleanly" — a per-heat signal, not a per-task event. True task completion is tracked elsewhere (state.json `queue[].status == 'complete'`, or the commit message prefix).

**Fix candidates:**
- **A (cheap):** In the retro, de-dup worklog rows by `task_id` before counting. "Tasks shipped" = unique task_ids with at least one `outcome=complete` row in window.
- **B (better):** Correlate against `state.json` — count tasks whose `status` flipped to `complete` *in window*. Needs a complete-at timestamp in state that we don't currently store.
- **C (simplest):** Rename the metric to "heats completed" so the number stops being misleading. Combine with (A) for a second line: "unique tasks touched: N".

Recommend **A + C**: rename to "heats completed", add a "unique task_ids touched" line, drop the confusing "tasks shipped" framing entirely.

### ❌ Gap 2 — Pure-allocator count mixes heats with task-less rows

**Symptom:** 762/762 pure-allocator. True today (no steering.log) but the denominator conflates `task_id=generated` research rows with real task heats. A pure-allocator metric should exclude heats that never had a task in the first place.

**Fix:** Filter the denominator to rows where `task_id` starts with `t-` (the real task prefix). Treat `generated` and `-` as ineligible.

### ⚠️  Gap 3 — No signal that steering.log is empty

**Symptom:** Output happily reports "Pin events: 0" without flagging that `steering.log` is missing entirely. A user glancing at this might think "nothing got pinned this week" when in fact the pipeline hasn't written anything yet.

**Fix:** When `steering.log` is absent, add a one-line footer: `_Note: steering.log not present — no attribution data yet._` Same when present-but-empty.

### ⚠️  Gap 4 — Markdown output lacks a "top pinners" / "top actors" breakdown

**Symptom:** Even with attribution data, the retro doesn't group by actor. For a multi-agent future (where `bellows-poker`, `cli`, `human:*` all appear) you'd want to see who's doing the steering.

**Fix:** Add a `## By actor` section — count pin events per actor, sorted descending. Trivial to add once we have real data to group on.

### ⚠️  Gap 5 — No commit/PR-link surface

**Symptom:** The retro ties pin_heat → ship_heat via heat numbers, but a human reading this wants to click through to the commit that shipped the pinned task. No link surfaced today.

**Fix:** For each `shipped_post_pin` row, look up the `notes` field from worklog and extract the `[stage] description` pattern — or link to `git log --grep=t-XXX` output. Defer to a follow-up; low value until actor attribution is live.

---

## Value thesis

**First-run dogfooding validated the CLI doesn't crash on real data and found 5 gaps before any human ran it.** The highest-leverage fixes are Gap 1 (rename "tasks shipped" to "heats completed", de-dup by task) and Gap 3 (flag empty steering.log) — both are under 10 lines of code and make the retro trustworthy once real pin events start accumulating.

Gaps 2/4/5 are polish — track them but don't block on them. The retro's core value (pin→ship lag, pure-allocator ratio) will show up naturally once 1–2 weeks of UI-driven steering has accumulated.

---

## Follow-up candidates

- **t-346-candidate** (impl, p2) — Fix Gaps 1, 2, 3. Rename "tasks shipped" to "heats completed", de-dup by task_id, filter task-less rows, add empty-log footer.
- **t-347-candidate** (impl, p3) — Add "## By actor" breakdown section (Gap 4). Low-urgency until multi-actor data exists.
