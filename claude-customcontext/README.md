# Claude Custom Context

Shell scripts that parse Claude Code's status JSON (`$HOME/.claude/status.json`) and display a **context window usage bar** with model name and percentage — designed for shell prompt integration.

## Files

| File | Description |
|------|-------------|
| `statusline.sh` | Bash script — embedded context window table, no external deps besides `jq` |
| `statusline.ps1` | PowerShell equivalent — reads context sizes from `model-contexts.json` for external maintainability |
| `model-contexts.json` | Shared model→context-window-size mapping (used by the PS1 script; `statusline.sh` has its own copy for portability) |

## Quick Start

### Bash (zsh prompt)
```zsh
# ~/.zshrc
setopt prompt_subst
PR_GIT='$(git rev-parse --abbrev-ref HEAD 2>/dev/null)'
RPROMPT='$(echo $(cat $HOME/.claude/status.json) | jq -c . | ~/path/to/statusline.sh)'
```

### PowerShell
```powershell
# $PROFILE
function prompt { "$( $input | ...\statusline.ps1 ) >" }
```

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
