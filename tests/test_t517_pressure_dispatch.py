"""t-517 (ini-015): back-pressure-aware Marshal dispatch.

When Assembly's queue is loaded, dispatch should prefer orthogonal,
low-conflict-risk tasks over ones that touch the same files as in-flight
work — WITHOUT ever letting risk override task priority.

Acceptance map:
  (a) low pressure (ratio < 0.3) → ordering identical to t-441
  (b) high pressure → non-in-flight initiative beats in-flight at equal pri
  (c) high pressure → research/planning beats implementation at similar risk
  (d) touches overlap measurably deprioritizes (synthetic A=smithy/ B=bellows/)
  (e) rig-event 'marshal_pressure_dispatch' fires for every high-pressure pick
  (f) priority dominates — a P0 beats a P2 even under max risk
  (g) conflict-risk scoring factored into a reusable pure helper
"""

import json
import subprocess

import pytest
from click.testing import CliRunner

from smithy.cli import cli
from smithy.dispatch import (
    select_task_for_forge,
    select_task_with_pressure,
    conflict_risk_score,
    effective_score,
    PRESSURE_FLOOR,
    RISK_CAP,
)


def _state(*, initiatives, queue, forges=None):
    return {
        "project": "test",
        "queue": queue,
        "initiatives": initiatives,
        "parallel": {"forges": forges or [{"id": "forge-anneal",
                                            "status": "idle"}]},
    }


def _ini(id, rank, *, touches=None, parallelism="parallel", status="active"):
    return {"id": id, "rank": rank, "touches": touches or [],
            "parallelism": parallelism, "status": status}


def _task(id, ini, *, priority=2, stage="implementation", status="pending",
          desc="", blocked_by=None, assigned_forge=None):
    return {"id": id, "initiative_id": ini, "priority": priority,
            "stage": stage, "status": status, "desc": desc,
            "blocked_by": blocked_by or [], "assigned_forge": assigned_forge}


# --- (a) regression: low pressure preserves t-441 ordering -------------

class TestLowPressureRegression:
    def test_low_pressure_matches_plain_walk(self):
        # ini-A (rank 1) holds a riskier task; ini-B (rank 2) is orthogonal.
        # Under HIGH pressure the rescorer would prefer B, but under low
        # pressure rank dominates and A wins — exactly like t-441.
        st = _state(
            initiatives=[_ini("ini-A", 1, touches=["smithy/"]),
                         _ini("ini-B", 2, touches=["bellows/"])],
            queue=[
                _task("t-a", "ini-A", priority=2),
                _task("t-b", "ini-B", priority=2),
                # in-flight A task → makes A look risky
                _task("t-a0", "ini-A", status="in_progress"),
            ],
        )
        # plain (ratio 0.0)
        assert select_task_for_forge(st, "forge-anneal")["id"] == "t-a"
        # below the floor → still t-441 order, no rescoring
        task, decision = select_task_with_pressure(
            st, "forge-anneal", None, PRESSURE_FLOOR - 0.01)
        assert task["id"] == "t-a"
        assert decision is None

    def test_pressure_ratio_zero_is_default(self):
        st = _state(
            initiatives=[_ini("ini-A", 1)],
            queue=[_task("t-a", "ini-A")],
        )
        # default keyword path
        assert select_task_for_forge(st, "forge-anneal")["id"] == "t-a"


# --- (b) high pressure prefers non-in-flight initiative ----------------

class TestHighPressureInitiativePreference:
    def test_non_inflight_initiative_wins_at_equal_priority(self):
        st = _state(
            initiatives=[_ini("ini-A", 1), _ini("ini-B", 2)],
            queue=[
                _task("t-a", "ini-A", priority=2),
                _task("t-b", "ini-B", priority=2),
                _task("t-a0", "ini-A", status="submitted"),  # A in flight
            ],
        )
        task, decision = select_task_with_pressure(
            st, "forge-anneal", None, 0.9)
        assert task["id"] == "t-b"          # orthogonal B beats in-flight A
        assert decision["selected_id"] == "t-b"
        assert set(decision["candidate_ids"]) == {"t-a", "t-b"}
        # A scored strictly higher (worse) than B
        assert decision["scores"]["t-a"] > decision["scores"]["t-b"]


# --- (c) research/planning beats implementation at similar risk --------

class TestStageRisk:
    def test_research_beats_implementation(self):
        st = _state(
            initiatives=[_ini("ini-A", 1), _ini("ini-B", 2)],
            queue=[
                _task("t-impl", "ini-A", priority=2, stage="implementation"),
                _task("t-res", "ini-B", priority=2, stage="research"),
            ],
        )
        task, _ = select_task_with_pressure(st, "forge-anneal", None, 0.9)
        assert task["id"] == "t-res"

    def test_marketing_is_lowest_risk(self):
        st = _state(
            initiatives=[_ini("ini-A", 1), _ini("ini-B", 2)],
            queue=[
                _task("t-impl", "ini-A", priority=2, stage="implementation"),
                _task("t-mkt", "ini-B", priority=2, stage="marketing"),
            ],
        )
        task, _ = select_task_with_pressure(st, "forge-anneal", None, 0.9)
        assert task["id"] == "t-mkt"


# --- (d) touches overlap deprioritizes (the spec's synthetic case) -----

