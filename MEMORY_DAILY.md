# Daily Memory

## 2026-04-09

### Heats 1-5: Bootstrap
- Surveyed 4 reference projects, built protocol, wavefront allocator validated
- 5 gaps identified and 3 fixed (stuck detection, output redirect, keep/discard)

### Heats 6-25: Feature Build → v0.2 Complete
- Idea pipeline, dashboard, vocabulary fix, anti-windup, README
- Beads DAG research → blocked_by dependencies implemented
- forge-init.sh, SessionEnd hook, checkpoint file, fresh-session resume (28KB)
- All v0.2 tasks complete

### Heats 26-38: v0.3 — Personas + Production
- Value measurement research, deep-dive doc, wavefront visualization
- Persona system: designed → built → consolidated to 2 (Anvil + Forge)
- v0.3 plan complete, dispatch system wired

### Heats 39-47: v0.4 — Real-Project Readiness
- Persona verification: 2 stale refs fixed, all paths valid (h39)
- Real-project readiness: 5 gaps in forge-init.sh identified (h40)
- Templates improved with guided comments (h41), E2E tested (h43)
- SessionEnd hook documented in README (h42), dashboard example added (h45)
- v0.4 plan: multi-project isolation (copy not symlink), 6 tasks queued (h44)
- STRATEGY.md full refresh (h46)
- Adaptive queue management research: per-stage heuristic, anti-spiral guard (h47)

### Heat 48 [planning]: t-028 complete — auto-task generation design in plan.md. Memory consolidated.
### Heat 49 [testing]: Data integrity — 8 automated checks all pass. Stage heats off by 1 (timing), all else exact.
### Heat 50 [testing]: Simulated auto-task heuristic — all 6 stages produce reasonable tasks. Fixed trigger: `<3` → `<=3`. Noted: implementation integral (-1.0) blocking t-021 which blocks 2 tasks.
### Heat 51 [planning]: **Critical fix** — integral recovery trap. Softened clamp ±1.0→±0.5, added unblocking override (+0.3 for tasks that unblock 2+). Implementation integral reset to -0.5.
### Heat 52 [implementation]: t-021 done — .gitignore in scaffold + dogfood. **Unblocking override worked!** First impl heat since h38 (14 heats ago).

### Key Patterns
- 10/10 human ideas processed and implemented
- Anti-windup decay (0.85) keeps allocator balanced across 47 heats
- Implementation integral deeply negative (-1.0) from early over-allocation, recovering slowly
- Exploration rule (every 5th heat) prevents allocator stagnation
- Session context growing but manageable — session cycling validated at 28KB cold start
