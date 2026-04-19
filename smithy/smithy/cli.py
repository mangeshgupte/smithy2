"""Smithy CLI — deterministic bookkeeping for The Forge."""

import json
import sys
import click
from datetime import datetime, timezone
from pathlib import Path

from .state import (
    find_project_root, load_state, save_state, validate_state,
    append_worklog, write_checkpoint, delete_checkpoint,
    forge_checkpoint_path, DEFAULT_FORGE_ID,
    primary_forge_id, detect_forge_from_cwd, main_repo_root,
    assembly_queue_path, worklog_path, state_lock, normalize_human_priority,
    VALID_STAGES, VALID_SIGNALS, VALID_OUTCOMES,
)
from .task_detail import scheduler_key

# t-414: base set for Click type=Choice defaults. The *runtime* valid set is
# dynamic — includes every Forge id from state.parallel.forges[] — so new
# Forge verbs (temper, anneal, draw, …) don't need a code edit. Commands that
# accept a persona argument use `type=str` + `_validate_persona(state, ...)`
# instead of `type=click.Choice(...)` so they accept "forge-quench" and peers.
VALID_PERSONAS = ["forge", "marshal", "anvil", "chisel", "assembly"]


def _all_personas(state):
    """t-414: dynamic valid-persona set. Base is the fixed roster plus every
    Forge id registered in state.parallel.forges[]. Used to validate
    arguments to CLI commands that route nudges."""
    names = set(VALID_PERSONAS)
    for f in (state.get("parallel") or {}).get("forges") or []:
        fid = f.get("id")
        if fid:
            names.add(fid)
    return names


def _validate_persona(state, persona, arg_name="persona"):
    """Raise click.BadParameter if persona isn't in the dynamic valid set."""
    valid = _all_personas(state)
    if persona not in valid:
        raise click.BadParameter(
            f"{persona!r} is not a valid persona; expected one of "
            f"{sorted(valid)}",
            param_hint=arg_name,
        )


def _pick_priority_signal(state: dict, task: dict) -> str:
    """Pick one terse signal explaining why this task earned its rank.

    Vocabulary (per t-313 spec): recency | poker | stage-balance | blocked-deps-clear.
    One signal per reason string. Order of precedence:
    - blocked-deps-clear: dependencies just cleared (all blocked_by are complete)
    - poker: initiative ranked in the top 3
    - recency: initiative viewed_at set (human looked at it recently)
    - stage-balance: task's stage is underweight vs target (heats-per-target ratio)
    """
    queue = state.get("queue", [])
    complete_ids = {t["id"] for t in queue if t.get("status") == "complete"}
    blocked = task.get("blocked_by") or []
    if blocked and all(b in complete_ids for b in blocked):
        return "blocked-deps-clear"

    ini_id = task.get("initiative_id")
    if ini_id:
        ini = next((i for i in state.get("initiatives", []) if i["id"] == ini_id), None)
        if ini:
            if isinstance(ini.get("rank"), int) and ini["rank"] <= 3:
                return "poker"
            if ini.get("viewed_at"):
                return "recency"

    stages = state.get("stages", {})
    stage_name = task.get("stage", "")
    s = stages.get(stage_name, {})
    target = s.get("target", 0)
    heats = s.get("heats", 0)
    used = state.get("budget", {}).get("used", 0) or 1
    actual = heats / used if used else 0
    if target > 0 and actual < target * 0.9:
        return "stage-balance"

    return "stage-balance"


def _build_priority_reason(state: dict, task: dict) -> str:
    """Format an auto-reason string ≤40 chars: 'ini-XXX rank=N + <signal>' or 'p{N} + <signal>'."""
    signal = _pick_priority_signal(state, task)
    ini_id = task.get("initiative_id")
    if ini_id:
        ini = next((i for i in state.get("initiatives", []) if i["id"] == ini_id), None)
        rank = ini.get("rank", "?") if ini else "?"
        reason = f"{ini_id} rank={rank} + {signal}"
    else:
        reason = f"p{task.get('priority', 2)} + {signal}"
    return reason[:40]


def _reset_worktree_on_reject(root, forge_id):
    """t-439: discard uncommitted WIP in the Forge's worktree after the
    pre-submit gate rejects. Runs `git reset --hard HEAD` + `git clean
    -fdx -e .venv` in the worktree. Never raises into end-heat —
    reject-path cleanup must not mask the original test failure.

    t-562 hardening:
    - `.venv/` is excluded from the clean. `-x` removes IGNORED files,
      so every reject used to silently delete the worktree venv — the
      next gate then failed on ImportError and the rejects compounded
      (April's reject spiral; temper's mid-session venv loss
      2026-06-13). `-x` is kept for pyc/scratch; the env survives.
    - The silent fallback to `root` is GONE. When the worktree path
      doesn't resolve, we log and skip cleanup — running `clean -fdx`
      at the main repo root would eat untracked coordination files
      (.assembly-queue.jsonl, .smithy-nudge-queue/, checkpoints)."""
    import subprocess
    wt = main_repo_root(root) / ".worktrees" / (forge_id or "")
    if not (forge_id and wt.exists() and (wt / ".git").exists()):
        _err(f"reject-cleanup skipped: no worktree for {forge_id!r} "
             f"at {wt} (t-562 — never clean the main repo root)")
        return
    try:
        subprocess.run(["git", "reset", "--hard", "HEAD"],
                       cwd=str(wt), capture_output=True, text=True,
                       timeout=30)
        subprocess.run(["git", "clean", "-fdx", "-e", ".venv"],
                       cwd=str(wt), capture_output=True, text=True,
                       timeout=30)
        _err(f"worktree reset to HEAD + cleaned (t-439 reject-cleanup, "
             f".venv preserved)")
    except Exception as exc:
        _err(f"worktree reset failed ({exc}); inspect manually")


def _run_presubmit_tests(root, forge_id, tests_cmd=None, timeout_s=600):
    """t-427: run the project's pytest suite in the Forge's worktree,
    returning `{"passed": bool, "output": str}`. Used as a hard gate in
    end-heat before a task is handed off to Assembly — a Forge that
    submits red tests used to burn an Assembly rebase + rerun cycle
    (observed with t-425 and t-423 on 2026-04-17). Now the Forge sees
    the red locally and re-iterates the next heat.

    Command precedence: explicit --tests-cmd > SMITHY_TESTS_CMD env >
    the shipped default `python3 -m pytest -q smithy/tests/ tests/`,
    which catches BOTH legacy test paths in this repo. Subprocess runs
    from inside the Forge's worktree so it exercises the rebased tree,
    not main's working copy.
    """
    import os
    import shlex
    import subprocess
    cmd = tests_cmd or os.environ.get(
        "SMITHY_TESTS_CMD",
        "python3 -m pytest -q smithy/tests/ tests/",
    )
    wt = main_repo_root(root) / ".worktrees" / (forge_id or "")
    cwd = wt if (forge_id and wt.exists() and (wt / ".git").exists()) else root
    # t-489: if the default command starts with bare `python3`, rewrite
    # it to the cwd's `.venv/bin/python3` when present so the pytest
    # subprocess imports `smithy` from the worktree's own editable
    # install, not the system's (main-bound) one. An explicit override
    # via --tests-cmd / SMITHY_TESTS_CMD is respected verbatim.
    argv = shlex.split(cmd)
    if tests_cmd is None and argv and argv[0] == "python3":
        venv_py = Path(cwd) / ".venv" / "bin" / "python3"
        if venv_py.exists():
            argv[0] = str(venv_py)
    try:
        r = subprocess.run(
            argv, cwd=str(cwd),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "returncode": None,
                "output": f"tests timed out after {timeout_s}s",
                "cmd": cmd, "cwd": str(cwd)}
    return {
        "passed": r.returncode == 0,
        "returncode": r.returncode,
        "output": (r.stdout + r.stderr),
        "cmd": cmd,
        "cwd": str(cwd),
    }


# t-427: stages where end-heat skips the pre-submit gate. Research /
# planning / marketing heats produce prose + notes, not code, so
# pytest on them would be pure overhead. Testing / implementation /
# editing all touch code and must go through the gate.
_NO_GATE_STAGES = {"research", "planning", "marketing"}


def _ensure_task_branch(root, forge_id, task_id):
    """t-420: checkout `<forge_id>/<task_id>` off main if not already there.

    Returns a dict describing the change (or the already-on-branch state)
    so start-heat can include it in its JSON output. Exits the process
    with a clear error when the worktree has uncommitted changes — we
    never silently reset a Forge's in-progress work; the operator commits
    or passes --reuse-scratch.
    """
    import subprocess
    expected = f"{forge_id}/{task_id}"
    cur = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(root), capture_output=True, text=True,
    ).stdout.strip()
    if cur == expected:
        return {"branch": expected, "created": False, "from": cur}

    # Refuse to move if the worktree has uncommitted changes — that's
    # someone's in-progress task work and the switch would either abort
    # or clobber it.
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(root), capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        _output({
            "error": "worktree has uncommitted changes — commit them or "
                     "pass --reuse-scratch before start-heat",
            "current_branch": cur,
            "would_switch_to": expected,
            "dirty_files": [line[3:] for line in dirty.splitlines()][:20],
        })
        sys.exit(1)

    r = subprocess.run(
        ["git", "checkout", "-B", expected, "main"],
        cwd=str(root), capture_output=True, text=True,
    )
    if r.returncode != 0:
        _output({
            "error": f"git checkout -B {expected} main failed",
            "stderr": r.stderr.strip(),
            "hint": "ensure main is fast-forwardable here "
                    "(git fetch origin main), or pass --reuse-scratch",
        })
        sys.exit(1)
    return {"branch": expected, "created": True, "from": cur}


