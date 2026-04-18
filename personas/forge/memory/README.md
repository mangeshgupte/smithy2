# Forge memory — per-forge layout (t-458)

Prior to t-458 every Forge wrote to a single `personas/forge/memory/` directory,
producing "severe conflict" rejects from Assembly when two Forges touched
`MEMORY.md` on different task branches. Each Forge now owns its own subdir:

```
personas/forge/memory/
├── README.md                          # this file
├── quench/                            # forge-quench's memory
│   ├── MEMORY.md
│   ├── MEMORY_DAILY.md
│   ├── MEMORY_WEEKLY.md
│   └── <typed-entry>.md ...
├── temper/                            # forge-temper's memory
│   └── ...
└── anneal/                            # forge-anneal's memory
    └── ...
```

**Ownership:** each Forge writes ONLY to `memory/<its-forge-suffix>/`. A
Forge's `forge-id` is `forge-quench`, `forge-temper`, `forge-anneal` — the
memory subdir drops the `forge-` prefix (`quench/`, `temper/`, `anneal/`).

**Reading:** a Forge typically reads only its own subdir at startup. When
cross-Forge insight-sharing is desired (rare), read the other subdirs
explicitly — but never *edit* them. Cross-subdir edits re-introduce the
merge-conflict risk this layout exists to eliminate.

**CLI:** `smithy memory-write` auto-detects the caller's Forge id from the
worktree cwd and writes into the correct subdir. It never writes to the
shared root, so concurrent calls from different Forges can never collide.

**Patrol check:** `smithy patrol` flags the reappearance of any of the
legacy shared files (`personas/forge/memory/MEMORY.md`,
`MEMORY_DAILY.md`, `MEMORY_WEEKLY.md`) as a drift warning — if one
shows up, it means a regression pushed memory to the wrong path.
