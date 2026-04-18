# ini-021 — Context Reset Per Task: design + rollout plan

**Source briefs:**
- R1 baseline: `research/ini-021-baseline.md` (t-451)
- R2 mechanism: `research/ini-021-clear-mechanism.md` (t-452)

**Status:** planning complete, tasks ready for Marshal to file.
**Hypothesis:** Forge session context between tasks is not load-bearing —
all durable output already persists on disk (worklog, state.json,
persona memory, checkpoints, branches). Cross-heat context accumulation
causes pollution (stale branch identity, autoregressive drift, retry
cascades) and unnecessary token burn.

## 1. Trigger rule (CLEAN-end-heat-only)

`/clear` fires exactly when **all** of:

1. The most recent Bash tool call matched `smithy end-heat *`
2. That call exited with `exitCode == 0`
3. The end-heat stdout JSON contains `"outcome": "complete"` OR
   `"outcome": "submitted"`
4. The Forge pane is inside a tmux session (`$TMUX_PANE` set)
5. The kill switch is on: `FORGE_AUTO_CLEAR_ENABLED=1`

**Skip on `partial`, `blocked`, `rejected`** — those outcomes signal
the model has unfinished work or a problem to react to; preserving the
debug trail is more valuable than the token savings.

**Why not TeammateIdle?** R2 §1 establishes this. In nudge-driven mode
Forge does *not* idle between heats — it loops `end-heat → SendMessage
→ drain-nudges → queue-pop → start-heat` continuously. TeammateIdle
fires only at queue-empty, which would clear once per work session
instead of once per heat. The hypothesis requires per-heat clearing.

## 2. Hook wiring

### 2.1 settings.json (per-Forge worktree)

Lives at `.worktrees/<forge-id>/.claude/settings.json`. Add:

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

The `if` field requires Claude Code v2.1.85+. Pre-2.1.85 the predicate
is silently ignored, so the script must self-guard (covered in §2.2).

### 2.2 hooks/post-end-heat-clear.sh

Verbatim from R2 §8 — already drafted there. Key properties:

- Default-OFF kill switch (`FORGE_AUTO_CLEAR_ENABLED`) — script returns
  immediately if unset.
- Self-guards against pre-v2.1.85 by re-checking the command prefix.
- Parses `tool_response.exitCode` and stdout JSON `outcome` with
  Python (no `jq` dep).
- Two-step `tmux send-keys` (text then Enter) to dodge the buffer
  flush race (same pattern as `scripts/nudge.sh:75-76`).
- Optional rig-events log row (`forge_auto_clear`) for the A/B
  observation in §5.

Place at `hooks/post-end-heat-clear.sh`, `chmod +x`, ship in the
implementation heat.

### 2.3 Compatibility with existing hooks

Already present in `.claude/settings.json`:

| Hook | Script | Conflict? |
|---|---|---|
| `SessionEnd` | `hooks/session-end-forge.sh` | None — fires only on full session shutdown |
| `TeammateIdle` | `hooks/teammate-idle.sh` | None — fires at idle; this hook fires at end-heat |
| `TaskCompleted` | `hooks/task-completed.sh` | None — fires on team-task completion, not Bash output |

Drive-by from R2 §5.6: `hooks/teammate-idle.sh` is silently broken
(reads `state["tasks"]`, smithy uses `state["queue"]`). Out of scope
for ini-021 but file as a follow-up clean-up task.

## 3. loop.md protocol update — warm-up read after `/clear`

After a `/clear`, Claude Code automatically re-reads:

- System prompt
- Project CLAUDE.md from the current cwd
- `~/.claude/projects/.../memory/MEMORY.md` (auto-memory, first 25KB)

The Forge persona CLAUDE.md already begins with a "Starting Up"
section that instructs reading `IDENTITY.md`, persona memory, and
state.json. So the *content* is recoverable. What needs an explicit
addition to `protocol/loop.md` is acknowledging that a /clear may have
just happened, and the model should treat the *next* prompt (almost
certainly a Marshal nudge like `Task t-XXX queued. Run smithy
queue-pop to start.`) as a fresh-context resume signal.

Proposed insertion in `protocol/loop.md`, after the existing Step 0
(Session Start):

```markdown
## Step 0.5: Warm-up after `/clear` (when ini-021 auto-clear is enabled)

If your previous heat triggered `/clear` (you'll see this prompt
arrive in a context that has only your CLAUDE.md auto-loaded, no
prior assistant turns), do not re-run session bootstrap — that's
expensive and the prior pane already did it. Just:

1. Read `state.json` (lightweight — only the fields you need).
2. Read `MEMORY_DAILY.md` if you depend on recent insights.
3. Run `smithy queue-pop` (the nudge prompt that arrives says exactly
   that anyway).

Heuristic: if you don't recognize the most recent commit's content
(check `git log --oneline -3`) and your conversation has no prior
turns, you're post-/clear. Skip patrol/sync — they just ran in the
prior heat.
```

