# The Smithy — Autonomous AI Worker

## What This Is

An autonomous AI worker that operates in bounded 5-minute heats ("heats"). Given a budget and a project, it self-directs work across six stages: research, planning, implementation, testing, editing, and marketing. A human uses Bellows (the dashboard) to review decisions and drop ideas asynchronously; the Smith picks them up in the next heat.

**Agent roster:** **Anvil** (human interface / steering), **Marshal** (allocator), **Forge** (executor — one or more, named by verb: quench/temper/anneal), **Assembly** (sole integrator to `main`), and **Comms** (read-only, cron-woken status narrator). See the roster table in `README.md` for where each lives.

## Current Project: Building Itself (Dogfooding)

The first project is The Smithy system itself. The Smith builds, tests, and refines the very infrastructure it runs on.

### What needs to exist:
- A CLAUDE.md protocol that drives autonomous heat-based work
- A PI controller that allocates effort across stages
- Flat-file state management (state.json, worklog.tsv)
- Inbox/outbox for async human-AI communication
- 4-level memory hierarchy (worklog → daily → weekly → identity)
- Git as the substrate — every heat's work is committed

## Commander's Intent

The human's strategic intent. Reference this when generating tasks or making decisions.

- **Intent** (project-level, canonical — t-384): Create an AI collaborator who can run autonomously, while also being responsive to human steers, and can carry out the high-level intents that the human expresses and wants.
- **Legacy framing**: Build a reliable, transparent, self-directing AI coworker system
- **Success looks like**: Someone can forge-init a new project, run 20 heats, and get useful output without babysitting
- **Tone**: Careful, well-tested, documented. Quality over speed.
- **Boundaries**: No external dependencies (no Python wrappers, no databases). Flat files only. No messaging integration yet.
- **Not this**: Don't over-engineer. Don't add features nobody asked for. Don't build a web UI yet.
- **References**: Autoresearch simplicity, Make-like directness, Taskwarrior CLI UX

## Constraints

- Runs entirely inside Claude Code (no external orchestrator, no Python wrapper)
- Flat files over databases for v0.1
- Must be transparent — all state inspectable via cat/vim
- Git-tracked — the record is sacred
- Budget-bounded — never exceed allocated heats

## Influences

- **Autoresearch**: 5-minute bounded loops, "NEVER STOP", modify-commit-run-log-iterate
- **Gas Town**: GUPP ("if work is hooked to you, YOU RUN IT"), three-layer model (identity/sandbox/session)
- **NanoClaw**: Messaging patterns, per-group isolation (future)
- **AI Collaborator**: Git-native structured disagreement (future)
- **Memory Substrate**: Token-budgeted context assembly, episodic store (future)

## Initiative Lifecycle

Work is organized into **initiatives** (`ini-XXX`) — bounded bodies of
related tasks with a shared goal. An initiative moves through a lifecycle,
and closing one is a first-class step that captures what was learned, not
just a status flip (ini-025).

**States:** `proposed` → `approved`/`active` → `complete` (or `rejected`).
Proposing and approving are human territory; Anvil and the rig execute
within an approved initiative.

**Closure flow (end-to-end):**

1. **Decide to close.** The human signals an initiative is done. Anvil
   verifies every task under it is `complete` — no open
   `pending`/`in_progress`/`submitted` rows. Open work is flipped
   explicitly or the closure waits.
2. **Anvil drafts the retro prose.** Anvil reads the record (worklog
   filtered to the ini's task ids, git log of merged shas, memories
   tagged with ini context, `plans/` docs referencing it) and produces
   `plans/retro/ini-XXX-retro.md` from `plans/retro/TEMPLATE-initiative-retro.md`,
   filling the prose sections and leaving data sections marked for a
   Forge. The drafting steps are in `personas/anvil/CLAUDE.md`
   §"Closing Initiatives".
3. **Forge fills the data.** Anvil files an `editing` task; a Forge runs
   the state/worklog/git queries and fills the "What shipped" bullets and
   the metrics appendix, then submits.
4. **Assembly merges** the retro into main via the standard gate.
5. **Human reviews + closes.** The retro renders on the Bellows
   initiative detail page. The human edits prose if needed (directly on
   main — retros are human territory, no gate) and runs
   `smithy complete-initiative <id> --retro plans/retro/ini-XXX-retro.md
   [--successor <ini-id>]`. The CLI validates the path and writes the
   state.json closure fields (`retro_path`, `closed_at`,
   `heat_cost_total`, `successor_ini`). `--force-no-retro` is the
   escape hatch for edge cases.

**Succession is binary + optional pointer.** An initiative is `complete`
with an optional `successor_ini` when there's a direct continuation
(e.g. ini-018 → ini-024). There is no `maintenance` status — later
maintenance work files as a new initiative when substantial, or as a
`theme-XXX` task without initiative attribution when small. A new
initiative may start while a prior one's retro is still in flight;
closure never gates new work.

Design contract: `plans/initiative-retros-design.md`. Template:
`plans/retro/TEMPLATE-initiative-retro.md`.

## Created

2026-04-09
