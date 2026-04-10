# AI Worker Landscape: Orchestration Patterns & Runtime Environments

*Heat 81 | 2026-04-09*

## Multi-Agent Orchestration Frameworks

### CrewAI — Role-Based Teams
**Architecture**: Each agent has a role, goal, and backstory. Coordination via "Crews" (autonomous teams) and "Flows" (event-driven pipelines). Sequential or hierarchical process types.
**Key insight**: Role definition is the primary coordination mechanism. Agents with clear roles produce better output than general-purpose agents.
**Limitation**: 2x token usage and 3x latency vs LangGraph due to multi-step verification. Heavy abstraction layer.
**Relevance**: Our persona system (Anvil/Forge) IS role-based coordination. CrewAI validates the approach but suggests we should keep roles minimal — our 2-persona model is lighter than typical CrewAI setups.

### LangGraph — Graph-Based Workflows
**Architecture**: Directed graph with conditional edges. Agent interactions are nodes. Built-in checkpointing with time travel (replay any state).
**Key insight**: **Checkpointing with time travel** — can rewind to any previous state and replay from there. This is more powerful than our checkpoint file (which only saves current HEAD for rollback).
**Limitation**: Steep learning curve. Graph definition is complex for simple workflows.
**Relevance**: Our heat loop IS a simple graph (linear, with branches for exploration). LangGraph's checkpointing is superior — we should consider making worklog.tsv replayable (event sourcing).

### AutoGen/AG2 — Conversational GroupChat
**Architecture**: Multiple agents in a shared conversation. A selector agent decides who speaks next. In-memory conversation history.
**Key insight**: **Conversation as coordination** — agents coordinate by talking, not by message-passing or shared state. The selector is the key: it decides which agent should respond to each turn.
**Limitation**: Memory is conversation history — scales poorly. No persistent state beyond chat.
**Relevance**: Less relevant to The Forge's model. We use flat files for coordination (inbox/outbox/dispatch), which is more inspectable but less fluid than conversational coordination.

## Runtime Environments

### Claude Code
**Architecture**: TypeScript harness wrapping Claude. Tool use (bash, read, write, edit, grep, glob), sub-agent spawning, CLAUDE.md-driven behavior. Internal "KAIROS" daemon for autonomous operation. v2.0 adds Agent Teams (parallel sub-agents) and scheduled tasks.
**Key insight**: **CLAUDE.md IS the program.** The instructions in CLAUDE.md control the agent's behavior entirely through prose. This is exactly what The Forge does. We are literally built on this paradigm.
**Relevance**: We are inside Claude Code. Our protocol files are our CLAUDE.md. The Forge validates that prose-as-program works for sustained autonomous operation (79 heats and counting). Agent Teams could enable parallel heats across stages.

### OpenAI Codex CLI
**Architecture**: CLI tool wrapping GPT models. JSONL stdin/stdout communication. Sandbox execution environment.
**Key insight**: Sandboxed execution prevents accidental damage. The Forge has no sandbox — our checkpoint/rollback is the safety mechanism.
**Relevance**: Sandboxing would be valuable for testing stage, where bad code could break things. Our checkpoint mechanism is lightweight but less safe.

## Key Takeaways for The Forge

| Pattern | Used By | Our Status | Should Adopt? |
|---------|---------|------------|---------------|
| Event sourcing | OpenHands | Partial (worklog is append-only but state is mutable) | Yes — make state derivable from events |
| Checkpointing with time travel | LangGraph | Partial (checkpoint file for current heat only) | Maybe — replay from any heat would be powerful |
| Role-based agents | CrewAI | Yes (Anvil/Forge) | Keep it minimal |
| Repo map | Aider | No | Yes — give Smith structural awareness |
| Confidence/uncertainty | Devin | Planned (t-041) | Yes — already designed |
| Agent-computer interface | SWE-Agent | CLAUDE.md as ACI | Validate — is prose optimal? |
| Parallel agents | Claude Code v2 | No | Future — parallel heats |
| Lint→test→fix loop | Aider | No | Yes — for implementation stage |
