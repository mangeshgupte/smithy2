"""t-406: regression tests for task status vocabulary consistency.

Asserts that the canonical task status list (`VALID_TASK_STATUSES`) is
coherent across Poker, Cockpit, and CLI — no stray `in_flight` values,
no filters offering values that can never match stored data.
"""

from pathlib import Path

from smithy.state import VALID_TASK_STATUSES


REPO_ROOT = Path(__file__).parent.parent


def test_canonical_status_list_is_complete():
    # Every status the system knows about is enumerated in one place.
    assert "pending" in VALID_TASK_STATUSES
    assert "in_progress" in VALID_TASK_STATUSES
    assert "submitted" in VALID_TASK_STATUSES  # Assembly two-row lifecycle
    assert "deferred" in VALID_TASK_STATUSES
    assert "complete" in VALID_TASK_STATUSES
    # Not a canonical status — it was a display-only alias that drifted into
    # the Cockpit filter dropdown. Fixed in t-406.
    assert "in_flight" not in VALID_TASK_STATUSES


def test_cockpit_filter_only_offers_real_statuses():
    """The filter dropdown in cockpit.html must list valid statuses.

    Previously offered `in_flight` which never matched any row because
    storage uses `in_progress`.
    """
    html = (REPO_ROOT / "ui-priority-poker" / "templates"
            / "cockpit.html").read_text()
    # Find the STATUS filter block specifically (there are several Jinja
    # `for s in [...]` loops in this template — stages, statuses, etc.).
    import re
    block = re.search(r"<label>status.*?</select>", html, re.DOTALL)
    assert block, "status filter block not found"
    m = re.search(r"\{%\s*for s in \[([^\]]+)\]\s*%\}", block.group(0))
    assert m, "status filter list not found in cockpit.html"
    raw = m.group(1)
    values = [v.strip().strip("'").strip('"') for v in raw.split(",")]
    for v in values:
        assert v in VALID_TASK_STATUSES, \
            f"cockpit filter offers {v!r}, not in VALID_TASK_STATUSES"


def test_poker_reads_canonical_in_progress_status():
    """Poker's in-flight aggregation must read status == 'in_progress'."""
    src = (REPO_ROOT / "ui-priority-poker" / "app.py").read_text()
    # The aggregation line reads in-progress tasks for display.
    assert 'status") == "in_progress"' in src, \
        "Poker should read status == 'in_progress' (canonical storage value)"


def test_no_stale_in_flight_filter_choice_in_cli():
    """CLI `queue` command's --status choice must match the canonical list."""
    src = (REPO_ROOT / "smithy" / "smithy" / "cli.py").read_text()
    # The click.Choice for the queue list status filter.
    import re
    for m in re.finditer(
        r'click\.Choice\(\[([^\]]*pending[^\]]*complete[^\]]*)\]',
        src,
    ):
        raw = m.group(1)
        values = [v.strip().strip("'").strip('"') for v in raw.split(",")]
        for v in values:
            if v == "all":
                continue
            assert v in VALID_TASK_STATUSES, \
                f"CLI choice offers {v!r}, not in VALID_TASK_STATUSES"
