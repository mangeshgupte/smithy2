# Human-AI Interface: Research Lab & Military Command Models

*Heat 71 | 2026-04-09*

## Part 1: Research Lab / PhD Advisor Model

### Core Insight
The advisor doesn't do the work — they shape the *question*. Meetings have agendas agreed in advance, end with action items and timelines, and both parties commit in writing. The advisor's role is to "challenge ideas without discouraging confidence and maintain high standards without being inflexible."

### How Information Flows
**Student → Advisor:**
- Weekly 1:1 meetings (first months), then spacing out as independence grows
- Written progress against milestones
- Draft artifacts for review (papers, code, data)

**Advisor → Student:**
- Milestone structure set early, reviewed periodically
- Feedback on artifacts, not on process
- Course corrections framed as questions ("have you considered...?") not directives

### What Makes It Work
1. **Graduated autonomy**: Close supervision early, loose supervision later
2. **Milestones, not time**: Progress measured by deliverables, not hours
3. **Both parties agree on agenda**: No surprise topics
4. **Written action items**: Accountability without surveillance

### What Makes It Fail
1. Absent advisor (no meetings, no feedback)
2. Micromanaging advisor (reviews every line, no intellectual space)
3. No clear milestones (student drifts without checkpoints)
4. Power asymmetry prevents honest upward feedback

### Concrete Ideas for The Forge

#### Idea 4: Graduated Autonomy Protocol
Start runs with close oversight (human reviews every 3 heats), then widen the interval as the Forge demonstrates competence. Configurable: `oversight_interval: 3` → `5` → `10` → `20`.

At each oversight checkpoint:
- Forge writes a "lab meeting" summary: what was tried, what worked, what's stuck
- Human responds with feedback or "LGTM" (continue)
- If no human response within 5 heats, Forge continues autonomously

#### Idea 5: Artifact-Based Review
Instead of reviewing every heat, the human reviews *artifacts* — the actual outputs:
- New files created (code, docs, research)
- Protocol changes
- Strategic direction changes

The Forge generates a "review pack" at the end of each run: a curated list of the most important artifacts, ordered by impact, with a 1-line summary each. The human reviews artifacts, not the heat log.

**Implementation effort**: 2 heats each.

---

## Part 2: Military Command / Auftragstaktik

### Core Insight
**Commander's intent** is broader than the mission. It communicates *why* and *what conditions*, giving subordinates maximum freedom on *how*. The subordinate can violate specific orders if doing so better achieves the commander's intent. The commander is obliged to express intent "clearly and unambiguously" and communicate "the conditions and motives on which his intent was based."

### How Information Flows
**Commander → Subordinate:**
- Objective (what to achieve)
- Intent (why, and what success looks like)
- Constraints (time, resources, boundaries)
- NOT the method

**Subordinate → Commander:**
- Situation reports (SITREPs) — brief, structured
- Exception reports when conditions change
- After-action review (AAR): what was planned, what happened, why, what to do differently

### What Makes It Work
1. **Intent over instructions**: Agent understands *why*, can adapt to changing conditions
2. **Structured reporting**: SITREPs are formatted, not narrative
3. **After-action reviews**: Systematic learning from every engagement
4. **Trust + competence**: Requires trained subordinates who share the commander's mental model

### What Makes It Fail
1. Commander specifies method, not just intent (undermines autonomy)
2. Subordinate lacks context to interpret intent
3. No AAR → same mistakes repeated
4. Loss of trust → reversion to micromanagement

### Concrete Ideas for The Forge

#### Idea 6: Commander's Intent Field
Add a `commander_intent` field to state.json or dispatch:
```json
{
  "intent": "Make the system usable by someone who isn't me",
  "success_looks_like": "A stranger can forge-init, run 10 heats, and get useful output",
  "boundaries": ["No external dependencies", "Keep it simple"],
  "not_this": ["Don't build a web UI yet", "Don't add messaging"]
}
```

The Forge references this when generating tasks or making strategic decisions. Every heat's decision can be traced back to: "Does this serve the commander's intent?"

#### Idea 7: After-Action Review Protocol
After every run (not every heat), generate a structured AAR:
1. **What was planned** (dispatch direction or self-generated goals)
2. **What happened** (actual work, with key decisions)
3. **Why the delta** (what went differently and why)
4. **Lessons learned** (what to change in future runs)

This goes into a new file: `aar/<date>.md`. It's different from outbox.md (which is status updates) — AARs are reflective and focused on improving the process.

**Implementation effort**: 2-3 heats each.
