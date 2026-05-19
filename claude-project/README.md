# claude-project

Manage MCP server configuration across projects in `.claude.json`.

Claude Code's `claude.json` stores per-project MCP server settings. This tool
provides CLI commands to inspect and manage those configurations.

## Commands

| Command | Description |
|---------|-------------|
| `list` | List all registered project paths |
| `check` | Show local `mcpServers` per project |
| `show-enabled` | Show non-disabled servers per project |
| `disable-all` | Disable all MCP servers for all projects |
| `disable <path>` | Disable all MCP servers for a specific project |
| `clean <path>` | Reset `mcpServers` and `disabledMcpServers` for a project |
| `delete <path>` | Delete a project entry |