def _rebind_smithy_install(root, sha):
    """t-460: post-merge hook — re-run `pip install -e` from the MAIN
    repo's smithy/ if the merged commit touched smithy code.

    The editable install is global (one .pth file shared across all
    panes). Whichever pane last ran `pip install -e` wins. After
    Assembly merges new smithy/ code into main, we proactively rebind
    the install to main so all panes (including Assembly's own next
    pytest run) import the freshly merged code, not whatever stale
    worktree the .pth currently points at.

    Best-effort: never raises. Skipped when the merge didn't touch
    smithy/ paths, or when SMITHY_SKIP_INSTALL_REBIND=1 is set (CI /
    test fixtures don't want a real pip call)."""
    import os
    import subprocess
    if os.environ.get("SMITHY_SKIP_INSTALL_REBIND"):
        return {"rebound": False, "reason": "SMITHY_SKIP_INSTALL_REBIND set"}
    main_root = main_repo_root(root)
    smithy_pkg = main_root / "smithy"
    if not (smithy_pkg / "pyproject.toml").exists():
        return {"rebound": False, "reason": "no main smithy/pyproject.toml"}
    try:
        diff = subprocess.run(
            ["git", "show", "--stat", "--name-only", "--format=", sha],
            cwd=str(main_root), capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:
        return {"rebound": False, "reason": f"git show failed: {exc}"}
    touched = [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]
    if not any(p.startswith("smithy/") for p in touched):
        return {"rebound": False, "reason": "merge didn't touch smithy/"}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(smithy_pkg),
             "--user", "--quiet"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:
        return {"rebound": False, "reason": f"pip install failed: {exc}"}
    if result.returncode != 0:
        return {"rebound": False,
                "reason": f"pip rc={result.returncode}: {result.stderr[:120]}"}
    return {"rebound": True, "target": str(smithy_pkg), "sha": sha[:12]}


def _rig_events_path(root):
    """t-425: canonical rig-events.jsonl path — append-only telemetry at
    the MAIN repo root. Gitignored."""
    return main_repo_root(root) / "rig-events.jsonl"


def _detect_stalled_forges(root, state, stall_s):
    """t-462: correlate queue_push events with queue_pop / forge_started
    to find Forges that are ignoring pushes — dead-between-heats Forges
    that look idle to patrol's heartbeat check.

    Returns list of dicts: [{forge_id, task_id, pushed_at, age_s}, ...].

    Algorithm:
      1. Tail the last 500 rig events (bounded I/O, plenty of context).
      2. For each queue_push, look up the task's assigned_forge in state
         and record (task_id, forge_id, push_ts).
      3. For each forge, compute the last activity timestamp from
         queue_pop (actor=forge) or forge_started (actor=forge).
      4. Flag a forge if it has a push newer than its last activity AND
         that push is older than stall_s AND the forge is currently idle
         (busy forges with stale pushes are mid-heat, not stalled).
    """
    path = _rig_events_path(root)
    if not path.exists():
        return []

    try:
        lines = path.read_text().splitlines()[-500:]
    except OSError:
        return []
    events = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            continue

    assigned = {}
    for t in state.get("queue") or []:
        tid = t.get("id")
        if tid:
            assigned[tid] = t.get("assigned_forge")

    now = datetime.now(timezone.utc)

    def _parse_ts(s):
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            return None

    last_activity = {}
    latest_push = {}
    for ev in events:
        ev_type = ev.get("event")
        ts = _parse_ts(ev.get("ts"))
        if not ts:
            continue
        if ev_type == "queue_push":
            tid = ev.get("task_id")
            fid = assigned.get(tid)
            if fid and (fid not in latest_push or ts > latest_push[fid]["ts"]):
                latest_push[fid] = {"ts": ts, "task_id": tid}
        elif ev_type in ("queue_pop", "forge_started"):
            actor = ev.get("actor") or ev.get("forge_id")
            if actor and (actor not in last_activity
                          or ts > last_activity[actor]):
                last_activity[actor] = ts

    parallel = state.get("parallel") or {}
    forges_by_id = {f.get("id"): f for f in parallel.get("forges") or []}

    stalled = []
    for fid, push in latest_push.items():
        activity_ts = last_activity.get(fid)
        if activity_ts and activity_ts >= push["ts"]:
            continue
        age_s = (now - push["ts"]).total_seconds()
        if age_s <= stall_s:
            continue
        forge = forges_by_id.get(fid) or {}
        if forge.get("status") != "idle":
            continue
        stalled.append({
            "forge_id": fid,
            "task_id": push["task_id"],
            "pushed_at": push["ts"].isoformat(),
            "age_s": round(age_s, 1),
        })

    return sorted(stalled, key=lambda x: x["forge_id"])


def _detect_starving_forges(state):
    """t-491 (ini-019): complement to _detect_stalled_forges.

    _detect_stalled_forges catches 'Marshal pushed, Forge ignored' — a
    Forge-side wedge. It cannot see 'Marshal stopped pushing, queue has
    work' because that path has no queue_push event to anchor on.

    Observed 2026-04-18 heat 887: forge-anneal idle, next_tasks=[], 9
    pending tasks in queue, halt off, budget remaining → patrol clean.
    Marshal had simply stopped dispatching. This detector surfaces that
    shape from a single state.json snapshot, no event correlation needed.

    Conditions for a forge to be flagged 'starving':
      - forge.status == 'idle' AND forge.current_task is falsy
      - parallel.halt_flag is False (otherwise idle is expected)
      - budget remaining > 0 (otherwise idle is end-of-run)
      - next_tasks is empty (nothing already dispatched and waiting)
      - queue has at least one pending task that this forge could take
        (unassigned, or assigned to this forge)

    The last clause avoids false positives when the queue contains only
    tasks pinned to a *different* forge — that forge is the one Marshal
    should dispatch to, not this one.

    Returns a list of dicts: [{forge_id, pending_count, ...}, ...]
    """
    parallel = state.get("parallel") or {}
    if parallel.get("halt_flag"):
        return []

    budget = state.get("budget") or {}
    total = budget.get("total_heats", 0) or 0
    used = budget.get("used", 0) or 0
    if total > 0 and used >= total:
        return []

    next_tasks = state.get("next_tasks") or []
    if next_tasks:
        # Something is already dispatched — whichever Forge's turn it is
        # will pick it up. Not starvation.
        return []

    queue = state.get("queue") or []
    pending = [t for t in queue if t.get("status") == "pending"]
    if not pending:
        return []

    starving = []
    for forge in parallel.get("forges") or []:
        fid = forge.get("id")
        if not fid:
            continue
        if forge.get("status") != "idle" or forge.get("current_task"):
            continue
        # Count tasks this forge could actually take: unassigned, or
        # pinned to this forge.
        eligible = [
            t for t in pending
            if not t.get("assigned_forge") or t.get("assigned_forge") == fid
        ]
        if not eligible:
            continue
        starving.append({
            "forge_id": fid,
            "pending_count": len(eligible),
            "queue_total_pending": len(pending),
        })

    return sorted(starving, key=lambda x: x["forge_id"])


def _emit_rig_event(root, event, **fields):
    """t-425: append one JSON line to rig-events.jsonl.

    Never raises into callers — telemetry must not break heat execution.
    Each row: `{"ts": ISO8601, "event": str, ...fields}`. Consumers
    (rig-replay, future dashboards) tolerate unknown fields so new
    emitters can add their own without a schema bump."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
        }
        for k, v in fields.items():
            if v is not None:
                entry[k] = v
        path = _rig_events_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _output(data: dict):
    """Print JSON to stdout (for LLM consumption)."""
    click.echo(json.dumps(data, indent=2))


def _err(msg: str):
    """Print to stderr (for human debugging)."""
    click.echo(msg, err=True)


@click.group()
@click.option("--dir", "project_dir", default=".", help="Project directory")
@click.pass_context
def cli(ctx, project_dir):
    """Smithy — bookkeeping CLI for The Forge."""
    ctx.ensure_object(dict)
    try:
        ctx.obj["root"] = find_project_root(project_dir)
    except FileNotFoundError:
        ctx.obj["root"] = Path(project_dir).resolve()


@cli.command("start-heat")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.option("--task", "task_id", default=None, help="Task ID to work on")
@click.option("--forge", "forge_id", default=None,
              help="t-409 H1: Forge id (defaults to cwd's worktree; primary if cwd is main).")
@click.option("--reuse-scratch", "reuse_scratch", is_flag=True, default=False,
              help="t-420: skip the per-task branch checkout and commit on "
                   "the worktree's current branch. Escape hatch for the "
                   "rare case where stacking commits on scratch is the goal.")
@click.pass_context
def start_heat(ctx, stage, task_id, forge_id, reuse_scratch):
    """Start a new heat. Sets task to in_progress, writes checkpoint."""
    root = ctx.obj["root"]
    # t-409 H1: resolve forge id — explicit flag wins, else detect from cwd,
    # else fall back to primary (lets main-root smoke-runs still work).
    explicit_forge = forge_id is not None
    detected_forge = None
    if forge_id is None:
        detected_forge = detect_forge_from_cwd(root)
        forge_id = detected_forge or primary_forge_id(root)

    # t-542: the task's `assigned_forge` pin is truth — cwd detection is
    # a heuristic that fails when a pane invokes smithy from outside its
    # worktree (observed h1222: forge-anneal's start-heat fell back to
    # primary and clobbered forge-quench's .forge-checkpoint.json).
    # Cross-check the pin BEFORE any checkpoint write:
    #   - pin matches resolution → proceed;
    #   - pin set, resolution came from the primary FALLBACK (no explicit
    #     flag, no cwd match) → adopt the pin;
    #   - pin set and contradicts an explicit flag or a positive cwd
    #     detection → refuse; that's another forge's task.
    if task_id:
        try:
            _peek = load_state(root)
        except Exception:
            _peek = {}
        _t = next((t for t in _peek.get("queue", []) or []
                   if t.get("id") == task_id), None)
        pinned = _t.get("assigned_forge") if _t else None
        if pinned and pinned != forge_id:
            if explicit_forge or detected_forge:
                _output({
                    "error": f"Task {task_id} is pinned to {pinned} but this "
                             f"start-heat resolved forge_id={forge_id} "
                             f"({'--forge flag' if explicit_forge else 'cwd detection'}). "
                             "Refusing — a cross-forge write would clobber "
                             "another Forge's checkpoint.",
                    "pinned_forge": pinned,
                    "resolved_forge": forge_id,
                })
                sys.exit(1)
            forge_id = pinned
            _err(f"forge_id adopted from task pin: {pinned} "
                 "(cwd detection failed; primary fallback overridden, t-542)")

    # t-473: reject ghost-submit-producing invocations. A `start-heat`
    # without `--task` from within a Forge worktree writes
    # task_id="generated" into the checkpoint; end-heat then has no
    # per-task branch to submit (t-420 enforcement), silently consumes
    # a budget heat, and fires a spurious HEAT_DONE nudge. Root-cause
    # of the 15+ "task_id=generated" events seen on 2026-04-18. Main-
    # repo smoke runs (tests, one-offs) are left alone — they have no
    # Forge worktree and never trip the ghost path. `--reuse-scratch`
    # is the explicit opt-out for the rare stack-on-scratch case.
    if task_id is None and not reuse_scratch:
        main_root = main_repo_root(root)
        if root.resolve() != main_root.resolve():
            _output({
                "error": "start-heat without --task in a Forge worktree "
                         "would ghost-submit (no per-task branch). "
                         "Run `smithy queue-pop` first, or pass "
                         "`--reuse-scratch` for the rare stack-on-scratch case.",
                "forge_id": forge_id,
                "cwd_worktree": str(root),
            })
            sys.exit(1)

    # t-420: per-task branch enforcement runs BEFORE the lock so a slow
    # git checkout never blocks a sibling Forge's heat transition. The
    # branch op only touches filesystem, not state.json.
    branch_change = None
    if task_id and not reuse_scratch:
        main_root = main_repo_root(root)
        if root.resolve() != main_root.resolve():
            branch_change = _ensure_task_branch(root, forge_id, task_id)

    # t-426: bump budget.used INSIDE the lock so two concurrent
    # start-heats don't both compute heat=N+1 from the same snapshot
    # and collide on the checkpoint. Used to happen at end-heat, which
    # was the lost-update race (see task description evidence).
    task_desc = None
    with state_lock(root):
        state = load_state(root)
        budget = state["budget"]

        # t-395 I0: halt flag checked inside the lock so a concurrent
        # halt-rig either sees this start-heat or we see the halt.
        parallel = state.get("parallel") or {}
        if parallel.get("halt_flag"):
            _output({
                "error": "Rig is halted — new heats blocked",
                "halted_at": parallel.get("halted_at"),
                "reason": parallel.get("halt_reason"),
                "hint": "smithy resume-rig to clear",
            })
            sys.exit(1)

        if budget["used"] >= budget["total_heats"]:
            _output({"error": "Budget exhausted", "used": budget["used"],
                     "total": budget["total_heats"]})
            sys.exit(1)

        heat_number = budget["used"] + 1
        budget["used"] = heat_number  # t-426: atomic bump.

        # Set task to in_progress if specified
        if task_id:
            for task in state.get("queue", []):
                if task["id"] == task_id:
                    # t-543: claim-task (ini-024 T2) flips a task to
                    # in_progress BEFORE start-heat runs, so the documented
                    # claim→start flow used to die on the pending-only
                    # check. Accept in_progress when WE are the claimer
                    # (idempotent re-entry); reject a sibling's claim, and
                    # reject unattributed in_progress — no sanctioned path
                    # leaves a claim unstamped, so that's an orphan for
                    # patrol, not a startable heat.
                    if task["status"] == "in_progress":
                        claimer = task.get("assigned_forge")
                        if claimer != forge_id:
                            _output({
                                "error": f"Task {task_id} is in_progress, "
                                         f"claimed by {claimer or 'nobody'} "
                                         f"(you are {forge_id})"
                                         + ("" if claimer else
                                            " — run `smithy patrol --fix` "
                                            "to reap the orphan"),
                                "claimed_by": claimer,
                                "forge_id": forge_id,
                            })
                            sys.exit(1)
                    elif task["status"] != "pending":
                        _output({"error": f"Task {task_id} is {task['status']}, not pending"})
                        sys.exit(1)
                    task["status"] = "in_progress"
                    task_desc = task["desc"]
                    break
            else:
                _output({"error": f"Task {task_id} not found in queue"})
                sys.exit(1)

        # t-544: keep the registry honest — patrol's orphan-checkpoint
        # heuristic reads parallel.forges[].status, and a stale "idle"
        # there got live checkpoints deleted mid-heat (h1221/h1230 on
        # 2026-06-12). Stamp busy + current task/heat at heat start.
        for _f in (state.get("parallel") or {}).get("forges") or []:
            if _f.get("id") == forge_id:
                _f["status"] = "busy"
                _f["current_task"] = task_id
                _f["current_heat"] = heat_number
                _f["last_heartbeat"] = datetime.now(
                    timezone.utc).isoformat(timespec="seconds")
                break

        save_state(root, state)
        total_heats = budget["total_heats"]

    write_checkpoint(root, heat_number, stage, task_id or "generated",
                     forge_id=forge_id)

    result = {
        "heat": heat_number,
        "stage": stage,
        "task_id": task_id,
        "task_desc": task_desc,
        "forge_id": forge_id,
        "budget_remaining": total_heats - heat_number,
    }
    if branch_change:
        result["branch"] = branch_change
    _emit_rig_event(root, "forge_started", actor=forge_id, forge_id=forge_id,
                    task_id=task_id, stage=stage, heat=heat_number)
    _output(result)
    _err(f"Heat {heat_number} [{stage}] started as {forge_id}"
         + (f" — {task_desc}" if task_desc else ""))


@cli.command("end-heat")
@click.argument("value", type=float)
@click.argument("signal", type=click.Choice(VALID_SIGNALS))
@click.argument("notes")
@click.option("--outcome", type=click.Choice(VALID_OUTCOMES), default="complete")
@click.option("--progress", type=float, default=None, help="Stage progress override (0-1)")
@click.option("--no-nudge", is_flag=True, default=False, help="Skip auto-nudge to marshal")
@click.option("--forge", "forge_id", default=None,
              help="t-409 H1: Forge id (defaults to cwd's worktree; primary if cwd is main).")
@click.option("--skip-tests", "skip_tests", is_flag=True, default=False,
              help="t-427: bypass the pre-submit pytest gate. Use only when "
                   "you've already run tests or the heat genuinely didn't "
                   "touch code.")
@click.option("--tests-cmd", "tests_cmd", default=None,
              help="t-427: override the pre-submit test command (default "
                   "`python3 -m pytest -q smithy/tests/ tests/`).")
@click.pass_context
def end_heat(ctx, value, signal, notes, outcome, progress, no_nudge, forge_id,
             skip_tests, tests_cmd):
    """End the current heat. Updates all counters and logs."""
    root = ctx.obj["root"]

    # t-409 H1: resolve forge id the same way start-heat does so the
    # matching per-Forge checkpoint is read.
    if forge_id is None:
        forge_id = detect_forge_from_cwd(root) or primary_forge_id(root)

    # Read checkpoint (per-Forge, anchored at main repo root).
    cp_path = forge_checkpoint_path(root, forge_id)
    if not cp_path.exists():
        _output({"error": f"No checkpoint found for {forge_id} at {cp_path.name}"
                          f" — did you start a heat?"})
        sys.exit(1)
    checkpoint = json.loads(cp_path.read_text())

    heat = checkpoint["heat"]
    stage = checkpoint["stage"]
    task_id = checkpoint["task_id"]

    # t-399 I4: two-row lifecycle gate. When Assembly is enabled, a
    # "complete" end-heat is really a "submitted" hand-off. Read the
    # config OUTSIDE the state lock — it doesn't change during a heat.
    state_peek = load_state(root)

    # t-542: poisoned-checkpoint guard. If the checkpoint we just read
    # carries a task pinned to a DIFFERENT forge, a cross-write happened
    # (another forge's start-heat resolved to our path). Completing it
    # would attribute their heat to us and delete their recovery state —
    # refuse and point at patrol instead.
    if task_id and task_id != "generated":
        _t = next((t for t in state_peek.get("queue", []) or []
                   if t.get("id") == task_id), None)
        _pin = _t.get("assigned_forge") if _t else None
        if _pin and _pin != forge_id:
            _output({
                "error": f"Checkpoint at {cp_path.name} carries task "
                         f"{task_id} pinned to {_pin}, not {forge_id} — "
                         "cross-forge checkpoint write suspected. Refusing "
                         "to end this heat; run `smithy patrol --fix` and "
                         "re-check which forge owns the task.",
                "checkpoint_task": task_id,
                "pinned_forge": _pin,
                "resolved_forge": forge_id,
            })
            sys.exit(1)
    assembly_enabled = (
        (state_peek.get("parallel") or {}).get("assembly", {}).get("enabled", False)
    )

    effective_outcome = outcome
    if assembly_enabled and outcome == "complete" and task_id != "generated":
        effective_outcome = "submitted"

    # t-427: pre-submit pytest gate runs OUTSIDE the lock (t-426) — the
    # test suite can take minutes and blocking every other Forge's
    # state transition on it would defeat the point of N>1. The gate
    # reads code/disk but never writes state.json.
    test_gate = None
    if (effective_outcome == "submitted"
            and not skip_tests
            and stage not in _NO_GATE_STAGES
            and task_id != "generated"):
        test_gate = _run_presubmit_tests(root, forge_id, tests_cmd=tests_cmd)
        if not test_gate["passed"]:
            # Downgrade — don't let this task reach Assembly.
            effective_outcome = "partial"
            # Flag in the caller's notes so the worklog row and Marshal's
            # nudge both carry the context.
            tail_lines = test_gate["output"].splitlines()[-3:]
            tail = " | ".join(tail_lines)[:200]
            notes = f"{notes} | PRE-SUBMIT TESTS FAILED: {tail}"
            # Print the most relevant slice to the Forge's stderr so the
            # human reading the pane sees it immediately. 30 lines is
            # enough for a pytest summary block without drowning the pane.
            head = "\n".join(test_gate["output"].splitlines()[:30])
            _err("--- pre-submit test failure (first 30 lines) ---")
            _err(head)
            _err("--- end ---")
            # t-439: reset-on-reject. Uncommitted WIP from a rejected
            # heat used to survive into the next heat's branch checkout
            # (`git checkout -B` preserves modified files), so the next
            # pytest ran against stale code, failed again, and the
            # pollution compounded across 3–4 consecutive rejects
            # (observed on t-425, t-426, t-431 across this session's
            # hardening sprint). Reset the worktree to HEAD and
            # `git clean -fdx` here so the next heat starts from a
            # clean slate; the per-task branch ref is unaffected.
            _reset_worktree_on_reject(root, forge_id)

    # t-426: all state.json mutations happen inside the lock. Re-load
    # state fresh so we see any sibling's updates (e.g. a concurrent
    # start-heat's budget.used bump) and don't clobber them.
    completed_task = None
    with state_lock(root):
        state = load_state(root)

        # t-426: budget.used is bumped by start-heat now. end-heat used
        # to re-set state["budget"]["used"] = heat here — that was the
        # lost-update race: if another Forge had bumped to heat+1
        # while we were working, resetting to heat lost their update.

        # Update stage stats
        s = state["stages"][stage]
        s["heats"] = s.get("heats", 0) + 1
        if progress is not None:
            s["progress"] = max(0, min(1, progress))
        s["value_ema"] = round(0.7 * s.get("value_ema", 0.5) + 0.3 * value, 3)

        # Update allocator integral
        total_heats = sum(st["heats"] for st in state["stages"].values()) or 1
        actual_frac = s["heats"] / total_heats
        target = s.get("target", 0.16)
        error = target - actual_frac
        integral = state["allocator"]["integral"].get(stage, 0)
        integral = integral * 0.85 + error
        integral = max(-0.5, min(0.5, integral))
        state["allocator"]["integral"][stage] = round(integral, 3)

        # Mark task status based on effective outcome.
        if effective_outcome == "complete" and task_id != "generated":
            for task in state.get("queue", []):
                if task["id"] == task_id:
                    task["status"] = "complete"
                    # Auto-clear sticky human priority on complete (t-312).
                    task["human_priority"] = None
                    task["priority_reason"] = None
                    completed_task = task
                    break
        elif effective_outcome == "submitted" and task_id != "generated":
            for task in state.get("queue", []):
                if task["id"] == task_id:
                    task["status"] = "submitted"
                    # t-548: record which heat produced this submission.
                    # _do_assembly_reject pairs it with the rejection
                    # heat in reject_history; resubmits overwrite so the
                    # stamp always names the latest hand-off.
                    task["submitted_heat"] = heat
                    completed_task = task
                    break
        elif (test_gate is not None and not test_gate["passed"]
              and task_id != "generated"):
            # t-427: pre-submit test-fail downgrade — flip status back to
            # pending so the Forge can start the next heat on the same
            # task without tripping start-heat's "not pending" guard.
            # The per-task branch stays intact; the Forge just iterates.
            for task in state.get("queue", []):
                if task["id"] == task_id:
                    task["status"] = "pending"
                    break

        # Increment initiative heats_used
        ini_id = completed_task.get("initiative_id") if completed_task else None
        if ini_id:
            for ini in state.get("initiatives", []):
                if ini["id"] == ini_id:
                    ini["heats_used"] = ini.get("heats_used", 0) + 1
                    if ini.get("budget_cap") and ini["heats_used"] >= ini["budget_cap"]:
                        # Append warning to outbox
                        outbox_path = root / "outbox.md"
                        if outbox_path.exists():
                            warning = f"\n\n**⚠️ Initiative {ini_id} ({ini['title']}) has reached its budget cap ({ini['budget_cap']} heats).**\n"
                            outbox_path.write_text(outbox_path.read_text() + warning)
                    break

        # Update overall progress
        progresses = [st.get("progress", 0) for st in state["stages"].values()]
        state["overall_progress"] = round(sum(progresses) / len(progresses), 2)

        # t-544: mirror of start-heat's registry stamp — the heat is over,
        # so flip the entry back to idle. Keeps patrol's registry-vs-
        # checkpoint coherence checks meaningful in both directions.
        for _f in (state.get("parallel") or {}).get("forges") or []:
            if _f.get("id") == forge_id:
                _f["status"] = "idle"
                _f["current_task"] = None
                _f["current_heat"] = None
                _f["last_heartbeat"] = datetime.now(
                    timezone.utc).isoformat(timespec="seconds")
                break

        # Save state
        save_state(root, state)

    # Append worklog (use effective_outcome so "submitted" lands when Assembly
    # is enabled — the second row is written later by assembly-merge/reject).
    append_worklog(root, heat, stage, task_id, effective_outcome, value,
                   signal, notes, forge_id=forge_id)

    # Delete this Forge's checkpoint (t-409 H1).
    delete_checkpoint(root, forge_id=forge_id)

    # t-399 I4 / t-422: when Assembly is enabled and the task was submitted,
    # enqueue for Assembly to rebase/merge. The queue entry captures the
    # current HEAD so Assembly merges only up to this submit boundary (not
    # future heats). The path is anchored at the MAIN repo root
    # (t-422 — t-419 missed this one file); without that anchor every
    # worktree wrote to its own queue and Assembly saw none of them.
    submit_entry = None
    if effective_outcome == "submitted":
        import subprocess as _sub
        wt = main_repo_root(root) / ".worktrees" / (forge_id or "")
        cwd = wt if (wt.exists() and (wt / ".git").exists()) else root
        head = _sub.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                        capture_output=True, text=True).stdout.strip()
        branch = _sub.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                          cwd=str(cwd), capture_output=True, text=True
                          ).stdout.strip()
        queue_path = assembly_queue_path(root)
        submit_entry = {
            "forge_id": forge_id,
            "task_id": task_id,
            "heat": heat,
            "branch": branch,
            "sha": head,
            "submitted_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        }
        # t-493: use the locked _append_queue helper so Assembly's tick
        # can't overwrite this row mid-flight. Plain open-for-append
        # without fcntl lost rows to the read-then-overwrite race.
        _append_queue(queue_path, submit_entry)

    result = {
        "heat": heat,
        "stage": stage,
        "task_id": task_id,
        "forge_id": forge_id,
        "outcome": effective_outcome,
        "value": value,
        "signal": signal,
        "overall_progress": state["overall_progress"],
        "budget_remaining": state["budget"]["total_heats"] - heat,
    }
    if test_gate is not None:
        # t-427: surface gate result so the Forge pane (and rig-events
        # consumers) can see exactly what happened.
        result["test_gate"] = {
            "passed": test_gate["passed"],
            "cmd": test_gate.get("cmd"),
        }
        if not test_gate["passed"]:
            result["test_gate"]["returncode"] = test_gate.get("returncode")

    # t-425: emit forge_ended event regardless of nudge outcome — this is
    # the authoritative "heat is closed" timestamp for replay/latency work.
    _emit_rig_event(root, f"forge_ended_{effective_outcome}",
                    actor=forge_id, forge_id=forge_id, task_id=task_id,
                    stage=stage, heat=heat, value=value, signal=signal)

    # Auto-nudge marshal so it can re-prioritize and assign next task.
    # t-422: also nudge Assembly when the task was submitted — that's what
    # closes the merge loop without Anvil hand-driving every merge.
    if not no_nudge:
        # t-508: compact human-readable HEAT_DONE format. The old message
        # ("task, value=0.8, signal=🟢. Re-prioritize.") was opaque from
        # Marshal's pane — no stage, no initiative, no task desc, no heat
        # number. The new shape puts identity + context front-and-center
        # and drops the noise (signal emoji already encodes value; the
        # "Re-prioritize" suffix was informational-only).
        #
        # Look up the task for desc + initiative_id. completed_task is
        # only set on complete/submitted outcomes; for partial/blocked
        # fall back to a fresh lookup against the same `state` we just
        # saved (still in scope).
        _nudge_task = completed_task
        if _nudge_task is None and task_id and task_id != "generated":
            for _t in state.get("queue", []):
                if _t.get("id") == task_id:
                    _nudge_task = _t
                    break
        nudge_msg = _format_heat_done_nudge(
            signal=signal, forge_id=forge_id or "", heat=heat,
            task_id=task_id, stage=stage, task=_nudge_task, notes=notes,
        )
        nudge_result = _nudge_persona("marshal", nudge_msg, root=root)
        result["nudge"] = nudge_result
        _emit_rig_event(root, "marshal_nudged", actor=forge_id,
                        target="marshal", task_id=task_id,
                        nudged=nudge_result.get("nudged"))
        if submit_entry:
            # t-510: compact ASSEMBLY_QUEUE format — mirrors HEAT_DONE's
            # emoji-first identity-then-context shape. "run smithy
            # assembly-tick." suffix dropped (Assembly's loop ticks, not
            # a human).
            asm_msg = _format_assembly_queue_nudge(
                task=_nudge_task, sha=submit_entry["sha"],
                forge_id=forge_id or "",
            )
            asm_result = _nudge_persona("assembly", asm_msg, root=root)
            result["assembly_nudge"] = asm_result
            _emit_rig_event(root, "assembly_nudged", actor=forge_id,
                            target="assembly", task_id=task_id,
                            branch=submit_entry["branch"],
                            sha=submit_entry["sha"],
                            nudged=asm_result.get("nudged"))
        if nudge_result["nudged"]:
            _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]} — nudged marshal")
        else:
            _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]} — marshal nudge skipped: {nudge_result['reason']}")
    else:
        result["nudge"] = {"nudged": False, "reason": "skipped (--no-nudge)"}
        _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]}")

    # t-395 I0: expose halted status so caller knows drain is final.
    parallel = state.get("parallel") or {}
    if parallel.get("halt_flag"):
        result["halt_flag"] = True
        _err(f"Heat {heat} ended — rig is halted, no new heats until 'smithy resume-rig'.")

    _output(result)


@cli.command("halt")
@click.option("--reason", default="", help="Why we're halting (recorded in state).")
@click.pass_context
def halt_cmd(ctx, reason):
    """t-395 I0: Set the halt flag. Marshal stops assigning; running heats
    drain via end-heat. Idempotent — re-halting updates reason/ts."""
    root = ctx.obj["root"]
    state = load_state(root)
    state.setdefault("parallel", {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["parallel"]["halt_flag"] = True
    state["parallel"]["halted_at"] = now
    state["parallel"]["halt_reason"] = reason or None
    save_state(root, state)
    _output({"halt_flag": True, "halted_at": now, "reason": reason or None})
    _err(f"Rig halted at {now}" + (f" — {reason}" if reason else ""))


@cli.command("resume-rig")
@click.pass_context
def resume_rig_cmd(ctx):
    """t-395 I0: Clear the halt flag. New heats permitted again."""
    root = ctx.obj["root"]
    state = load_state(root)
    parallel = state.setdefault("parallel", {})
    was_halted = bool(parallel.get("halt_flag"))
    parallel["halt_flag"] = False
    parallel.pop("halted_at", None)
    parallel.pop("halt_reason", None)
    save_state(root, state)
    _output({"halt_flag": False, "was_halted": was_halted})
    _err("Rig resumed" if was_halted else "Rig was not halted — no-op.")


@cli.command("shutdown-status")
@click.pass_context
def shutdown_status_cmd(ctx):
    """t-395 I0: Report halt state + in-flight checkpoint presence.

    Used by humans and by future Witness to know whether quiesce is complete.
    """
    root = ctx.obj["root"]
    state = load_state(root)
    parallel = state.get("parallel") or {}
    # t-542: quiesce means NO forge is mid-heat — check every roster
    # entry's per-Forge checkpoint (main-root anchored), not just the
    # primary's legacy file at a possibly-worktree `root`.
    forge_ids = [f.get("id") for f in (parallel.get("forges") or []) if f.get("id")]
    checkpoints = {}
    for fid in forge_ids or [primary_forge_id(root)]:
        cp = forge_checkpoint_path(root, fid)
        if cp.exists():
            try:
                checkpoints[fid] = json.loads(cp.read_text())
            except Exception:
                checkpoints[fid] = {"error": "unreadable"}
    halted = bool(parallel.get("halt_flag"))
    quiesced = halted and not checkpoints
    _output({
        "halt_flag": halted,
        "halted_at": parallel.get("halted_at"),
        "reason": parallel.get("halt_reason"),
        "checkpoint": checkpoints.get(primary_forge_id(root)),
        "checkpoints": checkpoints,
        "quiesced": quiesced,
    })


@cli.command("assembly-heartbeat")
@click.pass_context
def assembly_heartbeat_cmd(ctx):
    """t-398 I3: Stamp state.parallel.assembly.last_heartbeat = now.

    Called by the Assembly teammate each cycle so Witness / patrol can
    detect a stuck Assembly (heartbeat older than threshold).
    """
    root = ctx.obj["root"]
    state = load_state(root)
    parallel = state.setdefault("parallel", {})
    assembly = parallel.setdefault("assembly", {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    assembly["last_heartbeat"] = now
    save_state(root, state)
    _output({"last_heartbeat": now})


@cli.command("assembly-rebase")
@click.option("--forge", "forge_id", required=True)
@click.option("--task", "task_id", default=None,
              help="Per-task branch id (t-456). Omit for legacy "
                   "rebase-current-branch behaviour.")
@click.option("--base", default="main")
@click.pass_context
def assembly_rebase_cmd(ctx, forge_id, task_id, base):
    """t-399 I4 H2: Rebase the Forge's per-task branch onto base.

    t-456: pass ``--task <task-id>`` so rebase_forge_branch explicitly
    checks out ``<forge-id>/<task-id>`` before rebasing. Without it the
    function falls back to rebasing whatever branch is currently checked
    out in the worktree (risky when the Forge has moved on).
    """
    from .assembly import rebase_forge_branch
    _output(rebase_forge_branch(ctx.obj["root"], forge_id,
                                task_id=task_id, base=base))


@cli.command("assembly-continue-rebase")
@click.option("--forge", "forge_id", required=True)
@click.pass_context
def assembly_continue_rebase_cmd(ctx, forge_id):
    """t-399 I4 H2: Resume rebase after Assembly staged conflict fixes."""
    from .assembly import continue_rebase
    _output(continue_rebase(ctx.obj["root"], forge_id))


@cli.command("assembly-abort-rebase")
@click.option("--forge", "forge_id", required=True)
@click.pass_context
def assembly_abort_rebase_cmd(ctx, forge_id):
    """t-399 I4 H2: Abort a rebase-in-progress in the Forge's worktree."""
    from .assembly import abort_rebase
    _output(abort_rebase(ctx.obj["root"], forge_id))


@cli.command("assembly-test")
@click.option("--forge", "forge_id", required=True)
@click.pass_context
def assembly_test_cmd(ctx, forge_id):
    """t-399 I4 H2: Run pytest in Forge's worktree; return pass/fail."""
    from .assembly import run_tests_in_worktree
    _output(run_tests_in_worktree(ctx.obj["root"], forge_id))


@cli.command("assembly-ff-merge")
@click.option("--forge", "forge_id", required=True)
@click.option("--task", "task_id", required=True)
@click.option("--base", default="main")
@click.pass_context
def assembly_ff_merge_cmd(ctx, forge_id, task_id, base):
    """t-399 I4: Merge `<forge>/<task>` into base in project_dir."""
    from .assembly import ff_merge_forge_branch
    _output(ff_merge_forge_branch(ctx.obj["root"], forge_id, task_id, base))


@cli.command("assembly-merge")
@click.argument("task_id")
@click.option("--sha", required=True, help="Merge commit SHA on main.")
@click.option("--resolution", is_flag=True, default=False,
              help="Assembly resolved conflicts before merging.")
@click.pass_context
def assembly_merge_cmd(ctx, task_id, sha, resolution):
    """t-399 I4: Assembly's successful merge. Flips submitted → complete."""
    result = _do_assembly_merge(ctx.obj["root"], task_id, sha, resolution)
    _output(result)
    if "error" in result:
        sys.exit(1)


def _do_assembly_merge(root, task_id, sha, resolution):
    state = load_state(root)
    task = None
    for t in state.get("queue", []):
        if t["id"] == task_id:
            task = t
            break
    if task is None:
        return {"error": f"unknown task: {task_id}"}
    if task["status"] != "submitted":
        return {"error": f"task {task_id} status is {task['status']!r}, "
                         f"expected 'submitted'"}
    task["status"] = "complete"
    task["human_priority"] = None
    task["priority_reason"] = None
    save_state(root, state)

    outcome = "merged-with-resolution" if resolution else "merged"
    signal = "🔀" if resolution else "✅"
    append_worklog(root, state["budget"]["used"], "implementation", task_id,
                   outcome, 0.0, signal, f"merge sha={sha[:12]}")

    # t-478: nudge Marshal at the submitted→complete transition, not in
    # assembly_tick. Any caller that drives a merge through
    # _do_assembly_merge directly (smithy assembly-merge CLI, future
    # batch path) needs the wake-up too — putting it here makes the
    # nudge unconditional. Symmetric with _do_assembly_reject above.
    # t-424: fire both a durable file-queue row AND a live tmux event.
    # t-510: compact format — mirrors t-508's HEAT_DONE shape.
    merged_msg = _format_assembly_merged_nudge(task=task, sha=sha)
    _queue_nudge(root, "marshal", merged_msg)
    _nudge_persona("marshal", merged_msg, root=root)

    # t-460: rebind the global editable smithy install to MAIN whenever
    # a merge touches smithy/* code. Prevents stale-binary rejects where
    # Assembly's pytest collects against a worktree's old smithy package
    # because some other pane's `pip install -e` left the .pth pointing
    # there. Best-effort and quiet — failures don't block the merge.
    rebind = _rebind_smithy_install(root, sha)
    return {"task_id": task_id, "status": "complete", "outcome": outcome,
            "sha": sha, "rebind": rebind}


@cli.command("assembly-reject")
@click.argument("task_id")
@click.option("--reason", required=True, help="Why Assembly rejected the branch.")
@click.pass_context
def assembly_reject_cmd(ctx, task_id, reason):
    """t-399 I4: Assembly rejection. Flips submitted → pending + Marshal nudge."""
    result = _do_assembly_reject(ctx.obj["root"], task_id, reason)
    _output(result)
    if "error" in result:
        sys.exit(1)


def _do_assembly_reject(root, task_id, reason):
    state = load_state(root)
    task = None
    for t in state.get("queue", []):
        if t["id"] == task_id:
            task = t
            break
    if task is None:
        return {"error": f"unknown task: {task_id}"}
    if task["status"] != "submitted":
        return {"error": f"task {task_id} status is {task['status']!r}, "
                         f"expected 'submitted'"}

    task["status"] = "pending"
    # t-455: normalize before arithmetic — was `hp or 0; hp + 5` which
    # crashed on `"p1"`-style strings, halting the Assembly merge loop.
    # Unparseable drift coerces to 0 so reject still bumps visibility.
    try:
        base_hp = normalize_human_priority(task.get("human_priority")) or 0
    except ValueError:
        base_hp = 0
    task["human_priority"] = base_hp + 5
    pr = f"assembly rejected: {reason}"[:40]
    task["priority_reason"] = pr
    # t-548: bounce ledger. Tasks can bounce repeatedly — append every
    # (done, rejected) heat pair instead of overwriting. done_heat is the
    # submitted_heat stamped by end-heat's submit path; None for
    # submissions that predate t-548.
    task.setdefault("reject_history", []).append({
        "done_heat": task.get("submitted_heat"),
        "rejected_heat": state["budget"]["used"],
        "reason": reason[:80],
    })
    save_state(root, state)

    append_worklog(root, state["budget"]["used"], "implementation", task_id,
                   "rejected", 0.0, "🚫", f"reason={reason[:80]}")
    # t-399 I4 design (2026-04-13): rejection routes to Marshal (owns
    # scheduling), not to the Forge directly. t-424: fire BOTH a live
    # tmux send-keys via _nudge_persona AND a file-queue row via
    # _queue_nudge — the live event is what wakes a running Marshal
    # pane, and the file row is a durable audit trail Marshal can drain
    # if it was offline when the event fired. _nudge_persona alone
    # skips the file on success; we want the record either way.
    # t-510: compact ASSEMBLY_REJECTED — drops the verbose
    # "Task back to pending (priority +5). Decide: reassign, split, or
    # deprioritize." suffix. Assembly already flipped the status +
    # human_priority in state.json above; Marshal's re-prioritization
    # decision is its own job.
    nudge_msg = _format_assembly_rejected_nudge(
        task=task, forge_id=task.get("assigned_forge") or "", reason=reason,
    )
    _queue_nudge(root, "marshal", nudge_msg)
    _nudge_persona("marshal", nudge_msg, root=root)
    return {"task_id": task_id, "status": "pending",
            "human_priority": task["human_priority"],
            "priority_reason": pr}


@cli.command("assembly-tick")
@click.option("--base", default="main", help="Integration branch.")
@click.option("--dry-run", is_flag=True,
              help="Report what would happen without mutating anything.")
@click.option("--tests-cmd", default=None,
              help="Override default pytest command (space-separated).")
@click.pass_context
def assembly_tick_cmd(ctx, base, dry_run, tests_cmd):
    """t-399 I4: Drain one entry from .assembly-queue.jsonl and merge it.

    Pipeline: rebase branch onto base → (try_auto_resolve if conflict) →
    pytest → merge --no-ff. On severe conflict or test fail, abort and
    call assembly-reject (which nudges Marshal).

    Returns JSON describing the outcome. Re-invoke to process the next
    queue item; idempotent when queue is empty.
    """
    # t-475: route assembly_tick through the staging-worktree primitives
    # introduced in t-456. Prior behaviour rebased + ran tests in the
    # Forge's own worktree, so if the Forge had moved on to a later task
    # by the time Assembly got to this queue entry, pytest ran against
    # the WRONG branch contents and spuriously rejected valid submissions
    # (observed 2026-04-18 on t-472). Staging decouples verification from
    # whatever branch the Forge currently has checked out.
    from .assembly import (
        continue_rebase, abort_rebase, try_auto_resolve,
        run_tests_in_worktree, ff_merge_forge_branch, branch_name,
        rebase_task_branch, _STAGING_WORKTREE as STAGING_WORKTREE,
    )
    root = ctx.obj["root"]
    qpath = assembly_queue_path(root)
    reconciled = False
    if not qpath.exists() or qpath.stat().st_size == 0:
        # ini-024 T1: an empty/missing jsonl is NOT a "no work" signal — it
        # just means the fast-path cache is silent. Reconcile against truth:
        # state.queue + git branches. If a submitted task has a real per-task
        # branch on disk, process it; otherwise genuinely idle. This closes
        # the freeze class where a lost nudge or a _pop_queue race dropped
        # a row but state.json + git still said there was work (incident
        # 2026-04-18: t-480/t-448/t-493).
        recon = _reconcile_submitted(root)
        if recon is None:
            _output({"status": "empty"})
            return
        item = recon
        rest = []
        reconciled = True
    else:
        lines = [ln for ln in qpath.read_text().splitlines() if ln.strip()]
        item = json.loads(lines[0])
        rest = lines[1:]

    if dry_run:
        _output({"status": "would_process", "item": item,
                 "remaining": len(rest), "reconciled": reconciled})
        return

    forge_id = item["forge_id"]
    task_id = item["task_id"]
    expected_branch = branch_name(forge_id, task_id)
    # t-425: telemetry. Start a timer so we can report latency_ms on exit.
    _tick_started_at = datetime.now(timezone.utc)
    _emit_rig_event(root, "assembly_tick_begin", actor="assembly",
                    forge_id=forge_id, task_id=task_id,
                    branch=expected_branch, sha=item.get("sha"),
                    reconciled=reconciled)

    # t-510: ASSEMBLY_ATTEMPT — surface the merge-start so the 3–5min
    # rebase+test window isn't silent. Look up the task for desc +
    # stage + initiative_id (best-effort; a stale jsonl entry may point
    # at a task that was edited/removed from state.queue between submit
    # and tick). Emit to the Assembly pane via stderr; rig-event
    # already exists (`assembly_tick_begin`), so we don't double-log.
    _tick_state = load_state(root)
    _tick_task = next(
        (_t for _t in _tick_state.get("queue", []) if _t.get("id") == task_id),
        None,
    )
    _err(_format_assembly_attempt_nudge(
        task=_tick_task, forge_id=forge_id, sha=item.get("sha") or "",
    ))

    def _tick_latency_ms():
        return int((datetime.now(timezone.utc) - _tick_started_at)
                   .total_seconds() * 1000)

    def _reject(reason: str) -> dict:
        # t-475: abort any in-flight rebase in the STAGING worktree (not
        # the Forge's) so our cleanup matches where we actually ran it.
        abort_rebase(root, STAGING_WORKTREE)
        _do_assembly_reject(root, task_id, reason)
        _log(root, forge_id, task_id, "rejected", reason)
        # t-493 × ini-024 T1: only pop a row when the tick actually
        # consumed one (non-reconciled path). Reconciliation derives
        # `item` from state.json without reading the jsonl, so there's
        # nothing to drop.
        if not reconciled:
            _pop_queue(qpath, lines[0])
        _emit_rig_event(root, "assembly_tick_rejected", actor="assembly",
                        forge_id=forge_id, task_id=task_id, reason=reason,
                        latency_ms=_tick_latency_ms())
        return {"status": "rejected", "task_id": task_id, "reason": reason,
                "reconciled": reconciled}

    # 1. Rebase onto base — t-475: use rebase_task_branch so the work
    # happens in .worktrees/_assembly-staging/ instead of the Forge's
    # worktree. Conflict resolution loop below now targets staging too.
    rb = rebase_task_branch(root, forge_id, task_id, base=base)
    if rb["status"] == "conflict":
        res = try_auto_resolve(root, STAGING_WORKTREE)
        if res["status"] == "severe":
            _output(_reject(f"severe conflict in {','.join(res['files'])}"))
            return
        if res["status"] == "resolved":
            cont = continue_rebase(root, STAGING_WORKTREE)
            while cont["status"] == "conflict":
                res2 = try_auto_resolve(root, STAGING_WORKTREE)
                if res2["status"] == "severe":
                    _output(_reject(
                        f"severe conflict in {','.join(res2['files'])}"))
                    return
                if res2["status"] == "nothing":
                    break
                cont = continue_rebase(root, STAGING_WORKTREE)
            if cont["status"] == "error":
                _output(_reject(f"rebase error: {cont.get('detail','?')[:120]}"))
                return
        elif res["status"] == "nothing":
            pass  # fall through
    elif rb["status"] == "error":
        _output(_reject(f"rebase error: {rb.get('detail','?')[:120]}"))
        return

    staging_ref = rb.get("staging_ref")

    # 2. Run tests in the STAGING worktree, which has the rebased
    # per-task branch checked out — independent of the Forge's HEAD.
    cmd_override = tests_cmd.split() if tests_cmd else None
    tst = run_tests_in_worktree(root, STAGING_WORKTREE, cmd=cmd_override)
    if not tst["passed"]:
        # Don't abort rebase — it already completed. Just reject the merge.
        # t-533: persist the full (untruncated) test output so the
        # 3-line tail we stamp into state.json doesn't destroy the
        # diagnostic trace. Reject reason gets a file:// pointer.
        log_path = _persist_test_log(
            root, task_id, tst.get("output_full") or tst.get("output", ""),
        )
        tail = tst["output"].splitlines()[-3:]
        summary = f"tests failed: {'|'.join(tail)[:120]}"
        if log_path is not None:
            summary = f"tests failed (see file://{log_path}): {'|'.join(tail)[:80]}"
        _output(_reject(summary))
        return

    # 3. Merge the rebased staging ref into base in the main repo.
    # delete_branch=False: ff_merge's own delete uses `-d` (safe), but
    # the original forge branch is NOT an ancestor of the merged commit
    # (we merged the REBASED staging ref, whose SHAs differ). We force-
    # delete below once the merge is confirmed landed — safe because
    # the task's content is provably in main now.
    mr = ff_merge_forge_branch(root, forge_id, task_id, base,
                               source_ref=staging_ref,
                               delete_branch=False)
    if mr["status"] != "merged":
        _output(_reject(f"merge failed: {mr.get('detail','?')[:120]}"))
        return
    # t-475: now force-delete the original forge branch since its content
    # landed via the rebased staging ref. Surface the result under the
    # same "deleted" key ff_merge_forge_branch would have used so the
    # existing telemetry keeps working.
    from .assembly import delete_forge_branch
    mr["deleted"] = delete_forge_branch(root, forge_id, task_id, force=True)

    # Note: the ephemeral `_merge-<task-id>` branch stays on as staging's
    # current HEAD — rebase_task_branch on the next tick uses `checkout
    # -B` which resets the ref, so accumulation isn't an issue. Trying
    # to `git branch -D` here fails anyway because the ref is checked
    # out in the staging worktree.

    # 4. Record + flip task status
    _do_assembly_merge(root, task_id, mr["sha"], resolution=False)
    _log(root, forge_id, task_id, "merged", mr["sha"])
    # t-438: record the advisory push outcome alongside the merge
    # audit row. Best-effort — ff_merge_forge_branch already made the
    # attempt and never throws; we just log / telemeter it.
    push = mr.get("push")
    if push:
        _log(root, forge_id, task_id,
             f"push_{push['status']}",
             push.get("reason", push.get("branch", "")))
        _emit_rig_event(root, f"assembly_push_{push['status']}",
                        actor="assembly", forge_id=forge_id,
                        task_id=task_id, branch=push.get("branch"),
                        remote=push.get("remote"),
                        reason=push.get("reason"))
    # t-478: Marshal nudge moved into _do_assembly_merge so any caller
    # that bypasses assembly_tick (smithy assembly-merge, future batch
    # path) still wakes Marshal at the submitted→complete transition.
    # t-493 × ini-024 T1: drop only the drained row under lock —
    # preserves any Forge append that arrived during the merge tick.
    # Reconciliation paths didn't read from jsonl so there's no row to
    # drop; skip.
    if not reconciled:
        _pop_queue(qpath, lines[0])
    _emit_rig_event(root, "assembly_tick_merged", actor="assembly",
                    forge_id=forge_id, task_id=task_id,
                    branch=mr["branch"], sha=mr["sha"],
                    latency_ms=_tick_latency_ms())
    _output({"status": "merged", "task_id": task_id, "sha": mr["sha"],
             "branch": mr["branch"], "push": push,
             "reconciled": reconciled})


def _log(root, forge_id, task_id, outcome, detail):
    """Append an assembly-log.jsonl audit row."""
    path = root / "assembly-log.jsonl"
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "forge_id": forge_id, "task_id": task_id,
        "outcome": outcome, "detail": detail,
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _persist_test_log(root, tag, full_output):
    """t-533: write the full, untrimmed test output to
    `.assembly-logs/<tag>-<ISO-timestamp>.log` at the MAIN repo root.

    `tag` is the task id (single-reject path) or a batch identifier
    (batched path) — anything that makes the log file findable via the
    reject reason's `file://` pointer. Tag is sanitised to
    alnum/hyphen/underscore so it can't escape the directory. Returns
    the absolute path on success, None on any error; the caller still
    has the inline-truncated output + a human-readable reject reason
    as a fallback, so a missing log file is a diagnostic degradation,
    not a pipeline failure.
    """
    if not full_output:
        return None
    try:
        logs_dir = main_repo_root(root) / ".assembly-logs"
        logs_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds") \
            .replace(":", "")
        safe_tag = "".join(c if c.isalnum() or c in "-_" else "-"
                           for c in str(tag))[:64] or "unknown"
        path = logs_dir / f"{safe_tag}-{ts}.log"
        path.write_text(full_output)
        return str(path)
    except (OSError, ValueError, Exception):
        return None


def _append_queue(qpath, entry):
    """t-493: locked append to .assembly-queue.jsonl.

    Opens for append (create-if-missing) under an exclusive fcntl lock so
    a concurrent `_pop_queue` can't overwrite the file between the new
    row landing and the lock release. `fsync` after flush so a crash
    between the Forge's end-heat and Assembly's tick doesn't lose the
    just-submitted row.
    """
    import fcntl
    import os as _os
    qpath.parent.mkdir(parents=True, exist_ok=True)
    with open(qpath, "a") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry) + "\n")
            f.flush()
            try:
                _os.fsync(f.fileno())
            except OSError:
                pass  # fsync can fail on some filesystems; append still lands.
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _pop_queue(qpath, drained_line):
    """t-493: remove `drained_line` from `qpath` without destroying any
    concurrent appends.

    Prior behaviour overwrote the file with a stale in-memory `rest =
    lines[1:]` (or unlinked it when `rest` was empty). If a Forge
    appended a new row during the merge tick (seconds to minutes), that
    row was silently destroyed. Net effect: state.json still carried
    `status=submitted` for the lost task, `.assembly-queue.jsonl` had no
    matching entry, and Assembly idled forever while the task sat
    zombie (observed t-450 / t-463 / t-472 / t-480 / t-448).

    Fix: re-read the file under an exclusive lock, drop the FIRST
    occurrence of `drained_line`, and write back. Leave the file in
    place (empty is fine) so `_append_queue` never races an unlink.

    `drained_line` is the exact line text that was consumed (the first
    element of the `lines = [...]` list captured by assembly_tick).
    Matching by string keeps the contract simple and avoids
    re-serialising; Forge writes each row via `json.dumps` with the same
    key order, so byte-equality holds.
    """
    import fcntl
    if not qpath.exists():
        return
    with open(qpath, "r+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            current = [ln for ln in f.read().splitlines() if ln.strip()]
            kept = []
            dropped = False
            for ln in current:
                if not dropped and ln == drained_line:
                    dropped = True
                    continue
                kept.append(ln)
            f.seek(0)
            f.truncate()
            if kept:
                f.write("\n".join(kept) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _truncate_for_nudge(text: str, limit: int = 50) -> str:
    """Collapse whitespace and clip to `limit` chars with `…` for overflow."""
    if not text:
        return ""
    # Collapse internal whitespace so multi-line descs render on one line
    # in the nudge wire message.
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit - 1].rstrip() + "…"


def _stage_ini_segment(task, stage_fallback=None):
    """Render the '{stage}[/{ini_id}]' segment used by t-508/t-510
    nudges. Empty-string initiative IDs treated the same as None.
    Falls back to `stage_fallback` when the task dict omits `stage`."""
    if task is None:
        return stage_fallback or ""
    stage = task.get("stage") or stage_fallback or ""
    ini = task.get("initiative_id")
    if ini:
        return f"{stage}/{ini}"
    return stage


def _format_assembly_queue_nudge(task, sha: str, forge_id: str) -> str:
    """t-510: ASSEMBLY_QUEUE (Forge → Assembly) compact format.

      ASSEMBLY_QUEUE ⏳ {task_id} {stage}[/{ini}] · "{desc}" · from {forge_id} · sha={sha[:8]}
    """
    task_id = (task or {}).get("id", "(unknown)")
    stage_seg = _stage_ini_segment(task) or "(no stage)"
    desc = _truncate_for_nudge((task or {}).get("desc") or "") or "(no desc)"
    sha_short = (sha or "")[:8] or "(no sha)"
    return (f'ASSEMBLY_QUEUE ⏳ {task_id} {stage_seg} '
            f'· "{desc}" · from {forge_id or "(unknown-forge)"} '
            f'· sha={sha_short}')


def _format_assembly_attempt_nudge(task, forge_id: str, sha: str = "") -> str:
    """t-510: ASSEMBLY_ATTEMPT pane / rig-event message fired at the
    start of a merge try so the 3–5min rebase+test window isn't silent.

      ASSEMBLY_ATTEMPT 🔨 {task_id} {stage}[/{ini}] · "{desc}" · from {forge_id}
    """
    task_id = (task or {}).get("id", "(unknown)")
    stage_seg = _stage_ini_segment(task) or "(no stage)"
    desc = _truncate_for_nudge((task or {}).get("desc") or "") or "(no desc)"
    return (f'ASSEMBLY_ATTEMPT 🔨 {task_id} {stage_seg} '
            f'· "{desc}" · from {forge_id or "(unknown-forge)"}')


def _format_assembly_merged_nudge(task, sha: str) -> str:
    """t-510: ASSEMBLY_MERGED (Assembly → Marshal) compact format.

      ASSEMBLY_MERGED 🟢 {task_id} {stage}[/{ini}] · "{desc}" · sha={sha[:8]}
    """
    task_id = (task or {}).get("id", "(unknown)")
    stage_seg = _stage_ini_segment(task) or "(no stage)"
    desc = _truncate_for_nudge((task or {}).get("desc") or "") or "(no desc)"
    sha_short = (sha or "")[:8] or "(no sha)"
    return (f'ASSEMBLY_MERGED 🟢 {task_id} {stage_seg} '
            f'· "{desc}" · sha={sha_short}')


def _format_assembly_rejected_nudge(task, forge_id: str, reason: str) -> str:
    """t-510: ASSEMBLY_REJECTED (Assembly → Marshal) compact format.

      ASSEMBLY_REJECTED 🔴 {task_id} {stage}[/{ini}] · "{desc}" · from {forge_id} · {reason_60}

    Reason is truncated to 60 chars; the old verbose suffix ("Task back
    to pending (priority +5). Decide: reassign, split, or deprioritize.")
    is dropped — Assembly already flipped state.json and Marshal's job
    is obvious.
    """
    task_id = (task or {}).get("id", "(unknown)")
    stage_seg = _stage_ini_segment(task) or "(no stage)"
    desc = _truncate_for_nudge((task or {}).get("desc") or "") or "(no desc)"
    reason_short = _truncate_for_nudge(reason, limit=60) or "(no reason)"
    return (f'ASSEMBLY_REJECTED 🔴 {task_id} {stage_seg} '
            f'· "{desc}" · from {forge_id or "(unknown-forge)"} '
            f'· {reason_short}')


def _format_heat_done_nudge(signal: str, forge_id: str, heat: int,
                            task_id: str, stage: str,
                            task, notes: str) -> str:
    """t-508: compact HEAT_DONE nudge format.

    Normal:   HEAT_DONE {signal} {forge_id} h{heat} · {task_id} {stage}/{ini} · "{desc}"
    No ini:   HEAT_DONE {signal} {forge_id} h{heat} · {task_id} {stage} · "{desc}"
    No task:  HEAT_DONE {signal} {forge_id} h{heat} · (no task) · "{notes}"

    Signal emoji already encodes the value bracket (🟢 ≥0.7 / 🟡 <0.7 /
    🔴 rollback); we drop the raw decimal from the wire because a wake-up
    message reads better as identity + context. Marshal pattern-matches
    on the 'HEAT_DONE ' prefix — that's preserved (space-separated, no
    colon — the old ': ' form survives as a substring match too).
    """
    forge_tag = forge_id or "(unknown-forge)"
    if task_id in (None, "generated") or task is None:
        snippet = _truncate_for_nudge(notes) or "(no notes)"
        return (f'HEAT_DONE {signal} {forge_tag} h{heat} '
                f'· (no task) · "{snippet}"')
    ini = task.get("initiative_id")
    stage_part = f"{stage}/{ini}" if ini else stage
    desc = _truncate_for_nudge(task.get("desc") or "") or "(no desc)"
    return (f'HEAT_DONE {signal} {forge_tag} h{heat} '
            f'· {task_id} {stage_part} · "{desc}"')


def _reconcile_submitted(root):
    """ini-024 T1: Assembly reconciliation — scan state.queue for tasks that
    look ready for merge based on truth (status=submitted + branch exists in
    git), and return the first one as a synthesized queue item. Intended as
    a backstop for when .assembly-queue.jsonl is empty/missing despite real
    work existing on disk.

    A task is eligible when ALL of:
      - status == "submitted"
      - assigned_forge is set (can't derive a branch name otherwise)
      - branch `<forge-id>/<task-id>` resolves via `git rev-parse --verify`

    Returns a dict shaped like a jsonl row (forge_id, task_id, branch, sha,
    reconciled=True) or None when nothing eligible is found. Does not mutate
    anything — the caller drives the normal rebase/test/merge pipeline.
    """
    import subprocess as _subprocess
    state = load_state(root)
    for task in state.get("queue", []):
        if task.get("status") != "submitted":
            continue
        forge_id = task.get("assigned_forge")
        task_id = task.get("id")
        if not forge_id or not task_id:
            # No way to derive the branch — skip rather than guess. A patrol
            # check (t-491) surfaces submitted-without-forge as a separate
            # class of issue.
            continue
        branch = f"{forge_id}/{task_id}"
        r = _subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", branch],
            cwd=str(root), capture_output=True, text=True,
        )
        if r.returncode != 0:
            # No branch on disk — skipping is the safe path (don't
            # synthesize a ghost merge for a task that was marked
            # submitted but never pushed a branch). Patrol's submitted-
            # without-branch check will catch the data-integrity issue
            # separately.
            continue
        return {
            "forge_id": forge_id,
            "task_id": task_id,
            "branch": branch,
            "sha": r.stdout.strip(),
            "reconciled": True,
        }
    return None


