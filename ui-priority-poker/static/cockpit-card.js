/* t-612 (ini-016): single source of truth for the cockpit 2-line task card.
 *
 * REVERSES t-378's "keep the cockpit/poker rows separate" call. t-599 gave the
 * standalone /cockpit nice 2-line cards (id · initiative · priority · status /
 * desc snippet) but the poker right-rail kept its old single-line rendering, so
 * the two views of the same /api/cockpit data diverged. Both surfaces now build
 * the SAME card face from these helpers, styled by the shared `.c-card-*` rules
 * in static/style.css. Each surface keeps its own chrome: the standalone adds a
 * bulk-select checkbox, an expand chevron, and the defer kebab around the face;
 * the poker rail is click-to-open. Loaded by both index.html and cockpit.html
 * before their inline <script>, so `window.CockpitCard` is available to each.
 */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Initiative cell: a Bellows deep-link when BELLOWS_URL + PROJECT_NAME are on
  // the page (both templates set them), else a muted em-dash. Mirrors the old
  // cockpit iniCellHtml so the two surfaces linkify identically.
  function iniHtml(t) {
    // Both templates publish these globals (cockpit.html since t-599; index.html
    // since t-612). Fall back to the bare names for any other host page.
    var base = (global.COCKPIT_BELLOWS_URL || global.BELLOWS_URL || "")
      .replace(/\/+$/, "");
    var proj = global.COCKPIT_PROJECT_NAME || global.PROJECT_NAME || "";
    if (t.initiative_id && base && proj) {
      return '<a class="c-ini-link" href="' + base + "/project/" +
        encodeURIComponent(proj) + "/initiative/" +
        encodeURIComponent(t.initiative_id) +
        '" target="_blank" rel="noopener">' + esc(t.initiative_id) + "</a>";
    }
    return t.initiative_id ? esc(t.initiative_id) : "—";
  }

  // First line of the description, escaped. Mirrors the old cockpit descPreview.
  function descPreview(t) {
    var first = (t.desc || "(no description)").split("\n")[0];
    return esc(first);
  }

  // Priority pill text — a human override (you:pN) wins over the scheduler's pN.
  function prioText(t) {
    if (t.human_priority != null) return "you:p" + t.human_priority;
    return "p" + (t.priority == null ? "?" : t.priority);
  }

  // The shared line-1 inner spans: id · initiative · priority · status. The id
  // is a plain span carrying data-task-id; each surface wires its own open
  // behaviour (standalone → drawer, rail → in-place detail) via delegation, so
  // the markup stays identical across both.
  function line1Html(t) {
    // t-628 (ini-016): a human-overridden priority gets a pin glyph + the
    // .c-card-prio--pinned accent so the human can scan which tasks they've
    // pinned (the override is the cockpit's primary steering lever).
    const pinned = t.human_priority != null;
    const prioCls = "c-card-prio" + (pinned ? " c-card-prio--pinned" : "");
    const prioTxt = (pinned ? "📌 " : "") + esc(prioText(t));
    return '<span class="c-id" data-task-id="' + esc(t.id) + '">' + esc(t.id) +
      "</span>" +
      '<span class="c-card-ini">' + iniHtml(t) + "</span>" +
      '<span class="' + prioCls + '">' + prioTxt + "</span>" +
      '<span class="c-card-status" data-st="' + esc(t.status || "") + '">' +
      esc(t.status || "") + "</span>";
  }

  // The full self-contained 2-line card (line1 + desc line2). The poker rail
  // drops this straight into its <li>; the standalone composes line1Html with
  // its chrome instead (it needs the expand chevron / kebab interleaved).
  function cardHtml(t) {
    return '<div class="cockpit-card" data-task-id="' + esc(t.id) + '">' +
      '<div class="c-card-line1">' + line1Html(t) + "</div>" +
      '<div class="c-card-l2"><span class="c-desc-preview">' +
      descPreview(t) + "</span></div>" +
      "</div>";
  }

  global.CockpitCard = {
    esc: esc, iniHtml: iniHtml, descPreview: descPreview,
    prioText: prioText, line1Html: line1Html, cardHtml: cardHtml,
  };
})(window);
