# End-to-End Gaps — smithy init → run heats

## Gap 1: Protocol files not copied during init

`smithy init` creates empty `protocol/` directory but doesn't copy:
- `protocol/loop.md` — the heat loop (critical)
- `protocol/allocator.md` — how to pick stages
- `protocol/logging.md` — how to log heats
- `protocol/reporting.md` — AAR format
- `CLAUDE.md` — the protocol hub

**Fix**: `smithy init` should automatically run `smithy update <target>` after scaffolding, or copy protocol files directly.

**Workaround**: Run `smithy update <project-dir>` after init.

## Gap 2: No CLAUDE.md generated

The CLAUDE.md file that drives Forge is not scaffolded. Without it, Claude Code won't know to follow the Smith protocol.

**Fix**: Generate a CLAUDE.md during init that points to the protocol files.

## Gap 3: identity.md is mostly empty

The scaffolded identity.md has placeholder content but no Commander's Intent section. The human needs to fill this in before running heats, which isn't documented.

**Fix**: Add a Commander's Intent template with placeholders.

## Gap 4: No guidance on first run

After `smithy init`, there's no instruction telling the user what to do next (edit identity.md, set budget, run heats).

**Fix**: Print a "Next steps" message after init.

## Summary

The init → run path needs: protocol file copying, CLAUDE.md generation, better identity.md template, and post-init instructions. About 2-3 heats of work.
