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

### Heats 39+: Production Hardening
- Heat 39 [testing]: Persona system verification — found 2 stale references from Lens→Anvil consolidation, all paths valid
- Heat 40 [research]: Real-project readiness assessment — forge-init.sh missing .gitignore, SessionEnd hook, better templates. 4 tasks queued.
- Heat 41 [editing]: Improved scaffold templates — identity.md and STRATEGY.md now have guided HTML comments with examples
- Heat 42 [marketing]: Documented SessionEnd hook setup in README — config example, what it does, prerequisites
- Heat 43 [testing]: E2E test forge-init.sh with new templates — all 14 files present, JSON valid, comments rendered, substitution works
- Heat 44 [planning]: v0.4 plan — multi-project isolation via full copy (not symlink), forge-update.sh for protocol migration, 6 tasks queued
- Heat 45 [marketing]: Example dashboard output in README — shows what The Forge looks like to a new user

### Key Patterns
- Human ideas implemented quickly (8/8 done)
- Anti-windup decay makes allocator balanced
- Context growing — recommend session cycling after ~30 heats
