#!/usr/bin/env python3
"""Unified entry point for the session cleaners: launch the TUI for whichever
tool's data you want to browse and clean up."""

import sys

TOOLS = {
    "claude": "claude_tui.ClaudeCleanerTUI",
    "cursor": "cursor_tui.CursorCleanerTUI",
    "codex": "codex_tui.CodexCleanerTUI",
    "opencode": "opencode_tui.OpencodeCleanerTUI",
    "pi": "pi_tui.PiCleanerTUI",
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in TOOLS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(TOOLS)}>", file=sys.stderr)
        print("\nFor Claude Code's MCP config commands, use claude-mcp.py instead.", file=sys.stderr)
        sys.exit(1)

    module_name, class_name = TOOLS[sys.argv[1]].rsplit(".", 1)
    module = __import__(module_name)
    getattr(module, class_name)().run()


if __name__ == "__main__":
    main()
