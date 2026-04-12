# Intent Template Library — Seed Shapes for New Forge Projects

**Task:** t-336 (research, p2). The v1.8 steerability arc made intent legible per-project. A new user spinning up Forge faces a blank `identity.md` and `state.json` — no guidance on what "themes" or "initiatives" look like for *their* shape of project. This doc catalogs 6 templates covering the common project shapes, each with an intent skeleton, a seed theme/initiative map, and a one-paragraph value thesis.

Each template is copy-pastable into a fresh `identity.md` (intent section) and `state.json` (themes + initiatives seed). Users edit, not invent.

---

## Template 1 — Library / SDK

**Shape:** a reusable package someone else will depend on. Success = adoption + semver discipline. Risk = API churn burns users.

**Intent bullets (for `identity.md`):**
- Ship a stable, documented package that solves ONE problem well.
- Optimize for the caller's ergonomics, not the author's convenience.
- Treat every exported symbol as a contract — breaking changes need major-version bumps.
- Version v1.0 means "I'm willing to be stuck with this API for a year."

**Seed theme/initiative map:**
```yaml
themes:
  - {id: th-api,    name: "API Surface",    rank: 1, status: active}
  - {id: th-docs,   name: "Docs & Examples", rank: 2, status: active}
  - {id: th-tests,  name: "Test Coverage",   rank: 3, status: active}
initiatives:
  - {id: ini-core,  theme_id: th-api,   title: "Core types + happy-path API",      status: approved, rank: 1}
  - {id: ini-errs,  theme_id: th-api,   title: "Error model + failure semantics",  status: proposed, rank: 2}
  - {id: ini-readme, theme_id: th-docs, title: "README + quickstart example",      status: approved, rank: 3}
  - {id: ini-cov,   theme_id: th-tests, title: "95%+ unit coverage on core path",  status: approved, rank: 4}
```

**Value thesis:** Library authors chronically under-invest in docs + error UX and over-invest in features. This template front-loads the two things that adopters actually evaluate on day-one (README quality + error messages), and makes "stable API" a first-class theme so scope creep in v0.x shows up as measurable drift from the target.

---

## Template 2 — CLI Tool

**Shape:** a binary that takes args, does work, prints output. Success = someone types the command from memory on day 30. Risk = flag explosion, unclear subcommand hierarchy.

**Intent bullets:**
- Default behavior should be useful — zero flags required for the common case.
- Every subcommand fits on one line of `--help`.
- Exit codes are promises: 0 = good, non-zero = actionable diagnostic on stderr.
- No interactive prompts unless explicitly requested; scripts depend on silent success.

**Seed theme/initiative map:**
```yaml
themes:
  - {id: th-ux,     name: "Command UX",        rank: 1, status: active}
  - {id: th-io,     name: "Input/Output",      rank: 2, status: active}
  - {id: th-dist,   name: "Distribution",      rank: 3, status: active}
initiatives:
  - {id: ini-subcmd, theme_id: th-ux,  title: "Subcommand tree (verb-noun)",         status: approved, rank: 1}
  - {id: ini-help,   theme_id: th-ux,  title: "--help output on every command",      status: approved, rank: 2}
  - {id: ini-stdio,  theme_id: th-io,  title: "stdin/stdout pipe-friendliness",      status: proposed, rank: 3}
  - {id: ini-install, theme_id: th-dist, title: "One-line install (brew/curl/pipx)", status: proposed, rank: 4}
```

**Value thesis:** CLIs live or die on how quickly the first invocation works — the "clone, read README, type command, see result in <60s" loop. This template prioritizes subcommand hierarchy (hardest to change later) and --help quality over feature breadth. Distribution is explicitly a theme, not an afterthought, because `pip install` vs `brew install` vs "clone and build" each kill a different adopter segment.

---

## Template 3 — Web App (product)

**Shape:** a user-facing site with auth, persistence, multiple pages. Success = DAU retention + a sub-2s page load. Risk = framework sprawl, premature component libraries, auth edge cases.

**Intent bullets:**
- Ship the golden-path flow end-to-end before polishing any single screen.
- Auth is a foundation, not a feature — get it right once, stop touching it.
- Server-rendered HTML first; reach for SPA patterns only when interactivity requires them.
- No "admin tools" built in the product until the product has users.

