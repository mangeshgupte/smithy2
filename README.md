# The Smithy

An autonomous AI worker rig that runs inside Claude Code. A small team of
Claude agents (Marshal, one or more Forges, Assembly, with Anvil as the
human's interface) coordinate through flat files and a shared tmux session
to pick up tasks, run "heats" of focused work, merge to `main`, and
self-assess — no external orchestrator, no polling.

**New here?**
[QUICKSTART.md](QUICKSTART.md) (5 min) ·
[WALKTHROUGH.md](WALKTHROUGH.md) (narrative) ·
[STEERING.md](STEERING.md) (steering UIs)

```bash
cd my-project
claude
> Start
```

---

## Architecture

The rig is a **single tmux session** (`forge` by default, overridable via
`FORGE_SESSION`) with one pane per agent. Every agent is a Claude Code
session — they coordinate through files (`state.json`, `worklog.tsv`,
`.assembly-queue.jsonl`, `.smithy-nudge-queue/`), never through direct
RPC.

| Agent | Role | Where it lives |
|---|---|---|
| **Anvil** | The human's interface. Explains state, brainstorms strategy, steers the rig. Spawns nothing — peer agent, read-only on `main` by discipline. | `personas/anvil/` on `main` |
| **Marshal** | The allocator. Computes priorities, orders `next_tasks`, assigns work to a specific Forge (`assigned_forge`). | `.worktrees/marshal/` |
| **Forge** | The executor. One or more. Named by verb: `forge-quench` (primary), `forge-temper`, `forge-anneal`. Pops tasks, runs heats, commits on a per-task branch. | `.worktrees/<forge-id>/` |
| **Assembly** | The integrator. The **only** agent allowed to write to `main`. Rebases each Forge's per-task branch onto `main`, runs the full test suite, merges `--no-ff`, or rejects back to Marshal on severe conflict. | `personas/assembly/` on `main` |
| **Comms** | The narrator. A cron-woken persona that composes a human-facing status report (TL;DR + metrics + bottlenecks) from `state.json`, `worklog.tsv`, and `.assembly-queue.jsonl`. Read-only; reports only — never mutates state or touches `main`. | `personas/comms/` on `main` |

### Heat lifecycle

1. Marshal writes tasks to `state.next_tasks`, pinning each to an
   `assigned_forge`.
2. A nudge fires to that Forge's tmux pane.
3. Forge runs `smithy queue-pop` → `smithy start-heat --task <id>` (which
   auto-checks out `<forge-id>/<task-id>` off the latest `main`) → does
   the work → `git commit` → `smithy end-heat`.
4. `end-heat` runs the **pre-submit pytest gate** (t-427): if tests are
   red, the heat is downgraded to `partial` and the task bounces back
   to `pending`. If green, the task is marked `submitted`, a row goes
   into `.assembly-queue.jsonl`, and Assembly is nudged.
5. Assembly ticks: rebase → tests → `--no-ff` merge → task → `complete`.
   On a severe conflict it calls `assembly-reject`, which flips the
   task back to `pending` with `human_priority += 5` and nudges Marshal.

A task's status walks through:
`pending → in_progress → submitted → {complete | rejected → pending}`.

### Worktree invariant

`main` is sacred. Anvil and Assembly work on it; nobody else. Every
Forge runs from `.worktrees/<forge-id>/`, commits on a per-task branch
(`<forge-id>/<task-id>`), and never touches `main` directly. Marshal
lives in its own worktree too. `smithy patrol` enforces this — a Forge
that's accidentally on `main` fails check #7.

---

## Getting Started

```bash
# From the Smithy repo:
pip install -e smithy/

# Scaffold a new project (blank):
smithy init my-project --target ~/projects/my-project --with-personas

# Or pre-fill with a template (cli | lib | web | data-pipe | mobile | research):
smithy init --list-templates
smithy init my-project --target ~/projects/my-project --with-personas \
    --template cli

# Describe what you're building:
cd ~/projects/my-project
vim identity.md

# Bring up the rig — creates worktrees + tmux panes + starts Claude in each:
smithy up

# In Anvil's pane, tell it to start:
> Start
```

You're now in a running rig. Anvil will confirm the team is up, Marshal
will compute the first queue, and whichever Forge gets pinned the top
task will pick up `queue-pop` and begin heat 1. Watch `rig-events.jsonl`
or the tmux panes to see the cycle live.

---

## The Heat Loop

Each heat is ~5 minutes of focused work by a single Forge on a single
task. The canonical sequence (Forge's perspective):

```bash
smithy queue-pop                            # Claim the next pinned task
smithy start-heat <stage> --task <task-id>  # Writes checkpoint, auto-branches
# ... do the work, git add, git commit ...
smithy end-heat <value> <signal> "<notes>"  # Gate + log + nudge
```

`end-heat` self-assessment values (used by the allocator):

| Value | Meaning |
|---|---|
| 0.9–1.0 | Major breakthrough |
| 0.7–0.8 | Solid progress |
| 0.5–0.6 | Some friction |
| 0.3–0.4 | Mostly setup |
| 0.1–0.2 | Stuck |

Signal: 🟢 normal · 🟡 below-target or stalled · 🔴 rollback or regression.

### Outcomes

| Outcome | Written by | Meaning |
|---|---|---|
| `complete` | end-heat | Legacy N=1 path. Task done, worklog row emitted. |
| `submitted` | end-heat (Assembly enabled) | Forge committed to its branch; Assembly owns the merge. |
| `merged` / `merged-with-resolution` | Assembly | Integrated into `main`. Second worklog row (✅/🔀). |
| `rejected` | Assembly | Severe conflict or test fail; task flipped back to `pending`, `human_priority += 5`, Marshal nudged (🚫). |
| `partial` | end-heat | Pre-submit pytest gate tripped; task back to `pending`, Forge re-iterates next heat. |

---

## Common Operations

### Bring the rig up / down

```bash
smithy up                      # Create tmux session + worktrees + start Claude
smithy up --force              # Kill existing session and recreate
smithy up --dry-run            # Print panes that would be created
scripts/start-smithy.sh        # Re-tile panes in the running session
scripts/stop-smithy.sh         # Graceful shutdown
```

### Peek at state

```bash
smithy status                  # At-a-glance: heats, stages, budget
smithy queue                   # Current next_tasks with priority + stage
smithy task-tree               # Open-task DAG grouped by initiative
smithy task-tree --stuck       #   …only blocked-by-unmet tasks
smithy task-tree --json        #   …structured output
smithy list-tasks --status pending --stage testing
smithy sessions                # tmux panes in the rig
```

### Coordinate

```bash
smithy queue-push <task-id> --forge forge-quench   # Marshal assigns work
smithy queue-pop --forge forge-quench              # Forge claims work
smithy set-next-tasks <id1> <id2> ...              # Marshal re-orders queue
smithy nudge <persona> "<message>"                 # Live tmux send
scripts/nudge.sh <persona> "<message>"             # Same, via shell
```

### Debug

```bash
smithy patrol --fix                   # Validate state, auto-repair (9 checks)
smithy rig-replay --since 100         # Pretty-print recent rig events
smithy rig-replay --event assembly    #   …filter to assembly_tick_*
smithy witness-check                  # Per-Forge health + heartbeat staleness
smithy stats                          # Heat rate, stage heat distribution
smithy steering-retro --since=7d      # Weekly digest: pins, ships, pin→ship lag
```

---

## Files & State

Everything the rig knows is on disk. Inspect with `cat`, edit with `vim`,
audit with `git log`.

| File | Role | Written by |
|---|---|---|
| `state.json` | Queue, next_tasks, stages, allocator integral, parallel.forges registry, initiatives, themes | Every `smithy` state-mutating command, under an exclusive flock (`state_lock`, t-426) |
| `worklog.tsv` | Append-only heat log. One row per `end-heat`; a second row per Assembly outcome. Columns: `timestamp, heat, stage, task_id, outcome, value, signal, notes, forge_id` | `end-heat`, `assembly-merge`, `assembly-reject` |
| `.assembly-queue.jsonl` | FIFO of `{forge_id, task_id, branch, sha, submitted_at}` rows for Assembly to drain | `end-heat` when outcome=submitted |
| `rig-events.jsonl` | Append-only telemetry: `forge_started`, `forge_ended_*`, `assembly_tick_*` (with `latency_ms`), `queue_push/pop`, nudges (t-425) | All CLI commands that cause a state transition |
| `.smithy-nudge-queue/<persona>.jsonl` | File-queue fallback for nudges that couldn't reach a tmux pane | `nudge`, auto-fallback in `_nudge_persona` |
| `assembly-log.jsonl` | Assembly's per-merge audit log | `assembly-tick` |
| `inbox.md` | Human drops ideas here; Marshal triages | Human |
| `feedback.md` | Human steers quality (Forge reads on idle) | Human |
| `outbox.md` | End-of-run digests + periodic status reports | Anvil, Forge |
| `steering.log` | Every human steering event (pins, reorders) — used by `steering-retro` | Poker / Bellows / Timeline UIs |

All agent-shared files are anchored at the MAIN repo root. `smithy`
resolves paths via `main_repo_root()` so every worktree reads and
writes the same file (t-419 / t-422).

---

## Comms

Comms is a read-only persona that produces human-facing status reports —
a TL;DR over the rig's progress, key metrics, and current bottlenecks. It
composes prose on top of the numbers `smithy comms-snapshot` computes from
`state.json`, `worklog.tsv`, and `.assembly-queue.jsonl`. It reports only:
it never mutates state, queues tasks, or touches `main`.

- **Cadence.** A cron line wakes it every 5 minutes (override with
  `FORGE_COMMS_INTERVAL`). `scripts/start-smithy.sh` installs the line via
  `scripts/_comms-cron.sh install`; `stop-smithy.sh` removes it. The
  managed line looks like:

  ```cron
  */5 * * * * /abs/path/to/scripts/comms-tick.sh
  ```

  `comms-tick.sh` is a safety wrapper: it exits silently unless the rig is
  up (tmux session live, `halt_flag` false, comms window present), then
  nudges the Comms pane to report.

- **Reports.** Written under `personas/comms/reports/`.

- **Disable.** Set `FORGE_COMMS_WINDOW=''` — this opts out of the comms
  tmux window, the cron install, and patrol check #18 (the comms
  cron/window health check). With it empty, Comms is skipped entirely.

## Bellows

A FastAPI dashboard for managing Forge projects from a browser: morning
briefings, decision queues, initiative board, activity sparklines, direct
commands.

## Steering UIs

Three standalone FastAPI apps, each a different steering metaphor.

`scripts/start-smithy.sh` (t-477) launches Bellows + all three steering
UIs as a single tmux window named `ui` — one pane per uvicorn — so
start/stop are symmetric with `scripts/stop-smithy.sh --ui-only`
(t-468). Set `FORGE_UI_WINDOW=""` to skip the ui window entirely. To
run an individual service by hand:

```bash
cd bellows           && uv run uvicorn app:app --port 8080
cd ui-priority-poker && uv run uvicorn app:app --port 8001
cd ui-intent-editor  && uv run uvicorn app:app --port 8003
cd ui-timeline       && uv run uvicorn app:app --port 8004
```

| UI | Port | What it does |
|---|---|---|
| **Priority Poker** | 8001 | Drag-to-reorder initiative cards. Rank determines what Forge works on next. |
| **Intent Editor** | 8003 | Write natural-language outcomes. System decomposes into themes + initiatives. |
| **Timeline View** | 8004 | Gantt-style bars for each initiative; drag to allocate budget. |

All three include SSE live updates, a JSON API (`/api/state`), and a
cross-UI nav bar (URLs configurable via `URL_POKER` / `URL_INTENT` /
`URL_TIMELINE` / `URL_BELLOWS` env). Full docs: [STEERING.md](STEERING.md).

### Steering attribution

Every human steering event writes a row to `steering.log`
(`timestamp · heat · actor · task_id · field · before→after · source`).
`smithy steering-retro --since=7d --format=markdown` emits a weekly
digest: pins made, tasks shipped post-pin, avg pin→ship lag in heats,
by-actor breakdown. Pass `X-Actor: <name>` on Bellows/Poker mutations
to override the default UI actor.

---

## Built With The Smithy

The Smithy dogfoods itself. Over 800 heats it has built:

- **The Smithy protocol** itself — the system you're reading about.
- **Parallel Forges at N=3** — `forge-quench`, `forge-temper`,
  `forge-anneal` run concurrently with Assembly as sole integrator.
- **AI Tutor** — 5 subjects, PWA offline, SM-2 spaced repetition, 111
  tests.
- **Bellows** — project dashboard with initiative board, live run
  indicator, stage-colored activity feeds, segmented budget bars.

## Design Principles

- **Prose is the orchestrator.** CLAUDE.md + protocol files. No framework.
- **Flat files.** state.json, worklog.tsv, markdown. Inspect with `cat`.
- **Git is the substrate.** Every heat commits; Assembly is the only
  writer to `main`. The record is sacred.
- **Budget-bounded.** Never exceeds allocated heats. Say "Run N" to extend.
- **Single source of truth.** Every agent-shared file (state.json,
  worklog.tsv, queues, telemetry) lives at the MAIN repo root and is
  mutated under an exclusive flock. Worktree-local copies are stale
  snapshots; `smithy` always resolves to main.
- **Self-directed.** Marshal computes priorities, Forge iterates,
  Assembly integrates. The human intervenes via steering UIs, inbox
  drops, or `scripts/nudge.sh anvil '<msg>'` for a sync escalation.
