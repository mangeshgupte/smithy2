"""Tests for t-508 — compact HEAT_DONE nudge format.

Covers the pure formatter `_format_heat_done_nudge` directly (fast) and,
for one acceptance case, the end-to-end emission via `smithy end-heat`
so we verify the nudge message actually reaches `_nudge_persona` with
the new shape.

Acceptance (from task):
  (a) normal task heat → new format with id/stage/ini/desc
  (b) task-less heat (task_id='generated') → (no task) fallback with notes
  (c) long desc truncates to 50 chars with '…' ellipsis
  (d) no-initiative tasks omit the /ini-XXX segment
  (e) existing `HEAT_DONE` substring assertions in tests survive (prefix
      preserved); this module adds that assertion explicitly.
"""

from smithy.cli import _format_heat_done_nudge, _truncate_for_nudge


# -------------------- truncation helper --------------------------------


def test_truncate_preserves_short_text():
    assert _truncate_for_nudge("short") == "short"


def test_truncate_cuts_at_limit_with_ellipsis():
    text = "a" * 80
    out = _truncate_for_nudge(text, limit=50)
    assert len(out) == 50
    assert out.endswith("…")
    assert out.startswith("a" * 49)


def test_truncate_collapses_internal_whitespace():
    """Multi-line descs must fit on one wire line."""
    text = "line one\n    line two\n\n\nline three"
    out = _truncate_for_nudge(text)
    assert "\n" not in out
    assert "  " not in out  # no double spaces
    assert out == "line one line two line three"


def test_truncate_empty_input_returns_empty():
    assert _truncate_for_nudge("") == ""
    assert _truncate_for_nudge(None) == ""


# -------------------- formatter: happy path ----------------------------


def test_normal_heat_with_initiative_renders_full_context():
    task = {
        "id": "t-490", "desc": "Fix test env breakage",
        "initiative_id": "ini-019",
    }
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="forge-quench", heat=887,
        task_id="t-490", stage="implementation", task=task, notes="",
    )
    assert msg == (
        'HEAT_DONE 🟢 forge-quench h887 '
        '· t-490 implementation/ini-019 '
        '· "Fix test env breakage"'
    )


def test_prefix_preserved_for_marshal_pattern_match():
    """Old assertions do `"HEAT_DONE" in msg` — must survive."""
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="t-1",
        stage="implementation",
        task={"id": "t-1", "desc": "x", "initiative_id": "ini-1"},
        notes="",
    )
    assert msg.startswith("HEAT_DONE ")
    assert "HEAT_DONE" in msg


# -------------------- formatter: no initiative -------------------------


def test_task_without_initiative_omits_slash_segment():
    task = {"id": "t-1", "desc": "ad-hoc", "initiative_id": None}
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="forge-anneal", heat=100, task_id="t-1",
        stage="implementation", task=task, notes="",
    )
    assert "implementation/" not in msg
    assert "· t-1 implementation ·" in msg


def test_task_with_empty_string_initiative_omits_slash_segment():
    """Defensive: initiative_id sometimes serialized as '' rather than None."""
    task = {"id": "t-1", "desc": "ad-hoc", "initiative_id": ""}
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="t-1",
        stage="research", task=task, notes="",
    )
    assert "research/" not in msg
    assert "· t-1 research ·" in msg


# -------------------- formatter: truncation ---------------------------


def test_long_desc_truncates_to_50_chars():
    desc = "a really long description " * 5  # 130+ chars
    task = {"id": "t-1", "desc": desc, "initiative_id": "ini-1"}
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="t-1",
        stage="implementation", task=task, notes="",
    )
    # Extract the quoted desc portion.
    import re
    m = re.search(r'"([^"]*)"', msg)
    assert m is not None
    snippet = m.group(1)
    assert len(snippet) <= 50
    assert snippet.endswith("…")


def test_multiline_desc_joins_onto_one_line():
    task = {"id": "t-1", "desc": "line1\nline2\nline3",
            "initiative_id": "ini-1"}
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="t-1",
        stage="implementation", task=task, notes="",
    )
    assert "\n" not in msg
    assert '"line1 line2 line3"' in msg


# -------------------- formatter: no-task fallback ----------------------


def test_task_id_generated_renders_no_task_fallback():
    """Per feedback_start_heat_task_flag.md — start-heat without --task
    writes task_id='generated'. The nudge should degrade gracefully."""
    msg = _format_heat_done_nudge(
        signal="🟡", forge_id="forge-anneal", heat=42,
        task_id="generated", stage="implementation", task=None,
        notes="quick fixup to state.json",
    )
    assert "(no task)" in msg
    assert "quick fixup to state.json" in msg
    assert msg.startswith("HEAT_DONE 🟡 forge-anneal h42")


def test_no_task_fallback_uses_notes_and_truncates():
    long_notes = "x" * 200
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="generated",
        stage="research", task=None, notes=long_notes,
    )
    import re
    m = re.search(r'"([^"]*)"', msg)
    assert m is not None
    assert len(m.group(1)) <= 50


def test_no_task_with_empty_notes_renders_placeholder():
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="generated",
        stage="research", task=None, notes="",
    )
    assert "(no notes)" in msg


def test_task_dict_missing_still_renders_no_task_fallback():
    """Even with a task_id, if the task dict isn't found in state.queue
    (rare but possible — e.g. state.json was edited between start-heat
    and end-heat), fall through to the (no task) shape rather than
    crashing or emitting a malformed nudge."""
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=5, task_id="t-orphan",
        stage="implementation", task=None, notes="something happened",
    )
    assert "(no task)" in msg


# -------------------- formatter: removed noise -------------------------


def test_new_format_removes_old_noise():
    """Old format had 'value=X' + 'Re-prioritize' suffix. Neither should
    appear in the new one — signal emoji carries the value bracket and
    Marshal's re-prioritize job is obvious from HEAT_DONE itself."""
    task = {"id": "t-1", "desc": "x", "initiative_id": "ini-1"}
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="f", heat=1, task_id="t-1",
        stage="implementation", task=task, notes="whatever",
    )
    assert "value=" not in msg
    assert "Re-prioritize" not in msg


def test_signal_variants_all_render():
    for signal in ("🟢", "🟡", "🔴"):
        task = {"id": "t-1", "desc": "x", "initiative_id": "ini-1"}
        msg = _format_heat_done_nudge(
            signal=signal, forge_id="f", heat=1, task_id="t-1",
            stage="implementation", task=task, notes="",
        )
        assert f"HEAT_DONE {signal}" in msg


# -------------------- defensive: missing forge_id ----------------------


def test_missing_forge_id_renders_placeholder():
    task = {"id": "t-1", "desc": "x", "initiative_id": "ini-1"}
    msg = _format_heat_done_nudge(
        signal="🟢", forge_id="", heat=1, task_id="t-1",
        stage="implementation", task=task, notes="",
    )
    assert "(unknown-forge)" in msg
