# Integral Windup in the PI Allocator

## The Problem

Research integral is at 1.249 after 12 heats. It accumulated because:
- Heat 1: research target was 0.80 but only got 1 out of 1 heats → huge positive integral
- Subsequent heats: integral kept growing as research was consistently underallocated relative to its high early target
- Even at 50% progress with 3 heats, the integral still dominates all scores

This is **integral windup** — a classic PI controller problem where the integral term accumulates error faster than it can be corrected, leading to persistent bias.

## Solutions from Control Theory

### 1. Integral Clamping (Anti-Windup)
Cap the integral at a maximum absolute value. Prevents runaway accumulation.
```
integral = clamp(integral + error, -MAX, MAX)
# MAX could be 0.5 or 1.0
```
**Pros**: Simple, predictable. **Cons**: Arbitrary constant.

### 2. Integral Decay (Exponential Forgetting)
Decay the integral each heat so old errors fade out.
```
integral = integral * decay_factor + error
# decay_factor = 0.8 means 20% forgetting per heat
```
**Pros**: Graceful, no hard caps. **Cons**: Needs tuning.

### 3. Conditional Integration
Only accumulate integral when the error is small (within a band). Large errors don't pile up.
```
if abs(error) < threshold:
    integral += error
```
**Pros**: Prevents windup during big transitions. **Cons**: Another constant.

### 4. Reset on Stage Change
When the allocator picks a new stage, reset its integral to zero.
**Pros**: Clean. **Cons**: Loses useful history.

## Recommendation: Integral Decay

Use exponential decay with factor 0.85:
```
integral = integral * 0.85 + error
```

This means:
- After 5 heats, old error is at 0.85^5 = 0.44 of original (more than halved)
- After 10 heats, at 0.85^10 = 0.20 (80% forgotten)
- Recent errors still have full weight
- No hard caps or arbitrary thresholds

Combined with a clamp at ±0.5 for safety (softened from ±1.0 in heat 51 to prevent recovery traps).

## Impact on Current State

With decay applied retroactively, research integral would drop from 1.249 to ~0.5, making the scores more balanced and letting testing/editing win when they should.

## Implementation

One line change in `protocol/allocator.md`:
```
integral = state.allocator.integral[stage] * 0.85 + error
# Clamp to [-1.0, 1.0]
```
