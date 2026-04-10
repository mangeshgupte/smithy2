#!/bin/bash
# forge-status — Zero-effort dashboard for The Forge
# Usage: ./forge-status.sh [target-dir]
# Reads state.json, worklog.tsv, git log to generate an at-a-glance status report.

TARGET="${1:-.}"

if [ ! -f "$TARGET/state.json" ]; then
    echo "Error: $TARGET doesn't look like a Forge project"
    exit 1
fi

echo "═══════════════════════════════════════════════"
echo "  The Forge — Status Dashboard"
echo "═══════════════════════════════════════════════"
echo ""

# Budget & Progress
python3 -c "
import json
d = json.load(open('$TARGET/state.json'))
b = d['budget']
print(f'Budget: {b[\"used\"]}/{b[\"total_heats\"]} heats ({b[\"used\"]*100//max(b[\"total_heats\"],1)}% used)')
print(f'Overall progress: {d[\"overall_progress\"]*100:.0f}%')
print()

# Stage progress bars
print('Stage          Progress     Heats  Target')
for name in ['research','planning','implementation','testing','editing','marketing']:
    s = d['stages'][name]
    filled = int(s['progress'] * 10)
    bar = '█' * filled + '░' * (10 - filled)
    print(f'{name:15s}{bar}  {s[\"progress\"]*100:4.0f}%  {s[\"heats\"]:3d}    .{s[\"target\"]*100:02.0f}')
"

echo ""

# Recent signals (last 10 heats)
echo "── Recent Heats ────────────────────────────"
if [ -f "$TARGET/worklog.tsv" ]; then
    # Check if signal column exists (column 7 in new format)
    HEADER=$(head -1 "$TARGET/worklog.tsv")
    if echo "$HEADER" | grep -q "signal"; then
        tail -10 "$TARGET/worklog.tsv" | while IFS=$'\t' read -r ts heat stage tid outcome val signal notes; do
            [ "$heat" = "heat" ] && continue  # skip header
            printf "  %s Heat %s [%s] %s\n" "${signal:-🟢}" "$heat" "$stage" "$(echo "$notes" | head -c 60)"
        done
    else
        tail -10 "$TARGET/worklog.tsv" | while IFS=$'\t' read -r ts heat stage tid outcome val notes; do
            [ "$heat" = "heat" ] && continue
            printf "  🟢 Heat %s [%s] %s\n" "$heat" "$stage" "$(echo "$notes" | head -c 60)"
        done
    fi
fi

echo ""

# Alerts
echo "── Alerts ──────────────────────────────────"
python3 -c "
import json
d = json.load(open('$TARGET/state.json'))
alerts = []

# Stalled stages (progress unchanged in many heats)
for name, s in d['stages'].items():
    if s['heats'] > 0 and s['progress'] < 0.3:
        alerts.append(f'🟡 {name} low progress ({s[\"progress\"]*100:.0f}%) after {s[\"heats\"]} heats')

# Blocked tasks
for t in d['queue']:
    if t['status'] == 'pending' and t.get('blocked_by'):
        blockers = [b for b in t['blocked_by'] if any(q['id']==b and q['status']!='complete' for q in d['queue'])]
        if blockers:
            alerts.append(f'🟡 {t[\"id\"]} blocked by {blockers}')

# Integral extremes
for name, val in d['allocator']['integral'].items():
    if abs(val) >= 0.45:
        alerts.append(f'🟡 {name} integral near clamp ({val:.2f})')

# Queue depth
pending = [t for t in d['queue'] if t['status'] == 'pending']
if len(pending) <= 1:
    alerts.append(f'🟡 Queue low: only {len(pending)} pending task(s)')

if not alerts:
    print('  🟢 No alerts — everything nominal')
else:
    for a in alerts:
        print(f'  {a}')
" 2>/dev/null

echo ""

# Top 3 recent commits
echo "── Recent Commits ──────────────────────────"
cd "$TARGET" && git log --oneline -3 2>/dev/null | while read -r line; do
    echo "  $line"
done

echo ""

# What's Missing (from STRATEGY.md)
if grep -q "What's Missing" "$TARGET/STRATEGY.md" 2>/dev/null; then
    echo "── What's Missing ──────────────────────────"
    sed -n "/What's Missing/,/^##/p" "$TARGET/STRATEGY.md" | grep "^-" | head -5 | while read -r line; do
        echo "  $line"
    done
    echo ""
fi

echo "═══════════════════════════════════════════════"
