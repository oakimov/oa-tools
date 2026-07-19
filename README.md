# oa-tools

A collection of command-line tools and utilities.

## Projects

| Project | Description |
|---------|-------------|
| [**web-chat**](web-chat/) | Web UI and CLI chat client for OpenAI, Anthropic, and OpenAI-compatible APIs with streaming, model auto-discovery, and dark/light themes. |
| [**session-cleaner**](session-cleaner/) | CLI and TUI tools for browsing and cleaning up session data from Claude Code, Cursor (both IDE and CLI), Codex CLI, OpenCode, and pi.dev. Each tool shares the same project list → conversation list → message deep-dive navigation and unified, all-artifact deletion. Claude Code also gets MCP server config management (`claude-mcp.py`). |
| [**claude-customcontext**](claude-customcontext/) | Context window statusline for Claude Code — shows model name and usage bar in shell prompts. Includes bash and PowerShell scripts with a shared model context-size lookup table. |
| [**zcode-review**](zcode-review/) | Security/telemetry audit of ZCode (3.2.5 base; plugin ABI follow-up 3.3.6). Covers origin, telemetry, network endpoints, privacy controls, providers, and Claude-/Codex-style `.zcode-plugin` marketplace ABI (not `@opencode-ai/plugin`). |
| [**unarchiver**](unarchiver/) | Universal archive extraction utility with interactive TUI. Supports ZIP, 7z, TAR, RAR, ISO, and more via a plugin system. |
| [**pihole.txt**](pihole.txt) | Pi-hole blocklist for ad/tracking domains. |
