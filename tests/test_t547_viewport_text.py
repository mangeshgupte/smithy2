"""t-547: Cockpit uses the full viewport width with larger text.

Human feedback: /cockpit wasted space left/right (1400px centered cap)
and the 10-12px text was too small. t-547 drops the cap and raises
every font-size in the cockpit style block by 2px, preserving the
relative hierarchy (accents stay smaller than body).

Template-string assertions, same style as the other test_t5xx cockpit
suites.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def cockpit_html():
    tpl = REPO_ROOT / "ui-priority-poker" / "templates" / "cockpit.html"
    return tpl.read_text()


def test_no_max_width_cap(cockpit_html):
    assert "max-width: 1400px" not in cockpit_html


def test_no_centering_margin_on_page(cockpit_html):
    page_rule = re.search(r"\.cockpit-page \{([^}]*)\}", cockpit_html)
    assert page_rule, ".cockpit-page rule missing"
    assert "margin: 0 auto" not in page_rule.group(1)
    assert "max-width" not in page_rule.group(1)


def test_table_text_raised_to_14(cockpit_html):
    table_rule = re.search(r"\.cockpit-table \{([^}]*)\}", cockpit_html)
    assert table_rule
    assert "font-size: 14px" in table_rule.group(1)


def test_no_tiny_text_left(cockpit_html):
    """The pre-t-547 sizes (10px/11px) must be gone — every former
    occurrence moved up 2px."""
    assert "font-size: 10px" not in cockpit_html
    assert "font-size: 11px" not in cockpit_html


def test_hierarchy_preserved(cockpit_html):
    """Accents stay smaller than body: stage chip (12) < table (14) <
    inline desc (15)."""
    stage = re.search(r"\.c-stage \{[^}]*font-size: (\d+)px", cockpit_html)
    table = re.search(r"\.cockpit-table \{[^}]*font-size: (\d+)px", cockpit_html)
    inline = re.search(r"\.c-inline-desc \{[^}]*font-size: (\d+)px", cockpit_html)
    assert stage and table and inline
    assert int(stage.group(1)) < int(table.group(1)) < int(inline.group(1))
