# The Forge — End-to-End Walkthrough

A narrative tour of The Smithy, following one human from install to shipped feature. Read this if you want to see how the pieces — CLI, personas, steering UIs, nudge cycle — fit together in practice.

---

## Meet Alex

Alex maintains `tasq`, a small Python CLI for task tracking. They want to add a proper testing feature — unit tests, integration tests, coverage reports — but every time they open the repo, the work feels diffuse. Not hard, just scattered: parser edge cases, mock stores, CLI integration tests, a CI hook. Two evenings of flow, minimum. Alex has about forty-five minutes tonight.

They've heard about The Smithy — an autonomous AI worker that runs in bounded 5-minute "heats," self-prioritizes, commits every heat, and lets you steer without micromanaging. They decide to try it.

---

## Act 1 — Initialize

Alex installs the CLI first:

```bash
$ cd ~/src/smithy2
$ pip install -e smithy/
$ smithy --help
Usage: smithy [OPTIONS] COMMAND [ARGS]...

  The Smith protocol — autonomous AI worker orchestration.

Commands:
  init, start-all, stop-all, sessions, resume, patrol, sync-stages,
  status, stats, start-heat, end-heat, queue-push, queue-pop, ...
  (28 commands)
```

Then scaffolds a project:

```bash
$ smithy init tasq --target ~/projects/tasq
✓ Created ~/projects/tasq/CLAUDE.md
✓ Created ~/projects/tasq/protocol/loop.md
✓ Created ~/projects/tasq/protocol/allocator.md
✓ Created ~/projects/tasq/protocol/logging.md
✓ Created ~/projects/tasq/protocol/reporting.md
✓ Created ~/projects/tasq/state.json    (budget: 100 heats)
✓ Created ~/projects/tasq/identity.md   (template)
✓ Created ~/projects/tasq/worklog.tsv
✓ Created ~/projects/tasq/inbox.md
✓ Created ~/projects/tasq/outbox.md
✓ Created ~/projects/tasq/feedback.md
✓ Created ~/projects/tasq/personas/{anvil,marshal,forge}/CLAUDE.md

Next: edit identity.md, then `smithy start-all`
```

Alex opens `~/projects/tasq/identity.md` and fills it in:

```markdown
# tasq

## What This Is
A minimal Python CLI for personal task tracking.
Flat-file storage (~/.tasq/tasks.json). Three commands: add, list, done.

## Commander's Intent
- Intent: Reach production-quality test coverage (90%+) with meaningful tests
- Success looks like: CI green, edge cases covered, no mocked-out integrations
- Tone: Pragmatic. Tests should catch real bugs, not pad coverage.
- Boundaries: Only the testing layer — don't refactor core logic
- Not this: No new features. Testing & quality only.
```

They peek at `state.json`:

```json
{
  "project": "tasq",
  "budget": { "total_heats": 100, "used": 0 },
  "stages": {
    "research":       { "heats": 0, "progress": 0 },
    "planning":       { "heats": 0, "progress": 0 },
    "implementation": { "heats": 0, "progress": 0 },
    "testing":        { "heats": 0, "progress": 0 },
    "editing":        { "heats": 0, "progress": 0 },
    "marketing":      { "heats": 0, "progress": 0 }
  },
  "queue": [],
  "themes": [],
  "initiatives": [],
  "constraints": []
}
```

Six stages, 100 heats (~8 hours of bounded work), empty queue. Everything visible in a flat file. Alex likes this — no hidden state.

---

## Act 2 — Start the Team

Alex runs one command:

```bash
$ cd ~/projects/tasq
$ smithy start-all
✓ Created tmux session 'smithy2'
✓ Window 'anvil'   — Claude Code launched in personas/anvil/
✓ Window 'marshal' — Claude Code launched in personas/marshal/
✓ Window 'forge'   — Claude Code launched in personas/forge/

Attach: tmux attach -t smithy2
Or just message anvil: smithy tell anvil "Start"
```

Three Claude Code windows, each in a different persona directory, each loading its own CLAUDE.md. Alex attaches to the `anvil` window and types:

```
> Start
```

**Anvil boots up.** It reads `state.json`, `identity.md`, sees the intent ("Reach production-quality test coverage"), and spawns its two teammates using `TeamCreate` + the Agent tool. Each spawn prompt includes the `cd` trick — Anvil knows that without it, the spawned agent would inherit Anvil's working directory and load Anvil's CLAUDE.md instead of its own.

