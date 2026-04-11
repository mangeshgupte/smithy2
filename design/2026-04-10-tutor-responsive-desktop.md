# Design Spec: Tutor Responsive Desktop Layout

**Date**: 2026-04-10
**Author**: Chisel
**Status**: Ready for implementation

## Problem

Tutor is optimized purely for mobile — 600px max-width, bottom tab bar, single column. On a laptop screen it's a narrow strip floating in gray space. Kids doing homework on a laptop get a worse experience than on their phone.

## Goal

Make Tutor work well on both mobile and laptop with a single CSS-only responsive layer. Zero template changes. All new styles behind `@media (min-width: 1024px)`.

**Mobile stays exactly the same.** No regressions.

---

## Design System: Desktop Breakpoint

### New breakpoint: `@media (min-width: 1024px)`

Everything below is scoped to this breakpoint. Below 1024px, current mobile/tablet styles apply unchanged.

---

## 1. Navigation: Bottom Tab Bar -> Left Sidebar

The bottom tab bar becomes a fixed left sidebar on desktop.

### Layout

```
┌────────┐
│        │
│   📖   │   <- icon 24px
│  Learn │   <- label 11px
│        │
│   ✏️   │
│ Create │
│        │
│   🔄   │
│ Review │
│   3    │   <- badge stays, repositioned
│        │
│        │
│        │
│        │
│  🎓    │   <- app logo/icon at bottom (optional)
└────────┘
```

### CSS Spec

```
.tab-bar {
    /* Override mobile fixed-bottom */
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    right: auto;               /* was: right: 0 */
    width: 72px;
    flex-direction: column;    /* was: row */
    justify-content: flex-start;
    padding: 24px 0 0 0;      /* was: 8px 0 ... */
    border-top: none;
    border-right: 1px solid var(--border);
    gap: 8px;
}

.tab {
    padding: 12px 0;          /* was: 4px 20px */
    font-size: 11px;          /* same */
}

.tab.active {
    /* Left accent bar instead of bottom dot */
    /* Remove the ::after dot, use box-shadow or border-left */
}

.tab.active::after {
    display: none;            /* Remove bottom dot on desktop */
}

.tab.active {
    border-left: 3px solid var(--indigo);
    background: rgba(0, 188, 212, 0.06);
}

/* Shift body content right */
body {
    padding-bottom: 0;        /* was: 72px */
    margin-left: 72px;
}
```

### Badge

The `.tab-badge` repositions to sit inside the icon area (same visual treatment, just relative to the vertical layout).

---

## 2. Container: Widen for Desktop

```
.container {
    max-width: 960px;         /* was: 600px / 720px tablet */
    padding: 32px;            /* was: 16px / 24px tablet */
}
```

---

## 3. Home Page: Subject Cards Grid

### Current: single column stack
### Desktop: 2-column grid

```
┌──────────────────┐ ┌──────────────────┐
│ 🐍 Python        │ │ 🔢 Singapore Math│
│ 3/10 topics      │ │ 0/14 topics      │
│ ████░░░░ 30%     │ │ ░░░░░░░░ 0%      │
│ Continue →       │ │ Start Learning → │
└──────────────────┘ └──────────────────┘
┌──────────────────┐ ┌──────────────────┐
│ 📝 English Vocab │ │ 🧩 Logic         │
│ 2/7 topics       │ │ 1/7 topics       │
│ ███░░░░░ 28%     │ │ █░░░░░░░ 14%     │
│ Continue →       │ │ Continue →       │
└──────────────────┘ └──────────────────┘
```

### CSS Spec

```
.subject-list {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;                /* was: 16px in flex column */
}
```

Cards fill available width naturally. Subject icon, header, progress bar, and CTA all stay the same — they just have more horizontal room.

---

## 4. Welcome Card: Features Row

The 3 welcome features (Socratic lessons, Your flashcards, Spaced review) become a horizontal row instead of stacking.

