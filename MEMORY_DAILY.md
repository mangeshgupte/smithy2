# Daily Memory

## 2026-04-10

### Heats 461-470: Bug Fix + Smithy Init

**Syntax highlighting bug** (h461-462): Python highlighter was breaking non-Python examples (English Vocabulary showed raw `<span>` tags). Fixed by adding `data-subject` attribute to example blocks and scoping syntax.js selector to `[data-subject="python"]` only.

**Smithy init** (h463): Replaced forge-init.sh with `smithy init <project-name>` command. Scaffolds all files (state.json, worklog.tsv, identity.md, STRATEGY.md, feedback.md, inbox.md, etc.) with validated initial state. Supports `--with-personas` flag.

**Smithy CLI now has 12 commands:**
start-heat, end-heat, validate, status, allocate, pick-task, process-feedback, process-inbox, add-task, complete-task, commit, init

### Key Stats
- 142 tests (111 tutor + 12 commissioner + 19 smithy)
- All feedback processed and annotated (feedback cursor at 89)
- Smithy fully dogfooded for 20 consecutive heats (441-470)
