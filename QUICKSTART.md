# Quick Start — The Forge in 5 Minutes

The 30-second card. For the narrative tour, see [WALKTHROUGH.md](WALKTHROUGH.md). For steering UIs, see [STEERING.md](STEERING.md).

---

## Prereqs

- Python 3.9+, `tmux`, `git`, and [Claude Code](https://claude.com/claude-code).

## 1. Install

```bash
cd smithy2/
pip install -e smithy/
smithy --help        # should list ~28 commands
```

## 2. Scaffold a project

```bash
smithy init my-app --target ~/projects/my-app
cd ~/projects/my-app
$EDITOR identity.md  # write: intent, success criteria, boundaries
```

## 3. Start the team

```bash
smithy start-all     # tmux session: anvil + marshal + forge
tmux attach -t smithy2
```

In the **anvil** window, type:

```
> Start
```

Anvil spawns Marshal and Forge as Agent Teams teammates. Budget: 100 heats by default, one heat ≈ 5 minutes of work.

## 4. Steer (pick one)

Open any of these in a browser:

| UI | URL | Use |
|---|---|---|
| 🎯 Intent Editor | http://localhost:8003 | Write bullets → decomposed into themes + initiatives |
| 🃏 Priority Poker | http://localhost:8001 | Drag to rank, click to approve |
| 🛡️ Constraint Board | http://localhost:8002 | Budget caps, floors, excludes |
| 📅 Timeline | http://localhost:8004 | Schedule initiatives across heats |
| 🔔 Bellows | http://localhost:8080 | Multi-project dashboard |

Or via CLI:

```bash
smithy add-theme "Testing"
smithy propose th-001 "Unit tests" "Full parser coverage"
smithy approve ini-001
```

Marshal watches `state.json` — any change wakes it, it generates tasks, and pushes them to Forge's queue. Forge pops, executes, commits every heat.

## 5. Watch it work

```bash
git log --oneline       # one commit per heat
smithy status           # budget + queue snapshot
smithy stats            # per-stage breakdown
cat worklog.tsv         # every heat, with self-assessed value + signal
```

Ask Anvil `> what's the status?` for a full report.

## 6. Stop / resume

```bash
smithy stop-all         # graceful (sends /exit to each window)
smithy stop-all --kill  # immediate

smithy start-all        # resume — reads handoff, picks up where it left off
```

---

## Cheat Sheet

```bash
# Heat loop (Forge does these; you usually don't)
smithy queue-pop
smithy start-heat <stage>
smithy end-heat <value> <signal> "<notes>"

# Steering
smithy add-task <stage> "<desc>" --initiative <ini-id>
smithy add-constraint budget_cap --stage testing --value 40
smithy queue-push t-001 t-002 t-003

# Feedback (async; Forge reads between heats)
echo "- tests need more edge cases" >> feedback.md
```

## Principles

- **Every heat commits.** The record is the artifact.
- **Flat files.** Everything inspectable with `cat`.
- **Budget-bounded.** Forge never exceeds allocated heats.
- **You steer, the system runs.** Priorities from you; execution from the team.

---

**Next:** Read [WALKTHROUGH.md](WALKTHROUGH.md) for a full scenario, or [STEERING.md](STEERING.md) for the UIs.
