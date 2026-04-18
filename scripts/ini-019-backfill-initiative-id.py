#!/usr/bin/env python3
"""ini-019 R2 · Retro-annotate task → initiative_id migration.

One-time backfill: adds `initiative_id` (nullable) to every state.queue task,
then infers mappings for tasks currently missing one by cross-referencing:

  1. Task desc ↔ initiative description token overlap (Jaccard on informative tokens).
  2. Commit messages that mention the task_id (git log -G "t-XXX").
  3. Heat-proximity to the initiative's approval window (earliest worklog heat
     where the initiative had heats_used increment).

Usage:
  ini-019-backfill-initiative-id.py --dry-run            # (default) print proposed mapping
  ini-019-backfill-initiative-id.py --apply-schema       # add initiative_id:null + bump schema_version
  ini-019-backfill-initiative-id.py --apply-mapping      # write inferred mappings to state.json
  ini-019-backfill-initiative-id.py --out plans/ini-019-retro-map.md   # dry-run diff to file

Invariants:
  - Never overwrites an existing non-null initiative_id.
  - Ambiguous cases (multiple plausible inis, score tie or near-tie) are
    flagged, NOT guessed — the task stays null, and the operator resolves.
  - Rejected/deferred initiatives are NOT mapping targets.
  - Exits non-zero if state.json would become invalid (schema check).

Exit codes: 0 clean, 1 validation failure, 2 ambiguity (mapping not applied).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---- paths ------------------------------------------------------------------

def repo_root() -> Path:
    """Resolve the MAIN repo root — not a worktree. Prefer `git rev-parse
    --git-common-dir` so we always write the canonical state.json (t-419)."""
    here = Path(__file__).resolve()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=here.parent, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            common = Path(r.stdout.strip()).resolve()
            # common is .../smithy2/.git (or .../smithy2/.git/worktrees/<id>/…
            # resolved to main's .git); main repo root is one up from .git.
            main_root = common.parent
            if (main_root / "state.json").exists():
                return main_root
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    for p in [here, *here.parents]:
        if (p / "state.json").exists() and (p / "worklog.tsv").exists():
            return p
    raise SystemExit("could not locate repo root (state.json + worklog.tsv)")


# ---- schema -----------------------------------------------------------------

CURRENT_SCHEMA = 1
TARGET_SCHEMA = 2  # t-445: adds `initiative_id` (nullable) to every queue task

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to",
    "was", "with", "this", "these", "those", "we", "you", "they", "i", "but",
    "not", "can", "add", "new", "use", "using", "make", "create", "update",
    "do", "done", "fix", "t", "via", "per", "so", "if", "all", "one", "two",
    "task", "tasks", "heat", "heats", "stage", "file", "files", "code", "test",
    "tests", "write", "writing", "run", "runs", "set", "get", "also",
}


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9_\-]{3,}", text.lower())
    return {t for t in raw if t not in STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---- inference --------------------------------------------------------------

def _task_id_commit_mentions(root: Path, task_id: str) -> list[str]:
    """Return commit messages where this task_id appears (subject line only)."""
    try:
        r = subprocess.run(
            ["git", "log", "--format=%s", "-G", re.escape(task_id), "--all"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        return [ln for ln in r.stdout.splitlines() if task_id in ln]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _initiative_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Approved or active initiatives only — rejected ones are never mapping targets."""
    return [
        i for i in state.get("initiatives", [])
        if i.get("status") in ("approved", "active")
    ]


def _score(task: dict[str, Any], ini: dict[str, Any],
           commit_mentions: list[str]) -> tuple[float, list[str]]:
    """Return (score ∈ [0,1], reasons). Higher = stronger match."""
    reasons: list[str] = []
    score = 0.0

    # Signal 1 — desc token overlap.
    t_tokens = _tokens(task.get("desc", ""))
    i_tokens = _tokens(f"{ini.get('title','')} {ini.get('description','')}")
    jac = _jaccard(t_tokens, i_tokens)
    if jac > 0:
        score += 0.6 * jac
        reasons.append(f"desc_jaccard={jac:.2f}")

    # Signal 2 — explicit initiative tag in task desc or commit subjects.
    iid = ini.get("id", "")
    hit_in_desc = iid and iid in task.get("desc", "")
    hit_in_commit = any(iid in m for m in commit_mentions)
    if hit_in_desc:
        score += 0.4
        reasons.append("ini_id_in_desc")
    if hit_in_commit:
        score += 0.25
        reasons.append("ini_id_in_commit")

    # Signal 3 — ini title token hit (stronger than description, lower FP rate).
    title_tokens = _tokens(ini.get("title", ""))
    title_overlap = len(t_tokens & title_tokens) / max(1, len(title_tokens))
    if title_overlap >= 0.5:
        score += 0.2
        reasons.append(f"title_overlap={title_overlap:.2f}")

    return min(1.0, score), reasons


