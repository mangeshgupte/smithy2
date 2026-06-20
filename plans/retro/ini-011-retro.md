# ini-011: UI B — Constraint Board — Retrospective

**Closed:** 2026-06-20 *(pending `smithy complete-initiative`)*
**Heat cost:** 10 heats (budgeted 15)
**Task count:** 15 complete / 0 abandoned *(built then deliberately retired — see below)*
**Successor:** none — steering converged on ranking (ini-010 Priority Poker)
**Author:** Anvil (prose, 2026-06-20) + forge-quench (data, task t-613)

## Summary

A **negative result, deliberately reached.** ini-011 built the Constraint Board —
a standalone UI for steering by *boundaries* instead of orders ("no more than 5
heats on research", "testing above 80%"), air-traffic-control style. It shipped
fully (its own FastAPI app, violation detection, allocator wiring, CRUD, tests,
polish) and was dogfooded — then **intentionally retired** in a "ranking over
constraints" strategic reversal (STRATEGY.md; commit `176df2c`, t-310; deep
cleanup t-318). The lasting outcome is the validated finding that **rank is the
steering primitive and constraints were redundant** — every constraint scenario
turned out to be better expressed as a Priority-Poker rank reorder. The
initiative's final state is its own removal, and that is the point: it was a
cheap experiment with a clear verdict.

## What shipped

This initiative's deliverable is unusual: a full build arc *followed by its own
removal*. The board shipped, was dogfooded, and was then deleted on evidence.

**Built** (the board, shipped fully):

- t-159: Bellows constraint-board route — `—`
- t-160: Bellows constraint-board endpoints — `—`
- t-188: Constraint board scaffold / core app — `—`
- t-189: Violation detection / enforcement — `—`
- t-190: Constraint board tests — `—`
- t-206: Allocator reads constraints — `—`
- t-211: Improvement batch 1 — `—`
- t-212: Improvement batch 2 — `—`
- t-213: Improvement batch 3 — `—`
- t-220: Constraint-board sprint plan — `—`
- t-281: CRUD — add/edit endpoint + inline click-to-edit UI — `f459df3`
- t-282: CRUD tests — add/remove/toggle/edit, constraint types, violation detection (16 tests) — `8eb4304`
- t-289: Visual polish — match Poker's design system — `4de5a51`

**Retired** (the deliverable's final state is its own removal):

- t-310: Remove the Constraints UI — delete `ui-constraint-board/`, drop the nav link ("ranking over constraints") — `176df2c`
- t-318: Constraint deep cleanup — strip allocator constraint-scoring, the `add-constraint` CLI, and the `constraints: []` emission in `state.json` — `b65fbee`

## What worked (keep doing)

**The standalone-app architecture made the experiment cheap to run *and* cheap to
kill.** Four independent FastAPI UIs over a shared `state.json` meant the
Constraint Board could be deleted (t-310) with **zero changes to Poker / Timeline
/ Intent** — they never knew it left. That modularity is the reusable win: it
turns "should we build steering-UI X?" into a low-stakes, reversible bet instead
of a load-bearing commitment. Keep this shape for any speculative surface.

**Dogfooding produced the verdict, fast.** The decision to retire wasn't a
hunch — it came from real use: "Constraint got set up once and rarely touched,"
while Poker got used every session. Building it was *how we learned* it was
redundant. A working feature that gets dogfooded and then killed on evidence is a
successful experiment, not wasted work.

## What didn't (stop doing)

**We built the full board before testing it against Poker in real use — and the
taxonomy had already predicted it would be low-use.** The pre-build steering
taxonomy (cognitive-load vs. frequency) flagged constraints as set-once /
rarely-touched; we built the whole thing anyway, then deleted it. **Lesson:** when
several UIs target the *same job* (here: steering), build the cheapest one first,
dogfood it, and only then decide whether the siblings earn their existence —
don't build the full set in parallel and prune after.

**The retraction took two passes because the feature had grown tendrils into
core.** Removal needed t-310 (delete the UI) *and* t-318 (strip allocator
constraint-scoring, the `add-constraint` CLI, and the `constraints: []` emission
in `state.json`). A UI experiment that wires into core is expensive to retract.
**Lesson:** keep speculative UIs read-mostly and loosely coupled — let them
*read* state and propose, not embed write-paths into the allocator/CLI/schema —
until they've earned permanence.

## Carry-forward

- **Decision (canonical):** "ranking over constraints" — rank IS the steering signal (STRATEGY.md; commit `176df2c`).
- **Research:** `research/steering-patterns.md` + `research/steering-patterns-retrospective.md` — the four-UI steering taxonomy, the dogfooding usage data, and the full retirement rationale.
- **Unpursued forward idea (if constraint *value* is ever wanted):** a unified violations/activity side-panel surfacing limits *inside* Poker, where steering already lives (retrospective §"Looking forward" #1) — captures enforcement visibility without resurrecting a separate board.
- **Pattern to reuse:** standalone-UI-over-shared-state (cheap add/remove); and the heuristic "build the cheapest UI for a job first, dogfood, then decide on the rest."

## What's next

**No successor.** Steering converged on ranking (ini-010 Priority Poker), and that
is where the preference now lives. There is no constraint board and, by decision,
won't be one. If constraint-style *value* is ever wanted, it files as the
violations-side-panel idea above (a new task), not a revived board. Future
steering work files as a new initiative when substantial.

## Metrics appendix

| task   | stage          | heats | result | sha       |
|--------|----------------|------:|--------|-----------|
| t-159  | implementation |     1 | merged | `—`       |
| t-160  | implementation |     1 | merged | `—`       |
| t-188  | implementation |     1 | merged | `—`       |
| t-189  | implementation |     1 | merged | `—`       |
| t-190  | testing        |     1 | merged | `—`       |
| t-206  | implementation |     1 | merged | `—`       |
| t-211  | implementation |     1 | merged | `—`       |
| t-212  | implementation |     1 | merged | `—`       |
| t-213  | implementation |     1 | merged | `—`       |
| t-220  | planning       |     1 | merged | `—`       |
| t-281  | implementation |     1 | merged | `f459df3` |
| t-282  | testing        |     1 | merged | `8eb4304` |
| t-289  | editing        |     1 | merged | `4de5a51` |
| t-310  | editing        |     1 | merged | `176df2c` |
| t-318  | editing        |     0 | merged | `b65fbee` |

**Heat-count note.** The appendix sums to **14** distinct Forge work-heat worklog
rows (one per task), while ini-011's charged `heats_used` is **10**. The gap is
the pre-per-task-branch-era approximation: every task except t-281/t-282/t-289/
t-310 ran in April, before per-task branches made attribution exact — the ini-015
retro flagged the same effect. One row is the inverse: t-318 shipped (`b65fbee`)
but carries **no** worklog work-heat row, so it is recorded as **0** (an
attribution gap, not zero work). There were no reject-cycles; the build→retire
shape means t-310 and t-318 are the *removal* rows, not retries.
