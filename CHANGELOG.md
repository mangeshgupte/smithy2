# Changelog

## v0.5.1 — Interface Operationalization (heats 100-115)

### New Tools
- `forge-status.sh` — zero-effort L2 dashboard (budget, stages, signals, alerts, commits, what's missing)

### Protocol Additions
- `protocol/reporting.md` — L0-L4 information compression layers
- AAR now writes to `aar/` directory (not just outbox)
- `CLAUDE.md` references reporting.md

### v0.6 Planning
- v0.6 plan with 6 tasks: real-project run, repo map, lint→test→fix, self-critique, WhatsApp research, event-sourced state design

### Documentation
- README: forge-status, forge-validate in check-status section
- README: --with-personas example in quick-start
- CHANGELOG: updated through heat 115

---

## v0.5 — Polish + Real-World Validation (heats 39-99)

### Interface Improvements
- **Stoplight signals** (🟢/🟡/🔴) per heat — human reads only yellows/reds
- **Uncertainty field** in worklog — Forge flags uncertain decisions
- **Self-critique** in worklog notes — "Could improve: ..." after each heat
- **Commander's intent** in identity.md — strategic direction for all decisions
- **After-action review (AAR)** generated at end of each run

### Allocator Fixes
- **Soft clamp ±0.5** (was ±1.0) — prevents integral recovery traps
- **Unblocking override** — +0.3 boost for tasks that unblock 2+ others
- **Queued task bonus** — +0.07/ready task prevents dead tasks in low-scoring stages
- **Auto-task generation** — queue replenishes when ≤3 pending tasks

### New Tools
- `forge-update.sh` — update protocol files in existing projects
- `forge-validate.sh` — automated state/protocol integrity checks (19 checks)

### Scaffold Improvements
- `.gitignore` in forge-init.sh scaffold
- Guided templates with HTML comments for identity.md and STRATEGY.md
- Commander's intent template in identity.md

### Documentation
- FAQ/Troubleshooting section in README
- SessionEnd hook setup guide
- Example dashboard output
- Updated file structure diagram with personas, dispatch, hooks

### Research
- Human-AI interface: 10 domains, 22 ideas, top 5 synthesized
- AI worker landscape: Devin, OpenHands, CrewAI, Aider + synthesis
- Adaptive queue management, dead task problem, Telegram bridge design

---

## v0.4 — Real-Project Readiness (heats 39-68)
- Non-dogfood project scaffold tested (todo-cli)
- forge-update.sh for protocol updates
- 8 automated data integrity checks
- v0.4 status reporting to outbox.md

## v0.3 — Personas + Production (heats 26-38)
- 2-persona system: Anvil (interface) + Forge (worker)
- Dispatch files for inter-persona communication
- Value measurement research
- Wavefront visualization in STRATEGY.md

## v0.2 — Robustness + Scaffolding (heats 6-25)
- Beads DAG research → blocked_by task dependencies
- forge-init.sh project scaffolding
- SessionEnd hook for memory distillation
- Checkpoint file for crash recovery
- Fresh-session resume tested (28KB cold start)
- Anti-windup fix for PI controller (0.85 decay)

## v0.1 — Core Protocol (heats 1-5)
- 8-step heat loop
- Wavefront allocator with PI controller
- Flat-file state management (state.json, worklog.tsv)
- Inbox/outbox async communication
- 4-level memory hierarchy
- Git as the substrate
