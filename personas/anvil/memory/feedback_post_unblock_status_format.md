---
name: After unblocking the rig, deliver a "stuck vs working" status update
description: Human wants an explicit per-agent live-state report after any intervention that unblocks Smithy — not just confirmation that the action was taken
type: feedback
---

After Anvil (or any persona) takes an action that unblocks part of the rig — answering Marshal's silent question, killing a phantom tmux session, nudging idle forges, resolving zombie tasks, clearing a halt, etc. — deliver a structured status update with the same shape as the 2026-04-18 heat 989 report. Validated 2026-04-18.

**Why:** "I unblocked it" alone doesn't tell the human whether the rig is now actually moving. Multiple things are usually broken at once (e.g., heat 989: Marshal silent + smithy CLI session bug + 3 zombie tasks, all interleaved). A confirmation-only message hides the parts that are *still* stuck. The human needs to know which forge has which task, which agents are genuinely idle vs wedged, and what's still at risk — to decide whether to keep working or pause and intervene.

**How to apply:** After any unblock, deliver in this shape:
1. **Headline status of the agent that was stuck** — "idle and standing by (correctly — not stuck this time)" vs "still wedged" vs "active again." Be explicit about whether it's healthy idle or pathological idle.
2. **Live state of every forge** as a small table — branch (from pane title, since state.json heartbeats can be stale), what task it grabbed, current activity ("thinking," "idle," "executing heat N"). Pane titles via `tmux capture-pane | tail -10` are the source of truth, not state.json.
3. **next_tasks before/after delta** — what was queued, what was popped, what's remaining.
4. **Outstanding issues** — what's still potentially broken or at risk; flag the next thing likely to get stuck.
5. **Action taken or about to take** — if you nudged again, say so; if no further action needed, say "watching."

Do **not** just say "Marshal nudged. Forges are picking up." — that's the action, not the state.

Apply to: any intervention on halt/unhalt cycles, queue-state mutations, agent wakeups, phantom-session cleanup, post-zombie resolution, post-prompt unstick.
