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


def score_stages(stages: dict, integrals: dict, human_priorities: list, queue: list, initiatives: list = None, constraints: list = None) -> dict:
    """Score each stage using PI controller + bonuses."""
    benefits = compute_benefits(stages)
    targets = compute_targets(benefits)
    total_heats = sum(s.get("heats", 0) for s in stages.values()) or 1

    # Build constraint overrides
    capped_stages = set()  # stages that have hit their budget cap
    floor_stages = {}  # stages that need a boost to meet floor
    if constraints:
        for c in constraints:
            if c.get("status") != "active":
                continue
            if c["type"] == "budget_cap" and c.get("stage"):
                stage_heats = stages.get(c["stage"], {}).get("heats", 0)
                if stage_heats >= c.get("value", 999):
                    capped_stages.add(c["stage"])
            elif c["type"] == "floor" and c.get("stage"):
                floor_pct = c.get("value", 0)
                actual_pct = stages.get(c["stage"], {}).get("heats", 0) / total_heats * 100
                if actual_pct < floor_pct:
                    floor_stages[c["stage"]] = floor_pct - actual_pct

    # Build set of active/approved initiative IDs for gating
    active_ini_ids = set()
    if initiatives:
        active_ini_ids = {i["id"] for i in initiatives if i.get("status") in ("approved", "active")}

    # Filter queue: exclude tasks linked to non-active initiatives
    def _task_eligible(task):
        ini_id = task.get("initiative_id")
        if ini_id is None:
            return True  # standalone task
        return ini_id in active_ini_ids

    eligible_queue = [t for t in queue if _task_eligible(t)]

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

    # Unblocking override (uses eligible queue only)
    for task in eligible_queue:
        if task["status"] == "pending":
            for blocked_id in task.get("blocked_by", []):
                for t2 in eligible_queue:
                    if t2["id"] == blocked_id and t2["status"] == "pending":
                        scores[t2["stage"]] = scores.get(t2["stage"], 0) + 0.3

    # Queued task bonus (uses eligible queue only)
    for stage in VALID_STAGES:
        pending_in_stage = sum(1 for t in eligible_queue if t["stage"] == stage and t["status"] == "pending")
        scores[stage] = scores.get(stage, 0) + pending_in_stage * 0.07

    # Apply constraint overrides
    for stage in capped_stages:
        scores[stage] = -1.0  # suppress capped stages

    for stage, deficit in floor_stages.items():
        scores[stage] = scores.get(stage, 0) + deficit * 0.05  # boost underfunded stages

    return scores, targets, new_integrals


def pick_stage(scores: dict, heat_number: int) -> str:
    """Pick stage — highest score, or second-highest every 5th heat."""
    sorted_stages = sorted(scores.items(), key=lambda x: -x[1])
    if heat_number % 5 == 0 and len(sorted_stages) > 1:
        return sorted_stages[1][0]  # Exploration
    return sorted_stages[0][0]
