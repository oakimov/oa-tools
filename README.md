# oa-tools

A collection of command-line tools and utilities.

## Projects

| Project | Description |
|---------|-------------|
| [**web-chat**](web-chat/) | Web UI and CLI chat client for OpenAI, Anthropic, and OpenAI-compatible APIs with streaming, model auto-discovery, and dark/light themes. |
| [**cursor-plan-rebill**](cursor-plan-rebill/) | Rebills a Cursor usage CSV on the current plans at list price, with a weekly pool overflow estimate, to compare them with a legacy plan. |
| [**session-cleaner**](session-cleaner/) | CLI and TUI tools for browsing and cleaning up session data from Claude Code, Cursor (both IDE and CLI), Codex CLI, OpenCode, and pi.dev. Each tool shares the same project list → conversation list → message deep-dive navigation and unified, all-artifact deletion. Claude Code also gets MCP server config management (`claude-mcp.py`). |
| [**claude-customcontext**](claude-customcontext/) | Context window statusline for Claude Code — shows model name and usage bar in shell prompts. Includes bash and PowerShell scripts with a shared model context-size lookup table. |
| [**zcode-review**](zcode-review/) | Security/telemetry audit of ZCode (3.2.5 base; plugin ABI follow-up 3.3.6). Covers origin, telemetry, network endpoints, privacy controls, providers, and Claude-/Codex-style `.zcode-plugin` marketplace ABI (not `@opencode-ai/plugin`). |
| [**mimo-review**](mimo-review/) | Architecture comparison of Xiaomi MiMo Code vs upstream OpenCode — long-horizon harness (memory, checkpoints, compose/workflows, `/goal`, max-mode). |
| [**kilo-review**](kilo-review/) | Architecture comparison of Kilo Code vs upstream OpenCode — dual lineage (Cline/Roo → OpenCode rebuild), Gateway, sandbox, memory, indexing, PostHog telemetry, multi-client IDE/CLI/cloud. |
| [**lockedcode-review**](lockedcode-review/) | Architecture and security-hardening audit of LockedCode (~5 stars, very early stage). Covers OS-level confinement, seven-scanner pipeline, DLP, prompt injection detection, immutable audit trail, policy engine, SANDBOX-AUDIT critical findings, and `@opencode-ai/plugin` host ABI inheritance. |
| [**costrict-review**](costrict-review/) | Architecture/privacy comparison of CoStrict (Sangfor) vs OpenCode — Cline→Roo lineage (not an OpenCode fork), server-assisted Strict Mode workflow, RAG code review, local completion agent, CoStrict Cloud, workspace-trust hardening, and two-channel + raw-conversation/diff telemetry. |
| [**dsh-review**](dsh-review/) | Architecture/security review of DeepSeek Harness (deepseek-ai) — independent Cordis-based "everything is a plugin" agent harness (not an OpenCode fork), OS-enforced sandbox on all three platforms, opt-in default-off telemetry, plugin model vs the OpenCode family, and agent-driven engineering posture. |
| [**unarchiver**](unarchiver/) | Universal archive extraction utility with interactive TUI. Supports ZIP, 7z, TAR, RAR, ISO, and more via a plugin system. |
| [**pihole.txt**](pihole.txt) | Pi-hole blocklist for ad/tracking domains. |