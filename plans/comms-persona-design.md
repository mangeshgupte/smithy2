# Comms Persona — Design

**Status:** draft (Anvil, 2026-04-18)
**Initiative:** TBD (candidate: new ini-023 *Human-Facing Telemetry*, or fold into ini-019 *Forge Observability*)

## What this is

A new persona, **Comms**, whose only job is to report Smithy status to the human on a fixed cadence. Not a coordinator, not a doer — a *telegrapher*. It reads the shared record, writes a structured report, optionally fires a push notification, and goes back to sleep.

Comms is the answer to: *"I want to glance at one place every few minutes and know whether the rig is healthy and what's moving."*

## Goals

- Periodic, automatic status updates without the human needing to ask Anvil
- One canonical report file per day, append-only, scrollable + greppable
- Bottleneck explanations, not just metrics — narrative where it earns its keep
- Survives smithy restarts; never produces stale reports when smithy is down
- Costs are predictable and bounded (one fresh state read per wake)

## Non-goals

- Comms does **not** make decisions, file tasks, or steer the rig (that's Anvil/Marshal)
- Comms does **not** modify state.json, queue, or worklog (read-only)
- Comms does **not** replace Anvil's interactive status reports — those stay on demand
- No web UI, no Slack integration, no email digests in v1

## Key decisions (locked with human)

1. **Lifecycle:** persistent Claude session in its own tmux window, woken by **system cron** via `nudge.sh comms` every 5min (default; tunable)
2. **Context:** **clear on every wake** — each report is independent, deltas come from reading prior report file on disk
3. **Report format:** **layered TL;DR + detail** — 5-line summary at top, sections (metrics, initiatives moved, bottlenecks, what's next, anomalies) below
4. **Output:** markdown report at `personas/comms/reports/YYYY-MM-DD.md`, appended one section per wake separated by `---`; pane shows live stream

## Architecture

```
                 ┌─────────────────────┐
   system cron ──┤ scripts/comms-tick.sh │── if smithy alive ─→ scripts/nudge.sh comms "report now"
                 └─────────────────────┘                                │
                                                                       ▼
                                            ┌───────────────────────────────────┐
                                            │ tmux: forge:comms (Claude session) │
                                            │  /clear                            │
                                            │  read state.json, worklog, etc.    │
                                            │  read previous wake's report (Δ)   │
                                            │  write today's report.md           │
                                            │  optionally fire notification      │
                                            │  idle                              │
                                            └───────────────────────────────────┘
                                                        │
                                                        ▼
                                           personas/comms/reports/YYYY-MM-DD.md
```

## Components

### 1. Persona files

```
personas/comms/
├── IDENTITY.md          # who Comms is — character, voice, refusals
├── CLAUDE.md            # how Comms works — wake cycle, files to read, report format spec
├── memory/MEMORY.md     # durable learnings (e.g., "human prefers metric tables not paragraphs")
└── reports/
    └── YYYY-MM-DD.md    # one file per UTC day, appended each wake
```

`IDENTITY.md` core: "You are Comms — the telegrapher. You read the record and write the report. You don't decide. You don't fix. You report."

`CLAUDE.md` core: the wake cycle (clear → read → diff → write → notify → idle), the exact report skeleton, the list of state files to consult.

### 2. Tmux window — `comms`

New window in the `forge` tmux session, alongside `main` and `ui`. Single pane. Cwd: `personas/anvil/` (read-only by discipline; matches Anvil's posture). Launches `claude` with `--persona comms` (or equivalent) and immediately reads `IDENTITY.md` + `CLAUDE.md`.

`start-smithy.sh` adds the window after `ui`, then re-selects `main:0` so the human's control lands in the main window (per requirement). `stop-smithy.sh` kills the `comms` window symmetrically.

### 3. Cron entry

```cron
*/5 * * * * /Users/mangesh/vibes/smithy2/scripts/comms-tick.sh
```

`comms-tick.sh` is the safety wrapper:
1. Check `tmux has-session -t forge` — if no, exit silently
2. Check `parallel.halt_flag` in state.json — if true, exit silently (no reports during halt)
3. Check `tmux list-windows -t forge | grep comms` — if pane missing, log warning to stderr and exit
4. Otherwise: `scripts/nudge.sh comms "report now"`

`start-smithy.sh` installs the cron line via `crontab -l | grep -v comms-tick.sh; echo "<line>"` rewrite.
`stop-smithy.sh` removes the line via the inverse.

(Alternative: `launchd` plist for macOS-native scheduling. Cron is simpler and matches "real cron" intent; revisit if cron fires miss after sleep/wake.)

### 4. Wake-up flow (Comms-side)

When nudged:
1. Output `/clear` as first line — Claude Code clears context
2. Read `personas/comms/CLAUDE.md` (re-establishes role; cached after first wake)
3. Read state files (see §5)
4. Read prior section of today's `reports/YYYY-MM-DD.md` for delta computation
5. Compose new report section (per format spec, §6)
6. Append section + `---` separator to today's report file (create file if first wake of day)
7. Evaluate push triggers (§7); fire notification if any tripped
8. Idle — wait for next nudge

Steps 2-7 are done in a single Claude turn; idle is just "no further action."

### 5. State sources

Read each wake (size in parens is rough cap):

| File | Why |
|---|---|
| `state.json` (~300KB) | budget, parallel.forges, queue (filter to non-complete), initiatives, next_tasks, halt_flag |
| `worklog.tsv` (tail ~50 lines) | recent heat outcomes, who did what |
| `.assembly-queue.jsonl` | Assembly backlog depth |
| `.assembly-rejects.log` (if exists) | recent rejection reasons |
| `inbox.md` | un-triaged human input |
| `personas/comms/reports/YYYY-MM-DD.md` (tail) | prior section for delta |
| `git log --oneline -15` | recent merges sanity check |

Not read: per-forge MEMORY files (too volatile), per-forge queue files (covered by state.json queue field), STRATEGY.md (slow-moving; read once at start of day if at all).

### 6. Report format (locked with human)

```markdown
## YYYY-MM-DD HH:MM UTC · heat N/M (P% used)

**TL;DR**
- <one line: rig health + what's moving>
- <one line: most important merge/event since last report>
- <one line: top bottleneck if any, else "no bottlenecks">
- <one line: what to watch on next report>
- <one line: budget runway estimate>

### Metrics

| | now | Δ vs prior |
|---|---|---|
| Heats used | N | +K |
| Forges active | n/N | — |
| Assembly queue depth | D | ±X |
| Patrol issues | P | ±Y |
| Last 30min: green/partial/rejected | a/b/c | — |
| Tasks merged this report | M | — |

### Initiatives moved
- **<ini-id> (title)** — what landed, current heat count, momentum signal

### Bottlenecks
- <numbered, with explanation, cost in heats, suggested action — or "none">

### What's next
- <next_tasks contents with assignment + initiative context>

### Anomalies / patrol residue
- <patrol issues filtered to non-trivial; known-benign drift summarized in one line>

---
```

Length target: TL;DR ≤ 5 lines; full section ≤ 80 lines. If a section is empty (e.g., no bottlenecks), render `_none_` rather than omitting — preserves diffability.

### 7. Push notifications (v1: opt-in, narrow)

Comms only **communicates state**; it does not detect, diagnose, or fix stuck agents (that's separate work — patrol check or watchdog, see Out-of-scope below). Push notifications fire `osascript -e 'display notification ...'` (macOS native) only when reporting-worthy facts cross a threshold:

- Halt flag toggled since last report
- Patrol issue count jumped by ≥ 3
- ≥ 3 rejections of the same `task_id` in the report window (the "TestSyncStages" pattern)
- Budget remaining drops below 10%
- Assembly queue depth exceeds 2× n_forges (back-pressure ceiling)
- All forges idle for > 2 consecutive Comms cycles (10min) **as observed in state.json/heartbeats** — Comms reports the fact; root-cause investigation is the human's call (or a future watchdog's)

### Out-of-scope (explicitly)

- **Detecting stuck/wedged agents** — Comms doesn't grep panes, doesn't classify "blocked vs idle," doesn't diagnose Marshal. If state.json says a forge is idle and has been for 10min, Comms reports that *one fact*. The structural fix for silent-blocked agents (Marshal at stdin prompt, etc.) belongs in a separate ticket: candidates are a patrol check (`scripts/patrol` greps each pane tail for the prompt-with-cursor pattern), a Marshal protocol change (auto-escalate via nudge to Anvil instead of waiting on stdin), or a dedicated watchdog process.
- Filing tasks, mutating queue, modifying state.json — Comms is read-only.
- Acting on the reports it generates — that's Anvil + the human.

Otherwise: silent. Rationale — cron-driven 5min cycle could be noisy; only interrupt the human for things that change the rig posture.

Channel can be swapped (terminal-notifier, Slack webhook) without changing trigger logic.

## Implementation tickets (ordered)

T1. **Scaffolding** — create `personas/comms/{IDENTITY,CLAUDE}.md`, empty `memory/MEMORY.md`, `reports/.gitkeep`. Write the persona prompts. *(1 heat, planning)*

T2. **Tmux window in start-smithy.sh** — add `comms` window after `ui`; ensure final `select-window -t main:0`. Update `stop-smithy.sh` to symmetrically kill. Tests for both. *(1 heat, implementation)*

T3. **`scripts/comms-tick.sh` safety wrapper** — the 4-check guard (session, halt, pane, then nudge). Tests for each gate. *(1 heat, implementation)*

T4. **Cron install/uninstall** — extend `start-smithy.sh` and `stop-smithy.sh` with crontab line management. Idempotent (running start twice doesn't duplicate). Tests via `crontab -l` mock. *(1 heat, implementation)*

T5. **First wake — minimum viable report** — wire prompt that reads state.json + worklog tail and writes the TL;DR + Metrics sections only. Skip Initiatives/Bottlenecks/Push for v1. *(1 heat, implementation)*

T6. **Initiatives moved + Bottlenecks sections** — full per-initiative diff, bottleneck detection (group rejections by task_id, flag stalls, classify patrol issues). *(1-2 heats, implementation)*

T7. **Push notifications** — implement triggers per §7. Make trigger thresholds configurable in state.json under `comms.thresholds`. *(1 heat, implementation)*

T8. **Daily file rollover** — handle UTC midnight: new file, prior day's file becomes immutable archive. *(1 heat, implementation)*

T9. **Documentation** — README section, identity.md note, patrol check that comms cron is installed when smithy is up. *(1 heat, implementation)*

**Total budget:** 8-10 heats. Suggest gated dispatch: T1-T5 first (MVP), then human review, then T6-T9.

## Testing strategy

- **Unit:** `comms-tick.sh` gates (mock tmux, mock state.json), report-section composition (golden-file tests), push-trigger logic
- **Integration:** end-to-end on a mock state — `comms-tick.sh` fires, pane writes report, file appears
- **Smoke:** with rig running, force a wake via `scripts/nudge.sh comms "test"`, inspect resulting section in report file
- **Regression:** if Comms fails to write a report in 3 consecutive cycles, patrol surfaces it as an issue

## Rollout

1. Land T1-T5 behind `FORGE_COMMS_ENABLED=0` default. Manual nudge for testing.
2. Human reviews 3-5 sample reports against real rig activity. Adjust prompts.
3. Land T6-T9. Flip default to `FORGE_COMMS_ENABLED=1`.
4. After 1 week of operation, evaluate: cadence right? push thresholds right? sections useful or noisy?

## Open questions for human

1. **Initiative ID** — new ini-023, or fold under existing initiative? My recommendation: new ini-023, since this is a distinct human-facing capability (not just internal observability).
2. **Cadence default** — 5min was your stated default. Confirm? (My instinct: try 10min first; 5min may be noisier than useful at the current heat rate of ~12/hr.)
3. **Push channel** — macOS notification only for v1, or also Slack/email? (v1 keeps it local.)
4. **Memory** — does Comms accumulate memory like other personas (e.g., "human prefers numbers over prose")? My recommendation: yes, same pattern as Anvil.
