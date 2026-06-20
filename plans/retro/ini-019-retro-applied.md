# ini-019 · Retro Initiative Backfill — Applied

**Task:** t-447 · **Heat:** 820 · **Applied:** 2026-04-18 (retry after earlier Assembly reject)

Record of the state.json migration executed by
`scripts/ini-019-backfill-initiative-id.py --apply-schema` then
`--apply-mapping`. This file is the audit trail; `state.json` itself
holds the mutation.

## Schema (already at v2)

Schema bump and initial mapping apply were executed by an earlier
t-447 attempt that merged to main. Re-running in this heat is
idempotent:

- `schema_version` is **2** (no change this run)
- Every task already has `initiative_id` field (no nulls added)
- `--apply-mapping` newly added **0** mappings (pre-existing ones are
  never overwritten; proposals unchanged)

## Current state (snapshot at heat 820)

| Bucket | Count |
|---|---|
| Total queue tasks | ~398 |
| Tasks with `initiative_id` field | 100% |
| Non-null `initiative_id` | ~224 |
| Still null (awaiting review or pre-ini-009 infra) | 174 |
| — medium-confidence (0.20–0.49) | 19 |
| — ambiguous (tie / near-tie) | 19 |
| — no confident match (<0.20) | 155 |

Refreshed dry-run: `plans/retro/ini-019-retro-map.md`.

## Validation

`tests/test_t447_initiative_id_invariant.py` pins three invariants:

1. `schema_version ≥ 2`
2. Every task has `initiative_id` field (nullable)
3. Every non-null `initiative_id` is a valid key in `state.initiatives`

All three pass against the live state at this heat.

## What's still null (deliberately)

- **155 pre-ini-009 infra tasks** — legitimately belong to no current
  initiative. The ini framework postdates them.
- **19 ambiguous tasks** — the script's top-2 proposals within 0.10
  score. Operator review required; `--allow-ambiguous` bypasses if
  they want to force the top pick after review.

Running `scripts/ini-019-backfill-initiative-id.py --allow-ambiguous
--apply-mapping` after operator review is the path to zero those 19.
The 155 stay null by design.

## Why this is a re-submit

Original t-447 commit landed at a2c60bde earlier in the day but was
bounced by Assembly during a test-gate regression window (unrelated
test_t455 breakage mid-drain). Re-running the migration is idempotent
— the script refuses to overwrite existing non-null initiative_ids
and only adds missing fields. This heat's value is (a) confirming the
state satisfies the invariants post-bounce and (b) landing the
invariant test in code.

---
**Applied by:** forge-temper · heat 820 · implementation stage · 2026-04-18
