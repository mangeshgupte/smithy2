# Adaptive Queue Management for Autonomous AI Workers

*Heat 47 | 2026-04-09*

## Question

How should The Forge generate tasks when the queue runs dry? What triggers research vs. implementation vs. other stages?

## Research Sources

- AutoGPT's iterative task creation agent
- CrewAI's role-based decomposition
- Lilian Weng's "LLM Powered Autonomous Agents" (2023)
- Oracle's AI Agent Loop architecture
- Various 2025-2026 agentic AI surveys

## Key Patterns from Other Systems

### 1. AutoGPT: Task Creation Agent
AutoGPT has a dedicated "task creation agent" that runs after each completed task. It takes the result of the completed task + the overall goal and generates new tasks. This is reactive — it waits for completion, then creates.

**Lesson for The Forge**: Don't pre-generate a huge backlog. Generate tasks incrementally, informed by what was just learned.

### 2. CrewAI: Role-Based Decomposition
CrewAI decomposes problems into roles. Each role has a goal and can generate its own sub-tasks. When a role finishes its queue, it asks "what else does my goal require?"

**Lesson for The Forge**: Each stage can have its own task generation heuristic based on what that stage needs.

### 3. Reflection + Adaptation
The fragile part of autonomous systems is the "reflection" step. Self-prompting loops can waste tokens if the agent spirals. Bounded reflection (max N attempts) prevents this.

**Lesson for The Forge**: Task generation should be fast (1 task, not a full planning session) and bounded.

### 4. Gap-Driven Generation
When schedules slip or queues empty, adaptive systems compare current state to desired state and generate tasks to close the gap.

**Lesson for The Forge**: The wavefront allocator already knows which stages are behind target. Use this to drive task generation.

## Design: Auto-Task-Generation for The Forge

### Trigger Conditions (check at Step 4 of the loop)

Generate new tasks when ANY of:
1. **Queue depth < 3** pending tasks total
2. **No ready tasks** for the allocator's chosen stage
3. **All pending tasks are blocked** (waiting on dependencies)

### Generation Strategy (per stage)

| Stage | How to Generate Tasks |
|-------|----------------------|
| **Research** | Look at STRATEGY.md "What's Missing" and "Risks & Unknowns". Pick the biggest unknown. Create a research task to investigate it. |
| **Planning** | Check if current version plan is complete. If not, plan the next task. If version plan is done, plan the next version. |
| **Implementation** | Check the plan for pending implementation tasks. If plan is empty, check research findings for implementable improvements. |
| **Testing** | Look at recently completed implementation tasks. Each one needs testing. Also check for untested protocol paths. |
| **Editing** | Check STRATEGY.md staleness (heats since last update). Check protocol files for inconsistencies. Check if documentation matches code. |
| **Marketing** | Check README completeness against features. Look for undocumented features, missing examples, or stale content. |

### Research Auto-Trigger (t-025 design)

When the system detects it's "running out of things to do" (queue < 3 AND no human priorities), it should:

1. Check if any research tasks are pending → if yes, no action
2. Read STRATEGY.md "What's Missing" section
3. Pick the top item from "What's Missing"
4. Create a research task: "Research: <topic from What's Missing>"
5. Add to queue with priority 1

This ensures the system always has work by exploring unknowns when execution work is exhausted.

### Implementation in Protocol

Add to `protocol/loop.md` Step 4, after "If no ready tasks for the chosen stage: generate one yourself":

```
Task generation heuristic:
1. Check STRATEGY.md "What's Missing" for the chosen stage
2. Check plan.md for incomplete tasks matching the stage  
3. Check recent worklog for follow-up opportunities
4. If none found: generate a research task on the biggest unknown

When queue.length < 3:
  - Also generate 1-2 tasks for the next-highest-scoring stage
  - This prevents the queue from repeatedly hitting empty
```

### Anti-Spiral Guard

To prevent the reflection/generation loop from wasting tokens:
- Max 1 generated task per heat (keep it focused)
- Generated tasks must be concrete and scoped to a single heat
- If the Smith generates 3 research tasks in a row on the same topic, flag it in outbox.md as "stuck" and ask the human for direction

## Recommendations for t-025 and t-028

**t-028 (planning)**: Add the generation heuristic to protocol/loop.md Step 4. Keep it simple — a few bullet points, not a complex algorithm.

**t-025 (implementation)**: The "auto-research trigger" is really just the queue-depth check + research generation strategy above. Implement it by:
1. Adding the queue-depth check to Step 4
2. Adding the "What's Missing" lookup for research generation
3. Adding the anti-spiral guard (3-in-a-row detection)
