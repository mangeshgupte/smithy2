# ini-021 R2 — `/clear` mechanism survey

**Task:** t-452 · heat 981 · 2026-04-18 · forge-anneal

Authoritative survey of the Claude Code hook surface for triggering
`/clear` after each clean Forge end-heat. Covers hook semantics, the
right trigger point, the keystroke-delivery path, race conditions, and
ships a working `settings.json` snippet plus a complete prototype hook
script. Source: claude-code-guide subagent against Claude Code v2.1.85+
docs.

## 1. Trigger choice — PostToolUse, not TeammateIdle

Two candidate hooks fire near "heat completed":

| Hook | When it fires | Fit for /clear-between-heats |
|---|---|---|
| `PostToolUse` (matcher=Bash, `if=Bash(smithy end-heat *)`) | After every Bash tool call matching the predicate | ✅ — fires immediately after end-heat, before Forge starts the next heat |
| `TeammateIdle` | When teammate is *about to go idle* (queue-empty) | ❌ — only fires at end of a continuous run; Forge stays awake heat-to-heat in the nudge loop |

The Forge protocol (`personas/forge/CLAUDE.md`) is **nudge-driven**:
`end-heat → SendMessage(Marshal) → drain-nudges → queue-pop →
start-heat`, all in one continuous flow without yielding control. The
Forge only "goes idle" (TeammateIdle fires) when `queue-pop` returns
`{task: null}` AND the next nudge hasn't arrived yet. So:

- TeammateIdle would clear context only at the *bottom of a work
  session*, not between consecutive heats — missing the primary
  ini-021 goal.
- PostToolUse on `smithy end-heat *` fires **between** heats, which is
  what the hypothesis asks us to test.

The claude-code-guide agent recommended TeammateIdle on grounds of
semantic precision; that recommendation is wrong for this loop, because
Forge doesn't actually idle between heats.

## 2. PostToolUse contract (verified against v2.1.85+ docs)

**Stdin payload received by the hook:**

```json
{
  "session_id": "abc123",
  "cwd": "/Users/mangesh/vibes/smithy2/.worktrees/forge-anneal",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "smithy end-heat 0.85 🟢 \"...\""
  },
  "tool_response": {
    "exitCode": 0,
    "stdout": "{\"heat\": 981, \"outcome\": \"submitted\", ...}",
    "stderr": "Heat 981 [research] 🟢 — ..."
  },
  "tool_use_id": "toolu_..."
}
```

Key fields for the /clear decision:

- `tool_response.exitCode == 0` — heat closed cleanly. A non-zero exit
  means smithy refused the close (e.g. checkpoint missing, witness gate
  failed); we MUST NOT clear because the model still needs to react.
- `tool_response.stdout` — JSON; parse `outcome`. Per ini-021,
  clear only on `outcome ∈ {complete, submitted}` and skip on
  `partial / blocked / rejected` to preserve the debug trail.

**Matcher syntax** (v2.1.85+): the `if` field scopes execution without
spawning the hook process for non-matching commands:

```json
{
  "matcher": "Bash",
  "if": "Bash(smithy end-heat *)",
  "hooks": [{"type": "command", "command": "..."}]
}
```

Pre-v2.1.85 the `if` field is silently ignored, so the hook would
spawn on every Bash call and need to filter in-script. Detect at
script start with `[ "${1:-}" != "smithy end-heat" ]`-style guards.

**Fire-and-forget**: hooks do NOT block the model's next turn. So a
60s pytest in a *different* tool call doesn't matter; and our /clear
script (which is fast) won't delay anything either.

## 3. Keystroke delivery — `tmux send-keys`

**Hooks cannot issue `/clear` directly.** Hooks return JSON decisions
or write stdout/stderr; they cannot inject conversational input or run
slash commands. The only path is external: `tmux send-keys` against the
pane.

The existing `scripts/nudge.sh` already uses this exact pattern
(`scripts/nudge.sh:75-76`):

```bash
tmux send-keys -t "$PANE_ID" -- "$MESSAGE"
tmux send-keys -t "$PANE_ID" Enter
```