```
Anvil: Team created. Spawning Marshal and Forge.
Anvil: Marshal online — reading state, initiatives, protocol/allocator.md.
Anvil: Forge online — waiting for first task assignment.

Anvil: No themes or initiatives exist yet. What do you want to steer toward?
       You can:
       1. Tell me your priorities (I'll decompose into themes + initiatives)
       2. Open the Intent Editor at http://localhost:8004 and write bullets
       3. Drop into Priority Poker if you already have ideas drafted
```

**Marshal's first moments.** In the background, Marshal reads the protocol files, runs `smithy patrol --fix` to verify state integrity, then sits idle. Its job is to prioritize — but there's nothing to prioritize yet.

**Forge's first moments.** Forge runs `smithy resume`, `smithy patrol --fix`, `smithy sync-stages`, then calls `smithy queue-pop`. The queue returns `{task: null}`. Forge prints "Waiting for task…" and idles. It will wake when Marshal queues one.

Alex now has a running team. No heat has been spent yet — the budget is still 100/100.

---

## Act 3 — The Human Steers

Alex opens the Intent Editor in a browser tab: `http://localhost:8004`.

The UI is dark, clean, one textarea. Alex types:

```
- **Testing**
  - Build a full unit test suite for the core parser
  - Integration tests covering add/list/done round-trip
  - Edge case tests — malformed dates, unicode, empty args
  - Coverage report wiring (pytest-cov)
- **CI**
  - GitHub Actions workflow to run tests on push
  - Lint pass (ruff)
```

They hit **Decompose**. The UI decomposes the bullets into a tree: two themes (*Testing*, *CI*), six initiatives under them. All are marked `+ new` in green. Alex unchecks "Lint pass (ruff)" — out of scope tonight — and clicks **Apply Selected**.

Behind the scenes, the Intent Editor POSTs to `/apply`, which writes to `state.json`:

```json
"themes": [
  { "id": "th-001", "name": "Testing", "status": "active" },
  { "id": "th-002", "name": "CI",      "status": "active" }
],
"initiatives": [
  { "id": "ini-001", "theme_id": "th-001", "title": "Unit tests — parser",      "status": "proposed" },
  { "id": "ini-002", "theme_id": "th-001", "title": "Integration tests",        "status": "proposed" },
  { "id": "ini-003", "theme_id": "th-001", "title": "Edge case coverage",       "status": "proposed" },
  { "id": "ini-004", "theme_id": "th-001", "title": "Coverage reporting",       "status": "proposed" },
  { "id": "ini-005", "theme_id": "th-002", "title": "GitHub Actions workflow",  "status": "proposed" }
]
```

Nothing is `approved` yet — proposed initiatives are visible but don't gate work.

Alex switches to the Priority Poker tab: `http://localhost:8001`. The five proposed initiatives appear as cards stacked by theme. Alex drags them into the order they want the Forge to tackle them:

```
1. Unit tests — parser            ← highest priority
2. Edge case coverage
3. Integration tests
4. Coverage reporting
5. GitHub Actions workflow
```

They click **Approve** on the top three. The poker UI sends `POST /reorder` and `POST /approve/ini-001` (etc.), which write back to `state.json`. Approved initiatives now have `status: "approved"` and a `rank` field.

**The nudge cycle fires.** Writing `state.json` triggers a file-watch in Marshal. Marshal wakes up:

```
Marshal: State changed. Recomputing priorities.
Marshal: 3 approved initiatives, 0 tasks queued. Generating tasks for rank-1 initiative.
Marshal: smithy add-task testing "Unit test parser: tokenize()" --initiative ini-001
Marshal: smithy add-task testing "Unit test parser: parse_date()" --initiative ini-001
Marshal: smithy add-task testing "Unit test parser: parse_flags()" --initiative ini-001
Marshal: smithy queue-push t-001 t-002 t-003
Marshal: → nudge sent to forge
```

**Forge wakes.** It was idling; the nudge arrives and it returns to Step 1 of the loop.

---

## Act 4 — Forge Executes a Heat

