# ini-019 R2 — Retro Initiative-ID Backfill Design

**Task:** t-445 · **Initiative:** ini-019 · **Heat:** 824 · **Stage:** research

Design note and handoff for t-447 (implementation). Answers: *what schema
changes ship, how the migration script infers mappings, what the operator
reviews, and how validation gates commits*.

## 1. Schema change (TARGET v2)

`state.queue[*].initiative_id` becomes **required** and **nullable**:

- Every task object carries the field (no more `in` checks in consumers).
- `null` = "not yet mapped"; a non-null string must be a valid key from
  `state.initiatives[*].id`.
- `schema_version` bumps `1 → 2`.

Current state (2026-04-18):

| Bucket | Count | Action |
|---|---|---|
| `initiative_id` present, non-null | 185 | leave — never overwritten |
| `initiative_id` present, null | 0 | n/a |
| `initiative_id` field absent | 209 | add field (`null`) under `--apply-schema` |

Rejected or deferred initiatives (status `rejected`, 8 today) are **never
candidates** for inference; historical tasks linked to them stay null.

## 2. Script contract

`scripts/ini-019-backfill-initiative-id.py` — committed with t-445, runnable by
t-447. Self-contained, no smithy dep.

Modes:

| Flag | Effect | Writes state.json? |
|---|---|---|
| `--dry-run` (default) | Print proposed mapping table | no |
| `--out plans/...md`   | Same, to a markdown file | no |
| `--apply-schema`      | Add `initiative_id: null` to missing tasks; bump `schema_version`. Validates before writing. | yes (idempotent) |
| `--apply-mapping`     | Apply inferred mappings; skips ambiguous unless `--allow-ambiguous`. | yes |

Exit codes: `0` clean, `1` validation failure (aborts without writing),
`2` applied with ambiguous skips (operator review signalled).

## 3. Inference signals

Three independent signals combined to a score ∈ [0, 1]:

1. **Desc ↔ initiative-description Jaccard** — weighted 0.6 × j. Tokens are
   `[a-z0-9_-]{3,}` minus a 40-word stoplist (common English + Forge-generic
   verbs like *add, fix, run*). Low-signal pair → low j → doesn't contribute.
2. **Explicit `ini-NNN` reference** — +0.4 if the initiative id literally
   appears in the task desc; +0.25 if it appears in a commit message that
   also mentions the task id (`git log -G "t-XXX"`).
3. **Initiative-title token overlap** — +0.2 if ≥50% of title tokens also
   appear in the task desc. Title tokens are narrower and less prone to
   false-positives than full-description tokens.

A proposal is **ambiguous** when the runner-up initiative's score is within
0.10 of the top — the script flags it and declines to apply it without
`--allow-ambiguous`.

Threshold `confidence ≥ 0.20` to propose at all; below that, task stays null.

## 4. Dry-run results (current repo state)

| Bucket | Count | Notes |
|---|---|---|
| Proposals evaluated | 209 | every task missing `initiative_id` |
| High confidence (≥0.50) | 0 | no slam-dunks — most early tasks predate initiatives |
| Medium (0.20–0.49) | 54 | operator should scan these |
| Ambiguous | 18 | top-2 scored within 0.10 — deliberate no-op |
| No confident match | 155 | infrastructure / pre-initiative era tasks |

Dry-run file: `plans/ini-019-retro-map.md` (written by this heat).

**Observation:** the low high-confidence count is expected. The initiative
framework landed around t-183 (ini-009); ~140 earlier tasks existed before
then and won't map to anything sensible. The right call for t-447 is to
leave them null rather than force-fit.

## 5. Operator review flow (t-447)

1. Run with no flags → inspect `plans/ini-019-retro-map.md`.
2. Manually annotate the markdown for any medium-confidence rows that
   look wrong or the ambiguous/no-match rows that clearly belong somewhere.
3. For edits, either patch `state.json` by hand (single-edit, reviewable
   diff) or re-tune the script's signal weights and re-run.
4. Run `--apply-schema` first — safe, idempotent, adds nullable field.
5. Run `--apply-mapping` after review — applies only non-ambiguous
   high/medium-confidence proposals. Operator passes `--allow-ambiguous`
   only for the tie-break cases they've manually vetted.
6. Commit the state.json update on a single Assembly-ready branch.

## 6. Validation contract

`validate(state)` checks, run before every write:

- Every task has the `initiative_id` field.
- Every non-null `initiative_id` is a valid key in `state.initiatives`.
- Script refuses to write on validation failure (exit 1).

This is the only new invariant. Consumers of `state.queue` that previously
did `task.get("initiative_id")` continue to work; the field is now
guaranteed present, so `task["initiative_id"]` works too (consumer-side
cleanup is opportunistic, not a blocker).

## 7. Gaps flagged for Marshal / Anvil

1. **Low coverage is structural, not a script defect.** 155/209 legacy tasks
   will map to nothing. D-series initiative metrics (per ini-019 R1 inventory)
   will carry a "legacy/unscoped" bucket for older heats. That's honest.
2. **No stopword tuning loop.** If the 54 medium-confidence proposals look
   noisy in review, the fix is to expand `STOPWORDS` in the script — not to
   guess at tasks manually.
3. **Future invariant.** Once this lands, every *new* task should carry
   `initiative_id` at creation time (marshal's `add-task` default to
   `null` if unknown, or required CLI arg if Marshal sets it). That's a
   separate follow-up — propose as t-449 or similar.

## 8. Deliverables (this heat)

- `scripts/ini-019-backfill-initiative-id.py` — the migration tool.
- `plans/ini-019-retro-map.md` — the dry-run mapping for t-447 review.
- `research/ini-019-r2-backfill-design.md` — this document.

State.json is **not** modified in this heat. `--apply-schema` and
`--apply-mapping` are t-447's job; gating them behind an explicit operator
run preserves the "only Assembly writes to main" invariant.

---
**Prepared by:** forge-temper · heat 824 · research stage · 2026-04-18
