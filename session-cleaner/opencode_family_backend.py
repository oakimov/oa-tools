"""Generalized backend for OpenCode-family tools (OpenCode, KiloCode, MiMoCode).

All three share the identical SQLite schema (session/message/part tables with JSON
`data` columns) and ship a native `{tool} import <file>` CLI command that accepts
the same JSON format. This module provides a single parameterized backend whose
functions take a `ToolConfig` describing which tool to operate on.

Env var overrides respected:
  - KiloCode:  KILO_DB       (absolute path, relative to data dir, or :memory:)
  - MiMoCode:  MIMOCODE_DB   (absolute path, relative to data dir, or :memory:)
  - OpenCode:  (none)
"""

import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from transcript_ir import Transcript, TranscriptMessage

# ---------------------------------------------------------------------------
# Tool config
# ---------------------------------------------------------------------------

DEFAULT_PATHS = {
    "OpenCode": {
        "data_dir": os.path.expanduser("~/.local/share/opencode"),
        "db_filename": "opencode.db",
        "import_binary": "opencode",
    },
    "KiloCode": {
        "data_dir": os.path.expanduser("~/.local/share/kilo"),
        "db_filename": "kilo.db",
        "import_binary": "kilo",
        "env_var": "KILO_DB",
    },
    "MiMoCode": {
        "data_dir": os.path.expanduser("~/.local/share/mimocode"),
        "db_filename": "mimocode.db",
        "import_binary": "mimo",
        "env_var": "MIMOCODE_DB",
    },
}


@dataclass
class ToolConfig:
    display_name: str          # "OpenCode" | "KiloCode" | "MiMoCode"
    data_dir: str              # resolved absolute path
    db_path: str               # resolved absolute path to SQLite DB
    import_binary: str         # "opencode" | "kilo" | "mimo"


def resolve_tool_config(display_name: str) -> ToolConfig:
    defaults = DEFAULT_PATHS.get(display_name)
    if not defaults:
        raise ValueError(f"Unknown tool: {display_name}")

    data_dir = defaults["data_dir"]
    db_path = os.path.join(data_dir, defaults["db_filename"])

    env_var = defaults.get("env_var")
    if env_var:
        override = os.environ.get(env_var, "")
        if override:
            if override == ":memory:":
                db_path = ":memory:"
            elif os.path.isabs(override):
                db_path = override
            else:
                db_path = os.path.join(data_dir, override)

    return ToolConfig(
        display_name=display_name,
        data_dir=data_dir,
        db_path=db_path,
        import_binary=defaults["import_binary"],
    )


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OcodeSession:
    session_id: str
    directory: str
    title: str
    time_created: int
    time_updated: int
    message_count: int = 0
    total_size: int = 0


@dataclass
class OcodeProject:
    display_name: str
    sessions: List[OcodeSession] = field(default_factory=list)
    total_size: int = 0


UNKNOWN_PROJECT = "(unknown)"

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_conn_cache: Dict[str, sqlite3.Connection] = {}


def _get_db(cfg: ToolConfig) -> sqlite3.Connection:
    key = cfg.db_path
    if key not in _conn_cache:
        if key == ":memory:":
            conn = sqlite3.connect(":memory:")
        else:
            if not os.path.isfile(key):
                raise SystemExit(f"{cfg.display_name} database not found at {key}")
            conn = sqlite3.connect(key)
        conn.row_factory = sqlite3.Row
        _conn_cache[key] = conn
    return _conn_cache[key]


def _clear_cache() -> None:
    _conn_cache.clear()


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_sessions(cfg: ToolConfig) -> List[OcodeSession]:
    db = _get_db(cfg)
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
        sessions.append(OcodeSession(
            session_id=row["id"],
            directory=row["directory"] or "",
            title=row["title"] or "",
            time_created=row["time_created"] or 0,
            time_updated=row["time_updated"] or 0,
            message_count=row["msg_count"] or 0,
            total_size=size,
        ))
    return sessions


def scan_projects(cfg: ToolConfig) -> List[OcodeProject]:
    sessions = scan_sessions(cfg)
    by_dir: Dict[str, List[OcodeSession]] = {}
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
        projects.append(OcodeProject(
            display_name=display,
            sessions=sess,
            total_size=sum(s.total_size for s in sess),
        ))

    projects.sort(key=lambda p: p.total_size, reverse=True)
    return projects


