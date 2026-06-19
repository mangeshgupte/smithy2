#!/bin/bash
# TeammateIdle hook — called when a teammate (Forge) goes idle
# Exit 0: allow idle (no more work)
# Exit 2 + feedback on stdout: keep teammate working

# Check if there are pending tasks in state.json
PENDING=$(python3 -c "
import json, sys
with open('state.json') as f:
    state = json.load(f)
tasks = state.get('queue', [])
pending = [t for t in tasks if t.get('status') == 'pending']
print(len(pending))
" 2>/dev/null)

if [ "$PENDING" -gt 0 ] 2>/dev/null; then
    echo "There are $PENDING pending tasks. Check the shared task list for your next assignment."
    exit 2
fi

# No pending tasks — allow idle
exit 0
