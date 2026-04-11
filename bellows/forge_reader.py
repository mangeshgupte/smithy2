"""Read Forge project state from flat files."""

import json
import csv
import re
from pathlib import Path
from datetime import datetime, timezone


def _find_bottleneck(stages: dict) -> str:
    """Find the stage with lowest progress (the bottleneck)."""
    bottleneck = None
    min_progress = 1.0
    for sname, sdata in stages.items():
        prog = sdata.get("progress", 0)
        if prog < min_progress and sdata.get("heats", 0) > 0:
            min_progress = prog
            bottleneck = sname
    return bottleneck


def read_project(project_dir: str) -> dict:
    """Read all state from a Forge project directory."""
    p = Path(project_dir)
    if not (p / "state.json").exists():
        return None

    state = json.loads((p / "state.json").read_text())

    # Read recent worklog entries
    worklog = []
    worklog_path = p / "worklog.tsv"
    if worklog_path.exists():
        with open(worklog_path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                worklog.append(row)

    # Read outbox for decisions/updates
    outbox_text = ""
    if (p / "outbox.md").exists():
        outbox_text = (p / "outbox.md").read_text()

    # Read inbox for pending items
    inbox_text = ""
    if (p / "inbox.md").exists():
        inbox_text = (p / "inbox.md").read_text()

    # Read strategy for what's missing
    strategy_text = ""
    if (p / "STRATEGY.md").exists():
        strategy_text = (p / "STRATEGY.md").read_text()

    # Read identity for commander's intent
    identity_text = ""
    intent = ""
    if (p / "identity.md").exists():
        identity_text = (p / "identity.md").read_text()
        # Extract intent from ## Commander's Intent section
        in_intent = False
        intent_lines = []
        for line in identity_text.split("\n"):
            if "Commander's Intent" in line:
                in_intent = True
                continue
            if in_intent and line.startswith("## "):
                break
            if in_intent and line.strip():
                intent_lines.append(line.strip())
        intent = " ".join(intent_lines[:3]) if intent_lines else ""

    # Extract what's missing section
    whats_missing = []
    if "What's Missing" in strategy_text:
        in_section = False
        for line in strategy_text.split("\n"):
            if "What's Missing" in line:
                in_section = True
                continue
            if in_section and line.startswith("##"):
                break
            if in_section and line.startswith("- "):
                whats_missing.append(line[2:].strip())

    # Compute project signal (worst signal across recent heats)
    recent_heats = worklog[-5:] if worklog else []
    signal = "green"
    for h in recent_heats:
        s = h.get("signal", "🟢")
        if "🔴" in s:
            signal = "red"
            break
        elif "🟡" in s:
            signal = "yellow"

    # Pending decisions (from queue — priority 0, 1, or 2)
    decisions = []
    for task in state.get("queue", []):
        if task["status"] == "pending" and task.get("priority", 3) <= 2:
            decisions.append({
                "id": task["id"],
                "question": task["desc"],
                "priority": task.get("priority", 2),
                "stage": task["stage"],
            })
    decisions.sort(key=lambda d: d["priority"])

    # Classify notification tier for each decision
    for d in decisions:
        prio = d["priority"]
        if prio <= 1:
            d["tier"] = "push"       # Blocking now — needs immediate attention
            d["tier_label"] = "Needs attention"
        elif prio == 2:
            d["tier"] = "quiet"      # Will block soon — can wait for next check-in
            d["tier_label"] = "When you're ready"
        else:
            d["tier"] = "in-app"     # Nice to know — only visible in-app
            d["tier_label"] = "FYI"

    # Current activity and last active time
    current_activity = ""
    last_active = None
    if worklog:
        last = worklog[-1]
        current_activity = (last.get("notes") or "").split(". Could improve")[0]
        last_active = last.get("timestamp", "")[:16]  # YYYY-MM-DDTHH:MM

    # Group heats by day for activity feed
    days = {}
    for h in worklog:
        ts = h.get("timestamp", "")
        day = ts[:10] if len(ts) >= 10 else "unknown"
        if day not in days:
            days[day] = []
        days[day].append(h)

    # Build day summaries (sorted newest first)
    heat_days = []
    sorted_day_keys = sorted(days.keys(), reverse=True)
    for i, day in enumerate(sorted_day_keys):
        day_heats = days[day]
        stages_used = {}
        signals = {"🟢": 0, "🟡": 0, "🔴": 0}
        for h in day_heats:
            st = h.get("stage", "?")
            stages_used[st] = stages_used.get(st, 0) + 1
            sig = h.get("signal", "🟢")
            for s in signals:
                if s in sig:
                    signals[s] += 1
        summary = f"{len(day_heats)} heats: " + ", ".join(
            f"{s}×{c}" for s, c in sorted(stages_used.items(), key=lambda x: -x[1])
        )
        heat_days.append({
            "date": day,
            "heats": day_heats,
            "count": len(day_heats),
            "summary": summary,
            "signals": signals,
            "is_recent": i < 2,  # Show individual heats for last 2 days
        })

    return {
        "name": state.get("project", p.name),
        "dir": str(p),
        "signal": signal,
        "overall_progress": state.get("overall_progress", 0),
        "budget": state.get("budget", {}),
        "stages": state.get("stages", {}),
        "recent_heats": recent_heats[-10:],
        "heat_days": heat_days,
        "decisions": decisions,
        "whats_missing": whats_missing[:5],
        "current_activity": current_activity,
        "last_active": last_active,
        "bottleneck": _find_bottleneck(state.get("stages", {})),
        "queue": state.get("queue", []),
        "themes": state.get("themes", []),
        "initiatives": state.get("initiatives", []),
        "intent": intent,
    }


def discover_projects(base_dir: str) -> list[dict]:
    """Find all Forge projects under a base directory."""
    base = Path(base_dir)
    projects = []

    # Check immediate children and known locations
    candidates = list(base.iterdir()) if base.is_dir() else []

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "state.json").exists():
            project = read_project(str(candidate))
            if project:
                projects.append(project)

    # Sort: red first, then yellow, then green. Within each, most active first.
    signal_order = {"red": 0, "yellow": 1, "green": 2}
    projects.sort(key=lambda p: (
        signal_order.get(p["signal"], 2),
        -p["budget"].get("used", 0),
    ))

    return projects


