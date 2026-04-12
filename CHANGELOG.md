# Changelog

## v1.10 — Activity Side-Panel + Attribution Hardening (heats 765-775)

### Philosophy
- **Attribution is cheap to generate — but invisible unless it surfaces.** v1.9 landed the pipeline (steering.log). v1.10 closes the loop: a cross-UI **activity side-panel** merges steering events with Forge heats into one newest-first stream, visible on Poker today (and Timeline next). The retro that was a weekly CLI output is now a passive peripheral — "what's happening" visible without asking.

### Activity Side-Panel MVP (t-352-t-355)
- **Shared helper `smithy/smithy/activity.py`** (t-352) — `read_activity(project_root, limit=20, since=None)` merges `steering.log` + `worklog.tsv` tails into the common entry schema `{when, heat, origin, actor, task_id, verb, detail, source}`. Verb mapping from raw rows: `pinned`/`unpinned`/`priority-set` (human_priority or upcoming_pinned), `deferred`/`undeferred` (poker-drawer-defer/-undefer), `deleted` (queue_membership), `reordered` (upcoming_rank), `completed` (worklog outcome=complete). 7 unit tests.
- **`GET /api/activity?limit=&since=`** on Poker + Timeline (t-353) — thin wrappers over the helper, returning `{count, entries}`. Limit clamped to [1, 500]. 8 parametrized tests across both UIs — merged stream, limit, since, empty-project.
- **Poker activity side-panel** (t-354) — 280px right-rail, 5s poll, header = `h{heat} · {relative_time}`, body = `{icon} {actor} {verb} {task_id}`. Forge rows muted (opacity 0.72) to keep human steering legible. Collapsible via toggle, hidden below 900px viewport. "view full log →" link deep-links to `/api/activity?limit=500`.
- **E2E trace** (t-355) — `test_activity_e2e.py`: Bellows pin (X-Actor=test:activity) → steering.log → `read_activity` → Poker `/api/activity` → Poker HTML wiring, all in one test. Locks the t-352→t-354 seam.

### Attribution Hardening (trailing v1.9 items)
- **Retro Gap 4 — By-actor breakdown** (t-348) — `smithy steering-retro` JSON now includes `by_actor: [{actor, events}]` sorted descending; markdown grows a `## By actor` section. Enables "which teammate pinned the most this week" at a glance.
- **Retro Gap 1-3 fixes** (t-346) — "Tasks shipped" renamed to "Heats completed" (Forge logs per-heat not per-task); `unique_tasks_touched` added; `shipped_post_pin` dedups by earliest ship heat per task; `task_heats_total` filters denominator to real `t-*` tasks (excludes `generated`/research heats); empty-log footer renders when `steering.log` is missing or empty in window.

### Intent Templates + Regression (t-347, t-351)
- **`smithy init --template=<shape>`** (t-347) — 6 shapes (lib, cli, web, data-pipe, mobile, research) seed identity.md bullets + themes + initiatives on scaffold. `--list-templates` lists available shapes as JSON. Omitting `--template` preserves backwards-compat (blank scaffold).
- **Regression suite** (t-351) — 6 parametrized structural-integrity tests: themes/initiatives round-trip verbatim, unique IDs within a template, every initiative's `theme_id` resolves to a seeded theme, intent bullets render in original order, template label present.

### Documentation (t-350, t-349)
- **`research/activity-side-panel-design.md`** (t-349) — 6 framing Q&As (content, host UIs, freshness, window, interactivity, Forge-event scope), proposed entry schema, `/api/activity` proposal, UI mockup, and the 5 impl candidates (t-352→t-356) with value-theses. This doc is what the MVP shipped against.
- **README + STEERING docs** (t-350) — `smithy steering-retro` added to CLI cheat sheet; new "Intent Templates" section with 6-shape table; new "Steering Attribution" + "Steering Attribution Pipeline" sections with endpoint/field/source tables and example retro output; Timeline routes table gains `/api/steering-log`.

### Hypotheses
| # | Hypothesis | Status | Evidence |
|---|------------|--------|----------|
| H14 | Merging steering + forge into one stream is more useful than two surfaces | ⏳ inconclusive | Shipped to Poker only; pausing before Timeline render pending feedback on whether the mix is legible or cluttered |
| H15 | Verb-mapping from raw log fields is cheap to centralize | ✓ validated | 8 verbs mapped in a 10-line helper; zero coupling to UI code; both Poker+Timeline endpoints landed as 5-line wrappers |
| H16 | Retro gaps surface faster via dogfood than via beta | ✓ validated | First-run dogfood exposed 5 gaps (v1.9 Gap 1-5) before any human used the CLI; 3 fixed in t-346, 1 in t-348, 1 deferred |

### Stats
- **Heats**: 765-775 (11 heats — 4 impl + 2 editing + 2 research + 2 testing + 1 marketing)
- **Tests**: +36 across the block (7 activity helper, 8 activity API, 1 activity E2E, 2 retro Gap 1-3 fixes, 2 retro by-actor, 12 intent templates, 6 template regression, misc)
- **Full suite at v1.10 close**: 193 passing, 3.64s runtime

