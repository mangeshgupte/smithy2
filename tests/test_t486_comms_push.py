"""t-486 — ini-023 T7: Comms push triggers.

Rising-edge detection for macOS `osascript -e 'display notification'`
triggers: halt_toggle, patrol_jump, repeat_rejections, budget_low,
queue_backpressure, all_forges_idle. Thresholds configurable in
`state.parallel.comms.thresholds`.

Imports use the namespace form (`from smithy.smithy.X import …`) so
the tests pass under Assembly's bare `/usr/bin/python3` — per the
t-502 divergence research.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from smithy.smithy import cli as cli_mod


REPO_ROOT = Path(__file__).parent.parent


def _runner():
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


@pytest.fixture
def proj(tmp_path):
    """Minimal scaffolded project."""
    project = tmp_path / "proj"
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli",
         "--dir", str(tmp_path), "init", "proj", "--target", str(project)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip(f"init failed: {r.stderr}")
    (project / ".worktrees" / "marshal").mkdir(parents=True, exist_ok=True)
    return project


def _set_state(proj, mutate_fn):
    s = json.loads((proj / "state.json").read_text())
    mutate_fn(s)
    (proj / "state.json").write_text(json.dumps(s))


def _fired_path(proj):
    return proj / "personas" / "comms" / ".fired.jsonl"


# -------- Thresholds merge logic -------------------------------------------

class TestCommsThresholds:
    def test_defaults_used_when_state_empty(self):
        from smithy.smithy.cli import _comms_thresholds, COMMS_DEFAULT_THRESHOLDS
        out = _comms_thresholds({})
        assert out == COMMS_DEFAULT_THRESHOLDS

    def test_state_overrides_merge_over_defaults(self):
        from smithy.smithy.cli import _comms_thresholds
        state = {"parallel": {"comms": {"thresholds":
                                         {"budget_low_pct": 25.0,
                                          "patrol_jump_delta": 5}}}}
        out = _comms_thresholds(state)
        assert out["budget_low_pct"] == 25.0
        assert out["patrol_jump_delta"] == 5
        # Unset key falls through.
        assert out["repeat_rejection_count"] == 3

    def test_malformed_threshold_silently_uses_default(self):
        """A non-numeric value for a threshold we know about falls back."""
        from smithy.smithy.cli import _comms_thresholds
        state = {"parallel": {"comms":
                              {"thresholds": {"budget_low_pct": "not-a-number"}}}}
        out = _comms_thresholds(state)
        # defaults apply (no crash)
        assert out["budget_low_pct"] == 10.0


# -------- Rising-edge detection per trigger --------------------------------

class TestEvaluateCommsTriggers:
    def _base_state_and_snapshot(self):
        state = {"parallel": {"forges": [
            {"id": "f-01", "status": "idle"},
        ]}}
        snap = {"halt_flag": False, "assembly_queue_depth": 0,
                "forges": {"total": 1},
                "budget": {"total": 100, "used": 50, "remaining": 50}}
        return state, snap

    def test_halt_toggle_fires_on_rising_edge_only(self, tmp_path):
        from smithy.smithy.cli import _evaluate_comms_triggers, \
            COMMS_DEFAULT_THRESHOLDS
        state, snap = self._base_state_and_snapshot()
        snap["halt_flag"] = True
        # Prior: halt was False. Now: True. → fires.
        last = {"halt_toggle": {"condition": False, "fired": False,
                                "metric": False}}
        out = _evaluate_comms_triggers(state, snap, last,
                                       COMMS_DEFAULT_THRESHOLDS, tmp_path)
        halt = next(t for t in out if t["trigger"] == "halt_toggle")
        assert halt["condition"] is True
        assert halt["fired"] is True

    def test_halt_toggle_suppressed_when_unchanged(self, tmp_path):
        """halt flag still False this cycle → no transition, no fire."""
        from smithy.smithy.cli import _evaluate_comms_triggers, \
            COMMS_DEFAULT_THRESHOLDS
        state, snap = self._base_state_and_snapshot()
        last = {"halt_toggle": {"condition": False, "fired": False,
                                "metric": False}}
        out = _evaluate_comms_triggers(state, snap, last,
                                       COMMS_DEFAULT_THRESHOLDS, tmp_path)
        halt = next(t for t in out if t["trigger"] == "halt_toggle")
        assert halt["fired"] is False

    def test_budget_low_fires_once(self, tmp_path):
        from smithy.smithy.cli import _evaluate_comms_triggers, \
            COMMS_DEFAULT_THRESHOLDS
        state, snap = self._base_state_and_snapshot()
        snap["budget"] = {"total": 100, "used": 95, "remaining": 5}
        # First evaluation: no prior → fires.
        out1 = _evaluate_comms_triggers(state, snap, {},
                                        COMMS_DEFAULT_THRESHOLDS, tmp_path)
        b1 = next(t for t in out1 if t["trigger"] == "budget_low")
        assert b1["fired"] is True
        # Second evaluation with prior fired=True → suppressed.
        last = {"budget_low": {"condition": True, "fired": True, "metric": 5.0}}
        out2 = _evaluate_comms_triggers(state, snap, last,
                                        COMMS_DEFAULT_THRESHOLDS, tmp_path)
        b2 = next(t for t in out2 if t["trigger"] == "budget_low")
        assert b2["fired"] is False
        assert b2["condition"] is True  # still below threshold

    def test_queue_backpressure_threshold(self, tmp_path):
        from smithy.smithy.cli import _evaluate_comms_triggers, \
            COMMS_DEFAULT_THRESHOLDS
        state, snap = self._base_state_and_snapshot()
        # 1 forge, factor=2.0 → ceiling=2. depth=3 trips.
        snap["assembly_queue_depth"] = 3
        out = _evaluate_comms_triggers(state, snap, {},
                                       COMMS_DEFAULT_THRESHOLDS, tmp_path)
        bp = next(t for t in out if t["trigger"] == "queue_backpressure")
        assert bp["fired"] is True
        # depth=2 at ceiling → NOT over.
        snap["assembly_queue_depth"] = 2
        out2 = _evaluate_comms_triggers(state, snap, {},
                                        COMMS_DEFAULT_THRESHOLDS, tmp_path)
        bp2 = next(t for t in out2 if t["trigger"] == "queue_backpressure")
        assert bp2["fired"] is False

    def test_all_forges_idle_needs_consecutive_cycles(self, tmp_path):
        from smithy.smithy.cli import _evaluate_comms_triggers, \
            COMMS_DEFAULT_THRESHOLDS
        state, snap = self._base_state_and_snapshot()
        # Default requires 2 consecutive cycles. First eval: streak=1,
        # no fire. Second eval with streak carried: fires.
        out1 = _evaluate_comms_triggers(state, snap, {},
                                        COMMS_DEFAULT_THRESHOLDS, tmp_path)
        idle1 = next(t for t in out1 if t["trigger"] == "all_forges_idle")
        assert idle1["fired"] is False
        assert idle1["metric"] == 1

        last = {"all_forges_idle": {"condition": False, "fired": False,
                                    "metric": 1}}
        out2 = _evaluate_comms_triggers(state, snap, last,
                                        COMMS_DEFAULT_THRESHOLDS, tmp_path)
        idle2 = next(t for t in out2 if t["trigger"] == "all_forges_idle")
        assert idle2["metric"] == 2
        assert idle2["fired"] is True

        # Third cycle with fired=True → suppressed despite still-idle.
        last2 = {"all_forges_idle": {"condition": True, "fired": True,
                                     "metric": 2}}
        out3 = _evaluate_comms_triggers(state, snap, last2,
                                        COMMS_DEFAULT_THRESHOLDS, tmp_path)
        idle3 = next(t for t in out3 if t["trigger"] == "all_forges_idle")
        assert idle3["fired"] is False

    def test_all_forges_idle_streak_resets_when_any_busy(self, tmp_path):
        from smithy.smithy.cli import _evaluate_comms_triggers, \
            COMMS_DEFAULT_THRESHOLDS
        state, snap = self._base_state_and_snapshot()
        state["parallel"]["forges"] = [
            {"id": "f-01", "status": "busy"},
            {"id": "f-02", "status": "idle"},
        ]
        last = {"all_forges_idle": {"condition": True, "fired": True,
                                    "metric": 5}}
        out = _evaluate_comms_triggers(state, snap, last,
                                       COMMS_DEFAULT_THRESHOLDS, tmp_path)
        idle = next(t for t in out if t["trigger"] == "all_forges_idle")
        assert idle["metric"] == 0
        assert idle["fired"] is False


# -------- CLI end-to-end ---------------------------------------------------

class TestCommsPushTriggersCLI:
    def test_dry_run_doesnt_fire_or_persist(self, proj, monkeypatch):
        """--dry-run evaluates triggers but neither fires osascript nor
        writes to .fired.jsonl."""
        # Force halt_flag toggle — rising edge expected.
        _set_state(proj, lambda s: s.setdefault("parallel", {}).update(
            {"halt_flag": True, "forges": [{"id": "f-01", "status": "idle"}]}
        ))
        (proj / "personas" / "comms").mkdir(parents=True, exist_ok=True)
        # Seed prior halt state so first run registers a toggle.
        fp = _fired_path(proj)
        fp.write_text(json.dumps({"ts": "2026-04-19T00:00:00+00:00",
                                    "trigger": "halt_toggle",
                                    "condition": False,
                                    "fired": False,
                                    "metric": False}) + "\n")

        called = {"n": 0}

        def fake_osascript(title, body):
            called["n"] += 1
            return True

        monkeypatch.setattr(cli_mod, "_fire_macos_notification", fake_osascript)

        result = _runner().invoke(
            cli_mod.cli,
            ["--dir", str(proj), "comms-push-triggers", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        halt = next(t for t in data["evaluated"] if t["trigger"] == "halt_toggle")
        assert halt["fired"] is True
        # But no osascript fired and no row appended.
        assert called["n"] == 0
        # .fired.jsonl still the seed file + no new rows.
        rows = [ln for ln in fp.read_text().splitlines() if ln.strip()]
        assert len(rows) == 1  # only the seed

    def test_fires_on_rising_edge_and_persists(self, proj, monkeypatch):
        """Full-fat: rising edge → osascript called, .fired.jsonl
        appended with per-trigger rows for next cycle's decision."""
        _set_state(proj, lambda s: s.setdefault("parallel", {}).update({
            "halt_flag": True,
            "forges": [{"id": "f-01", "status": "busy"}],  # disable idle trigger
            "assembly": {"enabled": True},
        }))

        fired_bodies = []

        def fake_osascript(title, body):
            fired_bodies.append(body)
            return True

        monkeypatch.setattr(cli_mod, "_fire_macos_notification", fake_osascript)

        # Seed halt_toggle prior to False so the current True trips a fire.
        (proj / "personas" / "comms").mkdir(parents=True, exist_ok=True)
        fp = _fired_path(proj)
        fp.write_text(json.dumps({"ts": "2026-04-19T00:00:00+00:00",
                                    "trigger": "halt_toggle",
                                    "condition": False,
                                    "fired": False,
                                    "metric": False}) + "\n")

        result = _runner().invoke(
            cli_mod.cli,
            ["--dir", str(proj), "comms-push-triggers"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "halt_toggle" in data["fired"], data
        # osascript was called at least once for halt_toggle.
        assert any("Halt flag ON" in b for b in fired_bodies), fired_bodies
        # Fired.jsonl now has per-trigger rows from this run.
        rows = [json.loads(ln) for ln in fp.read_text().splitlines() if ln.strip()]
        halt_rows = [r for r in rows if r["trigger"] == "halt_toggle"]
        assert len(halt_rows) >= 2  # seed + this run
        assert halt_rows[-1]["fired"] is True

    def test_suppresses_continued_state(self, proj, monkeypatch):
        """On the cycle after a fire, the same still-true condition is
        not fired again. Models the 5-min cron cadence where halt stays
        on but we don't spam notifications."""
        _set_state(proj, lambda s: s.setdefault("parallel", {}).update({
            "halt_flag": True,
            "forges": [{"id": "f-01", "status": "busy"}],
            "assembly": {"enabled": True},
        }))

        calls = []

        def fake_osascript(title, body):
            calls.append(body)
            return True

        monkeypatch.setattr(cli_mod, "_fire_macos_notification", fake_osascript)
        (proj / "personas" / "comms").mkdir(parents=True, exist_ok=True)
        fp = _fired_path(proj)
        # First row: halt was True, we fired.
        fp.write_text(json.dumps({"ts": "2026-04-19T00:00:00+00:00",
                                    "trigger": "halt_toggle",
                                    "condition": False,
                                    "fired": False,
                                    "metric": True}) + "\n"
                      + json.dumps({"ts": "2026-04-19T00:05:00+00:00",
                                      "trigger": "halt_toggle",
                                      "condition": True,
                                      "fired": True,
                                      "metric": True}) + "\n")

        result = _runner().invoke(
            cli_mod.cli,
            ["--dir", str(proj), "comms-push-triggers"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # Halt is still True (unchanged since last fire) → no re-fire.
        assert "halt_toggle" not in data["fired"], data

    def test_re_fires_after_clear_then_re_trip(self, proj, monkeypatch):
        """Sequence: halt ON (fire) → halt OFF (clear) → halt ON
        (re-trip) → should fire again. Covers the idempotency clause."""
        calls = []
        monkeypatch.setattr(cli_mod, "_fire_macos_notification",
                            lambda t, b: (calls.append(b), True)[1])

        (proj / "personas" / "comms").mkdir(parents=True, exist_ok=True)
        fp = _fired_path(proj)
        # History: fired once, then cleared (condition False/fired
        # False), so the NEXT halt=True should re-fire.
        fp.write_text(
            json.dumps({"ts": "2026-04-19T00:00:00+00:00",
                        "trigger": "halt_toggle", "condition": True,
                        "fired": True, "metric": True}) + "\n"
            + json.dumps({"ts": "2026-04-19T00:05:00+00:00",
                           "trigger": "halt_toggle", "condition": True,
                           "fired": False, "metric": False}) + "\n"
        )
        _set_state(proj, lambda s: s.setdefault("parallel", {}).update({
            "halt_flag": True,
            "forges": [{"id": "f-01", "status": "busy"}],
            "assembly": {"enabled": True},
        }))

        result = _runner().invoke(
            cli_mod.cli,
            ["--dir", str(proj), "comms-push-triggers"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "halt_toggle" in data["fired"], data
