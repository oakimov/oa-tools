"""Cursor AI chat history data model, scanning, and deletion logic.

Covers both Cursor surfaces:
- **IDE**: every conversation in a single global SQLite database, with a side
  JSON file per workspace mapping its hash to a project folder. Message text
  normally lives in plain `bubbleId:*` rows; as a seamless fallback for the
  rare case where it doesn't, `get_bubble_messages` also tries decrypting
  Cursor's `EncryptedBlobStore` format via `cursor_crypt` — see that module
  for the full writeup of the scheme and what it's actually used for.
- **CLI** (`cursor-agent`): one directory per chat under `~/.cursor/chats/`,
  keyed by `md5(workspace path)`, each holding `meta.json` (title/timestamps),
  `prompt_history.json`, and a `store.db` SQLite blob store. Substantial
  chats are additionally mirrored as a plain, fully-readable JSONL transcript
  under `~/.cursor/projects/{slugified-path}/agent-transcripts/{chatId}/` —
  preferred for the message viewer when present, since `store.db`'s blobs are
  a content-addressed Merkle DAG (structural nodes are protobuf and are
  skipped; only the plain-JSON message blobs are read).
"""

import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional

import cursor_crypt
from common import format_tool_call, format_tool_result

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CURSOR_GLOBAL_DB = os.path.expanduser(
    "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
)
WORKSPACE_STORAGE = os.path.expanduser(
    "~/Library/Application Support/Cursor/User/workspaceStorage"
)

CLI_CHATS_DIR = os.path.expanduser("~/.cursor/chats")
CLI_PROJECTS_DIR = os.path.expanduser("~/.cursor/projects")

# Cursor's bubble `type` field: 1 = user turn, 2 = assistant turn.
BUBBLE_TYPE_ROLES = {"1": "USER", "2": "ASSISTANT"}

# "glass" is Cursor's internal namespace for its Background / Local Agent
# feature. A local agent project is a folder grouping agent conversations; its
# state lives across several ItemTable keys plus the content-addressed
# agentKv:blob:* store in cursorDiskKV.
GLASS_LOCAL_PROJECTS = "glass.localAgentProjects.v1"
GLASS_LOCAL_MEMBERSHIP = "glass.localAgentProjectMembership.v1"
GLASS_CLOUD_PROJECTS = "glass.cloudAgentProjects.v1"
GLASS_SELECTED_AGENT = "cursor/glass.selectedAgent"
GLASS_PANEL_PREFIX = "cursor/glass.editorPanelFullscreen/"
GLASS_TABS_PREFIX = "cursor/glass.tabs.v2/"
AGENT_BLOB_PREFIX = "agentKv:blob:"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CursorAgentProject:
    project_id: str
    name: str
    workspace_path: str
    member_ids: List[str] = field(default_factory=list)
    composer_member_ids: List[str] = field(default_factory=list)  # members that are also real chats
    is_archived: bool = False
    created_at: int = 0    # unix ms
    updated_at: int = 0    # unix ms
    attributed_size: int = 0  # bytes of agentKv blobs referencing this project's members


@dataclass
class CursorConversation:
    composer_id: str
    workspace_id: str
    name: str
    created_at: int  # unix ms
    updated_at: int  # unix ms
    is_archived: int
    is_subagent: int
    bubble_count: int = 0
    total_size: int = 0
    project_folder: str = ""
    is_draft: bool = False  # newer Cursor versions: real (non-draft) sessions
    # are worth keeping even when we can't locally read any message content
    # (see scan_conversations' module docstring note on encrypted content).


@dataclass
class CursorWorkspace:
    workspace_id: str
    project_folder: str
    conversations: List[CursorConversation] = field(default_factory=list)
    total_size: int = 0


@dataclass
class CliChat:
    chat_id: str
    workspace_hash: str
    dir_path: str
    title: str
    created_at: int  # unix ms, from meta.json
    updated_at: int  # unix ms, from meta.json
    prompt_count: int = 0
    total_size: int = 0


@dataclass
class CliWorkspace:
    workspace_hash: str
    display_name: str
    chats: List[CliChat] = field(default_factory=list)
    total_size: int = 0

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_conn = None


def _get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        if not os.path.isfile(CURSOR_GLOBAL_DB):
            raise SystemExit(f"Cursor global DB not found at {CURSOR_GLOBAL_DB}")
        _conn = sqlite3.connect(CURSOR_GLOBAL_DB)
        _conn.row_factory = sqlite3.Row
    return _conn


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _load_workspace_folders() -> dict:
    """Map workspace IDs to their project folder paths."""
    mapping = {}
    if not os.path.isdir(WORKSPACE_STORAGE):
        return mapping
    for entry in os.listdir(WORKSPACE_STORAGE):
        wsj = os.path.join(WORKSPACE_STORAGE, entry, "workspace.json")
        if os.path.isfile(wsj):
            try:
                with open(wsj) as f:
                    data = json.load(f)
                folder = data.get("folder", "")
                if folder.startswith("file://"):
                    folder = folder[7:]
                mapping[entry] = folder
            except (json.JSONDecodeError, OSError):
                pass
    return mapping