Self-contained — no env-var sniffing required.

## 4. Rollout strategy

**Phased, single-Forge first.**

| Phase | Scope | Duration | Exit condition |
|---|---|---|---|
| 0 — Land code | hooks/post-end-heat-clear.sh + per-worktree settings.json template + loop.md update + a kill-switch in `scripts/start-smithy.sh` | 1 implementation heat | Tests green; manual smoke on forge-anneal works |
| 1 — Single-Forge dry run (kill switch OFF) | Hook in place on forge-anneal but `FORGE_AUTO_CLEAR_ENABLED` unset; verify hook doesn't fire | 5 heats on forge-anneal | Zero `forge_auto_clear` rows in rig-events; nothing else changes |
| 2 — Single-Forge enable | Set `FORGE_AUTO_CLEAR_ENABLED=1` for forge-anneal only | 20 heats on forge-anneal | A/B comparison §5 favourable OR hard rollback per §7 |
| 3 — Roll to all Forges | Enable on forge-quench and forge-temper too | 20 heats per Forge | Stable; no regression vs Phase 2 |

**A/B arm assignment:**
- **Treatment**: forge-anneal — has the shortest baseline sessions, so
  any drift caused by /clear shows fastest.
- **Control**: forge-temper — comparable session lengths historically,
  also rarely involved in Assembly attribution noise.
- **Skip**: forge-quench — primary Forge, doubles as Assembly's pane
  context; clearing it would interfere with Assembly's interactive
  loop and confound the measurement.

## 5. Metrics to track

Headline question: *does auto-clearing context per heat reduce reject
rate / retry depth without harming value scores?*

| Metric | Source | Baseline (per R1) | Win condition |
|---|---|---|---|
| Reject rate | worklog.tsv outcome | 0% in short sessions, 27-42% in long sessions (forge-quench, but biased by Assembly attribution — measure forge-anneal/forge-temper instead) | ≤ control arm's rate |
| Retry cascade depth | max(starts) per (forge, task) | 5 (t-431, single session) | ≤ 2 in treatment arm over 20 heats |
| Value score (median) | worklog.tsv value | 0.85 ± 0.10 across all forges | within ±0.05 of control arm |
| Cross-task mentions in notes | regex `t-\d{3}` − own | 42% of heats reference other tasks | ≥ 50% reduction (proxy for context bleed) |
| Context proxy (scrollback lines) | `wc -l` of transcript at end-heat | unmeasured today; needs §6 hook | post-/clear should reset to small N each heat |
| forge_auto_clear emit count | rig-events.jsonl | 0 (pre-rollout) | matches count of clean end-heats during Phase 2 |

**Observation harness:** new rig-events row `forge_auto_clear` from
the hook script + the existing `forge_ended_*` rows from end-heat.
Both are already in `rig-events.jsonl`; Bellows / ini-019 dashboards
can read directly.

## 6. Telemetry hook (folded in from R1 §4)

The R1 baseline noted that no token-level telemetry exists today, so
the A/B y-axis is currently coarse. Land alongside the /clear hook a
small `forge_context_snapshot` rig-event, emitted from
`smithy end-heat` just before the existing `forge_ended_*` event:

```python
# In cli.py, just before the existing _emit_rig_event for forge_ended_*:
_emit_rig_event(root, "forge_context_snapshot",
                actor=forge_id, forge_id=forge_id, task_id=task_id,
                heat=heat, transcript_lines=lc, transcript_chars=cc,
                token_estimate=cc // 4, heats_since_clear=hsc)
```

Where `lc/cc` come from `wc -l` / `wc -c` of the Claude Code
transcript (resolve via `$CLAUDE_PROJECT_DIR/.claude/sessions/...` or
similar — confirm path during the implementation heat). `heats_since_clear`
is a counter persisted to `.forge-checkpoint-<id>.json` and reset
inside `post-end-heat-clear.sh`.

This delivers the y-axis the §5 metrics table needs. Field names
chosen so a future ini-019-driven swap to clean Anthropic SDK token
counts can keep dashboard compatibility.

## 7. Rollback path

The kill switch is the primary rollback:

```bash
# In the Forge's tmux pane:
unset FORGE_AUTO_CLEAR_ENABLED
# Or in scripts/start-smithy.sh, comment out the export.
```

Effect: hook script returns immediately on every PostToolUse fire; no
/clear is sent. No file edits required, no restart of Claude Code.

