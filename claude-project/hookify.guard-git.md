---
name: guard-git-destructive
enabled: true
event: bash
action: block
conditions:
  - field: command
    operator: regex_match
    pattern: \bgit\b.*\b(commit|push)\b|\bgit\b.*\breset\b.*--hard\b
---

Block git commit, push, and reset --hard regardless of flags between git and the subcommand.
