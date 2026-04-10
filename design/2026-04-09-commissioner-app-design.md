# Commissioner App — Design Spec

*2026-04-09 | Chisel*

## What We're Building

A mobile-first operational app for the Commissioner — the human who manages 5-10 AI Forge projects simultaneously. They alternate between catching up ("what happened while I was away?") and steering ("here's what I want next"). They're professionals in the field, often on their phone, making decisions with one thumb.

## Design Principles

1. **The card earns the right to be smaller.** Early-stage projects show more detail and demand more attention. Mature projects compress to a quiet summary.
2. **Forge does the homework.** Every decision presented to the Commissioner comes pre-researched with context, options, and a recommendation. The Commissioner reacts — they don't research.
3. **Forge earns the right to interrupt.** Push notifications are reserved for blocking decisions only. 2-3 per day max across all projects. Everything else is quiet or in-app only.
4. **Voice is first-class.** Every text input has a mic button. Field professionals need to speak, not type.
5. **Six screens, no more.** No hamburger menus, no drawers, no nesting beyond two levels.

---

## Information Architecture

```
LEVEL 1: Global (bottom tab bar, always visible)
[ Home ]    [ Inbox ]    [ Me ]

LEVEL 2: Project (sub-tabs within a project)
[ Activity ]    [ Decide ]    [ Direct ]
```

### Screen Inventory

| Screen | Purpose | Entry |
|--------|---------|-------|
| Morning Briefing | Catch up after absence | Auto on cold open (4+ hrs away) |
| Home / Project Cards | Portfolio overview | Home tab |
| Project Detail | Deep dive, 3 sub-tabs | Tap a card |
| Inbox | Cross-project decision queue | Inbox tab |
| Me / Settings | Preferences, project mgmt | Me tab |
| Heat Detail | Single heat expanded | Tap a heat in Activity |

---

## Screen 1: Morning Briefing

Appears on first open after 4+ hours of inactivity. Dismissable. Accessible later via icon on home screen.

Three sections, strict hierarchy:

### Needs You
Red items only. Decisions and blockers across all projects. Zero items here = great morning.

### Progress
Delta view — what changed since last visit. Shows percentage jumps per project. Projects that didn't move are hidden. The eye catches big jumps and stalls immediately.

### Notable
Forge's editorial judgment. 1-2 items max. Things that aren't decisions but are worth knowing: self-corrections, unexpected findings, anomalies. Section hidden if nothing is notable.

```
Good morning.
7 projects · 42 heats overnight

NEEDS YOU
  AI Tutor — 2 decisions
  Data Pipeline — budget empty since 2am

PROGRESS
  Marketing Site  41% -> 54%
  API Layer       67% -> 71%
  Mobile App      22% -> 38%
  Onboarding      85% -> 88%
  + 2 others on track

NOTABLE
  Mobile App had 3 test failures,
  self-corrected in heat 23. Worth a look.

[Go to projects]
```

---

## Screen 2: Home / Project Cards

Vertical scroll of project cards. One per project.

### Sort Order
Red first, then yellow, then green. Within each color, most-recently-active first. Things that need you float to the top.

### Stoplight Dot
Single most important signal per project.
- Green: running fine
- Yellow: something worth knowing
- Red: blocked or needs you

### Lifecycle-Adaptive Cards

Cards adapt based on project maturity. More detail early, more summary later.

**Early-stage (< 30% done) — tall, demanding:**
```
[Yellow] AI Tutor App
Day 1 · 8 heats used · 12% done

Research  [========--]  80%
Planning  [===-------]  30%
Building  [----------]   0%

Now: Researching spaced repetition frameworks

2 decisions waiting
  * Confirm target audience
  * Approve lesson flow approach

"Should this target kids or adult learners?
 Changes everything downstream."

Budget: 12/50 heats
[============------------------]
```

Includes:
- Stage progress bars (visible until stages pass ~50%)
- Pending decisions expanded inline with preview
- Forge's voice — most important open question in one sentence
- Budget bar shown prominently

**Mid-stage (30-70%) — moderate:**
```
[Green] Marketing Site
Day 3 · 31 heats · 52% done

Now: Building pricing page component

1 decision waiting
  * Pick pricing tier structure

Today: 6 heats · 3 commits
Budget: 31/60 heats
```

Stage bars gone. Decisions still expanded but fewer. Smaller card.

**Mature (70%+) — compact, quiet:**
```
[Green] Data Pipeline
Day 7 · 48 heats · 83% done

Last: "Added retry logic to S3 upload handler"

Today: 4 heats · all green
Budget: 48/55 heats
```

Autopilot mode. Just enough to confirm it's humming.

---

## Screen 3: Project Detail — Activity Tab (default)

