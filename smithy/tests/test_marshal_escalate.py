"""t-479: Marshal escalation — never-block-on-stdin.

Covers the CLI primitives that replace pane-stdin blocking:
  * `smithy marshal-escalate`        — persist + nudge Anvil + return
  * `smithy marshal-escalate-resolve` — Anvil flips status + nudges Marshal
  * `smithy marshal-escalate-list`   — inspection (open / all)

Plus the main acceptance scenarios from the task:
  (b) simulated t-450/t-463/t-472 wedge: Marshal does not block, entry is
      persisted, Anvil nudge fires, Marshal proceeds in the same iteration.
  (c) round-trip: after resolve, entry is marked resolved and Marshal is
      nudged.
"""

import json
import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

# Root-cause fix for the t-479 Assembly reject loop: import via
# `smithy.smithy.*` (namespace form) so pytest — run by Assembly from the
# staging worktree — resolves these modules from the REBASED source tree.
# The bare `smithy.*` form falls through to the globally-installed editable,
# which is bound to main and doesn't have the escalate commands on the task
# branch. Every other test file in this repo uses the namespace form for the
# same reason; t-479's first landing used the plain form and rejected twice.
from smithy.smithy.cli import cli
from smithy.smithy.state import VALID_STAGES


@pytest.fixture
def project(tmp_path):
    state = {
        "project": "test",
        "budget": {"total_heats": 50, "used": 10,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3,
                       "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": [
            {"id": "t-450", "stage": "implementation", "desc": "zombie A",
             "status": "submitted", "priority": 1, "blocked_by": []},
            {"id": "t-463", "stage": "implementation", "desc": "zombie B",
             "status": "submitted", "priority": 1, "blocked_by": []},
            {"id": "t-472", "stage": "implementation", "desc": "zombie C",
             "status": "submitted", "priority": 1, "blocked_by": []},
            {"id": "t-999", "stage": "implementation", "desc": "ready",
             "status": "pending", "priority": 2, "blocked_by": []},
        ],
        "next_tasks": [],
        "ideas": [],
        "themes": [],
        "initiatives": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.3,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    )
    (tmp_path / "feedback.md").write_text("# Feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path,
                   capture_output=True)
    return tmp_path


@pytest.fixture
def runner():
    # On click <8.3, CliRunner defaults to mix_stderr=True, which merges stderr
    # into result.stdout and breaks our json.loads assertions (escalate cmds
    # emit a human "Escalated X" line on stderr alongside the JSON on stdout).
    # Pass mix_stderr=False explicitly. On click >=8.3 the param was removed
    # and streams are always separate — fall back to the bare constructor.
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _read_entries(project):
    path = project / "marshal-questions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


class TestMarshalEscalateCreate:
    """Acceptance (b): Marshal escalates instead of blocking."""

    @patch("smithy.smithy.cli._nudge_persona")
    def test_escalate_writes_entry(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "persona": "anvil",
                                   "target": "%0"}
        result = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--tasks", "t-450,t-463,t-472",
            "--options", "abandon,reassign,reject",
            "--reason", "3 submitted tasks with no forge_id",
            "--safe-default", "leave status untouched; dispatch next",
            "--summary", "zombie submitted tasks",
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        entry = data["entry"]
        assert entry["id"].startswith("mq-")
        assert entry["tasks"] == ["t-450", "t-463", "t-472"]
        assert entry["options"] == ["abandon", "reassign", "reject"]
        assert entry["status"] == "open"
        assert entry["resolution"] is None
        assert entry["safe_default"].startswith("leave status")
        assert entry["created_at"].endswith("+00:00")

        # Persisted to file
        entries = _read_entries(project)
        assert len(entries) == 1
        assert entries[0]["id"] == entry["id"]

    @patch("smithy.smithy.cli._nudge_persona")
    def test_escalate_nudges_anvil(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "persona": "anvil",
                                   "target": "%0"}
        result = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--reason", "unknown initiative constraint",
            "--safe-default", "treat as serial",
            "--summary", "initiative constraint unclear",
        ])
        assert result.exit_code == 0
        mock_nudge.assert_called_once()
        args, kwargs = mock_nudge.call_args
        assert args[0] == "anvil"
        assert "MARSHAL_ESCALATE" in args[1]
        assert "initiative constraint unclear" in args[1]

    @patch("smithy.smithy.cli._nudge_persona")
    def test_escalate_no_nudge_flag(self, mock_nudge, project, runner):
        result = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--reason", "x", "--safe-default", "y",
            "--no-nudge",
        ])
        assert result.exit_code == 0
        mock_nudge.assert_not_called()
        data = json.loads(result.stdout)
        assert data["nudge"] is None

    @patch("smithy.smithy.cli._nudge_persona")
    def test_escalate_appends_multiple(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        for i in range(3):
            result = runner.invoke(cli, [
                "--dir", str(project), "marshal-escalate",
                "--reason", f"reason {i}",
                "--safe-default", f"default {i}",
                "--no-nudge",
            ])
            assert result.exit_code == 0
        entries = _read_entries(project)
        assert len(entries) == 3
        # Each has a distinct id
        assert len({e["id"] for e in entries}) == 3

    def test_escalate_requires_reason_and_safe_default(self, project, runner):
        # Missing required options → Click returns exit 2
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--no-nudge",
        ])
        assert r.exit_code == 2
        assert "reason" in (r.stdout + r.stderr).lower()


