"""t-513 — ini-020 impl-T3: bisect_batch unit coverage.

The binary search itself, isolated from git/pytest: reset_staging_to is
monkeypatched to record which accumulated-prefix sha each probe targets,
and the test runner is injected. CLI-level behaviour (reject + green-
prefix landing + flaky retry + abort) lives in test_t511_batcher.py's
TestAssemblyBatchTickCLI.
"""

import subprocess
from pathlib import Path

import pytest

import smithy.assembly as assembly_mod
from smithy.assembly import bisect_batch


def _merged(n):
    """Synthetic run_batch 'merged' green list: sha s0..s<n-1>."""
    return [{"entry": {"task_id": f"t-{i}", "forge_id": "forge-01"},
             "sha": f"s{i}", "status": "clean"} for i in range(n)]


@pytest.fixture
def probe_log(monkeypatch):
    """Patch reset_staging_to to a recorder; return the log of shas."""
    log = []

    def fake_reset(wt, ref):
        log.append(ref)
        return {"status": "ready"}

    monkeypatch.setattr(assembly_mod, "reset_staging_to", fake_reset)
    return log


def test_offender_at_index_2_of_4(probe_log):
    """Acceptance §(a): N=4, offender at index 2 → exactly 2 probes,
    green prefix [0, 1], offender isolated at 2."""
    merged = _merged(4)

    def run_tests(wt):
        # Tests pass iff the probed prefix tip is before the offender.
        idx = int(probe_log[-1][1:])
        return {"passed": idx < 2, "returncode": 0 if idx < 2 else 1,
                "output": ""}

    res = bisect_batch(Path("/unused"), merged, run_tests=run_tests)
    assert res["status"] == "isolated"
    assert res["offender_index"] == 2
    assert res["offender"]["entry"]["task_id"] == "t-2"
    assert [m["entry"]["task_id"] for m in res["green_prefix"]] == \
        ["t-0", "t-1"]
    assert res["probes"] == 2
    # Probe shas: mid=1 (pass) then mid=2 (fail).
    assert probe_log == ["s1", "s2"]


def test_offender_at_index_0_of_4(probe_log):
    """Acceptance §(b): offender first → empty green prefix."""
    merged = _merged(4)

    def run_tests(wt):
        return {"passed": False, "returncode": 1, "output": ""}

    res = bisect_batch(Path("/unused"), merged, run_tests=run_tests)
    assert res["status"] == "isolated"
    assert res["offender_index"] == 0
    assert res["green_prefix"] == []
    assert res["probes"] == 2  # mid=1 red, mid=0 red


def test_offender_last_of_4(probe_log):
    """All probes green → offender is the final entry, prefix = rest."""
    merged = _merged(4)

    def run_tests(wt):
        return {"passed": True, "returncode": 0, "output": ""}

    res = bisect_batch(Path("/unused"), merged, run_tests=run_tests)
    assert res["status"] == "isolated"
    assert res["offender_index"] == 3
    assert len(res["green_prefix"]) == 3
    assert res["probes"] == 2  # mid=1, mid=2


def test_n2_single_probe(probe_log):
    """N=2 needs exactly one probe."""
    merged = _merged(2)

    def run_tests(wt):
        return {"passed": True, "returncode": 0, "output": ""}

    res = bisect_batch(Path("/unused"), merged, run_tests=run_tests)
    assert res["offender_index"] == 1
    assert res["probes"] == 1


def test_probe_timeout_returns_error(probe_log):
    """Acceptance §(d): a pytest timeout mid-bisect aborts with
    status=error so the caller can reset staging and keep the queue."""
    merged = _merged(4)

    def run_tests(wt):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=600)

    res = bisect_batch(Path("/unused"), merged, run_tests=run_tests)
    assert res["status"] == "error"
    assert "timeout" in res["detail"]
    assert res["probes"] == 1


def test_reset_failure_returns_error(monkeypatch):
    """A failed staging reset is an abort, not a misattributed reject."""
    monkeypatch.setattr(
        assembly_mod, "reset_staging_to",
        lambda wt, ref: {"status": "error", "detail": "boom"},
    )
    merged = _merged(4)
    res = bisect_batch(Path("/unused"), merged,
                       run_tests=lambda wt: {"passed": True})
    assert res["status"] == "error"
    assert "boom" in res["detail"]