```
Forge: smithy queue-pop
       → { "task_id": "t-001", "stage": "testing",
           "description": "Unit test parser: tokenize()" }
Forge: smithy start-heat testing
       → heat 1 [testing] started
```

Forge reads `src/tasq/parser.py`, studies the `tokenize()` function, and writes `tests/test_parser_tokenize.py`. It picks out edge cases the code already handles — trailing whitespace, quoted args, empty input — plus two it suspects are under-tested. Runs `pytest tests/test_parser_tokenize.py -v`:

```
tests/test_parser_tokenize.py::test_basic PASSED
tests/test_parser_tokenize.py::test_quoted_args PASSED
tests/test_parser_tokenize.py::test_empty_input PASSED
tests/test_parser_tokenize.py::test_unicode FAILED
tests/test_parser_tokenize.py::test_trailing_semicolon FAILED
```

Two real bugs found. Forge fixes them in `parser.py` in the same heat — that's in-scope for a testing heat, per the protocol. Re-runs: all pass. Commits:

```
Forge: git add tests/test_parser_tokenize.py src/tasq/parser.py
Forge: git commit -m "[testing] t-001: tokenize() unit tests — 5 cases, fixed unicode + semicolon bugs"
[main 3a2f19c] [testing] t-001: tokenize() unit tests — 5 cases, fixed unicode + semicolon bugs
 2 files changed, 68 insertions(+), 3 deletions(-)
```

Then closes the heat:

```
Forge: smithy end-heat 0.9 🟢 "5 tests added, 2 pre-existing bugs surfaced and fixed. Coverage on tokenize() now 100%."
       → heat 1 [testing] complete
       → budget.used = 1 / 100
       → value_ema[testing] = 0.9
       → worklog.tsv appended
       → task t-001 marked complete
       → nudge sent to marshal
```

**The worklog entry:**

```
heat  stage    task_id  value  signal  notes
1     testing  t-001    0.9    🟢      5 tests added, 2 pre-existing bugs surfaced and fixed. Coverage on tokenize() now 100%.
```

**Forge's report to Marshal** (via `SendMessage`):

```
TASK_COMPLETE: t-001
Commit: 3a2f19c
Value: 🟢 (0.9)
Summary: 5 tokenize() tests + fixed 2 bugs (unicode, trailing semicolon).
Notes: parse_date() next — looks like it has more edge cases than tokenize did.
```

Forge loops back to Step 1, calls `queue-pop`, gets `t-002`. The whole cycle — pop, start, execute, commit, end, report — took 4 minutes 12 seconds.

---

## Act 5 — Alex Re-ranks to Shift Focus

By heat 6, Alex glances at the tmux pane and sees steady progress. Commits scrolling in `git log`:

```
$ git log --oneline -8
c1e7a44 [testing] t-006: parse_flags() — 4 tests, edge case on --done=false
9b3d501 [testing] t-005: integration test add→list round-trip
7fa1b1d [testing] t-004: parse_date() — 8 tests, fixed ISO format bug
4b82c3e [testing] t-003: parse_flags() — 6 tests
e5c9202 [testing] t-002: parse_date() — 5 tests
3a2f19c [testing] t-001: tokenize() unit tests — 5 cases, fixed unicode + semicolon bugs
```

Six heats, all testing. But Alex also wants coverage reporting and CI to happen before the budget is gone. They open Priority Poker (`http://localhost:8001`) and drag the coverage and CI initiatives above the remaining testing work. Rank IS the steering signal — Marshal watches `state.json`, sees the new order, and interleaves accordingly on the next heat.

No constraint needed. The preference signal already lives in the rank.

### Task-level nudges inside an initiative

Alex clicks the initiative row to expand the drawer. The queued tasks render like:

```
t-012  add CI workflow for pytest           M:p1 · ini-003 rank=1 + poker   you:—   [↓]
t-013  generate coverage.xml on every run   M:p2 · ini-003 rank=1 + poker   you:—   [↓]
t-014  upload coverage to codecov           M:p2 · ini-003 rank=1 + poker   you:—   [↓]
```

