# Human-AI Interface Synthesis

*Heat 76 | 2026-04-09*

## The Problem

The human cannot effectively assess whether the Forge's work is good. The current interface handles mechanics (dispatch, log, inbox/outbox) but fails at meaning: Is this the right thing? Is it working? Why was this decision made?

## Research Conducted

6 research documents covering 10 domains, generating 22 concrete ideas:

| Domain | Key Insight | Ideas Generated |
|--------|-------------|-----------------|
| Corporate governance | Exception-based reporting; pre-agreed metrics | Stoplight dashboard, assurance packs, quarterly reviews |
| Research labs | Graduated autonomy; milestone-based progress | Oversight intervals, artifact review |
| Military command | Commander's intent; after-action reviews | Intent field, AAR protocol |
| Animal colonies | Stigmergy — the work IS the signal; decay | Stigmergic state, decay-based memory |
| Open source | RFC process; automated quality gates | RFC for protocol changes, forge-validate.sh |
| VC portfolios | Zero-effort dashboards; metric thresholds | forge-status command, alert thresholds |
| Newsroom editorial | Story pitches; kill authority; beat autonomy | Pitch/kill protocol, autonomy zones |
| Pair programming | Thinking aloud; navigator/driver roles | Thinking-aloud commits, navigator mode |
| Creative industries | Creative brief; dailies review | identity.md as brief, run artifact review |
| Organizational research | Information compression; spot-checks; signaling | L0-L4 layers, spot-check, uncertainty signaling |

## Top 5 Interface Models to Prototype

### 1. Information Compression Layers (from Organizational Research)

**What**: A 5-layer reporting stack where each layer adds detail. The human reads the lightest layer that answers their question.

| Layer | Content | Reads | When |
|-------|---------|-------|------|
| L0 | 🟢/🟡/🔴 per heat + 1-line summary | Always | Every heat |
| L1 | 3-line run summary in outbox.md | After run | End of run |
| L2 | `forge-status` command | On demand | When curious |
| L3 | Key artifacts (files changed, decisions) | Spot-check | When L0/L1 flags |
| L4 | Full worklog + memory | Rarely | Deep investigation |

**Why this is #1**: It's the meta-framework. Every other idea is a component of one of these layers. Implementing this first creates the structure that everything else fits into.

**Implementation**: 2-3 heats. Modify logging protocol to generate L0 signals per heat and L1 summaries per run. L2 is a new `forge-status` script. L3 and L4 already exist.

---

### 2. Commander's Intent + Creative Brief (from Military + Creative Industries)

**What**: Before a run, the human specifies:
```json
{
  "intent": "Make the system usable by someone who isn't me",
  "success_looks_like": "A stranger can forge-init, run 10 heats, and get useful output",
  "tone": "careful, conservative, well-tested",
  "boundaries": ["No external dependencies", "No messaging yet"],
  "not_this": ["Don't build a web UI", "Don't over-optimize the allocator"],
  "references": ["Taskwarrior CLI UX", "Make-like simplicity"]
}
```

Every decision the Forge makes can be traced to: "Does this serve the intent?"

**Why this is #2**: It solves "maintaining strategic coherence across many heats." Right now, the Forge self-directs well mechanically but can drift from what the human actually wants. Intent makes the implicit explicit.

**Implementation**: 2 heats. Add intent section to identity.md or dispatch. Forge references intent when generating tasks and making strategic decisions.

---

### 3. Exception-Based Stoplight Dashboard (from Corporate Governance)

**What**: Each heat gets a signal:
- 🟢 **Green**: Completed normally, value ≥ 0.7, no issues
- 🟡 **Yellow**: Value < 0.7, progress stalled, task generated (not queued), or deviation from intent
- 🔴 **Red**: Rollback, blocked > 5 heats, allocator anomaly, or uncertainty-flagged decision

The heat dashboard already exists — this adds a signal classification. The human reads only yellow and red heats.

**Why this is #3**: It directly compresses the information overload problem. 30 green heats → "everything is fine." 2 yellow heats → "look at these." 1 red heat → "stop and review."

**Implementation**: 1-2 heats. Add signal classification logic to the logging protocol. Simple rules on value, outcome, and uncertainty.

---

### 4. After-Action Review (from Military Command)

**What**: After every run (not every heat), generate a structured AAR in `aar/<date>.md`:
1. **What was planned**: Dispatch direction or self-generated goals
2. **What happened**: Actual work, key decisions, artifacts
3. **Why the delta**: What went differently and why
4. **Lessons learned**: What to change in future runs
5. **Open questions**: Things the Forge is unsure about

**Why this is #4**: AARs address "understanding why decisions were made" and create a feedback loop. The human reads the AAR, not the full heat log. The AAR surfaces the *why* behind the *what*.

**Implementation**: 2 heats. Generate at end of run (Step 8 of the loop when budget exhausted). Template in logging protocol.

---

### 5. Uncertainty Signaling (from Organizational Research)

**What**: Each heat gets an uncertainty classification:
- **Certain**: "Clearly the right approach"
- **Moderate**: "Reasonable but alternatives exist"
- **Uncertain**: "Guessing — would benefit from human input"

Uncertain heats trigger yellow/red in the stoplight. The Forge proactively admits what it doesn't know.

**Why this is #5**: This is costly-to-fake signaling — the Forge admitting uncertainty *builds trust*. It tells the human exactly where to focus attention. It's the difference between "I did 30 heats of work" and "I did 28 confident heats and 2 where I need your input."

**Implementation**: 1 heat. Add `uncertainty` field to worklog entries and dashboard output. Feed into L0 signal classification.

---

## Recommendation: Implementation Order

| Priority | Model | Effort | Impact |
|----------|-------|--------|--------|
| 1 | Exception-Based Stoplight (#3) | 1-2 heats | High — immediate signal compression |
| 2 | Uncertainty Signaling (#5) | 1 heat | High — feeds into stoplight |
| 3 | Commander's Intent (#2) | 2 heats | High — strategic coherence |
| 4 | After-Action Review (#4) | 2 heats | Medium — reflective feedback loop |
| 5 | Information Compression Layers (#1) | 2-3 heats | Medium — formalization of above |

Start with #3 and #5 (can be done together in 2-3 heats) — they're the lowest effort and highest immediate impact. #2 (commander's intent) should come next as it shapes all future work. #4 (AAR) is a natural end-of-run addition. #1 is the formal framework that ties everything together.

## Ideas Not Selected (but worth keeping)

- **RFC Process** (Idea 10): Good but adds process overhead. Save for when protocol changes become contentious.
- **Pitch/Kill Protocol** (Idea 14): Useful but overlaps with commander's intent boundaries.
- **Navigator Mode** (Idea 17): Powerful for high-stakes work. Opt-in, implement later.
- **Graduated Autonomy** (Idea 4): Natural evolution — start tight, loosen. Already happening organically.
- **Spot-Check Protocol** (Idea 21): Subset of L3 in the compression layers.
- **Stigmergic State** (Idea 8): Beautiful idea. Partially realized via `forge-status`.
