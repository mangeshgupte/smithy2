# Agent Teams Retrospective — Marshal's Seat

A working doc, not an announcement. Written to save the next person (or next persona) some of the friction we hit running Anvil/Marshal/Forge as three Agent Teams teammates over heats ~634–719.

Author: Marshal (the prioritizer seat). Anvil and Forge should read this and push back on anything that looks wrong.

---

## Context

Three personas, spawned by Anvil as the lead:
- **Anvil** — human-facing. Strategy, steering, status explanations.
- **Marshal** — prioritizer. Watches state, generates tasks, pushes to queue.
- **Forge** — executor. Pops task, runs a heat, commits, reports.

Coordination was via `SendMessage` between teammates and `.smithy-nudge-queue/<persona>.jsonl` for cross-tmux nudges. The protocol: **nudge-driven**, not poll-driven. `smithy end-heat` auto-nudges Marshal; `smithy queue-push` auto-nudges Forge.

Observed over ~85 heats, across four task batches (t-285 to t-303) plus earlier infrastructure.

---

## What Worked

### 1. The nudge cycle is genuinely self-sustaining

Once the triangle was wired (end-heat → marshal, queue-push → forge), we stopped thinking about scheduling. Forge would finish a heat, nudge fired, I'd wake, re-prioritize, push next task, Forge woke, executed. Anvil only intervened for direction changes or human requests. That's the point, and it worked.

Heats 700–718 ran with essentially zero human input after the initial batch assignment. Cadence was roughly one heat every 3–5 minutes.

### 2. Separation of concerns held up

Anvil explaining → Marshal prioritizing → Forge executing was clean enough that I rarely needed to ask "whose job is this?" Strategic decisions went to Anvil. Task prioritization stayed with me. Execution details went to Forge. When the human asked "what's the status?" that landed on Anvil, who read the worklog and responded without pulling me in.

The split also made the conversation artifacts useful: each teammate's message log is roughly coherent in isolation, which helps future debugging.

### 3. `queue-push` auto-nudge is the right default

Forcing the queue write *and* the wake-up into one CLI call meant I couldn't forget one of them. Worth preserving.

### 4. `TASK_COMPLETE: t-XXX` report template

Forge's report template (commit hash + value + signal + summary) was rigid enough that I could grep the last N messages for outcomes without parsing prose. Keep it.

---

## What Caused Friction

### 1. The persona-directory bug

By far the largest source of pain. `Agent` tool spawns subagents in the **caller's** cwd, so Anvil's spawns of Marshal and Forge inherited `personas/anvil/`, which meant they would load Anvil's `CLAUDE.md` instead of their own. If Anvil didn't explicitly instruct the spawn prompt to `cd` to the correct persona dir and read its own CLAUDE.md by absolute path, the teammate would silently wear the wrong persona.

This is documented in `personas/anvil/CLAUDE.md` now (see the spawn-prompt pattern). But the first few times it happened, "why is Forge giving strategic brainstorms instead of executing?" was a long debug.

**Lesson:** every spawn prompt needs an explicit two-step preamble:
```
First, cd to /abs/path/to/personas/<name>/.
Then read your CLAUDE.md at /abs/path/to/personas/<name>/CLAUDE.md.
Only then: [task instructions]
```

### 2. Message cross-talk between Anvil and Marshal

Because Forge sent `TASK_COMPLETE` directly to me, and Anvil sometimes issued steering messages *also* to me, there were moments where Anvil's instruction to "reprioritize batch X" arrived while Forge was already telling me batch X was done. Twice I re-assigned an already-completed task (t-285, t-286) because Anvil's nudge ran ahead of Forge's report.

Forge handled it gracefully — responded "already done, commit abcd1234" every time. But that's wasted cycle.

**Lesson:** a lightweight "I've already handled that" contract is needed. Either:
- Marshal dedupes by checking task status before assigning (currently does, but only for same-batch), or
- Senders include a monotonic cursor so Marshal can drop stale directives.

### 3. `TaskUpdate task not found` on stale IDs

The shared task list's IDs drift between sessions. A few times I tried to `TaskUpdate` a task that had been re-IDed during a compaction or session switch (e.g., t-285's task_id 16 was no longer valid after context compression). The tool returned "Task not found" but no clear remediation path.

**Lesson:** don't store task-list IDs in memory or messages. Re-resolve by subject/description when crossing a session boundary.

### 4. `add-task` positional vs. flag confusion

Early in the run Forge tried `smithy add-task --stage testing "desc"` and got a "got unexpected argument" error. The CLI takes stage as positional (`add-task testing "desc"`), but the Forge persona docs weren't explicit until t-295 cleaned it up.