**Hard rollback** (if hook misbehaves at the OS level — e.g. mass
sending /clear during an unrelated tool call):

1. Remove the PostToolUse stanza from
   `.worktrees/<forge-id>/.claude/settings.json`.
2. The hook script can stay on disk (it's inert without
   `FORGE_AUTO_CLEAR_ENABLED=1` AND the settings.json wiring).
3. No state migration needed — existing rig-events rows for
   `forge_auto_clear` stay as historical data.

**Indicators that we should rollback before phase exit:**

- The next nudge after a `/clear` is silently dropped or re-routed
  (verify by ASSEMBLY_QUEUE / queue-pop telemetry continuity).
- Forge starts mis-identifying its persona (commits land on wrong
  branch, SendMessage targets wrong teammate, etc.).
- Reject rate climbs above control arm's baseline by ≥ 50%.
- Any case where a heat's recovery requires human intervention.

## 8. Risks (verbatim from R2 §6 + new)

1. **Agent Teams role-binding persistence across `/clear` is
   undocumented.** Highest unknown. Mitigation: kill switch + Phase 1
   dry run + the §3 warm-up read sequence as a defensive prime.
2. **Re-prime needed?** If after `/clear` the model doesn't
   self-identify as Forge, the next nudge needs to start with "You
   are forge-anneal; …". Decision: ship the hook *without* the
   re-prime; if Phase 1/2 shows it's needed, add a §3-Q1 follow-up
   that has the hook script also enqueue a one-line nudge after
   `/clear`.
3. **Submitted-then-rejected race.** A /clear after `submitted` clears
   the context that just produced the work. If Assembly later rejects,
   the next heat re-pops a fresh-context Forge that has to reconstruct
   from disk (worklog notes, branch SHA). For research/planning
   commits this is fine; for implementation that needs in-flight
   debugging context it could slow recovery. Trial both clear-on-
   submitted and clear-only-on-complete in Phase 2 if Phase 1 shows
   ambiguity. Default: clear on both.
4. **Hook timeouts.** `tmux send-keys` is fast, but if the pane is
   busy the keystrokes might queue. Hook timeout 10s leaves head-room.
5. **forge-quench (skipped from rollout) carries Assembly context.**
   Don't accidentally enable on forge-quench — Assembly's drain loop
   can be 50+ items deep mid-rebase. A mid-tick /clear would
   catastrophically dump the pane mid-merge. Belt-and-suspenders:
   put a `[ "$FORGE_ID" = "forge-quench" ] && exit 0` guard in the
   hook script even when `FORGE_AUTO_CLEAR_ENABLED=1`.

## 9. Tasks ready for Marshal to file

In dependency order:

| # | Stage | Title | Heats | Depends |
|---|---|---|---|---|
| T1 | implementation | Land `hooks/post-end-heat-clear.sh` + per-worktree settings.json template + `forge_context_snapshot` rig-event in `smithy end-heat` + protocol/loop.md §0.5 update | 1 | t-453 (this) |
| T2 | implementation | Add `FORGE_AUTO_CLEAR_ENABLED` plumbing to `scripts/start-smithy.sh` (default unset; export only when launching forge-anneal) | 1 | T1 |
| T3 | testing | Phase 1 dry run on forge-anneal with switch OFF — verify hook is inert | 1 | T2 |
| T4 | implementation | Phase 2 enable on forge-anneal; observe 20+ heats | 1 (observation) | T3 |
| T5 | research | Analyze rig-events for §5 metrics; produce `research/ini-021-ab-results.md` | 1 | T4 + 20 heats elapsed |
| T6 | implementation | Phase 3 roll out to forge-temper if T5 favorable; or rollback per §7 | 1 | T5 |

Total budget request: ~6 heats. Initiative cap is 15 (per state.json
`ini-021.budget_cap`); plenty of room.

## 10. Open questions for the implementation heat (T1)

1. **Transcript path resolution** — what env var or filesystem
   convention exposes the active Claude Code transcript file inside a
   PostToolUse hook? Best guess:
   `$CLAUDE_PROJECT_DIR/.claude/sessions/<session_id>.jsonl`. The hook
   stdin payload includes `session_id`; verify the on-disk path layout
   during T1.
2. **`heats_since_clear` persistence** — should it live in a new field
   on `.forge-checkpoint-<id>.json` or in a fresh sidecar
   `.forge-clear-counter-<id>.json`? Checkpoint is reset on
   start-heat, so probably needs a sidecar.
3. **ini-022 lifecycle interaction** — `scripts/start-smithy.sh` is
   actively being reshaped by ini-022 (rig startup + lifecycle). Land
   the export in a way that doesn't conflict — coordinate with whoever
   owns ini-022's next implementation heat.