def _load_composer_headers() -> list:
    """The authoritative, current composer list.

    Newer Cursor versions no longer keep the `composerHeaders` SQL table in
    sync with reality — some real (non-draft) composers exist only in the
    `composer.composerHeaders` blob under ItemTable, which also embeds the
    workspace path directly (`workspaceIdentifier.uri.fsPath`) instead of
    requiring a separate workspaceStorage/*/workspace.json lookup. Returns []
    if this key is absent, signalling callers to fall back to the older
    SQL-table-based scan for not-yet-migrated installs."""
    db = _get_db()
    row = db.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'").fetchone()
    if not row:
        return []
    try:
        blob = json.loads(_astext(row["value"]))
    except (json.JSONDecodeError, TypeError):
        return []
    return blob.get("allComposers", []) or []


def _bubble_counts_and_sizes() -> tuple:
    """Legacy per-composer message store: `bubbleId:{composerId}:{uuid}` keys
    in cursorDiskKV. Newer Cursor versions store conversation content
    encrypted per-composer instead (see `get_bubble_messages`), so this
    yields nothing for those — conversations still surface via `isDraft`,
    just without a browsable transcript or a real size figure."""
    db = _get_db()
    bubble_counts = {}
    bubble_sizes = {}
    for row in db.execute(
        "SELECT key, length(value) FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
    ).fetchall():
        parts = row["key"].split(":", 2)
        if len(parts) >= 2:
            cid = parts[1]
            bubble_counts[cid] = bubble_counts.get(cid, 0) + 1
            bubble_sizes[cid] = bubble_sizes.get(cid, 0) + row["length(value)"]
    return bubble_counts, bubble_sizes


def _build_workspace_list(conv_groups: dict) -> List[CursorWorkspace]:
    workspaces = []
    for wid, convs in conv_groups.items():
        folder = next((c.project_folder for c in convs if c.project_folder), "")
        total = sum(c.total_size for c in convs)
        meaningful = [c for c in convs if c.bubble_count > 0 or c.name or not c.is_draft]
        if not meaningful:
            continue
        display = os.path.basename(os.path.normpath(folder)) if folder else f"[orphan] {wid[:16]}"
        workspaces.append(CursorWorkspace(
            workspace_id=wid,
            project_folder=folder or display,
            conversations=convs,
            total_size=total,
        ))
    workspaces.sort(key=lambda w: w.total_size, reverse=True)
    return workspaces


def _scan_conversations_from_headers(headers: list) -> List[CursorWorkspace]:
    workspace_map = _load_workspace_folders()
    bubble_counts, bubble_sizes = _bubble_counts_and_sizes()

    ws_convs = {}
    for h in headers:
        cid = h.get("composerId")
        if not cid:
            continue
        ident = h.get("workspaceIdentifier") or {}
        wid = ident.get("id") or "unknown"
        folder = (ident.get("uri") or {}).get("fsPath") or workspace_map.get(wid, "")

        conv = CursorConversation(
            composer_id=cid,
            workspace_id=wid,
            name=h.get("subtitle", "") or "",
            created_at=h.get("createdAt", 0) or 0,
            updated_at=h.get("lastUpdatedAt", 0) or h.get("createdAt", 0) or 0,
            is_archived=1 if h.get("isArchived") else 0,
            is_subagent=1 if h.get("isBestOfNSubcomposer") else 0,
            bubble_count=bubble_counts.get(cid, 0),
            total_size=bubble_sizes.get(cid, 0),
            project_folder=folder,
            is_draft=bool(h.get("isDraft")),
        )
        ws_convs.setdefault(wid, []).append(conv)

    return _build_workspace_list(ws_convs)