**Seed theme/initiative map:**
```yaml
themes:
  - {id: th-golden, name: "Golden-path flow",    rank: 1, status: active}
  - {id: th-auth,   name: "Auth & Accounts",     rank: 2, status: active}
  - {id: th-perf,   name: "Performance",         rank: 3, status: active}
  - {id: th-ops,    name: "Deployment & Ops",    rank: 4, status: active}
initiatives:
  - {id: ini-signup, theme_id: th-auth,   title: "Signup → email verify → first session", status: approved, rank: 1}
  - {id: ini-onboard, theme_id: th-golden, title: "First-run onboarding to aha-moment",   status: approved, rank: 2}
  - {id: ini-nav,    theme_id: th-golden, title: "Primary nav + 3 core pages",             status: approved, rank: 3}
  - {id: ini-deploy, theme_id: th-ops,    title: "CI → staging → prod pipeline",           status: proposed, rank: 4}
```

**Value thesis:** Web apps fail at the golden path, not at the edges — most new-app code focuses on one beautiful page while signup is broken on Safari. This template forces auth-and-onboarding to be theme 1-2 so they can't be skipped, and bakes deployment in from the start so "it works on my laptop" never becomes a two-week fire drill.

---

## Template 4 — Data Pipeline

**Shape:** scheduled ingest → transform → serve. Success = fresh data lands correctly every run, observability is enough that failures page someone before users notice. Risk = silent data loss, schema drift in upstream sources.

**Intent bullets:**
- Idempotent by default — re-running a job must be safe, not a double-write.
- Schema expectations are asserted, not assumed; upstream changes fail loud, not silent.
- Freshness SLO is a first-class metric; dashboards show "last successful run" before anything else.
- Backfill is a required path, not a one-off script.

**Seed theme/initiative map:**
```yaml
themes:
  - {id: th-ingest, name: "Ingest & Schema",   rank: 1, status: active}
  - {id: th-xform,  name: "Transform Logic",   rank: 2, status: active}
  - {id: th-obs,    name: "Observability",     rank: 3, status: active}
  - {id: th-serve,  name: "Serving Layer",     rank: 4, status: active}
initiatives:
  - {id: ini-contract, theme_id: th-ingest, title: "Schema contract + validation",       status: approved, rank: 1}
  - {id: ini-idemp,    theme_id: th-xform,  title: "Idempotent transform primitives",    status: approved, rank: 2}
  - {id: ini-sloboard, theme_id: th-obs,    title: "Freshness SLO dashboard + alerts",   status: approved, rank: 3}
  - {id: ini-backfill, theme_id: th-xform,  title: "Backfill runbook + dry-run flag",    status: proposed, rank: 4}
```

**Value thesis:** Data pipelines that skip observability upfront accumulate silent failures for months — "the numbers look off" discovered too late. This template makes freshness SLO a theme, not a nice-to-have, and makes idempotency + schema contracts initiative-1 because they're the two things that cause 80% of production pages.

---

## Template 5 — Mobile App

**Shape:** native or cross-platform app with local state, offline-tolerant UX, app-store release cadence. Success = 4.5★+ store rating, <1% crash-free session loss, weekly release cadence. Risk = offline-state bugs, platform-specific quirks (iOS vs Android), review-cycle whiplash.

**Intent bullets:**
- Offline is a feature, not an edge case — every screen has an offline story.
- Crashes are critical bugs; targeted crash-free-session rate is a ship criterion.
- Every release ships to a staged rollout (1% → 10% → 100%), never 100% day-one.
- Platform parity is explicit — features land on both platforms or neither, no "Android later."

**Seed theme/initiative map:**
```yaml
themes:
  - {id: th-offline, name: "Offline & Sync",    rank: 1, status: active}
  - {id: th-perf,    name: "Startup & Stability", rank: 2, status: active}
  - {id: th-release, name: "Release Pipeline",  rank: 3, status: active}
  - {id: th-core,    name: "Core Feature Set",  rank: 4, status: active}
initiatives:
  - {id: ini-sync,    theme_id: th-offline, title: "Offline-first data model + sync queue", status: approved, rank: 1}
  - {id: ini-crash,   theme_id: th-perf,    title: "Crash reporting + symbolication",       status: approved, rank: 2}
  - {id: ini-rollout, theme_id: th-release, title: "Staged rollout + kill-switch",           status: approved, rank: 3}
  - {id: ini-parity,  theme_id: th-core,    title: "iOS/Android parity harness",             status: proposed, rank: 4}
```

