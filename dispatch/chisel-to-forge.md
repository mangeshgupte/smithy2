# Dispatch: Chisel -> Forge

Chisel writes design specs here. Forge reads when implementing UI/UX work.

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
