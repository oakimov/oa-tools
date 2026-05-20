# claude-project

Tools for managing Claude Code project data.

## Architecture

Shared logic lives in `claude_shared.py` (constants, config I/O, path encoding, data scanning, unified deletion). Both `claude-mcp.py` and `claude-cleaner.py` import from it.

## claude-mcp.py

CLI for managing MCP server configuration in `.claude.json` and project cleanup.

| Command | Description |
|---------|-------------|
| `list` | List all registered project paths |
| `show-enabled` | Show non-disabled servers per project (`-v` for details) |
| `disable-all` | Disable all MCP servers for all projects |
| `disable <path>` | Disable all MCP servers for a specific project |
| `clean <path>` | Reset `mcpServers` and `disabledMcpServers` for a project |
| `delete <path>` | Delete a project (removes `.claude.json` entry + filesystem data + session artifacts + plan files) |
| `clean-plans` | Remove approved and cancelled plan files across all projects |
| `tui` | Launch interactive cleaner TUI |

## claude-cleaner.py

Cross-project session, memory, and plan browser/cleanup TUI. Scans all projects
in `~/.claude/projects/` and provides a keyboard-driven interface to browse and
delete conversations, memories, plans, and entire project directories.

### Views

| View | Description |
|------|-------------|
| **Project list** | All projects sorted by total size. Shows conv/memory/plan counts. Right sidebar shows MCP servers, memories, plans, and stats. |
| **Project detail** | VSplit with conversations (date/size sortable) and right panel (MCP servers, memories, plans). |
| **Conversation viewer** | Full message history with scroll. Bottom bar shows UUID and size breakdown. |
| **Memory viewer** | Memory file body with frontmatter metadata. |
| **Plans cleanup** | All plans across projects with status (approved/cancelled/pending). |
| **Confirm delete** | Confirm prompt before removing any item. |

### Keybindings

| Key | Context | Action |
|-----|---------|--------|
| `↑`/`↓` | everywhere | Navigate |
| `PgUp`/`PgDn` | conversation/memory | Scroll pages |
| `Enter` | project list, detail | Open selected item |
| `Tab` | project detail | Switch between conversations and memories pane |
| `1` | project detail | Sort conversations by date |
| `2` | project detail | Sort conversations by size |
| `m` | project detail | Toggle MCP server status in bottom bar |
| `D` | project list, detail | Disable all MCP servers for selected project |
| `Ctrl+D` | project list | Disable MCP servers for all projects |
| `p` | project list | Open plans cleanup view |
| `a` | plans cleanup | Delete all removable plans |
| `d` | everywhere | Delete current item |
| `y` | confirm | Confirm action |
| `Esc` / `Backspace` | everywhere | Go back |
| `q` | everywhere | Quit |

### Unified deletion

Both tools perform the same unified deletion when removing a project:
- Removes the entry from `~/.claude.json`
- Removes the project directory under `~/.claude/projects/`
- Cleans session artifacts in `~/.claude/session-env/`, `~/.claude/file-history/`, and `~/.claude/sessions/`
- Removes plan files from `~/.claude/plans/` and per-project `plans/` directories

Conversation deletion removes the `.jsonl` file, its `{uuid}/` subdirectory (subagents, tool-results), all associated session artifacts, and the plan file for that conversation's slug.

Memory deletion removes the individual `.md` file from the project's `memory/` directory.

### Plan status

Plans are derived from the last `ExitPlanMode` tool call per plan slug across all sessions:

| Status | Meaning | Cleanup |
|--------|---------|---------|
| **approved** | User approved the plan (`allowedPrompts` present) | Removable |
| **cancelled** | Plan mode exited with empty input | Removable |
| **pending** | Plan presented but not yet approved or rejected | Kept |

## Guard rules (PreToolUse hooks)

The `guard-rules.py` script and `.md` files are PreToolUse hooks that block dangerous commands before Claude Code's permission system is consulted. Unlike deny-list patterns in `settings.local.json`, these can't be bypassed by reordering flags or using alternative syntax.

| File | Blocks |
|------|--------|
| `guard-rules.py` | Evaluates guard rules, exits 2 to block |
| `hookify.guard-find.md` | `find` with `-exec`, `-execdir`, or `-delete` |
| `hookify.guard-git.md` | `git commit`, `git push`, `git reset --hard` |

### Setup

1. Copy the hook script and rule files to `~/.claude/`:
```
cp guard-rules.py ~/.claude/hooks/
cp hookify.guard-*.md ~/.claude/
```

2. Register the PreToolUse hook in `~/.claude/settings.json`:
```json
"hooks": {
  "PreToolUse": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/guard-rules.py", "timeout": 5}]}]
}
```

3. The rules are active immediately on the next tool use — no restart needed.

### Rule format

Rule files use YAML frontmatter with conditions:
```yaml
---
name: rule-name
enabled: true
event: bash
action: block
conditions:
  - field: command
    operator: regex_match
    pattern: \bgit\b.*\b(commit|push)\b
---
```

Supported operators: `regex_match`, `contains`, `equals`, `starts_with`, `ends_with`.
