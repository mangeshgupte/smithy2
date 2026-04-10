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
total_chunks_used = sum of all stages' chunks (or 1 if zero to avoid division by zero)
actual_fraction = this_stage.chunks / total_chunks_used
error = target - actual_fraction
integral = state.allocator.integral[stage] + error
value_bonus = stage.value_ema * 0.3
priority_boost = 2.0 if stage is in human_priorities, else 1.0

score = (error + integral * 0.1 + value_bonus) * priority_boost
```

Store the updated `integral` values back to state.json.

## Pick Stage

- Normally: pick the stage with the highest score.
- Every 5th chunk (chunk number % 5 == 0): pick the **second-highest** scoring stage instead (exploration).
