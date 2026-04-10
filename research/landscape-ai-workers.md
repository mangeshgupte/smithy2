# AI Worker Landscape: Coding Agent Frameworks

*Heat 80 | 2026-04-09*

## 1. Devin (Cognition Labs)

**Architecture**: Full autonomous environment — spins up its own cloud with terminal, editor, browser. Uses LLM + reinforcement learning. Multi-agent operation in later versions.

**Key insight**: Devin has the same tools a human dev would: shell, editor, browser. It doesn't use special APIs — it uses the same interfaces. Self-assessed confidence evaluation added later, asking for clarification when uncertain.

**Limitation**: 13.86% fix rate on SWE-bench (autonomous). Expensive cloud infrastructure per session. Black-box — hard to inspect decision process.

**Relevance to The Forge**: Devin's confidence evaluation (asking when uncertain) maps to our Uncertainty Signaling idea. The "spin up an environment and walk away" model is similar to our heat-based autonomy, but Devin lacks our structured oversight mechanisms (stoplight, AAR).

## 2. SWE-Agent (Princeton/Stanford)

**Architecture**: Emphasized the critical importance of **agent-computer interfaces (ACIs)** — custom tools designed for AI, not human UIs. The interface between agent and environment matters more than the model.

**Key insight**: ACIs > raw tool access. Designing the right abstractions for the AI to interact with code (search, edit, navigate) is the main differentiator.

**Limitation**: Research-focused, not a product. Narrowly focused on bug fixing.

**Relevance to The Forge**: We use flat files as our ACI — CLAUDE.md, state.json, protocol/. Our "interface" is prose instructions, which is a radically different ACI philosophy (human-readable vs. machine-optimized). Worth questioning whether our ACI is optimal.

## 3. OpenHands (formerly OpenDevin)

**Architecture**: Event-sourced, stateless, composable. V1 refactored into SDK (agent logic), Tools (MCP integration), Workspace (file/git ops), Server (deployment). All interactions are immutable events in a log.

**Key insight**: **Event sourcing** — treat every action as an immutable event. State is derived by replaying events. This gives deterministic replay, debugging, and crash recovery for free.

**Limitation**: Complex architecture. 72% SWE-bench with Claude Sonnet 4.5 — strong but still fails 28%.

**Relevance to The Forge**: Our worklog.tsv IS an event log, but we don't use event sourcing properly — state.json is mutable, not derived. OpenHands' approach is more principled. Our flat-file state is simpler but less robust. The event-stream perception-action loop is conceptually similar to our heat loop.

## 4. Aider

**Architecture**: Terminal-based pair programming. Creates a **repository map** (function signatures + structure) for codebase awareness. Uses search/replace edit format for token efficiency. Auto-commits with descriptive messages. Tight lint→test→fix feedback loop.

**Key insight**: The **repo map** gives the LLM context about the entire codebase without reading every file. Edit format matters — search/replace is more accurate and token-efficient than whole-file rewrites. Auto-commit after each edit creates a clean, reviewable git history.

**Limitation**: Interactive, not autonomous. Requires human in the loop for direction. No long-running task management.

**Relevance to The Forge**: Aider's auto-commit pattern is exactly what we do (commit every heat). The repo map concept is interesting — we don't currently give the Smith a structural overview of the codebase. The lint→test→fix loop is a validation pattern we should adopt in our testing stage.
