"""Canonical scheduler_key three-tier invariant (t-383).

Order: promoted (hp set, hp < DEPRIO_THRESHOLD) < un-pinned (hp None)
       < deprioritized (hp >= DEPRIO_THRESHOLD).
"""

from smithy.task_detail import scheduler_key, DEPRIO_THRESHOLD, TaskSummary


def _t(tid, hp=None, priority=2):
    return {"id": tid, "human_priority": hp, "priority": priority}


class TestSchedulerKey:
    def test_unpinned_plus_deprioritized(self):
        unpinned = _t("u", hp=None)
        deprio = _t("d", hp=9999)
        assert scheduler_key(unpinned) < scheduler_key(deprio)

    def test_promoted_then_unpinned_then_deprioritized(self):
        promoted = _t("p", hp=0)
        unpinned = _t("u", hp=None)
        deprio = _t("d", hp=9999)
        tasks = [deprio, unpinned, promoted]
        tasks.sort(key=scheduler_key)
        assert [t["id"] for t in tasks] == ["p", "u", "d"]

    def test_promoted_by_hp_value(self):
        a = _t("a", hp=0)
        b = _t("b", hp=1)
        c = _t("c", hp=5)
        tasks = [c, b, a]
        tasks.sort(key=scheduler_key)
        assert [t["id"] for t in tasks] == ["a", "b", "c"]

    def test_threshold_exact_is_deprio(self):
        at_threshold = _t("at", hp=DEPRIO_THRESHOLD)
        just_below = _t("jb", hp=DEPRIO_THRESHOLD - 1)
        unpinned = _t("u", hp=None)
        tasks = [at_threshold, unpinned, just_below]
        tasks.sort(key=scheduler_key)
        assert [t["id"] for t in tasks] == ["jb", "u", "at"]

    def test_tiebreak_priority_then_id(self):
        x = _t("x", hp=None, priority=1)
        y = _t("y", hp=None, priority=0)
        z = _t("z", hp=None, priority=0)
        tasks = [x, z, y]
        tasks.sort(key=scheduler_key)
        # priority asc (0,0,1); ties (y,z both priority=0) broken by id asc.
        assert [t["id"] for t in tasks] == ["y", "z", "x"]

    def test_accepts_tasksummary(self):
        s = TaskSummary(id="t", human_priority=0, priority=1)
        d = TaskSummary(id="d", human_priority=9999, priority=1)
        assert scheduler_key(s) < scheduler_key(d)

    def test_missing_hp_key_treated_as_none(self):
        # state.json rows sometimes omit the key rather than store null.
        bare = {"id": "b", "priority": 0}
        unpinned = _t("u", hp=None, priority=0)
        # Both in bucket 1 (un-pinned); priority tie → id asc.
        assert scheduler_key(bare) < scheduler_key(unpinned)
