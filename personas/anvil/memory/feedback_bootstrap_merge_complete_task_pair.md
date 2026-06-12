---
name: Bootstrap merge must pair `git merge` with `smithy complete-task`
description: Anvil's one-time bootstrap merges (bypassing Assembly) leave state.json pending unless complete-task is called explicitly; always pair them
type: feedback
---

When Anvil bootstrap-merges a branch to main (the one-time exception to "only Assembly writes to main" per `feedback_bootstrap_coupling_pattern.md`), the git merge alone does NOT update state.json. The task stays `status=pending` until someone runs `smithy complete-task <task-id>`.

Assembly's normal flow ends with `_do_assembly_merge` which flips status to `complete`. Anvil's manual `git merge` skips that code path entirely.

Observed 2026-04-19 heat ~941 after bootstrap-merging 5 fix tasks: remembered `complete-task` for 3 of them, missed 2 (t-531, t-532). Marshal noticed state-vs-git divergence and flagged it. Downstream block-checks would have continued treating those tasks as pending (blocking their dependents).

**Why:** the git operation and the state mutation are decoupled in the bootstrap path. Easy to forget the second half.

**How to apply:**
1. **Every bootstrap-merge command must be followed in the same batch by `smithy complete-task <task-id>`.** Don't close the tool-call block until both are done.
2. Batched form that fits one tool call:
   ```
   git merge --no-ff --no-edit <branch> && smithy complete-task <task-id>
   ```
3. If a merge fails (conflict), fix and commit the conflict, THEN run `complete-task` — don't mark complete until the merge is actually in main.
4. After a batch of bootstrap merges, verify with one state read before declaring done:
   ```
   python3 -c "import json; s=json.load(open('state.json')); print({t['id']: t['status'] for t in s['queue'] if t['id'] in {'t-XXX','t-YYY'}})"
   ```
5. Also consider: pair bootstrap merges with a follow-up nudge to Marshal so it re-reads and confirms. Marshal will flag drift like it did here (valuable backstop, but also a signal that we could have avoided the drift in the first place).
