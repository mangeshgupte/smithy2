# Steering Patterns — How Humans Direct Autonomous Systems

## The Core Question

What controls does a human need to change an autonomous agent's direction without becoming a bottleneck?

## 1. Real-Time Strategy Games (StarCraft)

**Model**: Three-tier command hierarchy
- **Strategic**: "Attack the enemy base" (outcome, not method)
- **Tactical**: "Send these 5 units to this location" (who + where)
- **Autonomous**: Units auto-attack, auto-retreat, auto-heal

**Steering mechanisms**:
- Rally points (set destination, units figure out path)
- Control groups (name a set of units, command as one)
- Priority targets ("focus fire on this")
- Global upgrades (buff all units of a type)

**Key insight**: The human steers by **attention allocation** — where they look IS where they steer. Everything else runs autonomously.

**Frequency**: Continuous micro-decisions (100+ actions/minute), strategic decisions every 2-5 minutes.

**What Smithy can learn**: Attention = allocation. The human's gaze (which initiative they look at, which theme they rank higher) IS the steering input. No explicit commands needed.

## 2. Military C2 (Mission-Type Orders)

**Model**: Commander's Intent + Constraints
- Commander states the **desired end state**, not the method
- Subordinates have full autonomy within **boundaries**
- "Secure the bridge by 0600, no civilian casualties" = intent + constraint

**Steering mechanisms**:
- Commander's Intent (the "why" — survives when plans fail)
- Main Effort designation (which unit gets priority resources)
- Boundaries (geographic/temporal/rules of engagement)
- Phase lines (checkpoints that trigger reassessment)

**Key insight**: **Constraints steer better than commands.** Telling someone what NOT to do gives them more freedom than telling them what TO do.

**Frequency**: Strategic decisions every hours/days. Tactical decisions delegated.

**What Smithy can learn**: The human should set boundaries (budget caps, stage minimums, "don't touch X") and let Forge work freely within them.

## 3. Product Management (OKRs + Sprint Planning)

**Model**: Nested goals with delegation
- **OKRs**: Objectives (qualitative) + Key Results (measurable)
- **Roadmap**: Quarterly themes, loosely ordered
- **Sprint**: 2-week commitment, team decides how

**Steering mechanisms**:
- Priority stack (ordered list, work top-down)
- Capacity allocation ("50% on feature A, 30% on B, 20% on bugs")
- Blockers/escalation (team flags, PM decides)
- Demo/review (see output, redirect)

**Key insight**: **Ranking IS steering.** The PM's main job is keeping the priority stack in the right order. Everything else flows from rank.

**Frequency**: Priorities reviewed weekly. Daily standups for blockers only.

**What Smithy can learn**: A priority-ranked initiative list is the simplest, highest-leverage steering mechanism. Drag to reorder = maximum steering with minimum effort.

## 4. Air Traffic Control

**Model**: Constraints, not waypoints
- ATC doesn't fly the planes — pilots do
- ATC sets: altitude assignments, speed restrictions, holding patterns, approach sequences
- Separation is the invariant: "maintain at least 3 miles horizontal / 1000 feet vertical"

**Steering mechanisms**:
- Altitude assignment (vertical constraint)
- Speed restriction (temporal constraint)
- Sequencing (ordering constraint)
- Holding pattern (pause without canceling)

**Key insight**: **The controller manages separation, not trajectories.** They ensure things don't collide, not that they take the optimal path.

**Frequency**: Continuous monitoring, interventions only when separation threatened.

**What Smithy can learn**: The human should manage conflicts between initiatives (resource contention, scope overlap) rather than directing individual tasks.

## 5. AI Coding Tools

| Tool | Steering Model | Human Input | Feedback Loop |
|------|---------------|-------------|--------------|
| **Devin** | Chat-to-steer | Natural language messages mid-task | See terminal + browser, redirect |
| **Cursor** | Accept/reject per-edit | Approve or modify each suggestion | Immediate, per-line |
| **Claude Code** | Prompt + approve | Describe task, approve tool calls | Per-action approval |
| **Aider** | Chat + auto-commit | Describe changes, review diffs | Git diff after each change |

**Key insight**: Current tools are either **too granular** (approve each edit) or **too coarse** (describe the whole task). The sweet spot is **intent-level steering**: describe what you want at a higher level than individual edits, but lower than "build me an app."

## Taxonomy of Steering Modes

| Mode | Human Input | Frequency | Cognitive Load | Best For |
|------|------------|-----------|---------------|----------|
| **Ranking** | Drag to reorder | Per-session | Very low | Priority allocation |
| **Constraints** | Set boundaries | Per-run | Low | Safety + direction |
| **Timeline** | Drag bar endpoints | Per-run | Medium | Budget planning |
| **Intent** | Write 2-3 sentences | Per-sprint | Medium | Direction changes |
| **Approve/Reject** | Binary per-item | Per-heat | High | Critical decisions |
| **Chat** | Natural language | Continuous | High | Real-time course correction |

## Recommendations for Prototyping

### Build All Four UIs

Each represents a distinct steering mode. The human should try all four and discover which matches their working style:

1. **Priority Poker** (Ranking mode) — drag cards to reorder. Lowest cognitive load. Best when the human knows WHAT but not HOW MUCH.

2. **Constraint Board** (Constraint mode) — set boundaries. Best when the human wants to prevent bad outcomes without prescribing good ones.

3. **Timeline View** (Timeline mode) — visual budget allocation. Best when the human thinks in time/phases and wants to see tradeoffs.

4. **Intent Editor** (Intent mode) — write outcomes, system decomposes. Best when the human thinks in outcomes and wants the system to figure out tasks.

### Integration with Forge

All UIs should write to `state.json` — modifying themes/initiatives/tasks. Forge reads state.json, so any UI that writes to it becomes a steering mechanism. No Forge code changes needed.
