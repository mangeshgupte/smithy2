# The Forge — Autonomous AI Coworker

An AI worker that operates in bounded 5-minute heats, self-directs across project stages, and communicates asynchronously with a human.

## How It Works

Give it a budget. Point it at a project. Walk away. It works.

```
cd ~/vibes/ai-coworker
claude
> Run 20 heats.
```

The Smith (the AI worker) reads `CLAUDE.md`, follows the protocol, and loops autonomously:

1. **Load context** — reads state, inbox, memory, worklog
2. **Pick a stage** — wavefront allocator computes where effort is most valuable
3. **Execute** — 4 minutes of focused work on one task
4. **Log** — worklog entry, state update, memory append, dashboard print
5. **Repeat** — until budget exhausted

**After each heat, you see a dashboard like this:**

```
── Heat 14 [testing] ──────────────────────────────
Task: Live keep/discard test — deliberate bad edit, rollback confirmed
Value: 0.8 | Outcome: complete

Stage          Progress     Heats  Target
research       ██████░░░░    60%    5    .19
planning       █████░░░░░    45%    3    .17
implementation ███████░░░    65%    7    .07
testing        ████░░░░░░    40%    4    .22
editing        ████░░░░░░    40%    4    .20
marketing      ████░░░░░░    35%    3    .15

Budget: 14/30 | Overall: 48% | Next: editing
────────────────────────────────────────────────
```

## The Wavefront Allocator

Six stages form a dependency chain:

```
research → planning → implementation → testing → editing → marketing
```

Each stage's allocation = `prerequisite_readiness × (1 - own_progress)`. Effort naturally flows through the chain as each stage reaches sufficiency — heavy research early, then planning, then implementation, etc. No hardcoded phase transitions.

## Human-AI Communication

**During a session**: type messages between heats, or say "Focus on X" to redirect.

**Async**: edit `inbox.md` from another terminal. The Smith reads it at the start of each heat.

**Ideas**: provide via prompt (`Idea: ...`) or inbox.md. Each idea flows through a pipeline: capture → evaluate → track → acknowledge. Check `inbox.md` for status of every idea.

**Status**: read `outbox.md` or watch the ASCII dashboard printed after each heat.

## File Structure

```
CLAUDE.md              ← The brain (30-line hub)
protocol/
  loop.md              ← 8-step heat loop
  allocator.md         ← Wavefront + PI controller + unblocking override
  logging.md           ← Worklog, dashboards, stoplight signals, self-critique
  reporting.md         ← Information compression layers (L0-L4)
identity.md            ← Project context + commander's intent
STRATEGY.md            ← Living strategic plan (updated every ~5 heats)
state.json             ← Budget, stages, queue, allocator state
worklog.tsv            ← Append-only heat log
inbox.md / outbox.md   ← Async human-AI messages
MEMORY_DAILY.md        ← Working memory (consolidated every 6 heats)
MEMORY_WEEKLY.md       ← Validated patterns
research/              ← Research artifacts
plan.md                ← Living plan with version roadmap
.gitignore             ← Excludes checkpoint and output files
personas/              ← Optional multi-persona sessions
  anvil/CLAUDE.md      ← Human interface (strategy + explain)
  forge/CLAUDE.md      ← Autonomous worker
dispatch/              ← Inter-persona communication
  anvil-to-forge.md    ← Direction from Anvil
  forge-to-anvil.md    ← Reports from Forge
hooks/                 ← SessionEnd hook for memory distillation
aar/                   ← After-action reviews (generated at end of each run)
forge-status.sh        ← Zero-effort dashboard (L2 reporting layer)
forge-validate.sh      ← Automated state/protocol integrity checks
forge-update.sh        ← Update protocol files in existing projects
CHANGELOG.md           ← Version history
```

## Design Influences

- **Autoresearch**: 5-minute bounded loops, "NEVER STOP", modify-commit-run-log
- **Gas Town**: GUPP principle, three-layer persistence (identity/sandbox/session)
- **NanoClaw**: Messaging patterns, per-group isolation
- **AI Collaborator**: Git-native structured disagreement
- **Memory Substrate**: Token-budgeted context assembly, episodic store

## Examples

**Start a new project (2 minutes):**
```bash
# From The Forge repo:
./forge-init.sh my-saas-app ~/projects/my-saas-app

# With multi-persona support (Anvil + Forge):
./forge-init.sh my-saas-app ~/projects/my-saas-app --with-personas

# Edit the generated files:
vim ~/projects/my-saas-app/identity.md    # Describe your project
vim ~/projects/my-saas-app/STRATEGY.md    # Set your vision and roadmap

# Initialize git and start:
cd ~/projects/my-saas-app
git init && git add -A && git commit -m "[init] The Forge scaffold"
claude
> Run 20 heats.
```

