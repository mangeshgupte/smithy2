# Hard Timeout Enforcement for Heats

*Heat 104 | 2026-04-09*

## Question
How to enforce the ~5 minute heat budget? Currently heats have no hard timeout — the Smith self-regulates.

## Findings

### Claude Code Timeout Mechanisms

1. **Bash tool timeout**: Default 2 minutes, configurable up to 10 minutes per call via `timeout` parameter. Set default via `BASH_DEFAULT_TIMEOUT_MS` in settings.
2. **No heat-level timeout**: Claude Code has no concept of "heats" — timeouts apply to individual tool calls, not to logical work units.
3. **No external timer**: No way to set a timer that interrupts the Claude session after N minutes.

### Options for Heat Timeout

| Approach | Feasibility | Notes |
|----------|------------|-------|
| Self-regulation (current) | ✅ Working | Smith budgets ~4min execution + 1min logging. No enforcement. |
| Bash `timeout` command | ❌ Wrong level | Only limits individual commands, not the heat as a whole |
| External watchdog | ⚠️ Complex | Separate process monitors session, kills after N minutes |
| Hook-based timer | ⚠️ Possible | PreToolUse hook could track elapsed time per heat |
| Instruction-only | ✅ Simple | Protocol says "~5 minutes" — the LLM self-regulates |

### Recommendation

**Don't build a hard timeout.** The current self-regulation works well enough:
- The Smith naturally completes heats in 3-5 minutes
- The protocol says "~5 minutes" which is sufficient guidance
- Hard timeouts would require external orchestration (Python/shell wrapper), violating the "no external orchestrator" constraint
- If a heat runs long, it's usually because the work is valuable (research deep dives)

**If enforcement is ever needed**: Use a PreToolUse hook that checks elapsed time and warns/blocks after 5 minutes. But this adds complexity for minimal benefit.

### Impact on The Forge

No changes needed. The "~5 minutes" instruction in the protocol is sufficient. This is a non-issue in practice — in 99 heats, no heat has run significantly over time.

**Status**: t-039 resolved — no implementation needed.
