"""t-601 (ini-019 P1.1): unit tests for the pure metrics aggregation module.

One coherent fixture (two registered forges + a pre-t-409 legacy row + a thrash
task that rejects twice then merges) drives targeted per-section assertions,
plus parser, percentile, and end-to-end-shape coverage. Every metric is a pure
function of the fixture records — no file I/O.
"""

from datetime import datetime, timedelta, timezone

import pytest

from smithy import metrics


BASE = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso(offset_s):
    """ISO-8601 (Z-suffixed) at BASE + offset seconds — exercises the Py3.9
    Z-handling path in _parse_ts."""
    return (BASE + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

WORKLOG_TSV = "\t".join(metrics.WORKLOG_COLUMNS[:8]) + "\n" + "\n".join([
    # t-1: forge-quench impl, submitted then merged
    f"{iso(60)}\t10\timplementation\tt-1\tsubmitted\t0.8\t🟢\tdid t-1\tforge-quench",
    f"{iso(90)}\t10\timplementation\tt-1\tmerged\t0.0\t✅\tmerge sha=abc\tforge-quench",
    # t-2: forge-quench testing, low-value (zero-value heat), in flight
    f"{iso(230)}\t11\ttesting\tt-2\tsubmitted\t0.15\t🔴\tstuck\tforge-quench",
    # t-9: forge-temper impl thrash — two reject rows then submit+merge
    f"{iso(330)}\t12\timplementation\tt-9\trejected\t0.0\t🚫\treject1\tforge-temper",
    f"{iso(430)}\t13\timplementation\tt-9\trejected\t0.0\t🚫\treject2\tforge-temper",
    f"{iso(560)}\t14\timplementation\tt-9\tsubmitted\t0.6\t🟡\tfinally\tforge-temper",
    f"{iso(600)}\t14\timplementation\tt-9\tmerged\t0.0\t✅\tmerge sha=def\tforge-temper",
    # legacy: no trailing forge_id column (pre-t-409)
    "2026-05-01T00:00:00Z\t1\tresearch\tt-old\tsubmitted\t0.7\t🟢\tlegacy work",
])


def _rig_events():
    return [
        # t-1 full life
        {"event": "queue_push", "task_id": "t-1", "ts": iso(0), "queue_size": 1},
        {"event": "queue_pop", "task_id": "t-1", "ts": iso(10), "forge_id": "forge-quench"},
        {"event": "forge_started", "task_id": "t-1", "ts": iso(10), "heat": 10,
         "forge_id": "forge-quench", "stage": "implementation"},
        {"event": "forge_ended_submitted", "task_id": "t-1", "ts": iso(60), "heat": 10,
         "forge_id": "forge-quench", "stage": "implementation", "value": 0.8},
        {"event": "assembly_tick_merged", "task_id": "t-1", "ts": iso(90),
         "forge_id": "forge-quench", "latency_ms": 40},
        # t-2 in flight (started+ended, no merge)
        {"event": "queue_push", "task_id": "t-2", "ts": iso(20), "queue_size": 2},
        {"event": "queue_pop", "task_id": "t-2", "ts": iso(25), "forge_id": "forge-quench"},
        {"event": "forge_started", "task_id": "t-2", "ts": iso(200), "heat": 11,
         "forge_id": "forge-quench", "stage": "testing"},
        {"event": "forge_ended_submitted", "task_id": "t-2", "ts": iso(230), "heat": 11,
         "forge_id": "forge-quench", "stage": "testing", "value": 0.15},
        # t-9 thrash: 3 starts (forge-temper), 2 rejects, 1 merge, 3 pushes
        {"event": "queue_push", "task_id": "t-9", "ts": iso(30), "queue_size": 1},
        {"event": "forge_started", "task_id": "t-9", "ts": iso(300), "heat": 12,
         "forge_id": "forge-temper", "stage": "implementation"},
        {"event": "assembly_tick_rejected", "task_id": "t-9", "ts": iso(330),
         "forge_id": "forge-temper", "latency_ms": 10, "reason": "tests failed"},
        {"event": "queue_push", "task_id": "t-9", "ts": iso(340), "queue_size": 1},
        {"event": "forge_started", "task_id": "t-9", "ts": iso(400), "heat": 13,
         "forge_id": "forge-temper", "stage": "implementation"},
        {"event": "assembly_tick_rejected", "task_id": "t-9", "ts": iso(430),
         "forge_id": "forge-temper", "latency_ms": 12, "reason": "tests failed"},
        {"event": "queue_push", "task_id": "t-9", "ts": iso(440), "queue_size": 1},
        {"event": "forge_started", "task_id": "t-9", "ts": iso(500), "heat": 14,
         "forge_id": "forge-temper", "stage": "implementation"},
        {"event": "forge_ended_submitted", "task_id": "t-9", "ts": iso(560), "heat": 14,
         "forge_id": "forge-temper", "stage": "implementation", "value": 0.6},
        {"event": "assembly_tick_merged", "task_id": "t-9", "ts": iso(600),
         "forge_id": "forge-temper", "latency_ms": 55},
        # t-3 pushed, never popped
        {"event": "queue_push", "task_id": "t-3", "ts": iso(50), "queue_size": 3},
        # reprioritisation + a stall + a ghost
        {"event": "queue_set", "task_ids": ["t-3"], "ts": iso(70), "count": 1},
        {"event": "assembly_push_ok", "task_id": "t-7", "ts": iso(80), "forge_id": "forge-quench"},
        {"event": "forge_ended_submitted", "task_id": "t-8", "ts": iso(85), "heat": 9,
         "forge_id": "forge-quench", "stage": "editing", "value": 0.5},
    ]


def _assembly_rows():
    return [
        {"ts": iso(90), "forge_id": "forge-quench", "task_id": "t-1",
         "outcome": "merged", "detail": "ok"},
        {"ts": iso(330), "forge_id": "forge-temper", "task_id": "t-9",
         "outcome": "rejected", "detail": "tests failed: FAILED tests/test_foo.py::test_bar"},
        {"ts": iso(430), "forge_id": "forge-temper", "task_id": "t-9",
         "outcome": "rejected", "detail": "tests failed: FAILED tests/test_foo.py::test_bar"},
        {"ts": iso(600), "forge_id": "forge-temper", "task_id": "t-9",
         "outcome": "merged", "detail": "ok"},
        {"ts": iso(120), "forge_id": "forge-quench", "task_id": "t-5",
         "outcome": "rejected", "detail": "rebase error: You have unstaged changes."},
        {"ts": iso(130), "forge_id": "forge-anneal", "task_id": "t-6",
         "outcome": "rejected", "detail": "no new commits on branch"},
    ]


def _state():
    return {
        "budget": {"total_heats": 100, "used": 80, "started_at": iso(0)},
        "overall_progress": 0.5,
        "stages": {
            "research": {"target": 0.07, "heats": 5, "value_ema": 0.70},
            "planning": {"target": 0.05, "heats": 3, "value_ema": 0.70},
            "implementation": {"target": 0.40, "heats": 50, "value_ema": 0.75},
            "testing": {"target": 0.15, "heats": 20, "value_ema": 0.72},
            "editing": {"target": 0.20, "heats": 15, "value_ema": 0.71},
            "marketing": {"target": 0.08, "heats": 7, "value_ema": 0.77},
        },
        "allocator": {"integral": {"research": 0.1, "implementation": -0.2,
                                   "testing": 0.0, "planning": 0.0,
                                   "editing": 0.0, "marketing": 0.0}},
        "parallel": {
            "max_forges": 3, "halt_flag": False,
            "forges": [
                {"id": "forge-quench", "status": "busy", "current_task": "t-2",
                 "current_heat": 11, "last_heartbeat": iso(550)},
                {"id": "forge-temper", "status": "idle", "current_task": None,
                 "current_heat": None, "last_heartbeat": iso(600)},
                {"id": "forge-anneal", "status": "idle", "current_task": None,
                 "current_heat": None, "last_heartbeat": iso(300)},
            ],
        },
        "queue": [
            {"id": "t-1", "status": "complete", "initiative_id": "ini-A",
             "assigned_forge": "forge-quench"},
            {"id": "t-2", "status": "in_progress", "initiative_id": "ini-A",
             "assigned_forge": "forge-quench"},
            {"id": "t-9", "status": "complete", "initiative_id": "ini-B",
             "assigned_forge": "forge-temper"},
            {"id": "t-4", "status": "in_progress", "initiative_id": "ini-B",
             "assigned_forge": "forge-temper"},
            {"id": "t-3", "status": "pending", "initiative_id": None},
        ],
        "initiatives": [
            {"id": "ini-A", "title": "Alpha", "budget_cap": 10, "heats_used": 5,
             "parallelism": "parallel"},
            {"id": "ini-B", "title": "Beta", "budget_cap": 8, "heats_used": 4,
             "parallelism": "serial"},
        ],
        "next_tasks": ["t-3"],
    }


@pytest.fixture
def records():
    return {
        "worklog": metrics.parse_worklog(WORKLOG_TSV.splitlines()),
        "rig": _rig_events(),
        "assembly": _assembly_rows(),
        "state": _state(),
    }


# --------------------------------------------------------------------------- #
# Parsers + primitives                                                         #
# --------------------------------------------------------------------------- #

def test_parse_worklog_columns_and_coercion(records):
    rows = records["worklog"]
    assert len(rows) == 8                       # header skipped
    r0 = rows[0]
    assert r0["task_id"] == "t-1" and r0["heat"] == 10 and r0["value"] == 0.8
    assert r0["forge_id"] == "forge-quench"
    legacy = rows[-1]
    assert legacy["task_id"] == "t-old" and legacy["forge_id"] is None


def test_parse_jsonl_skips_blank_and_bad():
    out = metrics.parse_jsonl(['{"a": 1}', "", "  ", "not json", '{"b": 2}'])
    assert out == [{"a": 1}, {"b": 2}]


def test_parse_ts_handles_z_and_offset():
    a = metrics._parse_ts("2026-06-01T00:00:10Z")
    b = metrics._parse_ts("2026-06-01T00:00:00+00:00")
    assert a is not None and b is not None and round(a - b, 0) == 10
    assert metrics._parse_ts(None) is None
    assert metrics._parse_ts("garbage") is None


def test_percentiles_basic():
    p = metrics._percentiles([10, 20, 30, 40], ndigits=1)
    assert p["n"] == 4 and p["p50"] == 25.0
    empty = metrics._percentiles([])
    assert empty == {"p50": None, "p90": None, "p99": None, "n": 0}


# --------------------------------------------------------------------------- #
# Sections                                                                     #
# --------------------------------------------------------------------------- #

def test_budget_section(records):
    b = metrics.budget_section(records["state"])
    assert b == {"used": 80, "total": 100, "pct": 0.8, "overall_progress": 0.5}


def test_stages_section_share_and_drift(records):
    s = metrics.stages_section(records["state"])
    impl = s["implementation"]
    assert impl["heats"] == 50 and impl["share"] == 0.5
    assert impl["target_share"] == 0.40 and impl["drift"] == 0.1
    assert impl["value_ema"] == 0.75 and impl["integral"] == -0.2


def test_forges_section_signals_meanvalue_and_legacy(records):
    forges = metrics.forges_section(
        records["worklog"], records["rig"], records["assembly"],
        records["state"], 1, 14, now_ts=metrics._parse_ts(iso(700)))
    by_id = {f["id"]: f for f in forges}
    assert "legacy" in by_id                       # H.1 bucket, never dropped
    q = by_id["forge-quench"]
    impl = q["by_stage"]["implementation"]
    assert impl["heats"] == 1 and impl["mean_value"] == 0.8
    assert impl["signals"] == {"green": 1, "yellow": 0, "red": 0, "reject": 0}
    # 🔴 testing row for forge-quench
    assert q["by_stage"]["testing"]["signals"]["red"] == 1
    # forge-quench idle: busy (50+30)=80 over span 220 → 1-80/220
    assert q["idle_pct"] == 0.636
    assert q["last_heartbeat_age_s"] == 150       # 700 - 550
    # forge-temper: 2 rejects of 3 assembly rows → rejection_share 2/3
    t = by_id["forge-temper"]
    assert t["rejection_share"] == 0.667
    assert t["by_stage"]["implementation"]["signals"]["reject"] == 2


def test_forges_window_subset(records):
    # restrict to heats 11..14 → forge-quench keeps only the testing row
    forges = metrics.forges_section(
        records["worklog"], records["rig"], records["assembly"],
        records["state"], 11, 14)
    q = {f["id"]: f for f in forges}["forge-quench"]
    assert q["heats_total"] == 2 and q["heats_window"] == 1


def test_initiatives_section(records):
    inis = metrics.initiatives_section(
        records["state"], records["rig"], records["assembly"])
    by_id = {i["id"]: i for i in inis}
    assert by_id["ini-A"]["tasks_total"] == 2
    assert by_id["ini-A"]["tasks_in_flight"] == 1          # t-2
    assert by_id["ini-A"]["success_rate"] == 1.0
    assert by_id["ini-B"]["thrash_count"] == 1             # t-9
    assert by_id["ini-B"]["parallelism_declared"] == "serial"
    assert by_id["ini-B"]["cycle_time_median_s"] == 570.0  # merged600 - push30
    assert "unknown" in by_id and by_id["unknown"]["tasks_total"] == 1


def test_lifecycle_section(records):
    lc = metrics.lifecycle_section(records["rig"])
    assert lc["queue_wait"]["n"] == 2                      # t-1, t-2
    assert lc["in_flight"]["n"] == 3                       # t-1, t-2, t-9 h14
    assert lc["merge_latency_ms"]["n"] == 2
    assert lc["merge_latency_ms"]["p50"] in (40, 47.5, 48)  # 40 & 55
    assert lc["lead_time_s"]["n"] == 2                     # t-1 (90), t-9 (570)


def test_issues_section(records):
    iss = metrics.issues_section(
        records["worklog"], records["rig"], records["assembly"], records["state"])
    assert iss["ghost_submits"] == {"count": 1, "task_ids": ["t-8"]}
    assert iss["thrash"]["task_ids"] == ["t-9"]
    assert iss["stalls"] == {"count": 1, "task_ids": ["t-7"]}
    assert iss["rejections"]["total"] == 4
    assert iss["rejections"]["by_reason"]["tests-failed"] == 2
    assert iss["rejections"]["by_reason"]["rebase-conflict"] == 1
    assert iss["rejections"]["by_reason"]["no-commits"] == 1
    assert iss["rejections"]["by_forge"]["forge-temper"] == 2
    assert iss["repeat_tests"]["count"] == 1
    assert iss["repeat_tests"]["nodes"][0]["hits"] == 2
    assert iss["zero_value_heats"] == {"count": 1, "heat_ids": [11]}
    assert iss["orphans_reaped"] == {"count": 1, "task_ids": ["t-4"]}  # B13


def test_queue_section(records):
    q = metrics.queue_section(records["rig"], records["state"])
    assert q["depth_current"] == 1                         # next_tasks
    assert q["push_count_window"] == 6                     # t-1,t-2,t-9x3,t-3
    assert q["pop_count_window"] == 2
    assert q["set_events_window"] == 1


def test_thrash_detail_section(records):
    td = metrics.thrash_detail_section(records["rig"], records["assembly"])
    assert len(td) == 1
    row = td[0]
    assert row["task_id"] == "t-9"
    assert row["attempts"] == 3 and row["rejections"] == 2
    assert row["requeues"] == 2                            # 3 pushes - 1
    assert row["forges"] == ["forge-temper"]
    assert row["stages"] == ["implementation"] * 3
    assert row["time_to_green_s"] == 170.0                 # merge600 - lastReject430


def test_gaps_section(records):
    g = metrics.gaps_section(records["worklog"], records["state"])
    assert g["legacy_forge_rows"] == 1
    assert g["unbacked_initiatives"] == 1                  # t-3
    assert g["tool_activity_missing"] is True
    assert g["human_steering_blind"] is True


def test_classify_rejection():
    assert metrics.classify_rejection("tests failed: FAILED x::y") == "tests-failed"
    assert metrics.classify_rejection("rebase error: unstaged changes") == "rebase-conflict"
    assert metrics.classify_rejection("no new commits") == "no-commits"
    assert metrics.classify_rejection("not a fast-forward push") == "non-ff"
    assert metrics.classify_rejection("weird") == "other"
    assert metrics.classify_rejection(None) == "other"


# --------------------------------------------------------------------------- #
# Assembler                                                                    #
# --------------------------------------------------------------------------- #

def test_build_l2_snapshot_shape(records):
    snap = metrics.build_l2_snapshot(
        heat=14, generated_at=iso(700),
        worklog_rows=records["worklog"], rig_events=records["rig"],
        assembly_rows=records["assembly"], state=records["state"])
    # every §3.2 top-level key present
    for key in ["schema_version", "heat", "generated_at", "window", "budget",
                "stages", "forges", "initiatives", "lifecycle", "issues",
                "queue", "thrash_detail", "gaps"]:
        assert key in snap, f"missing {key}"
    assert snap["schema_version"] == "ini-019/l2/v1"
    assert snap["heat"] == 14
    assert snap["window"] == {"from_heat": 1, "to_heat": 14}
    assert isinstance(snap["forges"], list) and isinstance(snap["stages"], dict)
    # JSON-serialisable (drop-in pandas / JSONL)
    import json
    json.loads(json.dumps(snap))


def test_build_l2_snapshot_empty_records():
    """Degenerate input must not raise — empty logs + minimal state."""
    snap = metrics.build_l2_snapshot(
        heat=0, generated_at=iso(0), worklog_rows=[], rig_events=[],
        assembly_rows=[], state={"budget": {}, "stages": {}, "queue": [],
                                 "initiatives": [], "parallel": {"forges": []}})
    assert snap["budget"]["pct"] is None
    assert snap["forges"] == [] and snap["initiatives"] == []
    assert snap["issues"]["rejections"]["total"] == 0