For `/clear` the script needs the pane id. Two paths:

- **Inside a tmux session** (the production case): the hook inherits
  `$TMUX_PANE` from the surrounding pane env. `tmux send-keys -t
  "$TMUX_PANE" "/clear" Enter` works directly.
- **Outside tmux** (tests, manual runs): `$TMUX_PANE` is unset; the
  hook should detect and no-op silently.

Per docs, `Enter` (a tmux key name) submits the slash command. Splitting
text and Enter into two send-keys calls (the same pattern nudge.sh
uses) sidesteps a known Claude Code race where the pane buffer hasn't
flushed before the Enter arrives.

## 4. After `/clear` — what reloads automatically

The claude-code-guide agent verified against the docs:

| Reloads automatically on next user turn | Notes |
|---|---|
| System prompt | The model returns to its base system prompt |
| Project CLAUDE.md (current dir) | The `cd` invariant in personas/forge/CLAUDE.md ensures the right one loads |
| `~/.claude/projects/.../memory/MEMORY.md` (auto-memory) | First 200 lines / 25KB |
| Skills (descriptions) | Full bodies load on invocation |

Persona files Forge actually depends on (CLAUDE.md, IDENTITY.md,
memory/<suffix>/MEMORY.md) need to be read by the model on the
next turn. The Forge CLAUDE.md says "When Anvil spawns you: 1. cd …
2. Read this CLAUDE.md, IDENTITY.md, and memory/<your-suffix>/MEMORY.md".
After /clear, the next nudge ("Task t-XXX queued. Run smithy queue-pop
to start.") doesn't itself instruct the model to read those files — the
project CLAUDE.md auto-load *should* do it because that file's first
section is "Starting Up" with the read instructions. **This is the
biggest empirical risk**; see §6.

## 5. Race conditions and edge cases

### 5.1 Nudge during `/clear`

Per docs: text injected via `tmux send-keys` while `/clear` is
executing **survives** — the new text appears after `/clear` completes
and the new prompt is ready. So the auto-nudge cycle (`end-heat`
nudges Marshal → Marshal pushes a task → nudges Forge) is safe even
if the nudge arrives milliseconds after `/clear` was sent.

### 5.2 `/clear` during model response

If the hook fires faster than the assistant finishes its end-heat
response (it shouldn't — PostToolUse fires after the tool returns
and the assistant has formatted its own follow-up text — but
defensively): the docs say `/clear` gets queued. The current
response completes, then the clear executes. No content loss.

### 5.3 Mid-heat failure

If `smithy end-heat` aborts before emitting valid JSON (e.g. the
witness gate fails and exits 2), the hook still fires (PostToolUse
fires on success and failure). Two filters protect us:

1. `tool_response.exitCode != 0` → exit 0 without clearing.
2. `outcome` field absent from stdout JSON → exit 0 without clearing.

This means the failure path preserves the model's context so it can
read the gate failure and react. ✅.

### 5.4 Long-running Bash

`smithy end-heat` itself is fast (<1s). If a *different* tool call is
long (pytest 60s), it doesn't matter — the hook wouldn't match it
anyway. If end-heat ever became slow, the hook still doesn't block
the next turn (fire-and-forget per §2).

### 5.5 SessionEnd already fires

`.claude/settings.json` already has a `SessionEnd` hook running
`hooks/session-end-forge.sh` which distills the session into
MEMORY_DAILY.md. `/clear` is *not* the same as session end — `/clear`
keeps the same Claude Code session alive but starts a new context;
SessionEnd only fires on full session shutdown. So our hook does not
collide with the existing memory distillation.

### 5.6 Drive-by: `hooks/teammate-idle.sh` is silently broken

`hooks/teammate-idle.sh` reads `state.json` and queries `state["tasks"]`,
but smithy state schema uses `state["queue"]` (the `tasks` key was
renamed pre-t-419 / never matched the smithy schema). The `PENDING`
count is always 0, so the hook always exits 0 (allow idle) — the
"keep teammate working" branch is dead code. Worth a small follow-up
task to either delete or fix this hook; orthogonal to ini-021.

## 6. Empirical risk: Agent Teams system prompt persistence

Forges are spawned by Anvil via the Agent tool. Claude Code Agent
Teams sets a per-teammate role binding (which is what makes
`SendMessage` and the team coordination work). **It is not documented
whether `/clear` resets the team-spawn role binding** — i.e., does
post-/clear Forge still know it is "Forge" with `SendMessage(Marshal)`
available, or does it become a generic Claude Code session that
re-loads CLAUDE.md but lacks the team context?

If the role binding is lost:
- `SendMessage` may still appear as a tool, but the team
  routing might be broken.
- The next nudge "Task t-XXX queued" lands in a generic context;
  CLAUDE.md auto-load instructs reading persona files, which would
  re-establish the *content* of the Forge persona, but not necessarily
  the *team coordination plumbing*.

If preserved (likely outcome based on how Agent Teams models
spawning):
- The role binding persists like the system prompt, and we get a clean
  fresh-context Forge that is still part of the team.

**Validation plan for R3:**
1. Land the hook with a kill-switch env var
   (`FORGE_AUTO_CLEAR_ENABLED=1`).
2. Run on forge-anneal only (one-arm trial). Watch the rig-events log
   for: (a) does the next nudge after a /clear get processed correctly,
   (b) does SendMessage to Marshal still route, (c) does the model
   self-identify as Forge.
3. If broken, add a re-prime step: hook also enqueues a one-line
   nudge after /clear that says "You are forge-anneal; cd to your
   worktree and read CLAUDE.md to resume the heat loop." This is the
   defensive fallback that makes the experiment recoverable.

## 7. Working `settings.json` snippet

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "if": "Bash(smithy end-heat *)",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/hooks/post-end-heat-clear.sh",
            "timeout": 10000
          }
        ]
      }
    ]
  }
}
```

Notes:

- `$CLAUDE_PROJECT_DIR` resolves to the worktree root, so the hook
  path works for every Forge worktree without cwd guesswork.
- `timeout: 10000` (10s) is generous; the script does at most a
  `tmux send-keys` pair.
- `if` field gates execution — pre-v2.1.85 the predicate is ignored,
  so the script must still self-guard (see prototype).

## 8. Prototype `hooks/post-end-heat-clear.sh`

```bash
#!/usr/bin/env bash
# PostToolUse hook: clear Forge context after a clean end-heat.
# Wired by .claude/settings.json with `if=Bash(smithy end-heat *)`.
#
# Decision rules:
#   exit 0 = no /clear (default; preserves debug trail on failures)
#   /clear sent only when ALL of:
#     - the matched command starts with `smithy end-heat`
#     - tool_response.exitCode == 0
#     - tool_response.stdout has `"outcome": "complete"` or "submitted"
#     - $TMUX_PANE is set (we're inside a tmux pane)
#     - $FORGE_AUTO_CLEAR_ENABLED == "1" (kill switch)
#
# Intentionally Bash-only (no jq dep); parses with grep/sed.

