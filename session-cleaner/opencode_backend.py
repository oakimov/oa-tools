"""OpenCode session data model, scanning, and deletion logic.

OpenCode stores everything in one SQLite database
(~/.local/share/opencode/opencode.db): `session` rows carry the working
directory a session ran in directly (unlike Codex, no need to peek into a
transcript file), `message`/`part` hold the conversation turns, and a handful
of small side tables (`todo`, `session_input`, `session_context_epoch`,
`session_message`, `session_share`) hold session-scoped extras that all
cascade off `session.id`. A parallel per-session diff file lives under
storage/session_diff/{session_id}.json.
"""

import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from typing import List

from common import format_tool_call, format_tool_result

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OPENCODE_DIR = os.path.expanduser("~/.local/share/opencode")
DB_PATH = os.path.join(OPENCODE_DIR, "opencode.db")
SESSION_DIFF_DIR = os.path.join(OPENCODE_DIR, "storage", "session_diff")

UNKNOWN_PROJECT = "(unknown)"

# Session-scoped tables that key off session_id but aren't declared with a
# cascading FK we can rely on (SQLite only cascades if foreign_keys is ON for
# the connection) — deleted explicitly, in child-before-parent order.
_CHILD_TABLES = (
    "part",
    "message",
    "todo",
    "session_input",
    "session_context_epoch",
    "session_message",
    "session_share",
)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OpencodeSession:
    session_id: str
    directory: str
    title: str
    time_created: int  # unix ms
    time_updated: int  # unix ms
    message_count: int = 0
    total_size: int = 0


@dataclass
class OpencodeProject:
    display_name: str
    sessions: List[OpencodeSession] = field(default_factory=list)
    total_size: int = 0

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_conn = None


def _get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        if not os.path.isfile(DB_PATH):
            raise SystemExit(f"OpenCode database not found at {DB_PATH}")
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
    return _conn


def _diff_path(session_id: str) -> str:
    return os.path.join(SESSION_DIFF_DIR, session_id + ".json")


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_sessions() -> List[OpencodeSession]:
    db = _get_db()
    rows = db.execute(
        """
        SELECT s.id, s.directory, s.title, s.time_created, s.time_updated,
               (SELECT COUNT(*) FROM message m WHERE m.session_id = s.id) AS msg_count,
               (SELECT COALESCE(SUM(LENGTH(data)), 0) FROM message m WHERE m.session_id = s.id) AS msg_size,
               (SELECT COALESCE(SUM(LENGTH(data)), 0) FROM part p WHERE p.session_id = s.id) AS part_size
        FROM session s
        ORDER BY s.time_updated DESC
        """
    ).fetchall()

    sessions = []
    for row in rows:
        size = (row["msg_size"] or 0) + (row["part_size"] or 0)
        diff_path = _diff_path(row["id"])
        if os.path.isfile(diff_path):
            try:
                size += os.path.getsize(diff_path)
            except OSError:
                pass
        sessions.append(OpencodeSession(
            session_id=row["id"],
            directory=row["directory"] or "",
            title=row["title"] or "",
            time_created=row["time_created"] or 0,
            time_updated=row["time_updated"] or 0,
            message_count=row["msg_count"] or 0,
            total_size=size,
        ))
    return sessions


def scan_projects() -> List[OpencodeProject]:
    """Group sessions by the directory they ran in, mirroring Claude/Cursor/
    Codex's project-list view."""
    sessions = scan_sessions()
    by_dir = {}
    home = os.path.expanduser("~")
    for s in sessions:
        key = s.directory or UNKNOWN_PROJECT
        by_dir.setdefault(key, []).append(s)

    projects = []
    for directory, sess in by_dir.items():
        display = directory
        if display != UNKNOWN_PROJECT and display.startswith(home):
            display = "~" + display[len(home):]
        sess.sort(key=lambda s: s.time_updated or 0, reverse=True)
        projects.append(OpencodeProject(
            display_name=display,
            sessions=sess,
            total_size=sum(s.total_size for s in sess),
        ))

    projects.sort(key=lambda p: p.total_size, reverse=True)
    return projects


