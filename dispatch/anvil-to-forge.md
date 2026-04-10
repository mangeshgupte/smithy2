# Dispatch: Anvil → Forge

Anvil writes direction here. Forge reads on startup and uses it to guide autonomous work.

## 2026-04-10 00:00 — Direction: Iteration Tooling (3 stages)

### What We Decided
The Forge can build things, but the human can't efficiently iterate on them. The feedback loop is broken — there's no structured way to say "fix this" and have it flow into Forge work. We're building the iteration infrastructure in 3 stages across all 3 projects.

### Commander's Intent
```json
{
  "intent": "Build the tooling that lets the human iterate on any Forge project with minimal friction",
  "success_looks_like": "The human can give feedback on tutor or commissioner from one place, and Forge acts on it in the next run without manual dispatching",
  "tone": "Infrastructure work — careful, well-tested, protocol-level changes",
  "boundaries": ["Each stage must work independently", "Don't break existing protocol", "Keep flat-file architecture"],
  "not_this": ["Don't build multi-project Forge yet — that's stage 3, later", "Don't over-engineer — feedback.md is a file, not a database"],
  "references": ["protocol/loop.md", "commissioner/app.py", "dispatch/chisel-to-forge.md"]
}
```

### Stage 1: Feedback Protocol (5 heats on ai-coworker)

**Heat 1 — implementation:** Add `feedback.md` to the protocol.
- Template: human writes freeform feedback, Forge reads it
- Format: dated entries like inbox.md, but project-specific and focused on "what's wrong / what to improve"
- Add `feedback.md` to `forge-init.sh` scaffold so every new project gets one
- Update CLAUDE.md to reference it

**Heat 2 — implementation:** Add review-first-heat to `protocol/loop.md`.
- When feedback.md has new entries, the FIRST heat of a run is a "review heat"
- Review heat: read feedback → examine the relevant code/output → generate prioritized fix tasks → add to queue
- Stage = "planning", but driven by human feedback rather than allocator
- If no new feedback, skip review and proceed normally

**Heat 3 — testing:** Validate the feedback loop.
- Write test feedback to the dogfood project's feedback.md
- Run a heat, verify it picks up the feedback and generates tasks
- Verify forge-init.sh creates feedback.md for new projects

**Heat 4 — editing:** Update all docs.
- protocol/logging.md — document feedback.md format
- README — add feedback section
- STRATEGY.md — update

**Heat 5 — marketing:** Backfill feedback.md for tutor and commissioner.
- Create feedback.md in ~/vibes/tutor/ with the human's feedback ("questions too easy", "good for a first attempt, needs iteration")
- Create feedback.md in commissioner/ with known gaps (no tap-to-decide, no Direct tab)
- These are ready for the next Forge run on those projects

### Stage 2: Commissioner Feedback UI (5 heats on Commissioner)

**After stage 1 is done.** Add feedback input to the Commissioner's Direct tab:
- Per-project text/voice input that writes to that project's feedback.md
- Show recent feedback entries so the human can see what they've already said
- "Send feedback" button that appends to the file
- This makes Commissioner the single iteration hub

### Stage 3: Multi-Project Forge (later, not now)

Deferred. Design only after stages 1 and 2 are validated.

### Constraints
- Start with Stage 1 only (5 heats)
- Stage 2 will be dispatched separately after Stage 1 is confirmed working
- Don't touch tutor or commissioner code in Stage 1 (except creating their feedback.md files)
- Write an AAR at the end

### Budget
5 heats (Stage 1 only)

## 2026-04-09 23:00 — Direction: Build the Commissioner App

### What We Decided
Chisel designed a mobile-first operational app for managing multiple Forge projects. The full design spec is at `design/2026-04-09-commissioner-app-design.md` and the dispatch summary is at `dispatch/chisel-to-forge.md`. Read both before starting.

This is the second real project (after AI Tutor) and a natural evolution — the Forge building its own management interface.

