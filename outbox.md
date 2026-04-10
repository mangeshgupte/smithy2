# Outbox

The Smith writes status updates, questions, and summaries here.

## 2026-04-09 [run complete, 5/5 chunks]

### Summary
First run of The Forge, dogfooding on itself. 5 chunks across 5 stages:

| Chunk | Stage | What |
|-------|-------|------|
| 1 | research | Surveyed autoresearch, Gas Town, NanoClaw, Memory Substrate — 8 patterns, 5 gaps |
| 2 | planning | Created plan.md with prioritized task queue (4 items) |
| 3 | implementation | Added stuck detection, output redirection, keep/discard to loop.md |
| 4 | editing | Added dual-channel inbox convention, backfilled prompt ideas |
| 5 | testing | Protocol consistency check, fixed run continuation + task ID format |

### Wavefront allocator validated
The allocator correctly shifted focus: research → planning → implementation → editing → testing. Only marketing was untouched (correct — it's last in the dependency chain and prerequisites haven't progressed enough). The exploration rule (every 5th chunk pick second-best) triggered on chunk 5, selecting testing over research.

### Key decisions
- Wavefront model replaced fixed phase buckets (human's idea, implemented pre-run)
- CLAUDE.md kept short (~30 lines), detail in protocol/ files (human's idea)
- All 4 queued tasks completed in the run

### What to do next
- More research depth (research only at 0.2 progress — we surveyed but haven't gone deep)
- Marketing: write a README for the project
- Add more tasks to queue based on what's in plan.md (episodic store is the big v0.6 feature)
- Consider: should the allocator skip completed stages? Currently a stage at progress=1.0 would get benefit=0 naturally.

## 2026-04-09 [run complete, 9/9 chunks]

### Summary (chunks 7-9)

| Chunk | Stage | What |
|-------|-------|------|
| 7 | research | Deep dive on session cycling — checkpoint files, SessionEnd hooks, three-layer persistence |
| 8 | implementation | ASCII heat dashboard + idea status annotations in inbox.md |
| 9 | marketing | README.md written |

### Cumulative (all 9 chunks)

All 6 stages now have at least 1 chunk. 6 human ideas received, all implemented. The wavefront allocator was overridden once (chunk 9: marketing over research for the README).

### Stage distribution
- research: 2 chunks (22%)
- planning: 1 (11%)
- implementation: 3 (33%)
- testing: 1 (11%)
- editing: 1 (11%)
- marketing: 1 (11%)

### What to do next
- **Testing**: only 10% progress, 1 chunk. Needs validation that the protocol actually works across fresh sessions.
- **Research on /loop and /schedule**: Claude Code skills that could automate session cycling.
- **Checkpoint files**: write .forge-checkpoint.json before risky work (researched, not yet implemented).
- **Prune completed tasks**: queue has 4 "complete" entries taking up space.
