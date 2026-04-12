# Steering Patterns Retrospective

Companion to `steering-patterns.md` (pre-build). That doc asked *what steering modes exist*; this one asks *what we learned after building all four*. Feeds ini-009.

Scope: Priority Poker (ranking), Constraint Board (boundaries), Timeline View (budget-over-time), Intent Editor (natural-language decomposition). ~80 implementation + testing heats across t-278 → t-299, 66 UI tests, four standalone FastAPI apps writing to a shared `state.json`.

---

## 1. The Shared Substrate Was The Biggest Win

None of the four UIs know about the others. They share nothing but `state.json` on disk (+ SSE mtime watch for live refresh). That decision was made early and should have been louder in the retro from day one, because nearly every desirable property below *falls out of it*.

- **Any UI can be added or removed without touching the others.** Timeline (port 8004) was built last and slotted in with zero changes to Poker/Constraint/Intent.
- **Testing is trivial.** Starlette `TestClient` + a temp `state.json` fixture = full integration coverage, no server, no network. 66 tests run in under 2 seconds.
- **The human can edit `state.json` by hand** and every UI picks it up on next SSE tick. That's the "inspectable state" promise from the protocol made real.
- **Forge is unaware of UIs.** It reads `state.json`. Any steering mode that writes to that file becomes automatically wired in.

**Pattern:** *Treat the state file as the API.* Everything else is a view. This is what "flat files over databases" actually buys you once you commit to it.

**Failure mode avoided:** We never built a message bus between UIs. If we had, adding Timeline would have required a schema negotiation instead of a new folder.

---

## 2. Each UI Encodes A Different Question

The four modes aren't redundant. They answer distinct questions, and which one feels natural depends on how the human is thinking *that session*.

| UI | The question it answers | Input gesture | Best when the human… |
|---|---|---|---|
| Poker | "In what order?" | Drag-reorder cards | …already knows the list, just needs to rank |
| Constraint | "What's out of bounds?" | Add cap/floor/exclude rule | …wants to prevent bad outcomes, not prescribe good ones |
| Intent | "What outcomes do I want?" | Type bullet-markdown | …is starting from zero, only has a fuzzy end-state in mind |
| Timeline | "When does each thing happen?" | Drag bar endpoints | …is thinking in phases or needs to see parallelism/gaps |

Key observation: **no single UI dominates.** In our own dogfooding, Poker got used for daily re-ranking (cheap, one drag), Intent got used exactly once per "sprint" (high ceremony, high impact), Constraint got set up once and rarely touched, Timeline got used for mid-project replanning. Usage frequency is *inverse* to cognitive load — as predicted by the pre-build taxonomy, and now confirmed.

---

## 3. Affordances That Worked

Patterns worth copying into future steering UIs or slash-commands:

- **Rank IS the steering signal** (Poker). No priority numbers, no weights, no tiers — just position in a list. Every other ranking abstraction leaks.
- **Violations as first-class UI state** (Constraint). Red banner when a cap is breached, green when clean. The UI isn't just a form; it's a *status indicator* for whether the current trajectory is legal.
- **Selective apply with checkboxes** (Intent). Auto-decomposition is lossy; letting the human cherry-pick which decomposed items to actually create rescued it from being unusable when the parse went sideways.
- **Draggable endpoints, not draggable bars** (Timeline). Dragging a whole bar is ambiguous (did you move or resize?). Dragging only the endpoints forces the human to state intent. Plus it makes overlap detection meaningful.
- **SSE mtime watch for refresh.** No polling, no websockets, no "are you still there?" heartbeats. File changed → tick. 30 lines of code.
- **`/api/state` on every UI.** Uniform read endpoint means scripts, tests, and future UIs can all poke the same shape. This cost almost nothing and pays off constantly.

---

## 4. Failure Modes We Hit (Or Narrowly Avoided)