def get_session_messages(cfg: ToolConfig, session_id: str) -> List[dict]:
    db = _get_db(cfg)
    msg_rows = db.execute(
        "SELECT id, data, time_created FROM message WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    ).fetchall()

    part_rows = db.execute(
        "SELECT message_id, data, time_created FROM part WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    ).fetchall()

    text_by_message: Dict[str, List[str]] = {}
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
            from common import format_tool_call, format_tool_result
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
# Transcript export/import
# ---------------------------------------------------------------------------


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(13)}"


def _current_tool_version(cfg: ToolConfig) -> str:
    try:
        out = subprocess.run(
            [cfg.import_binary, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def _parse_iso_to_ms(ts: str, fallback_ms: int) -> int:
    if ts:
        try:
            return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pass
    return fallback_ms


def export_transcript(cfg: ToolConfig, session_id: str) -> Transcript:
    db = _get_db(cfg)
    session_row = db.execute(
        "SELECT id, directory, title, time_created, time_updated FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not session_row:
        raise ValueError(f"Session {session_id} not found in {cfg.display_name}")

    cwd = session_row["directory"] or ""
    title = session_row["title"] or ""
    created_ms = session_row["time_created"] or 0
    updated_ms = session_row["time_updated"] or 0

    def ms_to_iso(ms: int) -> str:
        if ms:
            try:
                return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
            except (ValueError, OverflowError):
                pass
        return ""

    msg_rows = db.execute(
        "SELECT id, data, time_created FROM message WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    ).fetchall()

    part_rows = db.execute(
        "SELECT message_id, data, time_created FROM part WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    ).fetchall()

    parts_by_message: Dict[str, List[dict]] = {}
    for row in part_rows:
        try:
            parts_by_message.setdefault(row["message_id"], []).append(json.loads(row["data"]))
        except (json.JSONDecodeError, TypeError):
            pass

    ir_messages: List[TranscriptMessage] = []
    for msg_row in msg_rows:
        try:
            msg_data = json.loads(msg_row["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        role = msg_data.get("role", "assistant")
        ts = ms_to_iso(msg_row["time_created"])
        parts = parts_by_message.get(msg_row["id"], [])

        for part in parts:
            ptype = part.get("type", "")
            if ptype == "text":
                text = part.get("text", "")
                if text:
                    ir_messages.append(TranscriptMessage(role=role, kind="text", text=text, timestamp=ts))
            elif ptype == "reasoning":
                text = part.get("text", "")
                if text:
                    ir_messages.append(TranscriptMessage(role=role, kind="thinking", text=text, timestamp=ts))
            elif ptype == "tool":
                tool_name = part.get("tool", "?")
                state = part.get("state", {})
                inp = state.get("input", {})
                ir_messages.append(TranscriptMessage(
                    role=role, kind="tool_call",
                    tool_name=tool_name,
                    tool_input=inp if isinstance(inp, dict) else {"_raw": str(inp)},
                    timestamp=ts,
                ))
                output = state.get("output", "")
                if output:
                    ir_messages.append(TranscriptMessage(
                        role=role, kind="tool_result",
                        text=output if isinstance(output, str) else json.dumps(output),
                        timestamp=ts,
                    ))

    return Transcript(
        source_tool=cfg.display_name.lower(),
        session_id=session_id,
        title=title or session_id[:12],
        cwd=cwd,
        created_at=ms_to_iso(created_ms),
        updated_at=ms_to_iso(updated_ms),
        messages=ir_messages,
    )


def import_transcript(cfg: ToolConfig, transcript: Transcript, target_cwd: str) -> str:
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
            "version": _current_tool_version(cfg),
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
            [cfg.import_binary, "import", tmp_path],
            capture_output=True, text=True, timeout=30, cwd=target_cwd,
        )
        if result.returncode != 0:
            db = _get_db(cfg)
            if db.execute("SELECT 1 FROM session WHERE id = ?", (session_id,)).fetchone():
                delete_session(cfg, session_id)
            raise RuntimeError(f"{cfg.import_binary} import failed: {result.stderr or result.stdout}")
    finally:
        os.remove(tmp_path)

    return session_id


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

_CHILD_TABLES = (
    "part",
    "message",
    "todo",
    "session_input",
    "session_context_epoch",
    "session_message",
    "session_share",
)


def delete_session(cfg: ToolConfig, session_id: str) -> dict:
    db = _get_db(cfg)
    stats: Dict[str, int] = {table: 0 for table in _CHILD_TABLES}
    stats["session"] = 0

    for table in _CHILD_TABLES:
        cur = db.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
        stats[table] = cur.rowcount

    cur = db.execute("DELETE FROM session WHERE id = ?", (session_id,))
    stats["session"] = cur.rowcount
    db.commit()

    return stats


def delete_sessions(cfg: ToolConfig, session_ids: List[str]) -> dict:
    total: Dict[str, int] = {"sessions": 0, "messages": 0, "parts": 0}
    for sid in session_ids:
        r = delete_session(cfg, sid)
        total["sessions"] += r["session"]
        total["messages"] += r["message"]
        total["parts"] += r["part"]
    return total
