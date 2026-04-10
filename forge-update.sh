#!/bin/bash
# forge-update.sh — Update protocol files in an existing Forge project
# Usage: ./forge-update.sh <target-dir>
#
# Copies the latest protocol files from the source (where this script lives)
# into an existing Forge project. State files are preserved.

set -e

TARGET="${1:?Usage: forge-update.sh <target-dir>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Verify target is a Forge project
if [ ! -f "$TARGET/CLAUDE.md" ] || [ ! -f "$TARGET/state.json" ]; then
    echo "Error: $TARGET doesn't look like a Forge project (missing CLAUDE.md or state.json)"
    exit 1
fi

echo "Updating protocol files in: $TARGET"
echo "Source: $SCRIPT_DIR"
echo ""

# Files to update (protocol only — never touch state)
PROTOCOL_FILES=(
    "CLAUDE.md"
    "protocol/loop.md"
    "protocol/allocator.md"
    "protocol/logging.md"
)

# Copy each file, showing what changed
for file in "${PROTOCOL_FILES[@]}"; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        if [ -f "$TARGET/$file" ]; then
            if diff -q "$SCRIPT_DIR/$file" "$TARGET/$file" > /dev/null 2>&1; then
                echo "  unchanged: $file"
            else
                cp "$SCRIPT_DIR/$file" "$TARGET/$file"
                echo "  updated:   $file"
            fi
        else
            mkdir -p "$(dirname "$TARGET/$file")"
            cp "$SCRIPT_DIR/$file" "$TARGET/$file"
            echo "  added:     $file"
        fi
    else
        echo "  missing:   $file (not in source)"
    fi
done

# Update .gitignore if it exists in source but not target
if [ -f "$SCRIPT_DIR/.gitignore" ] && [ ! -f "$TARGET/.gitignore" ]; then
    cp "$SCRIPT_DIR/.gitignore" "$TARGET/.gitignore"
    echo "  added:     .gitignore"
fi

echo ""
echo "Done. State files (state.json, worklog.tsv, memory, etc.) were NOT modified."
echo "Run 'git diff' in $TARGET to see what changed."
