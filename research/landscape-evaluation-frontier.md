# AI Worker Landscape: Self-Evaluation & Frontier Ideas

*Heat 83 | 2026-04-09*

## Self-Improvement & Evaluation

### Reflection Patterns (matured 2025-2026)

From simple "review your answer" → sophisticated multi-layer evaluation:

1. **Reflexion**: Agent maintains verbal memory of past mistakes. Uses natural language feedback to correct future behavior. The agent literally tells itself what went wrong.

2. **LATS** (Language Agent Tree Search): Combines Monte Carlo tree search with LLM reflection. Explores multiple solution paths, evaluates each, backtracks on failures. Like ToT but with formal search.

3. **Process Reward Models (PRMs)**: Score each intermediate step, not just the final output. Shifts evaluation from "is the answer right?" to "is each reasoning step right?"

4. **Intrinsic metacognitive learning**: Agent evaluates not just its output but its *learning process*. "Am I learning effectively? Should I change my approach?"

### Key Insight: Self-Assessment is Not Enough

The Forge rates each heat 0.0-1.0 (self-assessment). This is the weakest form of self-evaluation. Better approaches:

| Level | What | Example |
|-------|------|---------|
| L1: Rating | Score the output | Our current value (0.0-1.0) |
| L2: Critique | Explain what's wrong | "This heat was low-value because..." |
| L3: Revision | Fix the identified problem | Re-do the heat with corrections |
| L4: Meta-learning | Change the process | "I should approach research differently" |

The Forge does L1. We should add L2 (verbal self-critique in commit messages or worklog notes). L3 is our keep/discard mechanism. L4 would be protocol self-modification (dangerous but powerful).

### Relevance to The Forge

**What we do well**: Keep/discard pattern (L3), memory consolidation (basic L4)
**Gap**: No explicit self-critique (L2). The value rating (0.7 vs 0.8) doesn't explain *why*.
**Idea to steal**: Add a "self-critique" field to worklog entries — 1 sentence on what could be better. This feeds into the AAR (after-action review) at end of run.

---

## Frontier Ideas

### 1. Tool Creation
Agents that create their own tools when existing tools aren't sufficient. Example: an agent needs to parse a specific log format → creates a parser script → uses it in future tasks.

**Relevance**: The Forge already does this (forge-init.sh, forge-update.sh, forge-validate.sh planned). We CREATE tools as part of our implementation stage. This is a validated strength.

### 2. Continuous Learning from Episodic Memory
Agents that get better at tasks they've done before by retrieving relevant past experiences. MemRL (2026) uses reinforcement learning on episodic memory.

**Relevance**: Our MEMORY_DAILY/WEEKLY hierarchy is a simple version. The gap is retrieval — we read the whole file, not semantically relevant entries.

### 3. Agent-to-Agent Delegation
"Manager" agents decompose tasks and delegate to "worker" agents. Shared memory for collective learning. Conflict resolution mechanisms.

**Relevance**: Our Anvil→Forge dispatch system IS this pattern. Anvil delegates, Forge executes. The dispatch files are the shared communication channel. We could extend to Forge spawning sub-agents for parallel heats (using Claude Code's Agent Teams feature).

### 4. World Models
Agents that maintain internal models of their environment and can predict outcomes before acting. "What would happen if I changed the allocator formula?"

**Relevance**: Our STRATEGY.md is a weak world model — it describes the current state but doesn't predict outcomes. A proper world model would let the Forge simulate the effect of a protocol change before implementing it.

### 5. Frontier Agents as "Autonomous Partners"
The 2026 consensus: frontier agents solve three flaws of previous gen:
- **Amnesia**: Persistent memory across sessions
- **Isolation**: Access to tools and environment
- **Impatience**: Can work for hours/days without intervention

The Forge addresses all three: memory hierarchy, full tool access via Claude Code, and budget-bounded autonomy. We ARE a frontier agent by this definition.

## Summary: Top Ideas to Steal

| Idea | Source | Effort | Impact |
|------|--------|--------|--------|
| Self-critique in worklog | Reflexion pattern | 1 heat | Medium — improves feedback loop |
| PRM-style step evaluation | Process Reward Models | 3-4 heats | High — fundamentally better evaluation |
| Semantic memory retrieval | MemRL, vector DB | 5+ heats | High — enables learning at scale |
| Sub-agent delegation | Agent Teams, CrewAI | 3+ heats | Medium — enables parallel heats |
| Repo map for codebase awareness | Aider, SWE-Agent ACI | 2 heats | Medium — better code understanding |