def propose_mapping(state: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Return proposals: [{task_id, current, proposed, confidence, reasons, alts}]."""
    inis = _initiative_candidates(state)
    proposals: list[dict[str, Any]] = []

    for task in state.get("queue", []):
        current = task.get("initiative_id")
        if current:  # never overwrite existing mapping
            continue

        commit_mentions = _task_id_commit_mentions(root, task["id"])
        scored = []
        for ini in inis:
            s, why = _score(task, ini, commit_mentions)
            if s > 0:
                scored.append((s, ini["id"], why))
        scored.sort(reverse=True)

        top = scored[0] if scored else None
        runner = scored[1] if len(scored) > 1 else None

        proposal: dict[str, Any] = {
            "task_id": task["id"],
            "stage": task.get("stage"),
            "desc": task.get("desc", "")[:120],
            "current": current,
            "proposed": None,
            "confidence": 0.0,
            "reasons": [],
            "alts": [],
            "ambiguous": False,
        }

        if top and top[0] >= 0.20:
            proposal["proposed"] = top[1]
            proposal["confidence"] = round(top[0], 3)
            proposal["reasons"] = top[2]
            # Ambiguous if runner-up is within 0.10 of top.
            if runner and (top[0] - runner[0]) < 0.10:
                proposal["ambiguous"] = True
                proposal["alts"] = [
                    {"id": runner[1], "score": round(runner[0], 3),
                     "reasons": runner[2]}
                ]

        proposals.append(proposal)

    return proposals


# ---- schema migration -------------------------------------------------------

def apply_schema(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Add initiative_id:null to every queue task; bump schema_version."""
    added = 0
    for t in state.get("queue", []):
        if "initiative_id" not in t:
            t["initiative_id"] = None
            added += 1
    prev = state.get("schema_version", 1)
    state["schema_version"] = TARGET_SCHEMA
    return state, {"added_null_fields": added,
                   "schema_prev": prev, "schema_new": TARGET_SCHEMA}


def apply_mapping(state: dict[str, Any],
                  proposals: list[dict[str, Any]],
                  allow_ambiguous: bool = False) -> dict[str, int]:
    """Write proposed initiative_ids into state.queue; skip ambiguous by default."""
    by_id = {t["id"]: t for t in state.get("queue", [])}
    applied, skipped_ambiguous, skipped_low_conf = 0, 0, 0
    for p in proposals:
        if not p["proposed"]:
            skipped_low_conf += 1
            continue
        if p["ambiguous"] and not allow_ambiguous:
            skipped_ambiguous += 1
            continue
        if p["task_id"] in by_id and not by_id[p["task_id"]].get("initiative_id"):
            by_id[p["task_id"]]["initiative_id"] = p["proposed"]
            applied += 1
    return {"applied": applied,
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_low_confidence": skipped_low_conf}


# ---- validators -------------------------------------------------------------

def validate(state: dict[str, Any]) -> list[str]:
    """Return list of validation errors; empty = clean."""
    errs: list[str] = []
    valid_inis = {i["id"] for i in state.get("initiatives", [])}

    for t in state.get("queue", []):
        if "initiative_id" not in t:
            errs.append(f"{t['id']}: missing initiative_id field")
        iid = t.get("initiative_id")
        if iid is not None and iid not in valid_inis:
            errs.append(f"{t['id']}: initiative_id={iid} not in initiatives list")
    return errs


# ---- output -----------------------------------------------------------------

def render_dryrun(proposals: list[dict[str, Any]], stats: dict[str, int]) -> str:
    lines = [
        "# ini-019 · Retro Initiative Backfill — Dry-Run Map",
        "",
        f"Proposals: {len(proposals)}",
        f"  High-confidence (≥0.50): {sum(1 for p in proposals if p['confidence'] >= 0.50)}",
        f"  Medium (0.20–0.49): {sum(1 for p in proposals if 0.20 <= p['confidence'] < 0.50)}",
        f"  Ambiguous (tie/near-tie): {sum(1 for p in proposals if p['ambiguous'])}",
        f"  No confident match (<0.20): {sum(1 for p in proposals if not p['proposed'])}",
        "",
        "| task_id | stage | proposed | confidence | reasons | ambiguous | alts |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in proposals:
        alts = ", ".join(
            f"{a['id']}({a['score']:.2f})" for a in p["alts"]) or "—"
        lines.append(
            f"| {p['task_id']} | {p['stage']} | "
            f"{p['proposed'] or '(none)'} | {p['confidence']:.2f} | "
            f"{', '.join(p['reasons']) or '—'} | "
            f"{'⚠️' if p['ambiguous'] else ''} | {alts} |"
        )
    return "\n".join(lines) + "\n"


# ---- main -------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", help="path to state.json (default: repo root)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print proposed mapping (default if no action flag)")
    ap.add_argument("--apply-schema", action="store_true",
                    help="add initiative_id:null to all tasks; bump schema_version")
    ap.add_argument("--apply-mapping", action="store_true",
                    help="apply inferred mappings (skips ambiguous unless --allow-ambiguous)")
    ap.add_argument("--allow-ambiguous", action="store_true",
                    help="apply mappings flagged as ambiguous (operator override)")
    ap.add_argument("--out", help="write dry-run diff to this file (markdown)")
    args = ap.parse_args()

    root = repo_root()
    state_path = Path(args.state) if args.state else root / "state.json"
    state = json.loads(state_path.read_text())

    if not any([args.apply_schema, args.apply_mapping]):
        args.dry_run = True

    if args.dry_run:
        proposals = propose_mapping(state, root)
        stats = {}
        out = render_dryrun(proposals, stats)
        if args.out:
            Path(args.out).write_text(out)
            print(f"wrote dry-run to {args.out}", file=sys.stderr)
        else:
            sys.stdout.write(out)
        return 0

    if args.apply_schema:
        state, stats = apply_schema(state)
        errs = validate(state)
        if errs:
            for e in errs:
                print(f"VALIDATION: {e}", file=sys.stderr)
            return 1
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps({"apply_schema": stats, "state": str(state_path)}, indent=2))

    if args.apply_mapping:
        proposals = propose_mapping(state, root)
        map_stats = apply_mapping(state, proposals,
                                  allow_ambiguous=args.allow_ambiguous)
        errs = validate(state)
        if errs:
            for e in errs:
                print(f"VALIDATION: {e}", file=sys.stderr)
            return 1
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps({"apply_mapping": map_stats,
                          "state": str(state_path)}, indent=2))
        if map_stats["skipped_ambiguous"]:
            return 2  # signal that operator review is needed

    return 0


if __name__ == "__main__":
    sys.exit(main())
