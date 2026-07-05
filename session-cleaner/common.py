"""Low-level utilities shared by every backend and TUI: sizes, timestamps,
JSON I/O, and path-safety checks."""

import json
import os
from datetime import datetime, timezone


def format_size(sz: int) -> str:
    if sz < 1024:
        return f"{sz}B"
    elif sz < 1024 * 1024:
        return f"{sz / 1024:.0f}K"
    else:
        return f"{sz / 1024 / 1024:.1f}M"


def format_date_short(ts: str) -> str:
    """Format an ISO-8601 timestamp as a short absolute date (e.g. 'Jul 04')."""
    if not ts or len(ts) < 10:
        return ts[:10] if ts else ""
    try:
        dt = datetime.fromisoformat(ts[:19])
        now = datetime.now()
        if (now - dt).days > 180:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%b %d")
    except (ValueError, OverflowError):
        return ts[:10]


def format_relative(dt: datetime) -> str:
    """Format a timezone-aware datetime as a short relative string (e.g. '2h ago')."""
    now = datetime.now(timezone.utc)
    days = (now - dt).days
    if days > 180:
        return dt.strftime("%Y-%m-%d")
    elif days > 14:
        return dt.strftime("%b %d")
    elif days > 1:
        return f"{days}d ago"
    elif days == 1:
        return "yesterday"
    h = (now - dt).seconds // 3600
    if h > 1:
        return f"{h}h ago"
    m = max(1, (now - dt).seconds // 60)
    return f"{m}m ago"


def format_relative_ms(ms: int) -> str:
    """Format a unix-ms timestamp as a short relative string."""
    if not ms:
        return ""
    try:
        return format_relative(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))
    except (ValueError, OverflowError):
        return str(ms)


def format_message_timestamp(ts) -> str:
    """Format a transcript-message timestamp for display. Accepts either an
    ISO-8601 string (Claude/Cursor/Codex — sliced to seconds) or a unix-ms
    int (OpenCode)."""
    if not ts:
        return ""
    if isinstance(ts, (int, float)):
        return format_relative_ms(int(ts))
    return str(ts)[:19]


def load_json_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json_file(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def is_within(parent: str, child: str) -> bool:
    """Check that child path resolves within parent directory."""
    return os.path.realpath(child).startswith(os.path.realpath(parent) + os.sep)


def strip_top_lines(text: str, n: int = 5) -> str:
    """Drop the first n lines of a tool-output block — trims the boilerplate
    preamble tools like Codex's exec_command prepend (chunk id, wall time,
    exit code, token count, an "Output:" marker) before the real content."""
    if not text:
        return text
    lines = text.split("\n")
    if len(lines) <= n:
        return text
    return "\n".join(lines[n:])


def format_tool_call(name: str, args) -> str:
    """Render a tool invocation (name + arguments) as a display block."""
    if isinstance(args, dict):
        arg_str = args["command"] if "command" in args else json.dumps(args, ensure_ascii=False)
    elif isinstance(args, str):
        arg_str = args
    else:
        arg_str = str(args)
    return f"[tool call] {name}: {arg_str}"


def format_tool_result(output) -> str:
    """Render a tool result/output block, trimming its noisy leading lines."""
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return "[tool result]\n" + strip_top_lines(text, 5)