### Follow-ups queued
- **t-359** — Timeline activity side-panel render (impl, p3) — reuses t-354 CSS/JS at near-zero cost; pending feedback on Poker version
- **t-360** — Click-to-jump task anchors (impl, p3) — gate on user feedback per design doc §Q5

---

## v1.9 — Steering Attribution Pipeline (heats 756-764)

### Philosophy
- **Every human steering event becomes a traceable attribution row.** Before v1.9, "why did this task get reordered?" required git-archaeology across state.json diffs and commit messages. Now there's a single append-only `steering.log` per project with timestamp, heat, actor, task_id, field, before→after, source — wired into every UI mutation endpoint. The Timeline visualizes it; the CLI summarizes it weekly.

### Foundation — `steering.log` + shared logger (t-338)
- **New module `steering_log.py`** at repo root — `log_steering(project_root, actor, task_id, field, before, after, source)` + `read_steering_log(project_root, task_id=, actor=, since=)`. Per-project append-only TSV, 8-column schema, silent on missing state (heat=0 fallback), TSV-escape on embedded tabs/newlines.
- **Poker wire-ups** — `/api/task/<id>/{human-priority, defer, undefer}` and `DELETE /api/task/<id>` now emit attribution rows with `actor=bellows-poker` and fine-grained `source` values (`poker-drawer`, `poker-drawer-defer`, etc.)

### Read Endpoint — Bellows (t-339)
- **`GET /api/project/<name>/steering-log?task_id=&actor=&since=&limit=500`** — newest-first rows for one project. 404 on unknown project, empty list on missing log. 5 tests.
- **Upcoming mutations wire-ups** — `/api/upcoming/{pin, unpin, reorder}` log to the affected project's `steering.log` with `actor=bellows-upcoming`; reorder emits one `upcoming_rank` row per position.

### Timeline Markers (t-340)
- **`GET /api/steering-log`** on Timeline (project-scoped). **`<div class="steering-lane" id="steering-lane">`** rendered inside `.grid-overlay`; JS fetches rows every 7s, positions `.steering-marker` spans by heat-to-pixel mapping. Hover tooltip shows `h{heat} · {actor} · {task_id}` and the `field: before → after` delta. Markers outside `[tl_start, tl_end]` are skipped. CSS in `ui-timeline/static/style.css`.

### Actor Identity Hook — X-Actor (t-342)
- **Optional `X-Actor` request header** on Bellows (`upcoming/{pin,unpin,reorder}`) and Poker (`human-priority, defer, undefer, delete`). Overrides the UI-default actor; empty/whitespace or >64-char values ignored. Enables future multi-agent / scripted steering without code changes.

### Weekly Retro CLI (t-341)
- **`smithy steering-retro [--since=7d|24h|ISO] [--format=markdown|json]`** — renders steering.log + worklog.tsv into a weekly digest: pin events count, unique tasks pinned, tasks shipped, shipped-post-pin table with pin→ship heat lag, average lag, pure-allocator heats (no prior steering). Markdown by default for human reading; JSON for tooling. 5 tests via `click.testing.CliRunner`.

### Dogfood + Follow-ups (t-344)
- **First-run retro on smithy2 itself** exposed 5 gaps captured in `research/steering-retro-first-run.md`:
  - Gap 1 (biggest): "Tasks shipped" counter includes every heat because Forge logs `outcome=complete` per-heat, not per-task — rename + de-dup by task_id (t-346-candidate)
  - Gap 2: pure-allocator denominator mixes task-less rows (research, `generated`)
  - Gap 3: empty `steering.log` produces no hint to the reader (one-line footer fix)
  - Gap 4: no by-actor breakdown (t-347-candidate, waits on multi-actor data)
  - Gap 5: no commit/PR link surface (defer)

### E2E Pipeline Validation (t-345)
- **`tests/test_attribution_e2e.py::test_full_trace_pin_to_timeline_marker`** — single integration test: Bellows pin (with custom `X-Actor`) → `steering.log` file written → Bellows read endpoint surfaces row → Timeline `/api/steering-log` returns it → Timeline HTML contains lane element + marker JS. Validates all 5 components ship together.

### Documentation
- **`research/steering-attribution-audit.md`** — feasibility verdict (partial-yes today via git-log, full-yes with steering.log), 8-column schema proposal, and the 5 impl candidates (t-338→t-342) that landed this block. Value-thesis per candidate.
- **`research/steering-retro-first-run.md`** — dogfood findings above.

### Hypotheses
| # | Hypothesis | Status | Evidence |
|---|------------|--------|----------|
| H11 | A single per-project append-only log is enough for attribution | ✓ validated | Pipeline works end-to-end; zero schema migrations across 5 wire-ups |
| H12 | Attribution has real weekly value (retro as habit-forming artifact) | ⏳ inconclusive | First-run dogfood exposed 5 gaps before any pin data existed — need 1-2 weeks of UI-driven steering to test the thesis |
| H13 | `X-Actor` header cost is low enough to land while logging is fresh | ✓ validated | 4 Poker + 3 Bellows endpoints updated in one heat, 4 new tests |

