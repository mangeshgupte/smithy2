# Strategic Plan — The Smithy

*Updated after heat 641 | 2026-04-11*

## Vision

An autonomous AI coworker (The Smithy) that works in bounded 5-minute heats, self-directs across project stages, and communicates asynchronously with a human. Bookkeeping is deterministic via the `smithy` CLI. Given a budget and a project, it does useful work while the human is away.

## Retrospective Format (2026-04-12)

**Retros must end in candidates with value-theses, not things-to-consider.** Explicit rationale per candidate makes triage trivial and compounds into shipped work. The t-302 retro (`research/steering-patterns-retrospective.md` §6) shipped 4 of 6 candidates within one session (t-305, t-306, t-307, t-309). Apply this format to all future retros.

## Steering Philosophy (2026-04-12)

**Ranking over constraints.** Hard constraints are an anti-pattern — they tend to over-specify the problem, produce brittle infeasibilities, and hide the human's real preference signal. We steer via rankings instead: human rank + agent priority signal, composed into an ordering the human can nudge at any time (downrank, deprioritize, reorder). The Constraints UI is retired. Steerability = visible queue + visible outcomes + cheap one-gesture re-ranking.

## Relationship to Gas Town

**Decision: Approach B** — adopt Gas Town's best patterns, stay independent.

Gas Town is a Go-based multi-agent orchestration framework (20+ agents, Dolt-backed). Smithy is a single-agent self-directed system (flat JSON, Python CLI). They're complementary:

- **Adopted from Gas Town**: session cycling (handoff/resume), discover-don't-track (patrol), GUPP principle
- **Unique to Smithy**: wavefront allocator, 4-level memory hierarchy, self-assessment, AAR, budget system
- **Deferred**: Dolt backend (optional, for multi-agent future), multi-agent coordination

See `research/gas-town-integration-synthesis.md` for the full analysis.

## Current State

### What Exists

**Core protocol** (working, validated across 45 heats):
- `CLAUDE.md` — 30-line hub pointing to protocol files
- `protocol/loop.md` — 8-step heat loop with stuck detection, output redirection, keep/discard
- `protocol/allocator.md` — wavefront model + PI controller for stage selection
- `protocol/logging.md` — worklog format, state updates, memory writes, self-assessment

**State infrastructure** (working):
- `state.json` — budget, stage stats, task queue, allocator integral
- `worklog.tsv` — append-only heat log (45 entries)
- `inbox.md` / `outbox.md` — async human-AI communication (dual-channel: file + prompt)
- `MEMORY_DAILY.md` / `MEMORY_WEEKLY.md` — 4-level memory hierarchy

**Persona system** (working, consolidated in heat 38):
- Anvil — human interface (Lens hat + Strategy hat)
- Forge — autonomous worker (runs all 6 stages)
- `dispatch/` — flat-file inter-persona communication

**Scaffolding** (working):
- `forge-init.sh` — scaffold new projects with guided templates
- `hooks/session-end-forge.sh` — automatic memory distillation on session end

**Research** (8 artifacts):
- Autonomous loop patterns, session cycling, automation, integral windup, beads DAG, value measurement, real-project readiness

### Stage Progress

| Stage | Progress | Heats | Notes |
|-------|----------|--------|-------|
| Research | 90% | 33 | Landscape, Gas Town, PWA, subjects, steering patterns. |
| Planning | 85% | 33 | Sprint planning, mid-sprint reviews. |
| Implementation | 98% | 221 | Smithy CLI (28 cmds), Tutor (5 subjects, PWA, sessions), Bellows, 4 steering UIs. |
| Testing | 88% | 117 | 172 tests (111 tutor + 16 bellows + 45 smithy). Patrol clean. |
| Editing | 88% | 153 | Protocol, STRATEGY, CHANGELOG v1.4, READMEs, WALKTHROUGH. |
| Marketing | 84% | 84 | AARs, dispatch reports, CHANGELOGs, walkthrough. |

**Overall progress**: ~90% | **Heats used**: 641 | **Wavefront phase**: mature

### What's Working

- Wavefront allocator with 3 fixes (soft clamp, unblocking override, queued task bonus) — balanced across 188 heats
- **3 real projects built**: the-smithy (dogfood), ai-tutor (4-subject tutor with full Learn→Create→Review loop), Bellows (project dashboard)
- Commissioner App: 6 screens, tap-to-decide, day-grouped activity, inbox badges, feedback UI
- AI Tutor: 3-tab nav, student flashcards + AI review, SM-2 card player, teach-it-back, streak, session memory, 6 animations, 100 tests
- forge-init.sh + forge-update.sh + forge-validate.sh + forge-status.sh — full tool suite
- 5 interface models implemented: stoplight, uncertainty, commander's intent, AAR, L0-L4 compression
- Personas (Anvil + Forge + Chisel) with dispatch system
- Auto-task generation, DAG dependencies, idea pipeline
- 19 automated integrity checks (forge-validate)
- Comprehensive docs: README, FAQ, CHANGELOG, AARs, reporting.md

### What's Missing

- **Full-log browser surface** — extends the activity side-panel past its 20-entry cap
- **Cross-project activity view** in Bellows — portfolio-level merge of per-project feeds
- **Steering intent validation** — counterfactual framing ("would Forge have worked on this anyway?") for pin/reorder
- **Idle-state UX** — explain *why* when queue empty or Forge idle (budget exhausted, no intent, waiting on Marshal)
- **Feedback loop closure** — surface "what changed" in response to feedback.md entries

