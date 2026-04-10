# Dispatch: Forge → Anvil

## 2026-04-10 00:30 — Direction Complete: Iteration Tooling Stage 1

### What Was Done
Built the feedback protocol — the infrastructure for iterating on Forge projects.

| Heat | Stage | What |
|------|-------|------|
| 166 | impl | feedback.md template + forge-init.sh scaffold + CLAUDE.md reference |
| 167 | impl | review-first-heat in loop.md — feedback drives first heat of every run |
| 168 | test | 6/6 validation tests pass (exists, content, loop ref, context, CLAUDE, scaffold) |
| 169 | edit | README updated with feedback docs |
| 170 | mktg | Backfilled feedback.md for tutor + commissioner with human's real feedback |

### How It Works
1. Human writes feedback to `feedback.md` (freeform, dated entries)
2. On the first heat of the next run, Forge reads feedback → examines code → generates fix tasks
3. Fix tasks go into the queue, get picked by the allocator in subsequent heats
4. Human's feedback is annotated with "reviewed in heat N" for traceability

### Artifacts
- `feedback.md` — new file in protocol
- `protocol/loop.md` — review-first-heat logic added
- `CLAUDE.md` — references feedback.md
- `forge-init.sh` — scaffolds feedback.md for new projects
- `~/vibes/tutor/feedback.md` — backfilled with tutor feedback
- `commissioner/feedback.md` — backfilled with commissioner feedback

### Ready for Stage 2
Stage 2 (Commissioner Feedback UI) can begin — add feedback input to the Direct tab so the human can write feedback from the browser instead of editing files.
