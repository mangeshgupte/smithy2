#!/bin/bash
# forge-init.sh — Scaffold The Forge in a new project directory
# Usage: ./forge-init.sh <project-name> [target-dir] [--with-personas]

set -e

PROJECT="${1:?Usage: forge-init.sh <project-name> [target-dir] [--with-personas]}"
TARGET="${2:-.}"
WITH_PERSONAS=false
for arg in "$@"; do
    if [ "$arg" = "--with-personas" ]; then
        WITH_PERSONAS=true
    fi
done
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Initializing The Forge for project: $PROJECT"
echo "Target directory: $TARGET"
[ "$WITH_PERSONAS" = true ] && echo "Personas: enabled"

# Create directory structure
mkdir -p "$TARGET/protocol" "$TARGET/research"

# Copy protocol files (the brain)
cp "$SCRIPT_DIR/CLAUDE.md" "$TARGET/CLAUDE.md"
cp "$SCRIPT_DIR/protocol/loop.md" "$TARGET/protocol/loop.md"
cp "$SCRIPT_DIR/protocol/allocator.md" "$TARGET/protocol/allocator.md"
cp "$SCRIPT_DIR/protocol/logging.md" "$TARGET/protocol/logging.md"

# Create project-specific identity
cat > "$TARGET/identity.md" << EOF
# $PROJECT — The Forge

## What This Is

An autonomous AI worker building $PROJECT in bounded 5-minute heats.

## Current Project: $PROJECT

### What needs to exist:
<!-- List concrete deliverables. Be specific — these guide the Smith's task generation. -->
<!-- Examples: -->
<!-- - A REST API with /users, /posts, and /auth endpoints -->
<!-- - Unit tests covering all business logic -->
<!-- - A README with setup instructions and API docs -->

### Constraints:
<!-- List technical, time, or scope limits. These prevent the Smith from going off-track. -->
<!-- Examples: -->
<!-- - Python 3.12+, FastAPI, SQLite for v1 -->
<!-- - No external auth providers — JWT only -->
<!-- - Must run on a single machine (no distributed systems) -->

## Commander's Intent
<!-- The human's strategic intent. The Smith references this for all decisions. -->
<!-- - Intent: <what you're trying to achieve> -->
<!-- - Success looks like: <concrete outcome> -->
<!-- - Tone: <careful/fast, conservative/experimental> -->
<!-- - Boundaries: <what NOT to do> -->
<!-- - References: <projects or patterns to draw from> -->

## Influences
<!-- What existing projects, libraries, or patterns should the Smith draw from? -->

## Created

$(date +%Y-%m-%d)
EOF

# Create initial state
cat > "$TARGET/state.json" << EOF
{
  "project": "$PROJECT",
  "budget": {
    "total_heats": 0,
    "used": 0,
    "started_at": null
  },
  "stages": {
    "research":       {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5},
    "planning":       {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5},
    "implementation": {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5},
    "testing":        {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5},
    "editing":        {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5},
    "marketing":      {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5}
  },
  "allocator": {
    "integral": {"research": 0, "planning": 0, "implementation": 0, "testing": 0, "editing": 0, "marketing": 0}
  },
  "queue": [],
  "ideas": [],
  "feedback_cursor": 0,
  "inbox_cursor": 0,
  "human_priorities": [],
  "overall_progress": 0.0
}
EOF

# Create scaffold files
cat > "$TARGET/inbox.md" << 'EOF'
# Inbox

Write messages below. The Smith reads new lines at the start of each heat.
Format: `## YYYY-MM-DD HH:MM` followed by your message.
EOF

cat > "$TARGET/feedback.md" << 'EOF'
# Feedback

Human writes feedback here. Forge reads it at the start of each run and generates fix tasks.
Format: `## YYYY-MM-DD` followed by freeform feedback on what needs improving.
EOF

cat > "$TARGET/outbox.md" << 'EOF'
# Outbox

The Smith writes status updates, questions, and summaries here.
EOF