- **Port drift.** t-301 had to sweep a mismatch between `STEERING.md` (8081-8084) and the actual `NAV_LINKS` defaults (8001-8004). Four small servers + four docs + one nav bar = five places to forget to update. Pattern: centralize the URL table in one env-var source of truth (`URL_POKER`, `URL_CONSTRAINTS`, …), and have every surface read from it.
- **Persona-cwd spawn bug** (marshal retro, t-303). Not a UI bug, but the same class: when a process resolves config from cwd and cwd is wrong, everything silently loads the wrong identity. Flat-file state has this risk baked in — path resolution is implicit. Solution we actually used: each spawn prompt hard-codes its absolute directory.
- **Auto-decomposition misparsing** (t-293, `_decompose_intent` `.strip()` → `.rstrip()` fix). A one-character bug ate the bullet indentation and silently produced a tree with the wrong nesting. Lesson: parsers that eat human-formatted markdown need a round-trip test (parse → re-render → compare) or they rot invisibly.
- **No conflict resolution between UIs.** If Poker writes rank=1 for A and Timeline simultaneously writes `planned_start=50` for A, both succeed because they touch different fields. If two UIs ever *write the same field*, the last-writer wins and the other UI won't know. We never hit this in practice — but it's a sharp edge under the rug. The right answer is probably optimistic concurrency with an `etag`/mtime precondition on writes, not a lock.
- **Constraint board is easy to forget.** Once you set up floors/caps, there's no reason to re-visit. The UI has no affordance that says "hey, these rules are still active and just prevented 3 heats from happening." A violations-log side-panel would fix this.

---

## 5. When Each Mode Works Best (Prescriptive Summary)

For future project templates / onboarding:

- **Day 1, fuzzy goal:** Start in Intent. Type outcomes. Let decomposition propose themes/initiatives.
- **Day 2+, re-ranking:** Poker. One drag per session is usually all that's needed.
- **Once per project, safety setup:** Constraint. Set stage floors (testing ≥ 20%), stage caps (research ≤ 15 heats), exclusions.
- **Mid-project replanning or phased rollouts:** Timeline. Especially when budget is tight and overlap visibility matters.

The worst anti-pattern: using the wrong UI for the question. E.g., trying to express "don't spend more than 15 heats on research" via Timeline (by drawing a short bar) — the system won't enforce it because Timeline expresses *when*, not *cap*. Constraint is the right tool.

---

## 6. What's Missing (Candidate Tasks For ini-009)

Surfaced for Marshal to triage — none created as tasks here:

1. **Unified violations/activity side-panel** that Poker/Timeline/Intent can all show, populated from Constraint + Forge state. Makes the constraint board's enforcement visible everywhere.
2. **Schema version + mtime precondition** on writes, to fail loudly on concurrent overwrites instead of silently losing a field.
3. **Round-trip test for `_decompose_intent`** (parse → render → parse) to catch regressions in the markdown parser.
4. **"What changed since last heat?" diff view** on Bellows or Poker — currently the human has no way to see that their steering actually shifted Forge's behavior.
5. **Intent template library** beyond the 4 presets — themed templates for common project shapes (library-with-tests, CLI tool, web app).
6. **Steering-to-outcome attribution.** If the human reorders Poker and three heats later a task ships, there's no record that the reorder caused the reprioritization. A lightweight audit in `state.json` (`steering_events[]`) would let us evaluate whether steering actually steers.

---

## 7. Strategic Implications (for Anvil / STRATEGY.md)

- **The shared-file substrate model generalizes beyond steering.** Any future human-facing surface (reviews, annotations, heat-comments, memory-edits) should be a thin UI over a shape in `state.json`, not a new service.
- **Four UIs is probably the right number for now.** Each new UI adds surface area to keep in sync (ports, nav, env vars, docs). The question "should we build a fifth?" should be gated on "does it answer a question none of these four does?" — not on "would this be cool."
- **The modes we didn't build** (Approve/Reject, Chat) are the high-cognitive-load ones. Not building them is a feature, not a gap — it's consistent with the "autonomous, bounded, async" design stance. Re-evaluate only if the human reports wanting real-time course correction.

---

## References

- `STEERING.md` — user-facing docs for all 4 UIs
- `research/steering-patterns.md` — pre-build taxonomy (StarCraft, Mil C2, OKRs, ATC)
- `research/human-ai-interface-synthesis.md` — adjacent framing
- Commits: t-278/279 (Poker), t-281/282 (Constraint), t-283/285 (Intent), t-286/294/298 (Timeline), t-287 (nav), t-288 (docs), t-293 (parse fix), t-301 (port sweep), t-299 (E2E smoke)