**Drop in ideas while it's working:**
```
> Idea: Use SQLite instead of flat files for the data layer.
```
The Smith logs this to inbox.md, evaluates it, and either creates a task or defers it.

**Redirect priorities:**
```
> Focus on testing.
```
Testing gets 2x priority boost in the allocator until you clear it.

**Check what happened while you were away:**
```bash
cat outbox.md          # Smith's status updates and questions
cat worklog.tsv        # Every heat logged with stage, outcome, value
cat inbox.md           # Your ideas + what happened to each one
cat STRATEGY.md        # Current project state at a glance
```

**Continue a paused run:**
```
> Run 10 heats.
```
Adds 10 to the budget. Picks up exactly where it left off.

## Personas

The Forge has two personas, each running as a separate Claude Code session:

| Persona | Name | Role | Start Command |
|---------|------|------|---------------|
| **Interface** | **Anvil** | Your single point of contact. Explains state, brainstorms, dispatches. | `cd personas/anvil && claude` |
| **Worker** | **Forge** | Autonomous engine. Runs all 6 stages (research→marketing) via wavefront. | `cd personas/forge && claude` |

**Typical workflow:**
```
You ↔ Anvil      "What happened?" → explains (Lens hat)
                  "What next?"     → brainstorms (Strategy hat)
                  "Do it"          → dispatches to Forge
       ↓
     Forge        (autonomous: research, plan, implement, test, edit, market)
```

**Communication** via flat files in `dispatch/`:
- `dispatch/anvil-to-forge.md` — Anvil sends direction
- `dispatch/forge-to-anvil.md` — Forge reports results

## SessionEnd Hook (Automatic Memory)

The Forge can automatically distill session transcripts into `MEMORY_DAILY.md` when a Claude Code session ends.

**Setup:**

1. The hook script lives at `hooks/session-end-forge.sh`.

2. Add it to your Claude Code settings (`.claude/settings.json` in the project root):
```json
{
  "hooks": {
    "SessionEnd": [
      {
        "type": "command",
        "command": "./hooks/session-end-forge.sh"
      }
    ]
  }
}
```

3. The hook will:
   - Detect if the session was running in The Forge directory
   - Read the last 200 lines of the session transcript
   - Use Claude to distill key decisions, progress, and blockers into `MEMORY_DAILY.md`
   - Only runs for sessions in the Forge project tree

**Note**: The hook uses `claude -p` (programmatic mode) to call Claude for distillation. Make sure Claude CLI is available in your PATH.

## FAQ / Troubleshooting

**Q: The Smith seems stuck on one stage and won't do implementation work.**
The allocator uses a PI controller with integral memory. If a stage was over-allocated early, its integral goes negative and recovery takes time. Solutions:
- Say "Focus on implementation" to apply a 2x priority boost
- Check `state.json` → `allocator.integral` — if any value is at -0.5 (clamped), the stage is in recovery
- The unblocking override automatically boosts stages with tasks that unblock 2+ other tasks

**Q: How do I continue a run in a new Claude Code session?**
Just start a new `claude` session in the same directory and say "Run N heats." The Smith reads `state.json` and picks up where it left off. Cold start is ~28KB of context.

**Q: How do I give the Smith an idea while it's running?**
Either type it directly between heats (`Idea: use SQLite instead of flat files`) or edit `inbox.md` from another terminal. Both are processed the same way.

**Q: The Smith is doing research when I want it to build things.**
Say "Focus on implementation" — this applies a 2x priority boost. Or add specific tasks to `state.json` queue manually.

**Q: How do I see what happened while I was away?**
Check these files: `outbox.md` (status updates), `worklog.tsv` (every heat), `STRATEGY.md` (current state), `inbox.md` (your ideas + dispositions).

**Q: Can I use this on an existing project (not a new one)?**
Yes. Run `forge-init.sh my-project .` from your project root. It creates Forge files alongside your existing code. The Smith will read `identity.md` to understand what to work on.

## Key Principles

- **No Python.** The entire system is prose — CLAUDE.md + protocol files. Claude Code is the runtime.
- **Flat files.** state.json, worklog.tsv, markdown. Inspect with `cat`, edit with `vim`.
- **Git is the substrate.** Every heat's work is committed. The record is sacred.
- **Budget-bounded.** Never exceeds allocated heats. Say "Run N" to extend.
- **Self-directed.** Generates its own tasks when the queue is empty.
