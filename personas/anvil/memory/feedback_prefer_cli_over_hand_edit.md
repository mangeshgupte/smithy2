---
name: Prefer smithy CLI over hand-editing state.json for fields with invariants
description: When a field has uniqueness / ordering / cross-field constraints (rank, priority, status transitions), use the CLI (or queue a task to add one) rather than Python-in-bash editing
type: feedback
---

When changing `state.json` fields that have invariants — uniqueness (e.g., rank), ordering (rank again), cross-field constraints (status transitions, blocked_by references), or cascade effects — use a `smithy` CLI command that owns the invariant. Hand-editing via inline Python bypasses the housekeeping and creates drift.

**Why:** 2026-04-18, I hand-edited `ini-020.rank=2` and `ini-019.rank=3` via Python, unaware that ini-016 (rejected) and ini-017 (rejected) were already sitting at ranks 2 and 3. Collision, spotted in the post-change print. Root cause: no CLI enforced the rank invariants (unique among approved, contiguous). A `smithy initiative rank <id> <N>` with cascade-shift semantics would have handled it. Queued t-466 to add exactly that.

**How to apply:**
- For fields with clear invariants (rank, priority, blocked_by refs, status transitions), look for a CLI command first. If none exists, queue one as a task and find a narrow workaround rather than hand-editing.
- Acceptable hand-edits: free-text fields (desc, priority_reason), non-invariant scalar toggles (halt_flag).
- Not acceptable hand-edits: anything where "what about other rows?" is a question I have to answer in my head. That's the invariant — let code own it.
- Before any direct state.json edit, ask: "what would this need to cascade to?" If anything, use or build the CLI.
