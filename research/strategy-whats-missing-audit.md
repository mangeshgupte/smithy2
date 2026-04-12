# STRATEGY.md "What's Missing" — Audit (t-358)

**Date:** 2026-04-12, heat 777
**Context:** The `What's Missing` list in `STRATEGY.md` was last curated at roughly v0.4 scale (~150 heats in). The smithy now sits at heat 777 with v1.10 shipped. Every item deserves a re-verdict: still real, shipped, or superseded by a different design.

---

## The list today

```
- Tutor: offline card caching (PWA service worker)
- Tutor: "teach it back" mode (unlocks after mastery)
- Repo map for non-dogfood projects (t-044)
- Lint→test→fix loop (t-045)
- Self-critique / Reflexion (t-046)
- WhatsApp messaging bridge — deferred to v0.7+
- Semantic memory store (vector DB) — v0.8
- Parallel heats via sub-agents — v0.9
```

---

## Verdict per item

### 1. Tutor: offline card caching (PWA) — **SHIPPED**

Service worker + manifest + offline route shipped in v1.2. Commit `489f740` (research design), `e274b0b` (testing verifies manifest/SW/offline all 200). Remove.

### 2. Tutor: "teach it back" mode — **SHIPPED**

Feature lives under "Teach It Back" in Tutor. Commit `ba78486` + `eb60092` ("Teach It Back promoted", "Teach It Back prominence"). Remove.

### 3. Repo map for non-dogfood projects (t-044) — **SHIPPED**

Commit `5c24f3f`: `t-044: forge-repomap.sh — auto-generates repo map for new project orientation`. Remove.

### 4. Lint→test→fix loop (t-045) — **SHIPPED**

Commit `e6baa5f`: `t-045: Lint→test→fix loop — run tests before commit, fix failures in-heat`. Remove.

### 5. Self-critique / Reflexion (t-046) — **SHIPPED**

Commit `03b29af`: `t-046: Self-critique (Reflexion) protocol — review before commit, catch bugs, check intent alignment`. Remove.

### 6. WhatsApp messaging bridge — **SUPERSEDED**

Messaging has been re-framed since v0.4. Bellows + nudge queues + Agent Teams `SendMessage` cover async human↔persona and persona↔persona communication without external transport. A WhatsApp bridge is no longer on the critical path — it's a "nice extra surface" rather than missing infrastructure. Drop from `What's Missing`; keep as a future-surface idea in `inbox.md` if anyone still wants it.

### 7. Semantic memory store (vector DB) — **SUPERSEDED**

v0.4 assumed memory would need vector search. v1.x memory is built from CLAUDE.md, `MEMORY_DAILY.md`, `MEMORY_WEEKLY.md`, per-project `state.json` + `worklog.tsv` + `steering.log`. This is all grep-able flat text. The question "what did we learn?" is answered by retros (`smithy steering-retro`) and memory consolidation, not by vector similarity. Promote a vector DB only if a concrete retrieval miss motivates it; otherwise drop.

### 8. Parallel heats via sub-agents — **SUPERSEDED**

Agent Teams replaced this idea. Anvil spawns Marshal + Forge as teammates (decision H7 in v1.8 retro; STRATEGY.md §7). Parallelism at "heat" granularity was the wrong seam — parallelism at "persona" granularity is what shipped and works. A second Forge heat running concurrently is still theoretically possible, but cost/benefit hasn't argued for it given that heats are already ~5 minutes and commits are the synchronization unit. Drop from `What's Missing`; add as "Open question" under §Main Ideas if we revisit.

---

## What's actually missing now (revised list)

After retiring the shipped + superseded items, what's a real gap today?