def _batch_window_decision(entries: list, now, idle_timer_s: int = 60) -> dict:
    """ini-020 §(c): decide whether the batcher should fire. Returns
    {"action": "go" | "wait" | "idle", "depth": int, ...}.

    - depth >= 2 → go immediately.
    - depth == 1 → go only if the singleton is >= idle_timer_s old;
      else wait (a sibling may land).
    - depth == 0 → idle.
    """
    depth = len(entries)
    if depth == 0:
        return {"action": "idle", "depth": 0}
    if depth >= 2:
        return {"action": "go", "depth": depth}
    # depth == 1
    try:
        sub_at = datetime.fromisoformat(entries[0].get("submitted_at", ""))
    except (TypeError, ValueError):
        # No / bad timestamp → fire to avoid permanent wait.
        return {"action": "go", "depth": 1, "reason": "missing timestamp"}
    age_s = (now - sub_at).total_seconds()
    if age_s >= idle_timer_s:
        return {"action": "go", "depth": 1, "age_s": age_s,
                "reason": "singleton idle timeout"}
    return {"action": "wait", "depth": 1, "age_s": age_s,
            "idle_timer_s": idle_timer_s}


@cli.command("assembly-batch-tick")
@click.option("--base", default="main", help="Base branch (default main).")
@click.option("--idle-timer-s", type=int, default=60,
              help="Singleton wait threshold before N=1 fallback fires.")
@click.option("--dry-run", is_flag=True, default=False)
@click.pass_context
def assembly_batch_tick_cmd(ctx, base, idle_timer_s, dry_run):
    """ini-020 impl-T1 (t-511) + impl-T3 (t-513): batch-drain
    .assembly-queue.jsonl through the staging worktree with one pytest
    run on green; on red, bisect to the offending entry (with one
    flaky retry), reject it, and land the green prefix. Retains the
    legacy single-task `assembly-tick` path (impl-T5 will retire it).
    """
    from .assembly import (
        ensure_staging_worktree, _STAGING_WORKTREE,
        run_batch, run_batch_tests, ensure_staging_venv_versioned,
        smithy_tree_hash, staging_path, reset_staging_to,
        delete_forge_branch, bisect_batch,
    )
    import subprocess as _sp

    root = ctx.obj["root"]
    qpath = assembly_queue_path(root)
    if not qpath.exists() or qpath.stat().st_size == 0:
        _output({"status": "empty"})
        return

    entries = []
    for ln in qpath.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            continue

    def _pop_rows(ids):
        """Drop rows whose task_id ∈ ids from .assembly-queue.jsonl.
        Unparseable rows are kept (same invariant as `_pop_queue`); no
        lock needed because Assembly is singleton per rig."""
        if not ids or not qpath.exists():
            return
        keep = []
        for ln in qpath.read_text().splitlines():
            if not ln.strip():
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                keep.append(ln)
                continue
            if row.get("task_id") in ids:
                continue
            keep.append(ln)
        qpath.write_text("\n".join(keep) + "\n" if keep else "")

    now = datetime.now(timezone.utc)
    window = _batch_window_decision(entries, now, idle_timer_s=idle_timer_s)
    if window["action"] != "go":
        _output({"status": window["action"], **window})
        return

    if dry_run:
        _output({"status": "would_process", "window": window,
                 "entries": entries})
        return

    # 1. Merge each entry into staging sequentially.
    batch = run_batch(root, entries, base=base)
    if batch.get("status") != "ok":
        _output({"status": "error",
                 "detail": batch.get("detail", "run_batch failed")})
        return
    green = [m for m in batch["merged"]
             if m["status"] in ("clean", "mild")]
    severe = [m for m in batch["merged"] if m["status"] == "severe"]

    # 1b. t-512 (impl-T2): per-task assembly-reject for every severe
    # entry. Each rejection flips state to pending (+5 human_priority),
    # fires the ASSEMBLY_REJECTED nudge to Marshal, appends a worklog
    # reject row. The batch continues on the green subset (if any).
    # Reason is derived from run_batch's `detail` (which already carries
    # the conflicting-file list for merge conflicts or a one-line git
    # error for other severe cases). Truncate to 80 chars so the nudge
    # payload stays compact — per the task spec §(f).
    rejected_ids = set()
    for m in severe:
        e = m["entry"]
        raw = m.get("detail") or "severe conflict"
        reason = raw if len(raw) <= 80 else (raw[:77] + "...")
        _do_assembly_reject(root, e["task_id"], reason)
        _log(root, e["forge_id"], e["task_id"], "rejected", reason)
        rejected_ids.add(e["task_id"])

    # 1c. When the whole batch was rejected, skip the test + on-green
    # machinery entirely. The green subset is empty, staging is already
    # back at the last-good tip (`main` in this case, since run_batch
    # resets to main before doing any merge work), so there's nothing
    # to reset here — just pop the jsonl rows and emit telemetry.
    if not green:
        _pop_rows(rejected_ids)
        outcome = "all_rejected" if severe else "no_green"
        _emit_rig_event(root, "assembly_batch_merged", actor="assembly",
                        batch_size=0, batch_outcome=outcome,
                        severe_count=len(severe))
        _output({"status": outcome, "severe_count": len(severe),
                 "rejected_ids": sorted(rejected_ids),
                 "severe": [m.get("detail", "?") for m in severe]})
        return

    wt = staging_path(root)

    # 2. Venv: reuse if smithy hash unchanged, else recreate.
    smithy_hash = smithy_tree_hash(wt)
    venv_info = ensure_staging_venv_versioned(wt, smithy_hash=smithy_hash)
    if venv_info["status"] == "error":
        # Revert staging so we don't leave a half-merged tip across ticks.
        reset_staging_to(wt, base)
        _emit_rig_event(root, "assembly_batch_merged", actor="assembly",
                        batch_size=len(green), batch_outcome="venv_error")
        _output({"status": "venv_error",
                 "detail": venv_info.get("detail", "?")})
        return

    # 3. Single pytest run post-merge on staging's tip.
    n_batch = len(green)
    flaky = False
    bisect_info = None

    def _abort(detail, probes=0):
        """§(d): abort the tick — reset staging to base, LEAVE the
        queue intact (everything re-batches next tick), emit
        batch_outcome=aborted."""
        reset_staging_to(wt, base)
        _emit_rig_event(root, "assembly_batch_merged", actor="assembly",
                        batch_size=n_batch, batch_outcome="aborted",
                        probes=probes)
        _output({"status": "aborted", "detail": str(detail)[:200],
                 "probes": probes})

    try:
        tst = run_batch_tests(wt)
    except Exception as exc:
        _abort(exc)
        return
    if not tst["passed"]:
        # t-533: persist the full red-run trace BEFORE bisecting — the
        # truncated inline tail hid every real failure during the
        # 2026-06-12 gate crisis. The offender's reject reason carries
        # a file:// pointer to this log.
        batch_ids = sorted(m["entry"]["task_id"] for m in green)
        batch_tag = ("batch-" + (batch_ids[0] if batch_ids else "empty")
                     + (f"+{len(batch_ids) - 1}" if len(batch_ids) > 1 else ""))
        red_log_path = _persist_test_log(
            root, batch_tag,
            tst.get("output_full") or tst.get("output", ""),
        )
        # t-513 (impl-T3): bisect the red batch down to one offender.
        # N=1 needs no probes — the sole entry is the candidate.
        bs = (bisect_batch(wt, green) if n_batch > 1 else
              {"status": "isolated", "offender_index": 0,
               "offender": green[0], "green_prefix": [], "probes": 0})
        if bs["status"] != "isolated":
            _abort(bs.get("detail", "bisect failed"),
                   probes=bs.get("probes", 0))
            return
        offender = bs["offender"]

        # Flaky retry: one rerun at the offender's accumulated sha
        # before declaring it guilty. A pass means the red was flaky —
        # do NOT reject; land the WHOLE batch. Only one retry; a
        # second red confirms a real failure.
        retry = None
        rs = reset_staging_to(wt, offender["sha"])
        if rs["status"] == "ready":
            try:
                retry = run_batch_tests(wt)
            except Exception as exc:
                _abort(exc, probes=bs["probes"])
                return
        if retry is not None and retry["passed"]:
            flaky = True
            _emit_rig_event(root, "flaky_test_observed", actor="assembly",
                            batch_size=n_batch,
                            offender_candidate=offender["entry"]["task_id"],
                            returncode=tst.get("returncode"))
        else:
            # Confirmed offender: per-task reject (t-512 shape), land
            # the green prefix, leave post-offender entries queued —
            # they re-batch next tick without the offender.
            bisect_info = bs
            e = offender["entry"]
            reason = f"batch-bisect isolated from N={n_batch}"
            if red_log_path is not None:
                # t-533: point at the persisted full trace.
                reason += f" (full trace: file://{red_log_path})"
            _do_assembly_reject(root, e["task_id"], reason)
            _log(root, e["forge_id"], e["task_id"], "rejected", reason)
            rejected_ids.add(e["task_id"])
            green = bs["green_prefix"]
            _emit_rig_event(root, "assembly_batch_bisect", actor="assembly",
                            batch_size=n_batch, narrowed_to=1,
                            green_landed=len(green), probes=bs["probes"],
                            log_path=red_log_path)
            if not green:
                # Offender was the first entry — nothing to land.
                _pop_rows(rejected_ids)
                reset_staging_to(wt, base)
                _output({"status": "bisect_rejected",
                         "offender": e["task_id"],
                         "green_landed": 0,
                         "probes": bs["probes"],
                         "rejected_ids": sorted(rejected_ids)})
                return

    # 4. On-green: fast-forward-equivalent merge the landing tip into
    # main. After a bisect that's the green prefix's accumulated sha;
    # otherwise (clean green or flaky-forgiven) the full batch tip.
    staging_tip = (green[-1]["sha"] if bisect_info else
                   batch.get("staging_tip") or
                   _sp.run(["git", "rev-parse", "HEAD"], cwd=str(wt),
                           capture_output=True, text=True).stdout.strip())
    co = _sp.run(["git", "checkout", base], cwd=str(root),
                 capture_output=True, text=True)
    if co.returncode != 0:
        _output({"status": "error",
                 "detail": f"main checkout: {co.stderr.strip()}"})
        return
    mr = _sp.run(
        ["git", "merge", "--no-ff", "--no-edit",
         "-m", f"[assembly] batch merge {len(green)} task(s) → {base}",
         staging_tip],
        cwd=str(root), capture_output=True, text=True,
    )
    if mr.returncode != 0:
        _output({"status": "error",
                 "detail": f"main merge: {mr.stderr.strip()}"})
        return

    # 5. Per-entry state flip + branch cleanup + audit log.
    for m in green:
        e = m["entry"]
        _do_assembly_merge(root, e["task_id"], m["sha"],
                           resolution=(m["status"] == "mild"))
        _log(root, e["forge_id"], e["task_id"], "merged", m["sha"])
        delete_forge_branch(root, e["forge_id"], e["task_id"], force=True)

    # 6. Advisory push (t-438 semantics — never fails the batch).
    # t-545: honour the SMITHY_PUSH_ENABLED kill switch, and record
    # failures as an assembly-log audit row (not just telemetry) so a
    # silently-failing push is visible where rejects are triaged.
    from .assembly import push_enabled
    push_status = "skipped"
    push_reason = ""
    if not push_enabled():
        push_reason = "disabled by SMITHY_PUSH_ENABLED"
    else:
        try:
            pr = _sp.run(["git", "push", "origin", base],
                         cwd=str(root), capture_output=True, text=True, timeout=30)
            push_status = "ok" if pr.returncode == 0 else "failed"
            if pr.returncode != 0:
                tail = (pr.stderr or pr.stdout or "").strip().splitlines()
                push_reason = (tail[-1] if tail else "")[:200]
        except (subprocess.TimeoutExpired, Exception) as exc:
            push_status = "failed"
            push_reason = str(exc)[:200]
        if push_status == "failed":
            _log(root, "assembly", "batch", "push_failed", push_reason)

    # 7. Atomic pop of the landed entries + everything we assembly-
    # rejected above (severe merges from 1b, bisect offender from 3).
    # Post-offender entries after a bisect are NOT in either set, so
    # their rows survive and re-batch next tick.
    _pop_rows({m["entry"]["task_id"] for m in green} | rejected_ids)

    # 8. Telemetry. t-512: partial_reject when the batch had any
    # severe-rejected entries alongside the green ones; t-513:
    # bisect_partial when a bisect landed a green prefix.
    outcome = ("bisect_partial" if bisect_info
               else "partial_reject" if severe else "green")
    _emit_rig_event(
        root, "assembly_batch_merged", actor="assembly",
        batch_size=len(green), batch_outcome=outcome,
        severe_count=len(severe),
        venv_recreated=bool(venv_info.get("recreated")),
        push_status=push_status,
        flaky=flaky,
    )

    _output({
        "status": "merged",
        "outcome": outcome,
        "batch_size": len(green),
        "merged_ids": sorted({m["entry"]["task_id"] for m in green}),
        "rejected_ids": sorted(rejected_ids),
        "severe_count": len(severe),
        "flaky": flaky,
        "venv": {"status": venv_info["status"],
                 "recreated": venv_info.get("recreated", False)},
        "push": {"status": push_status, "reason": push_reason},
        "staging_tip": staging_tip,
    })


@cli.command("forge-spawn")
@click.argument("forge_id")
@click.option("--base", default="main", help="Base branch for the worktree.")
@click.pass_context
def forge_spawn_cmd(ctx, forge_id, base):
    """t-397 I2: Create a git worktree for a new Forge and register it.

    Refuses to run past state.parallel.max_forges, refuses duplicate ids,
    and is idempotent on the state-registration step (but won't re-create
    an existing worktree — clean up first with forge-reset).
    """
    import subprocess
    root = ctx.obj["root"]
    state = load_state(root)
    parallel = state.setdefault("parallel", {})
    forges = parallel.setdefault("forges", [])
    existing = {f["id"] for f in forges}
    if forge_id in existing:
        _output({"error": f"forge {forge_id} already registered"})
        sys.exit(1)
    max_forges = parallel.get("max_forges", 1)
    if len(forges) >= max_forges:
        _output({"error": f"already at max_forges={max_forges}; bump the cap first",
                 "forges": sorted(existing)})
        sys.exit(1)

    worktree_dir = root / ".worktrees" / forge_id
    if worktree_dir.exists():
        _output({"error": f"worktree path {worktree_dir} already exists",
                 "hint": "remove the directory or run 'git worktree remove' first"})
        sys.exit(1)

    branch = f"{forge_id}/scratch"
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_dir), base],
        cwd=str(root), capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"error": "git worktree add failed", "stderr": result.stderr.strip()})
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    forges.append({
        "id": forge_id,
        "status": "idle",
        "current_task": None,
        "current_heat": None,
        "started_at": now,
        "last_heartbeat": now,
        "worktree": str(worktree_dir.relative_to(root)),
        "branch": branch,
    })
    save_state(root, state)
    _output({"spawned": forge_id, "worktree": str(worktree_dir),
             "branch": branch})
    _err(f"Forge {forge_id} spawned at {worktree_dir} (branch {branch}).")


@cli.command("forge-reset")
@click.argument("forge_id")
@click.option("--remove-worktree", is_flag=True, default=False,
              help="Also git-worktree-remove the Forge's worktree.")
@click.pass_context
def forge_reset_cmd(ctx, forge_id, remove_worktree):
    """t-397 I2: Reclaim a (possibly zombie) Forge.

    Clears its checkpoint; re-queues any in-flight task (status→pending,
    assigned_forge→null); resets the registry entry to idle. Optionally
    removes the git worktree so forge-spawn can re-create from scratch.
    The primary Forge (parallel.forges[0]) is refused to keep the default
    Forge alive. t-407 H2: identified by index, not by the literal name
    "forge-01".
    """
    import subprocess
    root = ctx.obj["root"]
    primary = primary_forge_id(root)
    if forge_id == primary:
        _output({"error": f"refusing to reset the primary forge ({primary})"})
        sys.exit(1)
    state = load_state(root)
    parallel = state.setdefault("parallel", {})
    forges = parallel.setdefault("forges", [])
    entry = next((f for f in forges if f["id"] == forge_id), None)
    if entry is None:
        _output({"error": f"forge {forge_id} not found"})
        sys.exit(1)

    requeued = None
    task_id = entry.get("current_task")
    if task_id:
        for t in state.get("queue", []):
            if t["id"] == task_id:
                t["status"] = "pending"
                t["assigned_forge"] = None
                requeued = task_id
                break

    cp = forge_checkpoint_path(root, forge_id)
    checkpoint_removed = cp.exists()
    if cp.exists():
        cp.unlink()

    entry["status"] = "idle"
    entry["current_task"] = None
    entry["current_heat"] = None

    worktree_removed = False
    if remove_worktree:
        wt = entry.get("worktree")
        if wt:
            wt_path = root / wt
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt_path)],
                cwd=str(root), capture_output=True, text=True,
            )
            worktree_removed = result.returncode == 0
            if result.returncode != 0:
                _err(f"(warn) git worktree remove failed: {result.stderr.strip()}")

    save_state(root, state)
    _output({"reset": forge_id, "requeued_task": requeued,
             "checkpoint_removed": checkpoint_removed,
             "worktree_removed": worktree_removed})
    _err(f"Forge {forge_id} reset" + (f" (requeued {requeued})" if requeued else ""))


@cli.command("validate")
@click.pass_context
def validate(ctx):
    """Validate state.json consistency."""
    root = ctx.obj["root"]
    state = load_state(root)
    errors = validate_state(state)

    if errors:
        _output({"valid": False, "errors": errors})
        _err(f"Validation FAILED: {len(errors)} errors")
        sys.exit(1)
    else:
        _output({"valid": True, "errors": []})
        _err("Validation passed ✓")


@cli.command("status")
@click.pass_context
def status(ctx):
    """Show current project status (L0/L1)."""
    root = ctx.obj["root"]
    state = load_state(root)
    budget = state["budget"]

    stages_summary = {}
    for name, s in state["stages"].items():
        stages_summary[name] = {
            "progress": s.get("progress", 0),
            "heats": s.get("heats", 0),
        }

    pending = [t for t in state.get("queue", []) if t["status"] == "pending"]
    bp = _backpressure_check(root, state)

    _output({
        "project": state.get("project", "unknown"),
        "used": budget["used"],
        "total": budget["total_heats"],
        "remaining": budget["total_heats"] - budget["used"],
        "overall_progress": state.get("overall_progress", 0),
        "stages": stages_summary,
        "pending_tasks": len(pending),
        # t-516: surface Assembly-queue backpressure in status so
        # tuning is informed, not guessed.
        "assembly_queue": {
            "depth": bp["depth"],
            "threshold": bp["threshold"],
            "multiplier": bp["multiplier"],
            "n_forges": bp["n_forges"],
            "backpressured": not bp["ok"],
        },
    })
    _err(
        f"Assembly queue: {bp['depth']}/{bp['threshold']} "
        f"(multiplier={bp['multiplier']})"
    )


