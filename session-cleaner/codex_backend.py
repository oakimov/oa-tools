"""Codex CLI session data model, scanning, and deletion logic.

Codex stores sessions as flat JSONL files under ~/.codex/sessions/, indexed
by ~/.codex/session_index.jsonl and ~/.codex/history.jsonl. Each session file
starts with a `session_meta` (or `turn_context`) event carrying the working
directory the session ran in — that's used here to group sessions into
"projects", mirroring how Claude Code and Cursor group by project folder.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from common import format_tool_call, format_tool_result

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CODEX_DIR = os.path.expanduser("~/.codex")
SESSION_INDEX = os.path.join(CODEX_DIR, "session_index.jsonl")
HISTORY_FILE = os.path.join(CODEX_DIR, "history.jsonl")
SESSIONS_DIR = os.path.join(CODEX_DIR, "sessions")

UNKNOWN_PROJECT = "(unknown)"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CodexSession:
    session_id: str
    thread_name: str
    updated_at: str            # iso timestamp from session_index
    history_count: int = 0     # user message count in history.jsonl
    file_size: int = 0         # bytes of the session jsonl on disk
    file_path: str = ""        # path to the session file, if found
    orphan_file: bool = False  # has file on disk but no index entry
    orphan_index: bool = False  # has index entry but no file on disk
    created_at: str = ""       # extracted from filename if available
    cwd: str = ""              # working directory the session ran in


@dataclass
class CodexProject:
    display_name: str
    sessions: List[CodexSession] = field(default_factory=list)
    total_size: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.rstrip("Z"), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_session_id_from_filename(name: str) -> Optional[str]:
    m = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', name)
    return m.group(1) if m else None


def _extract_created_from_filename(name: str) -> str:
    m = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})', name)
    if m:
        return m.group(1).replace("-", ":", 2).replace("-", ":", 2).replace("-", ":")  # T00-00-00 -> T00:00:00
    return ""


def _extract_cwd(path: str) -> str:
    """Read the working directory from a session file's leading meta lines."""
    try:
        with open(path, "r", errors="replace") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") in ("session_meta", "turn_context"):
                    cwd = obj.get("payload", {}).get("cwd")
                    if cwd:
                        return cwd
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _read_jsonl(path: str) -> List[dict]:
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _write_jsonl(path: str, entries: List[dict]) -> None:
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def scan_sessions() -> List[CodexSession]:
    index_entries = _read_jsonl(SESSION_INDEX)
    index_by_id: dict = {}
    for e in index_entries:
        sid = e.get("id", "")
        if sid:
            existing = index_by_id.get(sid)
            if not existing or (e.get("updated_at", "") >= existing.get("updated_at", "")):
                index_by_id[sid] = e

    history = _read_jsonl(HISTORY_FILE)
    history_counts: dict = {}
    for h in history:
        sid = h.get("session_id", "")
        if sid:
            history_counts[sid] = history_counts.get(sid, 0) + 1

    file_entries: dict = {}  # id -> (path, created_at, size)
    if os.path.isdir(SESSIONS_DIR):
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for fname in files:
                if not fname.endswith(".jsonl"):
                    continue
                sid = _extract_session_id_from_filename(fname)
                if not sid:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    sz = os.path.getsize(fpath)
                except OSError:
                    sz = 0
                created = _extract_created_from_filename(fname)
                existing = file_entries.get(sid)
                if not existing or sz > existing[2]:
                    file_entries[sid] = (fpath, created, sz)

    all_ids = set(index_by_id.keys()) | set(file_entries.keys())
    sessions: List[CodexSession] = []

    for sid in sorted(all_ids):
        ie = index_by_id.get(sid)
        fe = file_entries.get(sid)

        s = CodexSession(
            session_id=sid,
            thread_name=(ie or {}).get("thread_name", "") or "",
            updated_at=(ie or {}).get("updated_at", "") or "",
            history_count=history_counts.get(sid, 0),
            file_size=fe[2] if fe else 0,
            file_path=fe[0] if fe else "",
            created_at=fe[1] if fe else "",
            orphan_file=fe is not None and ie is None,
            orphan_index=ie is not None and fe is None,
        )

        if not s.thread_name:
            for h in history:
                if h.get("session_id") == sid:
                    txt = h.get("text", "")
                    s.thread_name = txt[:60].strip()
                    if s.thread_name:
                        break

        if not s.updated_at:
            created = parse_ts(s.created_at)
            if created:
                s.updated_at = created.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        if s.file_path:
            s.cwd = _extract_cwd(s.file_path)

        sessions.append(s)

    sessions.sort(key=lambda s: s.updated_at or "", reverse=True)
    return sessions


