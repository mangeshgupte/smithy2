<!--
  Canonical initiative-retro template (ini-025 T2).

  Copy this file to plans/ini-<id>-retro.md when closing an initiative.
  Anvil fills the prose sections (Summary, What worked, What didn't,
  Carry-forward, What's next); a Forge "editing" task fills the data
  sections (What shipped, Metrics appendix) from the record. The header
  metrics are source-of-truth from state.json, NOT hand-counted.

  See plans/initiative-retros-design.md §"Artifact structure" for the
  contract, identity.md §"Initiative Lifecycle" for where this fits, and
  personas/anvil/CLAUDE.md §"Closing Initiatives" for the drafting steps.

  Delete every <!-- ... --> comment (including this one) before closing.
-->

# <ini-id>: <title> — Retrospective

**Closed:** YYYY-MM-DD
**Heat cost:** N heats (budgeted M)
**Task count:** K shipped / R rejected / A abandoned
**Successor:** <ini-id, or "none; maintenance via new initiatives as needed">
**Author:** Anvil (prose) + <forge-id> (data, task t-XXX)

## Summary

<!-- 2-3 sentences: what the initiative was, and what is different in the
     world now that it's done. Concrete, not aspirational. -->

## What shipped

<!-- Forge data fill. Bulleted list of concrete deliverables, each with
     its task id + merge sha. One line per shippable unit, newest or
     most-significant first. Example:
       - t-543: claim→start-heat idempotency seam — `a1b2c3d`
     Source: `git log --oneline main` filtered to this ini's merged
     branches; cross-check against the worklog (outcome=submitted rows). -->

<TODO: Forge data fill>

## What worked (keep doing)

<!-- Anvil prose. The NON-OBVIOUS wins: judgment calls that paid off,
     techniques validated, patterns worth repeating on the next
     initiative. Skip the obvious ("tests caught bugs") — capture what a
     future Smith wouldn't already know. -->

## What didn't (stop doing)

<!-- Anvil prose. Dead ends, premature abstractions, rework cycles, and
     bugs that RECURRED (cite the heats). The honest section — a yellow
     here is worth more than a green lie. -->

## Carry-forward

<!-- Anvil prose. Concrete learnings that apply to future work, as
     pointers, not restatements:
       - memories written (path + slug)
       - protocol/identity docs updated (file + section)
       - conventions codified (where the rule now lives)
     If a lesson isn't captured somewhere durable, capture it first, then
     point here. -->

## What's next

<!-- Pick one:
     - "Successor is <ini-id>: <one-line reason for the continuation>."
     - "No direct successor. Future <domain> work files as a new
       initiative when substantial; small fixes go to theme-<id> without
       initiative attribution." -->

## Metrics appendix

<!-- Forge data fill. Task-by-task breakdown. One row per task that
     carried a heat under this initiative. `result` is merged | rejected
     | abandoned; `sha` is the merge sha for merged rows, "—" otherwise.
     Source: worklog.tsv filtered to this ini's task ids + `git log`. -->

| task   | stage          | heats | result   | sha       |
|--------|----------------|-------|----------|-----------|
| t-XXX  | <stage>        | N     | merged   | `abc1234` |
| t-YYY  | <stage>        | N     | rejected | —         |

<TODO: Forge data fill>
