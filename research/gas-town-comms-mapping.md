# Gas Town Communication Protocol Mapping

*Heat 482 research | 2026-04-10*

## Communication Channels

| Smithy | Gas Town | Mapping |
|--------|----------|---------|
| `inbox.md` (human → Forge) | `gt nudge` (ephemeral) or `gt mail send` (persistent) | Nudge = real-time injection via system-reminder. Mail = bead-backed, survives session death. |
| `outbox.md` (Forge → human) | Agent bead CV chain + mail replies | Work history is queryable via `bd log`. |
| `dispatch/anvil-to-forge.md` | `gt sling` (hook work on agent) + formula | Sling creates a sling-context bead, formula defines the workflow. Agent picks up via GUPP. |
| `dispatch/forge-to-anvil.md` | `gt done` + POLECAT_DONE mail | Completion signals flow through the Witness protocol. |
| `feedback.md` | HELP/ESCALATED messages | `gt done --status=ESCALATED` signals the agent is stuck. |
| Review-first-heat | `gt prime --hook` + `gt mail check --inject` | On startup, agents recover context and process unread mail. Equivalent to checking feedback.md. |

## Key Differences

1. **Gas Town separates ephemeral (nudge) from persistent (mail)**. Smithy treats everything as persistent file writes. Gas Town's approach is more efficient at scale (20+ agents).
2. **Gas Town uses GUPP** ("if hooked, you run it") — no confirmation. Smithy's review-first-heat pattern is a confirmation step Gas Town explicitly avoids.
3. **Gas Town's Witness** replaces Anvil as the coordinator. The Witness patrols by scanning state (discover, don't track), not by reading dispatch files.
4. **Handoff messages** solve session cycling. Smithy's session memory (progress.py) is a simpler version of the same concept.
