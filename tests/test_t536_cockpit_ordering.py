"""t-536 (ini-016): Cockpit pending-section ordering.

The server returns rows in scheduler order. The client now re-sorts
the Pending bucket (pending + in_progress + submitted) by:

  1. in_progress before everything else (so active work is always
     visually pinned to the top)
  2. then by priority ascending (0 = highest)
  3. then by id as a stable tiebreaker

Tests target the template text + the JS sort comparator shape so the
order in the rendered HTML is deterministic.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
TEMPLATE = REPO_ROOT / "ui-priority-poker" / "templates" / "cockpit.html"


def _read():
    return TEMPLATE.read_text()


# ---------------------------- template shape ----------------------------


def test_splitSections_sorts_pending_client_side():
    html = _read()
    # The sort comparator lives inside splitSections and is keyed off
    # in_progress → priority → id. Each condition should appear as
    # identifiable text so a refactor can't silently drop a dimension.
    assert "splitSections" in html
    assert "'in_progress' ? 0 : 1" in html
    assert "pa - pb" in html
    assert "localeCompare" in html


def test_subtitle_reflects_new_ordering_policy():
    html = _read()
    # The old comment ("Scheduler order is authoritative; no client
    # resort.") was misleading post-t-536. Assert the new wording
    # surfaces the three-way sort policy explicitly.
    assert "In-flight first" in html
    assert "priority" in html
    assert "Scheduler order is authoritative; no client resort" not in html


def test_null_priority_sorts_last_with_99_sentinel():
    """Priority null → 99 in the comparator so un-prioritized tasks
    sink below even p3."""
    html = _read()
    # The sentinel value appears on both lhs and rhs of the comparator.
    assert "99" in html


def test_complete_section_still_sorts_by_last_worklog_ts():
    """The pending-sort change must not regress the Complete section's
    newest-first ordering — both sorts coexist inside splitSections."""
    html = _read()
    assert "b.last_worklog_ts" in html
    assert "localeCompare(a.last_worklog_ts" in html


def test_deferred_section_not_sorted_by_client():
    """Only pending + complete get client-side sort; deferred stays
    as-is so scheduler-defer order holds. Assert by the absence of a
    deferred.sort call in the function."""
    html = _read()
    assert "deferred.sort(" not in html


# ---------------------------- DnD still wired ----------------------------


def test_dnd_handlers_present_post_sort_change():
    """t-389 wired drag-drop for pending rows. The t-536 client-sort
    layers on top but doesn't touch row-level event registration."""
    html = _read()
    assert "onRowDragStart" in html
    assert "draggable = true" in html
    assert "onRowDrop" in html


# ---------------------------- order invariant ----------------------------


def test_sort_comparator_checks_status_priority_id_in_order():
    """Regression guard for the three-way sort: status short-circuits
    above priority, priority above id. The template should return
    immediately from each branch when the prior tier differs."""
    html = _read()
    # All three "return ..." branches should appear in order near the
    # splitSections function. We do a substring proximity check — at
    # least one early-return on `sa - sb`, one on `pa - pb`, and a
    # final `localeCompare`.
    import re
    block_match = re.search(
        r"pending\.sort\(\(a, b\) => \{(.+?)\}\);",
        html, re.DOTALL,
    )
    assert block_match, "couldn't locate the pending.sort comparator body"
    body = block_match.group(1)
    i_status = body.find("return sa - sb")
    i_pri = body.find("return pa - pb")
    i_id = body.find("localeCompare")
    assert 0 < i_status < i_pri < i_id, (
        f"status/priority/id must appear in order; got "
        f"status={i_status} pri={i_pri} id={i_id}"
    )
