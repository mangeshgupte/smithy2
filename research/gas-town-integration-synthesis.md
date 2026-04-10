# Gas Town Integration Synthesis

*Heat 482 research | 2026-04-10*

## Three Approaches

### Approach A: Smithy as Gas Town Rig Type

**Feasibility**: Medium. Gas Town's polecat model (hook → execute → done) maps to Forge's heat loop. But Gas Town has no concept of:
- Bounded heat runs with budget
- Wavefront allocation across 6 stages
- Self-assessed value signals
- 4-level memory hierarchy

**What you gain**: Multi-agent coordination, merge queue, Dolt-backed state, scheduler, plugin system, session cycling infrastructure.

**What you lose**: Autonomy model (GUPP replaces allocator-driven self-direction), memory hierarchy (CV chain replaces STRATEGY/MEMORY), flat-file simplicity.

**Effort**: 30-50 heats. Need to: (1) port smithy state to Dolt schema, (2) implement Forge as a polecat preset, (3) port allocator to work with Gas Town's dispatch model, (4) adapt memory system to work alongside CV chain.

### Approach B: Adopt Gas Town Patterns into Smithy

**Feasibility**: High. Cherry-pick the best ideas without taking the dependency:
- **Handoff protocol** → already partially done (session memory)
- **Discover, don't track** → useful for validation/patrol
- **GUPP** → Forge already has this ("NEVER STOP")
- **Session cycling** → add `smithy handoff` command
- **Dolt** → could add optional Dolt backend to smithy CLI later

**What you gain**: Best patterns without Dolt dependency or Go codebase dependency.

**What you lose**: Multi-agent coordination (would need to build from scratch), merge queue.

**Effort**: 10-15 heats. Add `smithy handoff`, improve session recovery, adopt discover-don't-track in validation.

### Approach C: Fork Gas Town

**Feasibility**: Low. Gas Town is 65+ Go packages, deeply integrated. Forking means maintaining a large Go codebase alongside Smithy's Python CLI.

**Drift risk**: High — Gas Town is actively developed. Fork would diverge quickly.

**Not recommended** unless Smithy plans to become a multi-agent Go system.

## Recommendation: Approach B (Adopt Patterns)

**Why**: Smithy and Gas Town solve different problems at different scales:
- **Gas Town**: 20+ agents on multiple projects, infrastructure-heavy, merge queue, Dolt persistence
- **Smithy**: 1 agent on 1 project, self-directed, memory-rich, flat-file simplicity

They're complementary, not competitors. Smithy's innovations (wavefront allocator, memory hierarchy, self-assessment, AAR) fill gaps Gas Town doesn't address. Gas Town's innovations (session cycling, handoff, discover-don't-track) improve Smithy's robustness.

**First 10 implementation heats:**

1. `smithy handoff` — save session context for successor (2 heats)
2. `smithy patrol` — discover-don't-track validation of state (2 heats)
3. Adopt session cycling mindset in protocol — context recovery on startup (2 heats)
4. Research Dolt as optional backend for smithy state (2 heats)
5. Document the Smithy ↔ Gas Town relationship in STRATEGY.md (2 heats)

**How this affects the smithy CLI plan**: Continue targeting flat JSON files. Add optional Dolt backend later (if/when multi-agent is needed). The CLI abstraction layer means the backend can change without affecting the LLM's interface.

## What Smithy Should Contribute Back

If Smithy's innovations prove valuable, they could be ported to Gas Town:
1. **Memory hierarchy** — CV chain + STRATEGY.md + MEMORY_DAILY consolidation
2. **Wavefront allocator** — automatic stage balancing for polecat work
3. **Self-assessment** — per-bead quality signals for oversight
4. **AAR** — structured learning capture per work batch

These address Gas Town's strategic memory gap without changing its architecture.
