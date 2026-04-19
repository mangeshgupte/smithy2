"""t-487 (ini-023 T8): Comms daily file rollover.

`smithy comms-snapshot` exposes three new fields:
  today_report_path         — absolute path to today's UTC-dated
                              YYYY-MM-DD.md under personas/comms/reports/
  today_date                — today's UTC date as YYYY-MM-DD
  is_first_section_of_day   — true when today's file is missing OR
                              contains no `## YYYY-MM-DD HH:MM UTC …`
                              headers yet (prior wake sections)

Comms reads these and renders `Δ vs prior` cells as `first of day`
when the flag is true, never touching yesterday's file. This test
module verifies the CLI contract; the LLM-driven report composition
is covered by the personas/comms/CLAUDE.md protocol doc.

Acceptance covered:
  (a) midnight crossing creates new file: fresh UTC date → fresh path
  (b) prior file untouched: writing today's file doesn't mutate
      yesterday's
  (c) is_first_section_of_day renders Δ correctly (doc assertion)
  (d) rapid wakes around midnight don't corrupt either file — we
      test by appending a section to yesterday's file then calling
      snapshot; today's `is_first_section_of_day` must still be true
      because the detection is keyed on today's file only
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(proj, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli",
         "--dir", str(proj), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _snap(proj):
    rc, out, err = _smithy(proj, "comms-snapshot")
    assert rc == 0, f"stderr: {err}"
    return json.loads(out)


@pytest.fixture
def proj(tmp_path):
    """Minimal state.json so `comms-snapshot` has something to report."""
    p = tmp_path / "p"
    rc, _, err = _smithy(tmp_path, "init", "p", "--target", str(p))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    return p


# ---------- snapshot surfaces the three new fields -------------------------


def test_snapshot_exposes_today_report_path(proj):
    snap = _snap(proj)
    assert "today_report_path" in snap
    assert snap["today_report_path"].endswith(".md")
    assert "personas/comms/reports/" in snap["today_report_path"]


def test_snapshot_today_date_is_utc(proj):
    snap = _snap(proj)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert snap["today_date"] == today
    # Path filename matches today_date.
    assert snap["today_report_path"].endswith(f"{today}.md")


# ---------- is_first_section_of_day semantics ----------------------------


def test_first_section_true_when_file_missing(proj):
    snap = _snap(proj)
    # Fresh scaffold — no report file yet.
    assert not Path(snap["today_report_path"]).exists()
    assert snap["is_first_section_of_day"] is True


def test_first_section_true_when_file_has_only_day_banner(proj):
    """A file with just `# 2026-04-19` header but no wake sections is
    still first-of-day."""
    snap = _snap(proj)
    path = Path(snap["today_report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {snap['today_date']}\n\n")
    snap2 = _snap(proj)
    assert snap2["is_first_section_of_day"] is True


def test_first_section_false_after_a_wake_section_is_appended(proj):
    """One `## YYYY-MM-DD HH:MM UTC …` header flips the flag off."""
    snap = _snap(proj)
    path = Path(snap["today_report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {snap['today_date']}\n\n"
        f"## {snap['today_date']} 09:00 UTC · heat 100/1543 (6.5% used)\n"
        "first wake body here\n"
        "---\n"
    )
    snap2 = _snap(proj)
    assert snap2["is_first_section_of_day"] is False


# ---------- rollover + rapid-wakes safety --------------------------------


def test_rollover_yesterdays_file_is_not_touched(proj):
    """(a) midnight crossing creates a new file; (b) the prior day's
    file is not rewritten. We can't force the system clock, so we
    simulate by creating yesterday's file with content and checking
    its mtime + content stays fixed after a snapshot."""
    snap = _snap(proj)
    today = snap["today_date"]
    yesterday_str = (datetime.strptime(today, "%Y-%m-%d") -
                     timedelta(days=1)).strftime("%Y-%m-%d")
    reports_dir = Path(snap["today_report_path"]).parent
    reports_dir.mkdir(parents=True, exist_ok=True)
    ypath = reports_dir / f"{yesterday_str}.md"
    ypath.write_text(
        f"# {yesterday_str}\n\n"
        f"## {yesterday_str} 23:55 UTC · heat 99/1543\n"
        "last wake of yesterday\n---\n"
    )
    before = ypath.read_text()
    before_mtime = ypath.stat().st_mtime
    # Call snapshot — which targets today's path, not yesterday's.
    snap2 = _snap(proj)
    assert snap2["today_date"] == today  # unchanged
    # Yesterday untouched.
    assert ypath.read_text() == before
    assert ypath.stat().st_mtime == before_mtime


def test_rapid_wakes_same_day_do_not_flip_first_of_day(proj):
    """Two snapshots in the same second must agree on
    `is_first_section_of_day` — the flag is keyed on the file's
    contents, not on elapsed time. Regression guard against any
    future "N seconds since last wake" heuristic sneaking in."""
    snap1 = _snap(proj)
    snap2 = _snap(proj)
    assert snap1["is_first_section_of_day"] == snap2["is_first_section_of_day"]
    assert snap1["today_report_path"] == snap2["today_report_path"]


def test_todays_file_detection_ignores_yesterdays_content(proj):
    """Yesterday having several wake sections must NOT make today's
    `is_first_section_of_day` flip to false. The check reads today's
    file only."""
    snap = _snap(proj)
    today = snap["today_date"]
    yesterday_str = (datetime.strptime(today, "%Y-%m-%d") -
                     timedelta(days=1)).strftime("%Y-%m-%d")
    reports_dir = Path(snap["today_report_path"]).parent
    reports_dir.mkdir(parents=True, exist_ok=True)
    ypath = reports_dir / f"{yesterday_str}.md"
    ypath.write_text(
        f"# {yesterday_str}\n\n"
        f"## {yesterday_str} 09:00 UTC · heat 50/1543\n body\n---\n"
        f"## {yesterday_str} 12:00 UTC · heat 80/1543\n body\n---\n"
    )
    # Today still has no file → first of day.
    snap2 = _snap(proj)
    assert snap2["is_first_section_of_day"] is True


# ---------- protocol doc contract ----------------------------------------


def test_comms_protocol_doc_references_first_of_day_literal():
    """personas/comms/CLAUDE.md documents the rollover contract so
    the LLM renders Δ cells correctly without re-deriving the rules."""
    doc = (REPO_ROOT / "personas" / "comms" / "CLAUDE.md").read_text()
    # The literal text Comms should write into Δ cells on the first
    # section of the day.
    assert "first of day" in doc
    # The snapshot fields Comms should consume.
    assert "today_report_path" in doc
    assert "is_first_section_of_day" in doc


def test_comms_protocol_doc_forbids_writing_yesterdays_file():
    doc = (REPO_ROOT / "personas" / "comms" / "CLAUDE.md").read_text()
    # Key instruction: never touch yesterday's file.
    assert "yesterday" in doc.lower()
    assert "immutable archive" in doc or "immutable" in doc