set -euo pipefail

# Kill switch — default OFF so the hook is inert until R3 enables it.
if [[ "${FORGE_AUTO_CLEAR_ENABLED:-0}" != "1" ]]; then exit 0; fi

# Read full hook payload.
INPUT=$(cat)

# Self-guard for pre-v2.1.85 where `if` is ignored.
CMD=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    p = json.load(sys.stdin)
    print(p.get("tool_input", {}).get("command", ""))
except Exception:
    pass
')
case "$CMD" in
  "smithy end-heat "*) ;;
  *) exit 0 ;;
esac

# Read tool_response fields.
read -r EXIT_CODE OUTCOME < <(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    p = json.load(sys.stdin)
    tr = p.get("tool_response", {})
    rc = tr.get("exitCode", 1)
    so = tr.get("stdout", "")
    out = ""
    try:
        j = json.loads(so)
        out = j.get("outcome", "")
    except Exception:
        pass
    print(rc, out)
except Exception:
    print(1, "")
')

if [[ "$EXIT_CODE" != "0" ]]; then exit 0; fi
case "$OUTCOME" in
  complete|submitted) ;;
  *) exit 0 ;;
esac

# We are in a tmux pane — required.
if [[ -z "${TMUX_PANE:-}" ]]; then exit 0; fi

