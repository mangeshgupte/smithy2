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
  allocator.md         ← Wavefront + PI controller
  logging.md           ← Worklog, dashboards, memory protocol
identity.md            ← Project context
STRATEGY.md            ← Living strategic plan (updated each heat)
state.json             ← Budget, stages, queue, allocator state
worklog.tsv            ← Append-only heat log
inbox.md / outbox.md   ← Async human-AI messages
MEMORY_DAILY.md        ← Working memory
MEMORY_WEEKLY.md       ← Validated patterns
research/              ← Research artifacts
plan.md                ← Living plan
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

## Key Principles

- **No Python.** The entire system is prose — CLAUDE.md + protocol files. Claude Code is the runtime.
- **Flat files.** state.json, worklog.tsv, markdown. Inspect with `cat`, edit with `vim`.
- **Git is the substrate.** Every heat's work is committed. The record is sacred.
- **Budget-bounded.** Never exceeds allocated heats. Say "Run N" to extend.
- **Self-directed.** Generates its own tasks when the queue is empty.
