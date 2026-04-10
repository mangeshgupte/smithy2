# Strategic Plan — The Forge

*Updated after heat 79 | 2026-04-09*

## Vision

An autonomous AI coworker that works in bounded 5-minute heats, self-directs across project stages, and communicates asynchronously with a human. Given a budget and a project, it does useful work while the human is away.

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
| Research | 80% | 17 | + human-AI interface: 10 domains, 22 ideas, synthesis with top 5 models. |
| Planning | 70% | 10 | + v0.5 plan, queued task bonus, interface research planning. |
| Implementation | 82% | 15 | + forge-update.sh, auto-task generation, .gitignore. |
| Testing | 63% | 13 | + forge-update.sh E2E, unblocking override edge cases, non-dogfood scaffold. |
| Editing | 68% | 14 | + protocol consistency 22/22, interface research logging, memory consolidation. |
| Marketing | 60% | 9 | + FAQ, file structure, Anvil dispatch report. |

**Overall progress**: ~71% | **Heats used**: 79 | **Wavefront phase**: late

### What's Working

- Wavefront allocator with soft clamp (±0.5) + unblocking override — balanced across 55 heats
- Exploration rule (every 5th heat) + unblocking override (critical-path boost) prevent both stagnation and recovery traps
- DAG task dependencies with ready detection
- forge-init.sh with guided templates, .gitignore, E2E tested
- 2-persona system (Anvil + Forge) with dispatch files
- SessionEnd hook for automatic memory distillation
- Checkpoint file for crash recovery
- Idea pipeline: 10/10 human ideas processed
- Auto-task generation heuristic designed (per-stage, anti-spiral guard)
- README with examples, FAQ, dashboard output, hook docs
- Data integrity verified: 8 automated checks pass

### What's Missing

- No non-dogfood project attempted yet — **priority, t-027 ready**
- No forge-update.sh for protocol updates (t-026, ready)
- No auto-task generation in protocol yet (t-025, ready — design complete)
- No --with-personas flag for forge-init.sh (t-023, ready)
- No messaging integration — WhatsApp bridge planned (v0.5, not yet started)
- No episodic memory store — v0.6
- No hard timeout enforcement on heats

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

## Risks & Unknowns

1. **Non-dogfood viability**: Has only been tested on itself. t-027 is ready to test this.
2. **Value signal noise**: Self-assessment doesn't meaningfully differentiate stages (0.7-0.8 cluster).
3. **Context growth**: At 55 heats, context compression is active. Session cycling validated but not stress-tested.
4. **Allocator integral recovery**: Fixed with soft clamp (±0.5) + unblocking override. Implementation integral recovering from -0.50.

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
