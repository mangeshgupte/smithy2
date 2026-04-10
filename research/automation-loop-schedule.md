# Automating Heat Execution — /loop vs /schedule vs External

## Findings

### /loop (Ralph Loop)
- Runs a prompt on a recurring interval **within the same session**
- Usage: `/loop 5m /command`
- Does NOT restart sessions — context window grows over time
- Stops at max-iterations or completion promise
- Good for: medium runs (10-20 heats) where context growth is acceptable

### /schedule (Remote Triggers)
- Creates cron-scheduled remote agents
- Runs **outside** the session — spawns new processes
- Could trigger new Claude Code sessions on schedule
- Less documented locally — needs further investigation

### SessionEnd Hook + External Cron (Recommended for v0.3)
- External cron triggers `claude -p "Run 5 heats"` every 30 minutes
- SessionEnd hook distills memory automatically
- New session reads state.json → resumes
- Most robust: clean sessions, no context growth, automatic memory consolidation

## Recommendation

| Run Length | Approach |
|-----------|----------|
| 1-20 heats | Current approach (single session, manual "Run N") |
| 20-50 heats | /loop with 5m interval — stays in session, context auto-compresses |
| 50+ heats | External cron + SessionEnd hook — session cycling |

## Action Items
- [ ] Test /loop with "Run 5 heats" as the recurring command
- [ ] Investigate /schedule for remote trigger creation
- [ ] Build SessionEnd hook for The Forge (adapt from agents/hooks/session-end-memory.sh)
