# Inbox

Write messages below. The Smith reads new lines at the start of each heat.
Format: `## YYYY-MM-DD HH:MM` followed by your message.

## 2026-04-09 [via prompt]
Idea: The effort allocation should depend on the stage of the project, and which area would give the maximum benefit at this point. Initially lots of research, then shifts to planning, then coding, etc.
→ ✓ done pre-run (wavefront allocator replaced fixed phase buckets)

## 2026-04-09 [via prompt]
Idea: Keep CLAUDE.md human readable and relatively short. Move a lot of the ideas into other files that are invoked via CLAUDE.md.
→ ✓ done pre-run (CLAUDE.md split to 30-line hub + protocol/ directory)

## 2026-04-09 [via prompt]
Idea: Create a strategic plan (STRATEGY.md) that lists the current state of the entire project and main ideas being tried. Updated after each heat.
→ ✓ done between runs (STRATEGY.md created, logging protocol updated to refresh each heat)

## 2026-04-09 [via prompt]
Directive: Run 1 heat focused on Inbox Idea Integration (protocol enhancement) — make the idea pipeline more robust.
→ ✓ done in heat 6 (4-step idea pipeline: capture→evaluate→track→acknowledge)

## 2026-04-09 [via prompt]
Idea: Track progress per heat visually. If too hard, a good textual representation.
→ ✓ done in heat 8 (ASCII dashboard with progress bars printed after each heat)

## 2026-04-09 [via prompt]
Idea: Each idea in inbox.md should have a status — whether considered and implemented (which heat), in queue (where), or not yet considered.
→ ✓ done in heat 8 (inline status annotations in inbox.md, added to logging protocol)

## 2026-04-09 [via prompt]
Idea: Standardize vocabulary to use "heat" everywhere instead of mixing "heat" and "heat". Heat serves as a global timeline for the whole project.
→ ✓ done in heat 12 (global find-and-replace across all protocol files, state.json keys, CLAUDE.md)

## 2026-04-09 [via prompt]
Idea: Task tracking should be backed by git and dependencies stored as a DAG. Research how it's done in beads for tracking tasks and dependencies.
→ ✓ done in heat 20 (beads DAG research + implemented blocked_by deps)

## 2026-04-09 [via prompt]
Idea: Multiple personas as separate Claude Code sessions. Comms (read-only explainer), Chief of Staff (coordinator/brainstormer, farms out work), Implementor (pure polecat, runs heats).
→ ✓ done in heats 36-38 (persona system designed and implemented)

## 2026-04-09 [via prompt]
Idea: Add a Planner persona between Anvil and Hammer. Anvil brainstorms, Planner turns it into a concrete plan, Hammer executes.
→ ✓ done in heat 39 (Blueprint persona created with dispatch files)

## 2026-04-09 [via prompt]
Idea: Auto-replenish research — when Forge is running low on good ideas or the task queue is thin, automatically trigger 10 research heats to survey the landscape and generate fresh direction.
→ ✓ done in heat 66 (auto-task generation added to loop.md Step 4: queue health check + per-stage heuristic)

## 2026-04-09 [via prompt]
Directive: No Telegram bridge. When messaging is needed, build a WhatsApp bridge instead. Defer messaging work until the time is right — don't build it yet.
→ ✓ acknowledged in heat 69 (Telegram tasks removed from v0.5, messaging deferred to v0.6+)

## 2026-04-09 [via prompt]
Idea: The human-AI interface is the bottleneck. Can't assess quality of changes. Need higher-level structure for ideas being tried. Research how different domains solve the oversight problem — companies, research orgs, universities, animal colonies, organizational research. Generate diverse interface models, then converge on top candidates.
→ ✓ research complete in heats 69-79 (synthesis in research/human-ai-interface-synthesis.md)

## 2026-04-09 [via prompt]
Directive: Operationalize the interface synthesis. Implement all 5 models: stoplight + uncertainty → commander's intent → AAR → compression layers.
→ partially done in heats 85-88 (stoplight, intent, AAR protocol). Remaining: forge-status, reporting.md, AAR to file.

## 2026-04-09 [via prompt]
Idea: Build a real project — an AI tutor that helps people learn. Focus on kids or adult university-level learning. First non-dogfood test of the Forge. Tests H5-H10 simultaneously.
→ dispatched (15 heats, see anvil-to-forge.md)

## 2026-04-09 [via Chisel]
Design: Commissioner App — mobile-first operational app for managing multiple Forge projects. 6 screens, lifecycle-adaptive cards, decision triage, morning briefing, voice-first. Full spec in design/2026-04-09-commissioner-app-design.md.
→ dispatched to Forge (15 heats, see anvil-to-forge.md)


## 2026-04-09 22:59 [via commissioner]
Test from commissioner
→ ✓ test message — Commissioner Direct tab POST works end-to-end

## 2026-04-10 [via prompt]
Idea: Build iteration tooling in 3 stages. Stage 1: feedback.md + review-first-heat in protocol (ai-coworker). Stage 2: feedback UI in Commissioner Direct tab. Stage 3: multi-project Forge (deferred). Makes iteration on tutor/commissioner/ai-coworker frictionless.
→ ✓ Stage 1 complete in heats 166-170. Stage 2 done in heats 172-173.

## 2026-04-10 [via prompt]
Idea: Tutor should be generic multi-subject. Add Grade 3 Singapore Math alongside Python. Serve as website, not CLI. Research 5 heats, then build autonomously for 500 heats total.
→ dispatched (500 heats on tutor project, see anvil-to-forge.md)


## 2026-04-10 09:35 [via commissioner]
Decision on t-044: APPROVE — looks good (task: Repo map generation for non-dogfood projects)


## 2026-04-10 09:35 [via commissioner]
Decision on t-046: REJECT (task: Self-critique (Reflexion-style) per heat)


## 2026-04-10 09:35 [via commissioner]
UNDO: Previous decision on t-046 was reversed.
