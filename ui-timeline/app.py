"""Timeline View — Gantt-style visual budget allocation."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
try:
    from steering_log import read_steering_log
except ImportError:
    def read_steering_log(*args, **kwargs):
        return []
try:
    from smithy.activity import read_activity
except ImportError:
    def read_activity(*args, **kwargs):
        return []

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import StreamingResponse

app = FastAPI(title="Timeline View")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STATE_DIR = os.environ.get("FORGE_PROJECT_DIR", str(Path(__file__).parent.parent))

NAV_LINKS = [
    ("🃏 Poker", os.environ.get("URL_POKER", "http://localhost:8001"), False),
    ("🎯 Intent", os.environ.get("URL_INTENT", "http://localhost:8003"), False),
    ("📅 Timeline", os.environ.get("URL_TIMELINE", "http://localhost:8004"), True),
    ("🔔 Bellows", os.environ.get("URL_BELLOWS", "http://localhost:8080"), False),
]


def _load_state():
    path = Path(STATE_DIR) / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(state):
    path = Path(STATE_DIR) / "state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")


class ConcurrentWriteError(Exception):
    """Another writer touched state.json between our load and save."""


def _load_state_with_mtime():
    path = Path(STATE_DIR) / "state.json"
    if not path.exists():
        return {}, 0.0
    return json.loads(path.read_text()), path.stat().st_mtime


def _save_state_checked(state, expected_mtime):
    path = Path(STATE_DIR) / "state.json"
    if path.exists() and path.stat().st_mtime - expected_mtime > 1e-6:
        raise ConcurrentWriteError("state.json changed since read")
    _save_state(state)


@app.exception_handler(ConcurrentWriteError)
async def _concurrent_write_handler(request, exc):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, start: int = None, end: int = None):
    state = _load_state()
    budget = state.get("budget", {})
    used = budget.get("used", 0)
    total = budget.get("total_heats", 0)

    initiatives = [
        i for i in state.get("initiatives", [])
        if i["status"] in ("approved", "active")
    ]

    themes = {th["id"]: th["name"] for th in state.get("themes", [])}

    # Count tasks per initiative
    task_counts = {}
    for t in state.get("queue", []):
        ini_id = t.get("initiative_id")
        if ini_id:
            if ini_id not in task_counts:
                task_counts[ini_id] = {"pending": 0, "complete": 0}
            if t["status"] == "complete":
                task_counts[ini_id]["complete"] += 1
            else:
                task_counts[ini_id]["pending"] += 1

    furthest_end = 0
    for ini in initiatives:
        ini["theme_name"] = themes.get(ini["theme_id"], "?")
        ini["task_pending"] = task_counts.get(ini["id"], {}).get("pending", 0)
        ini["task_complete"] = task_counts.get(ini["id"], {}).get("complete", 0)
        if "planned_start" not in ini:
            ini["planned_start"] = used
        if "planned_end" not in ini:
            ini["planned_end"] = ini["planned_start"] + (ini.get("budget_cap") or 10)
        furthest_end = max(furthest_end, ini.get("planned_end", 0))

    # Smart defaults for visible range
    if start is None:
        timeline_start = max(0, used - 20)
    else:
        timeline_start = start
    if end is None:
        timeline_end = used + max(50, (furthest_end - used) + 10)
    else:
        timeline_end = end

    # Clamp: never wider than 300h or narrower than 20h
    window = timeline_end - timeline_start
    if window < 20:
        timeline_end = timeline_start + 20
    elif window > 300:
        timeline_end = timeline_start + 300

    # Absolute bounds for the range slider (full project scope)
    abs_start = 0
    abs_end = max(total, furthest_end, used + 100)

    # Compute overlaps between initiatives
    overlaps = []
    for i, a in enumerate(initiatives):
        for b in initiatives[i+1:]:
            o_start = max(a["planned_start"], b["planned_start"])
            o_end = min(a["planned_end"], b["planned_end"])
            if o_start < o_end:
                overlaps.append({
                    "start": o_start, "end": o_end,
                    "a": a["title"][:20], "b": b["title"][:20],
                    "heats": o_end - o_start,
                })

    return templates.TemplateResponse(request=request, name="index.html", context={
        "initiatives": initiatives,
        "project": state.get("project", "unknown"),
        "used": used,
        "total": total,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "abs_start": abs_start,
        "abs_end": abs_end,
        "overlaps": overlaps,
        "nav_links": NAV_LINKS,
    })


@app.post("/update")
async def update_timeline(request: Request):
    data = await request.json()
    state, mtime = _load_state_with_mtime()

    for update in data.get("updates", []):
        ini_id = update["id"]
        for ini in state.get("initiatives", []):
            if ini["id"] == ini_id:
                ini["planned_start"] = update.get("start", ini.get("planned_start", 0))
                ini["planned_end"] = update.get("end", ini.get("planned_end", 0))
                break

    _save_state_checked(state, mtime)
    return JSONResponse({"ok": True})


@app.get("/api/state")
async def api_state():
    """Return initiative progress data for auto-refresh."""
    state = _load_state()
    data = {}
    for ini in state.get("initiatives", []):
        if ini["status"] in ("approved", "active"):
            data[ini["id"]] = {
                "heats_used": ini.get("heats_used", 0),
                "budget_cap": ini.get("budget_cap"),
                "status": ini["status"],
            }
    return JSONResponse(data)


@app.get("/api/steering-log")
async def api_steering_log(task_id: str = None, actor: str = None,
                           since: str = None, limit: int = 200):
    """Steering-log rows for this project, for Timeline's attribution lane.

    Newest-first. Each row carries a `heat` field — the Timeline renders a marker
    on the corresponding heat bar. Missing file = empty list (not an error).
    """
    rows = read_steering_log(STATE_DIR, task_id=task_id, actor=actor, since=since)
    rows.reverse()
    return JSONResponse({"count": len(rows), "rows": rows[:max(1, limit)]})


@app.get("/api/activity")
async def api_activity(limit: int = 20, since: str = None):
    """Unified activity stream — merged steering.log + worklog.tsv tails.

    See research/activity-side-panel-design.md for the entry schema.
    """
    entries = read_activity(STATE_DIR, limit=max(1, min(limit, 500)), since=since)
    return JSONResponse({"count": len(entries), "entries": entries})


@app.get("/api/current-heat")
async def api_current_heat():
    """Return the current heat (budget.used) for the now-indicator."""
    state = _load_state()
    budget = state.get("budget", {})
    return JSONResponse({
        "current_heat": budget.get("used", 0),
        "total_heats": budget.get("total_heats", 0),
    })


# t-520 (ini-012): rig-throughput metrics endpoint. Reads worklog.tsv,
# classifies each row's outcome (merged / rejected / partial), buckets
# by heat number and by wall-clock hour, and returns the shape the
# Timeline dashboard panel consumes. "complete" is the Forge-side
# outcome and is deliberately NOT counted here — merge/reject is what
# the Assembly pipeline records per task and that's the signal we want
# for throughput.

_METRIC_OUTCOMES = ("merged", "rejected", "partial")


def _parse_worklog_row(line: str):
    """Parse one worklog.tsv row into a dict with the fields we need.

    Returns None on header rows, blank lines, or malformed rows.
    Shape matches the file header: timestamp, heat, stage, task_id,
    outcome, value, signal, notes, forge_id? (t-409 trailing column).
    """
    if not line.strip() or line.startswith("timestamp\t"):
        return None
    parts = line.split("\t")
    if len(parts) < 5:
        return None
    ts_raw, heat_raw, _stage, task_id, outcome = parts[:5]
    try:
        heat = int(heat_raw)
    except ValueError:
        return None
    try:
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return {"ts": ts, "heat": heat, "task_id": task_id, "outcome": outcome}


@app.get("/api/metrics/heat-rates")
async def api_metrics_heat_rates(buckets: int = 10, bucket_size: int = 10):
    """t-520: bucketed + wall-clock throughput metrics for the dashboard.

    Query params:
      buckets     — how many heat buckets to return (default 10)
      bucket_size — heats per bucket (default 10)

    Response shape:
      {
        "buckets": [
          {"range": "890-899", "start": 890, "end": 899,
           "merged": N, "rejected": N, "partial": N,
           "ts_start": "ISO" | null, "ts_end": "ISO" | null},
          …
        ],
        "hourly": [
          {"hour_utc": "ISO", "merged": N, "rejected": N},
          …
        ],
        "summary": {
          "current_bucket":   {"merged": N, "rejected": N, "ratio": f | null},
          "last_24h":         {"merged": N, "rejected": N, "hourly_avg": f},
          "all_time":         {"merged": N, "rejected": N, "ratio": f | null},
        },
        "current_heat": N
      }

    Gaps in rig activity render as missing hour entries, not zeros — the
    client renders those as visible gaps in the line chart instead of
    interpolating across halts (per task spec).
    """
    from datetime import datetime, timedelta, timezone

    buckets = max(1, min(buckets, 200))
    bucket_size = max(1, min(bucket_size, 100))

    wl = Path(STATE_DIR) / "worklog.tsv"
    rows = []
    if wl.exists():
        try:
            for line in wl.read_text().splitlines():
                row = _parse_worklog_row(line)
                if row and row["outcome"] in _METRIC_OUTCOMES:
                    rows.append(row)
        except OSError:
            rows = []

    state = _load_state()
    current_heat = (state.get("budget") or {}).get("used", 0)

    # --- bucketed --------------------------------------------------
    #
    # Each bucket spans `bucket_size` heats; `buckets` buckets are
    # returned ending at the current heat (so the rightmost bucket
    # contains the most recent activity). Heats run low→high.
    if current_heat > 0:
        last_end = current_heat
    elif rows:
        last_end = max(r["heat"] for r in rows)
    else:
        last_end = 0

    bucket_rows = []
    for i in range(buckets - 1, -1, -1):
        # Rightmost bucket (i=0) ends at last_end; going back by
        # bucket_size per step.
        end = last_end - i * bucket_size
        start = end - bucket_size + 1
        if end <= 0:
            continue
        window = [r for r in rows if start <= r["heat"] <= end]
        bucket = {
            "range": f"{start}-{end}",
            "start": start,
            "end": end,
            "merged": sum(1 for r in window if r["outcome"] == "merged"),
            "rejected": sum(1 for r in window if r["outcome"] == "rejected"),
            "partial": sum(1 for r in window if r["outcome"] == "partial"),
            "ts_start": min((r["ts"] for r in window),
                            default=None).isoformat() if window else None,
            "ts_end": max((r["ts"] for r in window),
                          default=None).isoformat() if window else None,
        }
        bucket_rows.append(bucket)

    # --- hourly rates ---------------------------------------------
    #
    # Group rows by their UTC hour truncation. Only include hours that
    # have at least one row — letting the client render gaps naturally
    # instead of interpolating through rig halts.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    hourly_bins = {}
    for r in rows:
        if r["ts"] < cutoff:
            continue
        hour_key = r["ts"].replace(minute=0, second=0, microsecond=0)
        bin_ = hourly_bins.setdefault(hour_key,
                                      {"merged": 0, "rejected": 0})
        if r["outcome"] == "merged":
            bin_["merged"] += 1
        elif r["outcome"] == "rejected":
            bin_["rejected"] += 1
    hourly = [
        {"hour_utc": k.isoformat(),
         "merged": v["merged"], "rejected": v["rejected"]}
        for k, v in sorted(hourly_bins.items())
    ]

    # --- summary tiles ---------------------------------------------
    def _ratio(m, r):
        return round(m / (m + r), 3) if (m + r) > 0 else None

    current_bucket = bucket_rows[-1] if bucket_rows else {
        "merged": 0, "rejected": 0, "partial": 0,
    }
    last_24h_merged = sum(b["merged"] for b in hourly_bins.values())
    last_24h_rejected = sum(b["rejected"] for b in hourly_bins.values())
    hourly_avg = round(last_24h_merged / 24, 2) if last_24h_merged else 0.0

    all_time_merged = sum(1 for r in rows if r["outcome"] == "merged")
    all_time_rejected = sum(1 for r in rows if r["outcome"] == "rejected")

    summary = {
        "current_bucket": {
            "merged": current_bucket["merged"],
            "rejected": current_bucket["rejected"],
            "ratio": _ratio(current_bucket["merged"],
                            current_bucket["rejected"]),
        },
        "last_24h": {
            "merged": last_24h_merged,
            "rejected": last_24h_rejected,
            "hourly_avg": hourly_avg,
        },
        "all_time": {
            "merged": all_time_merged,
            "rejected": all_time_rejected,
            "ratio": _ratio(all_time_merged, all_time_rejected),
        },
    }

    return JSONResponse({
        "buckets": bucket_rows,
        "hourly": hourly,
        "summary": summary,
        "current_heat": current_heat,
    })


@app.get("/events")
async def events():
    """SSE endpoint — yields 'state-changed' when state.json is modified."""
    state_path = Path(STATE_DIR) / "state.json"

    async def event_stream():
        last_mtime = state_path.stat().st_mtime if state_path.exists() else 0
        while True:
            await asyncio.sleep(2)
            try:
                current_mtime = state_path.stat().st_mtime
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    yield f"event: state-changed\ndata: {{}}\n\n"
            except FileNotFoundError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