Reverse-chronological feed of what Forge did, grouped by time.

### Heat Cards
- One card per heat
- Stage tag color-coded ([implementation], [planning], etc.)
- Default: one-sentence collapsed view
- Tap to expand: full commit message, files changed, self-assessment notes
- File change count shown as "3 files changed"

### Auto-Summarization
Older days roll up into a single summary card. "6 heats, mostly research. Explored 3 spaced rep frameworks, recommended SM-2 variant. You approved." Expandable if needed. Critical for mobile — nobody scrolls through 40 heat cards.

Summaries reference the Commissioner's past decisions: "You approved" connects steering to outcomes.

---

## Screen 4: Project Detail — Decide Tab

Triage queue of decisions Forge can't or shouldn't make alone.

### Decision Cards

Each card contains:
- Priority indicator (red = blocking work now, yellow = will block soon)
- The question in plain language
- Context: why this matters, what it affects
- Forge's recommendation (starred)
- Options as tap targets (buttons)
- Text field with mic icon below buttons for custom answers

```
[RED] HIGH
Who is the target audience?

Kids (8-12) vs adult learners. Affects tone,
session length, vocabulary, and reward mechanics.

I'm leaning adult — the commander's intent says
"professional development" but want to confirm
before I build the lesson shell.

[Adults]  [Kids]

[Or tell me what you want...          mic]
```

### After Deciding
Brief confirmation showing what Forge will do with the answer. 5-minute undo window for fat-thumb protection.

```
Confirmed: Adults
Forge will scope all content for professional
adult learners.
[Undo · 5 min]
```

### Resolved History
"4 resolved this week" — expandable at bottom. Useful for catching drift.

---

## Screen 5: Project Detail — Direct Tab

Proactive steering. The Commissioner came here with something to say.

### Free-Form Input (top)
Text field with mic icon. Type or speak. "Focus on testing for the next 5 heats." "Drop everything and fix the login bug." Forge interprets and acts on the next heat.

### Quick Actions
Four big tap targets for the most common steering moves:

| Action | What it does |
|--------|-------------|
| Run N heats | Start heats. Shows last budget as default, adjustable. |
| Pause | Stop heats immediately. |
| Change priority | Reorder stage weights or focus areas. |
| Add idea | Quick capture to idea pipeline. Voice or text. |

### Commander's Intent
Always visible. Editable. Forge acknowledges changes and explains what shifts.

### Budget
Visual bar + quick-add buttons ([+10 heats] [+25 heats]). No typing.

### Active Tasks
Drag-to-reorder list with handles. Swipe left to remove. Long-press to edit. The Commissioner reprioritizes what Forge works on next without writing instructions.

---

## Screen 6: Inbox — Cross-Project Decision Queue

The Decide tab pulled up to the global level. Every pending decision across every project, sorted by priority, grouped by project.

Decisions are actionable inline — same tap-to-decide interface as the project Decide tab. The Commissioner can clear all blocking decisions in 30 seconds without entering any specific project.

Badge count on the Inbox tab = pending decisions. Same number shows on the app icon.

---

## Notifications

### Three Tiers

| Tier | Delivery | Frequency | Examples |
|------|----------|-----------|---------|
| 1 — Push | Sound + banner | 2-3/day max | Blocking decisions |
| 2 — Quiet | Badge only | Several/day | Run complete, budget empty, stage transitions |
| 3 — In-app | Activity tab only | Many/day | Individual heats, file changes, self-assessment |

### Per-Project Control

Each event type is configurable per project (Push / Quiet / Off). Sensible defaults out of the box. "Mute all · 4 hours" option for focus time.

### Key Principle
If Tier 1 fires more than 2-3 times per day, the Commissioner will mute it and the whole system breaks. Forge must batch non-blocking decisions and only escalate what truly gates progress.

---

## Interaction Patterns

### Voice Input
Every text input has a mic icon. Tap and talk. Forge acknowledges what it understood in natural language before acting. This is a first-class input method for field professionals.

### One-Tap Decisions
Option buttons on decision cards. Most decisions should be resolvable with a single tap — approve Forge's recommendation or pick an alternative.

### Undo Windows
5-minute undo on all decisions. Fat-thumb protection for mobile.

### Auto-Summarization
Anything older than "today" gets rolled up into natural-language summaries. Expandable but collapsed by default.

---

## Open Questions

1. **Offline support?** Field professionals may have spotty connectivity. Do decisions queue locally and sync when back online?
2. **Multi-Commissioner?** Can multiple people steer the same project, or is it 1:1?
3. **Watch/widget?** A complication or widget showing the Inbox badge + top red item could be valuable for quick glances without opening the app.
4. **Haptics?** Subtle haptic feedback on decision taps could reinforce the "I just made a call" feeling.