_Audited at heat 777 (t-358). Prior list (PWA, teach-it-back, t-044/t-045/t-046, WhatsApp, vector DB, parallel heats) shipped or superseded — see `research/strategy-whats-missing-audit.md`._

## Main Ideas Being Tried

### 1. Wavefront Resource Allocation
**Status**: Validated (55 heats), improved at heat 51
**Result**: Works well. Soft clamp (±0.5) and unblocking override added to fix integral recovery trap. Effort naturally distributed across all 6 stages.

### 2. CLAUDE.md as the Entire Orchestrator
**Status**: Validated (45 heats, multiple sessions)
**Result**: Works. The Smith correctly follows protocol, computes allocator math inline, manages state. Session cycling confirmed viable at 28KB cold start.
**Open question**: Approaching 50 heats in this session — context compression working but monitoring.

### 3. Self-Assessed Value Signal
**Status**: In use, weakly validated
**Result**: Values cluster in 0.7-0.8 range. Limited differentiation between stages. The signal feeds value_ema but doesn't strongly influence allocation compared to error and integral terms.

### 4. Dogfooding (Building Itself)
**Status**: Mature, approaching diminishing returns
**Result**: 45 heats of self-improvement. Real-project readiness assessment (heat 40) found 5 concrete gaps. The protocol is solid enough to try non-dogfood use.

### 5. Dual-Channel Human Input + Idea Pipeline
**Status**: Validated
**Result**: 10 ideas tracked (all done). Pipeline provides full traceability from human input to action.

### 6. Persona System
**Status**: Implemented, lightly tested
**Result**: Anvil (interface) + Forge (worker) with dispatch files. Consolidated from 3 to 2 personas after finding Lens/Anvil overlap. Verified in heat 39.

### 7. Coordination Model: Agent Teams (Decision)
**Status**: Decided (heat 690)
**Decision**: Use Claude Code Agent Teams as the primary coordination model. Anvil is the lead agent — it spawns Marshal and Forge as teammates via the `Agent` tool. Communication uses `SendMessage`, shared task lists via `TaskCreate`/`TaskList`.

**Rejected alternative**: Independent tmux sessions coordinated via file-based dispatch + `smithy nudge`. This was built (t-262 through t-266) but Agent Teams provides native messaging, idle notifications, and shared task state without custom infrastructure.

**Known limitation**: Agent Teams is single-session — all teammates are subprocesses of the lead. The `smithy start-all` command (independent tmux windows) cannot use Agent Teams. It remains available as a fallback for crash-resilient scenarios.

**Persona cwd workaround**: The Agent tool spawns in the caller's cwd. Spawn prompts must explicitly `cd` to the persona directory and read the persona's own CLAUDE.md to avoid loading the wrong protocol.

## Hypotheses

### Active — Being Tested Now

| # | Hypothesis | Status | Evidence |
|---|-----------|--------|----------|
| H5 | Stoplight signals compress oversight information | ~ early signal | 2 yellows surfaced real issues (heats 121, 142). Need more data. |
| H7 | AAR captures the "why" behind decisions | ~ early signal | AARs generated for both project runs. Need human review of usefulness. |

### Parked

| # | Hypothesis | Status | Evidence |
|---|-----------|--------|----------|
| H4 | Self-assessed value signal differentiates stages | ~ inconclusive | 0.7-0.8 cluster, no meaningful differentiation yet |

### Validated — No Further Testing

| # | Hypothesis | Status | Evidence |
|---|-----------|--------|----------|
| H1 | Wavefront allocation balances effort across stages | ✓ validated | 155 heats, no manual steering, all 6 stages covered |
| H2 | Prose-only orchestration (CLAUDE.md) scales | ✓ validated | Multi-session, 28KB cold start, session cycling works |
| H3 | Dogfooding surfaces real protocol issues | ✓ validated | Consistency checks, windup fix, stuck detection — all found by running |
| H8 | Forge produces useful output on non-self projects | ✓ validated | Tutor + Commissioner both functional. Human: "good for a first attempt" |
| H9 | The human can assess quality quickly | ✓ validated | Human assessed both apps in minutes, gave directional feedback |
| H10 | Forge's strategic decisions align with human intent | ✓ validated | Tutor followed "adults + Python + Socratic", Commissioner followed Chisel's spec |
| H6 | Commander's intent maintains strategic coherence | ✓ validated | No drift observed across either 15-heat run |

## Risks & Unknowns

1. **Non-dogfood viability**: Has only been tested on itself. t-036 ready to test this.
2. **Value signal noise**: Self-assessment doesn't meaningfully differentiate stages (0.7-0.8 cluster).
3. **Context growth**: At 55 heats, context compression is active. Session cycling validated but not stress-tested.
4. **Allocator integral recovery**: Fixed with soft clamp (±0.5) + unblocking override. Implementation integral recovering from -0.35.

## Roadmap

| Version | Focus | Status |
|---------|-------|--------|
| **v0.1** | Core protocol | **COMPLETE** (heats 1-5) |
| **v0.2** | Robustness + scaffolding | **COMPLETE** (heats 6-25) |
| **v0.3** | Personas + production readiness | **MOSTLY COMPLETE** (heats 26-38) |
| **v0.4** (now) | Multi-project + real-world readiness | IN PROGRESS (heats 39+) |
| **v0.5** | Messaging sidecar (WhatsApp) | PLANNED (deferred — build when ready) |
| **v0.6** | Web dashboard (htmx) | PLANNED |
| **v0.7** | Semantic memory (ChromaDB) | PLANNED |