### Commander's Intent
```json
{
  "intent": "Build a working Commissioner web app that lets one person manage 5-10 Forge projects from their laptop, with an eye toward phone usability",
  "success_looks_like": "A functional web prototype (localhost) with Morning Briefing, Home (lifecycle cards), and Decide tab working end-to-end against real Forge state files. Viewable on laptop and phone browser.",
  "tone": "Focused, implementation-heavy. The design is done — build it.",
  "boundaries": ["Follow Chisel's design spec closely", "Web app first — must work well on laptop, should be usable on phone browser", "No backend infrastructure yet — read directly from Forge flat files for the prototype"],
  "not_this": ["Don't redesign what Chisel already decided", "Don't build all 6 screens at once — prioritize the core loop", "No native mobile app yet — web only for now"],
  "references": ["design/2026-04-09-commissioner-app-design.md", "dispatch/chisel-to-forge.md"]
}
```

### Focus Areas

**Phase 1 — Core loop (heats 1-8):**
1. Scaffold the project (new directory, forge-init.sh)
2. Home screen with lifecycle-adaptive project cards reading from real state.json files
3. Morning Briefing screen (needs-you, progress deltas, notable)
4. Decide tab — decision cards with tap-to-decide

**Phase 2 — Steering + polish (heats 9-15):**
5. Direct tab — free-form input, quick actions, intent editor
6. Activity tab — heat feed with auto-summarization
7. Cross-project Inbox
8. Notification tier logic

### Technical Notes
- **Web app** — build with a lightweight web framework (Next.js, Vite+React, or even plain HTML/JS). Must run on localhost.
- For the prototype, read directly from Forge's flat files (state.json, worklog.tsv, outbox.md, dispatch files). A simple Node/Python file server is fine.
- **Laptop-first, phone-aware.** Design for a laptop browser as the primary experience. Use responsive CSS so it's usable (not perfect) on a phone browser. At the end of the build, note in the AAR what would need to change for a true mobile-native experience — this helps us assess the complexity of going to phone later.
- The design spec has ASCII wireframes for every screen — follow them closely, adapting the mobile-first layout to work on wider screens too

### Constraints
- Chisel's design decisions are final for this build. If something seems wrong, flag it in the AAR, don't redesign.
- Signal honestly — 🟡 if a screen is harder to implement than expected, 🔴 if you're blocked.
- Write an AAR at the end.

### Budget
15 heats

## 2026-04-09 22:00 — Direction: First Real Project — AI Tutor

### What We Decided
The Forge has been building itself for 99 heats. It's time for the acid test: build something real. The human chose an **AI tutor** — a tool that helps people learn new things. The audience is either kids or adults (university-level). The first few heats should research and decide which angle to take.

This run tests 6 hypotheses simultaneously:
- **H8**: Does Forge produce useful output on a non-self project?
- **H9**: Can the human assess quality in under 2 minutes?
- **H10**: Do Forge's decisions align with the intent?
- **H5**: Do stoplights compress oversight info?
- **H6**: Does commander's intent maintain coherence?
- **H7**: Does the AAR capture the "why"?

### Commander's Intent
```json
{
  "intent": "Build an AI tutor that helps people learn new things effectively",
  "success_looks_like": "A working prototype that a real person could use to learn a topic, with a clear pedagogical approach",
  "tone": "exploratory first, then focused — research the space before committing to an approach",
  "boundaries": ["No paid API dependencies for the MVP", "No complex infrastructure — keep it runnable locally"],
  "not_this": ["Don't build a generic chatbot wrapper", "Don't build a quiz-only app — learning is more than testing"],
  "references": ["Socratic method", "spaced repetition", "Bloom's 2-sigma problem", "Khan Academy's mastery approach"]
}
```

### Focus Areas

