# Poker template partials (t-378)

Partials used inside the Poker initiative-card drawer. Included via
`{% include '_partials/_task_row.html' %}` from `index.html`.

## Why no cross-app sharing?

t-378 asked whether `_task_row.html` should be shared across Poker drawer,
Bellows initiative deep-dive, and the Queue Cockpit. Investigation found three
genuinely different shapes:

| UI       | Markup             | Handlers                        | Columns               |
|----------|--------------------|--------------------------------|-----------------------|
| Poker    | `<div.drawer-row>` | `openTaskDetail`, `downrank`    | id/desc/M/reason/HP   |
| Bellows  | `<tr>` (table row) | read-only — click opens drawer  | id/stage/desc/M/HP    |
| Cockpit  | JS-rendered row    | bumpHP/clearHP/toggleDefer      | 10 cols + filter UX   |

Unifying them would require a container/handler/column matrix inside one partial.
Per the "three similar lines is better than a premature abstraction" guidance,
forcing the abstraction now would be net-negative. The partial lives here in its
own folder so future Poker-only partials can join it cleanly. If a second Jinja
consumer ever wants the Poker row verbatim (not a near-copy), we can wire up a
shared template dir then.

## Update — t-612 (ini-016): the Cockpit card IS now shared

t-378's "keep them separate" call held until the shapes converged. t-599 gave the
standalone `/cockpit` a 2-line task card (id · initiative · priority · status /
desc), but the poker right-rail kept its old single-line `cr-*` rendering — so the
two views of the same `/api/cockpit` data diverged. t-612 reverses the **Cockpit**
row of the table above: the cockpit task-card face is now one shared JS renderer,
`static/cockpit-card.js` (`window.CockpitCard`), styled by the shared `.c-card-*`
rules in `static/style.css`. Both the standalone table and the poker right-rail
build the identical card from it; each keeps its own chrome (standalone:
bulk-select + expand + defer kebab; rail: click-to-open).

The Poker **drawer** row (`_task_row.html`, this folder) and the Bellows deep-dive
row stay separate — they're still genuinely different shapes, so t-378's reasoning
still applies to *them*. Only the Cockpit↔rail card converged.
