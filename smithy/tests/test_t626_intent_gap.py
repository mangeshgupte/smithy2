"""t-626 (ini-017): `smithy intent-gap` — list tasks + initiatives with NULL
intent, ranked by recent worklog activity. Pure-function coverage of
intent_gap_units + a CLI smoke test (human + --json)."""

import json

from click.testing import CliRunner

from smithy.cli import cli
from smithy.worklog_agg import intent_gap_units


# --- pure ranking logic --------------------------------------------------

def test_lists_only_null_intent_units():
    state = {
        "queue": [
            {"id": "t-1", "intent": None, "stage": "implementation",
             "status": "pending", "desc": "A"},
            {"id": "t-2", "intent": "so X works", "stage": "implementation",
             "status": "pending", "desc": "B"},          # has intent → excluded
        ],
        "initiatives": [
            {"id": "ini-1", "intent": None, "title": "I1", "status": "active"},
            {"id": "ini-2", "intent": "the why", "title": "I2",
             "status": "active"},                          # has intent → excluded
        ],
    }
    ids = [u["id"] for u in intent_gap_units(state, {})]
    assert set(ids) == {"t-1", "ini-1"}


def test_ranked_by_recency_newest_first():
    state = {
        "queue": [
            {"id": "t-old", "intent": None, "status": "complete", "desc": ""},
            {"id": "t-new", "intent": None, "status": "pending", "desc": ""},
        ],
        "initiatives": [],
    }
    latest = {"t-old": {"ts": "2026-06-01T00:00:00Z"},
              "t-new": {"ts": "2026-06-05T00:00:00Z"}}
    ids = [u["id"] for u in intent_gap_units(state, latest)]
    assert ids == ["t-new", "t-old"]                      # newest activity first


def test_no_activity_units_sort_last():
    state = {
        "queue": [
            {"id": "t-active", "intent": None, "status": "pending", "desc": ""},
            {"id": "t-idle", "intent": None, "status": "pending", "desc": ""},
        ],
        "initiatives": [],
    }
    units = intent_gap_units(state, {"t-active": {"ts": "2026-06-01T00:00:00Z"}})
    ids = [u["id"] for u in units]
    assert ids == ["t-active", "t-idle"]
    assert units[-1]["last_activity"] is None


def test_initiative_recency_is_max_over_its_tasks():
    state = {
        "queue": [
            {"id": "t-1", "intent": "y", "status": "complete",
             "initiative_id": "ini-1"},                    # has intent (not listed)
            {"id": "t-2", "intent": None, "status": "complete",
             "initiative_id": "ini-1", "desc": ""},
        ],
        "initiatives": [{"id": "ini-1", "intent": None, "title": "I1",
                         "status": "active"}],
    }
    latest = {"t-1": {"ts": "2026-06-09T00:00:00Z"},
              "t-2": {"ts": "2026-06-02T00:00:00Z"}}
    ini = next(u for u in intent_gap_units(state, latest) if u["kind"] == "initiative")
    # recency rolls up the MAX over the initiative's tasks (incl. t-1 @ 06-09)
    assert ini["last_activity"] == "2026-06-09T00:00:00Z"


def test_empty_when_all_have_intent():
    state = {"queue": [{"id": "t-1", "intent": "why", "status": "pending"}],
             "initiatives": []}
    assert intent_gap_units(state, {}) == []


# --- CLI smoke -----------------------------------------------------------

def _seed(tmp_path):
    state = {
        "budget": {"total_heats": 100, "used": 10},
        "queue": [
            {"id": "t-1", "intent": None, "stage": "implementation",
             "status": "pending", "desc": "wire the thing", "blocked_by": []},
            {"id": "t-2", "intent": "so users can recover", "stage": "testing",
             "status": "pending", "desc": "test it", "blocked_by": []},
        ],
        "initiatives": [],
        "themes": [],
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-06-03T00:00:00Z\t11\timplementation\tt-1\tsubmitted\t0.8\t🟢\tx\n"
    )
    return tmp_path


def test_cli_intent_gap_json(tmp_path):
    _seed(tmp_path)
    r = CliRunner().invoke(cli, ["--dir", str(tmp_path), "intent-gap", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    ids = [u["id"] for u in data["intent_gap"]]
    assert "t-1" in ids and "t-2" not in ids       # t-2 has intent
    assert data["count"] == len(data["intent_gap"])


def test_cli_intent_gap_human(tmp_path):
    _seed(tmp_path)
    r = CliRunner().invoke(cli, ["--dir", str(tmp_path), "intent-gap"])
    assert r.exit_code == 0, r.output
    assert "Intent gaps:" in r.output
    assert "t-1" in r.output and "t-2" not in r.output
