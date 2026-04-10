# Human-AI Interface: Animal Colonies & Open Source Models

*Heat 72 | 2026-04-09*

## Part 1: Animal Colonies / Stigmergy

### Core Insight
Ants coordinate without any central controller. They communicate by **modifying the environment** — pheromone trails that other ants detect and respond to. The environment *is* the communication channel. Critically, pheromones **evaporate**: old signals decay naturally, so the system adapts without anyone deciding to forget.

### How Information Flows
- No direct communication between agents
- Agent leaves trace → environment changes → other agents react
- Reinforcement: successful paths get stronger signals
- Decay: unused paths fade automatically
- Emergent intelligence from simple local rules

### What Makes It Work
1. **Environment as message board**: No inbox needed — the work itself is the signal
2. **Natural decay**: Old information disappears without cleanup
3. **Positive feedback loops**: Good paths get reinforced by use
4. **Simplicity**: Each agent follows simple rules, complexity emerges

### What Makes It Fail
1. Local optima: colony fixates on a nearby food source, misses a better one
2. No ability to communicate abstract concepts (only "follow this path")
3. Slow adaptation when environment changes suddenly

### Concrete Ideas for The Forge

#### Idea 8: Stigmergic State — The Work IS the Signal
Instead of writing status reports to outbox.md, let the human inspect the work directly. The state of the repository IS the communication:

- **Git log** = pheromone trail (recent commits are strong, old ones fade)
- **File changes** = environmental modification
- **Test results** = positive/negative reinforcement

Build a `forge-status` command that generates an at-a-glance view from git:
```
forge-status: last 5 commits, files changed, tests pass/fail, STRATEGY.md diff
```

No separate reporting layer — the code is the report.

#### Idea 9: Decay-Based Memory
MEMORY_DAILY.md already consolidates every 6 heats. Take this further: **automatically prune** observations that haven't been referenced in 20+ heats. If a memory hasn't influenced a decision, it's like an evaporated pheromone — let it go.

**Implementation effort**: 2 heats each.

---

## Part 2: Open Source Projects

### Core Insight
Maintainers oversee strangers' contributions. They can't read every line of every PR — so they rely on **structure**: contributor guidelines, automated CI, RFC processes for big changes, and a graduated trust system (contributor → committer → maintainer).

### How Information Flows
**Contributor → Maintainer:**
- Pull request with description, tests, and compliance with style guide
- CI results (automated quality gate)
- Design doc / RFC for non-trivial changes

**Maintainer → Contributor:**
- Review comments (specific, actionable)
- LGTM / Request changes
- Strategic direction via roadmap/RFC

### What Makes It Work
1. **Automated quality gates**: CI runs before human review — catches the obvious
2. **RFC process for big changes**: Design review before implementation
3. **Graduated trust**: Proven contributors get more autonomy
4. **Artifact-based review**: Review the PR, not the process

### What Makes It Fail
1. Review bottleneck: One maintainer for too many PRs
2. Bikeshedding: Arguing about style instead of substance
3. No design review → surprises in implementation
4. Contributor guide is ignored or too vague

### Concrete Ideas for The Forge

#### Idea 10: RFC Process for Strategic Changes
When the Forge wants to change the protocol, add a new major feature, or deviate from the plan, it should write a brief RFC to `rfcs/<topic>.md`:
- Problem statement
- Proposed solution
- Alternatives considered
- Impact on existing work

The human can review and approve/reject before implementation. Small changes don't need RFCs — only changes affecting the protocol, allocator, or strategic direction.

**Threshold**: Any change to files in `protocol/` or `STRATEGY.md` vision/roadmap triggers an RFC.

#### Idea 11: Automated Quality Gate
Create `forge-validate.sh` (already planned as t-035) but expand it to be a pre-commit check:
- state.json schema valid
- worklog.tsv parseable
- All protocol cross-references resolve
- No unresolved merge conflicts
- Progress values in [0, 1]

This is the Forge's CI — catches corruption before the human needs to worry about it.

**Implementation effort**: 2-3 heats each.