Each row shows Marshal's priority (`M:p{N}`), the auto-generated `priority_reason` (≤40 chars, drawn from the `{recency, poker, stage-balance, blocked-deps-clear}` signal vocab), and Alex's sticky override (`you:—` means unset). Alex wants t-013 to happen *before* t-012 and clicks `↓` on t-012. The drawer POSTs to `/api/task/t-012/human-priority` with `{"value": 10}` — `you:p10` now appears on that row, and Marshal's next scheduling pass sorts `(human_priority or +inf, priority, id)`, so t-013 (unset, p2) leads t-012 (p10 sticky).

Alex flips to Bellows and opens `/project/tasq-cli/diff?n=1` to confirm the queue reordered as expected — the per-heat diff view shows `queue[*].human_priority` and order changes across the last N heats. When Forge eventually ships t-012, the sticky override auto-clears on completion; `human_priority` doesn't outlive the task it rode in on.

---

## Act 6 — Review

After about 20 heats, Alex wants a status check. They type into the anvil pane:

```
> what's the status?
```

Anvil reads the worklog, state, and git log, then responds:

```
THE FORGE — STATUS (heats 1-20)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

20 heats, 16 green, 3 yellow, 1 red | 42% intent progress (+42%) | 80 heats remaining

CURRENT INTENT: "Reach production-quality test coverage (90%+) with meaningful tests"

WHAT WE'RE LEARNING:

  VALIDATED
  - parse_date() had the most bugs of any parser module  (4 fixes in 3 heats)
  - Integration tests catch what unit tests miss          (heat 5 caught a real regression)

  JUST DEPLOYED — WATCHING
  - Coverage reporting via pytest-cov                     (wired heat 18, report clean)

  INCONCLUSIVE
  - Whether we'll hit 90% coverage by the cap             (currently 78%, 14 heats left in testing)

  INVALIDATED
  - tokenize() was low-risk                               (found 2 bugs in heat 1)

INTENT PROGRESS:
  Asked: 90% coverage, meaningful tests, CI green.
  Done: 78% coverage, 47 tests added, 6 real bugs fixed, pytest-cov wired.
  Left: 12 more percentage points of coverage, GitHub Actions workflow, final sweep.
  Blockers: None. testing cap at 20/40, healthy headroom.
  Confidence: High.

TEAM STATUS:
  Marshal: idle (queue has 3 tasks, Forge mid-heat)
  Forge:   executing heat 21 [testing] — t-021 edge case coverage

YOUR MOVE:
  1. Nothing urgent. Let it run.
  2. Want to see the coverage report? `cat htmlcov/index.html` after heat 22.
  3. If you want the CI work earlier, say so and I'll re-prioritize.
```

Alex reads it, decides it's on track, and walks away from the terminal. The Forge keeps going.

When they come back ninety minutes later:

```bash
$ smithy status
budget: 54 / 100 heats used
stages: testing 38, editing 8, marketing 6, planning 2
last heat: 54 [marketing] — README coverage section
last commit: 2 minutes ago
queue: 2 pending
```

```bash
$ git log --oneline | head -5
7a9e1a0 [marketing] t-054: README — testing section + coverage badge
dc41b8f [marketing] t-053: CHANGELOG — v0.2 testing milestone
b2e8f52 [editing] t-052: fix flaky integration test (tmpdir teardown race)
4491c03 [testing] t-051: parse_date() — final 3 edge cases, 94% coverage on parser
a0f32c5 [editing] t-050: test helpers — dedupe fixture boilerplate
```

54 heats. 94% parser coverage. A CHANGELOG entry. A README update with a coverage badge. A GitHub Actions workflow committed at heat 47. Alex ships a PR.

---

## Callouts — Where Human Steering Matters

| Moment | Who drove it | Why it mattered |
|--------|--------------|-----------------|
| Writing `identity.md` | Human | Every downstream decision flows from commander's intent. Vague intent → drifted work. |
| Decomposing goals in Intent Editor | Human | Converts fuzzy wants into discrete initiatives the system can prioritize. |
| Ranking in Priority Poker | Human | The system doesn't know *your* priorities — you tell it by ordering cards. |
| Approving initiatives | Human | Approval gates work. Proposed = visible but dormant. Approved = Marshal can generate tasks. |
| Re-ranking to shift focus | Human | Drag cards in Poker instead of capping stages — preference signal lives in the rank. |
| Asking "what's the status?" | Human | Anvil summarizes honestly — you learn what's working without reading commits. |

## Callouts — Where the System Self-Drives

