# The Wavefront Allocator

Run `smithy allocate` to get the recommended stage. The algorithm is implemented in `smithy/smithy/allocator.py`.

## How It Works

```bash
smithy allocate    # Returns: recommended_stage, scores, targets
```

### The 6 Stages (Dependency Chain)

```
research → planning → implementation → testing → editing → marketing
```

### Benefit Computation

Each stage's benefit = readiness × (1 - own_progress):
- **readiness** = progress of its prerequisite stage (1.0 for research)
- This naturally creates a wavefront — effort flows from research → marketing

### PI Controller Scoring

For each stage:
```
target = normalized benefit (with 0.05 floor)
error = target - actual_fraction
integral = old_integral * 0.85 + error    (clamped ±0.5)
score = (error + integral * 0.1 + value_bonus) * priority_boost
```

### Stage Selection

- Normally: pick highest-scoring stage
- Every 5th heat: pick second-highest (exploration)

### Bonuses

- **Unblocking override**: +0.3 for stages with critical-path tasks
- **Queued task bonus**: +0.07 per pending task in a stage
- **Priority boost**: 2× for stages in `human_priorities`

## Don't Compute This Yourself

The math is in Python. Just run `smithy allocate` and use the recommended stage. The explanation above is for understanding, not manual computation.