### Operational Note
- **State.json trailing-garbage incident at heat 761** — `state.json` grew a stray `_version": 1\n}\n` suffix past a valid JSON close, unparseable by the CLI. Cause unknown (possibly a long-running UI writer racing the mtime check). Fixed via `json.JSONDecoder().raw_decode()` truncation. If it recurs, treat as a signal that mtime-check alone is insufficient and add a post-write JSON parse-back verification.

### Stats
- **Heats**: 756-764 (9 heats — 5 impl + 1 research + 2 marketing/editing + 1 testing)
- **Tests**: +21 across the block (12 steering_log helper/wire-ups, 5 bellows upcoming/steering-log, 3 timeline, 5 steering-retro CLI, 1 E2E — some overlap via shared fixtures)
- **Files touched**: new `steering_log.py`, `tests/test_steering_log.py`, `tests/test_steering_retro.py`, `tests/test_attribution_e2e.py`, `research/steering-attribution-audit.md`, `research/steering-retro-first-run.md`; modified `smithy/cli.py`, `bellows/app.py`, `bellows/tests/test_upcoming.py`, `ui-priority-poker/app.py`, `ui-timeline/app.py`, `ui-timeline/templates/index.html`, `ui-timeline/static/style.css`, `tests/test_steering_uis.py`, `CHANGELOG.md`

---

## v1.8 — Steerability: Ranking > Constraints (heats 725-739)

### Philosophy Shift
- **STRATEGY.md**: ranking-first replaces constraint-first steering. The allocator is the executor; humans ship signal via *order*, not rules. Tasks' `human_priority` (sticky int, ascending) overrides Marshal's `priority` until completion or explicit clear.

### Constraints UI Retirement (ini-008 closeout)
- **ui-constraint-board deleted** (t-310); CLI constraint commands + state.json `constraints` block preserved for any surviving programmatic users but de-emphasized (t-318 cleanup — STEERING/QUICKSTART/README/WALKTHROUGH rewired around ranking)
- **docs/retro-agent-teams.md §8** — post-mortem on why constraints didn't earn their keep (t-311)

### Dispatch/ Retirement
- **`dispatch/` module removed** (t-308) — after queue unification (v1.5) and nudge integration, the old dispatcher had no live callers

### Full Steerability Feature
- **Sticky `human_priority`** on tasks (t-312): ascending int, null-by-default, persisted across heats, auto-cleared on `status: complete`
- **Scheduler sort** (t-313): `(human_priority or +inf, priority, id)` — `blocked_by` gating preserved (blocked tasks never lead regardless of priority); `priority_reason` auto-populated as `"ini-XXX rank=N + <signal>"` or `"p{N} + <signal>"`, ≤40 chars; signal vocab = `{recency, poker, stage-balance, blocked-deps-clear}`; wired into `add-task`, `queue-push`, `set-priority`, `set-next-tasks`
- **Poker drawer UI** (t-314, t-319): per-initiative expandable drawer with In-flight / Queued / Shipped-since-viewed sections; row layout `[task-id] [desc] M:p{N} [· priority_reason] [you:—|p{X}] [↓]`; one-click `↓` downrank; `POST /api/initiative/<id>/view` stamps `viewed_at` on expand; `POST /api/task/<id>/human-priority` with `{value: int|null}` sets/clears with mtime-checked save

### Queue-Pop Stale-Head Bug
- **t-317**: fixed `queue-pop` race where a task completed by a concurrent process could still be returned as the queue head. Root cause of the t-295 "race mystery" — not a race, a stale-read. Now revalidates status under mtime precondition.

### Per-Heat Diff View
- **Bellows `/project/<n>/diff?n=K`** (t-306): renders state.json field-level diff between HEAD and HEAD~K commits; JSON sibling at `/api/project/<n>/heat-diff`

### UI Concurrency Safety
- **All 4 steering UIs + Bellows decision endpoints** (t-316) now use mtime-checked writes; `ConcurrentWriteError` surfaces as HTTP 409. GET/SSE paths untouched.

### Testing
- **E2E steerability test** (t-315, `tests/test_e2e_smoke.py::test_steerability_loop_end_to_end`): baseline pick → human override flip via Poker TestClient → blocked-gating preservation → auto-clear on completion
- **Round-trip parser test** (t-305): state.json serialize → parse → compare across fixture corpus
- **312 tests green** across CLI, steering UIs, bellows, e2e