| Moment | Who drove it | Why it mattered |
|--------|--------------|-----------------|
| Generating tasks from initiatives | Marshal | You don't write 20 task descriptions — Marshal breaks initiatives into heat-sized work. |
| Ordering the queue | Marshal | Poker rank + stage balance → concrete order. |
| Fixing 2 bugs in a testing heat | Forge | Testing heats can fix the bugs they surface. No ticket needed. |
| Re-planning when rank changes | Marshal | You reorder Poker; Marshal interleaves other stages on its own. |
| Every commit, every heat | Forge | The record is the artifact. `git log` is the status dashboard. |
| Self-assessment 🟢/🟡/🔴 | Forge | Honest signal feeds the allocator's future stage decisions. |

---

## The Command Reference (for when you want it)

All of the above, as commands:

```bash
# Setup
smithy init <project> --target <path>
$EDITOR identity.md
smithy start-all

# Steering (or use the UIs at :8001-:8004)
smithy add-theme "Testing"
smithy propose th-001 "Unit tests" "Full coverage of parser"
smithy approve ini-001

# Queue / execution (Marshal and Forge do these automatically)
smithy queue-push t-001 t-002 t-003
smithy queue-pop
smithy start-heat <stage>
smithy end-heat <value> <signal> "<notes>"

# Coordination
smithy nudge <persona> "<message>"
smithy drain-nudges <persona>

# Observability
smithy status
smithy stats
smithy sessions
git log --oneline

# Lifecycle
smithy stop-all              # graceful
smithy stop-all --kill       # immediate
smithy start-all             # resume from handoff
```

---

## Steering UIs at a Glance

| UI | Port | Use when |
|----|------|----------|
| 🃏 Priority Poker | 8001 | You know what the work is — just order it. |
| 🎯 Intent Editor | 8003 | You have goals in bullets, want the system to decompose. |
| 📅 Timeline | 8004 | You want to plan *when* each initiative runs in the budget. |
| 🔔 Bellows | 8080 | Multi-project dashboard — watching several Forges at once. |

All three steering UIs share a nav bar — click any icon to switch. Each shows live state (SSE polling) and writes directly to `state.json`. No redeploys. See `STEERING.md` for the full reference.

---

## The Activity Side-Panel

Poker now carries a 280px right-rail (`📜 Activity`) that answers *"what's been happening?"* without leaving the page. It merges two streams into one newest-first feed: **steering events** from `steering.log` (pins, defers, reorders, deletes — anything a human did via Poker or Bellows Upcoming) and **Forge heats** from `worklog.tsv` (every heat Forge completed). Forge rows render slightly muted so human steering stays legible.

The panel refreshes every 5 seconds against `GET /api/activity?limit=20`. It's collapsible via the `−` toggle and hides entirely below 900px viewport to stay out of the way on narrow screens. Each entry is a single line:

```
h770 · just now
 🟢 forge completed t-347

h769 · 1m ago
 📌 mangesh pinned t-347

h768 · 3m ago
 ⏸ mangesh deferred t-340
```

Icons map to verbs: 📌 pinned / 📍 unpinned / ↑ priority-set / ⏸ deferred / ▶ undeferred / 🗑 deleted / ↕ reordered / 🟢 completed. The "view full log →" link deep-links to the raw JSON endpoint if you want to scroll further back. Timeline gets the same panel next — the helper (`smithy/activity.py`) and endpoint are already shared.

---

## Key Principles

- **Prose is the orchestrator** — CLAUDE.md + protocol files, no framework.
- **Flat files** — every piece of state inspectable with `cat`.
- **Git is the substrate** — every heat commits. The record is the artifact.
- **Budget-bounded** — the Forge never exceeds allocated heats.
- **Nudge-driven** — personas nudge each other; nudges queue when busy.
- **Self-directed** — generates tasks when the queue runs empty.
- **Human steers the priorities; the system runs them.**

---

## What's Next

- Read `STEERING.md` for the full UI reference.
- Read `protocol/loop.md` if you want to know exactly how a heat executes.
- Read `personas/anvil/CLAUDE.md`, `personas/marshal/CLAUDE.md`, `personas/forge/CLAUDE.md` to see what each agent actually knows.
- Try it with a small project first (budget 20–30 heats). The rhythm is easier to feel at that scale.