**Heats 1-3 (research):**
- What makes tutoring effective? (Bloom's 2-sigma, zone of proximal development, mastery learning)
- Existing AI tutors — what works, what doesn't (Khan Academy AI, Khanmigo, Duolingo, Synthesis, Quizlet AI)
- Kids vs adults — different needs, different approaches. Recommend one to start with.
- What's a good first subject domain to prototype with?

**Heats 4-5 (planning):**
- Pick the audience and domain based on research
- Design the core learning loop (how does a session flow?)
- Define the MVP scope — what's the minimum that demonstrates real tutoring?

**Heats 6+ (implementation, testing, etc.):**
- Build it. The allocator handles stage selection from here.
- Use `forge-init.sh` to scaffold the project in a new directory

### Setup
- Scaffold the tutor project using `forge-init.sh` in a new directory (e.g., `../../projects/ai-tutor/` or a sibling directory — Smith decides)
- This is a SEPARATE project from ai-coworker. It has its own state.json, worklog, etc.
- But run it from the Forge persona — the protocol is the same

### Constraints
- This is the first non-dogfood project. If the protocol has gaps, document them — that's valuable data for H8.
- Write an AAR at the end — this is the first real test of H7.
- Be honest in stoplights — if you're uncertain, say 🟡. We need real signal, not all-green theater.

### Budget
15 heats

## 2026-04-09 21:00 — Direction: Hypothesis Tracking + Reporting Formalization

### What We Decided
The human chose Version 2 (Hypothesis-Led, Intent as Context) as the standard status report format. Anvil's CLAUDE.md has been updated. A Hypotheses table has been added to STRATEGY.md. Forge needs to:

1. Update `protocol/reporting.md` to document the Version 2 status format as the L1/L2 reporting standard
2. Ensure the Hypotheses table in STRATEGY.md gets maintained — when a hypothesis changes status (validated, invalidated, inconclusive), update it during the regular STRATEGY refresh
3. Add a note in `protocol/logging.md` reminding the Smith to update hypothesis status when a heat produces evidence for or against a hypothesis

### Constraints
- Small task — 2 heats max
- Don't change the status format itself (Anvil owns that), just document it in protocol/reporting.md
- The Hypotheses table is the source of truth for Anvil's status reports

### Budget
2 heats

## 2026-04-09 20:00 — Direction: Operationalize Human-AI Interface

### What We Decided
The interface synthesis (`research/human-ai-interface-synthesis.md`) identified 5 models. The human reviewed it and said "looks good, operationalize it." Implement all 5 in priority order.

### Implementation Plan (follows the synthesis recommendation)

**Heats 1-2: Stoplight Dashboard (#3) + Uncertainty Signaling (#5)**
- Add a `signal` field to each heat in the worklog: 🟢 / 🟡 / 🔴
  - 🟢: value ≥ 0.7, completed normally, no issues
  - 🟡: value < 0.7, progress stalled, deviation from intent, or moderate uncertainty
  - 🔴: rollback, blocked > 5 heats, allocator anomaly, or high uncertainty
- Add an `uncertainty` field to each heat: certain / moderate / uncertain
- Update `protocol/logging.md` to include both fields in the worklog format
- Update the ASCII dashboard to show signals per heat (replace or augment current display)
- Uncertain heats auto-escalate to 🟡 or 🔴

**Heats 3-4: Commander's Intent (#2)**
- Add an `intent` section to the dispatch format (or identity.md) with fields:
  - `intent`: one sentence — what success looks like
  - `boundaries`: what NOT to do
  - `tone`: careful/aggressive/exploratory
  - `references`: examples or analogues to follow
- Update `protocol/loop.md` to read intent at the start of each heat
- Forge should reference intent when generating tasks and making keep/discard decisions
- If a heat's work doesn't serve the intent, it gets 🟡

**Heats 5-6: After-Action Review (#4)**
- Create `aar/` directory
- Generate `aar/YYYY-MM-DD-HH.md` at end of each run (when budget exhausted, Step 8)
- Template: What was planned → What happened → Why the delta → Lessons learned → Open questions
- Update `protocol/loop.md` to include AAR generation as part of the budget-exhausted path
- AAR replaces the current outbox run summary (or supplements it)

**Heats 7-8: Information Compression Layers (#1)**
- Formalize the L0-L4 layer structure in a new `protocol/reporting.md`
- L0: signal + 1-line per heat (already done by heats 1-2)
- L1: 3-line run summary in outbox (already exists, refine)
- L2: `forge-status` script — reads state.json, worklog, shows dashboard on demand
- L3: key artifacts list (files changed, decisions made) — add to AAR
- L4: full worklog + memory (already exists)
- Document when the human should read each layer

### Constraints
- These are implementation + editing heats — modify protocol files, logging, loop
- Test each change by verifying it works within the same run (the Forge is dogfooding)
- Keep changes backward-compatible with existing worklog format (add fields, don't remove)
- Reference the synthesis doc for details on each model

### Budget
8 heats

## 2026-04-09 18:00 — Direction: Human-AI Interface Research

### The Problem
The human cannot effectively assess whether the changes Forge makes are good. The current interface (Anvil chat + inbox.md) handles direction-setting and status reporting, but lacks structure for:
- Evaluating quality of work at the right abstraction level
- Understanding *why* decisions were made, not just *what* was done
- Giving feedback that actually shapes future work
- Maintaining strategic coherence across many heats

We need a higher-level structure for the ideas being tried. The current system works for mechanics (dispatching, logging) but fails at meaning (is this the right thing? is it working?).

### What To Research
All 10 heats should be **research stage**. Generate diverse ideas for how the human-AI interface could work, drawing from **varied domains**:

1. **Corporate governance** — How do boards oversee CEOs? What's the reporting cadence, what metrics matter, how do they evaluate without micromanaging? (quarterly reviews, KPIs, exception-based reporting)

2. **Research labs / academia** — How do PIs supervise PhD students and postdocs? Lab meetings, paper drafts, milestone reviews, the thesis committee model. What works about the advisor relationship?

3. **Military command structures** — Commander's intent, mission-type tactics (Auftragstaktik), after-action reviews. How do you give direction without specifying every step?

4. **Animal colonies** — How do ant colonies, bee hives, and slime molds coordinate without centralized control? Stigmergy (communication through environment modification), pheromone trails, waggle dances. What can distributed intelligence teach us?

5. **Open source projects** — How do maintainers review contributions from strangers? PRs, RFC processes, design docs, LGTM culture. What makes code review actually work?

6. **Venture capital / startup boards** — How do investors monitor portfolio companies? Board decks, metrics dashboards, the "don't call me unless it's bad" model. What's the right information density?

7. **Newsroom editorial** — How do editors manage reporters? Story pitches, editorial judgment, kill decisions, the desk structure. Layers of editorial review without bottlenecking.

8. **Organizational research** — Span of control theory, principal-agent problem, information asymmetry, delegation frameworks (RACI, etc.). What does the research say about effective oversight?

9. **Pair programming / mob programming** — Real-time collaboration models. Driver/navigator, thinking aloud, the role of the observer. When is tight coupling better than loose?

10. **Creative industries** — How do directors work with cinematographers, producers with showrunners, architects with contractors? The brief, the dailies, the review. Creative control at a distance.

For each domain, capture:
- The core insight about oversight/interface
- How information flows between the "overseer" and the "doer"
- What makes it work (or fail)
- A concrete idea for how The Forge could adopt it

### Deliverables
- Individual research docs in `research/` for each domain
- **Synthesis doc**: `research/human-ai-interface-synthesis.md` — top 5 interface models worth prototyping, with pros/cons and a recommendation for which to try first

### Constraints
- Stay in research stage — no implementation
- Think divergently first, then converge in the synthesis
- Don't just describe what exists — propose concrete mechanisms for The Forge
- Each idea should be specific enough that Forge could implement it in 2-3 heats

### Budget
10 heats

## 2026-04-09 16:00 — Direction: AI Worker Landscape Research

### What We Decided
Deep research sweep on the current state of autonomous AI workers — what exists, how they're architected, and what big ideas are emerging. The Forge has been building itself in relative isolation; it's time to map the landscape and identify what we're missing, what we're doing differently, and what ideas are worth stealing.

### Focus Areas
All 10 heats should be **research stage**. Cover these areas:

1. **Existing AI worker/agent frameworks** — Devin, SWE-Agent, OpenHands, Sweep, Aider, Claude Code itself, Cursor Agent, Windsurf, Codex CLI, etc. What's their architecture? How do they loop? How do they manage state?
2. **Orchestration patterns** — How do multi-agent systems coordinate? (CrewAI, AutoGen, LangGraph, Agency Swarm, etc.) What's working, what's hype?
3. **Memory and persistence** — How do long-running agents handle memory? Episodic stores, vector DBs, summarization chains, scratchpads. What's beyond flat files?
4. **Task decomposition and planning** — How do agents break down work? Tree-of-thought, plan-and-execute, ReAct, reflexion. What planning architectures actually work at scale?
5. **Self-improvement and evaluation** — How do agents assess their own output? LATS, self-reflection, reward models, human-in-the-loop signals.
6. **Big ideas and frontier thinking** — What's the boldest stuff being tried? Continuous learning, tool creation, world models, agent-to-agent delegation.

For each system or pattern, capture: architecture, key insight, limitation, and relevance to The Forge.

### Constraints
- Stay in research stage — no implementation, no protocol changes
- Write findings to `research/` as structured markdown docs
- Cite sources where possible (repos, papers, blog posts)
- End with a synthesis doc: `research/landscape-synthesis.md` summarizing top 5 ideas worth adopting

### Budget
10 heats
