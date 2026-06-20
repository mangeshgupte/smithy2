"""t-527 (ini-016): Cockpit UI polish — 4 refinements.

Coverage mapped to the task's acceptance list:
  (1) AGE in minutes: task.created_at set by add-task; TaskSummary
      exposes age_minutes; API endpoint serializes it; template's
      `formatAge` helper is present.
  (2) DESC as second row, not column: primary row no longer has a
      c-desc cell; a c-desc-row tr is appended per task; clicking it
      toggles the inline panel.
  (3) INITIATIVE clickable → Bellows: template renders
      `c-ini-link` anchor pointing at the Bellows deep-dive URL;
      BELLOWS_URL + PROJECT_NAME injected on window.
  (4) REASON column dropped from primary row; still rendered in
      buildInlinePanel.

Tests are a mix of pure-function (TaskSummary enrichment + CLI
add-task) and template-shape checks against the rendered HTML; the
template is deterministic at render time so HTML assertions are stable.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(proj, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli",
         "--dir", str(proj), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def proj(tmp_path):
    """Scaffold a project with `smithy init` + one initiative so the
    age / initiative paths have real data."""
    p = tmp_path / "p"
    rc, _, err = _smithy(tmp_path, "init", "p", "--target", str(p))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = json.loads((p / "state.json").read_text())
    s["initiatives"] = [{
        "id": "ini-test", "title": "Test",
        "status": "approved", "rank": 1,
    }]
    (p / "state.json").write_text(json.dumps(s, indent=2))
    return p


# ---------- (1) AGE — created_at stamp + age_minutes derivation ----------


def test_add_task_stamps_created_at(proj):
    rc, out, _ = _smithy(proj, "add-task", "implementation", "a task")
    assert rc == 0
    s = json.loads((proj / "state.json").read_text())
    t = s["queue"][0]
    assert "created_at" in t
    assert t["created_at"].endswith("+00:00") or t["created_at"].endswith("Z")
    # Parseable as ISO8601.
    ts = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
    assert ts.tzinfo is not None


def test_task_summary_age_minutes_from_created_at(proj):
    """TaskSummary.from_queue_row reads created_at and computes
    age_minutes; older stamps yield larger deltas."""
    from smithy.task_detail import TaskSummary
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=3)).isoformat()
    older = (now - timedelta(hours=2, minutes=15)).isoformat()
    r1 = TaskSummary.from_queue_row({"id": "t-1", "created_at": recent})
    r2 = TaskSummary.from_queue_row({"id": "t-2", "created_at": older})
    assert r1.age_minutes is not None and 2 <= r1.age_minutes <= 5
    assert r2.age_minutes is not None and 130 <= r2.age_minutes <= 140


def test_task_summary_age_minutes_none_when_created_at_missing():
    """Tasks predating t-527 have no created_at → age_minutes stays None
    and the Cockpit renders '—'."""
    from smithy.task_detail import TaskSummary
    r = TaskSummary.from_queue_row({"id": "t-legacy"})
    assert r.age_minutes is None
    assert r.created_at is None


def test_task_summary_age_minutes_none_on_unparseable_stamp():
    from smithy.task_detail import TaskSummary
    r = TaskSummary.from_queue_row({"id": "t-bad", "created_at": "garbage"})
    assert r.age_minutes is None
    # created_at passes through raw for diagnostic value.
    assert r.created_at == "garbage"


def test_task_summary_to_dict_includes_age_minutes_and_created_at():
    from smithy.task_detail import TaskSummary
    now = datetime.now(timezone.utc).isoformat()
    r = TaskSummary.from_queue_row({"id": "t-1", "created_at": now})
    d = r.to_dict()
    assert "age_minutes" in d
    assert "created_at" in d
    assert d["age_minutes"] is not None


# ---------- template shape — rendered cockpit.html -----------------------


@pytest.fixture
def cockpit_html():
    """Read the cockpit.html template directly. We don't need a running
    FastAPI instance — the template is Jinja with `{{ url_bellows
    |tojson }}` / `{{ project|tojson }}` injection. Most assertions
    here target static HTML / JS strings."""
    tpl = REPO_ROOT / "ui-priority-poker" / "templates" / "cockpit.html"
    return tpl.read_text()


# ---------- (2) DESC second-row shape ------------------------------------


def test_cockpit_template_renders_desc_as_second_row(cockpit_html):
    assert "c-desc-row" in cockpit_html
    assert "c-desc-cell" in cockpit_html


def test_cockpit_template_no_longer_has_desc_column_header(cockpit_html):
    # Look for a header cell whose text is exactly 'desc' — the prior
    # column lived on a plain `<th>desc</th>` line.
    assert "<th>desc</th>" not in cockpit_html


def test_cockpit_desc_row_does_not_carry_task_id_dataset(cockpit_html):
    """Regression (heat 1220): desc rows must NOT set dataset.taskId /
    dataset.status. pendingRows(), keyboard nav (focusRow / altMoveFocused),
    and the inline-panel toggle all select on `tr[data-task-id]` and assume
    one match per task — a desc row carrying data-task-id duplicates every
    task in DnD reorder arrays and adds phantom keyboard-focus stops."""
    # Desc rows identify via data-desc-for instead.
    assert "descRow.dataset.descFor" in cockpit_html
    assert "descRow.dataset.taskId" not in cockpit_html
    assert "descRow.dataset.status" not in cockpit_html


def test_cockpit_desc_row_click_toggles_inline_panel(cockpit_html):
    """The desc row's td wires an onclick to toggleInlineExpand so the
    user can click the desc line to see full detail."""
    assert "c-desc-cell" in cockpit_html
    assert "toggleInlineExpand" in cockpit_html
    # Desc cell specifically points at toggleInlineExpand with the task id.
    # Look for the combination in the template.
    # t-599: card layout — the desc cell now spans 9 (1 leading empty cell
    # for the checkbox column, was 2 leading empties + colspan-8).
    assert 'c-desc-cell" colspan="9" onclick="toggleInlineExpand' in cockpit_html


# ---------- (3) INITIATIVE clickable -------------------------------------


def test_cockpit_template_renders_initiative_as_bellows_link(cockpit_html):
    assert "c-ini-link" in cockpit_html
    assert "/project/" in cockpit_html
    assert "/initiative/" in cockpit_html
    assert 'target="_blank"' in cockpit_html
    assert 'rel="noopener"' in cockpit_html


def test_cockpit_injects_bellows_url_and_project_name(cockpit_html):
    assert "COCKPIT_BELLOWS_URL" in cockpit_html
    assert "COCKPIT_PROJECT_NAME" in cockpit_html
    # Both should be wired to the Jinja context variables.
    assert "url_bellows | tojson" in cockpit_html
    assert "project | tojson" in cockpit_html


# ---------- (4) REASON column dropped from primary row -------------------


def test_cockpit_template_no_reason_th_in_header(cockpit_html):
    assert "<th>reason</th>" not in cockpit_html


def test_cockpit_inline_panel_still_shows_reason(cockpit_html):
    """Reason hasn't been deleted — just moved entirely into the inline
    panel (where it already lived alongside the c-desc-row)."""
    assert "<dt>reason</dt>" in cockpit_html


# ---------- formatAge helper -----------------------------------------------


def test_cockpit_template_has_formatAge_helper(cockpit_html):
    assert "function formatAge(" in cockpit_html


def test_cockpit_age_cell_uses_formatAge(cockpit_html):
    assert "formatAge(t.age_minutes)" in cockpit_html


# ---------- colspan accounting ---------------------------------------------


def test_cockpit_primary_row_is_10_cells_wide(cockpit_html):
    """Header + skeleton + empty-state rows all use colspan=10 post-t-527."""
    # At least one occurrence of colspan="10" (skeleton + section-head +
    # empty-state still span the full 10-column table width).
    assert 'colspan="10"' in cockpit_html
    # t-599: the card cell + desc cell now span 9 (1 leading checkbox cell +
    # colspan-9 = 10), so the table stays a consistent 10-column grid.
    assert 'c-desc-cell" colspan="9"' in cockpit_html
    assert 'c-card-cell" colspan="9"' in cockpit_html


# ---------- regression guard ------------------------------------------------


def test_cockpit_still_renders_with_old_state(tmp_path):
    """A state.json with tasks lacking created_at must still serialize
    cleanly — age_minutes defaults to null rather than throwing."""
    from smithy.task_detail import TaskSummary
    r = TaskSummary.from_queue_row({
        "id": "t-old", "desc": "legacy", "stage": "implementation",
        "status": "pending", "priority": 2,
    })
    d = r.to_dict()
    assert d["age_minutes"] is None
    assert d["created_at"] is None
