#!/usr/bin/env bash
# SessionEnd hook: distill Forge session into memory
# Adapted from agents/hooks/session-end-memory.sh

set -euo pipefail

FORGE_DIR="/Users/mangesh/vibes/ai-coworker"

# Read hook input from stdin
INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Only run if session was in the Forge directory
if [ -z "$CWD" ]; then exit 0; fi
CWD_RESOLVED=$(cd "$CWD" 2>/dev/null && pwd) || exit 0
FORGE_RESOLVED=$(cd "$FORGE_DIR" && pwd)
if [[ "$CWD_RESOLVED" != "$FORGE_RESOLVED"* ]]; then exit 0; fi

DAILY_FILE="$FORGE_DIR/MEMORY_DAILY.md"
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then exit 0; fi

# Extract last 200 lines of human/assistant messages
TRANSCRIPT_SUMMARY=$(tail -200 "$TRANSCRIPT_PATH" | jq -r '
  select(.type == "human" or .type == "assistant") |
  if .type == "human" then "USER: " + (.message.content // "" | if type == "array" then map(select(.type == "text") | .text) | join(" ") else . end)
  elif .type == "assistant" then "ASSISTANT: " + (.message.content // "" | if type == "array" then map(select(.type == "text") | .text) | join(" ") else . end)
  else empty end
' 2>/dev/null | head -300)

if [ -z "$TRANSCRIPT_SUMMARY" ]; then exit 0; fi

TODAY=$(date +%Y-%m-%d)
CURRENT_DAILY=$(cat "$DAILY_FILE" 2>/dev/null || echo "# Daily Memory")

# Distill into MEMORY_DAILY.md via Claude
claude -p --max-turns 4 --allowedTools "Read,Write" \
  "You are The Smith's memory system. Distill this session transcript into MEMORY_DAILY.md.

Session transcript (last 200 lines):
---
$TRANSCRIPT_SUMMARY
---

Current MEMORY_DAILY.md:
---
$CURRENT_DAILY
---

Write the updated file to: $DAILY_FILE

Rules:
- Append under today's heading (## $TODAY)
- Concise bullet points: decisions, progress, blockers, ideas received
- Group by heat number if visible in transcript
- Skip: routine protocol steps, file reads, things already in worklog.tsv
- Keep total file under 3000 chars (prune old entries if needed)" 2>/dev/null || true

echo "Forge memory distilled for session ending $(date)" >&2
