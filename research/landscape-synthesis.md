# AI Worker Landscape Synthesis

*Heat 84 | 2026-04-09*

## What We Researched

4 research documents covering 6 areas across the autonomous AI worker landscape:

| Area | Doc | Key Systems/Patterns |
|------|-----|---------------------|
| AI worker frameworks | landscape-ai-workers.md | Devin, SWE-Agent, OpenHands, Aider |
| Orchestration patterns | landscape-orchestration.md | CrewAI, LangGraph, AutoGen, Claude Code, Codex CLI |
| Memory & persistence | landscape-memory-planning.md | Vector DB, episodic stores, summarization chains |
| Task planning | landscape-memory-planning.md | ReAct, Plan-Execute, ToT, Reflexion |
| Self-evaluation | landscape-evaluation-frontier.md | LATS, PRMs, metacognitive learning |
| Frontier ideas | landscape-evaluation-frontier.md | Tool creation, world models, agent delegation |

## Where The Forge Sits in the Landscape

### What We're Doing That Others Aren't

1. **Prose-as-program**: CLAUDE.md + protocol files define behavior entirely through natural language. No Python orchestrator, no SDK wrapper. Most frameworks require code to define agent behavior.

2. **Wavefront allocator**: Dynamic effort allocation across stages using a PI controller. No other system we found uses control theory for resource allocation across project phases.

3. **Budget-bounded autonomy**: Fixed heat budget with explicit start/stop. Most agents run until done or until they hit an error. Budget-bounding is a feature, not a limitation.

4. **Flat-file state**: Everything inspectable via `cat`. Most systems use databases, vector stores, or opaque internal state. Our transparency is unusual and valuable.

5. **Self-dogfooding**: Building the system using the system. Only Aider comes close (they use Aider to develop Aider).

### What We're Missing That Others Have

1. **Event sourcing** (OpenHands): Our state.json is mutable. We should derive state from the event log (worklog.tsv) instead of maintaining parallel state.

2. **Semantic memory retrieval** (vector DBs): We read whole files. At 500+ heats, we'll need similarity search to find relevant past experiences.

3. **Repo map** (Aider): We don't give the Smith a structural overview of the codebase. This matters more for non-dogfood projects.

4. **Explicit self-critique** (Reflexion): Our 0.0-1.0 value rating doesn't explain why. Adding verbal self-critique would improve the feedback loop.

5. **Parallel execution** (Claude Code Agent Teams): We run one heat at a time. Parallel heats across stages would increase throughput.

6. **Lint→test→fix loop** (Aider): Our implementation stage doesn't automatically validate output. We should run tests after code changes and fix failures in the same heat.

## Top 5 Ideas Worth Adopting

### 1. Self-Critique in Worklog (from Reflexion)
**What**: Add a 1-sentence self-critique to each worklog entry: "What could be better about this heat?"
**Why**: Our value rating (0.7-0.8 cluster) doesn't differentiate. Verbal self-critique surfaces specific improvement opportunities.
**Effort**: 1 heat (protocol change only)
**Impact**: Medium — improves AAR quality, helps human spot patterns

### 2. Repo Map for Non-Dogfood Projects (from Aider)
**What**: At the start of each run on a non-dogfood project, generate a structural map of the codebase (key files, functions, dependencies). Store in `repo-map.md`.
**Why**: The Smith needs codebase awareness to make good implementation decisions. Without a map, it's coding blind.
**Effort**: 2 heats
**Impact**: High for non-dogfood use — essential for real projects

### 3. Event-Sourced State (from OpenHands)
**What**: Make worklog.tsv the authoritative record. Derive state.json from worklog entries. Add a `forge-rebuild-state` command that reconstructs state from the log.
**Why**: Eliminates state corruption risk. If state.json gets corrupted, rebuild it. Enables "time travel" — reconstruct state at any heat.
**Effort**: 3-4 heats
**Impact**: High for robustness — eliminates a whole class of bugs

### 4. Lint→Test→Fix Loop (from Aider)
**What**: After implementation heats that create/modify code, automatically run tests (if they exist). If tests fail, attempt a fix in the same heat. Only commit if tests pass.
**Why**: Catches bugs immediately instead of in a separate testing heat. Tighter feedback loop.
**Effort**: 2 heats
**Impact**: High for code quality on real projects

### 5. Parallel Heats via Sub-Agents (from Claude Code Agent Teams)
**What**: For independent stages (e.g., testing + documentation), spawn sub-agents to work in parallel. Use git worktrees for isolation.
**Why**: 2x-3x throughput on long runs. Some stages are genuinely independent.
**Effort**: 5+ heats (complex — needs worktree management, merge strategy)
**Impact**: High for throughput but complex to implement correctly

## Strategic Recommendations

1. **Immediate (next 5 heats)**: Implement self-critique (#1) and the interface research findings (stoplight, uncertainty, intent). These are low-effort, high-impact protocol changes.

2. **Short-term (next 20 heats)**: Build repo map (#2) and lint→test→fix (#4) — essential before running on real projects.

3. **Medium-term (next 50 heats)**: Event-sourced state (#3) — important for long-running reliability.

4. **Long-term**: Parallel heats (#5) and semantic memory retrieval — these are complex features that require significant design work.

## What We're Doing Right (Validated by Landscape)

- **Budget-bounded autonomy** is a real differentiator — most agents lack this discipline
- **Flat-file transparency** is valuable and unusual — don't abandon it for a database
- **Prose-as-program** works at scale (79 heats) — this validates CLAUDE.md-driven architecture
- **Wavefront allocator** is unique and effective — no other system has this
- **Self-dogfooding** is the fastest path to a robust system
