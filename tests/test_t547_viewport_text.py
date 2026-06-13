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


# t-557 tokenized the type scale: font-size values moved from one-off px
# literals to `var(--fs-*)` tokens defined on .cockpit-page. These helpers
# resolve a rule's font-size back to its rendered px so the t-547
# guarantees (table=14, hierarchy ordering) survive the indirection.
def _token_map(cockpit_html):
    """Map each --fs-* token to its px value, read from .cockpit-page."""
    page_rule = re.search(r"\.cockpit-page \{([^}]*)\}", cockpit_html)
    assert page_rule, ".cockpit-page rule missing"
    return {name: int(px) for name, px in
            re.findall(r"(--fs-[a-z]+):\s*(\d+)px", page_rule.group(1))}


def _font_px(cockpit_html, selector):
    """Resolve a selector's font-size to px, whether it's a literal px
    value or a var(--fs-*) token reference."""
    rule = re.search(re.escape(selector) + r" \{([^}]*)\}", cockpit_html)
    assert rule, f"{selector} rule missing"
    body = rule.group(1)
    literal = re.search(r"font-size:\s*(\d+)px", body)
    if literal:
        return int(literal.group(1))
    token = re.search(r"font-size:\s*var\((--fs-[a-z]+)\)", body)
    assert token, f"{selector} has no resolvable font-size"
    tokens = _token_map(cockpit_html)
    assert token.group(1) in tokens, f"unknown token {token.group(1)}"
    return tokens[token.group(1)]


def test_no_max_width_cap(cockpit_html):
    assert "max-width: 1400px" not in cockpit_html


def test_no_centering_margin_on_page(cockpit_html):
    page_rule = re.search(r"\.cockpit-page \{([^}]*)\}", cockpit_html)
    assert page_rule, ".cockpit-page rule missing"
    assert "margin: 0 auto" not in page_rule.group(1)
    assert "max-width" not in page_rule.group(1)


def test_table_text_raised_to_14(cockpit_html):
    # t-557: table text is now var(--fs-md); the token resolves to 14px,
    # so the t-547 guarantee (body text = 14) holds through the scale.
    assert _font_px(cockpit_html, ".cockpit-table") == 14


def test_no_tiny_text_left(cockpit_html):
    """The pre-t-547 sizes (10px/11px) must be gone — every former
    occurrence moved up 2px."""
    assert "font-size: 10px" not in cockpit_html
    assert "font-size: 11px" not in cockpit_html


def test_hierarchy_preserved(cockpit_html):
    """Accents stay smaller than body: stage chip (12) < table (14) <
    inline desc (15). t-557 resolves each through the --fs-* scale; the
    ordering is the invariant, not the literal px."""
    stage = _font_px(cockpit_html, ".c-stage")
    table = _font_px(cockpit_html, ".cockpit-table")
    inline = _font_px(cockpit_html, ".c-inline-desc")
    assert stage < table < inline