1. **Full-log browser surface.** Activity side-panel ships 20 entries; "view full log →" currently deep-links to raw JSON. Want a rendered timeline / filterable view for retros longer than a session.
2. **Cross-project activity view.** Bellows shows per-project activity feeds; it doesn't merge them. A portfolio-level "what happened across all my Forges today" surface isn't built.
3. **Steering intent validation.** No surface answers "did my pin actually change what Forge worked on, or was Forge going to do it anyway?" The retro counts pin→ship but can't distinguish counterfactual. Needs either (a) a baseline/shadow mode, or (b) a "had you not pinned, next-up would have been X" annotation at pin time.
4. **Idle-state UX.** When the queue is empty and Forge is idle, no UI conveys *why* (budget exhausted, waiting for Marshal, no intent defined). A banner on Poker + Bellows would close the loop.
5. **Feedback.md → action loop closure.** Feedback is read at heat-top but there's no explicit "here's what we changed in response" surface. Users writing feedback can't easily see it was acted on vs buried.

These replace the old 8. Each is a plausible p2-p3 depending on demand.

---

## Proposed STRATEGY.md edit

Replace the existing `### What's Missing` block with:

```markdown
### What's Missing

- **Full-log browser surface** (extends activity side-panel beyond 20 entries)
- **Cross-project activity view** in Bellows (portfolio-level merge)
- **Steering intent validation** — counterfactual framing for pin/reorder
- **Idle-state UX** — explain *why* when queue empty / Forge idle
- **Feedback loop closure** — surface "what changed" in response to feedback.md

_Prior list (PWA, teach-it-back, t-044/t-045/t-046, vector DB, parallel heats, WhatsApp) shipped or superseded — audited in research/strategy-whats-missing-audit.md (t-358)._
```

---

## Impl candidates (retro format — value thesis per)

### t-361-candidate — STRATEGY.md inline edit (editing, p3)
Apply the proposed block above in one heat. Trim the shipped items and add the 5 new ones. Update any cross-references in README/WALKTHROUGH if they pointed at the old list.

**Value thesis:** The list is a compass. Keeping it full of done-items makes every `What's Missing` re-read a noise-filter exercise. One heat of editing improves every future planning heat by reducing lookup latency.

### t-362-candidate — Full-log browser surface (impl, p3)
A paginated rendered view of `/api/activity` (the existing endpoint already caps at 500). One template, one route; keeps the side-panel link functional past 20 entries.

**Value thesis:** Closes the obvious side-panel cliff. Cost: ~1 heat. No backend work; all data already exposed.

### t-363-candidate — Idle-state banner (impl, p3)
A small banner on Poker (+ Bellows project header) that surfaces one of: `queue empty, waiting on Marshal`, `budget exhausted at heat N`, `no intent — write some in Intent Editor`. Reads `state.json` + nudge-queue dir. 

**Value thesis:** Today an idle Forge is silently confusing. The banner makes idleness self-diagnosing. High ratio of clarity-gained to code-written.

### t-364-candidate — Cross-project activity feed in Bellows (impl, p3)
Merge all `steering.log` + worklog tails across projects in `FORGE_PROJECTS_DIR`, render on the Bellows dashboard. Reuses `smithy.activity.read_activity` per project; concat + sort.

**Value thesis:** Scales the side-panel's "what's happening" answer to portfolio-level. Only useful once someone has ≥2 Forges running; park until that's true.

### t-365-candidate — Feedback loop closure view (impl/editing, p3, research first)
Surface acted-on feedback on Poker's activity panel or Intent Editor. Needs a lightweight convention (e.g., `smithy ack-feedback <n>` writes a steering.log row with `source=feedback-ack`). Design heat first, then impl.

**Value thesis:** Unclear whether the gap is real or only theoretical — nobody has complained about feedback being silently ignored. Research-first gates the cost correctly.

---

## Recommendation

**Ship t-361 standalone** (editing, 1 heat) — immediate cleanup win, no risk.
**Queue the other four at p3** — each a "real gap" per the audit but none urgent enough to bump the activity-panel Timeline/click-to-jump follow-ups (t-359/t-360).

One-line summary for Marshal: 5/8 "missing" items are shipped, 3 are superseded, 5 new gaps surfaced. Ready to land the STRATEGY edit anytime.
