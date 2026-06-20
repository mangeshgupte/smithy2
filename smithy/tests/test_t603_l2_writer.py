"""t-603 (ini-019 P1.3): the end-heat L2 snapshot writer hook.

Covers the durable upsert primitive (idempotent keyed by heat, heat-sorted) and
the _emit_l2_snapshot plumbing (load → build → write) against a seeded temp
project. The pure aggregation itself is covered by test_metrics.py.
"""

import json
import subprocess

import pytest

from smithy import cli
from smithy.state import VALID_STAGES


def test_upsert_l2_row_idempotent_and_sorted(tmp_path):
    p = tmp_path / "l2-snapshots.jsonl"
    cli._upsert_l2_row(p, {"heat": 6, "tag": "b"})
    cli._upsert_l2_row(p, {"heat": 5, "tag": "a"})
    # re-write heat 5 — must overwrite, not duplicate
    n = cli._upsert_l2_row(p, {"heat": 5, "tag": "a2"})
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert n == 2 and len(rows) == 2
    assert [r["heat"] for r in rows] == [5, 6]          # heat-sorted
    assert next(r for r in rows if r["heat"] == 5)["tag"] == "a2"


def test_upsert_l2_row_skips_malformed_lines(tmp_path):
    p = tmp_path / "l2-snapshots.jsonl"
    p.write_text('{"heat": 1, "ok": true}\nnot json\n\n')
    cli._upsert_l2_row(p, {"heat": 2})
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [r["heat"] for r in rows] == [1, 2]          # bad line dropped


def _seed_project(tmp_path):
    state = {
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-10T00:00:00Z"},
        "overall_progress": 0.3,
        "stages": {s: {"target": 0.16, "heats": 2, "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": [{"id": "t-1", "status": "complete", "initiative_id": "ini-A"}],
        "initiatives": [{"id": "ini-A", "title": "A", "budget_cap": 10,
                         "heats_used": 1, "parallelism": "parallel"}],
        "parallel": {"max_forges": 1,
                     "forges": [{"id": "forge-quench", "status": "idle",
                                 "last_heartbeat": "2026-06-01T00:00:00Z"}]},
        "next_tasks": [],
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-06-01T00:00:00Z\t10\timplementation\tt-1\tsubmitted\t0.8\t🟢\tdid\tforge-quench\n"
    )
    (tmp_path / "rig-events.jsonl").write_text("")
    (tmp_path / "assembly-log.jsonl").write_text("")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


def test_emit_l2_snapshot_writes_valid_row(tmp_path):
    _seed_project(tmp_path)
    status = cli._emit_l2_snapshot(tmp_path, heat=10,
                                   generated_at="2026-06-01T00:00:00Z")
    assert status == {"written": True, "rows": 1}
    path = cli.l2_snapshots_path(tmp_path)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    snap = rows[0]
    assert snap["heat"] == 10
    assert snap["schema_version"] == "ini-019/l2/v1"
    assert snap["generated_at"] == "2026-06-01T00:00:00Z"
    # the section keys are present (full §3.2 shape from metrics)
    for key in ["budget", "stages", "forges", "issues", "queue", "gaps"]:
        assert key in snap


def test_emit_l2_snapshot_idempotent_by_heat(tmp_path):
    _seed_project(tmp_path)
    cli._emit_l2_snapshot(tmp_path, heat=10, generated_at="2026-06-01T00:00:00Z")
    cli._emit_l2_snapshot(tmp_path, heat=10, generated_at="2026-06-02T00:00:00Z")
    path = cli.l2_snapshots_path(tmp_path)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1                                # overwritten, not appended
    assert rows[0]["generated_at"] == "2026-06-02T00:00:00Z"


def test_emit_l2_snapshot_best_effort_on_bad_state(tmp_path, monkeypatch):
    """A metrics/build failure must not raise into end-heat — it returns a
    status dict so the heat close still succeeds."""
    _seed_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("synthetic build failure")

    monkeypatch.setattr("smithy.metrics.build_l2_snapshot", boom)
    status = cli._emit_l2_snapshot(tmp_path, heat=10)
    assert status["written"] is False
    assert "synthetic build failure" in status["error"]
    # nothing written on failure
    assert not cli.l2_snapshots_path(tmp_path).exists()