echo "# Daily Memory" > "$TARGET/MEMORY_DAILY.md"
echo "# Weekly Memory" > "$TARGET/MEMORY_WEEKLY.md"
echo "# Plan" > "$TARGET/plan.md"
printf "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tnotes\n" > "$TARGET/worklog.tsv"

cat > "$TARGET/STRATEGY.md" << EOF
# Strategic Plan — $PROJECT

*Updated after heat 0 | $(date +%Y-%m-%d)*

## Vision

<!-- One paragraph: what does this project do and who is it for? -->
<!-- Example: "A CLI tool that lets developers run database migrations safely, -->
<!-- with automatic rollback on failure and dry-run previews." -->

## Current State

### What Exists

Nothing yet. This is a fresh scaffold.

### Stage Progress

| Stage | Progress | Heats | Notes |
|-------|----------|-------|-------|
| Research | 0% | 0 | |
| Planning | 0% | 0 | |
| Implementation | 0% | 0 | |
| Testing | 0% | 0 | |
| Editing | 0% | 0 | |
| Marketing | 0% | 0 | |

**Overall progress**: 0% | **Heats used**: 0

### What's Working

(Updated by the Smith after each heat)

### What's Missing

(Updated by the Smith after each heat)

## Main Ideas Being Tried

<!-- The Smith adds entries here as it explores approaches. Each entry tracks: -->
<!-- what the idea is, its status (untested/validated/rejected), and results so far. -->

## Risks & Unknowns

<!-- Known risks and open questions the Smith should investigate. -->

## Roadmap

<!-- Define versions with concrete scope. Example: -->
<!-- | Version | Focus | Key Feature | -->
<!-- |---------|-------|-------------| -->
<!-- | v0.1    | Core  | Basic API with CRUD endpoints | -->
<!-- | v0.2    | Auth  | JWT authentication + middleware | -->
<!-- | v0.3    | Tests | 80% coverage, CI pipeline | -->
EOF

touch "$TARGET/research/.gitkeep"

# Create .gitignore
cat > "$TARGET/.gitignore" << 'EOF'
# Forge transient files
.forge-checkpoint.json
.forge-output.log
EOF

# Optionally scaffold personas
if [ "$WITH_PERSONAS" = true ]; then
    mkdir -p "$TARGET/personas/anvil" "$TARGET/personas/forge" "$TARGET/dispatch"

    cat > "$TARGET/dispatch/anvil-to-forge.md" << 'EOF'
# Dispatch: Anvil → Forge

Anvil writes direction here. Forge reads on startup and uses it to guide autonomous work.
EOF

    cat > "$TARGET/dispatch/forge-to-anvil.md" << 'EOF'
# Dispatch: Forge → Anvil

Forge writes completion reports here. Anvil reads to review work.
EOF

    # Copy persona CLAUDE.md files if they exist in source
    if [ -f "$SCRIPT_DIR/personas/anvil/CLAUDE.md" ]; then
        cp "$SCRIPT_DIR/personas/anvil/CLAUDE.md" "$TARGET/personas/anvil/CLAUDE.md"
    fi
    if [ -f "$SCRIPT_DIR/personas/forge/CLAUDE.md" ]; then
        cp "$SCRIPT_DIR/personas/forge/CLAUDE.md" "$TARGET/personas/forge/CLAUDE.md"
    fi

    echo ""
    echo "Personas scaffolded: Anvil (interface) + Forge (worker)"
    echo "  Start Anvil: cd $TARGET/personas/anvil && claude"
    echo "  Start Forge: cd $TARGET/personas/forge && claude"
fi

echo ""
echo "Done! The Forge is ready."
echo ""
echo "Next steps:"
echo "  1. Edit $TARGET/identity.md with your project details"
echo "  2. Edit $TARGET/STRATEGY.md with your vision and roadmap"
echo "  3. cd $TARGET && git init && git add -A && git commit -m '[init] The Forge scaffold'"
echo "  4. claude"
echo "  5. Run 10 heats."