def _scan_conversations_legacy() -> List[CursorWorkspace]:
    """Fallback for Cursor installs that predate the composer.composerHeaders
    ItemTable blob — reads the composerHeaders SQL table directly."""
    db = _get_db()
    workspace_map = _load_workspace_folders()
    bubble_counts, bubble_sizes = _bubble_counts_and_sizes()

    rows = db.execute(
        "SELECT composerId, workspaceId, createdAt, lastUpdatedAt, "
        "isArchived, isSubagent, value FROM composerHeaders "
        "ORDER BY lastUpdatedAt DESC"
    ).fetchall()

    ws_convs = {}
    for row in rows:
        cid = row["composerId"]
        wid = row["workspaceId"] or "unknown"
        try:
            val = json.loads(row["value"] or "{}")
        except json.JSONDecodeError:
            val = {}

        conv = CursorConversation(
            composer_id=cid,
            workspace_id=wid,
            name=val.get("name", "") or "",
            created_at=row["createdAt"] or 0,
            updated_at=row["lastUpdatedAt"] or 0,
            is_archived=row["isArchived"] or 0,
            is_subagent=row["isSubagent"] or 0,
            bubble_count=bubble_counts.get(cid, 0),
            total_size=bubble_sizes.get(cid, 0),
            project_folder=workspace_map.get(wid, ""),
            is_draft=bool(val.get("isDraft")),
        )
        ws_convs.setdefault(wid, []).append(conv)

    return _build_workspace_list(ws_convs)


def scan_conversations() -> List[CursorWorkspace]:
    headers = _load_composer_headers()
    if headers:
        return _scan_conversations_from_headers(headers)
    return _scan_conversations_legacy()


def _composer_encryption_keys(composer_id: str) -> List[str]:
    """Candidate AES key *strings* for this composer, read dynamically from
    its own composerData record — never hardcoded, and different per
    conversation. See cursor_crypt.py for how these become an actual AES key
    and why both fields are tried."""
    db = _get_db()
    row = db.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"composerData:{composer_id}",)).fetchone()
    if not row:
        return []
    try:
        data = json.loads(_astext(row["value"]))
    except (json.JSONDecodeError, TypeError):
        return []
    keys = []
    for field_name in ("blobEncryptionKey", "speculativeSummarizationEncryptionKey"):
        v = data.get(field_name)
        if isinstance(v, str) and v:
            keys.append(v)
    return keys


def _decrypt_composer_blobs(composer_id: str) -> List[dict]:
    """Best-effort fallback for a composer whose messages aren't sitting in
    plain bubbleId rows: try this composer's own dynamically-extracted keys
    (cursor_crypt.decrypt_blob) against every binary blob in the
    content-addressed `composer.content.*` store, and pull out anything that
    both decrypts and parses as a recognizable {role, content} message.
    Silently yields nothing if the `cryptography` package isn't installed,
    the composer has no key, or none of its blobs decrypt under that key
    (e.g. the encryption is gating something other than message text, as
    observed in practice — see cursor_crypt.py)."""
    if not cursor_crypt.HAS_AESGCM:
        return []
    keys = _composer_encryption_keys(composer_id)
    if not keys:
        return []

    db = _get_db()
    messages = []
    for row in db.execute("SELECT value FROM cursorDiskKV WHERE key LIKE 'composer.content.%'").fetchall():
        raw = row["value"]
        if not isinstance(raw, (bytes, bytearray)):
            continue  # already plain text — nothing to decrypt here
        plaintext = None
        for key_str in keys:
            plaintext = cursor_crypt.decrypt_blob(raw, key_str)
            if plaintext is not None:
                break
        if plaintext is None:
            continue
        try:
            obj = json.loads(plaintext)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # decrypted, but not a format we can read further (likely protobuf)
        if not isinstance(obj, dict) or obj.get("role") not in ("user", "assistant"):
            continue
        text = _extract_text(obj.get("content"))
        if not text:
            continue
        messages.append({
            "role": obj["role"].upper(),
            "text": text,
            "timestamp": obj.get("createdAt", ""),
        })
    messages.sort(key=lambda m: m["timestamp"] or "")
    return messages


def _parse_maybe_json(raw):
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _format_tool_bubble(tfd: dict) -> str:
    """Render a bubble's `toolFormerData` (Cursor's tool-call representation
    — call and result live in the same bubble, unlike Claude/Codex/pi.dev's
    separate call/result turns)."""
    name = tfd.get("name", "?")
    parts = [format_tool_call(name, _parse_maybe_json(tfd.get("params", "")))]
    result_raw = tfd.get("result", "")
    if result_raw:
        result = _parse_maybe_json(result_raw)
        output = result.get("contents", result) if isinstance(result, dict) else result
        parts.append(format_tool_result(output))
    return "\n".join(parts)