Related gotchas Forge hit more than once:
- `start-heat testing` (not `start-heat --stage testing`)
- `end-heat VALUE SIGNAL NOTES` — three positionals, not `--value`/`--notes`
- `SIGNAL` must be `🟢/🟡/🔴`, not `green/yellow/red`

**Lesson:** a CLI cheat sheet at the top of `protocol/loop.md` would have saved maybe 4–5 re-tries. (The Forge CLAUDE.md rewrite in t-295 partly addresses this.)

### 5. State mutations happening under me

Twice the human edited `state.json` directly while I was mid-computation. Marshal's state-loading isn't atomic; it reads, computes, writes back, and a concurrent human write could in principle be lost. Never saw actual data loss, but the window exists.

**Lesson:** either all writes go through `smithy` commands with a lock, or Marshal should re-read + diff before writing. Currently neither is true.

---

## Recommendations for the Next Persona

### Make the cwd contract explicit in a shared doc

Currently only `personas/anvil/CLAUDE.md` documents the cd-first spawn pattern. That's the wrong home for it — the rule belongs to *any* lead that spawns teammates. Move it to `protocol/agent-teams.md` or similar. Otherwise, a future lead will repeat this mistake.

### Add a "cursor" field to cross-persona messages

Every SendMessage should include a `heat_number` or `seq` field. The receiver drops messages with cursor ≤ last_processed. Simple deduplication, solves the Anvil-vs-Forge race cleanly.

### Consider folding Marshal back into Anvil

Honest question. Marshal does three things:
1. Generate tasks from approved initiatives
2. Prioritize the queue
3. Push the next task after each heat

Step (3) is mostly mechanical — `queue-pop` does most of it, and Forge could call it directly after `end-heat`. Steps (1) and (2) need judgment, but they only fire when state changes (human steering) or when the queue empties. That's rare enough that Anvil could handle it on demand.

The separation helped us *discover* the nudge cycle, but once the cycle is mature, Marshal may be a layer we don't need. Worth testing with a 2-persona variant (Anvil + Forge only) and measuring friction.

If we keep Marshal, give it a clearer idle state — right now it's unclear whether "silent Marshal" means "working" or "idle waiting for state change."

### Don't over-rely on `TaskList` / `TaskUpdate`

These drifted on us. For coordination, SendMessage + the shared task description as the stable key is more reliable than task IDs. Use TaskList/TaskUpdate for *display* only, not for protocol state.

### Write down what the retrospective-author's role actually is

Reading this back, I notice half of what I call "Marshal's work" is really observation — I noticed the cross-talk because I was the one re-assigning. A future persona may not get this retrospective; it will be named something like "Scout" or "Keeper" and handed a CLAUDE.md. Make sure that CLAUDE.md tells them what to watch *for*, not just what to do.

---

## Concrete Citations

| Heat / commit | Friction observed |
|---|---|
| Heats 634–687 (v1.5 arc) | Initial queue-unification, nudge integration |
| Heats ~700 (t-285 kickoff) | Marshal re-assigned t-285/t-286 to Forge after Forge had already completed them. Forge: "already done, commit <hash>" × 2 |
| t-285 debugging | `_decompose_intent` bug (`.strip()` eating sub-bullet whitespace) slipped past until Forge noticed test assertions didn't match real behavior. Fixed in t-293 |
| t-287 (cross-nav) | Only moment where I needed Anvil to adjudicate — the URL_BELLOWS default port (8000 vs 8080) was genuinely ambiguous. Was later fixed in t-301 |
| t-292 tests, commit 27b4628 | Two test assertions wrong because I didn't tell Forge that Poker's `/api/state` returns `{ini_id: {...}}` not `{initiatives: [...]}`. Forge found it by running the tests, not from my spec |
| t-295 (Forge persona rewrite) | Removed `HOOK_DONE` / dispatch references that were still lingering in Forge's CLAUDE.md even though the nudge cycle replaced them ~60 heats earlier |
| t-301 (port sweep) | Classic "docs drift from code" — STEERING.md and README claimed 8081-8084, code defaulted to 8001-8004. Not caused by Agent Teams per se, but the multi-persona setup made the mismatch harder to notice because nobody "owned" that alignment |

---

## Open Questions

1. Is the nudge-queue-file mechanism (`.smithy-nudge-queue/<persona>.jsonl`) still needed now that SendMessage works reliably within a team? It was a pre-Agent-Teams primitive. Possibly dead weight.
2. Should Forge's `end-heat` report be structured JSON by default rather than a templated string? Would make dedup trivial.
3. Does the 3-persona split make sense for projects under, say, 200 heats, or is it overkill?

Not answering these now — flagging for whoever designs the next iteration.

---

*Written by Marshal, heat 719, commit forthcoming. Reviewed in conversation with Forge (who executed this heat) — any factual errors are mine.*
