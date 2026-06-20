"""t-625 (ini-017): intent triple validation + description-as-intent lint in
validate_state. Vocabulary per research/intents-as-primitives.md §3 —
intent_source ∈ {t-XXX, human, auto}; intent str|null ≤ INTENT_MAX_LEN; the
overlap finding FLAGS (lint:) but does not block.
"""

from smithy.state import validate_state, VALID_STAGES, INTENT_MAX_LEN


def _base_state(queue=None, initiatives=None):
    """A minimal state that validate_state accepts cleanly, so intent findings
    are the only errors a test sees."""
    return {
        "budget": {"used": 5, "total_heats": 100},
        "stages": {s: {"progress": 0.1, "value_ema": 0.7} for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": queue or [],
        "themes": [],
        "initiatives": initiatives or [],
        "next_tasks": [],
    }


def _task(tid="t-1", **kw):
    base = {"id": tid, "status": "pending", "desc": "do the thing"}
    base.update(kw)
    return base


def _intent_errs(state):
    return [e for e in validate_state(state)
            if "intent" in e or e.startswith("lint:")]


# --- hard checks ---------------------------------------------------------

def test_valid_intent_triple_no_errors():
    st = _base_state(queue=[_task(intent="so users can recover locked accounts",
                                  intent_source="t-100")])
    assert _intent_errs(st) == []


def test_null_intent_is_ok():
    # The default (no intent set) must not error — 573/573 live tasks are null.
    assert _intent_errs(_base_state(queue=[_task()])) == []


def test_non_string_intent_errors():
    errs = validate_state(_base_state(queue=[_task(intent=123)]))
    assert any("intent must be str" in e for e in errs)


def test_intent_too_long_errors():
    errs = validate_state(_base_state(queue=[_task(intent="x" * (INTENT_MAX_LEN + 1))]))
    assert any("too long" in e for e in errs)


def test_intent_at_limit_ok():
    errs = validate_state(_base_state(queue=[_task(intent="y" * INTENT_MAX_LEN)]))
    assert not any("too long" in e for e in errs)


def test_invalid_intent_source_errors():
    # t-617's loose comment listed "anvil"/"inferred" — t-625 narrows the vocab
    # to the research-doc canonical {t-XXX, human, auto}; "anvil" is now invalid.
    errs = validate_state(_base_state(queue=[_task(intent="why", intent_source="anvil")]))
    assert any("invalid intent_source" in e for e in errs)


def test_valid_intent_source_forms():
    for src in ("t-42", "t-9", "human", "auto", None):
        st = _base_state(queue=[_task(intent="a distinct why reason here",
                                      intent_source=src)])
        assert not any("invalid intent_source" in e for e in validate_state(st)), src


# --- description-as-intent lint (flag, not block) ------------------------

def test_overlap_lint_flags_not_blocks():
    # intent restates the description → a lint: warning, NOT a hard error.
    st = _base_state(queue=[_task(desc="add OAuth login endpoint",
                                  intent="add OAuth login endpoint")])
    errs = validate_state(st)
    lints = [e for e in errs if e.startswith("lint:")]
    hard = [e for e in errs if "intent" in e and not e.startswith("lint:")]
    assert lints and "restates description" in lints[0]
    assert hard == []                         # overlap is flagged, never blocks


def test_distinct_intent_no_lint():
    st = _base_state(queue=[_task(
        desc="add OAuth login endpoint with token refresh",
        intent="so returning users skip the password prompt entirely")])
    assert not any(e.startswith("lint:") for e in validate_state(st))


def test_initiative_intent_also_validated():
    st = _base_state(initiatives=[{
        "id": "ini-1", "status": "approved", "theme_id": None,
        "description": "build the constraint board",
        "intent": "build the constraint board"}])
    errs = validate_state(st)
    assert any(e.startswith("lint:") and "ini-1" in e for e in errs)