### Stats
- **Heats**: 725-739 (14 heats)
- **Tests**: 312 passing (+10 scheduler sort, +9 poker drawer, +3 concurrency, +1 e2e steerability on top of v1.7's baseline)
- **Files touched**: STRATEGY.md, smithy/cli.py, smithy/tests/test_smithy.py, ui-priority-poker/{app.py, templates/index.html, templates/_task_row.html, static/style.css}, ui-intent-editor/app.py, ui-timeline/app.py, bellows/app.py, tests/test_steering_uis.py, tests/test_e2e_smoke.py, ui-constraint-board/ (deleted), dispatch/ (deleted)

---

## v1.7 — Docs, Timeline Indicator, E2E + Agent Teams Retro (heats 710-719)

### Documentation
- **WALKTHROUGH.md** rewritten as narrative (484 lines): "Alex" walks the tasq-CLI maintainer through init → steering → execution → review in 6 acts, with terminal samples and state.json snippets (`3c2813f`)
- **QUICKSTART.md** added (114 lines): 5-minute copy-pastable recipe, steering UI table with ports, CLI cheat sheet; README header now links QUICKSTART / WALKTHROUGH / STEERING (`5869532`)
- **docs/retro-agent-teams.md** (153 lines): Marshal-seat retrospective — what worked (nudge cycle, separation of concerns, `TASK_COMPLETE` template), friction (persona-cwd bug, Anvil/Forge cross-talk, stale task IDs, CLI gotchas), recommendations (shared cwd contract, cursor field, consider folding Marshal into Anvil), concrete heat+commit citations (`3acb8c6`)

### Forge Persona Rewrite
- **personas/forge/CLAUDE.md** aligned with Agent Teams: cd-first spawn pattern, 6-step heat loop, `TASK_COMPLETE` report template, removed stale `HOOK_DONE` / dispatch references (`b238c43`)

### Timeline Current-Heat Indicator
- **Vertical "now · hN" line** across the bar region, full-height gridline overlay, red pill label (`bd4f3de`)
- **GET /api/current-heat** endpoint; browser polls every 5s and reacts to SSE `state-changed`
- **4 new tests** for the endpoint + indicator render conditions

### Visual Polish (Timeline)
- **Shadow system + gradient bars + status color-coding** (approved=blue, active=green, proposed=yellow-dim, rejected=grey, complete=dark) with hover lift; drag indicator pill shows `h{start} → h{end} ({n}h)`; gridlines; mobile @480px (`e780c58`)

### E2E Smoke Test
- **tests/test_e2e_smoke.py** (190 lines, 23 tests, 1.9s runtime): `TestCLIStateFlow` (5), `TestUIStackOverState` (12 parametrized), `TestNavConsistency` (4), `TestFullSmokeFlow` (2) — scaffolds a tmp project, exercises add-task/queue/start-heat/end-heat, loads all 4 UIs over the same state.json, verifies nav env vars, headline flow CLI heat → Timeline `/api/current-heat` reports 1 (`acac7c4`)

### Port Mismatch Sweep
- `URL_BELLOWS` default **8000 → 8080** across all 4 steering UIs
- **STEERING.md** and **README.md** 8081-8084 → 8001-8004 to match `NAV_LINKS` defaults; README steering table reordered ascending (`cc706ec`)

### UI Reactivity Tests (carryover from batch start)
- **21 tests** for nav bars, refresh button, `/api/state` across all 4 UIs, state-change reactions, env var overrides, empty-state shapes; fixed poker `/api/state` assertion format (`27b4628`)

### Stats
- **Heats**: 710-719 (10 heats)
- **Tests**: 114/114 passing (+23 e2e, +4 timeline indicator, +21 UI reactivity on top of v1.6's 230)
- **Files touched**: CHANGELOG, README, STEERING, WALKTHROUGH, QUICKSTART, personas/forge/CLAUDE.md, ui-timeline (app.py, templates, static), all 4 ui-*/app.py (port defaults), tests/test_steering_uis.py, tests/test_e2e_smoke.py (new), docs/retro-agent-teams.md (new)

---

## v1.6 — Steering UIs Production + Visual Design System (heats 688-709)

### Marshal Agent Completion (ini-015)
- **25 integration tests** for Marshal→Forge dispatch cycle: queue-push nudge, FIFO pop, end-heat nudge, set-next-tasks nudge, busy-session queueing, full e2e
- **Marshal CLAUDE.md** aligned with CLI: startup sequence (drain-nudges, add-task, queue-push), message-driven loop, priority rules
- **Anvil CLAUDE.md** updated: SendMessage coordination patterns (steering change, urgent injection, status check), nudge cycle documentation

### Priority Poker Polish (ini-010)
- **Drag-drop visual feedback**: rotation on drag (-1deg), scale(0.96), shadow elevation, opacity shift
- **Live weight badges**: update on reorder without page reload
- **CSS design system**: `--shadow-sm/md/lg`, `--surface-hover`, weight badge glow (green box-shadow)
- **Responsive**: mobile breakpoint at 480px, touch support
- **15 tests**: render, weight badges, filtering, reorder persistence, approve/reject, /api/state

### Constraint Board CRUD + Polish (ini-011)
- **POST /edit/{id}** endpoint: inline editing of value, stage, description
- **Visual polish**: type-specific left borders (blue=cap, green=floor, yellow=exclude), type badges, progress bars (ok/warn/over), violation glow + shake animation, inactive dimming (45% opacity)
- **Save flash**: "✓ saved" feedback on inline edit
- **Focus rings** on inputs with blue box-shadow
- **16 tests**: add (3 types), edit (value, description, preserve fields, 404), remove, toggle, violation detection

### Intent Editor Enhancements (ini-013)
- **POST /edit-theme/{id}** and **POST /edit-initiative/{id}** endpoints
- **Bug fix**: `_decompose_intent()` `.strip()` → `.rstrip()` — sub-bullets now parse correctly as initiatives
- **Visual polish**: tree connector lines (border-left + border-bottom), collapsible branches with rotating chevron, color-coded status badges (green=active, blue=approved, yellow=proposed)
- **Save flash** and focus rings matching constraint board
- **16 tests**: render, decomposition, apply (themes, initiatives, skip unchecked, history), edit, delete (cascade), /api/state

### Timeline View Tests (ini-012)
- **19 tests** with dedicated fixture (4 initiatives, 2 tasks, planned overlap): rendering, approved/active filtering, rejected/proposed exclusion, update persistence (start/end/multiple/preserve fields), overlap detection, /api/state, range params, clamping

### UI Reactivity (ini-014)
- **Refresh button** on all 4 UIs: ↻ with spin animation
- **GET /api/state** endpoints on Constraint Board and Intent Editor (poker and timeline already had them)
- **Cross-UI navigation bar**: links to all 4 steering UIs + Bellows, active page highlighted, env var config (`URL_POKER`, `URL_CONSTRAINTS`, `URL_INTENT`, `URL_TIMELINE`, `URL_BELLOWS`)
- **Bellows integration**: steering links in project sub-tabs (project, board, decide, direct pages)

### Documentation
- **STEERING.md** (263 lines): philosophy, ASCII architecture diagram, per-UI feature/route/state.json tables, env var config, test commands
- **README** expanded: steering UI section with setup, architecture, cross-nav, test reference

### Stats
- **66 steering UI tests** (15 poker + 16 constraint + 19 timeline + 16 intent editor)
- **25 marshal integration tests**
- **~230 total tests** (145 smithy CLI + 66 steering UI + 16 bellows)
- **709 heats**

---

## v1.5 — Queue Unification + Nudge Integration (heats 634-687)

### Unified Task Queue
- **Removed old hook mechanism** (`.forge-hook.json`, `hook-marshal`) — replaced with single ordered queue
- **`queue-push`** / **`queue-pop`** / **`queue`** / **`queue-clear`** — atomic queue operations on `next_tasks` in state.json
- **`set-next-tasks`** — Marshal sets ordered task list, validates all IDs exist and are pending
- **`set-priority`** — change task priority (0-3)
- **`list-tasks`** — filter by status/stage/initiative, sort by priority, resolve initiative titles

### Nudge System
- **`nudge <persona> <message>`** — send a message to a persona's tmux window; if mid-heat (checkpoint exists), queues to `.smithy-nudge-queue/<persona>.jsonl`
- **`drain-nudges <persona>`** — read and clear queued nudges (JSONL format, handles malformed lines)
- **Auto-nudge** on `queue-push` (→ forge), `set-next-tasks` (→ forge), `end-heat` (→ marshal)
- **`--no-nudge`** flag on queue-push, set-next-tasks, end-heat to suppress

### Session Management
- **`start-all`** — create `smithy2` tmux session with anvil, forge, marshal windows, each running Claude Code
- **`start <persona>`** / **`stop <persona>`** — manage individual persona windows
- **`stop-all`** — graceful (/exit → exit) or `--kill` shutdown
- **`sessions`** — list active persona windows with last-activity timestamps

### Always-On Loops
- **Forge loop rewritten**: check queue → pop → execute → end-heat → repeat (no more allocator-first)
- **Marshal loop rewritten**: queue-based, computes priorities and fills queue for Forge
- **Agent Teams model**: Anvil spawns Marshal and Forge as Claude Code teammates — replaces flat-file dispatch

### Persona Updates
- **Anvil** — lead agent, spawns teammates, coordinates via SendMessage (replaces dispatch files)
- **Marshal** — always-on allocator loop, uses set-next-tasks to assign work
- **Forge** — queue-pop loop, GUPP principle, reports via SendMessage

### Test Coverage (this cycle)
- **40 new tests**: nudge helpers (6), nudge command with tmux mocking (4), drain-nudges (4), sessions/start/stop (14), queue shortcuts (12)
- All tests use `monkeypatch` for subprocess isolation

### Stats
- **30+ smithy commands**
- **687 heats**

## v1.4 — Steering UIs + Constraint Enforcement + Content Expansion (heats 607-633)

### 4 Steering UIs — Research + Prototypes
- **Steering patterns research** — 5 domains (RTS, military C2, product mgmt, ATC, AI tools), 6-mode taxonomy
- **Priority Poker** (`ui-priority-poker/`) — drag-to-rank, click-to-expand (desc + progress + tasks), visual weight gradient, allocation badges (3×/2×/1×), proposed section with approve, kill zone
- **Constraint Board** (`ui-constraint-board/`) — budget caps, floors, excludes, violation detection, toggle activate/deactivate, quick templates
- **Timeline View** (`ui-timeline/`) — Gantt-style bars, drag interactivity (left/right/middle edges), snap-to-5 grid, summary row with over-budget warning
- **Intent Editor** (`ui-intent-editor/`) — bullet-point intent → auto-decompose, diff mode (new items green), delete themes/initiatives, apply to state.json

### Constraint Enforcement
- Allocator reads `constraints` from state.json
- `budget_cap` constraint → stage score suppressed to -1.0
- `floor` constraint → underfunded stage boosted proportionally

### Tutor Content Expansion
- **English Vocab**: 3 new topics (homophones, compound words, connotation) — now 10 topics / 37 exercises
- All 5 subjects now have 10 topics each (except Math with 14)

### New Features
- **Exercise timer** — ⏱ counter on lesson page, counts from page load
- **User page progress bar** — overall completion % across all subjects
- **Bellows STRATEGY.md viewer** — collapsible on Direct tab

### Stats
- **5 subjects**: 50 topics, 201 exercises
- **28 smithy commands**, 172 tests (111 + 16 + 45)
- **4 standalone steering UIs** — each ~200 lines, dark theme, vanilla JS
- **633 heats**

## v1.3 — User Sessions + Creative Writing + Init Fix + Stats (heats 576-600)

### Creative Writing — 5th Subject
- **10 topics** across 5 levels: show-don't-tell, strong verbs, sensory details, sentence variety, eliminating wordiness, voice & tone, figurative language, dialogue, scene vs summary, opening hooks
- **26 exercises**: free_response (rewrites, analysis), multiple_choice (identify technique), fill_in_blank
- Pink accent color (#EC4899)

### User Sessions
- **Cookie-based user ID** with middleware — each user gets isolated progress and cards
- **User switcher** (`/user`): enter name, stored as cookie, displayed in nav bar 👤 tab
- **Per-user storage**: `~/.tutor/users/<id>/progress.json` + `cards.json`
- Backward compatible: no user cookie = global (legacy) progress

### Intent Hierarchy
- **Themes + Initiatives** in state.json with full validation
- **9 CLI commands**: add-theme, list-themes, pause/activate-theme, propose, approve, reject, complete-initiative, list-initiatives
- **Task gating**: `--initiative` on add-task, pick-task filters by initiative status, auto-activates, heats_used tracking
- **Allocator gating**: only eligible tasks affect scoring
- **Bellows Board page**: themes → initiatives, approve/reject from UI, status-colored cards
- **Bellows home badges**: blue proposal count on project cards

### smithy init — End-to-End Fix
- Now generates **CLAUDE.md** (protocol hub)
- Copies **all 4 protocol files** (loop.md, allocator.md, logging.md, reporting.md)
- **Commander's Intent template** in identity.md with placeholders
- Prints **next steps** after init

### New Features
- **Tutor stats page** (`/stats`): subjects, topics completed, cards, streak, per-subject breakdown
- **Bellows live indicator**: pulsing green "running" badge when checkpoint exists
- **`smithy stats` command**: stage distribution, signal counts, theme/initiative summary
- **SW v2**: network-first for localhost (fixes dev caching)

### Stats
- **5 tutor subjects**: Python, Math, English, Logic, Creative Writing — 49 topics, 188 exercises
- **28 smithy commands**, 45 smithy tests
- **172 total tests** (111 tutor + 16 bellows + 45 smithy)
- **600 heats milestone**

## v1.2 — PWA Offline + Content Expansion + Naming (heats 548-567)

### PWA Offline Support
- **Service worker** (`sw.js`): cache-first for `/static/`, network-first with fallback for pages
- **manifest.json**: installable as app (standalone display, teal theme)
- **Offline page**: graceful fallback when network unavailable
- Service worker registration in base.html + `/manifest.json` and `/sw.js` FastAPI routes

### Logic & Critical Thinking — 4th Subject
- **10 topics** across 5 levels: number patterns, odd-one-out, if-then, syllogisms, fallacies, analogies, argument analysis, counterexamples, hidden assumptions, evaluating evidence
- **32 exercises**: math_input, multiple_choice, fill_in_blank, free_response
- Purple accent color with gradient overlay

### New Features
- **Difficulty indicators**: ●●○ dots on exercises (orange, 1-3 scale from curriculum data)
- **Topic review mode**: 🔄 button on completed topics for quick practice replay
- **Bellows Direct tab**: 6 quick-action buttons in 3-col grid (Run 10/20/50, Focus testing/building/design)

### Naming & Cleanup
- Commissioner app → **Bellows** (directory, app title, CSS, pyproject, README, templates)
- Project name: ai-coworker → **the-smithy** (state.json, identity.md)
- Bellows README: comprehensive docs for all 6 screens
- Old `forge-*.sh` scripts removed (636 lines) — all in smithy CLI now

### Stats
- **4 tutor subjects** (Python, Math, English, Logic) — 39 topics, 130 exercises
- **18 smithy commands**, 35 smithy tests
- **158 total tests** (111 tutor + 12 bellows + 35 smithy)
- Patrol clean across all runs

## v1.1 — Visual Design Sprint + CLI Completion (heats 518-547)

### Tutor Visual Redesign
- **Subject cards**: 5px accent bars (was 3px), topic count badges, taller progress bars, stronger accent gradients
- **Welcome card**: "Learn by Doing" copy, feature cards with icons + descriptions, contextual CTA (Start Learning / Continue / Resume)
- **Empty states**: Card-style with dashed borders, emoji icons, rich messaging, guidance CTAs
- **Button system**: 6 utility classes (btn-lg, btn-sm, btn-block, btn-stack, btn-green, btn-mt) — replacing inline styles
- **Monospace fonts**: Unified font stack (JetBrains Mono → Fira Code → Cascadia Code), tab-size: 4, consistent line-height
- **Exercise feedback**: Result icon with pop animation, centered colored title
- **Review session**: Card slide-in animation, celebration screen with icon pop

### Commissioner Visual Redesign
- **Stage colors**: 6 distinct colors (purple research, blue planning, green implementation, yellow testing, orange editing, red marketing)
- **Activity feed**: Stage-colored left borders on heat cards, colored stage badges, value color coding (green/yellow/red)
- **Stage bars**: Color-coded progress fills in project detail view
- **Budget visualization**: Segmented bar showing stage breakdown with legend
- **Decision cards**: 5px priority borders, critical pulse animation, stage-colored badges
- **Empty states**: Dashed borders, emoji icons across all screens

### New Smithy Commands (2)
- `smithy update <target>` — copy protocol files to existing project (replaces forge-update.sh)
- `smithy repomap [target]` — generate research/repo-map.md with file stats, dir structure, key files (replaces forge-repomap.sh)

### Cleanup
- Removed 5 forge-*.sh scripts (636 lines) — all functionality now in smithy CLI (18 commands total)
- 6 new tests for update + repomap (35 smithy tests, 158 total)

### Protocol Wired to CLI (heats 508-517)
- All 3 protocol files rewritten: loop.md, logging.md, allocator.md
- Zero manual state edits — all mutations go through smithy commands
- 2 stress test heats passed with patrol clean
- **New rule**: "NEVER directly edit state.json or worklog.tsv"

## v1.0 — Gas Town Patterns + 500-Heat Milestone (heats 481-500)

### Gas Town Integration Research
- 5 research docs analyzing extension points, state mapping, comms, autonomy/memory gaps
- **Decision: Approach B** — adopt patterns, stay independent

### New Smithy Commands (3)
- `smithy handoff` / `smithy resume` — session cycling (save/restore context across sessions)
- `smithy patrol [--fix]` — discover-don't-track validation (5 checks, auto-repair)
- `smithy sync-stages` — recalculate stage heats from worklog (fixes drift)

### Protocol Updates
- **Step 0** (new): `smithy resume` + `smithy patrol --fix` on session start
- **Step 8**: `smithy handoff` before stopping

### Milestone: 500 Heats
- 16 smithy commands, 29 smithy tests
- 152 total tests (111 tutor + 12 commissioner + 29 smithy)
- Patrol fully clean — zero discrepancies
- Stage heats synced from actual worklog data

## v0.9 — Smithy CLI + Visual Polish + Bug Fixes (heats 286-480)

### Smithy CLI (13 commands)
- `smithy start-heat` / `end-heat` — deterministic heat bookkeeping (counters, cursors, integrals)
- `smithy allocate` — wavefront allocator ported to Python
- `smithy pick-task` / `add-task` / `complete-task` — queue management with auto-incrementing IDs
- `smithy process-feedback` / `process-inbox` — cursor-based feed processing
- `smithy validate` / `status` — state consistency checks and L0/L1 summary
- `smithy init` — project scaffolding (replaces forge-init.sh)
- `smithy commit` — git add + commit with [stage] prefix
- `smithy memory-write` — append notes to MEMORY_DAILY.md
- **23 tests**, installable via `pip install -e smithy/`

### Recall Rhino Palette
- Playful Teal (#00BCD4), Energy Orange (#FF9800), Focus Green (#4CAF50), Review Yellow (#FFEB3B), Sky Blue (#ADD8E6)
- Subject accents: Orange=Python, Teal=Math, Green=English
- Dark mode removed — RR light palette applies everywhere

### Tutor Features
- **Teach It Back** — student explains concept, AI evaluates (Bloom's top level)
- **Topic completion summary** — mastery %, forward CTAs, card creation nudge
- **Card editing** — edit/delete from deck view
- **Python syntax highlighting** — scoped to Python examples only
- **Forward-CTA pattern** — success always leads forward, retry is secondary
- **6 CSS animations** — correct pulse, wrong shake, Socratic slide-up, streak bounce, card reveal, saved check
- **Onboarding welcome card** for first-time users

### Commissioner Features
- **Bottleneck indicator** on project cards
- **Last-active timestamp** from worklog
- **12 forge_reader tests**

### Bug Fixes
- Syntax highlighting no longer breaks non-Python examples
- Forward-CTA pattern across 4 success templates
- Teach It Back promoted to primary green CTA
- Dark mode CSS removed (was hiding RR palette)

## v0.8 — Tutor UI Redesign + Commissioner Polish (heats 181-285)

### Tutor App — Full Redesign
- **3-tab navigation**: Learn, Create, Review (bottom tab bar)
- **Create tab**: student-created flashcards with AI review, deck view, card editing/deleting
- **Review tab**: stats-first landing (due/done/total), SM-2 card player (forgot/hard/good/easy), review summary with strong/weak tracking
- **Teach It Back**: student explains concept, AI evaluates — unlocks after mastery
- **Design palette**: Deep Indigo, Wrong Amber, Hint Blue, subject accent bars, dark mode
- **Session memory**: resume interrupted sessions, exercise progress tracking
- **Streak counter**, weekly progress chart, onboarding welcome card
- **100 tests** across 9 test files (17 card tests, 20 integration tests)

### Commissioner App
- **Tap-to-decide**: approve/defer/reject buttons on decision cards with confirmation + undo
- **Notification tiers**: push/quiet/in-app classification based on priority
- **Activity tab**: day-grouped heat feed with auto-summarization
- **Inbox badges**: cross-project decision count
- **Briefing**: decision queue section with tier counts

### Protocol
- **feedback_cursor**: explicit cursor-based feedback tracking (replaces "first heat" heuristic)
- **Lint→test→fix loop**: run tests before commit, fix failures in-heat
- **Self-critique (Reflexion)**: review before commit — edge cases, intent alignment, missed items
- **forge-repomap.sh**: auto-generate repo map for new project orientation

## v0.5.1 — Interface Operationalization (heats 100-115)

### New Tools
- `forge-status.sh` — zero-effort L2 dashboard (budget, stages, signals, alerts, commits, what's missing)

### Protocol Additions
- `protocol/reporting.md` — L0-L4 information compression layers
- AAR now writes to `aar/` directory (not just outbox)
- `CLAUDE.md` references reporting.md

### v0.6 Planning
- v0.6 plan with 6 tasks: real-project run, repo map, lint→test→fix, self-critique, WhatsApp research, event-sourced state design

### Documentation
- README: forge-status, forge-validate in check-status section
- README: --with-personas example in quick-start
- CHANGELOG: updated through heat 115

---

## v0.5 — Polish + Real-World Validation (heats 39-99)

### Interface Improvements
- **Stoplight signals** (🟢/🟡/🔴) per heat — human reads only yellows/reds
- **Uncertainty field** in worklog — Forge flags uncertain decisions
- **Self-critique** in worklog notes — "Could improve: ..." after each heat
- **Commander's intent** in identity.md — strategic direction for all decisions
- **After-action review (AAR)** generated at end of each run

### Allocator Fixes
- **Soft clamp ±0.5** (was ±1.0) — prevents integral recovery traps
- **Unblocking override** — +0.3 boost for tasks that unblock 2+ others
- **Queued task bonus** — +0.07/ready task prevents dead tasks in low-scoring stages
- **Auto-task generation** — queue replenishes when ≤3 pending tasks

### New Tools
- `forge-update.sh` — update protocol files in existing projects
- `forge-validate.sh` — automated state/protocol integrity checks (19 checks)

### Scaffold Improvements
- `.gitignore` in forge-init.sh scaffold
- Guided templates with HTML comments for identity.md and STRATEGY.md
- Commander's intent template in identity.md

### Documentation
- FAQ/Troubleshooting section in README
- SessionEnd hook setup guide
- Example dashboard output
- Updated file structure diagram with personas, dispatch, hooks

### Research
- Human-AI interface: 10 domains, 22 ideas, top 5 synthesized
- AI worker landscape: Devin, OpenHands, CrewAI, Aider + synthesis
- Adaptive queue management, dead task problem, Telegram bridge design

---

## v0.4 — Real-Project Readiness (heats 39-68)
- Non-dogfood project scaffold tested (todo-cli)
- forge-update.sh for protocol updates
- 8 automated data integrity checks
- v0.4 status reporting to outbox.md

## v0.3 — Personas + Production (heats 26-38)
- 2-persona system: Anvil (interface) + Forge (worker)
- Dispatch files for inter-persona communication
- Value measurement research
- Wavefront visualization in STRATEGY.md

## v0.2 — Robustness + Scaffolding (heats 6-25)
- Beads DAG research → blocked_by task dependencies
- forge-init.sh project scaffolding
- SessionEnd hook for memory distillation
- Checkpoint file for crash recovery
- Fresh-session resume tested (28KB cold start)
- Anti-windup fix for PI controller (0.85 decay)

## v0.1 — Core Protocol (heats 1-5)
- 8-step heat loop
- Wavefront allocator with PI controller
- Flat-file state management (state.json, worklog.tsv)
- Inbox/outbox async communication
- 4-level memory hierarchy
- Git as the substrate
