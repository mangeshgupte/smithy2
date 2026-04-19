# Assembly-test divergence — root cause

**Task:** t-502 · 2026-04-19 · forge-anneal
**Scope:** diagnose why 4 tasks (t-479, t-489, t-491, t-484) pass Forge's
local `pytest` but fail/error in Assembly's staging-worktree `pytest`.

## TL;DR

Single shared root cause. Tests on a task branch do
`from smithy.cli import ...` (the "single-level" form). That name
resolves through the **globally-installed editable `smithy` package**
whose `.pth` file was last written by somebody's
`pip install -e …/smithy2/smithy` — currently bound to **MAIN**.
Assembly runs `python3 -m pytest` in `.worktrees/_assembly-staging/`;
system `python3` sees that `.pth`, loads main's `smithy.cli`, and any
symbol added on the task branch (`_detect_starving_forges`,
`marshal-escalate`, `comms-snapshot`, the new `TestNudgeRosterMismatch`
class's dependencies) is missing → `AttributeError` / `ImportError` /
`exit 2` / collection ERROR.

Forge's local run uses `<worktree>/.venv/bin/python3` (per t-461),
whose editable install points at the **worktree's** `smithy`. Same
test, different `smithy`, different outcome.

Staging has **no `.venv`** — that's the asymmetry. t-489's earlier
fix-attempt tried to prefer `<wt>/.venv/bin/python3` in
`run_tests_in_worktree`, but Assembly calls that function with
`forge_id = "_assembly-staging"`, and staging's `.venv` doesn't exist,
so the function falls through to system `python3` and the `.pth`
poison wins again.

Fix (recommended): **extend the per-Forge venv pattern (t-461) to cover
the staging worktree**. One-time cost at first Assembly tick of a
session; idempotent thereafter. Kills this entire class of divergence
by construction and preserves the current import conventions.

## 1. Confirmed per-task

All four are the same bug in different costumes:

| Task | Test file | Symbol only on task branch | Fail mode |
|---|---|---|---|
| t-479 | `smithy/tests/test_marshal_escalate.py` | `from smithy.cli import cli` where cli has `marshal-escalate*` commands | `result.exit_code == 2` — "unknown command" |
| t-489 | `smithy/tests/test_smithy.py::TestNudgeRosterMismatch` | New test class exercising new `_resolve_pane(forge_ids=…)` signature in cli | `TypeError: unexpected keyword argument` (main's helper has the old signature) |
| t-491 | `smithy/tests/test_t491_starvation.py` | `from smithy.cli import _detect_starving_forges` | `ImportError` at collection — symbol doesn't exist on main |
| t-484 | `smithy/tests/test_t484_comms_snapshot.py` | `from smithy.cli import cli` where cli has `comms-snapshot` command | `result.exit_code != 0` → JSON parse fails |

Evidence, extracted from each rejection's staging pytest output
(`assembly-log.jsonl`):

```
t-479: FAILED smithy/tests/test_marshal_escalate.py::TestMarshalEscalateList::test_list_empty
t-489: FAILED smithy/tests/test_smithy.py::TestNudgeRosterMismatch::test_wrong_session_fails_loud_not_queue
t-491: ERROR smithy/tests/test_t491_starvation.py — Interrupted: 1 error during collection
t-484: FAILED smithy/tests/test_t484_comms_snapshot.py::TestWorklog::test_window_minutes_flag_narrows
```

## 2. Mechanism

### 2.1 sys.path at Assembly's test invocation

From `.worktrees/_assembly-staging/` with bare `/usr/bin/python3`:

```
sys.path[0]    ''  (cwd = _assembly-staging)
…
/Users/mangesh/Library/Python/3.9/lib/python/site-packages  ← editable .pth
```

The `.pth` line in that site-packages adds
`/Users/mangesh/vibes/smithy2/smithy` (the **main** repo's smithy
project dir) to sys.path. That dir contains `smithy/__init__.py`, so
`import smithy` finds a **regular package** rooted at
`/Users/mangesh/vibes/smithy2/smithy/smithy/` — main's code.

Meanwhile `<staging>/smithy/` (no top-level `__init__.py`) is a
namespace-package candidate at cwd. But a regular package beats
namespace resolution, so the `.pth` wins unconditionally.

### 2.2 Why the two import forms behave differently

```
from smithy.cli       import cli      # single-level
from smithy.smithy.cli import cli     # namespace (through "smithy.smithy")
```

- **single-level** → resolves via the `.pth`-installed regular package
  → main's code.
- **namespace** → `smithy.smithy` is a submodule inside the namespace
  view of `smithy`. Since `<staging>/smithy/smithy/__init__.py` exists,
  Python finds the staging source via the cwd namespace path. (The
  `.pth`-installed regular package for `smithy` has no nested
  `smithy/smithy/` subpkg — it is `smithy/smithy/`, not
  `smithy/smithy/smithy/` — so the namespace form **doesn't** fall
  through to main.)

This is why `from smithy.smithy.assembly import ...` tests (e.g.
`tests/test_assembly_gitops.py`) have always worked on the task
branches without issue, while `from smithy.cli import ...` tests
flake. The repo currently has **both** idioms in use:

```
$ grep -rn '^from smithy' worktree-tests | awk -F'from smithy' '{print "smithy"$2}' | sort -u
  6 × smithy.cli import cli            ← broken under Assembly
  5 × smithy.smithy.cli import cli as smithy_cli  ← works
  4 × smithy.state import VALID_STAGES ← broken
  2 × smithy.smithy.assembly import (  ← works
  …
```

### 2.3 Forge-local path (why local passes)

Per t-461, each Forge worktree has `<wt>/.venv/` with `smithy` installed
editable pointing at `<wt>/smithy`. When Forge runs `.venv/bin/python3
-m pytest`, the venv's site-packages has its own `.pth` to `<wt>/smithy`
— so `import smithy` resolves to the **worktree's** code with the
task-branch changes. Every import form passes.

Staging has no venv. Assembly's fall-through to `/usr/bin/python3` is
the divergence.

### 2.4 t-489's first-attempt fix (landed, insufficient)

`70f59af` changed `run_tests_in_worktree` to prefer
`<worktree>/.venv/bin/python3` when it exists. Correct idea for Forge
worktrees; Assembly's callers pass `forge_id = "_assembly-staging"`,
staging has no `.venv`, `.venv/bin/python3` doesn't exist, so the
fallback keeps the bug alive.

The click-version fix in the same commit (try/except
`mix_stderr=False`) is orthogonal — that one is real and needed
(already applied in `test_marshal_escalate.py` by my t-479 landing).

## 3. Reproducer

Minimal repro against the current repo:

```bash
# From a task-branch-shaped worktree (here: forge-anneal/t-502 with
# any new symbol that doesn't exist on main):
cd <smithy2>/.worktrees/_assembly-staging

# 1) What Assembly actually runs — fails.
/usr/bin/python3 -c '
from smithy.cli import _detect_starving_forges
print("ok")
' 2>&1 | tail -3
# → ImportError (main lacks the symbol)

# 2) What Forge ran locally — passes.
<main>/.worktrees/<forge>/.venv/bin/python3 -c '
from smithy.cli import _detect_starving_forges
print("ok")
'
# → ok (worktree venv editable resolves the symbol)

# 3) Namespace form passes from both — even under Assembly:
/usr/bin/python3 -c '
from smithy.smithy.cli import _detect_starving_forges
print("ok")
'
# → ok (cwd namespace path wins over the .pth-installed package)
```

The delta is a single line of Python’s import-resolution logic.

## 4. Proposed fix

### Option A — per-staging venv (recommended)

Extend `scripts/forge-venv-setup.sh` / the equivalent bootstrap path to
cover `.worktrees/_assembly-staging/`. On `run_tests_in_worktree(root,
"_assembly-staging", ...)`, if `<staging>/.venv/` is missing, create
it (`uv venv`) and install the staging worktree's smithy editable
(`VIRTUAL_ENV=<staging>/.venv uv pip install -e <staging>/smithy`).
Then invoke `<staging>/.venv/bin/python3 -m pytest -q`.

Pros:
- Symmetric with Forges; no special-casing in test code.
- Both `smithy.cli` and `smithy.smithy.cli` import forms resolve
  correctly.
- One-time (~5s) cost at first merge of a session; subsequent ticks
  reuse.
- Works automatically for any future divergence class caused by
  sys.path ordering — this is the structural fix.

Cons:
- After a merge to `main` that touches `smithy/`, the staging venv's
  `.pth` still points at the rebased-but-now-obsolete staging source.
  Need an invalidation step — probably `uv pip install -e .` again
  every merge, which is idempotent and fast. Can be a one-liner in
  `assembly_tick`'s post-merge hook.

Implementation: 1 heat. Tests exist (`test_t461_forge_venv_setup.py`
covers the Forge case — the same shape for staging is a small
parametrization).

### Option B — set PYTHONPATH per run

`run_tests_in_worktree` sets `PYTHONPATH=<wt>/smithy` before invoking
pytest. Prepends staging's `smithy/` to `sys.path` so
`import smithy` finds the regular package at
`<staging>/smithy/smithy/`.

Pros:
- No venv creation.
- Zero persistent state.

Cons:
- **Breaks** all `from smithy.smithy.xxx` imports: once the outer
  `smithy` resolves as a regular package (not namespace), there's no
  `smithy/smithy/` inside it, so the nested name fails with
  `ModuleNotFoundError: No module named 'smithy.smithy'`. Confirmed in
  my t-479 dive when I tried this exact approach.
- Requires a sweeping import rewrite across the whole test tree to
  standardize on a single form.

Rejected unless paired with a codebase-wide import standardization.

### Option C — standardize test imports on the namespace form

No Assembly change. Sweep every test file; rewrite
`from smithy.cli` → `from smithy.smithy.cli`, etc. (also
`@patch("smithy.cli.…")` → `@patch("smithy.smithy.cli.…")` — I already
made this change for t-479's test file as a one-off).

Pros:
- Zero infra changes; no venv, no PYTHONPATH.
- Works as-is under Assembly today.

Cons:
- Convention-based; a future contributor reintroduces the bug the
  moment they write `from smithy.cli import …`.
- Breaks direct invocation `python -m smithy.cli` if that's wired
  anywhere (spot-check: no; smithy's console entry point is
  `smithy = smithy.cli:cli` which uses the installed package path and
  is unaffected).

Workable as a short-term stabilizer paired with a lint rule.

## 5. Recommendation

**Land Option A as the structural fix.** Ship a small supporting lint
(§6) so the `smithy.xxx` → `smithy.smithy.xxx` ambiguity stops
producing surprise test divergence across Forge/Assembly environments.

Follow-ups to file under **ini-019** ("hardening the rig"):

**Ticket I1 (P1) — staging venv bootstrap.** `ensure_staging_venv()`
in `smithy.smithy.assembly`; called at the top of
`run_tests_in_worktree` when `forge_id == "_assembly-staging"`. Tests:
(a) first call creates `<staging>/.venv/`; (b) subsequent calls
reuse; (c) after `main` touches `smithy/`, the venv install is
refreshed; (d) Assembly's pytest against a task-branch symbol that
doesn't exist on main passes. Estimate: 1 implementation heat. Unblocks
the 4-task class and any future one of this shape.

**Ticket I2 (P3) — patrol check #17: test-file import style.**
`patrol` surfaces test files containing bare
`from smithy.cli`/`smithy.state`/`smithy.assembly`/`smithy.dispatch`
imports with a hint to use the namespace form. Does NOT auto-fix (test
files are hand-written, the lint is advisory). Complements t-461's
install-sanity check. Estimate: <1 implementation heat.

**Ticket I3 (P2) — sweep existing tests.** Re-write the 15+
`from smithy.<mod>` imports in the test tree to the namespace form,
in a single "style" commit. Reduces the attack surface even with
Option A landed — belt-and-suspenders. Estimate: 1 implementation heat.

## 6. Out of scope / adjacent

- **Click `mix_stderr` deprecation** (seen on t-479, t-489). Separate
  compatibility issue, already patched per-file with a
  `try: CliRunner(mix_stderr=False)` except TypeError fallback in
  test_marshal_escalate.py, test_smithy.py, test_hooks.py,
  test_marshal_forge_flow.py. No re-investigation needed.
- **Pre-submit test gate running from main cwd.** Separate: end-heat's
  `_run_presubmit_tests` still runs from the main repo, so task-branch
  test fixture changes aren't visible and the gate spuriously rejects.
  I've flagged this three times; it still wants a task. Ticket I4
  candidate under ini-019.

## 7. Files referenced

- `smithy/smithy/assembly.py:262` — `run_tests_in_worktree` (the
  dispatch point)
- `smithy/smithy/assembly.py:262–277` (post-t-489 70f59af) — prefers
  `<wt>/.venv/bin/python3`; insufficient for staging
- `scripts/forge-venv-setup.sh` — the prior-art for Option A
- `.pth` at `/Users/mangesh/Library/Python/3.9/lib/python/site-packages/`
  — the contaminated sys.path entry
- Rejection records: `assembly-log.jsonl` entries for t-479, t-489,
  t-491, t-484

## 8. Deliverables

- **This doc** — diagnosis + reproducer + recommendation.
- **Follow-ups to file** (listed in §5): I1 (staging venv), I2 (patrol
  check), I3 (test import sweep), and I4 (pre-submit gate cwd) under
  ini-019.
