# The Wavefront Allocator

Decides which stage to work on each heat.

## The 6 Stages (Dependency Chain)

```
research → planning → implementation → testing → editing → marketing
```

## Compute Benefit Per Stage

For each stage, compute how much benefit additional work would produce:

```
Dependency chain (each stage's prerequisite):
  research:       none (always ready)
  planning:       research
  implementation: planning
  testing:        implementation
  editing:        implementation
  marketing:      editing

For each stage:
  if stage is "research":
    readiness = 1.0
  else:
    readiness = progress of its prerequisite stage (from the chain above)

  benefit = readiness * (1.0 - own_progress)
```

The key insight: a stage gets high benefit when its prerequisites are sufficiently done (`readiness` is high) but the stage itself still has work to do (`1 - own_progress` is high). This naturally creates a wavefront — effort concentrates on research first, then as research progresses, planning benefit rises, then implementation, etc.

## Compute Dynamic Targets

Normalize benefits to get target fractions:

```
total_benefit = sum of all stages' benefit (or 1 if zero)
target[stage] = benefit[stage] / total_benefit
```

A floor of 0.05 per stage ensures nothing is completely starved. After applying floors, renormalize to sum to 1.0.

Update the targets in state.json.

## Score Each Stage (PI Controller)

The dynamic targets feed into the PI controller to smooth allocation:

```
total_heats_used = sum of all stages' heats (or 1 if zero to avoid division by zero)
actual_fraction = this_stage.heats / total_heats_used
error = target - actual_fraction
integral = state.allocator.integral[stage] * 0.85 + error    # decay old errors (anti-windup)
integral = clamp(integral, -1.0, 1.0)                        # safety cap
value_bonus = stage.value_ema * 0.3
priority_boost = 2.0 if stage is in human_priorities, else 1.0

score = (error + integral * 0.1 + value_bonus) * priority_boost
```

Store the updated `integral` values back to state.json.

**Anti-windup**: The 0.85 decay factor means old errors lose ~50% weight after 5 heats and ~80% after 10. The ±1.0 clamp prevents extreme accumulation. This stops any single stage from permanently dominating the allocator due to early-phase imbalances.

## Pick Stage

- Normally: pick the stage with the highest score.
- Every 5th heat (heat number % 5 == 0): pick the **second-highest** scoring stage instead (exploration).
