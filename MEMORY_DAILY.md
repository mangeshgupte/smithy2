# Daily Memory

## 2026-04-09

### Heats 1-5: Bootstrap
- Surveyed 4 reference projects, built protocol, wavefront allocator validated
- 5 gaps identified and 3 fixed (stuck detection, output redirect, keep/discard)

### Heats 6-12: Feature Build + Hardening
- Idea pipeline, heat dashboard, vocabulary standardization (chunk→heat)
- Anti-windup fix for PI controller (0.85 decay + ±1.0 clamp)
- README shipped, all 6 stages covered

### Heats 13-19: v0.2 Kickoff
- Integral windup fixed, keep/discard live tested, v0.2 planned with 7 tasks
- Checkpoint file implemented, state pruned

### Heats 20-25: v0.2 Complete
- Beads research: git-backed task DAG with blocked_by dependencies
- Implemented DAG dependencies (blocked_by array + ready detection in loop)
- forge-init.sh: scaffold Forge in any directory
- SessionEnd hook for automatic memory distillation
- Fresh-session resume tested (28KB cold start)
- Quick-start guide in README
- **All v0.2 tasks complete. Queue empty.**

### Key Patterns
- Human ideas implemented quickly (8/8 done)
- Anti-windup decay makes allocator balanced
- Context growing — recommend session cycling after ~30 heats
