---
name: Prefer structural fixes over symptom patches when a shared-state root cause exists
description: When multiple independent bugs trace back to the same shared resource, fix the sharing, not the individual races
type: feedback
---

When two or more bugs have the same root cause (shared global state, single point of contention), prefer the **structural** fix that eliminates sharing over the **local** fix that patches each symptom. Symptom patches accumulate as protocol debt; structural fixes dissolve entire classes of problems.

**Why:** 2026-04-18 drain incident — four separate install-hazard incidents (t-447, t-448, t-456-retry, t-457-retry) all traced to ONE global editable smithy install shared across all panes. Successive fixes proposed: (1) pin install to main, (2) auto-rebind after every merge, (3) sys.path.insert in every test that introduces a symbol, (4) pre-tick hazard check. Each was locally correct but accumulated protocol burden. Human pointed out: mandate uv-scoped venvs instead. A single architectural decision (per-Assembly venv, later per-Forge venv) eliminates ALL the hazard modes — no global state to race on, no rebind dance, no sys.path tricks, no hazard check needed. t-460 was rewritten from "pin + auto-rebind" to "use uv venv" as a result.

**How to apply:** When reviewing a proposed fix, ask: "what's the underlying resource being shared that caused this bug?" If removing the sharing is tractable, propose that. Symptom patches are appropriate for one-off bugs; they're a warning sign when a third patch is being added to the same class. Specifically for Python environments: one global editable install per project is the shared-state smell; per-venv isolation is the structural answer. The project already defaults to uv — extending that to mandate scoped venvs is a small step with a large payoff.