@cli.command("stats")
@click.pass_context
def stats(ctx):
    """Show detailed project statistics — heat rate, stage distribution, value trends."""
    root = ctx.obj["root"]
    state = load_state(root)

    # Read worklog for time-based stats — t-454: anchor to main repo so a
    # stale worktree-local copy doesn't skew the read.
    wl_path = worklog_path(root)
    heats = []
    if wl_path.exists():
        for line in wl_path.read_text().strip().split("\n")[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 8:
                heats.append({
                    "timestamp": parts[0], "heat": parts[1], "stage": parts[2],
                    "value": float(parts[5]) if parts[5] else 0,
                    "signal": parts[6],
                })

    total_heats = len(heats)

    # Stage distribution
    stage_counts = {}
    stage_values = {}
    for h in heats:
        s = h["stage"]
        stage_counts[s] = stage_counts.get(s, 0) + 1
        stage_values.setdefault(s, []).append(h["value"])

    stage_dist = {}
    for s in VALID_STAGES:
        count = stage_counts.get(s, 0)
        vals = stage_values.get(s, [])
        stage_dist[s] = {
            "heats": count,
            "pct": round(count / total_heats * 100, 1) if total_heats else 0,
            "avg_value": round(sum(vals) / len(vals), 2) if vals else 0,
        }

    # Signal counts
    signals = {"🟢": 0, "🟡": 0, "🔴": 0}
    for h in heats:
        sig = h["signal"]
        if sig in signals:
            signals[sig] += 1

    # Themes + initiatives
    themes = state.get("themes", [])
    initiatives = state.get("initiatives", [])
    active_ini = [i for i in initiatives if i["status"] == "active"]

    _output({
        "total_heats": total_heats,
        "stage_distribution": stage_dist,
        "signals": signals,
        "themes": len(themes),
        "initiatives": {"total": len(initiatives), "active": len(active_ini)},
        "queue_size": len([t for t in state.get("queue", []) if t["status"] == "pending"]),
    })


@cli.command("add-task")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.argument("desc")
@click.option("--priority", type=int, default=2, help="Priority (0=highest, 3=lowest)")
@click.option("--blocked-by", multiple=True, help="Task IDs this is blocked by")
@click.option("--initiative", "initiative_id", default=None, help="Link to initiative ID")
@click.pass_context
def add_task(ctx, stage, desc, priority, blocked_by, initiative_id):
    """Add a new task to the queue."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])

    # Validate initiative if provided
    if initiative_id:
        ini_map = {i["id"]: i for i in state.get("initiatives", [])}
        if initiative_id not in ini_map:
            _output({"error": f"Initiative {initiative_id} not found"})
            sys.exit(1)
        if ini_map[initiative_id]["status"] not in ("approved", "active"):
            _output({"error": f"Initiative {initiative_id} status is '{ini_map[initiative_id]['status']}' — must be approved or active"})
            sys.exit(1)

    # Generate next task ID
    existing_ids = [t["id"] for t in queue]
    max_num = 0
    for tid in existing_ids:
        if tid.startswith("t-"):
            try:
                max_num = max(max_num, int(tid[2:]))
            except ValueError:
                pass
    new_id = f"t-{max_num + 1:03d}"

    task = {
        "id": new_id,
        "stage": stage,
        "desc": desc,
        "status": "pending",
        "priority": priority,
        "blocked_by": list(blocked_by),
        # t-471: initiative_id is the canonical schema (t-447 invariant).
        # Always write the key, defaulting to None, so freshly-added tasks
        # can never break test_every_task_has_initiative_id_field. Before
        # this, the field was only set when --initiative was passed, which
        # landed t-470 in state.json without it and blocked Assembly for
        # every submission afterward.
        "initiative_id": initiative_id,
    }

    task["human_priority"] = None
    task["priority_reason"] = _build_priority_reason(state, task)

    queue.append(task)
    state["queue"] = queue
    save_state(root, state)

    _output({"task": task})
    _err(f"Added {new_id}: {desc}")


@cli.command("complete-task")
@click.argument("task_id")
@click.pass_context
def complete_task(ctx, task_id):
    """Mark a task as complete."""
    root = ctx.obj["root"]
    state = load_state(root)

    for task in state.get("queue", []):
        if task["id"] == task_id:
            task["status"] = "complete"
            task["human_priority"] = None
            task["priority_reason"] = None
            save_state(root, state)
            _output({"task": task})
            _err(f"Completed {task_id}")
            return

    _output({"error": f"Task {task_id} not found"})
    sys.exit(1)


@cli.command("set-priority")
@click.argument("task_id")
@click.argument("priority", type=int)
@click.pass_context
def set_priority(ctx, task_id, priority):
    """Set a task's priority (0=highest, 3=lowest)."""
    root = ctx.obj["root"]

    if priority < 0 or priority > 3:
        _output({"error": f"Priority must be 0-3, got {priority}"})
        sys.exit(1)

    state = load_state(root)
    for task in state.get("queue", []):
        if task["id"] == task_id:
            old_priority = task.get("priority", 2)
            task["priority"] = priority
            if task.get("human_priority") is None:
                task["priority_reason"] = _build_priority_reason(state, task)
            save_state(root, state)
            _output({"task": task, "old_priority": old_priority})
            _err(f"Set {task_id} priority: {old_priority} → {priority}")
            return

    _output({"error": f"Task {task_id} not found in queue"})
    sys.exit(1)


# t-442 (ini-018 Task 3/4): Assembly-queue back-pressure.
#
# Marshal's dispatch path must slow down when Assembly is buried. The
# signal is the length of `.assembly-queue.jsonl` at the MAIN repo root
# — one line per submitted-but-not-yet-merged task. If that depth
# reaches 2x the number of registered Forges, we refuse new dispatches
# so Assembly has room to drain without the queue ballooning further.
#
# Scope: queue-pop (Forge's dispatch moment) and set-next-tasks
# (Marshal's bulk dispatch). queue-push is intentionally untouched —
# Marshal still records priorities; only hand-off to a Forge is
# throttled. Patrol check #9 (t-423) is orthogonal (it flags *stale*
# submitted rows, regardless of depth) and keeps running as usual.


def _assembly_queue_depth(root) -> int:
    """Count live entries in .assembly-queue.jsonl (empty lines skipped).
    Returns 0 when the file doesn't exist yet."""
    qpath = assembly_queue_path(root)
    if not qpath.exists():
        return 0
    try:
        return sum(1 for ln in qpath.read_text().splitlines() if ln.strip())
    except OSError:
        return 0


_DEFAULT_BACKPRESSURE_MULTIPLIER = 4


def _backpressure_multiplier(state) -> int:
    """t-516: resolve the backpressure multiplier with precedence
    FORGE_BACKPRESSURE_MULTIPLIER env > state.parallel.backpressure_multiplier
    > default (4). Rejects non-positive or non-integer values by falling
    through to the next layer so a typo can't accidentally 0-out the
    threshold."""
    import os
    for source in (
        os.environ.get("FORGE_BACKPRESSURE_MULTIPLIER"),
        (state.get("parallel") or {}).get("backpressure_multiplier"),
    ):
        if source is None or source == "":
            continue
        try:
            v = int(source)
        except (TypeError, ValueError):
            continue
        if v >= 1:
            return v
    return _DEFAULT_BACKPRESSURE_MULTIPLIER


def _backpressure_check(root, state) -> dict:
    """Return {"ok": bool, "depth": int, "n_forges": int,
               "multiplier": int, "threshold": int, "reason": str | None}.

    `ok=False` means Marshal's dispatch path should refuse and surface
    the reason. Threshold = multiplier * max(1, n_forges). The
    multiplier defaults to 4 (t-516); override per-rig via
    `state.parallel.backpressure_multiplier` or per-run via the
    FORGE_BACKPRESSURE_MULTIPLIER env var.
    """
    parallel = state.get("parallel") or {}
    n_forges = len((parallel.get("forges") or []))
    multiplier = _backpressure_multiplier(state)
    threshold = multiplier * max(1, n_forges)
    depth = _assembly_queue_depth(root)
    if depth >= threshold:
        return {"ok": False, "depth": depth, "n_forges": n_forges,
                "multiplier": multiplier, "threshold": threshold,
                "reason": (
                    f"assembly-queue backpressure (depth={depth}, "
                    f"threshold={threshold} [multiplier={multiplier} "
                    f"× forges={n_forges}])"
                )}
    return {"ok": True, "depth": depth, "n_forges": n_forges,
            "multiplier": multiplier, "threshold": threshold,
            "reason": None}


@cli.command("set-next-tasks")
@click.argument("task_ids", nargs=-1, required=True)
@click.option("--no-nudge", is_flag=True, default=False, help="Skip auto-nudge to forge")
@click.pass_context
def set_next_tasks(ctx, task_ids, no_nudge):
    """Set the ordered list of upcoming tasks for Marshal/Forge."""
    root = ctx.obj["root"]
    state = load_state(root)

    # t-442: refuse bulk dispatch when Assembly is saturated.
    bp = _backpressure_check(root, state)
    if not bp["ok"]:
        _output({"error": bp["reason"], "dispatched": False,
                 "depth": bp["depth"], "threshold": bp["threshold"],
                 "n_forges": bp["n_forges"]})
        _err(f"set-next-tasks refused: {bp['reason']}")
        sys.exit(1)

    queue = state.get("queue", [])
    queue_map = {t["id"]: t for t in queue}

    # Validate all task IDs exist and are pending
    errors = []
    for tid in task_ids:
        if tid not in queue_map:
            errors.append(f"{tid}: not found in queue")
        elif queue_map[tid]["status"] != "pending":
            errors.append(f"{tid}: status is '{queue_map[tid]['status']}', not pending")
    if errors:
        _output({"error": "Invalid task IDs", "details": errors})
        sys.exit(1)

    ordered = list(task_ids)
    state["next_tasks"] = ordered

    # Refresh priority_reason for agent-ordered tasks; preserve human-set reasons.
    for tid in ordered:
        t = queue_map[tid]
        if t.get("human_priority") is None:
            t["priority_reason"] = _build_priority_reason(state, t)

    save_state(root, state)

    result = {"next_tasks": ordered, "count": len(ordered)}
    _emit_rig_event(root, "queue_set", actor="marshal",
                    task_ids=ordered, count=len(ordered))

    # t-530: fan out nudges to every distinct forge that has a task
    # anywhere in `ordered`, not just the forge that owns ordered[0].
    # Prior behaviour left non-top pinned forges idle indefinitely
    # (observed 2026-04-19: forge-quench idle 15m with its P0 at
    # queue position 3). Build `forge_to_task`: first occurrence per
    # forge wins — dedupe so a forge with N pinned tasks gets one
    # nudge, not N. Unassigned (assigned_forge is None) tasks route to
    # the primary forge as today.
    if not no_nudge:
        primary = primary_forge_id(state)
        # Ordered list of (target_forge, first_task_id, position) pairs.
        # Dict preserves insertion order, which is the canonical walk
        # order through `ordered` — the "first pinned task" each forge
        # hears about matches the nudge body we'd have sent in the
        # single-forge world.
        forge_to_task: dict = {}
        for idx, tid in enumerate(ordered):
            t = queue_map.get(tid, {})
            target = t.get("assigned_forge") or primary
            if target not in forge_to_task:
                forge_to_task[target] = (tid, idx + 1)  # 1-based position

        nudges = []
        for target, (tid, pos) in forge_to_task.items():
            t = queue_map.get(tid, {})
            desc = t.get("desc", "")[:60]
            if pos == 1 and len(ordered) == 1:
                # Preserve the classic single-task message shape.
                msg = f"Queue updated. {len(ordered)} tasks ready. Top: {tid} — {desc}"
            elif pos == 1:
                msg = (f"Queue updated. {len(ordered)} tasks ready. "
                       f"Top: {tid} — {desc}")
            else:
                msg = (f"Queue updated. Your next task: {tid} "
                       f"at position {pos} — {desc}")
            nudge_result = _nudge_persona(target, msg, root=root)
            nudges.append({"target": target, "task_id": tid,
                           "position": pos, "result": nudge_result})
            _emit_rig_event(root, "nudge_sent", actor="marshal",
                            target=target, task_id=tid,
                            nudged=nudge_result.get("nudged"))

        result["nudges"] = nudges
        # Back-compat: surface the top-task nudge under the legacy
        # `nudge` key so existing callers that read result["nudge"]
        # don't break.
        if nudges:
            result["nudge"] = nudges[0]["result"]
        delivered = [n["target"] for n in nudges if n["result"].get("nudged")]
        if delivered:
            _err(f"Set {len(ordered)} next tasks: {', '.join(ordered)} "
                 f"— nudged {len(delivered)}/{len(nudges)}: "
                 f"{', '.join(delivered)}")
        else:
            _err(f"Set {len(ordered)} next tasks: {', '.join(ordered)} — no nudges delivered")
    else:
        result["nudge"] = {"nudged": False, "reason": "skipped (--no-nudge)"}
        result["nudges"] = []
        _err(f"Set {len(ordered)} next tasks: {', '.join(ordered)}")

    _output(result)


# --- t-497 (ini-024 T4): Marshal next_tasks invariant ---------------------
#
# Invariant: if next_tasks is empty AND at least one idle forge exists AND
# pending eligible tasks exist AND halt_flag is False AND budget remains,
# next_tasks MUST be repopulated with one eligible task per idle forge
# (de-duplicated). Marshal calls `smithy reconcile-next-tasks` every idle
# tick — both on nudge and on the idle timer — so a Marshal hiccup no
# longer freezes the rig. Correctness lives in Forge reconciliation
# (t-495/t-496); this is the optimization layer.
#
# Design details: plans/liveness-reconciliation-design.md §Marshal.


@cli.command("reconcile-next-tasks")
@click.option("--dry-run", is_flag=True, default=False,
              help="Compute the repopulation but don't write state.")
@click.option("--no-nudge", is_flag=True, default=False,
              help="Skip the auto-nudge to the first idle forge.")
@click.pass_context
def reconcile_next_tasks(ctx, dry_run, no_nudge):
    """t-497: repopulate next_tasks when the invariant is unmet.

    Invariant: next_tasks is empty AND ≥1 idle forge AND eligible pending
    tasks exist AND halt is off AND budget remains → populate up to N
    entries (N = idle forges) via the existing priority-walk.

    Idempotent. Runs every Marshal idle tick. No-op in the common case.
    """
    root = ctx.obj["root"]
    state = load_state(root)

    # --- invariant preconditions ----------------------------------------
    reasons = []
    parallel = state.get("parallel") or {}
    if parallel.get("halt_flag"):
        reasons.append("halt_flag=true")

    budget = state.get("budget") or {}
    total = budget.get("total_heats", 0) or 0
    used = budget.get("used", 0) or 0
    if total > 0 and used >= total:
        reasons.append("budget exhausted")

    current_next = list(state.get("next_tasks") or [])
    if current_next:
        reasons.append(f"next_tasks already populated ({len(current_next)})")

    forges = parallel.get("forges") or []
    idle_forges = [f for f in forges
                   if f.get("status") == "idle" and not f.get("current_task")]
    if not idle_forges:
        reasons.append("no idle forges")

    queue = state.get("queue") or []
    if not any(t.get("status") == "pending" for t in queue):
        reasons.append("no pending tasks")

    if reasons:
        _output({"repopulated": False, "next_tasks": current_next,
                 "skip_reasons": reasons})
        _err(f"reconcile: no-op ({', '.join(reasons)})")
        return

    # --- pick one eligible task per idle forge --------------------------
    #
    # `select_task_for_forge` already encodes the full constraint walk
    # (stage balance, priority, blocked_by, affinity, touches, serial /
    # parallel). Reusing it keeps the invariant aligned with Marshal's
    # existing priority logic — there's one ranking algorithm, not two.
    from smithy.dispatch import select_task_for_forge

    # We pick one task per idle forge by iterating: after picking for
    # forge-A, mark that task as in_progress in an in-memory copy of
    # state so the next walk for forge-B sees it as unavailable and
    # picks the next best option. Without this step, every unpinned
    # forge would pick the same top-priority task and only one would
    # survive the de-dup filter. The mutation is to a deep copy — the
    # caller's state dict is untouched until the final save below.
    import copy
    scratch = copy.deepcopy(state)
    scratch_queue_by_id = {t["id"]: t for t in scratch.get("queue") or []}

    picked = []
    # Visit idle forges in a stable order so the rig stays deterministic.
    for forge in sorted(idle_forges, key=lambda f: f.get("id", "")):
        fid = forge.get("id")
        if not fid:
            continue
        task = select_task_for_forge(scratch, fid)
        if task is None:
            continue
        tid = task.get("id")
        if not tid:
            continue
        picked.append(tid)
        # Mark the picked task in-flight in the scratch state so the
        # next forge's walk can't pick it again.
        if tid in scratch_queue_by_id:
            scratch_queue_by_id[tid]["status"] = "in_progress"
            scratch_queue_by_id[tid]["assigned_forge"] = fid

    if not picked:
        # Pending tasks exist but none are dispatchable right now (every
        # initiative may be serial-blocked, or affinity-pinned elsewhere).
        # Invariant is technically satisfied — there's nothing for these
        # forges to do. No-op.
        _output({"repopulated": False, "next_tasks": [],
                 "skip_reasons": ["no eligible pending tasks for idle forges"]})
        _err("reconcile: no-op (nothing dispatchable)")
        return

    if dry_run:
        _output({"repopulated": False, "next_tasks": picked,
                 "dry_run": True,
                 "idle_forges": [f.get("id") for f in idle_forges]})
        _err(f"reconcile (dry-run): would populate {len(picked)} task(s)")
        return

    # --- write + audit ---------------------------------------------------
    state["next_tasks"] = picked
    save_state(root, state)

    _emit_rig_event(
        root, "next_tasks_reconciled", actor="marshal",
        task_ids=picked,
        idle_forges=[f.get("id") for f in idle_forges],
        count=len(picked),
    )

    result = {"repopulated": True, "next_tasks": picked,
              "count": len(picked),
              "idle_forges": [f.get("id") for f in idle_forges]}

    # --- auto-nudge (fast path after the correctness path) -------------
    #
    # Nudge the forge assigned to the top task (or the primary forge if
    # unassigned). This mirrors set-next-tasks's nudge behaviour so
    # reconciliation and manual dispatch converge on the same cadence.
    if not no_nudge:
        queue_map = {t["id"]: t for t in queue}
        top_task = queue_map.get(picked[0], {})
        target = top_task.get("assigned_forge") or primary_forge_id(state)
        msg = (f"Queue reconciled. {len(picked)} task(s) ready. "
               f"Top: {picked[0]} — {top_task.get('desc','')[:60]}")
        nudge_result = _nudge_persona(target, msg, root=root)
        result["nudge"] = nudge_result
        _emit_rig_event(root, "nudge_sent", actor="marshal", target=target,
                        task_id=picked[0],
                        nudged=nudge_result.get("nudged"))

    _output(result)
    _err(f"reconcile: populated {len(picked)} task(s): {', '.join(picked)}")


@cli.command("queue")
@click.pass_context
def queue_show(ctx):
    """Show the current next_tasks queue with full task details."""
    root = ctx.obj["root"]
    state = load_state(root)
    next_tasks = state.get("next_tasks", [])
    queue = state.get("queue", [])
    queue_map = {t["id"]: t for t in queue}

    result = []
    for tid in next_tasks:
        task = queue_map.get(tid)
        if task:
            result.append({
                "id": task["id"],
                "stage": task.get("stage", ""),
                "priority": task.get("priority", 2),
                "status": task.get("status", "pending"),
                "desc": task.get("desc", "")[:120],
            })
        else:
            result.append({"id": tid, "error": "not found in queue"})

    _output({"queue": result, "count": len(result)})
    _err(f"Queue: {len(result)} tasks")


def _nudge_queue_path(root, persona):
    """Return the path to a persona's nudge queue file."""
    return root / ".smithy-nudge-queue" / f"{persona}.jsonl"


def _queue_nudge(root, persona, message):
    """Append a nudge to the persona's queue file (for when they're mid-heat)."""
    from datetime import datetime
    queue_dir = root / ".smithy-nudge-queue"
    queue_dir.mkdir(exist_ok=True)
    entry = json.dumps({
        "message": message,
        "timestamp": datetime.now().isoformat(),
    })
    queue_path = _nudge_queue_path(root, persona)
    with open(queue_path, "a") as f:
        f.write(entry + "\n")
    return queue_path


def _persona_is_busy(root, persona):
    """Check if a persona has an active checkpoint (mid-heat).

    t-542: per-Forge personas (forge-quench, forge-temper, …) resolve
    through `forge_checkpoint_path` — the old `.{persona}-checkpoint.json`
    guess never matched the real `.forge-checkpoint-<id>.json` name, so
    mid-heat Forges looked idle and got nudged/preempted."""
    if persona == "forge" or persona.startswith("forge-"):
        fid = None if persona == "forge" else persona
        return forge_checkpoint_path(root, fid).exists()
    cp_path = root / f".{persona}-checkpoint.json"
    return cp_path.exists()


def _pane_agent(path):
    """Derive agent name from a pane's cwd.

    t-414: worktree match now takes precedence over personas. A forge-quench
    pane whose cwd is `.worktrees/forge-quench/personas/forge` resolves to
    "forge-quench", not the generic "forge" — that's what makes per-Forge
    nudge routing possible at N≥2. Anvil and Assembly still live outside
    `.worktrees/` (per the Assembly-only-to-main rule), so the
    /personas/<name>/ suffix fallback resolves them to "anvil"/"assembly".
    """
    import re
    m = re.search(r"/\.worktrees/([^/]+)(?:/|$)", path)
    if m:
        return m.group(1)
    m = re.search(r"/personas/([^/]+)/?$", path)
    if m:
        return m.group(1)
    return None


def _forge_session():
    """tmux session name for the current rig. Defaults to 'forge'
    (t-408 layout); FORGE_SESSION env overrides for tests or alternate
    rigs. Replaces the old hardcoded 'smithy2' session name."""
    import os
    return os.environ.get("FORGE_SESSION", "forge")


def _resolve_pane(session, persona, forge_ids=None):
    """t-414: return (pane_id, reason). pane_id is the tmux id of the pane
    whose cwd maps to `persona` via _pane_agent; reason is a short string
    explaining why resolution failed (None on success).

    t-489: if `forge_ids` (the set of registered `parallel.forges[].id`s)
    is provided AND the session has panes but none of them map to any
    registered forge id, the session is treated as the wrong rig and a
    'no registered-forge panes' reason is returned. Callers use this
    signal to fail loudly rather than fall through to the silent
    .smithy-nudge-queue/ jsonl side-channel (observed 2026-04-18 when a
    stale 'smithy2' session lingered alongside the live 'forge').

    Verify: python3 -c "from smithy.cli import _resolve_pane; \
                         print(_resolve_pane('forge','marshal'))"
    """
    # t-429: pytest-context backstop lives in _nudge_persona (one level up),
    # not here — _resolve_pane returns a (pane_id, reason) tuple so a dict
    # short-circuit would break the unpacking contract.
    import subprocess
    chk = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True, text=True,
    )
    if chk.returncode != 0:
        return None, f"tmux session not found ('{session}')"
    ls = subprocess.run(
        ["tmux", "list-panes", "-t", session, "-s",
         "-F", "#{pane_id}\t#{pane_current_path}"],
        capture_output=True, text=True,
    )
    if ls.returncode != 0:
        return None, f"tmux list-panes failed: {ls.stderr.strip()}"

    pane_rows = []
    pane_agents = set()
    for line in ls.stdout.splitlines():
        if "\t" not in line:
            continue
        pid, path = line.split("\t", 1)
        pane_rows.append((pid, path))
        a = _pane_agent(path)
        if a:
            pane_agents.add(a)

    # t-489 roster-mismatch guard: a forge-ready tmux session is
    # characterised by having at least one pane whose _pane_agent maps
    # to either a registered `parallel.forges[].id` OR a worktree named
    # `forge-*`. The Apr 11 stale-session case had a single generic
    # shell window (pane_agents is empty). We return loudly so
    # _nudge_persona refuses to silently queue to jsonl. We only fire
    # when forges are registered (falsy/empty forge_ids = "don't know
    # enough, stay compatible with legacy callers").
    if forge_ids:
        has_forge_pane = any(
            a in forge_ids or a.startswith("forge-")
            for a in pane_agents
        )
        if not has_forge_pane:
            return None, (
                f"tmux session '{session}' has no registered-forge panes "
                f"(expected any of {sorted(forge_ids)} or forge-*, "
                f"saw {sorted(pane_agents) or '[none]'}) — "
                f"wrong session? set FORGE_SESSION to the live rig"
            )

    for pid, path in pane_rows:
        if _pane_agent(path) == persona:
            return pid, None
    return None, f"no pane for persona '{persona}' in session '{session}'"