class TestTouchesOverlap:
    def test_overlapping_touches_loses_to_orthogonal(self):
        # stage="research" on both → zero stage modifier, so the only
        # risk signal is same-initiative + touches overlap.
        st = _state(
            initiatives=[_ini("ini-A", 1, touches=["smithy/"]),
                         _ini("ini-B", 2, touches=["bellows/"])],
            queue=[
                _task("t-a", "ini-A", priority=2, stage="research"),
                _task("t-b", "ini-B", priority=2, stage="research"),
                _task("t-a0", "ini-A", status="in_progress",
                      stage="research"),  # in-flight A
            ],
        )
        task, decision = select_task_with_pressure(
            st, "forge-anneal", None, 0.9)
        assert task["id"] == "t-b"
        # A carries same-initiative (0.3) + touches-overlap (0.5) risk
        assert decision["risks"]["t-a"] == pytest.approx(0.8)
        assert decision["risks"]["t-b"] == 0.0


# --- (f) priority always dominates risk --------------------------------

class TestPriorityDominates:
    def test_p0_beats_p2_under_max_risk(self):
        # t-a is P0 but maximally risky (same-ini + touches overlap +
        # implementation stage). t-b is P2 and perfectly orthogonal.
        # Priority must still win.
        st = _state(
            initiatives=[_ini("ini-A", 1, touches=["smithy/", "tests/"]),
                         _ini("ini-B", 2, touches=["bellows/"])],
            queue=[
                _task("t-a", "ini-A", priority=0, stage="implementation",
                      desc="edit smithy/cli.py and tests/test_x.py"),
                _task("t-b", "ini-B", priority=2),
                _task("t-a0", "ini-A", status="in_progress",
                      desc="edit smithy/cli.py and tests/test_x.py"),
            ],
        )
        task, decision = select_task_with_pressure(
            st, "forge-anneal", None, 1.0)
        assert task["id"] == "t-a"          # P0 wins despite the risk
        assert decision["scores"]["t-a"] < decision["scores"]["t-b"]

    def test_risk_term_clamped_below_one_bucket(self):
        # Even an absurd risk * ratio can't add a full priority bucket.
        assert effective_score(0, risk=99.0, pressure_ratio=99.0) < 1.0
        assert effective_score(0, risk=99.0, pressure_ratio=99.0) == RISK_CAP
        # Negative (orthogonal docs) can't subtract a full bucket either.
        assert effective_score(2, risk=-99.0, pressure_ratio=99.0) > 1.0


# --- (g) reusable pure helper ------------------------------------------

class TestReusableHelper:
    def test_conflict_risk_score_is_pure_and_importable(self):
        st = _state(
            initiatives=[_ini("ini-A", 1, touches=["smithy/"])],
            queue=[_task("t-a", "ini-A")],
        )
        in_flight = [_task("t-a0", "ini-A", status="in_progress")]
        before = json.dumps(st, sort_keys=True)
        risk = conflict_risk_score(st, st["queue"][0], in_flight)
        assert risk >= 0.3                      # same-initiative penalty
        assert json.dumps(st, sort_keys=True) == before   # no mutation

    def test_no_inflight_means_zero_risk(self):
        st = _state(initiatives=[_ini("ini-A", 1)],
                    queue=[_task("t-a", "ini-A", stage="research")])
        assert conflict_risk_score(st, st["queue"][0], []) == 0.0


# --- (e) rig-event fires for high-pressure dispatch (CLI integration) --

@pytest.fixture
def project(tmp_path):
    state = _state(
        initiatives=[_ini("ini-A", 1), _ini("ini-B", 2)],
        queue=[
            _task("t-a", "ini-A", priority=2),
            _task("t-b", "ini-B", priority=2),
            _task("t-a0", "ini-A", status="submitted"),
        ],
        forges=[{"id": "forge-anneal", "status": "idle"}],
    )
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    )
    (tmp_path / "feedback.md").write_text("# Feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path,
                   capture_output=True)
    return tmp_path


def _rig_events(project):
    p = project / "rig-events.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


class TestRigEventEmission:
    def test_high_pressure_emits_rig_event(self, project):
        # 1 forge → threshold = 4; write 3 queue rows → ratio 0.75 (>= floor).
        (project / ".assembly-queue.jsonl").write_text(
            "\n".join(json.dumps({"task_id": f"x-{i}",
                                  "branch": f"forge-anneal/x-{i}"})
                      for i in range(3)) + "\n")
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(project),
                                "dispatch-next", "--forge", "forge-anneal"])
        assert r.exit_code == 0, r.stderr
        events = [e for e in _rig_events(project)
                  if e["event"] == "marshal_pressure_dispatch"]
        assert len(events) == 1
        ev = events[0]
        assert ev["forge_id"] == "forge-anneal"
        assert ev["selected_id"] == "t-b"     # orthogonal beats in-flight A
        assert "scores" in ev and "pressure_ratio" in ev

    def test_low_pressure_emits_no_rig_event(self, project):
        # No assembly-queue file → depth 0 → ratio 0 → no rescoring.
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(project),
                                "dispatch-next", "--forge", "forge-anneal"])
        assert r.exit_code == 0, r.stderr
        events = [e for e in _rig_events(project)
                  if e["event"] == "marshal_pressure_dispatch"]
        assert events == []
