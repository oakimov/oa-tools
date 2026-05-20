---
name: guard-find-exec
enabled: true
event: bash
action: block
conditions:
  - field: command
    operator: regex_match
    pattern: \bfind\b.*\s(-exec|-execdir|-delete)\b
---

Block find with -exec, -execdir, or -delete to prevent potentially dangerous bulk operations.
