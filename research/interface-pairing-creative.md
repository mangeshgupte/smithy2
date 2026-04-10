# Human-AI Interface: Pair Programming & Creative Industries Models

*Heat 74 | 2026-04-09*

## Part 1: Pair Programming / Mob Programming

### Core Insight
The navigator doesn't write code — they **think at a higher level** while the driver executes. The navigator "has the big picture in mind" while the driver handles the immediate. **Thinking aloud** is critical: the driver narrates what they're doing, the navigator asks questions. Role switching every 15-30 minutes keeps both engaged.

### How Information Flows
- **Driver → Navigator**: Narrates work in real-time ("I'm doing X because Y")
- **Navigator → Driver**: Questions, suggestions, edge cases, strategic direction
- **Bidirectional**: Frequent role switches, continuous dialogue

### What Makes It Work
1. **Thinking aloud**: Forces the doer to articulate reasoning
2. **Different cognitive modes**: One executes, one strategizes
3. **Immediate feedback**: Errors caught in real-time
4. **Role switching**: Prevents one person from dominating

### What Makes It Fail
1. Driver ignores navigator (autonomy without collaboration)
2. Navigator micromanages keystrokes
3. No role switching → disengagement
4. Skill gap too large → one person carries

### Concrete Ideas for The Forge

#### Idea 16: "Thinking Aloud" in Commit Messages
Each commit message should explain **why**, not just **what**:
- Bad: `[implementation] Added .gitignore`
- Good: `[implementation] Added .gitignore — checkpoint and output files were polluting git history, blocking clean diffs for review`

The commit message is the Forge "thinking aloud." The human (navigator) can review the reasoning, not just the change.

**Cost**: Zero — just a convention change in the logging protocol.

#### Idea 17: Navigator Mode for the Human
Instead of the human being absent during runs, offer a **navigator mode** where:
- After each heat, Forge pauses and prints: "What I did, what I'm thinking next, what I'm unsure about"
- Human can respond or press Enter to continue
- This is opt-in: `navigator_mode: true` in state.json

This turns async → sync, useful for high-stakes work or early runs on a new project.

**Implementation effort**: 2 heats.

---

## Part 2: Creative Industries (Film, Architecture)

### Core Insight
Directors and cinematographers spend **weeks in preproduction** aligning on creative goals before shooting starts. The creative brief establishes style, tone, constraints. Then during production, **dailies** (raw footage reviewed daily) keep them aligned without the director needing to be behind every camera.

### How Information Flows
**Director → DP:**
- Creative brief (style, tone, palette, emotional intent)
- Reference materials (other films, photos, paintings)
- Feedback on dailies ("love this angle", "too dark here")

**DP → Director:**
- Dailies (raw output for review)
- Technical constraints ("we can't do X with this lens")
- Creative proposals ("what if we tried Y?")

### What Makes It Work
1. **Preproduction alignment**: Invest time upfront to agree on vision
2. **Dailies review**: Short, frequent reviews of actual output
3. **Creative brief as contract**: Both sides reference it for decisions
4. **Collaborative, not hierarchical**: Best results when director trusts DP

### What Makes It Fail
1. No preproduction → misaligned vision
2. Director doesn't watch dailies → surprises in editing
3. Micromanagement kills creativity
4. Too much revision → budget/timeline blown

### Concrete Ideas for The Forge

#### Idea 18: Creative Brief = identity.md + Commander's Intent
Combine the existing `identity.md` with a "creative brief" section that captures:
- **Tone**: How should the Forge approach work? (careful vs. fast, conservative vs. experimental)
- **Style constraints**: Naming conventions, file organization, code style preferences
- **Reference projects**: "Make it like X" — concrete examples
- **Anti-patterns**: "Don't do Y" — learned preferences

This is what the director-DP preproduction achieves: alignment on *how*, not just *what*.

#### Idea 19: Dailies = Run Artifact Review
After each run, generate a "dailies" pack — the N most impactful artifacts:
- Files created or significantly modified
- Key decisions made (from commit messages)
- Things the Forge is unsure about

The human reviews the dailies, not the full heat log. Like a director watching 10 minutes of dailies instead of 8 hours of raw footage.

This overlaps with Idea 5 (artifact-based review) but adds the creative dimension: **does this feel right?** Not just "is it correct."

**Implementation effort**: 2-3 heats.
