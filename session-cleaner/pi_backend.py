"""pi.dev agent session data model, scanning, and deletion logic.

pi.dev stores each session as a standalone JSONL file under
~/.pi/agent/sessions/{encoded-cwd}/{timestamp}_{uuid}.jsonl — sessions are
already grouped one directory per project, unlike Codex/OpenCode's flat
layout. The directory name encodes the cwd path (slashes as dashes, wrapped
in a leading/trailing "--"), but the authoritative cwd is read from each
session file's leading `session` event instead of decoded from the
directory name, mirroring how Claude Code and Codex resolve project paths.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from common import format_tool_call, format_tool_result

PI_AGENT_DIR = os.path.expanduser("~/.pi/agent")
SESSIONS_DIR = os.path.join(PI_AGENT_DIR, "sessions")

UNKNOWN_PROJECT = "(unknown)"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PiSession:
    session_id: str
    file_path: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    file_size: int = 0


@dataclass
class PiProject:
    display_name: str
    dir_path: str
    sessions: List[PiSession] = field(default_factory=list)
    total_size: int = 0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _read_jsonl_lines(path: str):
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return

# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_session_file(path: str) -> Optional[PiSession]:
    session_id = ""
    created_at = ""
    updated_at = ""
    title = ""
    message_count = 0

    for obj in _read_jsonl_lines(path):
        ts = obj.get("timestamp", "")
        if ts:
            updated_at = ts
        t = obj.get("type")
        if t == "session":
            session_id = obj.get("id", "")
            created_at = ts or created_at
        elif t == "message":
            message_count += 1
            if not title:
                msg = obj.get("message", {})
                if msg.get("role") == "user":
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text:
                                title = text[:60]
                                break

    if not session_id:
        base = os.path.splitext(os.path.basename(path))[0]
        parts = base.split("_", 1)
        session_id = parts[1] if len(parts) == 2 else base

    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0

    return PiSession(
        session_id=session_id,
        file_path=path,
        title=title,
        created_at=created_at,
        updated_at=updated_at or created_at,
        message_count=message_count,
        file_size=size,
    )


def _resolve_project_cwd(dir_path: str) -> str:
    """Read the real cwd from any session file's leading event; fall back to
    decoding the directory name if none is found."""
    for fname in sorted(os.listdir(dir_path)):
        if not fname.endswith(".jsonl"):
            continue
        for obj in _read_jsonl_lines(os.path.join(dir_path, fname)):
            if obj.get("type") == "session" and obj.get("cwd"):
                return obj["cwd"]
            break  # only the first line of each file is worth checking
    encoded = os.path.basename(dir_path).strip("-")
    return "/" + encoded.replace("-", "/") if encoded else UNKNOWN_PROJECT


def scan_projects() -> List[PiProject]:
    projects = []
    if not os.path.isdir(SESSIONS_DIR):
        return projects

    home = os.path.expanduser("~")
    for entry in sorted(os.listdir(SESSIONS_DIR)):
        dir_path = os.path.join(SESSIONS_DIR, entry)
        if not os.path.isdir(dir_path):
            continue

        sessions = []
        for fname in os.listdir(dir_path):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(dir_path, fname)
            if not os.path.isfile(fpath):
                continue
            s = scan_session_file(fpath)
            if s:
                sessions.append(s)

        if not sessions:
            continue

        cwd = _resolve_project_cwd(dir_path)
        display = cwd
        if display != UNKNOWN_PROJECT and display.startswith(home):
            display = "~" + display[len(home):]

        sessions.sort(key=lambda s: s.updated_at or "", reverse=True)
        projects.append(PiProject(
            display_name=display,
            dir_path=dir_path,
            sessions=sessions,
            total_size=sum(s.file_size for s in sessions),
        ))

    projects.sort(key=lambda p: p.total_size, reverse=True)
    return projects


def get_session_messages(session: PiSession) -> List[dict]:
    messages = []
    for obj in _read_jsonl_lines(session.file_path):
        if obj.get("type") != "message":
            continue
        msg = obj.get("message", {})
        role = msg.get("role", "?")
        if role == "toolResult":
            text = format_tool_result(_extract_pi_text(msg.get("content", [])))
            messages.append({"role": "TOOL", "text": text, "timestamp": obj.get("timestamp", "")})
            continue
        if role not in ("user", "assistant"):
            continue
        texts = []
        for block in msg.get("content", []):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    texts.append(text)
            elif btype == "toolCall":
                texts.append(format_tool_call(block.get("name", "?"), block.get("arguments", {})))
        if not texts:
            continue
        messages.append({
            "role": role.upper(),
            "text": "\n".join(texts),
            "timestamp": obj.get("timestamp", ""),
        })
    return messages


def _extract_pi_text(content) -> str:
    """Flatten a toolResult message's `content` (list of {"type":"text",...}
    blocks) into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""

# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_session(session: PiSession) -> dict:
    """Delete a session file, cleaning up its parent project directory if
    that was the last session in it."""
    stats = {"file": 0}
    if os.path.isfile(session.file_path):
        stats["file"] = os.path.getsize(session.file_path)
        os.remove(session.file_path)
        parent = os.path.dirname(session.file_path)
        try:
            if parent != SESSIONS_DIR and not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass
    return stats


def delete_sessions(sessions: List[PiSession]) -> dict:
    total = {"sessions": 0, "bytes": 0}
    for s in sessions:
        r = delete_session(s)
        if r["file"]:
            total["sessions"] += 1
            total["bytes"] += r["file"]
    return total