def get_morning_briefing(projects: list[dict]) -> dict:
    """Generate morning briefing data from all projects."""
    needs_you = []
    progress = []
    notable = []

    total_heats = 0
    for p in projects:
        total_heats += p["budget"].get("used", 0)

        # Needs you: pending decisions
        if p["decisions"]:
            needs_you.append({
                "project": p["name"],
                "count": len(p["decisions"]),
                "signal": p["signal"],
            })

        # Progress: show progress percentage
        prog = p["overall_progress"]
        if prog > 0:
            progress.append({
                "project": p["name"],
                "progress": prog,
                "heats": p["budget"].get("used", 0),
            })

        # Notable: any yellow/red signals
        if p["signal"] == "yellow" or p["signal"] == "red":
            notable.append({
                "project": p["name"],
                "signal": p["signal"],
                "activity": p["current_activity"],
            })

    # Notification tier counts
    all_decisions = []
    for p in projects:
        all_decisions.extend(p.get("decisions", []))
    tier_counts = {
        "push": sum(1 for d in all_decisions if d.get("tier") == "push"),
        "quiet": sum(1 for d in all_decisions if d.get("tier") == "quiet"),
        "in_app": sum(1 for d in all_decisions if d.get("tier") == "in-app"),
    }

    return {
        "project_count": len(projects),
        "total_heats": total_heats,
        "needs_you": needs_you,
        "progress": sorted(progress, key=lambda x: -x["progress"]),
        "notable": notable,
        "tier_counts": tier_counts,
    }
