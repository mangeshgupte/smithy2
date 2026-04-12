"""Intent template library (t-347).

Structured Python form of the 6 templates documented in
`research/intent-template-library.md`. Kept in code (not parsed from markdown)
so behavior is stable across doc edits. If you change a template here, update
the research doc in lockstep.
"""

TEMPLATES = {
    "lib": {
        "label": "Library / SDK",
        "intent_bullets": [
            "Ship a stable, documented package that solves ONE problem well.",
            "Optimize for the caller's ergonomics, not the author's convenience.",
            "Treat every exported symbol as a contract — breaking changes need major-version bumps.",
            "Version v1.0 means \"I'm willing to be stuck with this API for a year.\"",
        ],
        "themes": [
            {"id": "th-api", "name": "API Surface", "rank": 1, "status": "active"},
            {"id": "th-docs", "name": "Docs & Examples", "rank": 2, "status": "active"},
            {"id": "th-tests", "name": "Test Coverage", "rank": 3, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-core", "theme_id": "th-api", "title": "Core types + happy-path API", "status": "approved", "rank": 1},
            {"id": "ini-errs", "theme_id": "th-api", "title": "Error model + failure semantics", "status": "proposed", "rank": 2},
            {"id": "ini-readme", "theme_id": "th-docs", "title": "README + quickstart example", "status": "approved", "rank": 3},
            {"id": "ini-cov", "theme_id": "th-tests", "title": "95%+ unit coverage on core path", "status": "approved", "rank": 4},
        ],
    },
    "cli": {
        "label": "CLI Tool",
        "intent_bullets": [
            "Default behavior should be useful — zero flags required for the common case.",
            "Every subcommand fits on one line of `--help`.",
            "Exit codes are promises: 0 = good, non-zero = actionable diagnostic on stderr.",
            "No interactive prompts unless explicitly requested; scripts depend on silent success.",
        ],
        "themes": [
            {"id": "th-ux", "name": "Command UX", "rank": 1, "status": "active"},
            {"id": "th-io", "name": "Input/Output", "rank": 2, "status": "active"},
            {"id": "th-dist", "name": "Distribution", "rank": 3, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-subcmd", "theme_id": "th-ux", "title": "Subcommand tree (verb-noun)", "status": "approved", "rank": 1},
            {"id": "ini-help", "theme_id": "th-ux", "title": "--help output on every command", "status": "approved", "rank": 2},
            {"id": "ini-stdio", "theme_id": "th-io", "title": "stdin/stdout pipe-friendliness", "status": "proposed", "rank": 3},
            {"id": "ini-install", "theme_id": "th-dist", "title": "One-line install (brew/curl/pipx)", "status": "proposed", "rank": 4},
        ],
    },
    "web": {
        "label": "Web App (product)",
        "intent_bullets": [
            "Ship the golden-path flow end-to-end before polishing any single screen.",
            "Auth is a foundation, not a feature — get it right once, stop touching it.",
            "Server-rendered HTML first; reach for SPA patterns only when interactivity requires them.",
            "No \"admin tools\" built in the product until the product has users.",
        ],
        "themes": [
            {"id": "th-golden", "name": "Golden-path flow", "rank": 1, "status": "active"},
            {"id": "th-auth", "name": "Auth & Accounts", "rank": 2, "status": "active"},
            {"id": "th-perf", "name": "Performance", "rank": 3, "status": "active"},
            {"id": "th-ops", "name": "Deployment & Ops", "rank": 4, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-signup", "theme_id": "th-auth", "title": "Signup → email verify → first session", "status": "approved", "rank": 1},
            {"id": "ini-onboard", "theme_id": "th-golden", "title": "First-run onboarding to aha-moment", "status": "approved", "rank": 2},
            {"id": "ini-nav", "theme_id": "th-golden", "title": "Primary nav + 3 core pages", "status": "approved", "rank": 3},
            {"id": "ini-deploy", "theme_id": "th-ops", "title": "CI → staging → prod pipeline", "status": "proposed", "rank": 4},
        ],
    },
    "data-pipe": {
        "label": "Data Pipeline",
        "intent_bullets": [
            "Idempotent by default — re-running a job must be safe, not a double-write.",
            "Schema expectations are asserted, not assumed; upstream changes fail loud, not silent.",
            "Freshness SLO is a first-class metric; dashboards show \"last successful run\" before anything else.",
            "Backfill is a required path, not a one-off script.",
        ],
        "themes": [
            {"id": "th-ingest", "name": "Ingest & Schema", "rank": 1, "status": "active"},
            {"id": "th-xform", "name": "Transform Logic", "rank": 2, "status": "active"},
            {"id": "th-obs", "name": "Observability", "rank": 3, "status": "active"},
            {"id": "th-serve", "name": "Serving Layer", "rank": 4, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-contract", "theme_id": "th-ingest", "title": "Schema contract + validation", "status": "approved", "rank": 1},
            {"id": "ini-idemp", "theme_id": "th-xform", "title": "Idempotent transform primitives", "status": "approved", "rank": 2},
            {"id": "ini-sloboard", "theme_id": "th-obs", "title": "Freshness SLO dashboard + alerts", "status": "approved", "rank": 3},
            {"id": "ini-backfill", "theme_id": "th-xform", "title": "Backfill runbook + dry-run flag", "status": "proposed", "rank": 4},
        ],
    },
    "mobile": {
        "label": "Mobile App",
        "intent_bullets": [
            "Offline is a feature, not an edge case — every screen has an offline story.",
            "Crashes are critical bugs; targeted crash-free-session rate is a ship criterion.",
            "Every release ships to a staged rollout (1% → 10% → 100%), never 100% day-one.",
            "Platform parity is explicit — features land on both platforms or neither, no \"Android later.\"",
        ],
        "themes": [
            {"id": "th-offline", "name": "Offline & Sync", "rank": 1, "status": "active"},
            {"id": "th-perf", "name": "Startup & Stability", "rank": 2, "status": "active"},
            {"id": "th-release", "name": "Release Pipeline", "rank": 3, "status": "active"},
            {"id": "th-core", "name": "Core Feature Set", "rank": 4, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-sync", "theme_id": "th-offline", "title": "Offline-first data model + sync queue", "status": "approved", "rank": 1},
            {"id": "ini-crash", "theme_id": "th-perf", "title": "Crash reporting + symbolication", "status": "approved", "rank": 2},
            {"id": "ini-rollout", "theme_id": "th-release", "title": "Staged rollout + kill-switch", "status": "approved", "rank": 3},
            {"id": "ini-parity", "theme_id": "th-core", "title": "iOS/Android parity harness", "status": "proposed", "rank": 4},
        ],
    },
    "research": {
        "label": "Research / Exploratory",
        "intent_bullets": [
            "Write-first: if it's not in a doc, it didn't happen.",
            "Time-box every experiment; \"I'll know more in a week\" is a hypothesis, not a plan.",
            "Reproducibility is a ship criterion — someone else should be able to re-run the experiment from the doc alone.",
            "Negative results are fine — \"this doesn't work because...\" is a valid deliverable.",
        ],
        "themes": [
            {"id": "th-question", "name": "Core Questions", "rank": 1, "status": "active"},
            {"id": "th-method", "name": "Methodology", "rank": 2, "status": "active"},
            {"id": "th-writeup", "name": "Write-ups & Deliverables", "rank": 3, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-hypo", "theme_id": "th-question", "title": "Primary hypothesis + kill criteria", "status": "approved", "rank": 1},
            {"id": "ini-protocol", "theme_id": "th-method", "title": "Experiment protocol + dataset", "status": "approved", "rank": 2},
            {"id": "ini-report", "theme_id": "th-writeup", "title": "Report template + weekly update", "status": "approved", "rank": 3},
            {"id": "ini-repro", "theme_id": "th-method", "title": "Reproducibility checklist", "status": "proposed", "rank": 4},
        ],
    },
}


def list_template_names() -> list:
    return sorted(TEMPLATES.keys())


def get_template(name: str):
    return TEMPLATES.get(name)


def render_identity_bullets(template: dict, project_name: str) -> str:
    """Render the Commander's Intent section seeded from a template."""
    bullets = "\n".join(f"- {b}" for b in template["intent_bullets"])
    return (
        f"# {project_name}\n\n"
        f"## What This Is\n\n"
        f"A {template['label']} project. Describe specifics below.\n\n"
        f"## Commander's Intent\n\n"
        f"**Shape: {template['label']}** — seeded from `smithy init --template`.\n\n"
        f"{bullets}\n\n"
        f"**Success looks like**: (fill in)\n\n"
        f"**Tone**: (fill in)\n\n"
        f"**Boundaries**: (fill in)\n\n"
        f"**Not this**: (fill in)\n"
    )
