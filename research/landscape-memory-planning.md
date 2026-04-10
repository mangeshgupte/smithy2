# AI Worker Landscape: Memory Systems & Task Planning

*Heat 82 | 2026-04-09*

## Memory & Persistence

### Memory Taxonomy (consensus across sources)

| Type | What It Stores | Duration | Implementation |
|------|---------------|----------|----------------|
| **Short-term / Working** | Current task context | Within session | Context window |
| **Episodic** | Past events + outcomes | Cross-session | Vector DB, event logs |
| **Semantic** | Facts and knowledge | Permanent | Knowledge graph, flat files |
| **Procedural** | How to do things | Permanent | Code, protocol files |

### Key Patterns

**Vector DB for episodic memory**: ChromaDB, Pinecone, Weaviate store embeddings with metadata. Similarity search retrieves top-k relevant memories. This is the standard approach for cross-session persistence.

**Summarization chains**: Older interactions get summarized to fit within context windows. "Temporal reflection summaries" compress memory into time-bound reconciliations.

**Event logs for episodic recall**: Redis Streams or append-only logs capture what happened, what was done, what resulted. Case-based reasoning from historical outcomes.

**Recent research**: MemRL (2026) — self-evolving agents that learn from episodic memory via reinforcement learning. Agentic Memory (2026) — unified long/short-term management.

### Relevance to The Forge

Our memory hierarchy maps cleanly:

| Our System | Memory Type | Implementation |
|------------|-------------|----------------|
| Context window | Short-term | Claude's context |
| worklog.tsv | Episodic | Append-only TSV (event log) |
| MEMORY_DAILY.md | Episodic (summarized) | Markdown (consolidated every 6 heats) |
| MEMORY_WEEKLY.md | Semantic | Markdown (validated patterns) |
| Protocol files | Procedural | Markdown (how to do things) |
| identity.md | Semantic | Markdown (who we are) |

**Gap**: No vector DB or similarity search. Retrieval is position-based (read the file), not semantic. For 79 heats this works. For 500+ heats, we'd need semantic retrieval to find relevant past experiences.

**Key idea to steal**: **Temporal reflection summaries** — our MEMORY_DAILY consolidation is already this, but we could make it more structured: "Between heats X and Y, these patterns held true, and this is what changed."

---

## Task Decomposition & Planning

### Planning Architectures

**ReAct** (Reasoning + Acting): Thought → Action → Observation loop. Simple, good for short tasks. Degrades on long-horizon work because the agent loses sight of the goal.

**Plan-and-Execute**: Explicitly plan multi-step solution first, then execute steps sequentially. Better task completion rates than ReAct for complex tasks. Our heat loop IS plan-and-execute: the allocator plans (picks stage), then we execute (do the task).

**Tree of Thoughts (ToT)**: Explore multiple solution paths simultaneously, evaluate, converge. Good for brainstorming but expensive (multiple LLM calls per decision point).

**Reflexion**: Self-correction via verbal feedback. Agent critiques its own plan before acting. Our self-assessment (value rating) is a weak version of this — Reflexion goes further by actually revising the plan based on self-critique.

**Hierarchical Planning**: Tree-like structures of sub-tasks → atomic actions. Effective for multi-stage work. Our stages (research → planning → implementation → testing → editing → marketing) are a fixed hierarchy. DAG task dependencies add flexibility.

### Key Insight: Task Duration is Doubling Every 7 Months
Agents now handle 2-hour tasks autonomously, with projections for 8-hour workdays by late 2026. The Forge's heat model (5 minutes × N heats) is well-suited for this trend — just add more heats.

### Relevance to The Forge

| Pattern | Our Implementation | Gap |
|---------|-------------------|-----|
| Plan-and-Execute | Heat loop (allocator plans, Smith executes) | Solid — this is our core model |
| Reflexion | Self-assessment value (0.0-1.0) | Weak — should add explicit self-critique |
| Hierarchical Planning | 6-stage wavefront | Fixed hierarchy — could benefit from dynamic decomposition |
| Tree of Thoughts | Not used | Could use for research stage (explore multiple approaches) |
| ReAct | Not used (too simple for our model) | N/A |

**Key ideas to steal**:
1. **Explicit self-critique** (Reflexion): After each heat, ask "What would I do differently?" — not just rate the value
2. **Dynamic decomposition**: Allow the allocator to create sub-stages when a stage is too broad
3. **Plan verification**: Before executing, verify the plan still makes sense given current state
