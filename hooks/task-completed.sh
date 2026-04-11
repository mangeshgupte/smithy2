#!/bin/bash
# TaskCompleted hook — sync Agent Teams task status back to state.json
# Called when any task in the shared list is marked complete

# The hook receives task info via stdin as JSON
# Extract task ID and sync to state.json via smithy CLI
INPUT=$(cat)
TASK_ID=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('taskId',''))" 2>/dev/null)

if [ -n "$TASK_ID" ]; then
    smithy complete-task "$TASK_ID" 2>/dev/null || true
fi

exit 0