def get_session_messages(session_id: str) -> List[dict]:
    """Return the user/assistant message turns for a session, oldest first."""
    db = _get_db()
    msg_rows = db.execute(
        "SELECT id, data, time_created FROM message WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    ).fetchall()

    part_rows = db.execute(
        "SELECT message_id, data, time_created FROM part WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    ).fetchall()

    text_by_message = {}
    for row in part_rows:
        try:
            part = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        ptype = part.get("type")
        if ptype == "text":
            text = part.get("text", "")
        elif ptype == "reasoning":
            text = f"[thinking] {part.get('text', '')}"
        elif ptype == "tool":
            state = part.get("state", {})
            text = format_tool_call(part.get("tool", "?"), state.get("input", {}))
            if state.get("output"):
                text += "\n" + format_tool_result(state["output"])
        else:
            continue
        if not text:
            continue
        text_by_message.setdefault(row["message_id"], []).append(text)

    messages = []
    for row in msg_rows:
        try:
            msg = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        role = msg.get("role", "?")
        if role not in ("user", "assistant"):
            continue
        texts = text_by_message.get(row["id"], [])
        if not texts:
            continue
        messages.append({
            "role": role.upper(),
            "text": "\n".join(texts),
            "timestamp": msg.get("time", {}).get("created"),
        })
    return messages


# ---------------------------------------------------------------------------
# Transcript import (cross-tool converter — see
# plans/transcript-converter-plan.md)
# ---------------------------------------------------------------------------

def _gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(13)}"


def _current_opencode_version() -> str:
    try:
        import subprocess
        out = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def _parse_iso_to_ms(ts: str, fallback_ms: int) -> int:
    if ts:
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pass
    return fallback_ms


def import_transcript(transcript, target_cwd: str) -> str:
    """Import a Transcript IR by shelling out to OpenCode's own `opencode
    import <file>` CLI command, rather than hand-crafting SQLite rows —
    OpenCode ships native `export`/`import` commands (discovered via
    `opencode --help`) that produce/consume exactly this
    {"info": {...}, "messages": [{"info": {...}, "parts": [...]}]} shape
    (confirmed against a real `opencode export` of an existing session).
    Using the tool's own importer guarantees compatibility with whatever
    schema the installed version actually expects — far more robust than
    reverse-engineered direct SQLite writes. Requires `opencode` on PATH.
    Returns the new session id.

    tool_call + the tool_result that follows it are merged into one
    native "tool" part (state.input/state.output) — OpenCode keeps call
    and result together, like Cursor, unlike Claude/Codex/pi.dev's
    separate events."""
    import subprocess
    import tempfile

    session_id = _gen_id("ses")
    base_ms = int(time.time() * 1000)
    counter = 0

    def next_ms(ts=None):
        nonlocal counter
        counter += 1
        return (_parse_iso_to_ms(ts, base_ms) if ts else base_ms) + counter

    messages = []
    last_user_msg_id = None
    for msg in transcript.messages:
        if msg.kind == "tool_result":
            # merge into the immediately preceding tool part's state.output
            if messages and messages[-1]["parts"]:
                last_part = messages[-1]["parts"][-1]
                if last_part.get("type") == "tool":
                    last_part.setdefault("state", {})["output"] = msg.text
            continue

        role = msg.role if msg.role in ("user", "assistant") else "assistant"
        msg_id = _gen_id("msg")
        msg_ms = next_ms(msg.timestamp)
        part_id = _gen_id("prt")

        if msg.kind == "text":
            part = {"type": "text", "text": msg.text}
        elif msg.kind == "thinking":
            part = {"type": "reasoning", "text": msg.text}
        elif msg.kind == "tool_call":
            part = {
                "type": "tool",
                "tool": msg.tool_name or "?",
                "callID": _gen_id("call"),
                "state": {
                    "status": "completed", "input": msg.tool_input or {}, "output": "",
                    "title": msg.tool_name or "?", "metadata": {}, "time": {"start": msg_ms, "end": msg_ms},
                },
            }
        else:
            part = {"type": "text", "text": msg.text}

        part.update({"id": part_id, "sessionID": session_id, "messageID": msg_id})

        # Full field set observed in a real `opencode export` — required
        # keys vary by role (assistant needs path/cost/tokens/modelID/
        # providerID; user needs model/agent), so both get the whole shape
        # with neutral defaults rather than guessing the minimal subset.
        if role == "assistant":
            msg_info = {
                "id": msg_id, "sessionID": session_id, "role": role,
                "parentID": last_user_msg_id,
                "mode": "build", "agent": "build",
                "path": {"cwd": target_cwd, "root": target_cwd},
                "cost": 0,
                "tokens": {"total": 0, "input": 0, "output": 0, "reasoning": 0,
                           "cache": {"read": 0, "write": 0}},
                "modelID": "imported", "providerID": transcript.source_tool,
                "time": {"created": msg_ms, "completed": msg_ms},
                "finish": "stop",
            }
        else:
            msg_info = {
                "id": msg_id, "sessionID": session_id, "role": role,
                "agent": "build",
                "model": {"providerID": transcript.source_tool, "modelID": "imported"},
                "time": {"created": msg_ms},
            }
            last_user_msg_id = msg_id

        messages.append({"info": msg_info, "parts": [part]})

    export_data = {
        "info": {
            "id": session_id,
            "slug": f"imported-{session_id[-8:]}",
            "directory": target_cwd,
            "path": "",
            "title": transcript.title or "Imported transcript",
            "agent": "build",
            "model": {"id": "imported", "providerID": transcript.source_tool, "variant": "default"},
            "version": _current_opencode_version(),
            "summary": {"additions": 0, "deletions": 0, "files": 0},
            "cost": 0,
            "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            "time": {"created": base_ms, "updated": base_ms},
        },
        "messages": messages,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(export_data, f)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["opencode", "import", tmp_path],
            capture_output=True, text=True, timeout=30, cwd=target_cwd,
        )
        if result.returncode != 0:
            # `opencode import` is not atomic on failure — it can commit the
            # session row (and some messages) before hitting a later
            # validation error, leaving an orphaned partial session behind.
            # Clean it up rather than leaving broken debris.
            db = _get_db()
            if db.execute("SELECT 1 FROM session WHERE id = ?", (session_id,)).fetchone():
                delete_session(session_id)
            raise RuntimeError(f"opencode import failed: {result.stderr or result.stdout}")
    finally:
        os.remove(tmp_path)

    return session_id


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_session(session_id: str) -> dict:
    """Delete a session and every artifact scoped to it. Returns stats."""
    db = _get_db()
    stats = {table: 0 for table in _CHILD_TABLES}
    stats["session"] = 0
    stats["diff_file"] = 0

    for table in _CHILD_TABLES:
        cur = db.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
        stats[table] = cur.rowcount

    cur = db.execute("DELETE FROM session WHERE id = ?", (session_id,))
    stats["session"] = cur.rowcount
    db.commit()

    diff_path = _diff_path(session_id)
    if os.path.isfile(diff_path):
        stats["diff_file"] = os.path.getsize(diff_path)
        os.remove(diff_path)

    return stats


def delete_sessions(session_ids: List[str]) -> dict:
    """Delete multiple sessions. Returns aggregate stats."""
    total = {"sessions": 0, "messages": 0, "parts": 0, "bytes": 0}
    for sid in session_ids:
        r = delete_session(sid)
        total["sessions"] += r["session"]
        total["messages"] += r["message"]
        total["parts"] += r["part"]
        total["bytes"] += r["diff_file"]
    return total
