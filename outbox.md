# Outbox

The Smith writes status updates, questions, and summaries here.

## 2026-04-09 [run complete, 5/5 heats]

### Summary
First run of The Forge, dogfooding on itself. 5 heats across 5 stages:

| Heat | Stage | What |
|-------|-------|------|
| 1 | research | Surveyed autoresearch, Gas Town, NanoClaw, Memory Substrate — 8 patterns, 5 gaps |
| 2 | planning | Created plan.md with prioritized task queue (4 items) |
| 3 | implementation | Added stuck detection, output redirection, keep/discard to loop.md |
| 4 | editing | Added dual-channel inbox convention, backfilled prompt ideas |
| 5 | testing | Protocol consistency check, fixed run continuation + task ID format |

### Wavefront allocator validated
The allocator correctly shifted focus: research → planning → implementation → editing → testing. Only marketing was untouched (correct — it's last in the dependency chain and prerequisites haven't progressed enough). The exploration rule (every 5th heat pick second-best) triggered on heat 5, selecting testing over research.

### Key decisions
- Wavefront model replaced fixed phase buckets (human's idea, implemented pre-run)
- CLAUDE.md kept short (~30 lines), detail in protocol/ files (human's idea)
- All 4 queued tasks completed in the run

### What to do next
- More research depth (research only at 0.2 progress — we surveyed but haven't gone deep)
- Marketing: write a README for the project
- Add more tasks to queue based on what's in plan.md (episodic store is the big v0.6 feature)
- Consider: should the allocator skip completed stages? Currently a stage at progress=1.0 would get benefit=0 naturally.

## 2026-04-09 [run complete, 19/19 heats]

### Summary (heats 10-19)

| Heat | Stage | What |
|------|-------|------|
| 10 | testing | 10 protocol test scenarios (9 pass, 1 untested → now tested) |
| 11 | research | /loop, /schedule, external cron for automation |
| 12 | editing | Vocabulary standardization: chunk → heat globally |
| 13 | research | Integral windup fix — 0.85 decay + ±1.0 clamp |
| 14 | testing | Live keep/discard test — deliberate bad edit, rollback confirmed |
| 15 | marketing | README usage examples added |
| 16 | planning | v0.2 plan: 7 tasks for robustness + multi-project |
| 17 | implementation | Checkpoint file (.forge-checkpoint.json) for crash recovery |
| 18 | editing | State.json pruned — completed tasks and done ideas removed |
| 19 | editing | Final summary, new idea queued (git-backed DAG tasks from beads) |

### Cumulative (19 heats total)
- All 6 stages well-covered (4/2/4/3/4/2 heats)
- 8 human ideas received: 7 done, 1 queued (beads research)
- v0.1 complete, v0.2 underway
- Anti-windup fix made allocator much more balanced

### Queued for next run
1. **t-012**: Research beads for git-backed task DAG (human's latest idea)
2. **t-006**: SessionEnd hook for memory distillation
3. **t-007**: Project template scaffolding script
4. **t-009**: Fresh-session resume test
5. **t-011**: Quick-start guide

## 2026-04-09 [run complete, 9/9 heats]

### Summary (heats 7-9)

| Heat | Stage | What |
|-------|-------|------|
| 7 | research | Deep dive on session cycling — checkpoint files, SessionEnd hooks, three-layer persistence |
| 8 | implementation | ASCII heat dashboard + idea status annotations in inbox.md |
| 9 | marketing | README.md written |

### Cumulative (all 9 heats)

All 6 stages now have at least 1 heat. 6 human ideas received, all implemented. The wavefront allocator was overridden once (heat 9: marketing over research for the README).

### Stage distribution
- research: 2 heats (22%)
- planning: 1 (11%)
- implementation: 3 (33%)
- testing: 1 (11%)
- editing: 1 (11%)
- marketing: 1 (11%)

### What to do next
- **Testing**: only 10% progress, 1 heat. Needs validation that the protocol actually works across fresh sessions.
- **Research on /loop and /schedule**: Claude Code skills that could automate session cycling.
- **Checkpoint files**: write .forge-checkpoint.json before risky work (researched, not yet implemented).
- **Prune completed tasks**: queue has 4 "complete" entries taking up space.
