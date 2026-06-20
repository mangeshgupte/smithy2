"""t-606 (ini-019 P1.8): validate every emitted L2 row against the committed
JSON Schema (l2-snapshots.schema.json, Draft 2020-12, plan §3.2).

The L2 archive row (l2-snapshots.jsonl) and the `smithy report --json` payload
are both metrics.build_l2_snapshot output, so one schema governs both.

Validation uses a small dependency-free JSON-Schema-subset checker (supporting
exactly the keywords this schema uses: $ref/$defs, type, const, properties,
required, additionalProperties, items). That keeps the test runnable in any
venv — a hard `jsonschema` import would ImportError in the staging venv and a
collection error there aborts the whole gate. A separate test does a full
Draft-2020-12 validation when `jsonschema` happens to be installed.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from smithy import cli
from smithy.cli import cli as cli_root
from smithy.state import VALID_STAGES

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "l2-snapshots.schema.json"


# --- minimal JSON-Schema-subset validator --------------------------------

def _type_ok(inst, t):
    for tt in (t if isinstance(t, list) else [t]):
        if tt == "object" and isinstance(inst, dict):
            return True
        if tt == "array" and isinstance(inst, list):
            return True
        if tt == "string" and isinstance(inst, str):
            return True
        if tt == "boolean" and isinstance(inst, bool):
            return True
        if tt == "integer" and isinstance(inst, int) and not isinstance(inst, bool):
            return True
        if tt == "number" and isinstance(inst, (int, float)) and not isinstance(inst, bool):
            return True
        if tt == "null" and inst is None:
            return True
    return False


def _validate(inst, schema, root, path="$"):
    errs = []
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].split("/")[-1]]
    if "const" in schema and inst != schema["const"]:
        return [f"{path}: expected const {schema['const']!r}, got {inst!r}"]
    if "type" in schema and not _type_ok(inst, schema["type"]):
        return [f"{path}: expected type {schema['type']}, got {type(inst).__name__}"]
    if isinstance(inst, dict):
        for r in schema.get("required", []):
            if r not in inst:
                errs.append(f"{path}: missing required '{r}'")
        props = schema.get("properties", {})
        ap = schema.get("additionalProperties", True)
        for k, v in inst.items():
            if k in props:
                errs += _validate(v, props[k], root, f"{path}.{k}")
            elif ap is False:
                errs.append(f"{path}.{k}: additional property not allowed")
            elif isinstance(ap, dict):
                errs += _validate(v, ap, root, f"{path}.{k}")
    if isinstance(inst, list) and "items" in schema:
        for i, el in enumerate(inst):
            errs += _validate(el, schema["items"], root, f"{path}[{i}]")
    return errs


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


# --- fixture project + emitted row ----------------------------------------

def _state(used, *, legacy=False, unknown=False):
    stages = {s: {"target": round(1 / 6, 3), "heats": 0, "value_ema": 0.7}
              for s in VALID_STAGES}
    stages["implementation"]["heats"] = 2
    queue = [{"id": "t-001", "stage": "implementation", "status": "complete",
              "initiative_id": None if unknown else "ini-001",
              "assigned_forge": "forge-quench", "priority": 1, "blocked_by": []}]
    return {
        "project": "schema-fixture",
        "budget": {"total_heats": 100, "used": used,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": stages,
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "overall_progress": 0.42,
        "queue": queue,
        "next_tasks": [],
        "themes": [],
        "initiatives": [
            {"id": "ini-001", "title": "First", "status": "active",
             "heats_used": 2, "budget_cap": 10, "rank": 1},
        ],
        "parallel": {"forges": [
            {"id": "forge-quench", "status": "idle", "current_task": None,
             "current_heat": None, "last_heartbeat": "2026-04-10T01:00:00Z"},
        ]},
        "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [],
    }


def _worklog(legacy=False):
    rows = (
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        "2026-04-10T00:10:00Z\t1\timplementation\tt-001\tsubmitted\t0.8\t🟢\tw\tforge-quench\n"
        "2026-04-10T00:20:00Z\t2\timplementation\tt-001\tmerged\t0.0\t🟢\tm\tforge-quench\n"
    )
    if legacy:  # a pre-t-409 row with no forge_id → the "legacy" forge bucket
        rows += "2026-04-10T00:05:00Z\t1\tresearch\tt-000\tcomplete\t0.6\t🟢\told\t\n"
    return rows


def _make_project(tmp_path, used=2, legacy=False, unknown=False):
    (tmp_path / "state.json").write_text(json.dumps(_state(used, legacy=legacy,
                                                           unknown=unknown)))
    (tmp_path / "worklog.tsv").write_text(_worklog(legacy=legacy))
    (tmp_path / "rig-events.jsonl").write_text(
        json.dumps({"ts": "2026-04-10T00:20:00Z",
                    "event": "assembly_tick_merged", "task_id": "t-001"}) + "\n")
    (tmp_path / "assembly-log.jsonl").write_text(
        json.dumps({"ts": "2026-04-10T00:20:00Z", "forge_id": "forge-quench",
                    "task_id": "t-001", "outcome": "merged", "detail": None}) + "\n")
    return tmp_path


def _emit_and_read(tmp_path, heat):
    cli._emit_l2_snapshot(tmp_path, heat=heat, generated_at="2026-04-10T02:00:00Z")
    rows = [json.loads(ln) for ln in
            (tmp_path / "l2-snapshots.jsonl").read_text().splitlines()
            if ln.strip()]
    return next(r for r in rows if r["heat"] == heat)


# --- the schema artifact --------------------------------------------------


class TestSchemaArtifact:
    def test_schema_is_valid_json(self, schema):
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["properties"]["schema_version"]["const"] == "ini-019/l2/v1"

    def test_schema_top_level_required_matches_payload_keys(self, schema):
        # The schema's required top-level keys are exactly build_l2_snapshot's.
        from smithy import metrics
        snap = metrics.build_l2_snapshot(
            heat=1, generated_at="2026-04-10T00:00:00Z", worklog_rows=[],
            rig_events=[], assembly_rows=[],
            state=_state(1))
        assert set(schema["required"]) == set(snap.keys())


# --- emitted rows validate ------------------------------------------------


class TestEmittedRowsValidate:
    def test_emitted_l2_row_validates(self, tmp_path, schema):
        row = _emit_and_read(_make_project(tmp_path), heat=2)
        errs = _validate(row, schema, schema)
        assert errs == [], errs

    def test_report_json_payload_validates(self, tmp_path, schema):
        _make_project(tmp_path)
        r = CliRunner(mix_stderr=False).invoke(
            cli_root, ["--dir", str(tmp_path), "report", "--at-heat", "2",
                       "--json"])
        assert r.exit_code == 0, r.stderr
        payload = json.loads(r.stdout)
        payload.pop("surface", None)  # report-only marker, not in the archive
        errs = _validate(payload, schema, schema)
        assert errs == [], errs

    def test_legacy_forge_and_unknown_initiative_validate(self, tmp_path, schema):
        # The nullable buckets (legacy forge: null current_task/idle_pct;
        # unknown initiative: null title/budget_cap) must satisfy the schema.
        row = _emit_and_read(
            _make_project(tmp_path, legacy=True, unknown=True), heat=2)
        assert any(f["id"] == "legacy" for f in row["forges"])
        assert any(i["id"] == "unknown" for i in row["initiatives"])
        errs = _validate(row, schema, schema)
        assert errs == [], errs


# --- validator sanity (it actually rejects bad rows) ----------------------


class TestValidatorRejects:
    def test_missing_required_key(self, tmp_path, schema):
        row = _emit_and_read(_make_project(tmp_path), heat=2)
        del row["budget"]
        assert any("missing required 'budget'" in e
                   for e in _validate(row, schema, schema))

    def test_wrong_type(self, tmp_path, schema):
        row = _emit_and_read(_make_project(tmp_path), heat=2)
        row["heat"] = "two"  # should be integer
        assert any("$.heat" in e for e in _validate(row, schema, schema))

    def test_unexpected_additional_property(self, tmp_path, schema):
        row = _emit_and_read(_make_project(tmp_path), heat=2)
        row["surprise"] = 1
        assert any("surprise" in e for e in _validate(row, schema, schema))

    def test_bad_schema_version(self, tmp_path, schema):
        row = _emit_and_read(_make_project(tmp_path), heat=2)
        row["schema_version"] = "ini-019/l2/v2"
        assert any("const" in e for e in _validate(row, schema, schema))


# --- full Draft-2020-12 validation when jsonschema is installed -----------


class TestFullJsonSchema:
    def test_jsonschema_validates_if_available(self, tmp_path, schema):
        jsonschema = pytest.importorskip("jsonschema")
        row = _emit_and_read(_make_project(tmp_path), heat=2)
        jsonschema.validate(instance=row, schema=schema)  # raises on failure