def scan_projects() -> List[CodexProject]:
    """Group sessions by the cwd they ran in, mirroring Claude/Cursor's
    project-list view."""
    sessions = scan_sessions()
    by_cwd: dict = {}
    for s in sessions:
        key = s.cwd or UNKNOWN_PROJECT
        by_cwd.setdefault(key, []).append(s)

    home = os.path.expanduser("~")
    projects = []
    for cwd, sess in by_cwd.items():
        display = cwd
        if display != UNKNOWN_PROJECT and display.startswith(home):
            display = "~" + display[len(home):]
        sess.sort(key=lambda s: s.updated_at or "", reverse=True)
        projects.append(CodexProject(
            display_name=display,
            sessions=sess,
            total_size=sum(s.file_size for s in sess),
        ))

    projects.sort(key=lambda p: p.total_size, reverse=True)
    return projects


def get_session_messages(session: CodexSession) -> List[dict]:
    """Return the user/assistant message turns for a session, oldest first."""
    if not session.file_path or not os.path.isfile(session.file_path):
        return []
    messages = []
    try:
        with open(session.file_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "response_item":
                    continue
                payload = obj.get("payload", {})
                ptype = payload.get("type")
                if ptype == "message":
                    role = payload.get("role", "?")
                    if role not in ("user", "assistant"):
                        continue
                    texts = []
                    for block in payload.get("content", []):
                        if isinstance(block, dict) and block.get("type") in ("input_text", "output_text", "text"):
                            texts.append(block.get("text", ""))
                    text = "\n".join(t for t in texts if t)
                    if not text:
                        continue
                    messages.append({
                        "role": role.upper(),
                        "text": text,
                        "timestamp": obj.get("timestamp", ""),
                    })
                elif ptype == "function_call":
                    args = payload.get("arguments", "")
                    try:
                        args = json.loads(args) if isinstance(args, str) else args
                    except (json.JSONDecodeError, TypeError):
                        pass
                    messages.append({
                        "role": "ASSISTANT",
                        "text": format_tool_call(payload.get("name", "?"), args),
                        "timestamp": obj.get("timestamp", ""),
                    })
                elif ptype == "function_call_output":
                    messages.append({
                        "role": "TOOL",
                        "text": format_tool_result(payload.get("output", "")),
                        "timestamp": obj.get("timestamp", ""),
                    })
    except OSError:
        pass
    return messages


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def _find_session_file_by_id(session_id: str) -> Optional[str]:
    """Find session file on disk by UUID."""
    if not os.path.isdir(SESSIONS_DIR):
        return None
    for root, _dirs, files in os.walk(SESSIONS_DIR):
        for fname in files:
            if session_id in fname and fname.endswith(".jsonl"):
                return os.path.join(root, fname)
    return None


def delete_session(session_id: str) -> dict:
    """Delete a session from all storage layers. Returns stats."""
    stats = {"index": 0, "history": 0, "file": 0}

    if os.path.isfile(SESSION_INDEX):
        entries = _read_jsonl(SESSION_INDEX)
        before = len(entries)
        entries = [e for e in entries if e.get("id") != session_id]
        stats["index"] = before - len(entries)
        _write_jsonl(SESSION_INDEX, entries)

    if os.path.isfile(HISTORY_FILE):
        entries = _read_jsonl(HISTORY_FILE)
        before = len(entries)
        entries = [e for e in entries if e.get("session_id") != session_id]
        stats["history"] = before - len(entries)
        _write_jsonl(HISTORY_FILE, entries)

    fpath = _find_session_file_by_id(session_id)
    if fpath and os.path.isfile(fpath):
        sz = os.path.getsize(fpath)
        os.remove(fpath)
        stats["file"] = sz

        parent = os.path.dirname(fpath)
        while parent and parent != SESSIONS_DIR:
            try:
                if not os.listdir(parent):
                    os.rmdir(parent)
                else:
                    break
            except OSError:
                break
            parent = os.path.dirname(parent)

    return stats


def delete_sessions(session_ids: List[str]) -> dict:
    """Delete multiple sessions. Returns aggregate stats."""
    stats = {"index": 0, "history": 0, "files": 0, "bytes": 0}
    for sid in session_ids:
        r = delete_session(sid)
        stats["index"] += r["index"]
        stats["history"] += r["history"]
        if r["file"]:
            stats["files"] += 1
            stats["bytes"] += r["file"]
    if os.path.isdir(SESSIONS_DIR) and not any(
        f for _, _, files in os.walk(SESSIONS_DIR) for f in files
    ):
        shutil.rmtree(SESSIONS_DIR)
    return stats


def delete_all_sessions() -> dict:
    """Delete all sessions. Returns stats."""
    return delete_sessions([s.session_id for s in scan_sessions()])


def reconcile_sessions() -> dict:
    """Report orphaned index entries and orphaned files (no auto-delete)."""
    sessions = scan_sessions()
    return {
        "file_orphans": sum(1 for s in sessions if s.orphan_file),
        "index_orphans": sum(1 for s in sessions if s.orphan_index),
    }
