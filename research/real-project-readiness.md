# Real-Project Readiness Assessment

*Heat 40 | 2026-04-09*

## Question

What needs to change for The Forge to work on a non-dogfood project?

## Method

Ran `forge-init.sh` on a test directory, inspected output against what the dogfood project actually uses, and identified gaps.

## Findings

### What forge-init.sh Gets Right
- All protocol files (loop.md, allocator.md, logging.md) copied correctly
- state.json initialized with proper schema
- Scaffold files (inbox, outbox, memory, plan, worklog) all created
- identity.md and STRATEGY.md templates provided
- research/ directory created
- Instructions printed for next steps

### Gap 1: Missing .gitignore
**Impact**: Medium
Temporary files will be committed:
- `.forge-checkpoint.json` (crash recovery, should be transient)
- `.forge-output.log` (bash output redirect, should be transient)

**Fix**: Add a `.gitignore` to the scaffold.

### Gap 2: No SessionEnd Hook
**Impact**: Medium
The dogfood project has `hooks/session-end-forge.sh` wired in `.claude/settings.json` for automatic memory distillation. New projects get nothing.

**Fix**: Include the hook script and document how to wire it in settings.json. Don't auto-create `.claude/settings.json` (user may have their own config).

### Gap 3: Sparse Templates
**Impact**: Low
`identity.md` has placeholder text ("Describe your project goals here"). A new user won't know what to write.

**Fix**: Add better examples showing what good identity/strategy files look like. Reference the dogfood project's files as examples.

### Gap 4: No Personas in Scaffold
**Impact**: Low (personas are optional)
The persona system (Anvil + Forge) with dispatch files is a power feature. Not needed for basic usage, but there's no way to opt-in during scaffold.

**Fix**: Add `--with-personas` flag to forge-init.sh that creates the dispatch/ and personas/ directories.

### Gap 5: No CLAUDE.md Instructions for Context
**Impact**: High
The scaffolded CLAUDE.md tells the Smith to "Read identity.md" but a new project's identity.md has no real content. The first few heats will be unguided.

**Fix**: forge-init.sh should prompt for or accept a project description that gets embedded in identity.md and STRATEGY.md.

## Priority Order

1. **.gitignore** — easy fix, prevents noise in git history
2. **Better templates** — identity.md needs real scaffolding questions
3. **SessionEnd hook** — document how to wire it up
4. **Project description on init** — make first-run useful
5. **Personas flag** — nice-to-have for power users

## Tasks Generated

| Stage | Task | Priority |
|-------|------|----------|
| implementation | Add .gitignore to forge-init.sh scaffold | 1 |
| editing | Improve identity.md and STRATEGY.md templates with guided questions | 2 |
| implementation | Add --with-personas flag to forge-init.sh | 3 |
| marketing | Document SessionEnd hook setup in README | 2 |
