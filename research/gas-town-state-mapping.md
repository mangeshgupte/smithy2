# Gas Town State Mapping

*Heat 482 research | 2026-04-10*

## How Smithy State Maps to Gas Town

| Smithy (flat files) | Gas Town (Dolt) | Notes |
|---------------------|-----------------|-------|
| `state.json` | `issues` table (beads) | Each task = a bead row. Budget/stages would need custom fields or separate table. |
| `worklog.tsv` | Dolt commit history + wisps | Each heat = a Dolt commit. Wisps for ephemeral patrol data. |
| `queue[]` (tasks) | Beads with `type=task`, `status`, `priority` | Direct mapping — beads already have status, priority, dependencies. |
| `allocator.integral{}` | No equivalent | Wavefront allocator is Smithy-specific. Would need custom state or `.runtime/` JSON. |
| `budget.*` | Rig config or agent bead metadata | No direct equivalent — Gas Town doesn't budget heats. |
| `feedback_cursor` | Mail protocol + read receipts | Gas Town uses `gt mail check` with read tracking. |
| `inbox_cursor` | Mailbox on agent bead | Messages tracked as bead dependencies. |

## Migration Path

1. **Tasks → Beads**: Each queue task becomes a bead (`bd create --type=task`). Status/priority/blocked_by map directly.
2. **Worklog → Commits**: Each heat's worklog entry becomes a Dolt commit message. The commit graph IS the worklog.
3. **State → Agent Bead**: Budget, stage progress, allocator state stored in agent bead's metadata JSON field.
4. **Feedback → Mail**: feedback.md entries become `gt mail send` messages to the Forge agent.

## Key Difference

Gas Town uses **Dolt commit graph** as the audit trail. Smithy uses **append-only TSV**. Both are immutable records, but Dolt's is queryable via SQL while TSV requires parsing.

The allocator and budget system have **no Gas Town equivalent** — they're Smithy innovations that Gas Town would benefit from.