def _nudge_persona(persona, message, root=None):
    """Send a message to a persona's pane in the FORGE_SESSION tmux session.

    Panes are resolved by `pane_current_path` via `_resolve_pane`. If the
    persona is mid-heat (checkpoint exists), queues the nudge to
    .smithy-nudge-queue/<persona>.jsonl instead of sending via tmux.

    Message text and Enter are two separate send-keys calls — the Claude
    Code TUI input box sometimes swallows a combined "text\\nEnter" so we
    deliver them independently.
    """
    import os
    import subprocess

    # t-519: opt-out env switch. Covers every code path (including
    # subprocess-spawned `smithy` CLI calls from tests) where the pytest-
    # context backstop below can't reach because the child process has a
    # fresh environment. Conftest autouse exports SMITHY_NUDGE_ENABLED=0
    # for every test run; the env inherits into subprocess.run children.
    if os.environ.get("SMITHY_NUDGE_ENABLED", "1") == "0":
        return {"nudged": False, "queued": False, "persona": persona,
                "target": None,
                "reason": "SMITHY_NUDGE_ENABLED=0"}

    # t-429: pytest-context backstop (in-process tests only — subprocess
    # calls from tests don't inherit PYTEST_CURRENT_TEST; that's what the
    # t-519 env switch above is for).
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"nudged": False, "queued": False, "persona": persona,
                "reason": "pytest context, nudge skipped"}

    session = _forge_session()

    if root and _persona_is_busy(root, persona):
        _queue_nudge(root, persona, message)
        return {"nudged": False, "queued": True, "persona": persona,
                "target": session,
                "reason": "persona mid-heat, nudge queued"}

    # t-489: read registered forge ids so _resolve_pane can distinguish
    # "session is wrong rig" from "persona has no pane". load_state can
    # raise (corrupt state, missing file); treat that as no-info and
    # preserve the legacy behaviour.
    forge_ids = None
    if root:
        try:
            _s = load_state(root)
            forge_ids = {
                f.get("id")
                for f in (_s.get("parallel") or {}).get("forges") or []
                if f.get("id")
            }
        except Exception:
            forge_ids = None

    pane_id, reason = _resolve_pane(session, persona, forge_ids=forge_ids)
    if pane_id is None:
        # t-489: wrong-session detected (pane roster has no forge panes).
        # Fail loudly rather than queue — the side-channel jsonl was what
        # let tasks t-448/t-474/t-479/t-480 sit unserved for ~25min.
        if reason and "no registered-forge panes" in reason:
            _err(f"nudge ERROR: {reason}")
            return {"nudged": False, "queued": False, "error": True,
                    "persona": persona, "target": session, "reason": reason}
        if root:
            _queue_nudge(root, persona, message)
            return {"nudged": False, "queued": True, "persona": persona,
                    "target": session,
                    "reason": f"{reason}, nudge queued"}
        return {"nudged": False, "queued": False,
                "reason": reason, "target": session}

    subprocess.run(
        ["tmux", "send-keys", "-t", pane_id, "--", message],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        ["tmux", "send-keys", "-t", pane_id, "Enter"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"nudged": False, "queued": False,
                "reason": f"send-keys failed: {r.stderr.strip()}",
                "target": pane_id}

    return {"nudged": True, "queued": False, "persona": persona,
            "target": pane_id, "message": message}


@cli.command("queue-push")
@click.argument("task_id")
@click.option("--top/--bottom", default=True, help="Insert at top (default) or bottom")
@click.option("--no-nudge", is_flag=True, default=False, help="Skip auto-nudge after push")
@click.option("--to", "target_persona", type=str, default="forge",
              help="Persona to nudge (default: forge; accepts forge-quench/"
                   "forge-temper/etc. or any registered forge id).")
@click.option("--forge", "assigned_forge", default=None,
              help="t-400 I5: Pin this task to the given Forge id (assigned_forge).")
@click.pass_context
def queue_push(ctx, task_id, top, no_nudge, target_persona, assigned_forge):
    """Add a task to the next_tasks queue and nudge the target persona.

    `--forge <id>` stamps `assigned_forge` on the task so only that Forge
    will pop it via `queue-pop --forge <id>`. Passing `--forge null` (or
    empty string) clears any prior assignment.
    """
    root = ctx.obj["root"]
    # t-426: serialise queue-push across actors (Anvil's manual fixes +
    # Marshal's automated re-prioritisations). Without the lock the
    # next_tasks list could lose one writer's update.
    with state_lock(root):
        state = load_state(root)
        queue_map = {t["id"]: t for t in state.get("queue", [])}

        if task_id not in queue_map:
            _output({"error": f"Task {task_id} not found in queue"})
            sys.exit(1)
        if queue_map[task_id]["status"] != "pending":
            _output({"error": f"Task {task_id} is {queue_map[task_id]['status']}, not pending"})
            sys.exit(1)

        # t-400 I5: stamp assigned_forge if --forge was given.
        if assigned_forge is not None:
            parallel = state.get("parallel") or {}
            forge_ids = {f.get("id") for f in (parallel.get("forges") or [])}
            if assigned_forge in ("", "null"):
                queue_map[task_id]["assigned_forge"] = None
            elif assigned_forge not in forge_ids:
                _output({"error": f"unknown forge id: {assigned_forge}",
                         "known": sorted(fid for fid in forge_ids if fid)})
                sys.exit(1)
            else:
                queue_map[task_id]["assigned_forge"] = assigned_forge

        next_tasks = state.get("next_tasks", [])
        # Remove if already present to avoid duplicates
        next_tasks = [t for t in next_tasks if t != task_id]
        if top:
            next_tasks.insert(0, task_id)
        else:
            next_tasks.append(task_id)
        state["next_tasks"] = next_tasks

        # Auto-populate priority_reason on push unless a human has set one.
        task = queue_map[task_id]
        if task.get("human_priority") is None:
            task["priority_reason"] = _build_priority_reason(state, task)

        save_state(root, state)

    position = "top" if top else "bottom"
    result = {"task_id": task_id, "position": position, "queue_size": len(next_tasks)}
    _emit_rig_event(root, "queue_push", actor="marshal", task_id=task_id,
                    position=position, queue_size=len(next_tasks))

    # Auto-nudge unless --no-nudge. Under t-414 routing, a generic "forge"
    # target resolves to the task's assigned_forge (if any) or the primary
    # Forge — otherwise _resolve_pane would miss every pane (they all report
    # forge-quench/forge-temper/…, not bare "forge").
    if not no_nudge:
        target = target_persona
        if target == "forge":
            target = queue_map[task_id].get("assigned_forge") \
                or primary_forge_id(state)
        _validate_persona(state, target, arg_name="--to/--forge")
        nudge_msg = f"Task {task_id} queued. Run smithy queue-pop to start."
        nudge_result = _nudge_persona(target, nudge_msg, root=root)
        result["nudge"] = nudge_result
        _emit_rig_event(root, "nudge_sent", actor="marshal", target=target,
                        task_id=task_id,
                        nudged=nudge_result.get("nudged"))
        if nudge_result["nudged"]:
            _err(f"Pushed {task_id} to {position} of queue ({len(next_tasks)} total) — nudged {target}")
        else:
            _err(f"Pushed {task_id} to {position} of queue ({len(next_tasks)} total) — nudge skipped: {nudge_result['reason']}")
    else:
        result["nudge"] = {"nudged": False, "reason": "skipped (--no-nudge)"}
        _err(f"Pushed {task_id} to {position} of queue ({len(next_tasks)} total)")

    _output(result)


@cli.command("dispatch-next")
@click.option("--forge", "forge_id", required=True,
              help="Forge id to dispatch for (walk initiatives from this "
                   "forge's perspective).")
@click.pass_context
def dispatch_next_cmd(ctx, forge_id):
    """t-441 (ini-018): advisory — pick the next task an idle forge should
    take, by walking initiatives with the multi-forge-poker constraints
    (parallelism / affinity / touches). Pure: does NOT pop, push, or
    mutate state. Marshal uses this to decide what to queue-push next.
    """
    from .dispatch import select_task_for_forge
    root = ctx.obj["root"]
    state = load_state(root)
    task = select_task_for_forge(state, forge_id)
    if task is None:
        _output({"task": None, "forge_id": forge_id,
                 "message": "no eligible task"})
        return
    _output({
        "forge_id":      forge_id,
        "task_id":       task["id"],
        "initiative_id": task.get("initiative_id"),
        "stage":         task.get("stage"),
        "priority":      task.get("priority"),
        "desc":          (task.get("desc") or "")[:200],
    })


@cli.command("queue-pop")
@click.option("--forge", "forge_id", default=None,
              help="t-400 I5: Only pop tasks unassigned or assigned to this forge.")
@click.pass_context
def queue_pop(ctx, forge_id):
    """Remove and return the first dispatchable task from next_tasks.

    With `--forge <id>`, skips tasks whose `assigned_forge` is set and does
    not match — so Forge-02 won't steal a task that Marshal pinned to
    Forge-01. Skipped-but-not-matching entries stay in the queue for their
    intended Forge; only status-stale entries are removed.
    """
    root = ctx.obj["root"]
    # t-407 H2: default --forge from cwd's worktree if caller omitted it.
    # Resolve outside the lock — it's a pure fs lookup.
    if forge_id is None:
        forge_id = detect_forge_from_cwd(root)

    # t-426: serialise queue-pop so two sibling Forges don't both claim
    # the same head of next_tasks. Was the contention point that drove
    # Marshal to reassign a task Forge-A was silently working on.
    skipped_stale: list[str] = []
    skipped_other_forge: list[str] = []
    task = None
    task_id = None
    empty = False
    remaining_len = 0
    with state_lock(root):
        state = load_state(root)
        next_tasks = state.get("next_tasks", [])

        # t-442: refuse dispatch when Assembly is saturated — keeps
        # Forge idling without clearing the pinned task from next_tasks.
        # Depth is read inside the lock so concurrent end-heat submits
        # don't race us into a wrong decision.
        bp = _backpressure_check(root, state)
        if not bp["ok"]:
            _output({"task": None, "dispatched": False,
                     "reason": bp["reason"],
                     "depth": bp["depth"],
                     "threshold": bp["threshold"],
                     "n_forges": bp["n_forges"]})
            _err(f"queue-pop backpressure: {bp['reason']}")
            return

        if not next_tasks:
            empty = True
        else:
            queue_by_id = {t["id"]: t for t in state.get("queue", [])}
            preserved: list[str] = []  # tasks not matching this forge — put back.
            while next_tasks:
                candidate_id = next_tasks.pop(0)
                candidate = queue_by_id.get(candidate_id)
                # Drop stale (missing / non-pending) entries outright.
                if not candidate or candidate.get("status") != "pending":
                    skipped_stale.append(candidate_id)
                    continue
                # If a --forge filter is in play, respect assigned_forge pinning.
                if forge_id is not None:
                    af = candidate.get("assigned_forge")
                    if af is not None and af != forge_id:
                        skipped_other_forge.append(candidate_id)
                        preserved.append(candidate_id)
                        continue
                task_id = candidate_id
                task = candidate
                break

            # Put back tasks that belong to other Forges, in original order.
            state["next_tasks"] = preserved + next_tasks
            save_state(root, state)
            remaining_len = len(state["next_tasks"])

    if empty:
        _output({"task": None, "message": "Queue empty"})
        _err("Queue empty")
        return

    if task is None:
        _output({"task": None, "message": "Queue empty (no match)",
                 "skipped_stale": skipped_stale,
                 "skipped_other_forge": skipped_other_forge})
        _err(f"Queue empty — skipped stale={skipped_stale} other-forge={skipped_other_forge}")
        return

    if skipped_stale:
        _err(f"Skipped {len(skipped_stale)} stale head(s): {skipped_stale}")
    _emit_rig_event(root, "queue_pop", actor=forge_id or "queue",
                    task_id=task_id, forge_id=forge_id,
                    remaining=remaining_len)
    _output({"task_id": task_id, "task": task,
             "remaining": remaining_len,
             "skipped_stale": skipped_stale,
             "skipped_other_forge": skipped_other_forge})
    _err(f"Popped {task_id} ({remaining_len} remaining)")


@cli.command("peek")
@click.option("--forge", "forge_id", default=None,
              help="Simulate a --forge-filtered queue-pop for this forge id.")
@click.option("--limit", "limit", default=5, type=int,
              help="Cap the returned next_tasks list (default 5).")
@click.option("--summary", "summary", is_flag=True, default=False,
              help="Include a one-shot diagnostic dump: queue counts by "
                   "status, top-5 dispatchable pending tasks, assembly queue "
                   "depth, backpressure state, halt status, forges.")
@click.pass_context
def peek_cmd(ctx, forge_id, limit, summary):
    """t-521: read-only equivalent of queue-pop for diagnostics.

    `queue-pop` mutates state.json (removes from next_tasks, reports
    stale heads). `peek` returns the same dispatchability analysis with
    ZERO writes — safe to run from any pane (Anvil, Bellows, a human
    eyeballing the rig). Same filtering + ordering rules as queue-pop.

    Output JSON:
      next_tasks        — ordered list of the top N entries in
                          state.next_tasks (id + status + assigned_forge +
                          desc snippet for each)
      would_pop         — the task queue-pop would return for this forge,
                          or null if nothing matches
      skipped_other_forge — task_ids that would be skipped because they
                          are pinned to a different forge
      skipped_stale     — task_ids that would be dropped because their
                          queue entry is stale (task missing, not pending)
      blocked_in_queue  — task_ids in next_tasks whose blocked_by is
                          unmet (advisory — queue-pop doesn't filter on
                          deps today; included here for diagnostic value)
      limit_applied     — the limit in use

    With --summary, also emits:
      queue_counts      — {status: count} across the full state.queue
      dispatchable_top5 — top 5 pending + deps-met + unassigned-or-mine
                          tasks sorted by priority
      assembly_queue_depth — .assembly-queue.jsonl line count
      backpressure      — {ok, reason, depth, threshold, n_forges}
      halt_flag         — bool
      forges            — [{id, status, current_task}]
    """
    root = ctx.obj["root"]
    if forge_id is None:
        forge_id = detect_forge_from_cwd(root)

    # No lock — we never write.
    state = load_state(root)
    queue_by_id = {t["id"]: t for t in state.get("queue", [])}
    complete_ids = {t["id"] for t in state.get("queue", [])
                    if t.get("status") == "complete"}

    next_ids = list(state.get("next_tasks", []))
    preview = []
    for tid in next_ids[:limit]:
        t = queue_by_id.get(tid)
        preview.append({
            "id": tid,
            "status": (t or {}).get("status"),
            "assigned_forge": (t or {}).get("assigned_forge"),
            "desc": ((t or {}).get("desc") or "")[:80],
            "stale": t is None or t.get("status") != "pending",
        })

    # Mirror queue-pop's walk, but read-only.
    skipped_stale: list[str] = []
    skipped_other_forge: list[str] = []
    blocked_in_queue: list[str] = []
    would_pop = None
    for tid in next_ids:
        t = queue_by_id.get(tid)
        if not t or t.get("status") != "pending":
            skipped_stale.append(tid)
            continue
        if forge_id is not None:
            af = t.get("assigned_forge")
            if af is not None and af != forge_id:
                skipped_other_forge.append(tid)
                continue
        # queue-pop doesn't check blocked_by today — capture as advisory only.
        deps = t.get("blocked_by") or []
        if not all(d in complete_ids for d in deps):
            blocked_in_queue.append(tid)
        would_pop = t
        break

    result = {
        "next_tasks": preview,
        "would_pop": would_pop,
        "skipped_other_forge": skipped_other_forge,
        "skipped_stale": skipped_stale,
        "blocked_in_queue": blocked_in_queue,
        "limit_applied": limit,
        "forge_id": forge_id,
    }

    if summary:
        from collections import Counter
        queue_counts = dict(Counter(
            (t.get("status") or "unknown") for t in state.get("queue", [])
        ))
        # Dispatchable = pending + deps all complete + assigned_forge in
        # (None, forge_id). Sorted by priority ascending (0 best), then id.
        dispatchable = []
        for t in state.get("queue", []):
            if t.get("status") != "pending":
                continue
            if not all(d in complete_ids for d in (t.get("blocked_by") or [])):
                continue
            if forge_id is not None:
                af = t.get("assigned_forge")
                if af is not None and af != forge_id:
                    continue
            dispatchable.append(t)
        dispatchable.sort(
            key=lambda t: (int(t.get("priority", 2) or 2), t.get("id", "")))
        top5 = [
            {"id": t["id"], "priority": t.get("priority"),
             "stage": t.get("stage"),
             "initiative_id": t.get("initiative_id"),
             "assigned_forge": t.get("assigned_forge"),
             "desc": (t.get("desc") or "")[:80]}
            for t in dispatchable[:5]
        ]
        assy_queue = main_repo_root(root) / ".assembly-queue.jsonl"
        assy_depth = 0
        if assy_queue.exists():
            try:
                assy_depth = sum(1 for ln in assy_queue.read_text().splitlines()
                                 if ln.strip())
            except OSError:
                pass
        bp = _backpressure_check(root, state)
        parallel = state.get("parallel") or {}
        forges_out = [
            {"id": f.get("id"), "status": f.get("status"),
             "current_task": f.get("current_task")}
            for f in (parallel.get("forges") or [])
        ]
        result["summary"] = {
            "queue_counts": queue_counts,
            "dispatchable_top5": top5,
            "assembly_queue_depth": assy_depth,
            "backpressure": bp,
            "halt_flag": bool(parallel.get("halt_flag")),
            "forges": forges_out,
        }

    _output(result)
    _err(
        f"peek: next_tasks={len(next_ids)} would_pop={(would_pop or {}).get('id','-')}"
        f" skipped_other={len(skipped_other_forge)} skipped_stale={len(skipped_stale)}"
    )


@cli.command("claim-task")
@click.option("--forge", "forge_id", required=True,
              help="Forge id claiming the task (must be in parallel.forges[] roster).")
@click.pass_context
def claim_task_cmd(ctx, forge_id):
    """ini-024 T2: atomic pending → in_progress claim.

    Finds the highest-priority claimable task for `forge_id` (same
    ordering as Marshal's dispatch, but honours per-task `assigned_forge`
    pinning) and CAS-flips its status to `in_progress`, stamping
    `assigned_forge`. Writes state.json under the shared lock so two
    sibling Forges racing for the same task cannot both win.

    Intended as the correctness backstop for Forge reconciliation (T3):
    when the next_tasks queue is empty or stale, a Forge can claim work
    directly from truth (state.queue) instead of waiting for a Marshal
    push that may never arrive.

    Exit codes:
      0 — task claimed; stdout = {"task_id": ..., "task": {...}}
      1 — no eligible task (halted rig, empty queue, all pinned to
          someone else); stdout = {"task": null, "reason": "..."}
      2 — usage error (forge not in roster); stderr + non-zero rc
    """
    from .dispatch import claim_task_for_forge
    root = ctx.obj["root"]

    with state_lock(root):
        state = load_state(root)
        parallel = state.get("parallel") or {}

        roster = {f.get("id") for f in parallel.get("forges") or []}
        if roster and forge_id not in roster:
            _output({"error": f"forge {forge_id!r} not in parallel.forges[] roster",
                     "roster": sorted(roster)})
            _err(f"forge {forge_id!r} not in roster: {sorted(roster)}")
            sys.exit(2)

        if parallel.get("halt_flag"):
            _output({"task": None, "reason": "halted",
                     "halt_flag": True})
            _err(f"claim-task {forge_id}: rig halted")
            sys.exit(1)

        task = claim_task_for_forge(state, forge_id)
        if task is None:
            _output({"task": None, "reason": "no eligible task"})
            _err(f"claim-task {forge_id}: no eligible task")
            sys.exit(1)

        task_id = task["id"]
        # CAS: re-verify status inside the lock before flipping. Between
        # claim_task_for_forge's read and this write we hold the lock,
        # so in practice this is defensive rather than load-bearing —
        # but it also protects against future non-locked helpers.
        for t in state.get("queue", []):
            if t["id"] == task_id:
                if t.get("status") != "pending":
                    _output({"task": None,
                             "reason": f"race: {task_id} is now {t['status']!r}"})
                    _err(f"claim-task {forge_id}: lost race on {task_id}")
                    sys.exit(1)
                t["status"] = "in_progress"
                t["assigned_forge"] = forge_id
                break
        save_state(root, state)

    _emit_rig_event(root, "claim_task", actor=forge_id,
                    task_id=task_id, forge_id=forge_id)
    _output({"task_id": task_id, "task": task})
    _err(f"Claimed {task_id} for {forge_id}")


@cli.command("queue-clear")
@click.pass_context
def queue_clear(ctx):
    """Clear the next_tasks queue."""
    root = ctx.obj["root"]
    state = load_state(root)
    old_count = len(state.get("next_tasks", []))
    state["next_tasks"] = []
    save_state(root, state)

    _output({"cleared": old_count})
    _err(f"Cleared {old_count} tasks from queue")


@cli.command("list-tasks")
@click.option("--status", "status_filter", default="pending",
              type=click.Choice(["pending", "complete", "in_progress", "deferred", "all"]),
              help="Filter by status (default: pending)")
@click.option("--stage", "stage_filter", default=None,
              type=click.Choice(VALID_STAGES),
              help="Filter by stage")
@click.option("--initiative", "initiative_filter", default=None,
              help="Filter by initiative ID")
@click.option("--limit", "limit", type=int, default=20,
              help="Max tasks to return (default: 20)")
@click.pass_context
def list_tasks(ctx, status_filter, stage_filter, initiative_filter, limit):
    """List tasks from the queue with optional filters."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])
    ini_map = {i["id"]: i for i in state.get("initiatives", [])}

    # Filter
    tasks = queue
    if status_filter != "all":
        tasks = [t for t in tasks if t.get("status") == status_filter]
    if stage_filter:
        tasks = [t for t in tasks if t.get("stage") == stage_filter]
    if initiative_filter:
        tasks = [t for t in tasks if t.get("initiative_id") == initiative_filter]

    # Canonical scheduler order (t-383): promoted < un-pinned < deprioritized.
    tasks.sort(key=scheduler_key)
    total_matching = len(tasks)

    # Apply limit
    tasks = tasks[:limit]

    # Build output with initiative titles resolved
    result = []
    for t in tasks:
        entry = {
            "id": t["id"],
            "stage": t.get("stage", ""),
            "priority": t.get("priority", 2),
            "status": t.get("status", "pending"),
            "desc": t.get("desc", "")[:120],
            "blocked_by": t.get("blocked_by", []),
        }
        ini_id = t.get("initiative_id")
        if ini_id:
            entry["initiative_id"] = ini_id
            ini = ini_map.get(ini_id)
            entry["initiative_title"] = ini["title"] if ini else "unknown"
        result.append(entry)

    _output({"tasks": result, "count": len(result), "total_matching": total_matching})
    _err(f"Listed {len(result)} tasks (status={status_filter})")


@cli.command("task-tree")
@click.option("--initiative", "initiative_filter", default=None,
              help="Only show tasks in this initiative (ini-XXX).")
@click.option("--json", "emit_json", is_flag=True, default=False,
              help="Emit machine-readable JSON instead of the ASCII tree.")
@click.option("--stuck", "stuck_only", is_flag=True, default=False,
              help="Show only tasks blocked on still-open deps "
                   "whose worklog is idle ≥24h (or never touched).")
@click.option("--stuck-hours", "stuck_hours", type=float, default=24.0,
              help="Threshold for --stuck (hours; default 24).")
@click.pass_context
def task_tree_cmd(ctx, initiative_filter, emit_json, stuck_only, stuck_hours):
    """t-431: Render the task DAG.

    Groups open tasks (status in open/pending/in_progress/submitted) by
    initiative (rank order) and draws blocked_by edges as an ASCII tree.
    Dispatchable tasks (deps resolved) are flagged ✓; tasks in a
    dependency cycle are flagged ⚠; tasks idle ≥24h on live deps get 💤.
    """
    from .task_tree import build_forest, forest_to_json, render_ascii

    root = ctx.obj["root"]
    state = load_state(root)
    worklog = main_repo_root(root) / "worklog.tsv"

    forest = build_forest(
        state,
        initiative_filter=initiative_filter,
        stuck_only=stuck_only,
        worklog_path=worklog,
        stuck_threshold_hours=stuck_hours,
    )

    if emit_json:
        _output({"forest": forest_to_json(forest),
                 "initiatives": len(forest),
                 "roots": sum(len(r) for _, r in forest)})
        return

    text = render_ascii(forest)
    # Print without quoting so the ASCII tree is readable. Route through
    # click so terminals that want colour/width heuristics can hook in.
    click.echo(text, nl=False)


@cli.command("allocate")
@click.pass_context
def allocate(ctx):
    """Run the wavefront allocator and recommend a stage."""
    from .allocator import score_stages, pick_stage

    root = ctx.obj["root"]
    state = load_state(root)

    scores, targets, new_integrals = score_stages(
        state["stages"],
        state["allocator"]["integral"],
        state.get("human_priorities", []),
        state.get("queue", []),
        state.get("initiatives", []),
    )

    heat = state["budget"]["used"] + 1
    recommended = pick_stage(scores, heat)
    exploration = heat % 5 == 0

    # Update targets and integrals in state
    for stage in VALID_STAGES:
        state["stages"][stage]["target"] = targets[stage]
    state["allocator"]["integral"] = new_integrals
    save_state(root, state)

    _output({
        "recommended_stage": recommended,
        "exploration": exploration,
        "scores": scores,
        "targets": targets,
    })
    _err(f"Allocator recommends: {recommended}" + (" (exploration)" if exploration else ""))


@cli.command("pick-task")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.pass_context
def pick_task(ctx, stage):
    """Find highest-priority ready task for a stage."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])

    # Build initiative status lookup
    ini_map = {i["id"]: i for i in state.get("initiatives", [])}

    # Find ready tasks
    complete_ids = {t["id"] for t in queue if t["status"] == "complete"}
    ready = []
    for task in queue:
        if task["stage"] != stage or task["status"] != "pending":
            continue
        blocked = task.get("blocked_by", [])
        if not all(bid in complete_ids for bid in blocked):
            continue
        # Initiative gating: skip tasks whose initiative isn't approved/active
        ini_id = task.get("initiative_id")
        if ini_id and ini_id in ini_map:
            if ini_map[ini_id]["status"] not in ("approved", "active"):
                continue
        ready.append(task)

    ready.sort(key=scheduler_key)

    if ready:
        picked = ready[0]
        # Activate initiative on first task pick
        ini_id = picked.get("initiative_id")
        if ini_id and ini_id in ini_map and ini_map[ini_id]["status"] == "approved":
            ini_map[ini_id]["status"] = "active"
            save_state(root, state)

        _output({"task": picked, "alternatives": len(ready) - 1})
        _err(f"Task: {picked['id']} — {picked['desc']}")
    else:
        _output({"task": None, "message": f"No ready tasks for {stage} — generate one"})
        _err(f"No ready tasks for {stage}")


@cli.command("next-task")
@click.pass_context
def next_task(ctx):
    """Pop the next task from Marshal's next_tasks list.

    If next_tasks is populated (by Marshal), returns and removes the first entry.
    Falls back to allocate + pick-task if next_tasks is empty.
    """
    root = ctx.obj["root"]
    state = load_state(root)
    next_tasks = state.get("next_tasks", [])

    if next_tasks:
        entry = next_tasks.pop(0)
        task_id = entry.get("task_id")
        stage = entry.get("stage")
        rationale = entry.get("rationale", "")

        # Find the actual task in queue
        task = None
        for t in state.get("queue", []):
            if t["id"] == task_id:
                task = t
                break

        state["next_tasks"] = next_tasks
        save_state(root, state)

        _output({
            "source": "marshal",
            "task": task,
            "stage": stage,
            "rationale": rationale,
            "remaining_queued": len(next_tasks),
        })
        _err(f"Next task (from Marshal): {task_id} [{stage}] — {rationale}")
    else:
        _output({
            "source": "none",
            "task": None,
            "message": "next_tasks empty — use smithy allocate + smithy pick-task",
        })
        _err("No Marshal-queued tasks. Use allocate + pick-task.")



# NOTE: Old hook/check-hook/unhook/hook-marshal/check-marshal-hook/unhook-marshal
# commands removed in t-262. Use queue-push/queue-pop/queue instead.


@cli.command("nudge")
@click.argument("persona", type=str)
@click.argument("message")
@click.pass_context
def nudge(ctx, persona, message):
    """Send a message to a persona's pane in the FORGE_SESSION tmux session.

    If the persona is mid-heat (checkpoint exists), the nudge is queued
    to .smithy-nudge-queue/<persona>.jsonl instead of sent via tmux.
    Accepts any registered forge id (forge-quench/forge-temper/…) in
    addition to the fixed roster (marshal/anvil/assembly/chisel/forge).
    """
    root = ctx.obj["root"]
    state = load_state(root)
    _validate_persona(state, persona)
    result = _nudge_persona(persona, message, root=root)
    _output(result)
    if result["nudged"]:
        _err(f"Nudged {result['target']}: {message[:60]}")
    elif result.get("queued"):
        _err(f"Queued nudge for {persona} (mid-heat): {message[:60]}")
    elif result.get("error"):
        # t-489: wrong-session errors must be actionable (exit != 0) so
        # callers like Marshal don't treat them as ordinary queuing.
        _err(f"ERROR: {result['reason']}")
        sys.exit(1)
    else:
        _err(f"Warning: {result['reason']} ({result['target']})")


@cli.command("drain-nudges")
@click.argument("persona", type=str)
@click.pass_context
def drain_nudges(ctx, persona):
    """Read and clear queued nudges for a persona. Returns JSON array of messages."""
    root = ctx.obj["root"]
    state = load_state(root)
    _validate_persona(state, persona)
    queue_path = _nudge_queue_path(root, persona)

    if not queue_path.exists():
        _output({"persona": persona, "nudges": [], "count": 0})
        _err(f"No queued nudges for {persona}")
        return

    nudges = []
    for line in queue_path.read_text().strip().split("\n"):
        if line.strip():
            try:
                nudges.append(json.loads(line))
            except json.JSONDecodeError:
                nudges.append({"message": line, "parse_error": True})

    # Clear the queue
    queue_path.unlink()

    _output({"persona": persona, "nudges": nudges, "count": len(nudges)})
    _err(f"Drained {len(nudges)} nudge(s) for {persona}")


# --- t-479: Marshal escalation (never-block-on-stdin) -----------------------
#
# Marshal must never pause a loop iteration waiting for a pane-stdin reply.
# When uncertainty exceeds policy (multiple plausible resolutions, a stuck
# task whose status change could be wrong, etc.), Marshal calls
# `smithy marshal-escalate` to persist a structured question, nudge Anvil,
# and return immediately. Marshal then applies the documented safe-default
# (typically: skip the ambiguous task, leave its status untouched, move on)
# and continues the main loop.
#
# Anvil resolves via `smithy marshal-escalate-resolve <id> --resolution "…"`
# which flips the entry to resolved, records the resolution, and nudges
# Marshal so the next loop iteration can act on it.
#
# Storage: `marshal-questions.jsonl` at repo root, append-only for creates,
# rewritten on resolve (one line per entry, resolved entries retained as
# audit trail).


def _marshal_questions_path(root):
    return root / "marshal-questions.jsonl"


def _read_marshal_questions(root):
    path = _marshal_questions_path(root)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            # Preserve unparseable lines as raw strings; list cmd flags them.
            entries.append({"_parse_error": True, "raw": line})
    return entries


def _write_marshal_questions(root, entries):
    path = _marshal_questions_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    tmp.replace(path)


@cli.command("marshal-escalate")
@click.option("--tasks", "tasks_csv", default="",
              help="Comma-separated task ids involved (e.g. t-450,t-463).")
@click.option("--options", "options_csv", default="",
              help="Comma-separated options considered.")
@click.option("--reason", required=True,
              help="Why Marshal can't decide — one line of decision context.")
@click.option("--safe-default", "safe_default", required=True,
              help="The safe-default Marshal is applying right now "
                   "(e.g. 'skip task, leave status untouched, dispatch next').")
@click.option("--summary", default=None,
              help="One-line summary for the Anvil nudge. Defaults to reason.")
@click.option("--no-nudge", is_flag=True, default=False,
              help="Skip the Anvil nudge (useful in tests).")
@click.pass_context
def marshal_escalate(ctx, tasks_csv, options_csv, reason, safe_default,
                     summary, no_nudge):
    """Persist a Marshal uncertainty question and nudge Anvil.

    Writes a structured entry to marshal-questions.jsonl and (by default)
    fires a one-line nudge to Anvil's pane. Returns the entry id so the
    caller can reference it. Never blocks — Marshal applies the safe-default
    and continues its loop.
    """
    from datetime import datetime, timezone
    root = ctx.obj["root"]
    tasks = [t.strip() for t in tasks_csv.split(",") if t.strip()]
    options = [o.strip() for o in options_csv.split(",") if o.strip()]
    # Microsecond resolution — two escalations in the same second must
    # still get distinct ids (test_escalate_appends_multiple covers this).
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    entry_id = f"mq-{ts}"
    entry = {
        "id": entry_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "options": options,
        "reason": reason,
        "safe_default": safe_default,
        "status": "open",
        "resolution": None,
        "resolved_at": None,
    }

    # Append the raw line (no rewrite needed on create).
    path = _marshal_questions_path(root)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    nudge_summary = (summary or reason)[:160]
    nudge_result = None
    if not no_nudge:
        msg = f"MARSHAL_ESCALATE {entry_id}: {nudge_summary}"
        nudge_result = _nudge_persona("anvil", msg, root=root)

    _output({
        "entry": entry,
        "path": str(path),
        "nudge": nudge_result,
    })
    _err(f"Escalated {entry_id}: {nudge_summary[:80]}")


@cli.command("marshal-escalate-resolve")
@click.argument("entry_id")
@click.option("--resolution", required=True,
              help="One-line resolution Anvil chose (or a longer block).")
@click.option("--no-nudge", is_flag=True, default=False,
              help="Skip the Marshal nudge.")
@click.pass_context
def marshal_escalate_resolve(ctx, entry_id, resolution, no_nudge):
    """Mark a Marshal escalation entry resolved and nudge Marshal.

    Anvil writes the resolution here; Marshal picks it up on its next wake
    via `smithy marshal-escalate-list --open` or via the nudge message.
    """
    from datetime import datetime, timezone
    root = ctx.obj["root"]
    entries = _read_marshal_questions(root)
    found = False
    for entry in entries:
        if entry.get("id") == entry_id:
            if entry.get("status") == "resolved":
                _output({"error": "already resolved", "entry": entry})
                _err(f"{entry_id} already resolved")
                return
            entry["status"] = "resolved"
            entry["resolution"] = resolution
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        _output({"error": "not found", "id": entry_id})
        _err(f"No entry {entry_id}")
        ctx.exit(1)
    _write_marshal_questions(root, entries)

    nudge_result = None
    if not no_nudge:
        msg = f"MARSHAL_ESCALATE_RESOLVED {entry_id}: {resolution[:160]}"
        nudge_result = _nudge_persona("marshal", msg, root=root)

    _output({"entry": entry, "nudge": nudge_result})
    _err(f"Resolved {entry_id}")


@cli.command("marshal-escalate-list")
@click.option("--open/--all", "open_only", default=True,
              help="--open (default) shows only unresolved; --all shows every entry.")
@click.pass_context
def marshal_escalate_list(ctx, open_only):
    """List Marshal escalation entries (default: open only)."""
    root = ctx.obj["root"]
    entries = _read_marshal_questions(root)
    if open_only:
        entries = [e for e in entries if e.get("status") == "open"]
    _output({"count": len(entries), "entries": entries})
    _err(f"{len(entries)} {'open' if open_only else 'total'} escalation(s)")


# --- t-484 (ini-023 T5): Comms snapshot ------------------------------------
#
# Comms is an LLM-driven persona (see personas/comms/CLAUDE.md). At each
# wake it composes a TL;DR + Metrics section and appends to the day's
# report file. The metrics numbers must be deterministic — the LLM can
# compose prose reliably but mis-count queue lengths. This CLI produces
# the exact fields Comms needs in a single JSON read, so its wake loop
# is: `/clear` → read persona files → `smithy comms-snapshot` → compose
# TL;DR (LLM) → append section (LLM).
#
# MVP scope (T5): the fields needed for the TL;DR + Metrics table in
# §6 of plans/comms-persona-design.md. Initiatives / Bottlenecks /
# What's-next / Anomalies land in T6; push triggers in T7.


def _recent_worklog_outcomes(root, tail=30, window_minutes=30):
    """Parse the tail of worklog.tsv for 'now' metrics.

    Returns (counts, merged_recent) where:
      counts = {"green": int, "yellow": int, "red": int, "submitted": int,
                "rejected": int, "merged": int}
      merged_recent = int — tasks whose worklog row within the window
                            had outcome=merged (includes Assembly merges
                            Forge logged via end-heat --outcome merged).
    """
    from datetime import datetime, timedelta, timezone
    wl = root / "worklog.tsv"
    if not wl.exists():
        return ({"green": 0, "yellow": 0, "red": 0, "submitted": 0,
                 "rejected": 0, "merged": 0}, 0)
    try:
        lines = wl.read_text().splitlines()
    except OSError:
        return ({"green": 0, "yellow": 0, "red": 0, "submitted": 0,
                 "rejected": 0, "merged": 0}, 0)
    rows = lines[-tail:] if len(lines) > tail else lines[1:]  # strip header
    counts = {"green": 0, "yellow": 0, "red": 0,
              "submitted": 0, "rejected": 0, "merged": 0}
    merged_recent = 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    for line in rows:
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        ts_raw, _heat, _stage, _tid, outcome, _value = parts[:6]
        signal = parts[6] if len(parts) > 6 else ""
        # Signal counts — honour whichever emoji was logged.
        if "🟢" in signal:
            counts["green"] += 1
        elif "🟡" in signal:
            counts["yellow"] += 1
        elif "🔴" in signal:
            counts["red"] += 1
        if outcome == "submitted":
            counts["submitted"] += 1
        elif outcome == "rejected":
            counts["rejected"] += 1
        elif outcome == "merged" or outcome == "complete":
            counts["merged"] += 1
        # Recency window for merged.
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff and outcome in ("merged", "complete"):
                merged_recent += 1
        except (ValueError, AttributeError):
            pass
    return counts, merged_recent


def _initiatives_moved(state, root, window_minutes):
    """t-485 (ini-023 T6): per-initiative movement snapshot.

    For each active/approved initiative, emit:
      id, title, status, rank, heats_used, budget_cap,
      last_merged_tasks (task_ids landed in the window),
      in_flight_count (pending+in_progress+submitted in this initiative),
      momentum: "green" (>=1 merged in window) / "yellow" (submitted but
        nothing merged) / "red" (rejections in window and no merges) /
        "gray" (no activity).

    The LLM composes the narrative diff against the last comms report
    section; this function only surfaces the current-state numbers.
    """
    from datetime import datetime, timedelta, timezone
    wl = root / "worklog.tsv"
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    # Build {task_id: [outcome, outcome, ...]} for the window from worklog.
    task_outcomes_in_window = {}
    if wl.exists():
        for line in wl.read_text().splitlines()[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            ts_raw, _heat, _stage, task_id, outcome = parts[:5]
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts < cutoff:
                continue
            task_outcomes_in_window.setdefault(task_id, []).append(outcome)

    queue = state.get("queue") or []
    tasks_by_ini = {}
    for t in queue:
        ini = t.get("initiative_id")
        if ini:
            tasks_by_ini.setdefault(ini, []).append(t)

    initiatives = [
        i for i in (state.get("initiatives") or [])
        if i.get("status") in ("approved", "active")
    ]
    out = []
    for ini in initiatives:
        ini_id = ini.get("id")
        ini_tasks = tasks_by_ini.get(ini_id, [])
        in_flight = sum(1 for t in ini_tasks
                        if t.get("status") in ("pending", "in_progress",
                                                "submitted"))
        merged_here, rejected_here, submitted_here = [], [], []
        for t in ini_tasks:
            tid = t.get("id")
            outs = task_outcomes_in_window.get(tid, [])
            if any(o == "merged" for o in outs):
                merged_here.append(tid)
            elif any(o == "rejected" for o in outs):
                rejected_here.append(tid)
            elif any(o == "submitted" for o in outs):
                submitted_here.append(tid)
        if merged_here:
            momentum = "green"
        elif submitted_here and not rejected_here:
            momentum = "yellow"
        elif rejected_here:
            momentum = "red"
        else:
            momentum = "gray"
        out.append({
            "id": ini_id,
            "title": ini.get("title", ""),
            "status": ini.get("status"),
            "rank": ini.get("rank"),
            "heats_used": ini.get("heats_used", 0),
            "budget_cap": ini.get("budget_cap"),
            "in_flight": in_flight,
            "last_merged_tasks": merged_here,
            "last_rejected_tasks": rejected_here,
            "last_submitted_tasks": submitted_here,
            "momentum": momentum,
        })
    return out


def _detect_bottlenecks(state, root, window_minutes, active_forges=None):
    """t-485 (ini-023 T6): surface rig health warnings.

    Detectors (return list of {type, headline, explanation, cost_heats,
    suggested_action}):
      (a) ≥3 rejections of the same task_id within `window_minutes` in
          the worklog — retry-loop pattern.
      (b) task in_progress with a checkpoint file whose mtime is
          >30min old — likely hung forge / zombie heat.
      (c) assembly queue depth > n_forges — Assembly is saturated and
          Forges will back-pressure on submits.
      (d) status=submitted task with no merge/reject row in the last 5
          worklog entries overall AND no jsonl row — zombie submit.
    Empty list when the rig is healthy.
    """
    from datetime import datetime, timedelta, timezone
    out = []
    window_cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    wl = root / "worklog.tsv"

    # Parse worklog once.
    worklog_rows = []
    if wl.exists():
        for line in wl.read_text().splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            ts_raw, heat, stage, tid, outcome = parts[:5]
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            worklog_rows.append({"ts": ts, "task_id": tid, "outcome": outcome})

    # (a) retry loop.
    rejection_counts = {}
    for row in worklog_rows:
        if row["ts"] >= window_cutoff and row["outcome"] == "rejected":
            rejection_counts[row["task_id"]] = rejection_counts.get(
                row["task_id"], 0) + 1
    for tid, n in rejection_counts.items():
        if n >= 3:
            out.append({
                "type": "retry_loop",
                "headline": f"{tid} rejected {n}× in last {window_minutes}min",
                "explanation": (
                    f"Assembly has rejected {tid} {n} times in the recent "
                    "window. The pattern usually means the rebase surfaces "
                    "a test delta the branch can't close on its own — a "
                    "stale editable install, a fixture drift, or a real "
                    "code conflict the Forge keeps re-applying."
                ),
                "cost_heats": n,
                "suggested_action": (
                    "Pull the most recent rejection detail from "
                    "assembly-log.jsonl, hand-review the diff, and either "
                    "repin to a different Forge or split into smaller "
                    "commits."
                ),
            })

    # (b) stuck in-flight: task in_progress + checkpoint mtime > 30min.
    stuck = []
    parallel = state.get("parallel") or {}
    for t in state.get("queue", []):
        if t.get("status") != "in_progress":
            continue
        fid = t.get("assigned_forge")
        if not fid:
            continue
        # t-542: was `list(forge_ids)[0]` — set iteration order made the
        # "primary" nondeterministic, mis-attributing checkpoints. Use
        # the canonical resolver (roster order + main-root anchoring).
        cp_path = forge_checkpoint_path(root, fid)
        if not cp_path.exists():
            continue
        try:
            mtime = datetime.fromtimestamp(cp_path.stat().st_mtime,
                                            tz=timezone.utc)
        except OSError:
            continue
        if mtime < stuck_cutoff:
            minutes_stuck = int(
                (datetime.now(timezone.utc) - mtime).total_seconds() / 60)
            stuck.append((t.get("id"), fid, minutes_stuck))
    for tid, fid, m in stuck:
        out.append({
            "type": "stuck_in_progress",
            "headline": f"{tid} on {fid} has been in_progress for {m}min",
            "explanation": (
                f"{fid}'s checkpoint file hasn't been touched in {m}min, "
                "longer than any normal heat. Either the pane is wedged "
                "waiting on stdin or the Forge crashed mid-heat."
            ),
            "cost_heats": 1,
            "suggested_action": (
                "Inspect the pane (scripts/forge-status.sh), then reap "
                "the checkpoint via `smithy patrol --fix` to return the "
                "task to pending."
            ),
        })

    # (c) assembly saturation.
    assy_queue = main_repo_root(root) / ".assembly-queue.jsonl"
    depth = 0
    if assy_queue.exists():
        try:
            depth = sum(1 for line in assy_queue.read_text().splitlines()
                        if line.strip())
        except OSError:
            pass
    n_forges = active_forges if active_forges is not None else len(
        parallel.get("forges") or [])
    if depth > n_forges and n_forges > 0:
        out.append({
            "type": "assembly_saturated",
            "headline": f"Assembly queue depth {depth} exceeds {n_forges} forges",
            "explanation": (
                f"The .assembly-queue.jsonl is {depth} items deep but "
                f"only {n_forges} Forges are running. Submits will "
                "backpressure and Forges may idle until Assembly drains."
            ),
            "cost_heats": depth - n_forges,
            "suggested_action": (
                "Check Assembly's pane for a hung tick; if idle, "
                "`smithy assembly-tick` manually or wait for the nudge."
            ),
        })

    # (d) zombie submit: status=submitted AND task_id missing from recent
    # worklog rows AND no matching jsonl entry.
    jsonl_tids = set()
    if assy_queue.exists():
        try:
            for line in assy_queue.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = entry.get("task_id")
                if tid:
                    jsonl_tids.add(tid)
        except OSError:
            pass
    recent_wl_tids = {row["task_id"] for row in worklog_rows[-5:]}
    for t in state.get("queue", []):
        if t.get("status") != "submitted":
            continue
        tid = t.get("id")
        if tid in jsonl_tids:
            continue  # Assembly will pick it up from the jsonl.
        if tid in recent_wl_tids:
            continue  # Recent submit row suggests it's still moving.
        out.append({
            "type": "zombie_submit",
            "headline": f"{tid} is submitted but missing from jsonl + recent worklog",
            "explanation": (
                f"{tid} has status=submitted in state.json but no row in "
                ".assembly-queue.jsonl and nothing in the last 5 worklog "
                "entries. Post-ini-024 T1 this self-heals on the next "
                "assembly-tick, but it's worth surfacing."
            ),
            "cost_heats": 1,
            "suggested_action": (
                "Run `smithy assembly-tick` — reconciliation will pick "
                "it up from state.queue + git branches."
            ),
        })

    return out


@cli.command("comms-snapshot")
@click.option("--window-minutes", type=int, default=30,
              help="Recency window for 'last N-min' counters (default 30).")
@click.pass_context
def comms_snapshot(ctx, window_minutes):
    """Emit a JSON snapshot of the fields Comms needs for a wake.

    t-484 (ini-023 T5). Comms's wake loop calls this to get
    deterministic metrics numbers; the LLM composes the TL;DR prose on
    top. No state is mutated — read-only, like Comms itself.
    """
    from datetime import datetime, timezone
    root = ctx.obj["root"]
    state = load_state(root)

    budget = state.get("budget") or {}
    used = budget.get("used", 0) or 0
    total = budget.get("total_heats", 0) or 0
    pct_used = (100.0 * used / total) if total else None

    parallel = state.get("parallel") or {}
    forges = parallel.get("forges") or []
    active = sum(1 for f in forges if f.get("status") == "busy")
    halted = bool(parallel.get("halt_flag"))

    # Assembly queue depth — count non-blank lines in .assembly-queue.jsonl.
    assy_queue = main_repo_root(root) / ".assembly-queue.jsonl"
    assy_depth = 0
    if assy_queue.exists():
        try:
            assy_depth = sum(
                1 for line in assy_queue.read_text().splitlines()
                if line.strip()
            )
        except OSError:
            pass

    queue = state.get("queue") or []
    queue_summary = {
        "pending": sum(1 for t in queue if t.get("status") == "pending"),
        "in_progress": sum(1 for t in queue if t.get("status") == "in_progress"),
        "submitted": sum(1 for t in queue if t.get("status") == "submitted"),
        "complete": sum(1 for t in queue if t.get("status") == "complete"),
    }

    counts, merged_recent = _recent_worklog_outcomes(
        root, tail=30, window_minutes=window_minutes
    )

    snapshot = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "heat": used,
        "budget": {
            "used": used,
            "total": total,
            "pct_used": round(pct_used, 1) if pct_used is not None else None,
            "remaining": total - used if total else None,
        },
        "forges": {
            "active": active,
            "total": len(forges),
            "ids": [f.get("id") for f in forges if f.get("id")],
        },
        "halt_flag": halted,
        "assembly_queue_depth": assy_depth,
        "queue_summary": queue_summary,
        "worklog_tail_30": counts,
        "tasks_merged_in_window": merged_recent,
        "window_minutes": window_minutes,
        # t-485 (ini-023 T6): narrative-section inputs.
        "initiatives_moved": _initiatives_moved(state, root, window_minutes),
        "bottlenecks": _detect_bottlenecks(
            state, root, window_minutes=60, active_forges=len(forges),
        ),
    }
    _output(snapshot)
    _err(
        f"Comms snapshot: heat {used}/{total or '?'} "
        f"forges {active}/{len(forges)} "
        f"assy_queue {assy_depth}"
    )


# t-486 (ini-023 T7): push triggers.
#
# Triggers evaluated per §7 of plans/comms-persona-design.md: halt toggle,
# patrol issue-count jump, repeated rejections, budget floor, assembly
# queue back-pressure, all-forges-idle-across-cycles. Thresholds live in
# `state.parallel.comms.thresholds` (falling back to COMMS_DEFAULT_THRESHOLDS
# when missing). Idempotency is rising-edge: a trigger that stayed true
# last wake is suppressed; it re-fires only after clearing then re-tripping.
# Prior-state is stored in `personas/comms/.fired.jsonl` (append-only,
# read from tail — one row per evaluation per trigger).

COMMS_DEFAULT_THRESHOLDS = {
    "patrol_jump_delta": 3,           # issue count jumped by >= N
    "repeat_rejection_count": 3,       # same task_id rejected >= N times in window
    "repeat_rejection_window_min": 30,
    "budget_low_pct": 10.0,            # remaining budget fraction (%)
    "queue_backpressure_factor": 2.0,  # depth > factor * n_forges
    "all_idle_consecutive_cycles": 2,  # all forges idle for >= N wakes
}


def _comms_thresholds(state):
    """Merge state.parallel.comms.thresholds over COMMS_DEFAULT_THRESHOLDS.
    Missing keys use the defaults; never raises on a malformed shape."""
    cfg = ((state.get("parallel") or {})
           .get("comms") or {}).get("thresholds") or {}
    out = dict(COMMS_DEFAULT_THRESHOLDS)
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            if k in out and isinstance(v, (int, float)):
                out[k] = v
    return out


def _comms_fired_path(root):
    return root / "personas" / "comms" / ".fired.jsonl"


def _comms_last_states(root):
    """Read `.fired.jsonl` tail and return {trigger: last_row_dict}.
    Malformed / missing → empty dict. Only the most recent row per
    trigger survives; older rows are historical and don't affect
    rising-edge detection."""
    fp = _comms_fired_path(root)
    if not fp.exists():
        return {}
    try:
        lines = fp.read_text().splitlines()
    except OSError:
        return {}
    last = {}
    for ln in lines:
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        tr = row.get("trigger")
        if tr:
            last[tr] = row
    return last


def _evaluate_comms_triggers(state, snapshot, last_states, thresholds, root):
    """Core trigger evaluation. Pure-ish: no subprocess / no filesystem
    writes. Returns a list of dicts per trigger:
      {
        "trigger": str,
        "condition": bool,              # tripped this evaluation?
        "fired": bool,                  # rising-edge (should osascript)
        "body": str,                    # one-line notification body
        "metric": <numeric context>     # for delta detection next cycle
      }
    """
    results = []

    # --- halt_toggle: halt_flag changed since last evaluation ----------
    halt_now = bool(snapshot.get("halt_flag"))
    prior = last_states.get("halt_toggle") or {}
    halt_prev = prior.get("metric") if isinstance(prior.get("metric"), bool) else None
    toggled = (halt_prev is not None and halt_now != halt_prev)
    # Suppress if we've already fired for this transition (same state as
    # the last recorded row AND the last row already fired).
    already_fired = bool(prior.get("fired"))
    fired_halt = toggled and not (halt_prev == halt_now and already_fired)
    results.append({
        "trigger": "halt_toggle",
        "condition": toggled,
        "fired": fired_halt,
        "body": f"Halt flag {'ON' if halt_now else 'OFF'}",
        "metric": halt_now,
    })

    # --- patrol_jump: issue count jumped by >= delta -------------------
    # Use the most recent patrol count available via state.
    patrol_count = _patrol_issue_count(root)
    prior = last_states.get("patrol_jump") or {}
    prev_count = prior.get("metric")
    delta_threshold = thresholds["patrol_jump_delta"]
    jumped = (isinstance(prev_count, int)
              and patrol_count - prev_count >= delta_threshold)
    # Rising-edge: fire only when the last recorded row wasn't already
    # a fire for the same (or larger) count.
    fired_patrol = jumped and not (prior.get("fired") and
                                   prior.get("metric") == patrol_count)
    results.append({
        "trigger": "patrol_jump",
        "condition": jumped,
        "fired": fired_patrol,
        "body": f"Patrol issues jumped {prev_count or 0} → {patrol_count}",
        "metric": patrol_count,
    })

    # --- repeat_rejections: same task_id >= N rejections in window -----
    window = thresholds["repeat_rejection_window_min"]
    min_count = thresholds["repeat_rejection_count"]
    worst = _repeat_reject_worst(root, window_minutes=window)
    tripped_reject = worst is not None and worst["count"] >= min_count
    prior = last_states.get("repeat_rejections") or {}
    # Rising edge: fire only if wasn't tripped last time, or the worst
    # task_id changed.
    prev_task = prior.get("metric") if isinstance(prior.get("metric"), str) else None
    fired_reject = tripped_reject and (
        not prior.get("fired") or prev_task != (worst["task_id"] if worst else None)
    )
    results.append({
        "trigger": "repeat_rejections",
        "condition": tripped_reject,
        "fired": fired_reject,
        "body": (f"{worst['task_id']} rejected {worst['count']}× in {window}m"
                 if worst else "no repeated rejections"),
        "metric": worst["task_id"] if worst else None,
    })

    # --- budget_low: remaining fraction < threshold --------------------
    budget = snapshot.get("budget") or {}
    total = budget.get("total") or 0
    remaining = budget.get("remaining") or 0
    pct_remaining = (100.0 * remaining / total) if total else 100.0
    below = pct_remaining < thresholds["budget_low_pct"]
    prior = last_states.get("budget_low") or {}
    fired_budget = below and not prior.get("fired")
    results.append({
        "trigger": "budget_low",
        "condition": below,
        "fired": fired_budget,
        "body": f"Budget {pct_remaining:.1f}% remaining ({remaining}/{total})",
        "metric": round(pct_remaining, 1),
    })

    # --- queue_backpressure: assembly_queue_depth > factor * n_forges --
    depth = snapshot.get("assembly_queue_depth") or 0
    n_forges = (snapshot.get("forges") or {}).get("total") or 1
    ceiling = thresholds["queue_backpressure_factor"] * n_forges
    over = depth > ceiling
    prior = last_states.get("queue_backpressure") or {}
    fired_bp = over and not prior.get("fired")
    results.append({
        "trigger": "queue_backpressure",
        "condition": over,
        "fired": fired_bp,
        "body": f"Assembly-queue depth {depth} > 2×{n_forges} forges",
        "metric": depth,
    })

    # --- all_forges_idle: all forges idle N consecutive cycles ---------
    forges = (state.get("parallel") or {}).get("forges") or []
    all_idle_now = bool(forges) and all(
        f.get("status") == "idle" for f in forges
    )
    prior = last_states.get("all_forges_idle") or {}
    # Use `metric` as the running consecutive-cycle counter. Reset to 0
    # when not all-idle; otherwise += 1.
    prev_streak = prior.get("metric") if isinstance(prior.get("metric"), int) else 0
    streak = (prev_streak + 1) if all_idle_now else 0
    need = int(thresholds["all_idle_consecutive_cycles"])
    tripped = streak >= need
    fired_idle = tripped and not prior.get("fired")
    results.append({
        "trigger": "all_forges_idle",
        "condition": tripped,
        "fired": fired_idle,
        "body": f"All {len(forges)} forges idle for {streak} cycles",
        "metric": streak,
    })

    return results


def _patrol_issue_count(root):
    """Run `smithy patrol` and return its `issues` length. Cheap: no
    --fix, no state mutation. Returns 0 on any error — a trigger that
    can't read its source is silent, not loud."""
    import subprocess as _sp
    import sys as _sys
    try:
        r = _sp.run(
            [_sys.executable, "-m", "smithy.smithy.cli",
             "--dir", str(root), "patrol"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return 0
        data = json.loads(r.stdout)
        return len(data.get("issues") or [])
    except (json.JSONDecodeError, OSError, Exception):
        return 0


def _repeat_reject_worst(root, window_minutes):
    """Scan worklog for rejected rows in the window. Returns
    {task_id, count} for the task_id with the most rejections, or None
    if no task has any rejection in the window."""
    from datetime import datetime, timedelta, timezone
    wl = root / "worklog.tsv"
    if not wl.exists():
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    counts = {}
    try:
        lines = wl.read_text().splitlines()
    except OSError:
        return None
    for line in lines[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        ts_raw, _heat, _stage, task_id, outcome = parts[:5]
        if outcome != "rejected":
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        counts[task_id] = counts.get(task_id, 0) + 1
    if not counts:
        return None
    task_id, count = max(counts.items(), key=lambda kv: kv[1])
    return {"task_id": task_id, "count": count}


def _fire_macos_notification(title, body):
    """Best-effort `osascript` notification; silent failure on
    non-macOS (missing osascript, permissions denied). Returns True on
    success, False otherwise."""
    import subprocess as _sp
    import shutil as _sh
    if _sh.which("osascript") is None:
        return False
    # Guard against AppleScript string-escaping: drop quotes + newlines
    # from body + title before inlining. They're prose, not data.
    safe_body = body.replace('"', "'").replace("\n", " ")[:200]
    safe_title = title.replace('"', "'").replace("\n", " ")[:100]
    script = f'display notification "{safe_body}" with title "{safe_title}"'
    try:
        r = _sp.run(["osascript", "-e", script],
                    capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (_sp.TimeoutExpired, OSError):
        return False


@cli.command("comms-push-triggers")
@click.option("--window-minutes", type=int, default=30,
              help="Recency window for rejection scanning.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Evaluate triggers but don't fire or persist state.")
@click.pass_context
def comms_push_triggers_cmd(ctx, window_minutes, dry_run):
    """t-486 (ini-023 T7): evaluate Comms push triggers and fire macOS
    notifications on rising edges. Persistent prior-state in
    personas/comms/.fired.jsonl.

    Comms's wake loop calls this AFTER the report section has been
    written. Output is a single JSON with `{fired: [...], evaluated: [
    ...]}` so the operator (or tests) can see what tripped.
    """
    from datetime import datetime, timezone
    root = ctx.obj["root"]
    state = load_state(root)
    thresholds = _comms_thresholds(state)

    # Inline snapshot fields we need — avoid a second subprocess call.
    budget = state.get("budget") or {}
    used = budget.get("used", 0) or 0
    total = budget.get("total_heats", 0) or 0
    assy_queue = main_repo_root(root) / ".assembly-queue.jsonl"
    assy_depth = 0
    if assy_queue.exists():
        try:
            assy_depth = sum(
                1 for line in assy_queue.read_text().splitlines()
                if line.strip()
            )
        except OSError:
            pass
    parallel = state.get("parallel") or {}
    forges = parallel.get("forges") or []
    snapshot = {
        "halt_flag": bool(parallel.get("halt_flag")),
        "assembly_queue_depth": assy_depth,
        "forges": {"total": len(forges)},
        "budget": {"total": total, "used": used,
                   "remaining": total - used if total else None},
    }

    last = _comms_last_states(root)
    triggers = _evaluate_comms_triggers(state, snapshot, last, thresholds, root)

    # Find the most recent report file for the file:// link.
    report_link = ""
    reports_dir = root / "personas" / "comms" / "reports"
    if reports_dir.is_dir():
        reports = sorted(reports_dir.glob("*.md"), reverse=True)
        if reports:
            report_link = f"file://{reports[0].resolve()}"

    fired_now = []
    for t in triggers:
        if t["fired"] and not dry_run:
            body = t["body"]
            if report_link:
                body = f"{body} · {report_link}"
            ok = _fire_macos_notification("Smithy", body)
            t["osascript_ok"] = ok
            fired_now.append(t["trigger"])

    # Persist prior-state rows — one per trigger — so the next wake can
    # do rising-edge detection. Skip persistence on --dry-run.
    if not dry_run:
        fp = _comms_fired_path(root)
        fp.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with open(fp, "a") as f:
            for t in triggers:
                f.write(json.dumps({
                    "ts": ts,
                    "trigger": t["trigger"],
                    "condition": t["condition"],
                    "fired": t["fired"],
                    "metric": t["metric"],
                }) + "\n")

    _output({
        "fired": fired_now,
        "evaluated": [{"trigger": t["trigger"],
                        "condition": t["condition"],
                        "fired": t["fired"]}
                       for t in triggers],
        "thresholds": thresholds,
        "report_link": report_link,
    })
    _err(f"Comms push: fired {len(fired_now)}/{len(triggers)}"
         + (f" {fired_now}" if fired_now else ""))


@cli.command("sessions")
@click.pass_context
def sessions(ctx):
    """List persona windows in the tmux session."""
    import subprocess

    # Check tmux session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", _forge_session()],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"session": _forge_session(), "windows": [], "count": 0})
        _err("No tmux session found")
        return

    # List windows in tmux session
    result = subprocess.run(
        ["tmux", "list-windows", "-t", _forge_session(), "-F",
         "#{window_name}\t#{window_activity}\t#{window_active}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"session": _forge_session(), "windows": [], "count": 0})
        _err("Failed to list tmux windows")
        return

    from datetime import datetime
    windows = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, activity_ts, active = parts[0], parts[1], parts[2]
        try:
            last_activity = datetime.fromtimestamp(int(activity_ts)).isoformat()
        except (ValueError, OSError):
            last_activity = activity_ts
        windows.append({
            "name": name,
            "target": f"{_forge_session()}:{name}",
            "last_activity": last_activity,
            "active": active == "1",
        })

    _output({"session": _forge_session(), "windows": windows, "count": len(windows)})
    _err(f"{len(windows)} window(s) in tmux session")


@cli.command("start")
@click.argument("persona", type=click.Choice(VALID_PERSONAS))
@click.pass_context
def start_session(ctx, persona):
    """Start a persona as a named window in the tmux session."""
    import subprocess
    root = ctx.obj["root"]
    target = f"{_forge_session()}:{persona}"
    persona_dir = root / "personas" / persona

    if not persona_dir.exists():
        _output({"error": f"Persona directory not found: {persona_dir}"})
        sys.exit(1)

    # Ensure tmux session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", _forge_session()],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Create the session with this persona as the first window
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", _forge_session(), "-n", persona,
             "-c", str(persona_dir), "claude"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            _output({"error": f"Failed to create tmux session: {result.stderr.strip()}"})
            sys.exit(1)
        _output({"started": True, "target": target, "persona": persona, "dir": str(persona_dir), "created_session": True})
        _err(f"Created tmux session with {persona} window in {persona_dir}")
        return

    # Check if window already exists
    result = subprocess.run(
        ["tmux", "list-windows", "-t", _forge_session(), "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if persona in result.stdout.strip().split("\n"):
        _output({"started": False, "reason": "window already exists", "target": target})
        _err(f"Warning: window '{persona}' already exists in tmux session")
        return

    # Create new window in tmux session
    result = subprocess.run(
        ["tmux", "new-window", "-t", _forge_session(), "-n", persona,
         "-c", str(persona_dir), "claude"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"error": f"Failed to create window: {result.stderr.strip()}"})
        sys.exit(1)

    _output({"started": True, "target": target, "persona": persona, "dir": str(persona_dir)})
    _err(f"Started {persona} window in tmux session ({persona_dir})")


@cli.command("start-all")
@click.option("--safe", is_flag=True, default=False, help="Run claude without --dangerously-skip-permissions")
@click.pass_context
def start_all(ctx, safe):
    """Start the full tmux session with anvil, forge, and marshal windows."""
    import subprocess
    root = ctx.obj["root"]
    claude_cmd = "claude" if safe else "claude --dangerously-skip-permissions"
    personas = ["anvil", "forge", "marshal"]

    # Check if tmux session already exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", _forge_session()],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        # Session exists — check which windows are missing
        result = subprocess.run(
            ["tmux", "list-windows", "-t", _forge_session(), "-F", "#{window_name}"],
            capture_output=True, text=True,
        )
        existing = result.stdout.strip().split("\n") if result.stdout.strip() else []
        started = []
        skipped = []
        for p in personas:
            if p in existing:
                skipped.append(p)
                continue
            persona_dir = root / "personas" / p
            if not persona_dir.exists():
                skipped.append(p)
                continue
            subprocess.run(
                ["tmux", "new-window", "-t", _forge_session(), "-n", p,
                 "-c", str(persona_dir)],
                capture_output=True, text=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", f"{_forge_session()}:{p}", claude_cmd, "Enter"],
                capture_output=True, text=True,
            )
            started.append(p)
        _output({"session": _forge_session(), "started": started, "skipped": skipped, "claude_cmd": claude_cmd})
        _err(f"{_forge_session()}: started {started}, skipped {skipped}")
        return

    # Create fresh session with first persona, then add the rest
    first = personas[0]
    first_dir = root / "personas" / first
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", _forge_session(), "-n", first,
         "-c", str(first_dir)],
        capture_output=True, text=True,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{_forge_session()}:{first}", claude_cmd, "Enter"],
        capture_output=True, text=True,
    )
    started = [first]

    for p in personas[1:]:
        persona_dir = root / "personas" / p
        if not persona_dir.exists():
            continue
        subprocess.run(
            ["tmux", "new-window", "-t", _forge_session(), "-n", p,
             "-c", str(persona_dir)],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{_forge_session()}:{p}", claude_cmd, "Enter"],
            capture_output=True, text=True,
        )
        started.append(p)

    _output({"session": _forge_session(), "started": started, "claude_cmd": claude_cmd})
    _err(f"tmux session created with windows: {started}")


@cli.command("stop")
@click.argument("persona", type=click.Choice(VALID_PERSONAS))
@click.option("--kill", is_flag=True, default=False, help="Kill the tmux window instead of graceful /exit")
@click.pass_context
def stop_session(ctx, persona, kill):
    """Stop a persona's Claude session in the tmux session."""
    import subprocess, time
    target = f"{_forge_session()}:{persona}"

    # Check session and window exist
    result = subprocess.run(
        ["tmux", "list-windows", "-t", _forge_session(), "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"stopped": False, "reason": "tmux session not found"})
        _err("tmux session not found")
        return

    existing = result.stdout.strip().split("\n") if result.stdout.strip() else []
    if persona not in existing:
        _output({"stopped": False, "reason": f"window '{persona}' not found"})
        _err(f"Window '{persona}' not found in tmux session")
        return

    if kill:
        subprocess.run(["tmux", "kill-window", "-t", target], capture_output=True, text=True)
        _output({"stopped": True, "persona": persona, "method": "kill"})
        _err(f"Killed {target}")
    else:
        # Send /exit to Claude, wait briefly, then send exit to shell
        subprocess.run(["tmux", "send-keys", "-t", target, "/exit", "Enter"], capture_output=True, text=True)
        time.sleep(2)
        subprocess.run(["tmux", "send-keys", "-t", target, "exit", "Enter"], capture_output=True, text=True)
        _output({"stopped": True, "persona": persona, "method": "graceful"})
        _err(f"Sent /exit to {target}")


@cli.command("stop-all")
@click.option("--kill", is_flag=True, default=False, help="Kill the entire tmux session")
@click.pass_context
def stop_all(ctx, kill):
    """Stop all Claude sessions in the tmux session."""
    import subprocess, time
    personas = ["anvil", "forge", "marshal"]

    # Check session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", _forge_session()],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"stopped": False, "reason": "tmux session not found"})
        _err("tmux session not found")
        return

    if kill:
        subprocess.run(["tmux", "kill-session", "-t", _forge_session()], capture_output=True, text=True)
        _output({"stopped": True, "method": "kill-session", "personas": personas})
        _err("Killed tmux session")
        return

    # Graceful: send /exit to each window's Claude, then exit the shell
    result = subprocess.run(
        ["tmux", "list-windows", "-t", _forge_session(), "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    existing = result.stdout.strip().split("\n") if result.stdout.strip() else []
    stopped = []
    for p in personas:
        if p not in existing:
            continue
        subprocess.run(["tmux", "send-keys", "-t", f"{_forge_session()}:{p}", "/exit", "Enter"], capture_output=True, text=True)
        stopped.append(p)

    # Wait for Claude to exit, then close shells
    time.sleep(3)
    for p in stopped:
        subprocess.run(["tmux", "send-keys", "-t", f"{_forge_session()}:{p}", "exit", "Enter"], capture_output=True, text=True)

    _output({"stopped": True, "method": "graceful", "personas": stopped})
    _err(f"Stopped: {stopped}")


@cli.command("process-feedback")
@click.pass_context
def process_feedback(ctx):
    """Read new feedback entries after cursor."""
    root = ctx.obj["root"]
    state = load_state(root)
    cursor = state.get("feedback_cursor", 0)

    fb_path = root / "feedback.md"
    if not fb_path.exists():
        _output({"new_entries": [], "cursor": cursor})
        return

    lines = fb_path.read_text().splitlines()
    new_lines = lines[cursor:] if cursor < len(lines) else []

    # Parse entries
    entries = []
    for line in new_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("→") and not stripped.startswith("#"):
            entries.append(stripped)

    # Update cursor
    state["feedback_cursor"] = len(lines)
    save_state(root, state)

    _output({"new_entries": entries, "cursor": len(lines), "count": len(entries)})
    _err(f"{len(entries)} new feedback entries")


@cli.command("process-inbox")
@click.pass_context
def process_inbox(ctx):
    """Read new inbox entries after cursor."""
    root = ctx.obj["root"]
    state = load_state(root)
    cursor = state.get("inbox_cursor", 0)

    inbox_path = root / "inbox.md"
    if not inbox_path.exists():
        _output({"new_entries": [], "cursor": cursor})
        return

    lines = inbox_path.read_text().splitlines()
    new_lines = lines[cursor:] if cursor < len(lines) else []

    entries = []
    for line in new_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("→") and not stripped.startswith("#"):
            entries.append(stripped)

    state["inbox_cursor"] = len(lines)
    save_state(root, state)

    _output({"new_entries": entries, "cursor": len(lines), "count": len(entries)})
    _err(f"{len(entries)} new inbox entries")


@cli.command("sync-stages")
@click.option("--force-down", is_flag=True,
              help="t-454: allow budget.used to decrease (default: monotonic). "
                   "Without this, sync-stages only ever raises budget.used to "
                   "match the worklog count — guards against stale-worklog drift.")
@click.pass_context
def sync_stages(ctx, force_down):
    """Recalculate stage heats from worklog.tsv to fix drift."""
    root = ctx.obj["root"]
    state = load_state(root)
    # t-454: anchor the read to the MAIN repo's worklog.tsv. Reading
    # from `root / "worklog.tsv"` resolves to the worktree's
    # tracked-but-stale copy (the source of the 2026-04-18 budget
    # drift); writes are already routed through main_repo_root so this
    # closes the asymmetry.
    wl_path = worklog_path(root)

    if not wl_path.exists():
        _output({"error": "No worklog.tsv found"})
        sys.exit(1)

    # Count heats per stage from worklog
    stage_counts = {s: 0 for s in VALID_STAGES}
    lines = wl_path.read_text().strip().split("\n")
    for line in lines[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) >= 3:
            stage = parts[2]
            if stage in stage_counts:
                stage_counts[stage] += 1

    # Update state
    old_counts = {}
    for stage in VALID_STAGES:
        old_counts[stage] = state["stages"][stage].get("heats", 0)
        state["stages"][stage]["heats"] = stage_counts[stage]

    # t-454: monotonic guard. Budget.used should never decrease as a
    # side effect of recomputation — that's how we lost 79 heats on
    # 2026-04-18. The anchored read above prevents the original drift,
    # but keep this as defense-in-depth: if some future worklog read
    # path regresses, the worst case becomes "no change" rather than
    # "silently lose work." Operators wanting a true downward override
    # use `--force-down` (rare; explicit).
    total_heats = len(lines) - 1
    old_used = state["budget"]["used"]
    state["budget"]["used"] = (
        total_heats if force_down else max(old_used, total_heats)
    )
    new_used = state["budget"]["used"]

    save_state(root, state)

    _output({
        "old_used": old_used,
        "new_used": new_used,
        "stage_changes": {s: {"old": old_counts[s], "new": stage_counts[s]}
                          for s in VALID_STAGES if old_counts[s] != stage_counts[s]},
        "total_worklog_entries": total_heats,
    })
    _err(f"Synced stages from {total_heats} worklog entries")


@cli.command("patrol")
@click.option("--fix", is_flag=True, help="Auto-fix simple discrepancies")
@click.pass_context
def patrol(ctx, fix):
    """Discover-don't-track validation. Scans git + worklog + state for discrepancies."""
    root = ctx.obj["root"]
    state = load_state(root)
    issues = []
    fixes = []

    # 1. Check worklog heat count matches budget.used.
    # t-454: anchor the read to MAIN's worklog and only auto-fix UPWARD.
    # Pre-fix this check would set budget.used = worklog_heats from a
    # worktree's stale snapshot, silently losing recently-recorded heats
    # (892 → 824 on 2026-04-18). Downward correction is now an issue
    # surfaced for the operator (no auto-fix); upward correction stays
    # as before.
    wl_path = worklog_path(root)
    if wl_path.exists():
        lines = wl_path.read_text().strip().split("\n")
        worklog_heats = len(lines) - 1  # minus header
        budget_used = state["budget"]["used"]
        if worklog_heats != budget_used:
            issues.append(f"worklog has {worklog_heats} entries but budget.used is {budget_used}")
            if fix and worklog_heats > budget_used:
                state["budget"]["used"] = worklog_heats
                fixes.append(f"Set budget.used to {worklog_heats}")

    # 2. Check for tasks stuck in_progress (no active checkpoint).
    # t-437: parallel-Forges aware — each task's assigned_forge must
    # have ITS OWN per-Forge checkpoint on disk. The pre-t-437 check
    # only looked at the primary's `.forge-checkpoint.json`, so a task
    # pinned to forge-temper would appear "live" (because the primary
    # had a checkpoint for ITS task) while its own forge-temper
    # checkpoint was absent — and the orphan leaked across Marshal's
    # re-prioritize cycles (observed t-416 / t-433 on 2026-04-18).
    cp_path = root / ".forge-checkpoint.json"
    has_checkpoint = cp_path.exists()  # kept for check #4 below.
    from .state import primary_forge_id as _pfi
    primary = _pfi(root)
    for task in state.get("queue", []):
        if task["status"] != "in_progress":
            continue
        fid = task.get("assigned_forge") or primary
        cp = forge_checkpoint_path(root, fid)
        if not cp.exists():
            issues.append(
                f"Task {task['id']} is in_progress on {fid} but "
                f"{cp.name} is missing"
            )
            if fix:
                task["status"] = "pending"
                fixes.append(f"Reset {task['id']} to pending (orphan reap)")

    # 3. Check stage heats sum approximately matches budget.used
    stage_sum = sum(s.get("heats", 0) for s in state["stages"].values())
    budget_used = state["budget"]["used"]
    if abs(stage_sum - budget_used) > 10:  # Allow some tolerance
        issues.append(f"Stage heats sum ({stage_sum}) differs from budget.used ({budget_used}) by {abs(stage_sum - budget_used)}")

    # 4. Check for orphan checkpoint (checkpoint but budget exhausted)
    if has_checkpoint and state["budget"]["used"] >= state["budget"]["total_heats"]:
        issues.append("Checkpoint exists but budget is exhausted")
        if fix:
            cp_path.unlink()
            fixes.append("Deleted orphan checkpoint")

    # 5. Check feedback/inbox cursors don't exceed file length
    for cursor_name, file_name in [("feedback_cursor", "feedback.md"), ("inbox_cursor", "inbox.md")]:
        cursor = state.get(cursor_name, 0)
        fpath = root / file_name
        if fpath.exists():
            line_count = len(fpath.read_text().splitlines())
            if cursor > line_count:
                issues.append(f"{cursor_name} ({cursor}) exceeds {file_name} ({line_count} lines)")
                if fix:
                    state[cursor_name] = line_count
                    fixes.append(f"Set {cursor_name} to {line_count}")

    # 6. t-401 I6: per-Forge witness. For every registered Forge in
    # parallel.forges[], check heartbeat recency and checkpoint coherence.
    # Tier-1 witness: heartbeat older than STALE_S while status="busy", OR
    # checkpoint exists but forge is marked idle (orphan), OR forge is busy
    # but checkpoint missing (lost). Healthy Forges are unaffected — each
    # Forge is evaluated independently so one zombie doesn't mask others.
    STALE_S = 900  # 15 min; matches t-386 witness threshold.
    from datetime import datetime, timezone
    parallel = state.get("parallel") or {}
    forges = parallel.get("forges") or []
    stuck_forges = []
    for forge in forges:
        fid = forge.get("id")
        if not fid:
            continue
        fstatus = forge.get("status")
        cp_exists = forge_checkpoint_path(root, fid).exists()
        hb = forge.get("last_heartbeat")
        age_s = None
        if hb:
            try:
                age_s = (datetime.now(timezone.utc)
                         - datetime.fromisoformat(hb)).total_seconds()
            except Exception:
                age_s = None
        if fstatus == "busy" and age_s is not None and age_s > STALE_S:
            issues.append(
                f"{fid} heartbeat stale ({int(age_s)}s > {STALE_S}s) — zombie?"
            )
            stuck_forges.append(fid)
        if fstatus == "busy" and not cp_exists:
            issues.append(f"{fid} is busy but has no checkpoint — lost state")
            stuck_forges.append(fid)
        if fstatus == "idle" and cp_exists:
            # t-544: registry status is a CACHE, not truth (ini-024) —
            # it lags reality whenever a pane runs code that doesn't
            # stamp it. Deleting on "idle + checkpoint" alone destroyed
            # two live heats on 2026-06-12 (forge-temper h1221/h1230):
            # the heat lost its checkpoint mid-flight, end-heat refused,
            # and check #2 then reset the task — budget/worklog drift.
            # Verify the forge is ACTUALLY idle before reaping:
            #   live = checkpoint's task is in_progress AND assigned to
            #          this forge, OR checkpoint mtime is fresh (a heat
            #          plausibly in flight).
            # Live + --fix → repair the registry to busy (trust the
            # checkpoint, not the cache). Only stale-and-taskless
            # checkpoints are deleted.
            cp_file = forge_checkpoint_path(root, fid)
            cp_task = None
            try:
                cp_task = json.loads(cp_file.read_text()).get("task_id")
            except Exception:
                pass
            task_live = any(
                t.get("id") == cp_task
                and t.get("status") == "in_progress"
                and t.get("assigned_forge") == fid
                for t in state.get("queue", [])
            )
            FRESH_S = 1800  # 30 min — matches the stuck-heat cutoff.
            mtime_fresh = False
            try:
                cp_age = (datetime.now(timezone.utc)
                          - datetime.fromtimestamp(
                              cp_file.stat().st_mtime, tz=timezone.utc)
                          ).total_seconds()
                mtime_fresh = cp_age < FRESH_S
            except OSError:
                pass
            if task_live or mtime_fresh:
                issues.append(
                    f"{fid} registry says idle but its checkpoint looks "
                    f"LIVE ({'task ' + cp_task + ' in_progress' if task_live else 'fresh mtime'}) "
                    "— registry lagging, not an orphan"
                )
                if fix:
                    forge["status"] = "busy"
                    if cp_task and cp_task != "generated":
                        forge["current_task"] = cp_task
                    fixes.append(
                        f"Repaired {fid} registry status idle→busy from "
                        "live checkpoint (no reap)")
            else:
                issues.append(f"{fid} is idle but has a checkpoint — orphan")
                if fix:
                    cp_file.unlink()
                    fixes.append(f"Deleted orphan checkpoint for {fid}")

    # 7. t-407 H2: Assembly-only-to-main invariant. Every Forge registered
    # in parallel.forges[] must have a `worktree` field pointing under
    # `.worktrees/`, and that path must exist. Marshal must also live in a
    # worktree (`.worktrees/marshal`). Anvil and Assembly are allowed on main
    # (Anvil is read-only by discipline; Assembly is the integrator).
    # Worktree paths resolve relative to the MAIN repo root, so the check is
    # correct whether patrol runs from main or from inside a worktree.
    import subprocess as _sp
    main_root = root
    try:
        _out = _sp.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if _out:
            from pathlib import Path as _P
            main_root = _P(_out).parent
    except Exception:
        pass
    for forge in forges:
        fid = forge.get("id") or "<unnamed>"
        wt = forge.get("worktree")
        if not wt:
            issues.append(f"{fid} has no worktree — Forges must not run on main")
            continue
        if not wt.startswith(".worktrees/"):
            issues.append(
                f"{fid} worktree {wt!r} is not under .worktrees/ — "
                f"Forges must not run on main"
            )
            continue
        if not (main_root / wt).exists():
            issues.append(f"{fid} worktree path {wt!r} does not exist")
    if not (main_root / ".worktrees" / "marshal").exists():
        issues.append(
            ".worktrees/marshal does not exist — Marshal must not run on main"
        )

    # 8. t-419: state.json divergence. Under approach A, worktree copies of
    # state.json are stale tracked snapshots — smithy only reads/writes the
    # main copy. A worktree file with `budget.used` *higher* than main is
    # evidence that something wrote to the worktree directly (a smithy
    # regression or manual edit), which is what caused the 2026-04-12 rig
    # deadlock. Report divergence so the operator can investigate or run
    # `scripts/state-sync.sh`; --fix does not auto-resolve (we don't trust
    # either copy blindly).
    main_state_path = main_root / "state.json"
    if main_state_path.exists():
        try:
            main_used = json.loads(main_state_path.read_text())\
                .get("budget", {}).get("used", 0)
        except Exception:
            main_used = None
        wt_base = main_root / ".worktrees"
        if wt_base.exists() and main_used is not None:
            for wt_dir in sorted(wt_base.iterdir()):
                wt_state = wt_dir / "state.json"
                if not wt_state.exists() or wt_state.resolve() == \
                        main_state_path.resolve():
                    continue
                try:
                    wt_used = json.loads(wt_state.read_text())\
                        .get("budget", {}).get("used", 0)
                except Exception:
                    continue
                if wt_used > main_used:
                    issues.append(
                        f"{wt_dir.name}/state.json budget.used={wt_used} > "
                        f"main={main_used} — worktree-local write detected. "
                        f"Run scripts/state-sync.sh after investigating."
                    )

    # 9. t-423: stale .assembly-queue.jsonl entries. Assembly is the only
    # thing that drains the queue; if its pane crashes or mis-handles a
    # nudge, entries accumulate silently and the rig *looks* healthy
    # while nothing reaches main. Flag any entry whose submitted_at is
    # more than ASSEMBLY_STALE_S old (default 5 min). No auto-fix — the
    # operator either restarts Assembly (which drains) or rejects the
    # task manually.
    ASSEMBLY_STALE_S = 300  # 5 min — loose enough that a slow test run
                            # on a real tick doesn't false-positive.
    q_path = assembly_queue_path(root)
    if q_path.exists():
        now_utc = datetime.now(timezone.utc)
        for raw in q_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            submitted_at = entry.get("submitted_at")
            if not submitted_at:
                continue
            try:
                sub_ts = datetime.fromisoformat(submitted_at)
            except Exception:
                continue
            age_s = (now_utc - sub_ts).total_seconds()
            if age_s > ASSEMBLY_STALE_S:
                mins = int(age_s // 60)
                issues.append(
                    f"STALE assembly-queue: {entry.get('task_id','?')} "
                    f"by {entry.get('forge_id','?')} submitted {mins}m ago, "
                    f"branch {entry.get('branch','?')}"
                    f"@{(entry.get('sha','') or '')[:8]}"
                )

    # 10. t-438: origin/main drift. Assembly's advisory push is
    # best-effort — if it fails silently over enough merges, local
    # main marches ahead of origin and the next disk failure loses
    # the whole session (observed 2026-04-18: 144 commits unpushed).
    # Warn at >=5 unpushed commits, red at >=20. No auto-fix — pushing
    # is a decision, not a repair (may conflict, may need auth, etc.).
    try:
        _rv = _sp.run(
            ["git", "rev-list", "--count", "origin/main..main"],
            cwd=root, capture_output=True, text=True, check=False,
        )
        if _rv.returncode == 0 and _rv.stdout.strip().isdigit():
            ahead = int(_rv.stdout.strip())
            if ahead >= 20:
                issues.append(
                    f"main is {ahead} commits ahead of origin/main — "
                    f"push is badly stuck; `git push origin main` now"
                )
            elif ahead >= 5:
                issues.append(
                    f"main is {ahead} commits ahead of origin/main — "
                    f"Assembly's advisory push may be failing"
                )
    except Exception:
        pass  # no remote configured, no network — silent skip.

    # t-458 Check #11: per-forge memory layout drift. After the migration
    # the root `personas/forge/memory/` must not contain the legacy shared
    # files — their reappearance means a regression routed a memory write
    # to the old path, re-opening the MEMORY.md merge-conflict class.
    mem_root = root / "personas" / "forge" / "memory"
    for legacy in ("MEMORY.md", "MEMORY_DAILY.md", "MEMORY_WEEKLY.md"):
        if (mem_root / legacy).exists():
            issues.append(
                f"legacy shared memory file at personas/forge/memory/{legacy} — "
                f"move into the per-forge subdir (quench/temper/anneal) or "
                f"check smithy memory-write routing (t-458 regression)"
            )

    # t-462 Check #12: stalled Forges via queue_push/queue_pop correlation.
    # The zombie check (#6) misses Forges that die between heats — status
    # is idle and the heartbeat isn't yet stale enough, so patrol sees
    # nothing while Marshal pushes tasks the Forge never consumes.
    # Derived from rig-events.jsonl: if a queue_push targeting forge-X
    # has no matching queue_pop within STALL_S seconds and forge-X is
    # currently idle, flag it. Forges idle-poll at ~30s so 4x grace (120s)
    # is ample; false-positive cost is one human glance.
    STALL_S = 120
    stalled_forges = _detect_stalled_forges(root, state, STALL_S)
    for item in stalled_forges:
        issues.append(
            f"{item['forge_id']} ignored queue push "
            f"(task {item['task_id']}) {int(item['age_s'])}s ago "
            f"(threshold {STALL_S}s) — possibly unreachable"
        )

    # t-491 (ini-019) Check #16: forge starvation — the Marshal-side
    # counterpart of check #12. Catches "queue has work, forges idle,
    # Marshal not dispatching" (next_tasks empty despite pending tasks).
    # Pure state.json snapshot; no event correlation required.
    starving_forges = _detect_starving_forges(state)
    for item in starving_forges:
        issues.append(
            f"{item['forge_id']} starving: {item['pending_count']} pending "
            f"task(s) available, next_tasks empty — Marshal not dispatching"
        )
    # --fix: nudge Marshal so it re-reads state and picks up the
    # starvation. We don't push a specific task (which task to pick is
    # Marshal's job) and we don't mutate next_tasks directly — that would
    # race with Marshal's own dispatch logic. The nudge is idempotent
    # and cheap; if Marshal is genuinely dead, check #12 / witness-check
    # will cover it on the Forge side.
    if fix and starving_forges:
        msg = (
            f"PATROL_STARVATION: {len(starving_forges)} forge(s) starving — "
            f"re-evaluate and dispatch"
        )
        nudge_result = _nudge_persona("marshal", msg, root=root)
        fixes.append(
            f"nudged marshal ({'sent' if nudge_result.get('nudged') else 'queued'})"
        )

    # 13. t-466: initiative rank invariants. Approved/active initiatives
    # must carry contiguous ranks 1..N; everything else must carry
    # rank=null. Surface violations only — operator runs
    # `smithy initiative renumber` to repair, since hand-edits often
    # carry intent we shouldn't auto-clobber.
    for issue in _validate_ranks(state):
        issues.append(f"initiative rank: {issue}")

    # 14. t-467: per-worktree venv health. After ini-020 phase 2 every
    # Forge + Marshal worktree must carry its own .venv/ (created by
    # scripts/forge-venv-setup.sh, run automatically by start-smithy.sh
    # before Claude boots). A missing .venv/ means the pane's smithy CLI
    # falls back to the global install — exactly the t-460 stale-binary
    # hazard ini-020 was built to retire. No auto-fix: re-creating the
    # venv from patrol would race with whatever shell that pane is
    # running. Operator runs `bash scripts/forge-venv-setup.sh` from the
    # worktree. _-prefixed reserved worktrees (e.g. _assembly-staging,
    # _merge-tXXX) are skipped — they're transient and not Claude-hosted.
    wt_base = main_root / ".worktrees"
    if wt_base.exists():
        for wt_dir in sorted(wt_base.iterdir()):
            if not wt_dir.is_dir() or wt_dir.name.startswith("_"):
                continue
            if not (wt_dir / ".venv").exists():
                issues.append(
                    f"{wt_dir.name}/.venv missing — run "
                    f"`bash scripts/forge-venv-setup.sh` from that worktree "
                    f"(t-467: pane will silently use the global install)"
                )

    # 15. t-489: dual-session detection. Warn if FORGE_SESSION's session
    # is live AND another tmux session named 'smithy*' or 'forge*' is
    # also live — that's the "stale 'smithy2' alongside live 'forge'"
    # condition where the internal nudge path could (pre-t-489) silently
    # pick the wrong session and fall through to .smithy-nudge-queue/.
    # tmux unavailable or erroring: silent skip (CI, headless dev).
    try:
        import subprocess as _sp
        _ls = _sp.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if _ls.returncode == 0:
            _active = _forge_session()
            _all = [s.strip() for s in _ls.stdout.splitlines() if s.strip()]
            _stale = [s for s in _all
                      if s != _active
                      and (s.startswith("smithy") or s.startswith("forge"))]
            if _active in _all and _stale:
                issues.append(
                    f"tmux dual-session: active FORGE_SESSION='{_active}' "
                    f"plus stale {_stale} — run "
                    f"`tmux kill-session -t <name>` to clear "
                    f"(internal nudges may target the wrong session)"
                )
    except Exception:
        pass

    # 16. t-507: Assembly staging venv health. When Assembly is enabled,
    # `.worktrees/_assembly-staging/.venv/` must exist so the staging
    # pytest imports `smithy` from the rebased task branch's source,
    # not bare python3's main-bound editable install (the t-460 /
    # t-502 hazard). `ensure_staging_venv` auto-bootstraps at test time;
    # this patrol check surfaces drift between ticks. No auto-fix —
    # bootstrap is Assembly's responsibility and running uv from
    # patrol would race with whatever shell is active in that pane.
    assembly_cfg = (state.get("parallel") or {}).get("assembly") or {}
    if assembly_cfg.get("enabled"):
        staging_venv = main_root / ".worktrees" / "_assembly-staging" / ".venv"
        if not staging_venv.exists():
            issues.append(
                "_assembly-staging/.venv missing — Assembly's staging "
                "pytest will fall back to system python3 and import "
                "smithy from MAIN (t-460); ensure_staging_venv "
                "bootstraps on next assembly-tick, or force with "
                "`uv venv .venv && uv pip install -e smithy` inside "
                ".worktrees/_assembly-staging/"
            )

    # 17. t-493: state-vs-jsonl drift (zombie-submitted detector).
    # A task marked `submitted` in state.json must have a matching row
    # in .assembly-queue.jsonl — otherwise Assembly can't see it, idles,
    # and the work sits forever while the rig looks healthy. Recurring
    # class (t-450 / t-463 / t-472 / t-480 / t-448). Root cause was the
    # read-then-overwrite race in _pop_queue (fixed same heat) but the
    # patrol check guards against any future path that drops a row.
    #
    # --fix rebuilds missing entries from (a) the queue task's
    # assigned_forge, (b) per-task branch tip via `git rev-parse`. If
    # the branch is missing, the entry is NOT rebuilt (that's the
    # operator's call — state flip back to pending, or assembly-reject).
    import subprocess as _sp2
    q_path = assembly_queue_path(root)
    jsonl_task_ids = set()
    if q_path.exists():
        for raw in q_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            tid = entry.get("task_id")
            if tid:
                jsonl_task_ids.add(tid)
    submitted_in_state = [t for t in state.get("queue", [])
                          if t.get("status") == "submitted"]
    from .state import primary_forge_id as _pfi2
    _primary = _pfi2(state)
    zombies = [t for t in submitted_in_state
               if t["id"] not in jsonl_task_ids]
    for zt in zombies:
        issues.append(
            f"state has {zt['id']} status=submitted but "
            f".assembly-queue.jsonl missing its entry — "
            f"zombie-submitted (Assembly will never see it)"
        )
        if fix:
            fid = zt.get("assigned_forge") or _primary
            br = f"{fid}/{zt['id']}"
            pr = _sp2.run(["git", "rev-parse", br],
                          cwd=str(main_root), capture_output=True, text=True)
            if pr.returncode != 0:
                continue  # branch gone — operator must decide
            entry = {
                "forge_id": fid,
                "task_id": zt["id"],
                "heat": state["budget"].get("used"),
                "branch": br,
                "sha": pr.stdout.strip(),
                "submitted_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"),
            }
            _append_queue(q_path, entry)
            fixes.append(
                f"Rebuilt assembly-queue entry for {zt['id']} "
                f"({br}@{entry['sha'][:8]})"
            )

    # Save fixes if any
    if fix and fixes:
        save_state(root, state)

    _output({
        "issues": issues,
        "fixes": fixes,
        "clean": len(issues) == 0,
        "checks_run": 17,
        "stuck_forges": sorted(set(stuck_forges)),
        "stalled_forges": stalled_forges,
        "starving_forges": starving_forges,
    })
    if issues:
        _err(f"Patrol found {len(issues)} issues" + (f", fixed {len(fixes)}" if fixes else ""))
    else:
        _err("Patrol: all clean ✓")


@cli.command("witness-check")
@click.option("--stale-threshold", type=int, default=900,
              help="Heartbeat staleness threshold in seconds (default 900).")
@click.pass_context
def witness_check_cmd(ctx, stale_threshold):
    """t-401 I6: Per-Forge witness report. Returns structured per-Forge
    health (heartbeat age, checkpoint presence, stuck state) so Anvil can
    surface a zombie Forge without eyeballing patrol output.

    Each Forge is evaluated independently — a single zombie does not bleed
    into healthy peers' status.
    """
    from datetime import datetime, timezone
    root = ctx.obj["root"]
    state = load_state(root)
    parallel = state.get("parallel") or {}
    now = datetime.now(timezone.utc)
    report = []
    for forge in (parallel.get("forges") or []):
        fid = forge.get("id")
        if not fid:
            continue
        hb = forge.get("last_heartbeat")
        age_s = None
        if hb:
            try:
                age_s = (now - datetime.fromisoformat(hb)).total_seconds()
            except Exception:
                age_s = None
        cp_exists = forge_checkpoint_path(root, fid).exists()
        fstatus = forge.get("status")
        stuck_reasons = []
        if fstatus == "busy" and age_s is not None and age_s > stale_threshold:
            stuck_reasons.append(f"heartbeat stale ({int(age_s)}s)")
        if fstatus == "busy" and not cp_exists:
            stuck_reasons.append("no checkpoint")
        if fstatus == "idle" and cp_exists:
            stuck_reasons.append("orphan checkpoint")
        report.append({
            "forge_id": fid, "status": fstatus,
            "last_heartbeat": hb, "heartbeat_age_s": age_s,
            "checkpoint_present": cp_exists, "current_task": forge.get("current_task"),
            "stuck": bool(stuck_reasons), "stuck_reasons": stuck_reasons,
        })
    _output({"forges": report,
             "any_stuck": any(f["stuck"] for f in report),
             "threshold_s": stale_threshold})


@cli.command("handoff")
@click.argument("notes")
@click.option("--next", "next_steps", default=None, help="What the next session should do first")
@click.pass_context
def handoff(ctx, notes, next_steps):
    """Save session context for the next session. Called at budget exhaustion or manual handoff."""
    from datetime import datetime
    root = ctx.obj["root"]
    state = load_state(root)

    # Read last few worklog entries for context — t-454: anchor to main.
    wl_path = worklog_path(root)
    recent_heats = []
    if wl_path.exists():
        lines = wl_path.read_text().strip().split("\n")
        for line in lines[-5:]:
            parts = line.split("\t")
            if len(parts) >= 8:
                recent_heats.append({"heat": parts[1], "stage": parts[2], "notes": parts[7]})

    handoff_data = {
        "timestamp": datetime.now().isoformat(),
        "budget": state["budget"],
        "overall_progress": state.get("overall_progress", 0),
        "pending_tasks": [t for t in state.get("queue", []) if t["status"] == "pending"],
        "recent_heats": recent_heats,
        "human_priorities": state.get("human_priorities", []),
        "context_notes": notes,
        "next_steps": next_steps,
    }

    path = root / ".forge-handoff.json"
    path.write_text(json.dumps(handoff_data, indent=2) + "\n")

    _output(handoff_data)
    _err(f"Handoff saved: {notes[:60]}")


@cli.command("resume")
@click.pass_context
def resume(ctx):
    """Resume from a previous session's handoff. Reads .forge-handoff.json."""
    root = ctx.obj["root"]
    path = root / ".forge-handoff.json"

    if not path.exists():
        _output({"has_handoff": False, "message": "No handoff file found — fresh start"})
        _err("No handoff — starting fresh")
        return

    handoff_data = json.loads(path.read_text())

    # Delete the handoff file (consumed)
    path.unlink()

    _output({
        "has_handoff": True,
        "context_notes": handoff_data.get("context_notes", ""),
        "next_steps": handoff_data.get("next_steps"),
        "pending_tasks": len(handoff_data.get("pending_tasks", [])),
        "recent_heats": handoff_data.get("recent_heats", []),
        "human_priorities": handoff_data.get("human_priorities", []),
        "budget": handoff_data.get("budget", {}),
    })
    _err(f"Resumed from handoff: {handoff_data.get('context_notes', '')[:60]}")


@cli.command("memory-write")
@click.argument("note")
@click.option("--heat", "heat_num", type=int, default=None, help="Heat number for context")
@click.option("--stage", default=None, help="Stage for context")
@click.pass_context
def memory_write(ctx, note, heat_num, stage):
    """Append a note to personas/forge/memory/<forge-suffix>/MEMORY_DAILY.md.

    t-458: each Forge writes to its own subdir (quench/temper/anneal)
    to eliminate MEMORY.md merge conflicts between parallel Forges. The
    subdir is the forge-id with the `forge-` prefix dropped, detected
    from the cwd's worktree at runtime.
    """
    from datetime import date
    root = ctx.obj["root"]
    forge_id = detect_forge_from_cwd(root) or primary_forge_id(root)
    subdir = forge_id.removeprefix("forge-") if forge_id else "quench"
    path = root / "personas" / "forge" / "memory" / subdir / "MEMORY_DAILY.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    header = f"## {today}"

    if path.exists():
        content = path.read_text()
    else:
        content = "# Daily Memory\n"

    # Check if today's header exists
    if header not in content:
        content += f"\n{header}\n"

    # Build the entry
    prefix = ""
    if heat_num and stage:
        prefix = f"[h{heat_num} {stage}] "
    elif heat_num:
        prefix = f"[h{heat_num}] "

    entry = f"\n- {prefix}{note}\n"
    content += entry

    path.write_text(content)
    _output({"date": today, "note": note, "heat": heat_num})
    _err(f"Memory: {note[:60]}")


@cli.command("add-theme")
@click.argument("name")
@click.pass_context
def add_theme(ctx, name):
    """Add a new theme to the intent hierarchy."""
    root = ctx.obj["root"]
    state = load_state(root)
    themes = state.setdefault("themes", [])

    # Auto-generate ID
    max_num = 0
    for th in themes:
        try:
            num = int(th["id"].split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    new_id = f"th-{max_num + 1:03d}"

    # Rank = max + 1
    max_rank = max((th.get("rank", 0) for th in themes), default=0)

    theme = {"id": new_id, "name": name, "rank": max_rank + 1, "status": "active"}
    themes.append(theme)
    save_state(root, state)

    _output({"theme": theme})
    _err(f"Added theme {new_id}: {name}")


@cli.command("list-themes")
@click.pass_context
def list_themes(ctx):
    """List themes sorted by rank."""
    root = ctx.obj["root"]
    state = load_state(root)
    themes = sorted(state.get("themes", []), key=lambda t: t.get("rank", 0))
    _output({"themes": themes, "count": len(themes)})


@cli.command("pause-theme")
@click.argument("theme_id")
@click.pass_context
def pause_theme(ctx, theme_id):
    """Pause a theme."""
    root = ctx.obj["root"]
    state = load_state(root)
    for th in state.get("themes", []):
        if th["id"] == theme_id:
            th["status"] = "paused"
            save_state(root, state)
            _output({"theme": th})
            _err(f"Paused {theme_id}")
            return
    _output({"error": f"Theme {theme_id} not found"})
    sys.exit(1)


@cli.command("activate-theme")
@click.argument("theme_id")
@click.pass_context
def activate_theme(ctx, theme_id):
    """Activate a paused theme."""
    root = ctx.obj["root"]
    state = load_state(root)
    for th in state.get("themes", []):
        if th["id"] == theme_id:
            th["status"] = "active"
            save_state(root, state)
            _output({"theme": th})
            _err(f"Activated {theme_id}")
            return
    _output({"error": f"Theme {theme_id} not found"})
    sys.exit(1)


PARALLELISM_CHOICES = ("serial", "parallel")


@cli.command("propose")
@click.argument("theme_id")
@click.argument("title")
@click.argument("description")
@click.option("--budget-cap", type=int, default=None, help="Max heats for this initiative")
@click.option("--parallelism", type=click.Choice(PARALLELISM_CHOICES), default="parallel",
              help="t-440: serial → Marshal dispatches at most one task from this initiative at a time.")
@click.option("--affinity", multiple=True,
              help="t-440: pin tasks to specific Forge ids (repeatable). Empty = any Forge.")
@click.option("--touches", multiple=True,
              help="t-440: path-globs this initiative writes (repeatable), for cross-initiative contention checks.")
@click.pass_context
def propose(ctx, theme_id, title, description, budget_cap, parallelism, affinity, touches):
    """Propose a new initiative under a theme."""
    root = ctx.obj["root"]
    state = load_state(root)

    theme_ids = {th["id"] for th in state.get("themes", [])}
    if theme_id not in theme_ids:
        _output({"error": f"Theme {theme_id} not found"})
        sys.exit(1)

    initiatives = state.setdefault("initiatives", [])
    max_num = 0
    for ini in initiatives:
        try:
            num = int(ini["id"].split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    new_id = f"ini-{max_num + 1:03d}"

    initiative = {
        "id": new_id,
        "theme_id": theme_id,
        "title": title,
        "description": description,
        "status": "proposed",
        "budget_cap": budget_cap,
        "heats_used": 0,
        "parallelism": parallelism,
        "affinity": list(affinity),
        "touches": list(touches),
    }
    initiatives.append(initiative)
    save_state(root, state)

    _output({"initiative": initiative})
    _err(f"Proposed {new_id}: {title}")


@cli.command("edit-initiative")
@click.argument("initiative_id")
@click.option("--parallelism", type=click.Choice(PARALLELISM_CHOICES), default=None,
              help="t-440: update parallelism (serial|parallel).")
@click.option("--affinity", default=None,
              help="t-440: comma-separated Forge ids (empty string clears).")
@click.option("--touches", default=None,
              help="t-440: comma-separated path-globs (empty string clears).")
@click.pass_context
def edit_initiative(ctx, initiative_id, parallelism, affinity, touches):
    """Edit multi-forge poker fields on an existing initiative (t-440).

    Each flag is independent — omitted flags leave the field unchanged.
    For --affinity and --touches, pass a comma-separated list; an empty
    string clears the list.
    """
    root = ctx.obj["root"]
    state = load_state(root)

    ini = next((i for i in state.get("initiatives", []) if i["id"] == initiative_id), None)
    if ini is None:
        _output({"error": f"Initiative {initiative_id} not found"})
        sys.exit(1)

    if parallelism is not None:
        ini["parallelism"] = parallelism
    if affinity is not None:
        ini["affinity"] = [s.strip() for s in affinity.split(",") if s.strip()]
    if touches is not None:
        ini["touches"] = [s.strip() for s in touches.split(",") if s.strip()]

    save_state(root, state)
    _output({"initiative": ini})
    _err(f"Edited {initiative_id}")


@cli.command("approve")
@click.argument("initiative_id")
@click.pass_context
def approve_initiative(ctx, initiative_id):
    """Approve a proposed initiative."""
    root = ctx.obj["root"]
    state = load_state(root)
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            if ini["status"] != "proposed":
                _output({"error": f"Cannot approve: status is '{ini['status']}', expected 'proposed'"})
                sys.exit(1)
            ini["status"] = "approved"
            save_state(root, state)
            _output({"initiative": ini})
            _err(f"Approved {initiative_id}")
            return
    _output({"error": f"Initiative {initiative_id} not found"})
    sys.exit(1)


@cli.command("reject")
@click.argument("initiative_id")
@click.pass_context
def reject_initiative(ctx, initiative_id):
    """Reject an initiative."""
    root = ctx.obj["root"]
    state = load_state(root)
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["status"] = "rejected"
            save_state(root, state)
            _output({"initiative": ini})
            _err(f"Rejected {initiative_id}")
            return
    _output({"error": f"Initiative {initiative_id} not found"})
    sys.exit(1)


@cli.command("complete-initiative")
@click.argument("initiative_id")
@click.option("--retro", "retro_path", default=None,
              help="Path to the retro document (REQUIRED unless "
                   "--force-no-retro). Convention: plans/ini-<id>-retro.md. "
                   "File must exist at close time.")
@click.option("--successor", "successor_ini", default=None,
              help="Optional follow-on initiative id — must already exist "
                   "with status approved or active. Errors on self-ref or "
                   "ref to complete/rejected initiatives.")
@click.option("--force-no-retro", is_flag=True, default=False,
              help="Escape hatch — close without a retro document. Emits "
                   "a rig-event warning so the skip is visible in audit.")
@click.pass_context
def complete_initiative(ctx, initiative_id, retro_path, successor_ini,
                        force_no_retro):
    """Close an initiative — status → done, record retro + closure metadata.

    t-503 (ini-025): closure is no longer a bare status flip. It captures
    retro_path, closed_at, heat_cost_total (snapshot from heats_used),
    and optional successor_ini for a follow-on initiative. Required retro
    can be overridden with --force-no-retro (audited via rig-event).
    """
    from datetime import datetime, timezone
    root = ctx.obj["root"]
    state = load_state(root)

    # --- locate target ---------------------------------------------------
    target = None
    by_id = {ini.get("id"): ini for ini in state.get("initiatives", []) or []}
    target = by_id.get(initiative_id)
    if target is None:
        _output({"error": f"Initiative {initiative_id} not found"})
        _err(f"Initiative {initiative_id} not found")
        sys.exit(1)

    # --- idempotency: refuse to re-close a done initiative --------------
    if target.get("status") == "done":
        _output({"error": f"{initiative_id} already closed",
                 "initiative": target})
        _err(f"{initiative_id} already closed (closed_at="
             f"{target.get('closed_at')})")
        sys.exit(1)

    # --- retro argument handling ----------------------------------------
    if retro_path and force_no_retro:
        _output({"error": "--retro and --force-no-retro are mutually exclusive"})
        _err("--retro and --force-no-retro are mutually exclusive")
        sys.exit(2)
    if not retro_path and not force_no_retro:
        _output({"error": "--retro <path> is required (or --force-no-retro to "
                          "close without one)"})
        _err(f"{initiative_id}: --retro required (or --force-no-retro escape)")
        sys.exit(2)
    if retro_path:
        retro_file = Path(retro_path)
        if not retro_file.is_absolute():
            retro_file = root / retro_file
        if not retro_file.exists():
            _output({"error": f"retro file not found: {retro_path}"})
            _err(f"retro file not found: {retro_path}")
            sys.exit(1)
        expected = f"plans/ini-{initiative_id.split('-')[-1]}-retro.md"
        # Convention warning — just stderr, doesn't block closure.
        if not retro_path.endswith(expected.split("/")[-1]) \
                and expected not in str(retro_path):
            _err(f"warning: retro path doesn't match convention "
                 f"'{expected}' (got '{retro_path}')")

    # --- successor validation -------------------------------------------
    if successor_ini:
        if successor_ini == initiative_id:
            _output({"error": f"successor cannot reference self: {initiative_id}"})
            _err(f"successor cannot be self ({initiative_id})")
            sys.exit(1)
        succ = by_id.get(successor_ini)
        if succ is None:
            _output({"error": f"successor {successor_ini} not found"})
            _err(f"successor {successor_ini} not found")
            sys.exit(1)
        if succ.get("status") not in ("proposed", "approved", "active"):
            _output({"error": f"successor {successor_ini} has status "
                              f"'{succ.get('status')}' — must be "
                              f"approved/active/proposed"})
            _err(f"successor {successor_ini} has invalid status "
                 f"'{succ.get('status')}'")
            sys.exit(1)

    # --- mutate ----------------------------------------------------------
    target["status"] = "done"
    target["retro_path"] = retro_path  # None iff --force-no-retro
    target["closed_at"] = datetime.now(timezone.utc).isoformat()
    target["heat_cost_total"] = target.get("heats_used") or 0
    target["successor_ini"] = successor_ini  # None if unspecified
    save_state(root, state)

    # --- audit trail ----------------------------------------------------
    event = "initiative_closed"
    _emit_rig_event(
        root, event,
        initiative_id=initiative_id,
        retro_path=retro_path,
        closed_at=target["closed_at"],
        heat_cost_total=target["heat_cost_total"],
        successor_ini=successor_ini,
        force_no_retro=bool(force_no_retro),
    )
    if force_no_retro:
        _err(f"warning: {initiative_id} closed with --force-no-retro "
             f"(rig-event logged)")

    _output({"initiative": target})
    _err(f"Closed {initiative_id}"
         + (f" → successor {successor_ini}" if successor_ini else ""))


@cli.command("list-initiatives")
@click.option("--theme", "theme_filter", default=None, help="Filter by theme ID")
@click.pass_context
def list_initiatives(ctx, theme_filter):
    """List initiatives grouped by status."""
    root = ctx.obj["root"]
    state = load_state(root)
    initiatives = state.get("initiatives", [])
    themes = {th["id"]: th["name"] for th in state.get("themes", [])}

    if theme_filter:
        initiatives = [i for i in initiatives if i["theme_id"] == theme_filter]

    # Group by status
    order = ["proposed", "approved", "active", "done", "rejected"]
    grouped = {s: [] for s in order}
    for ini in initiatives:
        grouped.setdefault(ini["status"], []).append(ini)

    # Count tasks per initiative
    task_counts = {}
    for task in state.get("queue", []):
        ini_id = task.get("initiative_id")
        if ini_id:
            task_counts[ini_id] = task_counts.get(ini_id, 0) + 1

    result = []
    for ini in initiatives:
        result.append({
            **ini,
            "theme_name": themes.get(ini["theme_id"], "?"),
            "task_count": task_counts.get(ini["id"], 0),
        })

    _output({"initiatives": result, "count": len(result)})


# ---------------------------------------------------------------------------
# t-466: initiative rank management.
#
# `rank` is the cross-initiative ordering field. It only applies to
# initiatives the rig is actively scheduling against; everything else
# carries `rank=null`. The CLI below owns three invariants so Anvil
# never has to hand-edit state.json again:
#
#   1. Membership: only RANKABLE_INI_STATUSES = {"approved", "active"}
#      participate. Other statuses are forced to `rank=null` on every
#      mutation.
#   2. Uniqueness + contiguity: rankable ranks form 1..N exactly; no
#      gaps, no duplicates.
#   3. Atomicity: every mutation runs inside `state_lock` and renumbers
#      contiguously before save, so observers never see a half-applied
#      state.
#
# A patrol check (#13) flags drift but does not auto-fix — the operator
# runs `smithy initiative renumber` once they understand the cause.

RANKABLE_INI_STATUSES = {"approved", "active"}


def _rank_sort_key(ini):
    """Sort key for rankable initiatives. Existing ranks first (in order),
    then unranked (None) by id, so `renumber` is stable for already-ranked
    inputs and deterministic for newly-promoted ones."""
    rank = ini.get("rank")
    return (0, rank) if isinstance(rank, int) else (1, ini.get("id", ""))


def _renumber_ranks(state):
    """In-place: assign rank 1..N to rankable initiatives in current
    order; null-out rank on every non-rankable initiative.

    Returns (count_rankable, count_nulled) so callers can report.
    """
    inis = state.get("initiatives", [])
    rankable = [i for i in inis if i.get("status") in RANKABLE_INI_STATUSES]
    rankable.sort(key=_rank_sort_key)
    nulled = 0
    for i in inis:
        if i.get("status") not in RANKABLE_INI_STATUSES:
            if i.get("rank") is not None:
                nulled += 1
            i["rank"] = None
    for n, i in enumerate(rankable, start=1):
        i["rank"] = n
    return len(rankable), nulled


def _rankable_sorted(state):
    """Return rankable initiatives sorted by current rank (ascending)."""
    rs = [i for i in state.get("initiatives", [])
          if i.get("status") in RANKABLE_INI_STATUSES]
    rs.sort(key=_rank_sort_key)
    return rs


def _validate_ranks(state):
    """Return list of issue strings. No mutation."""
    issues = []
    rankable = [i for i in state.get("initiatives", [])
                if i.get("status") in RANKABLE_INI_STATUSES]
    null_inis = [i for i in state.get("initiatives", [])
                 if i.get("status") not in RANKABLE_INI_STATUSES
                 and i.get("rank") is not None]
    for i in null_inis:
        issues.append(f"initiative {i['id']} status={i['status']} carries "
                      f"rank={i['rank']} (should be null)")
    seen = {}
    for i in rankable:
        if i.get("rank") is None:
            issues.append(f"initiative {i['id']} ({i['status']}) missing rank")
            continue
        if not isinstance(i["rank"], int):
            issues.append(f"initiative {i['id']} rank is "
                          f"{type(i['rank']).__name__}, expected int")
            continue
        seen.setdefault(i["rank"], []).append(i["id"])
    expected = set(range(1, len(rankable) + 1))
    actual = set(seen.keys())
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            issues.append(f"initiative ranks not contiguous 1..{len(rankable)}: "
                          f"missing {missing}")
        if extra:
            issues.append(f"initiative ranks out of range 1..{len(rankable)}: "
                          f"extra {extra}")
    for r, ids in sorted(seen.items()):
        if len(ids) > 1:
            issues.append(f"initiative rank {r} collision: {sorted(ids)}")
    return issues


def _find_ini_or_die(state, ini_id):
    for i in state.get("initiatives", []):
        if i["id"] == ini_id:
            return i
    _output({"error": f"Initiative {ini_id} not found"})
    sys.exit(1)


def _require_rankable(ini):
    if ini.get("status") not in RANKABLE_INI_STATUSES:
        _output({"error": f"Initiative {ini['id']} status is "
                          f"{ini['status']!r} — only "
                          f"{sorted(RANKABLE_INI_STATUSES)} are rankable"})
        sys.exit(1)


@cli.group("initiative")
def initiative_group():
    """t-466: initiative rank management subcommands."""


@initiative_group.command("rank")
@click.argument("initiative_id")
@click.argument("position", type=int)
@click.pass_context
def initiative_rank_cmd(ctx, initiative_id, position):
    """Set absolute rank; cascade-shifts others to keep 1..N contiguous."""
    root = ctx.obj["root"]
    with state_lock(root):
        state = load_state(root)
        target = _find_ini_or_die(state, initiative_id)
        _require_rankable(target)
        ranked = _rankable_sorted(state)
        # Remove target then insert at the requested position (1-indexed,
        # clamped). Renumber takes care of the final 1..N stamping.
        ranked = [i for i in ranked if i["id"] != target["id"]]
        idx = max(0, min(len(ranked), position - 1))
        ranked.insert(idx, target)
        for n, i in enumerate(ranked, start=1):
            i["rank"] = n
        _renumber_ranks(state)  # also nulls non-rankables
        save_state(root, state)
    _output({"initiative": target,
             "ranked": [{"id": i["id"], "rank": i["rank"]} for i in ranked]})
    _err(f"{initiative_id} ranked at {target['rank']}")


@initiative_group.command("uprank")
@click.argument("initiative_id")
@click.pass_context
def initiative_uprank_cmd(ctx, initiative_id):
    """Swap with the rank-1 neighbor; no-op at rank 1."""
    root = ctx.obj["root"]
    with state_lock(root):
        state = load_state(root)
        target = _find_ini_or_die(state, initiative_id)
        _require_rankable(target)
        ranked = _rankable_sorted(state)
        idx = next((n for n, i in enumerate(ranked) if i["id"] == target["id"]),
                   None)
        if idx is None:
            _output({"error": f"{initiative_id} not in rankable list"})
            sys.exit(1)
        moved = False
        if idx > 0:
            ranked[idx], ranked[idx - 1] = ranked[idx - 1], ranked[idx]
            moved = True
        for n, i in enumerate(ranked, start=1):
            i["rank"] = n
        _renumber_ranks(state)
        save_state(root, state)
    _output({"initiative": target, "moved": moved,
             "rank": target["rank"]})
    _err(f"{initiative_id} uprank → rank {target['rank']}"
         + ("" if moved else " (no-op, already at top)"))


@initiative_group.command("downrank")
@click.argument("initiative_id")
@click.pass_context
def initiative_downrank_cmd(ctx, initiative_id):
    """Swap with the rank+1 neighbor; no-op at last."""
    root = ctx.obj["root"]
    with state_lock(root):
        state = load_state(root)
        target = _find_ini_or_die(state, initiative_id)
        _require_rankable(target)
        ranked = _rankable_sorted(state)
        idx = next((n for n, i in enumerate(ranked) if i["id"] == target["id"]),
                   None)
        if idx is None:
            _output({"error": f"{initiative_id} not in rankable list"})
            sys.exit(1)
        moved = False
        if idx < len(ranked) - 1:
            ranked[idx], ranked[idx + 1] = ranked[idx + 1], ranked[idx]
            moved = True
        for n, i in enumerate(ranked, start=1):
            i["rank"] = n
        _renumber_ranks(state)
        save_state(root, state)
    _output({"initiative": target, "moved": moved,
             "rank": target["rank"]})
    _err(f"{initiative_id} downrank → rank {target['rank']}"
         + ("" if moved else " (no-op, already at bottom)"))


@initiative_group.command("mv")
@click.argument("initiative_id")
@click.option("--before", "before_id", default=None,
              help="Move target to immediately before this initiative.")
@click.option("--after", "after_id", default=None,
              help="Move target to immediately after this initiative.")
@click.pass_context
def initiative_mv_cmd(ctx, initiative_id, before_id, after_id):
    """Relative-position move. --before and --after are mutually exclusive."""
    if (before_id is None) == (after_id is None):
        _output({"error": "exactly one of --before or --after is required"})
        sys.exit(2)
    anchor_id = before_id or after_id
    if anchor_id == initiative_id:
        _output({"error": "cannot move an initiative relative to itself"})
        sys.exit(1)
    root = ctx.obj["root"]
    with state_lock(root):
        state = load_state(root)
        target = _find_ini_or_die(state, initiative_id)
        anchor = _find_ini_or_die(state, anchor_id)
        _require_rankable(target)
        _require_rankable(anchor)
        ranked = _rankable_sorted(state)
        ranked = [i for i in ranked if i["id"] != target["id"]]
        anchor_idx = next((n for n, i in enumerate(ranked)
                           if i["id"] == anchor["id"]), None)
        if anchor_idx is None:
            _output({"error": f"anchor {anchor_id} not in rankable list"})
            sys.exit(1)
        insert_at = anchor_idx if before_id else anchor_idx + 1
        ranked.insert(insert_at, target)
        for n, i in enumerate(ranked, start=1):
            i["rank"] = n
        _renumber_ranks(state)
        save_state(root, state)
    _output({"initiative": target,
             "anchor": {"id": anchor["id"], "rank": anchor["rank"]},
             "mode": "before" if before_id else "after"})
    _err(f"{initiative_id} moved {'before' if before_id else 'after'} "
         f"{anchor_id} → rank {target['rank']}")


@initiative_group.command("renumber")
@click.pass_context
def initiative_renumber_cmd(ctx):
    """Null-out ranks on non-rankable initiatives; renumber the rest 1..N
    in their current rank order. Idempotent — safe to run repeatedly.
    Also serves as the one-time t-466 cleanup migration."""
    root = ctx.obj["root"]
    with state_lock(root):
        state = load_state(root)
        n_rankable, n_nulled = _renumber_ranks(state)
        save_state(root, state)
    _output({"rankable_renumbered": n_rankable, "nulled": n_nulled})
    _err(f"Renumbered {n_rankable} rankable initiative(s); "
         f"nulled {n_nulled} stray rank(s).")


@initiative_group.command("validate-ranks")
@click.pass_context
def initiative_validate_ranks_cmd(ctx):
    """Report rank invariant violations (no mutation). Exit 0 if clean,
    exit 1 if any issues."""
    root = ctx.obj["root"]
    state = load_state(root)
    issues = _validate_ranks(state)
    _output({"issues": issues, "clean": len(issues) == 0})
    if issues:
        sys.exit(1)


@cli.command("init")
@click.argument("project_name", required=False)
@click.option("--target", default=".", help="Target directory")
@click.option("--with-personas", is_flag=True, help="Scaffold persona directories")
@click.option("--template", "template_name", default=None,
              help="Seed shape: lib|cli|web|data-pipe|mobile|research")
@click.option("--list-templates", is_flag=True, help="List available templates and exit")
@click.pass_context
def init(ctx, project_name, target, with_personas, template_name, list_templates):
    """Scaffold a new Forge project.

    --template=<shape> seeds identity.md intent bullets and state.json
    themes/initiatives from `research/intent-template-library.md`. Without a
    template, init falls back to the blank scaffold for backwards compatibility.
    """
    from datetime import date
    from .intent_templates import TEMPLATES, list_template_names, get_template, render_identity_bullets

    if list_templates:
        _output({"templates": [
            {"name": n, "label": TEMPLATES[n]["label"],
             "themes": len(TEMPLATES[n]["themes"]),
             "initiatives": len(TEMPLATES[n]["initiatives"])}
            for n in list_template_names()
        ]})
        return

    if not project_name:
        _err("Error: project_name required (or pass --list-templates)")
        sys.exit(1)

    template = None
    if template_name:
        template = get_template(template_name)
        if template is None:
            _err(f"Unknown template '{template_name}'. Available: {', '.join(list_template_names())}")
            sys.exit(1)

    target_path = Path(target).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    # Protocol dir
    (target_path / "protocol").mkdir(exist_ok=True)
    (target_path / "research").mkdir(exist_ok=True)

    # State
    state = {
        "project": project_name,
        "budget": {"total_heats": 0, "used": 0, "started_at": None},
        "stages": {s: {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5} for s in VALID_STAGES},
        "allocator": {"integral": {s: 0 for s in VALID_STAGES}},
        "queue": [],
        "ideas": [],
        "themes": list(template["themes"]) if template else [],
        "initiatives": list(template["initiatives"]) if template else [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.0,
    }
    (target_path / "state.json").write_text(json.dumps(state, indent=2) + "\n")

    # Worklog
    (target_path / "worklog.tsv").write_text("timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")

    # Scaffold files
    today = date.today().isoformat()
    templates = {
        "CLAUDE.md": f"# The Smith Protocol\n\nYou are the Smith. You work The Forge — an autonomous AI worker.\n\nRead `identity.md` for the current project context. Read `STRATEGY.md` for the strategic plan.\n\n## Starting a Run\n\nWhen the human says \"Run N heats\":\n1. Read `state.json` and set budget.\n2. Read `protocol/loop.md` and begin the heat loop.\n\n## Protocol Files\n\n| File | Contains |\n|------|----------|\n| `protocol/loop.md` | The heat loop — steps 1-8 |\n| `protocol/allocator.md` | How to pick which stage to work on |\n| `protocol/logging.md` | How to log heats |\n\n## Rules\n\n1. **NEVER STOP.** Loop until budget exhausted.\n2. **One task per heat.** Scope tightly.\n3. **Commit every heat.** Format: `[stage] description`\n4. **The record is sacred.** Never edit worklog.tsv retroactively.\n5. **NEVER directly edit state.json or worklog.tsv.** Use smithy CLI commands.\n",
        "identity.md": (render_identity_bullets(template, project_name) + f"\n## Created\n\n{today}\n"
                        if template else
                        f"# {project_name}\n\n## What This Is\n\nDescribe your project here.\n\n## Commander's Intent\n\n- **Intent**: What are you building and why?\n- **Success looks like**: What does done look like?\n- **Tone**: Quality over speed? Move fast? Careful and tested?\n- **Boundaries**: What should the Smith NOT do?\n- **Not this**: What to avoid?\n\n## Created\n\n{today}\n"),
        "STRATEGY.md": f"# Strategic Plan — {project_name}\n\n*Updated after heat 0 | {today}*\n\n## Vision\n\n## Current State\n\n### What Exists\n\nNothing yet.\n\n## Roadmap\n\n",
        "inbox.md": "# Inbox\n\nWrite messages below.\n",
        "outbox.md": "# Outbox\n\nThe Smith writes status updates here.\n",
        "feedback.md": "# Feedback\n\nHuman writes feedback here. Forge reads it at the start of each run.\n",
        # t-458: per-forge memory subdirs (quench/temper/anneal) eliminate
        # MEMORY.md merge conflicts between parallel Forges. Init seeds all
        # three even if parallelism is off today — cheap, forward-compatible.
        "personas/forge/memory/quench/MEMORY_DAILY.md": "# Daily Memory\n",
        "personas/forge/memory/quench/MEMORY_WEEKLY.md": "# Weekly Memory\n",
        "personas/forge/memory/temper/MEMORY_DAILY.md": "# Daily Memory\n",
        "personas/forge/memory/temper/MEMORY_WEEKLY.md": "# Weekly Memory\n",
        "personas/forge/memory/anneal/MEMORY_DAILY.md": "# Daily Memory\n",
        "personas/forge/memory/anneal/MEMORY_WEEKLY.md": "# Weekly Memory\n",
        ".gitignore": ".forge-checkpoint.json\n.forge-output.log\n",
    }
    for name, content in templates.items():
        dest = target_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    # Personas
    if with_personas:
        for persona in ["anvil", "forge"]:
            (target_path / "personas" / persona).mkdir(parents=True, exist_ok=True)

    # Copy protocol files from forge root
    import shutil
    forge_root = Path(__file__).parent.parent.parent
    protocol_files = ["protocol/loop.md", "protocol/allocator.md", "protocol/logging.md", "protocol/reporting.md"]
    copied = []
    for relpath in protocol_files:
        src = forge_root / relpath
        dst = target_path / relpath
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(relpath)

    all_files = list(templates.keys()) + ["state.json", "worklog.tsv"] + copied
    _output({
        "project": project_name,
        "dir": str(target_path),
        "personas": with_personas,
        "template": template_name,
        "themes_seeded": len(state["themes"]),
        "initiatives_seeded": len(state["initiatives"]),
        "files": all_files,
    })
    _err(f"Initialized {project_name} at {target_path}")
    _err(f"\nNext steps:")
    _err(f"  1. Edit {target_path}/identity.md — describe your project + commander's intent")
    _err(f"  2. cd {target_path}")
    _err(f"  3. claude")
    _err(f"  4. > Run 20 heats")


@cli.command("update")
@click.argument("target")
@click.pass_context
def update(ctx, target):
    """Copy protocol files to an existing project (replace forge-update.sh)."""
    import shutil

    target_path = Path(target).resolve()

    # Verify target is a Forge project
    if not (target_path / "state.json").exists():
        _output({"error": f"{target} doesn't look like a Forge project (missing state.json)"})
        sys.exit(1)

    # Source protocol files are in the forge root (smithy's grandparent package)
    # __file__ = smithy/smithy/smithy/cli.py -> grandparent = smithy/ (forge root)
    forge_root = Path(__file__).parent.parent.parent  # smithy/smithy/smithy -> smithy/

    protocol_files = [
        "CLAUDE.md",
        "protocol/loop.md",
        "protocol/allocator.md",
        "protocol/logging.md",
        "protocol/reporting.md",
    ]

    results = {"updated": [], "added": [], "unchanged": [], "missing": []}

    for relpath in protocol_files:
        src = forge_root / relpath
        dst = target_path / relpath

        if not src.exists():
            results["missing"].append(relpath)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            if src.read_text() == dst.read_text():
                results["unchanged"].append(relpath)
            else:
                shutil.copy2(src, dst)
                results["updated"].append(relpath)
        else:
            shutil.copy2(src, dst)
            results["added"].append(relpath)

    # Copy .gitignore if missing
    gi_src = forge_root / ".gitignore"
    gi_dst = target_path / ".gitignore"
    if gi_src.exists() and not gi_dst.exists():
        shutil.copy2(gi_src, gi_dst)
        results["added"].append(".gitignore")

    _output(results)
    total_changes = len(results["updated"]) + len(results["added"])
    _err(f"Updated {total_changes} files, {len(results['unchanged'])} unchanged")


@cli.command("repomap")
@click.argument("target", default=".")
@click.pass_context
def repomap(ctx, target):
    """Generate research/repo-map.md with file stats, dir structure, key files."""
    import os

    target_path = Path(target).resolve()
    if not target_path.is_dir():
        _output({"error": f"Directory '{target}' not found"})
        sys.exit(1)

    outdir = target_path / "research"
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / "repo-map.md"

    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env", ".mypy_cache", ".pytest_cache"}
    source_exts = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".tsx", ".jsx"}
    config_files = ["package.json", "pyproject.toml", "Cargo.toml", "go.mod", "setup.py", "Makefile", "Dockerfile"]
    doc_files = ["README.md", "CLAUDE.md", "CONTRIBUTING.md", "CHANGELOG.md"]

    # Collect files
    all_files = []
    for root_dir, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            all_files.append(Path(root_dir) / f)

    # Stats by extension
    ext_counts = {}
    for f in all_files:
        ext = f.suffix or "(none)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:10]

    # Directory structure (depth 3)
    dirs_list = []
    for root_dir, dirs, _ in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = Path(root_dir).relative_to(target_path)
        depth = len(rel.parts)
        if depth <= 3:
            dirs_list.append(str(rel) if str(rel) != "." else target_path.name)

    # Key files
    found_configs = [f for f in config_files if (target_path / f).exists()]
    found_docs = [f for f in doc_files if (target_path / f).exists()]

    # Largest source files
    source_files = []
    for f in all_files:
        if f.suffix in source_exts:
            try:
                lines = len(f.read_text(errors="ignore").splitlines())
                source_files.append((lines, str(f.relative_to(target_path))))
            except Exception:
                pass
    largest = sorted(source_files, key=lambda x: -x[0])[:10]

    # Test files
    test_files = [
        str(f.relative_to(target_path)) for f in all_files
        if f.name.startswith("test_") or f.name.endswith("_test.py")
        or ".test." in f.name or ".spec." in f.name
    ][:20]

    # Write markdown
    lines = [
        "# Repository Map\n",
        "*Auto-generated by `smithy repomap`*\n",
        "## Stats\n",
        f"- **Total files**: {len(all_files)}",
        "- **By type**:",
    ]
    for ext, count in top_exts:
        lines.append(f"  - {ext}: {count}")

    lines.extend(["", "## Directory Structure\n", "```"])
    lines.extend(dirs_list[:50])
    lines.extend(["```", "", "## Key Files\n", "### Config & Entry Points"])
    for f in found_configs:
        lines.append(f"- `{f}`")
    lines.extend(["", "### Documentation"])
    for f in found_docs:
        lines.append(f"- `{f}`")

    lines.extend(["", "### Largest Source Files\n"])
    for count, path in largest:
        lines.append(f"- `{path}` ({count} lines)")

    lines.extend(["", "### Test Files"])
    for f in test_files:
        lines.append(f"- `{f}`")
    lines.append("")

    outfile.write_text("\n".join(lines))

    _output({
        "output": str(outfile),
        "total_files": len(all_files),
        "source_files": len(source_files),
        "test_files": len(test_files),
    })
    _err(f"Repo map: {outfile}")


@cli.command("export")
@click.option("--output", default=None, help="Output filename")
@click.pass_context
def export_project(ctx, output):
    """Export project as a self-contained tar.gz."""
    import tarfile
    from datetime import datetime

    root = ctx.obj["root"]
    state = load_state(root)
    project_name = state.get("project", "project")

    if not output:
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        output = f"{project_name}-{ts}.tar.gz"

    output_path = Path(output).resolve()

    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}
    skip_files = {".forge-checkpoint.json", ".forge-output.log"}

    with tarfile.open(output_path, "w:gz") as tar:
        import os
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for f in filenames:
                if f in skip_files:
                    continue
                filepath = Path(dirpath) / f
                arcname = str(filepath.relative_to(root))
                tar.add(filepath, arcname=arcname)

    size_kb = output_path.stat().st_size // 1024
    _output({"file": str(output_path), "size_kb": size_kb, "project": project_name})
    _err(f"Exported to {output_path} ({size_kb} KB)")


@cli.command("commit")
@click.argument("message")
@click.pass_context
def commit(ctx, message):
    """Git add changed files and commit with [stage] prefix."""
    import subprocess
    root = ctx.obj["root"]

    # Check for checkpoint to get current stage
    cp_path = root / ".forge-checkpoint.json"
    stage = "misc"
    if cp_path.exists():
        cp = json.loads(cp_path.read_text())
        stage = cp.get("stage", "misc")

    full_msg = f"[{stage}] {message}"

    # Git add tracked changes
    result = subprocess.run(
        ["git", "add", "-A"], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        _output({"error": f"git add failed: {result.stderr}"})
        sys.exit(1)

    # Check if there's anything to commit
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
    )
    if not status.stdout.strip():
        _output({"error": "Nothing to commit"})
        sys.exit(1)

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", full_msg], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        _output({"error": f"git commit failed: {result.stderr}"})
        sys.exit(1)

    _output({"message": full_msg, "output": result.stdout.strip()})
    _err(f"Committed: {full_msg}")


def _parse_since(spec: str) -> str:
    """Parse --since into an ISO timestamp cutoff.

    Accepts: '7d', '24h', or an ISO date/timestamp. Returns UTC ISO string.
    """
    from datetime import datetime, timedelta
    spec = (spec or "").strip()
    if not spec:
        spec = "7d"
    now = datetime.utcnow()
    if spec.endswith("d") and spec[:-1].isdigit():
        cutoff = now - timedelta(days=int(spec[:-1]))
    elif spec.endswith("h") and spec[:-1].isdigit():
        cutoff = now - timedelta(hours=int(spec[:-1]))
    else:
        # Assume ISO — pass through, no parsing validation beyond this
        return spec
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


@cli.command("steering-retro")
@click.option("--since", default="7d", help="Time window: Nd, Nh, or ISO timestamp")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
@click.pass_context
def steering_retro(ctx, since, fmt):
    """Weekly steering retro — summarize pins, ships, lag, and pure-allocator heats.

    Reads steering.log + worklog.tsv. Emits markdown (default) or JSON digest for the
    given window (default last 7 days).
    """
    import csv
    root = ctx.obj["root"]
    cutoff = _parse_since(since)

    steering_path = root / "steering.log"
    steering_rows = []
    if steering_path.exists():
        with open(steering_path) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("timestamp", "") >= cutoff:
                    steering_rows.append(row)

    wl_path = worklog_path(root)  # t-454: anchor to main repo
    worklog_rows = []
    if wl_path.exists():
        with open(wl_path) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("timestamp", "") >= cutoff:
                    worklog_rows.append(row)

    # Pin events: human_priority set (non-null after), or upcoming_pinned rank bump
    pin_events = [r for r in steering_rows
                  if (r.get("field") == "human_priority" and r.get("after") not in ("null", ""))
                  or (r.get("field") == "upcoming_pinned" and r.get("after") not in ("null", ""))]

    # Task → earliest pin heat
    earliest_pin = {}
    for r in pin_events:
        tid = r.get("task_id", "-")
        try:
            h = int(r.get("heat", "0"))
        except ValueError:
            continue
        if tid not in earliest_pin or h < earliest_pin[tid]:
            earliest_pin[tid] = h

    # Heats completed (outcome == complete) in window — each worklog row is one heat.
    # Note: Forge logs outcome=complete per-heat, not per-task. A single task may
    # span many heats, so we track both the heat count and unique task_ids touched.
    heat_completions = [r for r in worklog_rows if r.get("outcome") == "complete"]

    def _is_real_task(tid):
        return bool(tid) and tid.startswith("t-")

    tasks_touched = {r.get("task_id") for r in heat_completions
                     if _is_real_task(r.get("task_id"))}

    # Shipped-post-pin: earliest-pinned tasks where at least one heat completed after pin
    post_pin = []
    for r in heat_completions:
        tid = r.get("task_id")
        if tid not in earliest_pin:
            continue
        try:
            ship_h = int(r.get("heat", "0"))
        except ValueError:
            continue
        pin_h = earliest_pin[tid]
        if ship_h > pin_h:
            post_pin.append({"task_id": tid, "pin_heat": pin_h, "ship_heat": ship_h,
                             "lag": ship_h - pin_h, "value": r.get("value"),
                             "signal": r.get("signal")})

    # Dedup post_pin to earliest ship per task
    dedup = {}
    for p in post_pin:
        cur = dedup.get(p["task_id"])
        if cur is None or p["ship_heat"] < cur["ship_heat"]:
            dedup[p["task_id"]] = p
    post_pin = list(dedup.values())

    avg_lag = (sum(p["lag"] for p in post_pin) / len(post_pin)) if post_pin else None

    # Pure-allocator heats: real-task worklog rows whose task_id has no prior steering.
    # Filter task-less rows (research/generated) out of the denominator per Gap 2 fix.
    steered_task_ids = {r.get("task_id") for r in steering_rows if _is_real_task(r.get("task_id"))}
    task_heats = [r for r in worklog_rows if _is_real_task(r.get("task_id"))]
    pure_allocator = [r for r in task_heats
                      if r.get("task_id") not in steered_task_ids]

    # By-actor breakdown — count steering events per actor (Gap 4 / t-348)
    by_actor = {}
    for r in steering_rows:
        actor = r.get("actor") or "-"
        by_actor[actor] = by_actor.get(actor, 0) + 1
    by_actor_sorted = sorted(by_actor.items(), key=lambda x: (-x[1], x[0]))

    digest = {
        "since": cutoff,
        "pins_made": len(pin_events),
        "unique_tasks_pinned": len(earliest_pin),
        "heats_completed": len(heat_completions),
        "unique_tasks_touched": len(tasks_touched),
        "shipped_post_pin": post_pin,
        "avg_lag_heats": avg_lag,
        "pure_allocator_heats": len(pure_allocator),
        "task_heats_total": len(task_heats),
        "steering_log_present": steering_path.exists(),
        "by_actor": [{"actor": a, "events": n} for a, n in by_actor_sorted],
    }

    if fmt == "json":
        _output(digest)
        return

    # Markdown
    empty_log = not steering_path.exists() or not steering_rows
    pure_frac = (f"{len(pure_allocator)}/{len(task_heats)}" if task_heats else "0/0")
    lines = [
        f"# Steering retro — since {cutoff}",
        "",
        f"- **Pin events:** {len(pin_events)} across {len(earliest_pin)} unique task(s)",
        f"- **Heats completed:** {len(heat_completions)} (across {len(tasks_touched)} unique task(s))",
        f"- **Shipped post-pin:** {len(post_pin)}" +
            (f" (avg lag {avg_lag:.1f}h)" if avg_lag is not None else ""),
        f"- **Pure-allocator heats:** {len(pure_allocator)} "
        f"({pure_frac} task-heats had no prior steering)",
        "",
    ]
    if post_pin:
        lines.append("## Shipped post-pin")
        lines.append("")
        lines.append("| task | pin heat | ship heat | lag | value | signal |")
        lines.append("|------|----------|-----------|-----|-------|--------|")
        for p in sorted(post_pin, key=lambda x: x["lag"]):
            lines.append(f"| {p['task_id']} | {p['pin_heat']} | {p['ship_heat']} | "
                         f"{p['lag']}h | {p['value']} | {p['signal']} |")
        lines.append("")
    if pin_events and not post_pin:
        lines.append("_No pinned tasks shipped in window yet._")
        lines.append("")
    if by_actor_sorted:
        lines.append("## By actor")
        lines.append("")
        lines.append("| actor | events |")
        lines.append("|-------|--------|")
        for a, n in by_actor_sorted:
            lines.append(f"| {a} | {n} |")
        lines.append("")
    if empty_log:
        footer = ("_Note: steering.log not present — no attribution data yet. "
                  "Pin/defer/reorder via Bellows or Poker to populate this log._"
                  if not steering_path.exists()
                  else "_Note: steering.log is empty for this window — no pins or "
                       "steering events recorded in the selected range._")
        lines.append(footer)
        lines.append("")

    click.echo("\n".join(lines))


@cli.command("rig-replay")
@click.option("--since", "since", default=50, type=int,
              help="Print the last N events (default 50). Pass 0 for all.")
@click.option("--event", "event_filter", default=None,
              help="Only show events whose name contains this substring.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit raw JSONL instead of the pretty single-line format.")
@click.pass_context
def rig_replay(ctx, since, event_filter, as_json):
    """t-425: pretty-print recent rig-events.jsonl entries.

    Append-only telemetry is useless if nobody reads it — this is the
    zero-dep viewer. Format per row: `<ts>  <event>  actor=<x>
    task=<y>  [detail]`. Use `--since 0` to read the whole file, or
    `--event assembly` to filter to a single class of events.
    """
    path = _rig_events_path(ctx.obj["root"])
    if not path.exists():
        _err(f"No rig-events.jsonl at {path}")
        return
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if event_filter:
        lines = [ln for ln in lines if event_filter in ln]
    if since > 0:
        lines = lines[-since:]
    if as_json:
        for ln in lines:
            click.echo(ln)
        return
    for ln in lines:
        try:
            e = json.loads(ln)
        except json.JSONDecodeError:
            click.echo(f"?? {ln}")
            continue
        extras = []
        for k in ("forge_id", "task_id", "stage", "branch", "sha",
                  "latency_ms", "nudged", "reason", "target", "value",
                  "signal", "heat", "position", "queue_size", "count",
                  "task_ids"):
            if k in e:
                v = e[k]
                if k == "sha" and isinstance(v, str):
                    v = v[:8]
                extras.append(f"{k}={v}")
        click.echo(f"{e.get('ts','?')}  {e.get('event','?'):<26}"
                   f"  actor={e.get('actor','?'):<14}  "
                   f"{'  '.join(extras)}")


@cli.command("up")
@click.option("--force", is_flag=True, help="Kill existing tmux session and recreate.")
@click.option("--dry-run", is_flag=True, help="Print panes that would be created and exit.")
@click.option("--session", "session_name", default="forge",
              help="tmux session name (default: forge). Passed via FORGE_SESSION env.")
@click.pass_context
def up(ctx, force, dry_run, session_name):
    """Launch the Forge tmux rig (anvil/marshal/assembly + forges)."""
    import os
    import subprocess
    root = ctx.obj["root"]
    script = root / "scripts" / "start-smithy.sh"
    if not script.exists():
        _output({"error": f"start-smithy.sh not found at {script}"})
        sys.exit(1)
    cmd = [str(script)]
    if force:
        cmd.append("--force")
    if dry_run:
        cmd.append("--dry-run")
    env = os.environ.copy()
    env["FORGE_SESSION"] = session_name
    result = subprocess.run(cmd, cwd=str(root), env=env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    cli()
