"""Wavefront allocator — ported from protocol/allocator.md to Python."""

from .state import VALID_STAGES

# Dependency chain
PREREQS = {
    "research": None,
    "planning": "research",
    "implementation": "planning",
    "testing": "implementation",
    "editing": "implementation",
    "marketing": "editing",
}


def compute_benefits(stages: dict) -> dict:
    """Compute benefit per stage using wavefront model."""
    benefits = {}
    for stage in VALID_STAGES:
        prereq = PREREQS[stage]
        readiness = 1.0 if prereq is None else stages.get(prereq, {}).get("progress", 0)
        own_progress = stages.get(stage, {}).get("progress", 0)
        benefits[stage] = readiness * (1.0 - own_progress)
    return benefits


def compute_targets(benefits: dict) -> dict:
    """Normalize benefits to target fractions with 0.05 floor."""
    total = sum(benefits.values()) or 1
    targets = {s: max(0.05, b / total) for s, b in benefits.items()}
    # Renormalize
    t_total = sum(targets.values())
    return {s: round(v / t_total, 3) for s, v in targets.items()}


def score_stages(stages: dict, integrals: dict, human_priorities: list, queue: list) -> dict:
    """Score each stage using PI controller + bonuses."""
    benefits = compute_benefits(stages)
    targets = compute_targets(benefits)
    total_heats = sum(s.get("heats", 0) for s in stages.values()) or 1

    scores = {}
    new_integrals = {}

    for stage in VALID_STAGES:
        s = stages.get(stage, {})
        actual_frac = s.get("heats", 0) / total_heats
        target = targets[stage]
        error = target - actual_frac

        old_integral = integrals.get(stage, 0)
        integral = old_integral * 0.85 + error
        integral = max(-0.5, min(0.5, integral))
        new_integrals[stage] = round(integral, 3)

        value_bonus = s.get("value_ema", 0.5) * 0.3
        priority_boost = 2.0 if stage in human_priorities else 1.0

        score = (error + integral * 0.1 + value_bonus) * priority_boost
        scores[stage] = round(score, 4)

    # Unblocking override
    task_ids_by_stage = {}
    for task in queue:
        if task["status"] == "pending":
            stage = task["stage"]
            task_ids_by_stage.setdefault(stage, []).append(task["id"])

    for task in queue:
        if task["status"] == "pending":
            for blocked_id in task.get("blocked_by", []):
                # Find which stage has the blocking task
                for t2 in queue:
                    if t2["id"] == blocked_id and t2["status"] == "pending":
                        scores[t2["stage"]] = scores.get(t2["stage"], 0) + 0.3

    # Queued task bonus
    for stage in VALID_STAGES:
        pending_in_stage = sum(1 for t in queue if t["stage"] == stage and t["status"] == "pending")
        scores[stage] = scores.get(stage, 0) + pending_in_stage * 0.07

    return scores, targets, new_integrals


def pick_stage(scores: dict, heat_number: int) -> str:
    """Pick stage — highest score, or second-highest every 5th heat."""
    sorted_stages = sorted(scores.items(), key=lambda x: -x[1])
    if heat_number % 5 == 0 and len(sorted_stages) > 1:
        return sorted_stages[1][0]  # Exploration
    return sorted_stages[0][0]
