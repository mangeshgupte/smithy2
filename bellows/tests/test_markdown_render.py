"""Tests for t-501 — markdown rendering of task.desc.

The `render_task_markdown` helper powers:
  - the `|markdown` Jinja filter used in initiative.html / direct.html
  - `task.desc_html` on /api/project/<name>/task/<id>, which the initiative
    drawer switches to `.innerHTML` from the old `.textContent`.

The security bar is: never allow a raw <script>, never emit a
javascript:/data:/vbscript: href. Everything else (bullets, bold,
inline code, fenced blocks, headers, blockquotes) should render.
"""

import sys
from pathlib import Path

import pytest


# Keep bellows/ on sys.path so `import app` finds bellows/app.py, not
# some other "app" module from the workspace. Same pattern as
# test_upcoming.py.
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="module")
def render():
    """Import the render helper from bellows/app.py."""
    import app as app_mod
    return app_mod.render_task_markdown


# ---------------------------- structure ---------------------------------


def test_empty_input_returns_empty_string(render):
    assert render("") == ""
    assert render(None) == ""


def test_bullet_list_renders(render):
    html = render("- first\n- second\n- third")
    assert "<ul>" in html
    assert "<li>first</li>" in html
    assert "<li>second</li>" in html
    assert "<li>third</li>" in html


def test_numbered_list_renders(render):
    html = render("1. one\n2. two")
    assert "<ol>" in html
    assert "<li>one</li>" in html
    assert "<li>two</li>" in html


def test_bold_and_italic(render):
    html = render("**bold** and *italic* text")
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html


def test_inline_code(render):
    html = render("see `cli.py:275` for details")
    assert "<code>cli.py:275</code>" in html


def test_fenced_code_block(render):
    html = render("```\ndef f():\n    return 1\n```")
    assert "<pre><code>" in html
    assert "def f():" in html


def test_headers(render):
    html = render("# big\n## medium\n### small")
    assert "<h1>big</h1>" in html
    assert "<h2>medium</h2>" in html
    assert "<h3>small</h3>" in html


def test_plain_paragraph_wraps_in_p(render):
    html = render("just a sentence.")
    assert "<p>just a sentence.</p>" in html


# ---------------------------- security ---------------------------------


def test_script_tag_is_escaped_not_executed(render):
    """The canonical XSS smoke test."""
    html = render("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "alert(1)" in html  # text remains, just as inert characters


def test_inline_html_img_onerror_neutralized(render):
    """The <img> tag + onerror payload must not become a live element.
    Pre-escape renders the whole thing as inert text; `onerror` can
    appear in the escaped payload but it's inside an escaped-tag text
    node, not on a real <img>."""
    html = render('<img src="x" onerror="alert(1)">')
    # No real <img> element.
    assert "<img " not in html and "<img>" not in html
    # Escaped form of the tag is present (so users still see their input).
    assert "&lt;img" in html


def test_javascript_href_is_stripped(render):
    """Markdown link with javascript: URI must not produce a live href."""
    html = render("[click](javascript:alert(1))")
    assert 'href="javascript:' not in html
    # Link text still renders — just without the dangerous href.
    assert "click" in html


def test_data_uri_href_is_stripped(render):
    html = render("[x](data:text/html,<script>alert(1)</script>)")
    assert 'href="data:' not in html


def test_vbscript_href_is_stripped(render):
    html = render("[x](vbscript:msgbox)")
    assert 'href="vbscript:' not in html


def test_http_link_preserved_with_noopener(render):
    html = render("[home](https://example.com)")
    assert 'href="https://example.com"' in html
    assert 'rel="noopener noreferrer"' in html


def test_case_insensitive_unsafe_scheme(render):
    html = render("[x](JavaScript:alert(1))")
    assert 'href="JavaScript:' not in html
    assert 'href="javascript:' not in html


def test_entity_in_code_block_stays_safe(render):
    """A code span containing `<script>` must not produce a live <script>
    anywhere. Pre-escape double-escapes the entity inside backticks
    (`&amp;lt;script&amp;gt;` renders as literal `&lt;script&gt;` text in
    the browser) — slightly ugly but safe. The security invariant: no
    literal `<script>` in the output HTML."""
    html = render("`<script>`")
    assert "<code>" in html
    assert "<script>" not in html  # the load-bearing invariant


# ------------------------- jinja filter ---------------------------------


def test_filter_is_registered_on_templates(render):
    """The Jinja environment used by bellows must have the filter wired."""
    import app as app_mod
    assert "markdown" in app_mod.templates.env.filters
    # Round-trip: the filter's behaviour matches render_task_markdown.
    filt = app_mod.templates.env.filters["markdown"]
    assert filt("**x**") == render("**x**")
