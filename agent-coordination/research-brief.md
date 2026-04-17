# Agent Coordination — Research Brief

**Date:** 2026-04-15 · **For:** Mangesh · **By:** Anvil

---

## TL;DR

- The Forge's current tmux rig is already a good strict-coordination design: single-writer merges, CLI-funneled state, role-typed refusal contracts.
- Research on multi-agent LLMs says that's exactly right. Unstructured agent chatter **amplifies errors up to 17×** vs. a single agent (MAST, 2025).
- The trick isn't "strict or loose" — it's **strict at merge edges, loose at input edges.** The Forge already does this; the brief names it and suggests where to tighten.
- **Fastest wins:** schema the nudge-queue JSON, give each persona an Agent Card, close the set of message types, add a mid-heat escalate channel.

---

## 1. What The Forge does today

Five things make its coordination strict:

1. **One writer to `main`.** Assembly only. Per-task branches; rebase + test + merge or reject to Marshal.
2. **All state mutations go through one CLI.** `smithy add-task`, `queue-push`, `end-heat`, etc. No agent hand-edits `state.json` or `worklog.tsv`.
3. **Small closed message vocabulary.** Essentially: *queue-push*, *end-heat*, *assembly-merged*, *assembly-rejected*. Each one maps to a state transition.
4. **Role refusal contracts.** Every `CLAUDE.md` has a "What You Refuse To Do" — Anvil won't write code, Marshal won't execute, Assembly won't auto-resolve code conflicts.
5. **Append-only record.** `worklog.tsv`, `assembly-log.jsonl`, git history. The record is the oracle; agent memory is disposable.

Two things stay loose on purpose: `inbox.md` (human ideas, free prose) and research heats (exploratory by design).

**Wake signal:** `scripts/nudge.sh` — `tmux send-keys` into the target pane. Claude only re-reads state when it takes a turn; nudge is what triggers the turn. State sits durably in files; nudges are ephemeral.

---

## 2. The spectrum

Strict ↔ exploratory coordination, roughly in order:

