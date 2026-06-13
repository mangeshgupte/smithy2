# Daily Memory

## 2026-06-12

- [h1326 implementation] Before extending a 'follow-up to t-NNN' task, read t-NNN's merged code first — the predecessor often already did the part the follow-up ticket lists. t-518 (per-task touches) listed 'update the scorer' as item 3, but t-517 had already wired dispatch._effective_touches (task-level override → initiative fallback) and conflict_risk_score uses it. The real t-518 work was just the CLI input (add-task --touches) + schema + tests, not the scorer. Saves a heat of redundant work and prevents conflicting reimplementation.
