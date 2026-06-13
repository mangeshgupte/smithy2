"""t-546: Cockpit — expand/collapse a task row by clicking anywhere on it.

The chevron (16px c-expand cell) used to be the only toggle target.
t-546 makes the whole row clickable while keeping interactive children
(links, buttons, checkbox, defer kebab, the chevron itself) working
unchanged via a closest() guard.

Template-string assertions, same style as test_t527_* / test_t536_*:
the cockpit page is static Jinja + inline JS, so asserting on the
template source pins the wiring without a browser.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def cockpit_html():
    tpl = REPO_ROOT / "ui-priority-poker" / "templates" / "cockpit.html"
    return tpl.read_text()


def test_row_click_handler_defined(cockpit_html):
    assert "function onRowClickToggle" in cockpit_html


def test_row_click_handler_guards_interactive_children(cockpit_html):
    """closest() guard must cover every interactive element a row
    renders: id link (a), hp bump buttons (button), bulk checkbox
    (input), defer kebab (.c-kebab), and the chevron (.c-expand)."""
    assert "evt.target.closest" in cockpit_html
    for needle in ("a,", "button,", "input,", ".c-kebab", ".c-expand"):
        assert needle in cockpit_html, f"guard missing {needle!r}"


def test_row_click_handler_ignores_text_selection(cockpit_html):
    assert "window.getSelection" in cockpit_html


def test_render_row_wires_row_click(cockpit_html):
    """Both row builders attach the whole-row click listener."""
    assert cockpit_html.count(
        "tr.addEventListener('click', e => onRowClickToggle(e, t.id))"
    ) == 2  # renderRow + renderCompleteRow


def test_chevron_toggle_still_present(cockpit_html):
    """The chevron keeps its dedicated onclick — row click is additive,
    not a replacement."""
    assert "onclick=\"toggleInlineExpand(event, '${t.id}')\"" in cockpit_html


def test_row_click_delegates_to_inline_expand(cockpit_html):
    """The row handler funnels into the same toggleInlineExpand path the
    chevron uses (single source of truth for panel state)."""
    assert "toggleInlineExpand(evt, taskId)" in cockpit_html


def test_pointer_cursor_affordance(cockpit_html):
    """Rows advertise clickability; declared before the draggable grab
    rule so pending rows keep cursor: grab."""
    pointer_idx = cockpit_html.find(
        ".cockpit-table tr[data-task-id] { cursor: pointer; }")
    grab_idx = cockpit_html.find(
        '.cockpit-table tr[draggable="true"] { cursor: grab; }')
    assert pointer_idx != -1
    assert grab_idx != -1
    assert pointer_idx < grab_idx