| Pattern | Strictness | Good for |
|---|---|---|
| Session types / state machine | Very strict | Safety-critical transitions |
| Workflow orchestration (Temporal, Dapr) | Strict | Long-running, replayable jobs |
| **CLI-mediated shared state (Forge today)** | **Strict** | **Auditable team workflows** |
| Contract Net (bid / accept / confirm) | Medium | Heterogeneous workers, load-aware |
| Blackboard (schema'd shared memory) | Medium | Collaborative problem-solving |
| Tuple space / Linda (`out`, `in`, `rd`) | Medium-loose | Uncoupled producers/consumers |
| Actor model / OTP | Loose-ish | Fault-tolerant message passing |
| A2A / MCP over JSON-RPC | Varies | Cross-org agent interop |
| Pub/sub event bus | Loose | Fan-out, decoupled consumers |
| Conversational (AutoGen group chat) | Loose | Debate, consensus, ideation |
| Stigmergy (traces in shared env) | Loose | Swarms, exploration |

**Rule of thumb:** The further left, the more auditable. The further right, the more adaptive. **You choose per surface, not per system.**

---

## 3. Key patterns worth knowing

Five patterns, four to borrow from and one to avoid. Each with the problem it was invented to solve, because the *motivation* usually tells you when the pattern is the right tool.

### 3.1 Blackboard (Hearsay-II, ~1975)

**Problem it was invented for.** CMU's Hearsay-II speech understanding system. No single algorithm could recognize connected speech — you needed acoustic, phonetic, syntactic, and semantic knowledge *combined*, and you didn't know in advance which would crack a given utterance. Pipelining them didn't work; you had to let whichever was most confident contribute next.

**Core idea.** A shared, hierarchical memory (the "blackboard") holds the current problem state — hypotheses, partial solutions, confidence scores. Around it sit independent *knowledge sources* (specialists). A *controller* watches the blackboard and fires whichever KS's trigger condition best matches the current state. Think of a room of experts around a whiteboard, each stepping up when they have something to add.

**Why it mattered.** Opportunistic problem-solving — the system's behavior emerges from the current state, not a pre-written plan. It's the ancestor of every "shared context" multi-agent design, including modern LLM frameworks like [arXiv 2507.01701's blackboard MAS](https://arxiv.org/html/2507.01701v1).

**Forge mapping.** `state.json` + `worklog.tsv` *are* our blackboard. Marshal is the controller. Each persona is a specialized KS. The difference: our KSes aren't triggered by pattern-matching the blackboard — they're triggered by nudges. That's a deliberate simplification.

**Trade-offs.** Controller becomes a bottleneck; schema drifts as you add KSes; concurrency is hard if multiple KSes want to write the same region. Works best when the schema is small and mostly stable.

---

### 3.2 Tuple spaces / Linda (Gelernter, 1985)

**Problem it was invented for.** In the early 80s, parallel programming was glued to specific architectures — shared-memory threads on one kind of machine, message-passing on another, and your code didn't port. David Gelernter at Yale wanted to *separate coordination from computation* so any language (C, Fortran, Lisp) could become parallel by adding a tiny coordination layer.

**Core idea.** A shared associative memory — the "tuple space" — holding data tuples like `("task", 42, "testing", payload)`. Four primitives:

- `out(tuple)` — write a tuple.
- `in(pattern)` — **take** a matching tuple (destructive; blocks until one appears).
- `rd(pattern)` — **read** a matching tuple (non-destructive).
- `eval(tuple)` — spawn a process that computes the tuple then `out`s it.

Matching is associative: a consumer says "give me something shaped like `("task", ?, "testing", ?)`" and gets whatever fits. Producer and consumer never need to know each other exists, and they don't need to be alive at the same time.

**Why it mattered.** Full decoupling in space (no addresses) and time (asynchronous). This is the lineage of JavaSpaces, Apache River, and — less directly — modern message queues. An [excellent 2024 essay](https://otavio.cat/posts/ai-orchestration-reinventing-linda/) argues every AI orchestration framework is now rediscovering Linda.

**Forge mapping.** `.smithy-nudge-queue/*.jsonl` and `.assembly-queue.jsonl` are tuple spaces in miniature. `queue-push` ≈ `out`, `queue-pop` ≈ `in`. This is *why* the rig survives individual agents crashing: if Marshal goes down, Forge's end-heat still `out`s a nudge tuple; Marshal picks it up on restart.

**Trade-offs.** Weaker schema than a blackboard (anything can be a tuple); naive implementations scale badly; you still need a separate discipline for persistence and ordering. The Forge solves this by keying tuples by recipient and using JSONL files — simple, debuggable, durable.

---

### 3.3 Contract Net Protocol (Smith, 1980; FIPA 2002)

**Problem it was invented for.** Reid Smith's PhD at Stanford on distributed sensor networks. How do N autonomous nodes divide up sub-problems *without a central scheduler* when capabilities, load, and task arrival are all dynamic? Smith borrowed the metaphor from civil engineering: a prime contractor posts a job, subcontractors bid, the winner does the work.

**Core idea.** A tight five-step state machine:

1. **Call for proposals (cfp)** — manager broadcasts "task X, who can do it?"
2. **Propose / refuse** — each potential contractor replies with a bid (cost, time, confidence) or declines.
3. **Accept / reject** — manager picks a winner, informs losers.
4. **Inform-done / failure** — winner reports completion.
5. **Optional: progress / cancel** mid-execution.

Every message type is pre-declared; the transitions are strict.

**Why it mattered.** It's the canonical example of *market-based* task allocation, as opposed to directive assignment. Scales with heterogeneous workers because each worker self-evaluates fit. FIPA standardized it in 2002 and it's still the reference interaction pattern for agent marketplaces.

**Forge mapping.** We *don't* use it. Marshal directly pushes to a specific Forge's queue because today all Forges are clones — no bidding adds value. If we ever specialize (forge-temper = tests, forge-anneal = docs, forge-quench = impl), CNP starts earning its overhead.

**Trade-offs.** Every task announcement is O(N) broadcast. Bid reasoning costs tokens per worker per cfp. Weak bidders can starve. Don't use it when a directive scheduler already knows who should do what — CNP is for when the *manager doesn't know best*.

---

### 3.4 FIPA ACL / speech acts (KQML 1993 → FIPA 1997)

**Problem it was invented for.** The DARPA Knowledge Sharing Effort in the early 90s wanted interoperable intelligent agents — not just exchanging bytes, but understanding *what the other agent meant to do*. Early attempt: KQML (Knowledge Query and Manipulation Language). FIPA later cleaned it up into ACL.

**Core idea.** Borrowed from Austin and Searle's *speech-act theory* in philosophy of language. An utterance isn't just data — it's an action. "I promise to pay you tomorrow" *is* the promise. Messages between agents should carry that force explicitly via a **performative**: a tag like `inform`, `request`, `propose`, `confirm`, `refuse`, `subscribe`, `query-ref`. The receiver can reason about what the sender wants ("they requested X, so they believe I can do X and want the result") without parsing free text.

A FIPA ACL message has a fixed envelope: performative (mandatory) + sender + receiver + content + optional ontology/language/conversation-id fields.

**Why it mattered.** Separates *intent* from *payload*. Two agents built by different teams can still coordinate because the meaning of `request` is standardized, even if the content schema isn't. It's the intellectual ancestor of modern typed message protocols, including A2A's JSON-RPC method names.

**Forge mapping.** We have an implicit performative vocabulary — `TASK_COMPLETE`, `ASSEMBLY_MERGED`, `ASSEMBLY_REJECTED`, generic nudge. Making these explicit (a closed set of ~6 prefixes, parsed not just matched) is the section-7 recommendation that most directly borrows from ACL.

**Trade-offs.** FIPA's full formal semantics (grounded in agents' beliefs, desires, intentions) are heavy — almost no production system uses them rigorously. The *useful* piece is the typed-envelope discipline, not the philosophical machinery.

---

### 3.5 The anti-pattern — unstructured group chat

**Why it exists.** After ChatGPT, "just have agents talk to each other in natural language" felt like the obvious design. AutoGen, BabyAGI, CAMEL, early LangChain agent execs all bet on it.

**Why it fails.** MAST 2025 data is unambiguous: unstructured networks **amplify errors up to 17× vs. a single agent**, and coordination breakdowns are 37% of failures. The top sub-modes — acting on wrong assumptions (6.8%), task derailment (7.4%), reasoning/action mismatch (13.2%) — are what you get when the medium is free-form text and the protocol is "keep chatting until someone says stop." Tokens compound (~15× single-agent cost) and errors compound faster.

**Use it anyway when:** the task is genuine ideation or debate where the *conversation* is the product (brainstorming, critique, adversarial review). Not when there's a right answer and you need to reach it reliably.

---

## 4. How modern LLM frameworks think about this

| Framework | Abstraction | Strictness | Where Forge sits |
|---|---|---|---|
| **LangGraph** | Directed state graph, persistent checkpoints | High | Closest match |
| **CrewAI** | Roles + tasks + crew | Medium | Similar spirit, less durable |
| **AutoGen** | Group chat / dialogue | Low | Deliberately avoided |

The Forge is architecturally a LangGraph — explicit state transitions, durable record — implemented on a filesystem + tmux substrate instead of a Python runtime. That's the right call for "no broken `main`."

**Anthropic's orchestrator-worker pattern** (lead agent decomposes, workers explore in parallel, lead synthesizes) matches Anvil → Marshal → N×Forge → Assembly. Anthropic reports +90% on research evals vs. single-agent, at ~15× token cost. Worth doing when task value is high; overkill for routine edits.

**MetaGPT's lesson:** structured *artifacts* at every handoff (PRD, design doc, task list) reduce ambiguity. Our stage pipeline (research → planning → implementation → testing) is this pattern.

---

## 5. The failure data (MAST, 2025)

The 2025 paper *"Why Do Multi-Agent LLM Systems Fail?"* analyzed 1,642 traces across 7 frameworks. Failure rates were **41–86%**. Unstructured networks amplified errors **up to 17×** vs. a single agent.

The 14 failure modes cluster into three buckets. The biggest one — **coordination breakdowns, 37% of all failures** — includes:

- Proceeding on wrong assumptions instead of asking (6.8%)
- Task derailment (7.4%)
- Reasoning/action mismatch (13.2%)
- Ignoring peer input, withholding info, unexpected resets

**What Forge already defends against:** role violations (refusal contracts), wrong-assumption loops (`smithy` fails loudly on misuse), task derailment (per-heat commits make drift visible in 5 min), no verification (Assembly runs tests before merge).

**What Forge is still exposed to:**

- **Mid-heat blockers.** If a Forge gets stuck, Marshal doesn't hear until `end-heat`. No in-heat escalate channel.
- **Stale nudges.** Nudges queue but agents can act on old ones. No sequence numbers.
- **Off-scope commits.** Assembly tests the code but doesn't check "did this change touch the files the task implied?"

---

## 6. Trade-offs

| Dimension | Stricter protocol | Looser protocol |
|---|---|---|
| Auditability | High | Low |
| Token cost | Low | High (chat ≈ 15× single-agent) |
| Robustness to model slips | High — schema rejects | Low — errors propagate |
| Flexibility / novelty | Low | High |
| Onboarding / changing the protocol | Expensive | Cheap |
| Failure visibility | Fails at the boundary | Fails silently downstream |

**Where stricter is obviously worth it:** merges, budget updates, role handoffs, the audit trail.

**Where stricter is worse:** brainstorming, design, human-facing conversation, early iteration on a new persona.

---

## 7. Recommended next moves

Ordered cheap-to-expensive. All of them preserve the "strict at merge, loose at input" split.

### Cheap and obvious

1. **Schema the queue entries.** JSON schema for `.smithy-nudge-queue/*.jsonl` and `.assembly-queue.jsonl`. `smithy` validates on enqueue and dequeue. Session-typed coordination at the cheapest boundary. ~1 heat.

2. **Agent Card per persona.** A small `capabilities.json` next to each `IDENTITY.md` declaring: accepted messages, forbidden actions, files read/written. Lets `patrol` mechanically verify "did Anvil touch `main`?" (no). Localized version of the A2A Agent Card pattern. ~1 heat per role.

3. **Name the performatives.** Consolidate `TASK_COMPLETE` / `ASSEMBLY_MERGED` / `ASSEMBLY_REJECTED` / generic nudge into a closed set of ~6 typed prefixes. Prose context still in the body. ~1 heat.

### Closes real MAST gaps

4. **Mid-heat escalate channel.** Define `ESCALATE:` — a Forge can write to `inbox.md` (or a dedicated file) without calling `end-heat`. Anvil polls on idle. Today there's no safe way for Forge to say "I'm stuck, this task can't close."

5. **Sequence numbers on nudges.** Monotonic seq per producer. `drain-nudges` returns the latest and marks older ones `superseded`. Closes the "act on stale signal" hole.

6. **Assembly scope check.** Before merge, verify the diff touches files within the task's declared scope. Catches unrelated edits sneaking in to close a heat.

### Bigger bets — consider, don't rush

7. **Supervisor / liveness check.** A watcher that notices when a pane goes silent. OTP's lesson: supervisors are cheap; mystery outages aren't.

8. **Contract Net when Forges specialize.** Only pays off once Forges have different capabilities. Not yet.

9. **Headless runner.** Tmux stops scaling around 5 Forges. The protocol itself (filesystem + CLI + nudges) is portable to any process manager. A web UI tailing each agent's log would preserve observability.

---

## Sources

- [Why Do Multi-Agent LLM Systems Fail? (MAST, arXiv 2503.13657)](https://arxiv.org/abs/2503.13657)
- [Multi-Agent Collaboration Mechanisms: A Survey of LLMs (arXiv 2501.06322)](https://arxiv.org/html/2501.06322v1)
- [How Anthropic built a multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Building Effective Agents (Anthropic)](https://www.anthropic.com/research/building-effective-agents)
- [MetaGPT (arXiv 2308.00352)](https://arxiv.org/abs/2308.00352)
- [FIPA Contract Net Specification](http://www.fipa.org/specs/fipa00029/SC00029H.html)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [Tuple space (Wikipedia)](https://en.wikipedia.org/wiki/Tuple_space)
- ["Our AI Orchestration Frameworks Are Reinventing Linda"](https://otavio.cat/posts/ai-orchestration-reinventing-linda/)
- [Temporal — Durable Execution meets AI](https://temporal.io/blog/durable-execution-meets-ai-why-temporal-is-the-perfect-foundation-for-ai)
- [CrewAI vs LangGraph vs AutoGen (DataCamp)](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen)
