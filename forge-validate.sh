#!/bin/bash
# forge-validate.sh — Automated state/protocol integrity checks for The Forge
# Usage: ./forge-validate.sh [target-dir]
# Returns 0 if all checks pass, 1 if any fail.

set -e

TARGET="${1:-.}"
ERRORS=0

check() {
    local desc="$1"
    local result="$2"
    if [ "$result" = "0" ]; then
        echo "  ✓ $desc"
    else
        echo "  ✗ $desc"
        ERRORS=$((ERRORS + 1))
    fi
}

echo "Validating Forge project: $TARGET"
echo ""

# 1. Required files exist
echo "=== File Structure ==="
for f in CLAUDE.md state.json worklog.tsv identity.md STRATEGY.md inbox.md outbox.md \
         MEMORY_DAILY.md protocol/loop.md protocol/allocator.md protocol/logging.md; do
    if [ -f "$TARGET/$f" ]; then
        check "$f exists" 0
    else
        check "$f exists" 1
    fi
done

# 2. state.json is valid JSON
echo ""
echo "=== State Integrity ==="
if python3 -c "import json; json.load(open('$TARGET/state.json'))" 2>/dev/null; then
    check "state.json is valid JSON" 0
else
    check "state.json is valid JSON" 1
fi

# 3. Progress values in range
python3 -c "
import json, sys
d = json.load(open('$TARGET/state.json'))
ok = True
for name, stage in d['stages'].items():
    if not (0 <= stage['progress'] <= 1):
        print(f'  ✗ {name} progress out of range: {stage[\"progress\"]}')
        ok = False
    if not (0 <= stage['value_ema'] <= 1):
        print(f'  ✗ {name} value_ema out of range: {stage[\"value_ema\"]}')
        ok = False
    if stage['heats'] < 0:
        print(f'  ✗ {name} heats negative')
        ok = False
if ok:
    print('  ✓ All stage values in valid ranges')
sys.exit(0 if ok else 1)
" 2>/dev/null
if [ $? -ne 0 ]; then ERRORS=$((ERRORS + 1)); fi

# 4. Integral values in [-0.5, 0.5]
python3 -c "
import json, sys
d = json.load(open('$TARGET/state.json'))
ok = True
for name, val in d['allocator']['integral'].items():
    if not (-0.5 <= val <= 0.5):
        print(f'  ✗ {name} integral out of range: {val}')
        ok = False
if ok:
    print('  ✓ All integrals in [-0.5, 0.5]')
sys.exit(0 if ok else 1)
" 2>/dev/null
if [ $? -ne 0 ]; then ERRORS=$((ERRORS + 1)); fi

# 5. Unique task IDs
python3 -c "
import json, sys
d = json.load(open('$TARGET/state.json'))
ids = [t['id'] for t in d['queue']]
if len(ids) == len(set(ids)):
    print(f'  ✓ Queue: {len(ids)} tasks, all unique IDs')
else:
    dupes = [x for x in ids if ids.count(x) > 1]
    print(f'  ✗ Duplicate task IDs: {set(dupes)}')
    sys.exit(1)
" 2>/dev/null
if [ $? -ne 0 ]; then ERRORS=$((ERRORS + 1)); fi

# 6. worklog.tsv has valid header
echo ""
echo "=== Worklog ==="
HEADER=$(head -1 "$TARGET/worklog.tsv" 2>/dev/null)
if echo "$HEADER" | grep -q "timestamp"; then
    check "worklog.tsv has valid header" 0
else
    check "worklog.tsv has valid header" 1
fi

# 7. Protocol cross-references
echo ""
echo "=== Protocol Cross-References ==="
if grep -q "protocol/loop.md" "$TARGET/CLAUDE.md" 2>/dev/null; then
    check "CLAUDE.md → protocol/loop.md" 0
else
    check "CLAUDE.md → protocol/loop.md" 1
fi
if grep -q "protocol/allocator.md" "$TARGET/CLAUDE.md" 2>/dev/null; then
    check "CLAUDE.md → protocol/allocator.md" 0
else
    check "CLAUDE.md → protocol/allocator.md" 1
fi
if grep -q "±0.5" "$TARGET/protocol/allocator.md" 2>/dev/null; then
    check "allocator.md uses ±0.5 clamp" 0
else
    check "allocator.md uses ±0.5 clamp (or missing)" 1
fi

# 8. No merge conflicts
echo ""
echo "=== Clean State ==="
if grep -rq "<<<<<<< " "$TARGET"/*.md "$TARGET"/*.json "$TARGET"/*.tsv 2>/dev/null; then
    check "No merge conflicts in state files" 1
else
    check "No merge conflicts in state files" 0
fi

# Summary
echo ""
if [ $ERRORS -eq 0 ]; then
    echo "All checks passed ✓"
    exit 0
else
    echo "$ERRORS check(s) failed ✗"
    exit 1
fi
