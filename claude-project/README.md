# claude-project

Tools for managing Claude Code project data.

## Architecture

| File | Purpose |
|------|---------|
| `claude_shared.py` | Shared library: constants, config I/O, path encoding, data model, scanning, deletion, and the `CleanerTUI` class. All other scripts import from here. TUI dependencies (`prompt_toolkit`) are guarded — non-TUI commands work without it. |
| `claude-mcp.py` | CLI for MCP server management and project cleanup. Imports `CleanerTUI` directly for the `tui` subcommand. |
| `claude-cleaner.py` | Thin entry point (3 lines) that calls `CleanerTUI().run()`. Kept for direct execution (`python claude-cleaner.py`). |
| `settings-propagate.py` | Propagates default permissions and skill overrides to all `.claude/settings.local.json` files. Uses shared JSON I/O from `claude_shared.py`. |
| `settings.local.json` | Canonical defaults file used by `settings-propagate.py`. |

## Guard Rules: cc-safety-net

Dangerous commands (`git push --force`, `git reset --hard`, `find -delete`, `rm -rf` outside cwd, shell wrappers, interpreter one-liners) are blocked by the [cc-safety-net](https://github.com/kenryu42/claude-code-safety-net) plugin (1.3k stars, active).

Install once, applies to all projects:

```
/plugin marketplace add kenryu42/cc-marketplace
/plugin install safety-net@cc-marketplace
/reload-plugins
```

Custom rules (user-wide, central location): `~/.cc-safety-net/config.json`. Run `npx cc-safety-net doctor` to verify installation.

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

## CleanerTUI (in claude_shared.py)

Cross-project session, memory, and plan browser/cleanup TUI. Scans all projects
in `~/.claude/projects/` and provides a keyboard-driven interface to browse and
delete conversations, memories, plans, and entire project directories.

Launched via `claude-mcp.py tui` or `python claude-cleaner.py`.

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

## settings-propagate.py

Propagates a canonical `settings.local.json` (permissions and skill overrides) to all `.claude/settings.local.json` files under a directory tree.

```
python settings-propagate.py [--dry-run] [--defaults-file PATH] [search_root]
```

- `search_root`: directory to scan (default: `~`)
- `--defaults-file`: JSON file with canonical settings (default: `settings.local.json` next to script)
- `--dry-run`: show what would change without writing

Permissions are merged (additive — new entries added, existing preserved). Skill overrides are replaced entirely with the defaults.

## Unified deletion

Both the CLI and TUI perform the same unified deletion when removing a project:
- Removes the entry from `~/.claude.json`
- Removes the project directory under `~/.claude/projects/`
- Cleans session artifacts in `~/.claude/session-env/`, `~/.claude/file-history/`, and `~/.claude/sessions/`
- Removes plan files from `~/.claude/plans/` and per-project `plans/` directories

Conversation deletion removes the `.jsonl` file, its `{uuid}/` subdirectory (subagents, tool-results), all associated session artifacts, and the plan file for that conversation's slug.

Memory deletion removes the individual `.md` file from the project's `memory/` directory. Path containment is verified before deletion.

## Plan status

Plans are derived from the last `ExitPlanMode` tool call per plan slug across all sessions:

| Status | Meaning | Cleanup |
|--------|---------|---------|
| **approved** | User approved the plan (`allowedPrompts` present) | Removable |
| **cancelled** | Plan mode exited with empty input | Removable |
| **pending** | Plan presented but not yet approved or rejected | Kept |

## Safety

- `load_config()` handles missing `.claude.json` gracefully (returns `{}`) and raises with context for corrupt JSON
- Path containment checks (`_is_within`) guard all file deletions against path traversal
- Plan file deletion validates paths resolve within `~/.claude/plans/` or `~/.claude/projects/`
- Memory deletion validates paths resolve within `~/.claude/projects/`
- TOCTOU protection in project rescanning (handles files deleted between listing and access)
- `settings-propagate.py` validates `search_root` exists before walking
- Scan failures log warnings to stderr instead of silently swallowing exceptions
