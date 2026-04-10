# Human-AI Interface: VC Portfolio Monitoring & Newsroom Editorial Models

*Heat 73 | 2026-04-09*

## Part 1: VC / Startup Board Model

### Core Insight
"The dashboard should not be a special exercise or 'make work' done just for the board — it should take almost no extra work to pull together." VCs monitor portfolios through **automated, continuous dashboards** that pull directly from operational data. No special reporting — the data the company uses to run itself IS the board report.

### How Information Flows
**Startup → VC:**
- Monthly/quarterly automated KPI snapshots (MRR, burn, churn, LTV:CAC)
- Exception alerts when metrics cross thresholds
- Board deck only for strategic decisions, not status updates

**VC → Startup:**
- "Don't call me unless it's bad" — minimal interference when things are on track
- Strategic advice at board meetings
- Network/resource access when needed

### What Makes It Work
1. **Zero-effort reporting**: Dashboard pulls from existing operational data
2. **Continuous monitoring**: Not quarterly — always-on
3. **Metric-driven**: Quantitative signals, not narrative
4. **Attention proportional to risk**: More engagement when metrics are yellow/red

### Concrete Ideas for The Forge

#### Idea 12: Zero-Effort Dashboard
The human should be able to run one command and get the board deck:
```bash
forge-status  # pulls from state.json, worklog.tsv, git log
```
Output:
- Progress by stage (from state.json — already exists)
- Velocity: heats/stage over last 10 heats
- Alert flags: any stalled progress, any value < 0.5, any blocked tasks
- Top 3 commits (from git log)
- STRATEGY.md "What's Missing" section

**No new file needed** — generated on demand from existing state.

#### Idea 13: Metric Thresholds with Alerts
Define thresholds in state.json:
```json
"alerts": {
  "stall_threshold": 5,     // heats without progress increase
  "low_value_threshold": 0.5,
  "max_queue_age": 15        // heats a task can sit pending
}
```
When a threshold is breached, Forge writes to outbox.md. Otherwise, silence = everything is fine.

**Implementation effort**: 2-3 heats.

---

## Part 2: Newsroom Editorial Model

### Core Insight
Newsrooms have **layered editorial oversight**: reporters have autonomy on their beat, but every story passes through desk editors before publication. The Editor-in-Chief handles strategy and major calls, not individual story editing. The daily editorial meeting is where priorities are set — a brief, structured alignment session.

### How Information Flows
**Reporter → Editor:**
- Story pitches (1-2 sentences: what, why it matters)
- Draft stories for review
- Beat-level situation awareness

**Editor → Reporter:**
- Assignment (what to cover)
- Editorial judgment (is this a story? is it ready?)
- Kill decision (stop work on this — it's not worth it)
- Resource allocation (photographer, travel budget)

### What Makes It Work
1. **Beat autonomy**: Reporter owns their domain, doesn't need permission for routine coverage
2. **Pitch → approve cycle**: Big stories are pitched before invested in
3. **Kill authority**: Editor can stop work early, saving wasted effort
4. **Daily standup**: Brief alignment meeting, not a full review

### Concrete Ideas for The Forge

#### Idea 14: Story Pitch / Kill Protocol
Before starting a major task (anything touching protocol, allocator, or spanning 3+ heats), Forge writes a 2-line "pitch" to outbox.md:
- What it wants to do
- Why (connected to commander's intent)

The human can approve (silence = approve after 3 heats) or kill ("Don't do this"). This prevents the Forge from investing heavily in work the human doesn't want.

**Kill mechanism**: Human writes `KILL: <task-id>` in inbox.md. Forge drops the task and logs the kill.

#### Idea 15: Beat Autonomy Zones
Define zones where the Forge has full autonomy (no pitch needed):
- Testing, editing, marketing (routine quality work)
- Research (exploring is always ok)

And zones requiring a pitch:
- Protocol changes
- New tools/scripts
- Strategic direction changes
- Anything marked priority 1

**Implementation effort**: 2 heats.
