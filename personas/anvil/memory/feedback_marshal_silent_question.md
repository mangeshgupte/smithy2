---
name: Marshal silently waits at interactive prompt
description: When Marshal hits a decision it can't make, it asks via stdout and blocks — no nudge, no notification, invisible until you tab to the pane
type: feedback
---

When Marshal encounters a decision outside its authority (zombie tasks stuck in `submitted`, ambiguous priority signal, conflicting human input), it writes a question to its pane stdout and waits at the `❯` prompt. There is **no surfacing mechanism**: no entry in worklog, no patrol issue raised, no nudge to Anvil, no notification. The pane shows the question but the rig looks "idle."

Observed 2026-04-18 heat 989: Marshal blocked 7m37s on a question about t-450/t-463/t-472 zombie status. All three forges idle the entire time. Only surfaced because the human asked Anvil "Marshal appears stuck."

**Why:** Marshal correctly defers decisions outside its scope, but the stdout-only channel is invisible to anyone not actively reading that pane. The forges look idle (because they are), Marshal looks idle (because it's at a prompt), and there's no signal distinguishing "no work to do" from "blocked on input."

**How to apply:**
1. When the human reports any forge looking idle for >5min, **always check Marshal's pane first** — `tmux capture-pane -t forge:main.2 -p | tail -60`. The wedge is usually there.
2. After any rig change (halt/unhalt, queue mutation, reorder), spot-check Marshal's pane within ~2min — if it's at a prompt, answer it via state mutation + nudge.
3. Don't try to answer Marshal *in the pane* — that breaks the file-coordination contract. Resolve via state.json/CLI, then nudge Marshal to re-read.
4. **Comms is NOT the fix.** Comms's job is communicating state, not fixing it. The structural fix for silent-blocked agents is separate work — candidates: (a) a patrol check that grep's pane tail for prompt-with-cursor + idle, raises an issue; (b) Marshal protocol change to auto-escalate decisions via nudge to Anvil instead of waiting at stdin; (c) a dedicated watchdog process. Decide separately from Comms.