def get_bubble_messages(composer_id: str) -> List[dict]:
    """Return the message turns for a conversation, oldest first."""
    db = _get_db()
    rows = db.execute(
        "SELECT value FROM cursorDiskKV WHERE key LIKE ?",
        (f"bubbleId:{composer_id}:%",),
    ).fetchall()
    messages = []
    for row in rows:
        try:
            obj = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            continue
        role = BUBBLE_TYPE_ROLES.get(str(obj.get("type", "")), "?")
        text = obj.get("text", "") or ""
        if not text and obj.get("toolFormerData"):
            text = _format_tool_bubble(obj["toolFormerData"])
        messages.append({
            "role": role,
            "text": text,
            "timestamp": obj.get("createdAt", ""),
        })
    messages.sort(key=lambda m: m["timestamp"] or "")
    if messages:
        return messages
    return _decrypt_composer_blobs(composer_id)


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def _remove_composer_id_from_blob(db: sqlite3.Connection, composer_id: str) -> int:
    """Remove a composerId from the ItemTable blob (composer.composerHeaders).
    Returns 1 if removed, 0 if not found."""
    row = db.execute(
        "SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'"
    ).fetchone()
    if not row:
        return 0
    try:
        data = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return 0
    all_c = data.get("allComposers", [])
    before = len(all_c)
    all_c = [c for c in all_c if c.get("composerId") != composer_id]
    if len(all_c) == before:
        return 0
    data["allComposers"] = all_c
    db.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("composer.composerHeaders", json.dumps(data)),
    )
    return 1


def delete_conversation(composer_id: str) -> dict:
    """Delete a conversation and return stats about what was removed."""
    db = _get_db()
    removed = {"composer_header": 0, "bubbles": 0, "checkpoints": 0,
               "blob": 0, "composer_data": 0, "row_heights": 0}

    cur = db.execute("DELETE FROM composerHeaders WHERE composerId = ?", (composer_id,))
    removed["composer_header"] = cur.rowcount

    cur = db.execute(
        "DELETE FROM cursorDiskKV WHERE key LIKE ?", (f"bubbleId:{composer_id}:%",)
    )
    removed["bubbles"] = cur.rowcount

    cur = db.execute(
        "DELETE FROM cursorDiskKV WHERE key LIKE ?", (f"checkpointId:{composer_id}:%",)
    )
    removed["checkpoints"] = cur.rowcount

    cur = db.execute(
        "DELETE FROM cursorDiskKV WHERE key = ?", (f"composerData:{composer_id}",)
    )
    removed["composer_data"] = cur.rowcount

    cur = db.execute(
        "DELETE FROM cursorDiskKV WHERE key = ?",
        (f"composerVirtualRowHeights:{composer_id}",),
    )
    removed["row_heights"] = cur.rowcount

    removed["blob"] = _remove_composer_id_from_blob(db, composer_id)

    db.commit()
    return removed


def reconcile_storage() -> dict:
    """Make all storage layers consistent with the authoritative blob.
    Removes any records in composerHeaders/cursorDiskKV that reference
    composer IDs not present in the ItemTable blob."""
    db = _get_db()

    row = db.execute(
        "SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'"
    ).fetchone()
    if not row:
        return {"error": "no blob found"}
    try:
        blob = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {"error": "corrupt blob"}
    valid_ids = {c["composerId"] for c in blob.get("allComposers", []) if c.get("composerId")}

    if not valid_ids:
        return {"error": "blob has no composers"}

    removed = {"table": 0, "composer_data": 0, "row_heights": 0,
               "bubbles": 0, "checkpoints": 0}

    def _orphan_ids(prefix: str) -> set:
        rows = db.execute(
            "SELECT key FROM cursorDiskKV WHERE key LIKE ?", (f"{prefix}:%",)
        ).fetchall()
        refd = set()
        for (key,) in rows:
            cid = key.split(":", 2)[1]
            if cid not in valid_ids:
                refd.add(cid)
        return refd

    table_orphans = [
        cid for (cid,) in db.execute("SELECT composerId FROM composerHeaders").fetchall()
        if cid not in valid_ids
    ]
    for cid in table_orphans:
        cur = db.execute("DELETE FROM composerHeaders WHERE composerId = ?", (cid,))
        removed["table"] += cur.rowcount

    for prefix, label in [
        ("composerData", "composer_data"),
        ("composerVirtualRowHeights", "row_heights"),
        ("bubbleId", "bubbles"),
        ("checkpointId", "checkpoints"),
    ]:
        for cid in _orphan_ids(prefix):
            like = f"{prefix}:{cid}:%" if label in ("bubbles", "checkpoints") else f"{prefix}:{cid}"
            cur = db.execute(
                "DELETE FROM cursorDiskKV WHERE key LIKE ?", (like,)
            )
            removed[label] += cur.rowcount

    db.commit()
    removed["valid_ids"] = len(valid_ids)
    return removed


