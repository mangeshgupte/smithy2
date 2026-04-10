# Strategic Plan — The Forge

*Updated after chunk 8 | 2026-04-09*

## Vision

An autonomous AI coworker that works in bounded 5-minute chunks, self-directs across project stages, and communicates asynchronously with a human. Given a budget and a project, it does useful work while the human is away.

## Current State

### What Exists

**Core protocol** (working, validated by 5-chunk dogfood run):
- `CLAUDE.md` — 30-line hub pointing to protocol files
- `protocol/loop.md` — 8-step heat loop with stuck detection, output redirection, keep/discard
- `protocol/allocator.md` — wavefront model + PI controller for stage selection
- `protocol/logging.md` — worklog format, state updates, memory writes, self-assessment

**State infrastructure** (working):
- `state.json` — budget, stage stats, task queue, allocator integral
- `worklog.tsv` — append-only chunk log (5 entries)
- `inbox.md` / `outbox.md` — async human-AI communication (dual-channel: file + prompt)
- `MEMORY_DAILY.md` — 4-level memory hierarchy (L1 worklog → L2 daily → L3 weekly → L4 identity)

**Research** (initial survey complete):
- `research/autonomous-loop-patterns.md` — 8 patterns from autoresearch, Gas Town, NanoClaw, Memory Substrate

### Stage Progress

| Stage | Progress | Chunks | Notes |
|-------|----------|--------|-------|
| Research | 40% | 2 | Survey + deep dive on session cycling. Checkpoint files, SessionEnd hooks mapped out. |
| Planning | 30% | 1 | Task queue created. Plan.md has 5 prioritized items. |
| Implementation | 50% | 3 | Protocol gaps + idea pipeline + heat dashboard + idea status annotations. |
| Testing | 10% | 1 | Protocol consistency check done. No automated tests yet. |
| Editing | 20% | 1 | Inbox convention added. CLAUDE.md already split to hub+protocol. |
| Marketing | 0% | 0 | No README or docs yet. |

**Overall progress**: ~25% | **Chunks used**: 8 | **Wavefront phase**: early→middle

### What's Working

- The wavefront allocator correctly shifts effort through the dependency chain
- 5 chunks touched 5 different stages — no stage hoarding
- Exploration rule (every 5th chunk) fires correctly
- Flat-file state is transparent and git-tracked
- Protocol files are modular and human-readable

### What's Missing

- No automated testing (protocol is tested manually by running it)
- No README or external documentation
- No messaging integration (inbox.md only, no Telegram/Slack)
- No episodic memory store (flat files only)
- No hard timeout enforcement on chunks

## Main Ideas Being Tried

### 1. Wavefront Resource Allocation
**Status**: Validated in first run
**Idea**: Instead of fixed phase buckets (early/middle/late with hardcoded percentages), compute dynamic targets from a dependency chain. Each stage's benefit = `prerequisite_readiness * (1 - own_progress)`. Effort naturally flows research → planning → implementation → testing → editing → marketing as each stage reaches sufficiency.
**Result so far**: Works well. The allocator moved through all 5 stages in 5 chunks with no manual steering. The PI controller prevents oscillation and the 0.05 floor prevents starvation.
**Open question**: At what progress level should a stage be considered "done enough" to stop receiving allocation? Currently benefit approaches 0 as progress → 1.0, which is correct.

### 2. CLAUDE.md as the Entire Orchestrator
**Status**: Validated in first run
**Idea**: No Python, no SDK, no subprocess management. Claude Code reads CLAUDE.md and protocol files, follows the instructions, reads/writes flat files. The "program" is prose.
**Result so far**: Works. Claude correctly follows the 8-step loop, computes allocator math inline, manages state.json, and commits each chunk's work.
**Open question**: Will this scale past ~50 chunks in a single session? Context window may become a constraint. May need session-cycling (fresh Claude Code session, reads state, continues).

### 3. Self-Assessed Value Signal
**Status**: In use, not yet validated
**Idea**: The Smith rates each chunk 0.0-1.0 for productivity. This feeds the allocator's value_ema, biasing toward stages where work has been productive.
**Result so far**: Values assigned (0.7-0.8 range) but the signal hasn't meaningfully differentiated stages yet. Need more chunks to see if it creates useful bias.
**Open question**: Is self-assessment reliable enough? Could be biased toward "felt productive" vs "actually moved the needle."

### 4. Dogfooding (Building Itself)
**Status**: In progress
**Idea**: The first project the Forge works on is the Forge itself. This surfaces protocol issues immediately — if the loop has a gap, the Smith hits it while running.
**Result so far**: Effective. The consistency check in chunk 5 found two real issues (run continuation semantics, task ID format). Research in chunk 1 identified 5 gaps that were mostly fixed by chunk 4.

### 5. Dual-Channel Human Input + Idea Pipeline
**Status**: Implemented (enhanced in chunk 6)
**Idea**: Human communicates via inbox.md (async) or prompt. Both processed the same way. Ideas flow through a 4-step pipeline: capture → evaluate (actionable/research/strategic/done) → track (ideas array in state.json with status and linked task_id) → acknowledge (outbox confirmation).
**Result so far**: 4 ideas tracked so far, all status "done". Pipeline provides traceability from human input to action taken.
**Open question**: Will the ideas array grow too large? May need pruning of "done" ideas after they're old enough.

## Risks & Unknowns

1. **Context window scaling**: A 50-chunk run in one session will push context limits. Need to test and plan for session cycling.
2. **Value signal noise**: Self-assessment may not produce useful differentiation. May need external signals (test pass rate, commit size, human feedback).
3. **Single-session fragility**: If the Claude Code session crashes mid-heat, state may be inconsistent. Stuck detection helps but isn't bulletproof.
4. **Allocator cold start**: With 0 progress everywhere, research always wins. The wavefront naturally handles this, but the first few chunks are predictable.

## Roadmap

| Version | Focus | Key Feature |
|---------|-------|-------------|
| **v0.1** (now) | Core protocol | Heat loop, wavefront allocator, flat-file state |
| **v0.2** | Messaging | Telegram/Slack sidecar bridging inbox/outbox |
| **v0.3** | Multi-project | State per project, project switching |
| **v0.4** | Design debate | AI Collaborator integration — Smith opens PRs for decisions |
| **v0.5** | Dashboard | Web UI (htmx) — worklog, allocations, memory viewer |
| **v0.6** | Semantic memory | ChromaDB episodic store, semantic retrieval across chunks |
| **v0.7** | Headless mode | Python orchestrator wrapping Claude Code for unattended runs |