# Send /clear in two steps — same pattern as scripts/nudge.sh
# to dodge the buffer-flush race.
tmux send-keys -t "$TMUX_PANE" -- "/clear"
tmux send-keys -t "$TMUX_PANE" Enter

# Optional: log to rig-events for the A/B analysis in R3.
LOG="${CLAUDE_PROJECT_DIR:-$(pwd)}/rig-events.jsonl"
TS="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
printf '{"ts": "%s", "event": "forge_auto_clear", "actor": "%s", "outcome": "%s"}\n' \
  "$TS" "${FORGE_ID:-unknown}" "$OUTCOME" >> "$LOG" 2>/dev/null || true

exit 0
```

This script is intentionally inert until `FORGE_AUTO_CLEAR_ENABLED=1`
is exported in the Forge's pane env. Production rollout for the
A/B trial sets it on forge-anneal only:

```bash
# In tmux-layout.sh when launching forge-anneal:
tmux send-keys -t "$pid" "export FORGE_AUTO_CLEAR_ENABLED=1" Enter
```

## 9. Open questions for R3 (not in scope here)

1. **Persona re-prime nudge**: do we need a one-shot "you are
   forge-anneal, read CLAUDE.md" nudge after /clear, or does the
   project CLAUDE.md auto-load handle it? Empirical — answer in R3
   with the kill switch enabled.
2. **Outcome filter precision**: should `submitted` actually clear,
   given that Assembly may bounce the branch back? If it bounces, the
   re-pop will be a fresh context that has to reconstruct the prior
   work from disk — possibly fine, possibly slow. Trial both modes.
3. **Heartbeat / nudge ordering**: does `/clear` interfere with
   the SendMessage(Marshal) step that runs RIGHT before queue-pop?
   The flow is: end-heat → SendMessage(Marshal) → drain-nudges →
   queue-pop → start-heat. Hook fires after end-heat, but the
   model may still be mid-response writing the SendMessage. Per
   §5.2 /clear queues until response completes — should be fine,
   but R3 should confirm against a real run.
4. **Marshal and Anvil**: do they want the same hook? Marshal also
   has a tight loop and likely accumulates context across many
   re-prioritizations. Out of scope for ini-021 (which targets
   Forge), but the same mechanism would extend trivially.
5. **Compact-event detection**: ini-019 will eventually expose
   auto-compact events. When it does, replace the kill switch with a
   smarter trigger — clear only when token usage > threshold OR a
   compact just fired (proactive vs reactive).

## 10. Recommended R3 ship list

In dependency order:

1. Create `hooks/post-end-heat-clear.sh` per §8 verbatim.
2. Wire `.claude/settings.json` per §7 in **only forge-anneal's
   worktree** (`.worktrees/forge-anneal/.claude/settings.json`).
3. Set `FORGE_AUTO_CLEAR_ENABLED=1` in forge-anneal's tmux pane env
   (one-line addition to `scripts/tmux-layout.sh` gated on the forge
   id).
4. Run 20 heats on forge-anneal, watch `rig-events.jsonl` for
   `forge_auto_clear` rows interleaved with `forge_ended_*` rows.
5. Validate per §6 — does Forge survive `/clear` and continue the
   loop? If no, add the re-prime nudge as a §9-Q1 follow-up.
6. Compare reject rate / value scores against forge-temper (the
   no-clear control) per the ini-021 R1 baseline at
   `research/ini-021-baseline.md` §5.

R3 is one implementation heat (steps 1-3) plus one observation/heat
of analysis (steps 4-6). No new code for the A/B harness itself —
the existing `rig-events.jsonl` carries it.
