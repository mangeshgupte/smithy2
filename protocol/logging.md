# Logging Protocol

All logging is handled by `smithy end-heat`. You provide the inputs, smithy handles the record-keeping.

## End a Heat

```bash
smithy end-heat <value> <signal> "<notes>" [--outcome complete|partial|blocked]
```

This atomically:
- Increments `budget.used`
- Increments the stage's `heats` count
- Computes `value_ema`: 0.7 * old + 0.3 * new
- Updates allocator integral (with ±0.5 clamp and 0.85 decay)
- Appends a row to `worklog.tsv`
- Marks task complete (if outcome=complete)
- Updates `overall_progress`
- Deletes checkpoint

## Your Inputs

### Value (0.0-1.0)

Rate the heat's productivity honestly:
- **0.9-1.0**: Major breakthrough, key feature complete
- **0.7-0.8**: Solid progress, meaningful deliverable
- **0.5-0.6**: Some progress but hit friction
- **0.3-0.4**: Mostly setup/exploration
- **0.1-0.2**: Stuck, wrong direction

### Signal

- 🟢 **Green**: Completed normally, value ≥ 0.7, no issues
- 🟡 **Yellow**: Value < 0.7, or progress stalled, or moderate uncertainty
- 🔴 **Red**: Rollback, blocked > 5 heats, or deviation from intent

### Notes

One-line summary. Include self-critique: "Could improve: <what>". If nothing could be better: "Could improve: nothing obvious."

## Memory

```bash
smithy memory-write "<insight>" --heat <N> --stage <stage>
```

Appends to MEMORY_DAILY.md under today's date. Use for consolidated insights (every 6th heat).

## Outbox

Write to `outbox.md` manually when:
- You have a blocking question
- Completed a significant milestone
- Changed direction unexpectedly
- Budget is about to run out (last 3 heats)
