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
