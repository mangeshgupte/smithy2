#!/bin/bash
# forge-init.sh — Scaffold The Forge in a new project directory
# Usage: ./forge-init.sh <project-name> [target-dir]

set -e

PROJECT="${1:?Usage: forge-init.sh <project-name> [target-dir]}"
TARGET="${2:-.}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Initializing The Forge for project: $PROJECT"
echo "Target directory: $TARGET"

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
(Describe your project goals here)

### Constraints:
(List your constraints here)

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

(Describe your project vision)

## Current State

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

## Main Ideas Being Tried

(Will be populated as work begins)

## Roadmap

(Define your versions and milestones)
EOF

touch "$TARGET/research/.gitkeep"

echo ""
echo "Done! The Forge is ready."
echo ""
echo "Next steps:"
echo "  1. Edit $TARGET/identity.md with your project details"
echo "  2. Edit $TARGET/STRATEGY.md with your vision and roadmap"
echo "  3. cd $TARGET && git init && git add -A && git commit -m '[init] The Forge scaffold'"
echo "  4. claude"
echo "  5. Run 10 heats."