class TestMarshalEscalateResolve:
    """Acceptance (c): round-trip resolve marks entry + nudges Marshal."""

    @patch("smithy.smithy.cli._nudge_persona")
    def test_resolve_flips_status(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}

        # Create
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--reason", "ambiguous", "--safe-default", "skip",
            "--no-nudge",
        ])
        entry_id = json.loads(r.stdout)["entry"]["id"]

        # Resolve
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-resolve", entry_id,
            "--resolution", "abandon all three — they're lost to the Assembly race",
        ])
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["entry"]["status"] == "resolved"
        assert "abandon all three" in data["entry"]["resolution"]
        assert data["entry"]["resolved_at"].endswith("+00:00")

        # Persisted
        entries = _read_entries(project)
        assert len(entries) == 1
        assert entries[0]["status"] == "resolved"

    @patch("smithy.smithy.cli._nudge_persona")
    def test_resolve_nudges_marshal(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}

        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--reason", "x", "--safe-default", "y", "--no-nudge",
        ])
        entry_id = json.loads(r.stdout)["entry"]["id"]

        mock_nudge.reset_mock()
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-resolve", entry_id,
            "--resolution", "do X",
        ])
        assert r.exit_code == 0
        mock_nudge.assert_called_once()
        args, _ = mock_nudge.call_args
        assert args[0] == "marshal"
        assert "MARSHAL_ESCALATE_RESOLVED" in args[1]
        assert entry_id in args[1]

    def test_resolve_unknown_id(self, project, runner):
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-resolve", "mq-bogus",
            "--resolution", "whatever",
        ])
        assert r.exit_code != 0
        data = json.loads(r.stdout)
        assert data["error"] == "not found"

    @patch("smithy.smithy.cli._nudge_persona")
    def test_resolve_idempotent_on_already_resolved(self, mock_nudge,
                                                    project, runner):
        mock_nudge.return_value = {"nudged": True}
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate",
            "--reason", "x", "--safe-default", "y", "--no-nudge",
        ])
        entry_id = json.loads(r.stdout)["entry"]["id"]

        runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-resolve", entry_id,
            "--resolution", "first answer", "--no-nudge",
        ])
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-resolve", entry_id,
            "--resolution", "second answer", "--no-nudge",
        ])
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["error"] == "already resolved"
        # First resolution preserved
        entries = _read_entries(project)
        assert entries[0]["resolution"] == "first answer"


class TestMarshalEscalateList:
    @patch("smithy.smithy.cli._nudge_persona")
    def test_list_filters_open(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        # Create 2, resolve 1
        ids = []
        for i in range(2):
            r = runner.invoke(cli, [
                "--dir", str(project), "marshal-escalate",
                "--reason", f"r{i}", "--safe-default", f"s{i}", "--no-nudge",
            ])
            ids.append(json.loads(r.stdout)["entry"]["id"])
        runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-resolve", ids[0],
            "--resolution", "done", "--no-nudge",
        ])

        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-list",
        ])
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["count"] == 1
        assert data["entries"][0]["id"] == ids[1]

        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-list", "--all",
        ])
        data = json.loads(r.stdout)
        assert data["count"] == 2

    def test_list_empty(self, project, runner):
        r = runner.invoke(cli, [
            "--dir", str(project), "marshal-escalate-list",
        ])
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["count"] == 0
        assert data["entries"] == []
