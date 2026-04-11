# Dolt Evaluation — Can It Replace Flat-File State?

## What Is Dolt?

Dolt is "Git for data" — a SQL database with branching, merging, diffing, and commit history. It's a MySQL-compatible server that stores data in a Git-like structure. Every change is a commit. You can branch, merge, and diff tables.

## Current Smithy State

Smithy uses flat files:
- `state.json` — single JSON blob (~1000 lines), read/written atomically
- `worklog.tsv` — append-only TSV, one row per heat
- `MEMORY_DAILY.md` / `MEMORY_WEEKLY.md` — markdown
- Various `.md` files for communication

**What works**: Simple, inspectable with `cat`, git-tracked, zero dependencies.

**What doesn't**: 
- No concurrent writers (two Forge instances would corrupt state.json)
- No queryable history (can't ask "what was the progress 50 heats ago?")
- No structured relationships (initiatives → tasks is JSON nesting, not foreign keys)

## Dolt Pros for Smithy

1. **Multi-agent safety** — SQL transactions, no file corruption from concurrent writes
2. **Queryable history** — `SELECT * FROM worklog WHERE heat > 600 AND stage = 'testing'`
3. **Branching** — each Forge persona could work on a branch, merge at boundaries
4. **Diffing** — `dolt diff HEAD~10` shows exactly what changed in the last 10 heats
5. **Schema enforcement** — no more "oops, forgot a field in state.json"

## Dolt Cons for Smithy

1. **Dependency** — requires `dolt` binary (~100MB) and a running server
2. **Complexity** — SQL schema design, migrations, connection management
3. **Inspectability loss** — `cat state.json` becomes `dolt sql -q "SELECT *..."`
4. **Over-engineering** — single-agent Smithy doesn't need multi-writer safety
5. **Python driver** — needs `mysql-connector-python` or `sqlalchemy`

## Recommendation

**Don't migrate now. Design for it.**

Smithy is single-agent today. Flat files work. But if/when multi-agent comes:
1. Abstract state access behind functions (already done: `load_state`/`save_state`)
2. Keep the CLI interface stable — commands don't care if state is JSON or SQL
3. When ready, swap `state.py` to use Dolt instead of JSON files
4. The migration is surgical: one file, ~50 lines

**Conclusion**: Dolt is the right tool for multi-agent Smithy. Not needed yet. The abstraction boundary is already in place.
