# claude-project

Tools for managing Claude Code project data.

## claude-project.py

Manage MCP server configuration across projects in `.claude.json`.

Claude Code's `claude.json` stores per-project MCP server settings. This tool
provides CLI commands to inspect and manage those configurations.

| Command | Description |
|---------|-------------|
| `list` | List all registered project paths |
| `check` | Show local `mcpServers` per project |
| `show-enabled` | Show non-disabled servers per project |
| `disable-all` | Disable all MCP servers for all projects |
| `disable <path>` | Disable all MCP servers for a specific project |
| `clean <path>` | Reset `mcpServers` and `disabledMcpServers` for a project |
| `delete <path>` | Delete a project entry |

## claude-cleaner.py

Cross-project session and memory browser/cleanup tool. Scans all projects
in `~/.claude/projects/` and provides a keyboard-driven TUI to browse and
delete conversations, memories, and entire project directories.

### Views

| View | Description |
|------|-------------|
| **Project list** | All projects sorted by total size. Shows conv/memory counts. |
| **Project detail** | VSplit with conversations (date/size sortable) and memories. |
| **Conversation viewer** | Full message history with scroll. Bottom bar shows UUID and size breakdown (chat / subagents / tool results). |
| **Memory viewer** | Memory file body with frontmatter metadata. |
| **Confirm delete** | Confirm prompt before removing any item. |

### Keybindings

| Key | Action |
|-----|--------|
| `↑`/`↓` | Navigate |
| `PgUp`/`PgDn` | Scroll pages in conversation/memory views |
| `Enter` | Open selected item |
| `Tab` | Switch between conversations and memories pane |
| `1` | Sort conversations by date |
| `2` | Sort conversations by size |
| `d` | Delete current item (project / conversation / memory) |
| `y` | Confirm delete |
| `Esc` / `Backspace` | Go back |
| `q` | Quit |

### Delete behavior

- **Conversation** deletion removes the `.jsonl` file, its `{uuid}/` subdirectory (subagents, tool-results), and any associated session artifacts in `~/.claude/session-env/`, `~/.claude/file-history/`, and `~/.claude/sessions/`.
- **Project** deletion removes the entire project directory under `~/.claude/projects/`.
- **Memory** deletion removes the individual `.md` file from the project's `memory/` directory.
