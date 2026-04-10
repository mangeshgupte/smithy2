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