```
┌──────────────────────────────────────────────────┐
│ Learn by Doing                                   │
│ Your AI tutor teaches through questions...       │
│                                                  │
│  📖 Socratic     ✏️ Your          🔄 Spaced      │
│     lessons        flashcards       review       │
│  Learn through   Write cards in   SM-2 algo      │
│  guided Qs       your own words   remembers      │
└──────────────────────────────────────────────────┘
```

### CSS Spec

```
.welcome-features {
    flex-direction: row;       /* was: column */
    gap: 24px;
}

.welcome-feature {
    flex: 1;
    text-align: center;
}
```

---

## 5. Subject Page: Topic List Widens

The topic list stays single column (it's a sequential progression — grid would break the flow). But with the wider container, each topic card gets more breathing room.

The action buttons on completed topics (🔄 ✏️ 🎓) spread out more naturally with the extra width. No layout change needed — flexbox handles it.

The header action buttons (Start Study Session, Stats, Due badge) stay in a row — with more width they won't wrap.

---

## 6. Lesson Page: Two-Panel Layout (The Big Win)

This is the most impactful change. On desktop, the lesson splits into two panels:

**Left panel (40%)**: Key Concepts + Example + Manipulatives + Socratic Questions
**Right panel (60%)**: Practice exercises (scrollable independently)

```
┌──────────────────────────────────────────────────┐
│ ← Variables & Assignment                          │
├─────────────────────┬────────────────────────────┤
│                     │                            │
│ 📖 Key Concepts     │  ✏️ Practice               │
│ • Variables store   │  ┌────────────────────┐    │
│   values in memory  │  │ Variables    2 of 5│    │
│ • Use = to assign   │  │ ████░░░░░░░░░░░░░ │    │
│ • Names must start  │  │                    │    │
│   with a letter     │  │ What does the      │    │
│                     │  │ following print?   │    │
│ Example:            │  │                    │    │
│ ┌─────────────────┐ │  │ x = 10             │    │
│ │ name = "Alice"  │ │  │ print(x + 5)       │    │
│ │ age = 10        │ │  │                    │    │
│ │ print(name)     │ │  │ [_______________]  │    │
│ └─────────────────┘ │  │                    │    │
│                     │  │ [Check]  💡 Hint   │    │
│ 💭 Think About This │  └────────────────────┘    │
│ ▸ Why do we need... │                            │
│ ▸ What happens if.. │  ┌────────────────────┐    │
│                     │  │ Variables    3 of 5│    │
│                     │  │ ...                │    │
│                     │  └────────────────────┘    │
└─────────────────────┴────────────────────────────┘
```

### Why This Matters

On mobile, kids scroll down from concepts → example → exercises. If they forget something, they scroll back up. On desktop, the reference material is **always visible** next to the practice. This is the #1 advantage of having a wider screen for learning.

### CSS Spec

This requires a structural approach. The lesson page has multiple `.lesson-section` elements in sequence. On desktop, we wrap them differently.

**Strategy**: Use CSS to create the two-panel layout without changing HTML. The lesson content is a series of `.lesson-section` blocks. We can use CSS grid on the `.container` (or a wrapper) where the concepts/example sections go left and the practice section goes right.

**Implementation approach — CSS-only using `display: grid` on the content area**:

```
/* Lesson page uses a body class or the existing structure */
/* The lesson template has sections in this order:
   1. .page-header (full width)
   2. .lesson-section "Key Concepts" 
   3. .lesson-section "Example"
   4. .lesson-section "See It" (manipulatives, optional)
   5. .lesson-section "Think About This" (socratic, optional)
   6. .lesson-section "Practice"
*/

/* Add a body class via template to target lesson pages */
/* OR use the existing structure with :has() */

/* Target: make the lesson content a 2-col grid */
.container:has(.exercise-card) {
    display: grid;
    grid-template-columns: 2fr 3fr;
    gap: 0 32px;
    align-items: start;
}

/* Header spans full width */
.container:has(.exercise-card) .page-header {
    grid-column: 1 / -1;
}

/* Concepts, Example, Manipulatives, Socratic → left column */
/* Practice → right column */
/* The last .lesson-section (Practice) takes the right column */
.container:has(.exercise-card) .lesson-section:last-child {
    grid-column: 2;
    grid-row: 2 / span 10;   /* span many rows to fill */
    position: sticky;
    top: 32px;
    max-height: calc(100vh - 64px);
    overflow-y: auto;
}

/* All other lesson-sections stay in column 1 */
.container:has(.exercise-card) .lesson-section:not(:last-child) {
    grid-column: 1;
}
```

**Note on `:has()` support**: Works in all modern browsers (Chrome 105+, Safari 15.4+, Firefox 121+). For a kids' learning app in 2026, this is safe.

**Alternative if `:has()` is too risky**: Add a `lesson-layout` class to the container in `lesson.html` template. This is the ONE template change we'd accept — adding a class to a div.

### Sticky Left Panel

The left column (concepts) should be `position: sticky; top: 32px` so it stays visible as the user scrolls through exercises on the right. The exercises column scrolls naturally.

Actually, flip this: make the **right column (exercises)** sticky if there are many exercises, or let both scroll naturally. The key insight is that with the 2-col layout, concepts are always a quick glance to the left — no scrolling back up.

**Best approach**: Both columns scroll naturally. The left column is shorter, so it effectively stays pinned as the user scrolls through exercises. No need for `position: sticky` complexity.

---

## 7. Result Page: Centered, Wider

The result card (correct/incorrect feedback) stays centered, single column. Just gets more breathing room with the wider container. The result-actions buttons stay in a row and have more space.

No layout changes needed.

---

## 8. Review Play: Centered Card

Flashcard review is a focused, one-card-at-a-time flow. It should stay centered and not get too wide.

```
.review-card {
    max-width: 640px;
    margin: 0 auto;
}
```

The rating buttons (Forgot/Hard/Good/Easy) get more horizontal space. They already use flexbox — they'll spread naturally.

---

## 9. Review Landing: Stats + Chart Side by Side

```
┌──────────────────────────────────────────────────┐
│ Review                                           │
│                                                  │
│  ┌─────┐ ┌─────┐ ┌─────┐                        │
│  │  5  │ │  3  │ │ 24  │    🔥 3 day streak!    │
│  │ due │ │done │ │total│                         │
│  └─────┘ └─────┘ └─────┘                        │
│                                                  │
│  [Start Review]                                  │
│                                                  │
│  ┌─ This Week ─────────┐ ┌─ By Subject ────────┐│
│  │  █                  │ │ 🐍 Python    2 due  ││
│  │  █   █              │ │ 🔢 Math      3 due  ││
│  │  █   █       █      │ │ 📝 English   Clear  ││
│  │  █   █   █   █      │ │ 🧩 Logic     Clear  ││
│  │ Mon Tue Wed Thu     │ │                     ││
│  └─────────────────────┘ └─────────────────────┘│
└──────────────────────────────────────────────────┘
```

### CSS Spec

```
/* Weekly chart + subject breakdown side by side */
/* Wrap them in a grid or use flex */
/* These are currently sequential sections — use CSS grid on container */

/* Review landing: chart and subject list side by side */
.review-stats-grid {
    /* Already 3 columns — fine as is, just wider */
}

/* The weekly chart and subject breakdown could go side by side,
   but they're separate <section> elements. Use a parent grid
   or just let them stack wider. Stacking is fine — the content
   doesn't benefit much from side-by-side. */
```

Actually, for review landing — just widening to 720px max and keeping single column is better. The weekly chart and subject breakdown are both full-width elements that look good stacked. Side-by-side would make them too compressed.

```
/* Review/Create pages: centered, moderate width */
/* These are focused flows, not dashboards */
```

The wider container (960px) might be too wide for review. Consider keeping review and create at 720px centered:

```
/* On pages that don't benefit from full width */
.review-complete,
.review-card {
    max-width: 640px;
    margin-left: auto;
    margin-right: auto;
}
```

---

## 10. Create Page: Deck Grid

The deck list can go 2-column, like subject cards on the home page.

```
.deck-list {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
}
```

---

## 11. Browse All Topics: Multi-Column

The "Browse all topics" `<details>` section at the bottom of the home page. The topic links within each subject can flow into 2 columns.

```
.browse-topics {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
}
```

---

## 12. Code Input: Wider + Taller

Python code textareas benefit the most from desktop width. With the 2-panel lesson layout, the exercise panel is ~55% of 960px = ~530px. Much better than the current 600px - 32px padding = 568px (similar, but now it's beside concepts, not below them).

On the result page or any full-width code display:

```
.code-input {
    min-height: 120px;        /* was: rows="6" ~96px */
    font-size: 14px;
}

.example-block {
    font-size: 14px;
    padding: 16px;
}
```

---

## Summary of CSS Changes

All behind `@media (min-width: 1024px)`:

| Component | Change | Lines of CSS |
|-----------|--------|-------------|
| `.tab-bar` | Bottom → left sidebar, 72px wide | ~20 lines |
| `body` | Remove bottom padding, add left margin | 3 lines |
| `.container` | max-width 960px, padding 32px | 2 lines |
| `.subject-list` | Flex column → 2-col grid | 3 lines |
| `.welcome-features` | Column → row | 3 lines |
| `.lesson-section` (lesson page) | 2-panel grid layout | ~15 lines |
| `.deck-list` | Flex column → 2-col grid | 3 lines |
| `.browse-topics` | 1-col → 2-col grid | 3 lines |
| `.review-card` | Centered max-width | 2 lines |
| `.tab.active` | Dot → left border accent | 5 lines |
| Code inputs | Wider/taller defaults | 4 lines |

**Total**: ~65 lines of CSS. Zero template changes (or one class addition to lesson.html if `:has()` isn't preferred).

---

## Template Change (Optional, Recommended)

If the team prefers to avoid `:has()` for the lesson 2-panel layout, add one class in `lesson.html`:

```html
<!-- Change line 1 from: -->
{% block content %}

<!-- To: -->
{% block content %}
<!-- Add class to target lesson pages for desktop grid layout -->
```

Actually, the cleaner approach: in `base.html`, the `<main class="container">` could get page-specific classes via a block:

```html
<main class="container {% block page_class %}{% endblock %}">
```

Then in `lesson.html`:
```html
{% block page_class %}lesson-page{% endblock %}
```

This gives us a clean CSS hook: `.lesson-page` instead of `:has(.exercise-card)`.

---

## What NOT to Change

- **Mobile layout** — zero changes below 1024px
- **Colors, typography, spacing** — all remain identical
- **Animations** — all remain identical
- **Templates** (except optional class addition) — structure stays the same
- **JavaScript** — no JS changes needed
- **Tab bar on mobile/tablet** — stays at bottom below 1024px

---

## Testing Checklist

- [ ] Home page: subject cards in 2x2 grid on desktop, single column on mobile
- [ ] Sidebar nav: visible on desktop, bottom tabs on mobile
- [ ] Lesson page: 2-panel layout on desktop, stacked on mobile
- [ ] Review play: card centered, not too wide
- [ ] Create page: deck cards in 2-col grid on desktop
- [ ] Window resize: smooth transition between layouts at 1024px
- [ ] All animations still work
- [ ] Code input has good width for Python exercises
- [ ] Tab badge (review due count) visible in sidebar
- [ ] Active tab has left accent bar on desktop, dot on mobile
- [ ] No horizontal scrollbar at any width
- [ ] Welcome card features go horizontal on desktop
