# Plan

## v0.1: Core Protocol — COMPLETE (heats 1-5)
## v0.2: Robustness + New Project Support — COMPLETE (heats 6-25)

## v0.3 Plan: Production Readiness

### Goal
Make The Forge reliable for real daily use. Session cycling, proper testing, protocol hardening.

### Tasks

| ID | Stage | Description | Effort | Blocked By |
|----|-------|-------------|--------|------------|
| t-013 | implementation | Wire up SessionEnd hook in .claude/settings.json | Small | |
| t-014 | implementation | Add /loop integration for auto-restart within session | Medium | |
| t-015 | testing | End-to-end test: run forge-init.sh on a fresh project, run 3 heats | Medium | |
| t-016 | editing | Protocol review: ensure all files consistent after 25 heats of edits | Small | |
| t-017 | planning | Design multi-project state isolation strategy | Small | |
| t-018 | research | Research how to measure actual value (not just self-assessment) | Small | |
| t-019 | implementation | Add allocator visualization to STRATEGY.md (wavefront chart) | Small | |
| t-020 | marketing | Write a "How The Forge Works" deep-dive doc | Medium | |

### What "done" looks like for v0.3
- Can start a fresh project via forge-init.sh and run 20 heats unattended
- SessionEnd hook wired up and distilling memory automatically
- Protocol reviewed and consistent
- At least one non-dogfood project attempted

## v0.3 Status: Mostly Complete

Done: t-013 (settings), t-015 (E2E test), t-016 (protocol review), t-018 (value research), t-019 (wavefront viz), t-020 (deep-dive doc).
Remaining: t-014 (/loop integration), t-017 (multi-project isolation design).

## What's Actually Needed Next

The protocol and infrastructure are solid. The gap is: **nobody has used this on a real project yet.** The most valuable thing now is:

1. **Dogfood on a different project** — use forge-init.sh on a real codebase and run 10 heats
2. **Multi-project isolation** (t-017) — needed before above
3. **Polish the documentation** — deep-dive doc exists but STRATEGY.md needs a refresh

## v0.4: Multi-Project + Real-World Readiness

### Goal
Make The Forge work reliably on non-dogfood projects. Complete the gaps found in heat 40's readiness assessment.

### Multi-Project Isolation Design (t-017)

**Decision: Full isolation per project.** Each forge-init'd project is a self-contained directory with its own state, memory, and protocol files.

| Concern | Approach |
|---------|----------|
| State | Fully isolated — each project has its own state.json, worklog, memory |
| Protocol | Copied, not symlinked — explicit > implicit. Updates via `forge-update.sh` |
| Memory | Per-project only — no cross-project memory sharing (too risky) |
| Personas | Optional, per-project — only needed for complex projects |
| Discovery | No global index — each project is a git repo with CLAUDE.md |

**Why copy over symlink?** Symlinks create invisible dependencies. If the source protocol changes mid-run on another project, behavior becomes unpredictable. Copying means each project has a known-good snapshot.

**Migration path:** `forge-update.sh` copies latest protocol files into an existing project, preserving state files. Git diff shows what changed.

### Tasks

| ID | Stage | Description | Priority | Blocked By |
|----|-------|-------------|----------|------------|
| t-021 | implementation | Add .gitignore to forge-init.sh scaffold | 1 | |
| t-023 | implementation | Add --with-personas flag to forge-init.sh | 3 | t-021 |
| t-025 | implementation | Auto-research trigger when queue depth < 3 | 2 | |
| t-026 | implementation | Create forge-update.sh for protocol updates | 2 | |
| t-027 | testing | Scaffold + run 3 heats on a real (non-dogfood) project | 1 | t-021 |
| t-028 | planning | Design auto-research trigger logic in allocator | 2 | |

### Auto-Task Generation Design (t-028)

**Trigger**: At Step 4 of the loop, after picking a stage, check:
1. Queue has < 3 pending tasks total → generate 1-2 tasks
2. No ready tasks for chosen stage → generate 1 task for that stage
3. All pending tasks are blocked → generate 1 unblocked task

**Generation heuristic per stage:**

| Stage | How to Generate |
|-------|-----------------|
| Research | Read STRATEGY.md "What's Missing". Pick biggest unknown. |
| Planning | Is current version plan complete? If yes, plan next version. |
| Implementation | Check plan.md for pending impl tasks. If empty, check research for implementable improvements. |
| Testing | Find recently completed implementation tasks. Each needs testing. |
| Editing | Check STRATEGY.md staleness (heats since update > 5). Check protocol consistency. |
| Marketing | Check README against features. Find undocumented features. |

**Protocol change** (to loop.md Step 4): Add after "generate one yourself":
```
Queue health check (before picking a task):
  pending_count = count of queue items with status "pending"
  if pending_count < 3:
    generate 1-2 tasks using the heuristic above for the highest-scoring stages
    add to queue with status "pending"

Anti-spiral: if 3 consecutive generated research tasks target the same topic,
  write to outbox.md: "Stuck on <topic> — need human input"
```

**Implementation (t-025)**: Add the queue-depth check and generation heuristic to loop.md. This is a small protocol edit, not code.

### What "done" looks like for v0.4
- forge-init.sh produces complete, ready-to-run scaffolds (with .gitignore)
- forge-update.sh exists for protocol updates
- At least one non-dogfood project has been scaffolded and run for 3+ heats
- Auto-research trigger implemented (t-025)

## v0.5+ Outlook
- Telegram/Slack messaging sidecar
- AI Collaborator integration for design debates
- Dolt-backed task tracking (full beads)
- ChromaDB episodic store
- Web dashboard (htmx)
