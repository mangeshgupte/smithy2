# Dispatch: Chisel -> Forge

Chisel writes design specs here. Forge reads when implementing UI/UX work.

## 2026-04-10 — Design Spec: Tutor Responsive Desktop Layout

### What We're Building
Make Tutor work well on laptops — kids use it at a desk for homework, not just on phones.

### User Flow
No flow changes. Same Learn/Create/Review tabs, same screens. The layout adapts at `>=1024px` to use the wider screen.

### Screen Changes (Desktop Only)

**Navigation**: Bottom tab bar becomes a 72px fixed left sidebar. Vertical icon+label stack. Active tab gets a 3px left teal border instead of a bottom dot. Body shifts right with `margin-left: 72px`.

**Home (Learn)**: Subject cards go from single column to a **2-column grid**. Welcome features go from column to **horizontal row**. Browse-all-topics goes 2-column per subject.

**Lesson Page (The Big Win)**: **Two-panel layout** — concepts/example/manipulatives on the left (40%), exercises on the right (60%). Kids can reference the example while answering questions without scrolling. Use CSS grid with `:has(.exercise-card)` or a `.lesson-page` class on the container.

**Create**: Deck cards go 2-column grid.

**Review Landing**: Stays single column but wider. Stats grid looks fine as-is.

**Review Play**: Card stays centered, max-width 640px. Rating buttons get natural spacing.

**Result**: Centered, wider, no layout change.

### Design Decisions
- **Pure CSS, zero JS changes.** All behind `@media (min-width: 1024px)`. ~65 lines.
- **Mobile unchanged.** Not a single pixel moves below 1024px.
- **Sidebar over top-nav.** Matches learning app conventions (Duolingo, Coursera). Persistent, compact.
- **72px sidebar, not 200px.** Content is king. The nav just needs icons + labels.
- **Container widens to 960px.** From 600px. Enough for 2-col grids without feeling stretched.
- **Lesson 2-panel is the key win.** Everything else is nice-to-have polish. This is the reason to do this work.
- **`:has()` is safe in 2026.** Chrome 105+, Safari 15.4+, Firefox 121+. But a `.lesson-page` class fallback is fine too.

### Full Spec
See `design/2026-04-10-tutor-responsive-desktop.md` for complete CSS specs, ASCII wireframes, and testing checklist.

### Open Questions
1. Should we add a `.lesson-page` class to the container in lesson.html, or rely on `:has(.exercise-card)`? (Class is safer, `:has()` is zero-template-change.)
2. Container max-width: 960px for all pages, or 720px for focused flows (review play, create card author)?

## 2026-04-09 16:00 — Design Spec: Commissioner Mobile App

### What We're Building
A mobile-first operational app for the Commissioner to monitor, steer, and make decisions across 5-10 AI Forge projects from the field.

### Full Spec
See `design/2026-04-09-commissioner-app-design.md` for the complete design document.

### Key Design Decisions
- **Mobile-first, not responsive.** Designed for one-thumb use by field professionals.
- **Lifecycle-adaptive cards.** Early projects show more detail (stage bars, expanded decisions, Forge's voice). Mature projects compress to compact summaries.
- **Three-tier notifications.** Push only for blocking decisions (2-3/day max). Quiet badges for status changes. In-app only for routine activity.
- **Voice is first-class.** Every input has a mic button. Not an afterthought.
- **Six screens total.** Morning Briefing, Home, Project Detail (3 sub-tabs), Inbox, Me, Heat Detail.
- **Morning Briefing.** Auto-shows after 4+ hours away. Three sections: Needs You, Progress (deltas), Notable (Forge's editorial judgment).
- **Cross-project Inbox.** Global decision queue — clear all blocking decisions in 30 seconds without entering individual projects.

### Open Questions
1. Offline support for spotty field connectivity?
2. Multi-Commissioner support on a single project?
3. Watch/widget for quick glance without opening app?
4. Haptic feedback on decision taps?
