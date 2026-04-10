# Human-AI Interface: Corporate Governance Model

*Heat 70 | 2026-04-09*

## Core Insight

Boards don't try to understand everything. They use **exception-based reporting** — only surface what's out of bounds. Green/yellow/red signals compress vast operational detail into actionable oversight.

The principal-agent problem is exactly our situation: the human (principal) delegates to the Forge (agent), but can't observe every action and has less information about the work being done.

## How Information Flows

**Board ← CEO:**
- Quarterly reports with pre-defined KPIs
- Exception-based reporting: green/yellow/red stoplight charts
- "Assurance packs" — not narrative updates, but defined metrics + sampled evidence + exception reports
- Board committees specialize (audit, compensation, strategy) to go deeper in narrow areas

**Board → CEO:**
- Strategic direction, not operational detail
- "Commander's intent" equivalent: goals and constraints, not methods
- Annual evaluation against pre-set criteria

## What Makes It Work

1. **Pre-agreed metrics**: Both sides know what's measured before work begins
2. **Exception-based attention**: Human only needs to look when something is yellow/red
3. **Periodic deep dives**: Not every meeting — but regular cadence of thorough review
4. **Separation of oversight layers**: Committees handle depth, full board handles breadth

## What Makes It Fail

1. **Rubber-stamping**: Board trusts blindly, never challenges
2. **Metric gaming**: Agent optimizes for measured KPIs at expense of unmeasured value
3. **Information overload**: Too many metrics → nothing is signal
4. **Misaligned incentives**: Agent's goals diverge from principal's

## Concrete Ideas for The Forge

### Idea 1: Exception-Based Heat Dashboard
Replace the current dashboard (which shows everything equally) with a **stoplight system**:
- **Green**: Heat completed normally, value >= 0.7, no issues
- **Yellow**: Value < 0.7, or task took longer than expected, or progress stalled
- **Red**: Rollback occurred, blocked by external dependency, or allocator anomaly

The human only needs to read yellow/red heats. Green heats get a single summary line.

### Idea 2: Pre-Agreed "Assurance Pack"
Before a run, the human and Forge agree on 3-5 metrics that matter:
- e.g., "test coverage should increase", "no new files without tests", "research findings should be actionable"

After each run, Forge generates an assurance report against these pre-agreed metrics. Not "here's what I did" but "here's how I performed against what we agreed matters."

### Idea 3: Quarterly Review Model (Every ~20 Heats)
Every 20 heats, generate a structured review:
- KPI performance vs. targets
- Decisions that need human input (flagged yellow/red)
- Strategic recommendations for next 20 heats
- Self-assessment of what's working and what isn't

**Implementation effort**: 2-3 heats each.
