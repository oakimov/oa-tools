# Claude Custom Context

Shell scripts that parse Claude Code's status JSON (`$HOME/.claude/status.json`) and display a **context window usage bar** with model name and percentage — designed as a `statusLine` command in Claude Code's settings.

## Files

| File | Description |
|------|-------------|
| `statusline.sh` | Bash script — embedded context window table, no external deps besides `jq` |
| `statusline.ps1` | PowerShell equivalent — reads context sizes from `model-contexts.json` for external maintainability |
| `model-contexts.json` | Shared model→context-window-size mapping (used by the PS1 script; `statusline.sh` has its own copy for portability) |

## Quick Start

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "pwsh -NoLogo -File \"$HOME/.claude/statusline.ps1\"",
    "padding": 2
  }
}
```

For bash (requires `jq`), point the command at `statusline.sh` instead.

## How it works

Both scripts:
1. Read `status.json` from stdin (written by Claude Code on every turn)
2. Extract `model.id`, `context_window.context_window_size`, and token usage
3. Map the model to its known context window size
4. Calculate usage percentage and render a 10-character progress bar

```text
# Example output
[deepseek-v4-flash] ▓▓▓▓▓▓▓░░░ 61%
```