def delete_workspace(workspace_id: str) -> dict:
    """Delete all conversations for a workspace. Returns total count."""
    db = _get_db()
    rows = db.execute(
        "SELECT composerId FROM composerHeaders WHERE workspaceId = ?", (workspace_id,)
    ).fetchall()

    total = {"conversations": 0, "bubbles": 0, "checkpoints": 0}
    for (cid,) in rows:
        r = delete_conversation(cid)
        total["conversations"] += r["composer_header"]
        total["bubbles"] += r["bubbles"]
        total["checkpoints"] += r["checkpoints"]

    ws_dir = os.path.join(WORKSPACE_STORAGE, workspace_id)
    if os.path.isdir(ws_dir):
        shutil.rmtree(ws_dir)
        total["workspace_dir"] = ws_dir

    return total


def archive_conversation(composer_id: str, archive: bool = True) -> None:
    db = _get_db()
    db.execute(
        "UPDATE composerHeaders SET isArchived = ? WHERE composerId = ?",
        (1 if archive else 0, composer_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# CLI chats (cursor-agent)
# ---------------------------------------------------------------------------
#
# ~/.cursor/chats/{md5(cwd)}/{chatId}/ holds meta.json, prompt_history.json,
# and store.db (a SQLite `blobs` key-value store). Blobs form a
# content-addressed Merkle DAG: most are protobuf structural nodes (skipped —
# they fail JSON parsing and are simply not displayable), but the actual
# message content is stored as plain JSON blobs ({"role", "content"}).
# Reading them in SQLite rowid (insertion) order reconstructs a coherent,
# chronological transcript without needing to decode the DAG structure.
#
# Substantial chats are additionally mirrored as a fully-readable JSONL
# transcript under ~/.cursor/projects/{slugified-cwd}/agent-transcripts/
# {chatId}/{chatId}.jsonl — preferred when present since it's far simpler
# to parse and already in chronological order.

WORKSPACE_PATH_RE = re.compile(r"Workspace Path:\s*(\S+)")


def _extract_text(content) -> str:
    """Pull display text out of a message's `content`, which is either a
    plain string or a list of blocks — text, tool_use (command/name + args),
    or tool_result (output)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "text":
                parts.append(b.get("text", ""))
            elif btype == "tool_use":
                parts.append(format_tool_call(b.get("name", "?"), b.get("input", {})))
            elif btype == "tool_result":
                parts.append(format_tool_result(_extract_text(b.get("content", ""))))
        return "\n".join(p for p in parts if p)
    return ""


def _slugify_cwd(cwd: str) -> str:
    return cwd.lstrip("/").replace("/", "-")


def _resolve_cli_workspace_cwd(hash_dir: str) -> Optional[str]:
    """Scan any chat's store.db blobs in this workspace for a
    'Workspace Path: X' line — the only place the real cwd is recorded.
    Only JSON-parseable blobs are examined (binary Merkle-DAG structural
    blobs can't contain this and are skipped), and the search runs against
    the *decoded* text so a literal '\\n' inside the JSON string doesn't get
    swept into the match."""
    if not os.path.isdir(hash_dir):
        return None
    for chat_id in sorted(os.listdir(hash_dir)):
        db_path = os.path.join(hash_dir, chat_id, "store.db")
        if not os.path.isfile(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            for (data,) in conn.execute("SELECT data FROM blobs"):
                try:
                    obj = json.loads(_astext(data))
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                text = _extract_text(obj.get("content"))
                m = WORKSPACE_PATH_RE.search(text)
                if m:
                    conn.close()
                    return m.group(1)
            conn.close()
        except sqlite3.Error:
            continue
    return None


def scan_cli_workspaces() -> List[CliWorkspace]:
    workspaces = []
    if not os.path.isdir(CLI_CHATS_DIR):
        return workspaces

    home = os.path.expanduser("~")
    for entry in sorted(os.listdir(CLI_CHATS_DIR)):
        hash_dir = os.path.join(CLI_CHATS_DIR, entry)
        if not os.path.isdir(hash_dir):
            continue

        chats = []
        for chat_id in os.listdir(hash_dir):
            chat_dir = os.path.join(hash_dir, chat_id)
            if not os.path.isdir(chat_dir):
                continue

            meta = {}
            meta_path = os.path.join(chat_dir, "meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                except (OSError, json.JSONDecodeError):
                    meta = {}

            prompt_count = 0
            ph_path = os.path.join(chat_dir, "prompt_history.json")
            if os.path.isfile(ph_path):
                try:
                    with open(ph_path) as f:
                        prompt_count = len(json.load(f))
                except (OSError, json.JSONDecodeError, TypeError):
                    pass

            size = 0
            for dirpath, _dirs, filenames in os.walk(chat_dir):
                for fn in filenames:
                    try:
                        size += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass

            chats.append(CliChat(
                chat_id=chat_id,
                workspace_hash=entry,
                dir_path=chat_dir,
                title=meta.get("title", "") or "",
                created_at=meta.get("createdAtMs", 0) or 0,
                updated_at=meta.get("updatedAtMs", 0) or meta.get("createdAtMs", 0) or 0,
                prompt_count=prompt_count,
                total_size=size,
            ))

        if not chats:
            continue

        cwd = _resolve_cli_workspace_cwd(hash_dir)
        display = cwd or f"(unresolved: {entry[:12]})"
        if cwd and display.startswith(home):
            display = "~" + display[len(home):]

        chats.sort(key=lambda c: c.updated_at, reverse=True)
        workspaces.append(CliWorkspace(
            workspace_hash=entry,
            display_name=display,
            chats=chats,
            total_size=sum(c.total_size for c in chats),
        ))

    workspaces.sort(key=lambda w: w.total_size, reverse=True)
    return workspaces


def _agent_transcript_path(chat: CliChat) -> Optional[str]:
    cwd = _resolve_cli_workspace_cwd(os.path.dirname(chat.dir_path))
    if not cwd:
        return None
    slug = _slugify_cwd(cwd)
    path = os.path.join(CLI_PROJECTS_DIR, slug, "agent-transcripts", chat.chat_id, chat.chat_id + ".jsonl")
    return path if os.path.isfile(path) else None


def _parse_agent_transcript(path: str) -> List[dict]:
    messages = []
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
                role = msg.get("role") or obj.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = _extract_text(msg.get("content"))
                if not text:
                    continue
                messages.append({"role": role.upper(), "text": text, "timestamp": None})
    except OSError:
        return []
    return messages


def _parse_store_db_messages(db_path: str) -> List[dict]:
    messages = []
    if not os.path.isfile(db_path):
        return messages
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT data FROM blobs ORDER BY rowid").fetchall()
        conn.close()
    except sqlite3.Error:
        return messages
    for (data,) in rows:
        try:
            obj = json.loads(_astext(data))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        role = obj.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _extract_text(obj.get("content"))
        if not text:
            continue
        messages.append({"role": role.upper(), "text": text, "timestamp": None})
    return messages


def get_cli_chat_messages(chat: CliChat) -> List[dict]:
    """Prefer the plain-JSONL agent-transcripts mirror when it has real
    message content; fall back to parsing store.db's Merkle-DAG blobs."""
    transcript_path = _agent_transcript_path(chat)
    if transcript_path:
        messages = _parse_agent_transcript(transcript_path)
        if messages:
            return messages
    return _parse_store_db_messages(os.path.join(chat.dir_path, "store.db"))


def delete_cli_chat(chat: CliChat) -> dict:
    """Delete a CLI chat's chats/ directory and its agent-transcripts mirror,
    if any — both are the same session, so leaving either behind is an
    orphan."""
    stats = {"bytes": 0, "transcript_removed": False}
    transcript_path = _agent_transcript_path(chat)

    if os.path.isdir(chat.dir_path):
        stats["bytes"] = chat.total_size
        shutil.rmtree(chat.dir_path)
        parent = os.path.dirname(chat.dir_path)
        try:
            if not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass

    if transcript_path and os.path.isdir(os.path.dirname(transcript_path)):
        transcript_dir = os.path.dirname(transcript_path)
        shutil.rmtree(transcript_dir)
        stats["transcript_removed"] = True

    return stats


def delete_cli_chats(chats: List[CliChat]) -> dict:
    total = {"chats": 0, "bytes": 0, "transcripts": 0}
    for chat in chats:
        r = delete_cli_chat(chat)
        total["chats"] += 1
        total["bytes"] += r["bytes"]
        if r["transcript_removed"]:
            total["transcripts"] += 1
    return total


# ---------------------------------------------------------------------------
# Local agent projects (Cursor "glass" Background Agents)
# ---------------------------------------------------------------------------
#
# A local agent project groups agent conversations. Unlike a regular chat, its
# content is spread across ItemTable index keys and the content-addressed
# agentKv:blob:* store. Some of its "members" are ALSO regular composer chats
# (they have bubbleId:*/composerHeaders data). Deleting an agent project must
# therefore only remove the agent-grouping metadata + agent-only blobs, and
# must never touch a member's real conversation data — that stays a first-class
# chat, reachable and deletable through the normal conversation path.


def _astext(v) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return v or ""


def _load_item(key: str, default):
    """Read and JSON-decode an ItemTable value; return `default` if absent/bad."""
    db = _get_db()
    row = db.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(_astext(row["value"]))
    except (json.JSONDecodeError, TypeError):
        return default


def _load_item_raw(key: str) -> str:
    db = _get_db()
    row = db.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
    return _astext(row["value"]) if row else ""


def _save_item(key: str, data) -> None:
    db = _get_db()
    db.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        (key, json.dumps(data)),
    )


def _composer_ids() -> set:
    """IDs of all real composer chats (so agent members that overlap can be
    flagged and preserved)."""
    db = _get_db()
    return {r["composerId"] for r in db.execute("SELECT composerId FROM composerHeaders").fetchall()}


def _blob_sizes_by_member(member_ids: set) -> dict:
    """One pass over the agentKv blob store, attributing each blob's bytes to
    every member id it mentions. Used only for size display."""
    db = _get_db()
    sizes = {m: 0 for m in member_ids}
    if not member_ids:
        return sizes
    for r in db.execute(
        "SELECT value FROM cursorDiskKV WHERE key LIKE ?", (AGENT_BLOB_PREFIX + "%",)
    ).fetchall():
        v = _astext(r["value"])
        for m in member_ids:
            if m in v:
                sizes[m] += len(v)
    return sizes


def scan_agent_projects() -> List[CursorAgentProject]:
    projects = _load_item(GLASS_LOCAL_PROJECTS, [])
    membership = _load_item(GLASS_LOCAL_MEMBERSHIP, {})
    if not isinstance(projects, list) or not isinstance(membership, dict):
        return []

    members_by_project = {}
    for member_id, pid in membership.items():
        members_by_project.setdefault(pid, []).append(member_id)

    composer_ids = _composer_ids()
    all_members = set(membership.keys())
    sizes = _blob_sizes_by_member(all_members)

    home = os.path.expanduser("~")
    result = []
    for p in projects:
        pid = p.get("id", "")
        if not pid:
            continue
        ws = (p.get("workspace") or {}).get("uri", {})
        ws_path = ws.get("fsPath") or ws.get("path") or ""
        if ws_path.startswith(home):
            ws_path = "~" + ws_path[len(home):]
        members = members_by_project.get(pid, [])
        composer_members = [m for m in members if m in composer_ids]
        result.append(CursorAgentProject(
            project_id=pid,
            name=p.get("name", "") or "(unnamed)",
            workspace_path=ws_path,
            member_ids=members,
            composer_member_ids=composer_members,
            is_archived=bool(p.get("isArchived")),
            created_at=p.get("createdAt", 0) or 0,
            updated_at=p.get("lastUpdatedAt", 0) or 0,
            attributed_size=sum(sizes.get(m, 0) for m in members),
        ))
    result.sort(key=lambda a: a.attributed_size, reverse=True)
    return result


def get_agent_members(project_id: str) -> List[dict]:
    """Members of an agent project, flagged as real composer chats or agent-only."""
    membership = _load_item(GLASS_LOCAL_MEMBERSHIP, {})
    composer_ids = _composer_ids()
    db = _get_db()
    bubble_counts = {}
    for r in db.execute("SELECT key FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'").fetchall():
        cid = r["key"].split(":", 2)[1]
        bubble_counts[cid] = bubble_counts.get(cid, 0) + 1

    members = []
    for member_id, pid in membership.items():
        if pid != project_id:
            continue
        is_composer = member_id in composer_ids
        members.append({
            "member_id": member_id,
            "is_composer": is_composer,
            "bubble_count": bubble_counts.get(member_id, 0),
        })
    members.sort(key=lambda m: (not m["is_composer"], m["member_id"]))
    return members


def _delete_member_ui_state(db, member_ids: set) -> int:
    """Remove per-member glass UI-state keys (tab state, fullscreen flag).
    Returns the number of ItemTable rows removed."""
    removed = 0
    for m in member_ids:
        cur = db.execute("DELETE FROM ItemTable WHERE key = ?", (GLASS_PANEL_PREFIX + m,))
        removed += cur.rowcount
        # tab state lives at cursor/glass.tabs.v2/{workspaceId}/{memberId}/state.json
        cur = db.execute(
            "DELETE FROM ItemTable WHERE key LIKE ? AND key LIKE ?",
            (GLASS_TABS_PREFIX + "%", "%/" + m + "/%"),
        )
        removed += cur.rowcount
    return removed


def _purge_all_agent_blobs(db) -> tuple:
    """Delete every agentKv blob. Returns (count, bytes)."""
    total_bytes = 0
    for r in db.execute(
        "SELECT value FROM cursorDiskKV WHERE key LIKE ?", (AGENT_BLOB_PREFIX + "%",)
    ).fetchall():
        total_bytes += len(_astext(r["value"]))
    cur = db.execute("DELETE FROM cursorDiskKV WHERE key LIKE ?", (AGENT_BLOB_PREFIX + "%",))
    return cur.rowcount, total_bytes


def _sweep_agent_blobs(db, deleted_members: set, surviving_members: set) -> tuple:
    """Delete agentKv blobs that reference a deleted member and no surviving
    member. Conservative: a blob shared with a surviving project is kept, and
    a blob mentioning no member at all is left for the whole-store purge path.
    Returns (count, bytes)."""
    if not deleted_members:
        return 0, 0
    to_delete = []
    total_bytes = 0
    for r in db.execute(
        "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?", (AGENT_BLOB_PREFIX + "%",)
    ).fetchall():
        v = _astext(r["value"])
        if any(m in v for m in deleted_members) and not any(m in v for m in surviving_members):
            to_delete.append(r["key"])
            total_bytes += len(v)
    for key in to_delete:
        db.execute("DELETE FROM cursorDiskKV WHERE key = ?", (key,))
    return len(to_delete), total_bytes


def delete_agent_project(project_id: str) -> dict:
    """Delete a local agent project and every artifact scoped to it, leaving no
    orphans. Real composer chats that happen to be members are preserved."""
    db = _get_db()
    stats = {"project": 0, "members": 0, "ui_state": 0, "blobs": 0, "bytes": 0,
             "preserved_chats": 0}

    projects = _load_item(GLASS_LOCAL_PROJECTS, [])
    before = len(projects)
    projects = [p for p in projects if p.get("id") != project_id]
    stats["project"] = before - len(projects)
    _save_item(GLASS_LOCAL_PROJECTS, projects)

    membership = _load_item(GLASS_LOCAL_MEMBERSHIP, {})
    deleted_members = {m for m, pid in membership.items() if pid == project_id}
    membership = {m: pid for m, pid in membership.items() if pid != project_id}
    surviving_members = set(membership.keys())
    stats["members"] = len(deleted_members)
    stats["preserved_chats"] = len(deleted_members & _composer_ids())
    _save_item(GLASS_LOCAL_MEMBERSHIP, membership)

    stats["ui_state"] = _delete_member_ui_state(db, deleted_members)

    sel = _load_item_raw(GLASS_SELECTED_AGENT).strip().strip('"')
    if sel in deleted_members:
        db.execute("DELETE FROM ItemTable WHERE key = ?", (GLASS_SELECTED_AGENT,))

    # Blob GC: if no agent projects remain at all, the whole content-addressed
    # store is garbage; otherwise sweep only blobs unique to the deleted members.
    cloud = _load_item(GLASS_CLOUD_PROJECTS, [])
    if not projects and not cloud:
        stats["blobs"], stats["bytes"] = _purge_all_agent_blobs(db)
    else:
        stats["blobs"], stats["bytes"] = _sweep_agent_blobs(db, deleted_members, surviving_members)

    db.commit()
    return stats


def reconcile_agents() -> dict:
    """Sweep pre-existing agent-store orphans: membership pointing at projects
    that no longer exist, UI-state for unknown members, a dangling selectedAgent,
    and agentKv blobs unreachable from any surviving member (whole store when no
    agent projects remain)."""
    db = _get_db()
    stats = {"membership": 0, "ui_state": 0, "selected": 0, "blobs": 0, "bytes": 0}

    projects = _load_item(GLASS_LOCAL_PROJECTS, [])
    cloud = _load_item(GLASS_CLOUD_PROJECTS, [])
    valid_project_ids = {p.get("id") for p in projects if p.get("id")}

    membership = _load_item(GLASS_LOCAL_MEMBERSHIP, {})
    orphan_members = {m for m, pid in membership.items() if pid not in valid_project_ids}
    if orphan_members:
        membership = {m: pid for m, pid in membership.items() if pid in valid_project_ids}
        _save_item(GLASS_LOCAL_MEMBERSHIP, membership)
        stats["membership"] = len(orphan_members)
    surviving_members = set(membership.keys())

    stats["ui_state"] = _delete_member_ui_state(db, orphan_members)

    sel = _load_item_raw(GLASS_SELECTED_AGENT).strip().strip('"')
    if sel and sel not in surviving_members:
        cur = db.execute("DELETE FROM ItemTable WHERE key = ?", (GLASS_SELECTED_AGENT,))
        stats["selected"] = cur.rowcount

    if not projects and not cloud:
        stats["blobs"], stats["bytes"] = _purge_all_agent_blobs(db)
    else:
        stats["blobs"], stats["bytes"] = _sweep_agent_blobs(db, orphan_members, surviving_members)

    db.commit()
    return stats
