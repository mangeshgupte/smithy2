"""t-556: Cockpit polish 1/3 — spacing rhythm & column alignment.

Spacing normalized to a 4/8/12/16 rhythm (the ad-hoc 2/3/5/6/10px
paddings/gaps are gone); numeric columns (priority, hp, age, heat)
right-aligned with matching headers; chevron/id/stage cells vertically
centered; inline-panel padding matches the 8px table gutter.

No color or font-size changes (polish heats 2-3 own those).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def cockpit_html():
    return (REPO_ROOT / "ui-priority-poker" / "templates" / "cockpit.html").read_text()


@pytest.fixture(scope="module")
def style_block(cockpit_html):
    m = re.search(r"<style>(.*?)</style>", cockpit_html, re.S)
    assert m, "style block missing"
    return m.group(1)


class TestSpacingRhythm:
    def test_no_off_rhythm_paddings(self, style_block):
        """5/6/10px paddings were the ad-hoc offenders — all normalized."""
        for decl in re.findall(r"padding[^;]*;", style_block):
            for px in re.findall(r"(\d+)px", decl):
                assert int(px) in (0, 1, 2, 4, 8, 12, 16, 32), (
                    f"off-rhythm padding {px}px in: {decl}"
                )

    def test_no_off_rhythm_gaps(self, style_block):
        for decl in re.findall(r"gap[^;]*;", style_block):
            for px in re.findall(r"(\d+)px", decl):
                assert int(px) in (2, 4, 8, 12, 16), (
                    f"off-rhythm gap {px}px in: {decl}"
                )

    def test_table_cell_padding_on_grid(self, style_block):
        assert "padding: 4px 8px" in style_block   # td
        assert re.search(r"\.cockpit-table th \{[^}]*padding: 8px", style_block)


class TestNumericAlignment:
    def test_right_align_rule_present(self, style_block):
        assert "th.c-num" in style_block
        assert "text-align: right" in style_block

    def test_headers_tagged(self, cockpit_html):
        # t-599: the 2-line card layout dropped the per-column numeric headers
        # (M/you/age). The header row is now the select-all checkbox plus a
        # single label cell spanning the card.
        assert '<th class="c-num">M</th>' not in cockpit_html
        assert '<th class="c-num">you</th>' not in cockpit_html
        assert 'id="c-check-all"' in cockpit_html
        assert '<th colspan="9">tasks</th>' in cockpit_html

    def test_priority_cell_tagged(self):
        # t-599: priority moved from a right-aligned c-num table cell to a pill
        # on the card's line 1. t-612 (ini-016): that pill markup now lives in
        # the shared static/cockpit-card.js (rendered by /cockpit + the rail).
        js = (REPO_ROOT / "ui-priority-poker" / "static" / "cockpit-card.js").read_text()
        assert 'class="c-card-prio"' in js
        assert "t.priority == null" in js

    def test_hp_age_heat_right_aligned(self, style_block):
        rule = re.search(r"\.cockpit-table \.c-hp,[^}]*\}", style_block, re.S)
        assert rule and "text-align: right" in rule.group(0)
        assert ".c-ship-heat" in rule.group(0)
        assert ".c-age" in rule.group(0)


class TestVerticalCentering:
    def test_chevron_id_stage_centered(self, style_block):
        rule = re.search(r"\.cockpit-table td\.c-expand,[^}]*\}", style_block, re.S)
        assert rule, "vertical-centering rule missing"
        body = rule.group(0)
        assert "vertical-align: middle" in body
        assert "td.c-id" in body
        assert "td.c-stage-cell" in body

    def test_stage_cells_carry_class(self, cockpit_html):
        # t-599: the stage badge was dropped from the card face (renderRow /
        # renderCompleteRow no longer emit a c-stage-cell). The stage value now
        # surfaces in the expanded inline panel's detail list instead.
        assert "<dt>stage</dt>" in cockpit_html


class TestInlinePanelGutter:
    def test_inline_body_matches_table_gutter(self, style_block):
        """Horizontal padding 8px = the td gutter; 12/16 vertical rhythm."""
        assert "padding: 12px 8px 16px" in style_block