**Value thesis:** Mobile apps fail most often not at features but at the seams — offline transitions, crash recovery, staged releases. This template elevates offline + stability to the top two themes so they cannot be deferred into "later." Platform parity as an explicit initiative forces the "Android later" conversation to happen at plan time, not three months in.

---

## Template 6 — Research / Exploratory

**Shape:** open-ended investigation — "does approach X work?", "what patterns emerge in dataset Y?". Success = ship a report others can act on, not code that runs. Risk = endless rabbit holes, no written output, results that don't transfer to anyone else.

**Intent bullets:**
- Write-first: if it's not in a doc, it didn't happen.
- Time-box every experiment; "I'll know more in a week" is a hypothesis, not a plan.
- Reproducibility is a ship criterion — someone else should be able to re-run the experiment from the doc alone.
- Negative results are fine — "this doesn't work because..." is a valid deliverable.

**Seed theme/initiative map:**
```yaml
themes:
  - {id: th-question, name: "Core Questions",    rank: 1, status: active}
  - {id: th-method,   name: "Methodology",       rank: 2, status: active}
  - {id: th-writeup,  name: "Write-ups & Deliverables", rank: 3, status: active}
initiatives:
  - {id: ini-hypo,    theme_id: th-question, title: "Primary hypothesis + kill criteria", status: approved, rank: 1}
  - {id: ini-protocol, theme_id: th-method,  title: "Experiment protocol + dataset",     status: approved, rank: 2}
  - {id: ini-report,  theme_id: th-writeup,  title: "Report template + weekly update",    status: approved, rank: 3}
  - {id: ini-repro,   theme_id: th-method,   title: "Reproducibility checklist",          status: proposed, rank: 4}
```

**Value thesis:** Research projects fail silently — weeks of work produce no durable artifact, findings evaporate with the researcher. This template makes the write-up a theme from heat 1 and bakes in kill criteria at the hypothesis level so "let me keep exploring for just one more week" becomes a decision, not a default. Reproducibility as an initiative flags the fact that most research code, left alone, is unrunnable within 6 months.

---

## Cross-cutting notes

**What these templates share:**
- Themes are 3-4 max. More themes means the user hasn't chosen yet.
- The top-ranked theme in every template corresponds to the *highest-risk failure mode* for that shape — auth for web apps, schema for pipelines, offline for mobile.
- Each template's first initiative is a foundation-layer item (not a feature), because Forge tends to over-produce features and under-produce foundations.

**What these templates do NOT include:**
- No task-level seeds. Tasks are generated from initiatives at plan time, and locking them here would ossify too early.
- No constraints seeds. Constraints emerge from the project's specifics (deadlines, team size, tech stack), not the shape.
- No initiative-level budget caps. Those should come from the user's total budget + intent, not a template default.

**When to pick a template:** users run `smithy init <shape>` (future feature) or copy the block manually from this doc into their `identity.md` + `state.json`. The template is a *starting point*, not a cage — every element is editable.

---

## Future work (out of scope for this heat)

- `smithy init --template=lib|cli|web|pipe|mobile|research` scaffolding — would bump each template to live code, not just docs.
- A 7th template for "infra / internal tools" (monitoring stacks, internal dashboards). Distinct shape — no external users, different success criteria.
- A template meta-thesis: write one paragraph per template explaining *why* users pick one vs another. This doc gets users to a shape; a meta-thesis would get users to *their* shape.

## Recommendation summary

**Ship order for coverage:** lib + CLI + web are the 80% of new Forge projects; land those polished first. Pipeline + mobile + research serve the 20% tail, but the variance in those shapes is high enough that the seed value is disproportionate. Recommend shipping all 6 as one doc to avoid implied hierarchy.

**Next task candidate:** `smithy init --template=<shape>` CLI command that materializes the chosen template into `identity.md` + `state.json`. Low-risk, small diff, testable. Would turn this doc from reference material into executable scaffolding.
