# Telegram Bridge for inbox.md/outbox.md

*Heat 55 | 2026-04-09*

## Question

How to bridge The Forge's flat-file communication (inbox.md/outbox.md) with Telegram for async messaging?

## Architecture

```
Human (Telegram app)
  ↕ Telegram Bot API
Sidecar script (Python)
  ↕ File I/O
inbox.md / outbox.md
  ↕ Read by Smith
The Forge
```

The sidecar runs alongside The Forge, polling both Telegram and outbox.md for changes.

## Implementation Design

### Telegram → inbox.md (human sends message)
1. Sidecar polls Telegram via `getUpdates` (long polling, no webhook needed)
2. When a message arrives, append to `inbox.md`:
   ```markdown
   ## YYYY-MM-DD HH:MM [via telegram]
   <message text>
   ```
3. The Smith picks it up at the start of the next heat (normal inbox processing)

### outbox.md → Telegram (Smith sends update)
1. Sidecar watches outbox.md for changes (file mtime or `watchdog` library)
2. When outbox.md changes, read new lines since last cursor
3. Send new content to Telegram chat via `sendMessage`

### Setup
1. Create bot via BotFather → get token
2. Get chat_id (send `/start` to bot, then hit `getUpdates` endpoint)
3. Configure: `forge-telegram.json` with `{"token": "...", "chat_id": "..."}`
4. Run: `python3 forge-telegram.py &` (background sidecar)

### Dependencies
- `python3` + `requests` (stdlib-adjacent, no heavy deps)
- OR: pure bash with `curl` (zero deps, simpler but less robust)

### Bash-only version (minimal)
```bash
#!/bin/bash
# forge-telegram-poll.sh — Minimal Telegram bridge
TOKEN="<bot-token>"
CHAT_ID="<chat-id>"
INBOX="/path/to/inbox.md"
OFFSET=0

while true; do
  # Poll Telegram
  UPDATES=$(curl -s "https://api.telegram.org/bot$TOKEN/getUpdates?offset=$OFFSET&timeout=30")
  
  # Process each message
  echo "$UPDATES" | jq -r '.result[] | .message.text // empty' | while read -r MSG; do
    if [ -n "$MSG" ]; then
      echo "" >> "$INBOX"
      echo "## $(date '+%Y-%m-%d %H:%M') [via telegram]" >> "$INBOX"
      echo "$MSG" >> "$INBOX"
    fi
  done
  
  # Update offset
  NEW_OFFSET=$(echo "$UPDATES" | jq -r '.result[-1].update_id // empty')
  [ -n "$NEW_OFFSET" ] && OFFSET=$((NEW_OFFSET + 1))
done
```

## Constraints
- **No Python requirement** for v0.5: bash + curl + jq is sufficient
- **No webhook needed**: long polling works fine for 1 user
- **No state server**: the sidecar is stateless (offset stored in memory)
- **Security**: token stored in config file, not in CLAUDE.md

## Risks
- Long polling blocks a terminal session → run in background or via tmux
- File write conflicts if sidecar and Smith write inbox.md simultaneously → use `flock`
- Telegram rate limits (30 messages/second) — not a concern for single-user

## Tasks for v0.5

| Stage | Task | Priority |
|-------|------|----------|
| implementation | Create forge-telegram.sh (bash sidecar) | 1 |
| implementation | Add outbox.md watcher (inotifywait or polling) | 2 |
| testing | E2E test: send Telegram message → appears in inbox.md | 1 |
| marketing | Document Telegram setup in README | 2 |
