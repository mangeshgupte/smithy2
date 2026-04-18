---
name: Never put angle-bracketed placeholders in inline bash -c strings
description: Strings like <forge-id> or <task-id> inside `bash -c "..."` or `python3 -c "..."` arguments get parsed as shell redirection and crash the command
type: feedback
---

When passing Python code or prose to bash via `-c "..."` that contains angle-bracketed placeholders (e.g., `<forge-id>`, `<task-id>`, `<branch>`), the shell tokenizes `<X` as "redirect input from file X" before Python ever sees the string. Even inside double quotes in the outer shell, this can still bite depending on context. Observed 2026-04-18: `python3 -c "... '<forge-id>' ..."` failed with `no such file or directory: forge-id`.

**How to apply:** For any multi-line script or string containing `<X>` patterns, use heredoc form:

```
python3 << 'PYEOF'
... <forge-id> ...
PYEOF
```

The single-quoted `'PYEOF'` sentinel disables shell expansion inside the heredoc. Same rule for bash `<< 'EOF'` blocks containing angle-bracketed placeholders. Inline `-c` strings are fine only for short, placeholder-free commands.
