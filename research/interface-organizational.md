# Human-AI Interface: Organizational Research — Span of Control & Delegation

*Heat 75 | 2026-04-09*

## Core Insight

Span of control research shows that the optimal oversight ratio depends on **task complexity** and **agent competence**. Knowledge workers with high competence need less oversight (15-25:1), while complex technical work needs more (5-8:1). The key variable isn't the number of agents — it's the **information load** on the overseer.

Five managerial archetypes exist: player/coach, coach, supervisor, facilitator, coordinator. The Forge relationship is closest to **facilitator** (low direct task involvement, high strategic guidance) or **coordinator** (orchestrating work across domains).

## The Information Asymmetry Problem

This is our exact problem:
- The Forge has **more information** about what it did and why (it was there)
- The human has **more information** about what matters and why (strategic context)
- Neither can fully transfer their knowledge to the other without overwhelming bandwidth

### Solutions from Organizational Research

1. **Incentive alignment**: Make the agent's success criteria match the principal's. In our case: the Forge's self-assessment should be validated against human feedback.

2. **Monitoring + bonding**: A mix of oversight (human reviews) and bonding (Forge commits to transparency). Both parties invest in reducing information asymmetry.

3. **Screening mechanisms**: Use work samples (artifacts) to infer quality without reviewing everything. If the 3 artifacts the human spot-checks are good, trust the other 20.

4. **Signaling**: The agent proactively shares information that's costly to fake. In our case: the Forge's willingness to flag its own uncertainties and mistakes is a strong signal of trustworthiness.

## The RACI Model Applied to The Forge

| Decision Type | R (Responsible) | A (Accountable) | C (Consulted) | I (Informed) |
|---------------|----------------|-----------------|---------------|--------------|
| Task execution | Forge | Human | — | Human (via outbox) |
| Task selection | Forge (allocator) | Human (priorities) | — | Human (via dashboard) |
| Protocol changes | Forge (proposes) | Human (approves) | Anvil | — |
| Strategic direction | Anvil | Human | Forge | — |
| Quality assessment | Forge (self) + Human (spot-check) | Human | — | — |

## Concrete Ideas for The Forge

### Idea 20: Information Compression Layers
Design the reporting stack as layers of increasing detail:

| Layer | What | Who reads | When |
|-------|------|-----------|------|
| **L0: Signal** | Green/Yellow/Red emoji in 1 line | Human, always | Every heat |
| **L1: Summary** | 3-line run summary in outbox.md | Human, after run | End of run |
| **L2: Dashboard** | `forge-status` command output | Human, on demand | When curious |
| **L3: Artifacts** | Actual files changed (git diff) | Human, spot-check | When L0/L1 flags something |
| **L4: Full log** | worklog.tsv + MEMORY_DAILY.md | Human, rarely | Deep investigation |

The human normally reads L0 + L1. They only go deeper when something looks wrong. This is the VC dashboard model + exception-based reporting combined.

### Idea 21: Spot-Check Protocol
Human doesn't review everything. Instead:
- After each run, Forge presents 3 representative artifacts
- Human reviews those 3 in detail
- If all 3 are good → trust the rest
- If any are bad → deep dive into the full run

This is the organizational screening mechanism applied: quality inference from samples.

### Idea 22: Uncertainty Signaling
The Forge should proactively flag uncertainty. Add an `uncertainty` field to heat logging:
- `certain`: "This is clearly the right approach"
- `moderate`: "I chose this but alternatives exist"  
- `uncertain`: "I'm guessing here — would benefit from human input"

Uncertain heats get flagged in L0 (yellow signal). This is costly-to-fake signaling: the Forge admitting uncertainty builds trust.

**Implementation effort**: 2-3 heats each.
