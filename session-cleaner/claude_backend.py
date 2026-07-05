"""Claude Code data model, scanning, and deletion logic.

Covers ~/.claude.json (project/MCP config) and ~/.claude/projects/ (sessions,
memories, plans). See claude_tui.py for the TUI built on top of this module.
"""

import glob
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from common import is_within

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CLAUDE_DIR = os.path.expanduser("~/.claude")
CONFIG_PATH = os.path.expanduser("~/.claude.json")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")
SESSION_ENV_DIR = os.path.join(CLAUDE_DIR, "session-env")
FILE_HISTORY_DIR = os.path.join(CLAUDE_DIR, "file-history")
PLANS_DIR = os.path.join(CLAUDE_DIR, "plans")

# Claude Desktop keeps its own index of local Claude Code sessions (used for
# its session sidebar), separate from ~/.claude/projects/*.jsonl. Each entry
# is keyed by a "cliSessionId" pointing at the actual transcript file. See
# _delete_session_artifacts and find_orphan_desktop_sessions below.
DESKTOP_SESSIONS_DIR = os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code-sessions"
)

# ---------------------------------------------------------------------------
# Config I/O (.claude.json)
# ---------------------------------------------------------------------------

def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"Corrupt config file {CONFIG_PATH}: {e}")


def save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def is_project_key(key: str) -> bool:
    return key.startswith("/")


def get_project_paths(data: dict) -> List[str]:
    return sorted(k for k in data.get("projects", {}) if is_project_key(k))


def get_global_mcp_servers(data: dict) -> List[str]:
    return sorted(data.get("mcpServers", {}).keys())


def get_project_mcp_status(data: dict, project_path: str) -> dict:
    global_servers = set(get_global_mcp_servers(data))
    project = data.get("projects", {}).get(project_path, {})
    local_servers = set(project.get("mcpServers", {}).keys())
    disabled = set(project.get("disabledMcpServers", []))
    enabled = sorted((global_servers | local_servers) - disabled)
    return {
        "local": sorted(local_servers),
        "enabled": enabled,
        "disabled": sorted(disabled),
    }

# ---------------------------------------------------------------------------
# Path encoding
# ---------------------------------------------------------------------------

def encode_project_path(real_path: str) -> str:
    return real_path.replace("/", "-")


def find_json_key_for_dir(data: dict, encoded_dir: str) -> Optional[str]:
    for key in data.get("projects", {}):
        if is_project_key(key) and encode_project_path(key) == encoded_dir:
            return key
    return None


def find_dir_for_json_key(project_path: str) -> Optional[str]:
    encoded = encode_project_path(project_path)
    full_path = os.path.join(PROJECTS_DIR, encoded)
    return full_path if os.path.isdir(full_path) else None

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ConversationInfo:
    session_id: str
    slug: str = ""
    title: str = ""
    message_count: int = 0
    timestamp: str = ""
    total_size: int = 0
    chat_size: int = 0
    subagent_size: int = 0
    tool_size: int = 0
    # Desktop-only: a remote/cloud Cowork session with no local transcript —
    # only Desktop's own session-index metadata exists (see
    # scan_desktop_only_sessions). message_count is completedTurns, not a
    # real message count, and there's nothing to open in the message viewer.
    desktop_only: bool = False
    desktop_index_path: str = ""


@dataclass
class MemoryInfo:
    filepath: str
    name: str = ""
    description: str = ""
    mem_type: str = ""
    origin_session: str = ""


@dataclass
class ProjectInfo:
    encoded_dir: str
    display_name: str
    conversations: List[ConversationInfo] = field(default_factory=list)
    memories: List[MemoryInfo] = field(default_factory=list)
    total_size: int = 0


PLAN_APPROVED = "approved"
PLAN_CANCELLED = "cancelled"
PLAN_PENDING = "pending"


@dataclass
class PlanInfo:
    slug: str
    status: str
    plan_paths: List[str]
    project_dir: str
    project_display: str
    last_session_id: str
    timestamp: str


# ---------------------------------------------------------------------------
# Data scanning
# ---------------------------------------------------------------------------

def resolve_project_realpath(project_dir: str) -> str:
    """Extract the real project path from ~/.claude/projects/ subdirectory."""
    home = os.path.expanduser("~")
    if os.path.isdir(project_dir):
        for fname in sorted(os.listdir(project_dir)):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(project_dir, fname)
            try:
                with open(fpath, "r", errors="replace") as f:
                    for line in f:
                        try:
                            obj = json.loads(line)
                            if obj.get("type") == "user" and obj.get("cwd"):
                                raw = obj["cwd"]
                                if raw.startswith(home):
                                    return "~" + raw[len(home):]
                                return raw
                        except json.JSONDecodeError:
                            continue
            except (OSError, IOError):
                continue
    encoded = os.path.basename(project_dir)
    parts = encoded.strip("-").split("-")
    path = "/" + "/".join(parts)
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def scan_conversation(path: str) -> ConversationInfo:
    session_id = os.path.splitext(os.path.basename(path))[0]
    slug = ""
    title = ""
    user_asst_count = 0
    ts = ""
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
                if obj.get("type") in ("user", "assistant"):
                    user_asst_count += 1
                if not slug and obj.get("slug"):
                    slug = obj["slug"]
                if not title and obj.get("type") == "custom-title":
                    ct = obj.get("customTitle", "")
                    if ct:
                        title = ct
                if obj.get("timestamp"):
                    ts = obj["timestamp"]
    except Exception as e:
        print(f"Warning: failed to scan {path}: {e}", file=sys.stderr)
    chat_sz = os.path.getsize(path)
    subagent_sz = 0
    tool_sz = 0
    conv_dir = os.path.splitext(path)[0]
    if os.path.isdir(conv_dir):
        subagent_dir = os.path.join(conv_dir, "subagents")
        tool_dir = os.path.join(conv_dir, "tool-results")
        if os.path.isdir(subagent_dir):
            for dirpath, _, filenames in os.walk(subagent_dir):
                for fn in filenames:
                    try:
                        subagent_sz += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
        if os.path.isdir(tool_dir):
            for dirpath, _, filenames in os.walk(tool_dir):
                for fn in filenames:
                    try:
                        tool_sz += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
    total_sz = chat_sz + subagent_sz + tool_sz
    return ConversationInfo(
        session_id=session_id,
        slug=slug,
        title=title,
        message_count=user_asst_count,
        timestamp=ts,
        total_size=total_sz,
        chat_size=chat_sz,
        subagent_size=subagent_sz,
        tool_size=tool_sz,
    )


def scan_memories(memory_dir: str) -> List[MemoryInfo]:
    memories = []
    if not os.path.isdir(memory_dir):
        return memories

    memindex = os.path.join(memory_dir, "MEMORY.md")
    if not os.path.isfile(memindex):
        return memories

    md_files = [os.path.join(memory_dir, f) for f in os.listdir(memory_dir)
                if f.endswith(".md") and f != "MEMORY.md"]

    for fp in md_files:
        try:
            with open(fp, "r", errors="replace") as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: failed to read memory {fp}: {e}", file=sys.stderr)
            continue
        name = ""
        desc = ""
        mem_type = ""
        origin = ""
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            for line in fm_text.split("\n"):
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("type:"):
                    mem_type = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("originSessionId:"):
                    origin = line.split(":", 1)[1].strip().strip('"').strip("'")
        if name:
            memories.append(MemoryInfo(
                filepath=fp,
                name=name,
                description=desc,
                mem_type=mem_type,
                origin_session=origin,
            ))
    return memories


def _epoch_ms_to_iso(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).isoformat()
    except (ValueError, OverflowError, OSError, TypeError):
        return ""


def desktop_titles_by_cli_session_id() -> Dict[str, str]:
    """Titles from Desktop's session index, keyed by cliSessionId, for
    sessions that DO have a local transcript. The Desktop app derives a
    friendly title (e.g. "CCR API 400 model parsing error") that the local
    .jsonl often lacks (no `slug`/`custom-title` event) — without this,
    such conversations only display their raw session-id prefix, making
    them indistinguishable from genuinely empty ones in the same project."""
    titles: Dict[str, str] = {}
    for ip in _desktop_index_files():
        idx = _read_desktop_index(ip)
        if not idx:
            continue
        cli_id = idx.get("cliSessionId")
        title = idx.get("title", "")
        if cli_id and title:
            titles[cli_id] = title
    return titles


def scan_desktop_only_sessions() -> Dict[str, List[ConversationInfo]]:
    """Desktop-app (Cowork) sessions with no local ~/.claude/projects
    transcript, grouped by real cwd. These have no `cliSessionId` and are
    flagged `transcriptUnavailable` by the Desktop app itself — real
    remote/cloud-run sessions, not orphans (see find_orphan_desktop_sessions
    for the actual-orphan case: a cliSessionId pointing at a deleted file).
    Only metadata is available; there is no local transcript to display."""
    by_cwd: Dict[str, List[ConversationInfo]] = {}
    for ip in _desktop_index_files():
        idx = _read_desktop_index(ip)
        if not idx or idx.get("cliSessionId"):
            continue
        cwd = idx.get("cwd") or idx.get("originCwd") or ""
        if not cwd:
            continue
        try:
            size = os.path.getsize(ip)
        except OSError:
            size = 0
        conv = ConversationInfo(
            session_id=idx.get("sessionId", os.path.splitext(os.path.basename(ip))[0]),
            title=idx.get("title", ""),
            message_count=idx.get("completedTurns", 0),
            timestamp=_epoch_ms_to_iso(idx.get("lastActivityAt") or idx.get("createdAt")),
            total_size=size,
            chat_size=size,
            desktop_only=True,
            desktop_index_path=ip,
        )
        by_cwd.setdefault(cwd, []).append(conv)
    return by_cwd


def scan_desktop_sessions_for_project(encoded_dir: str) -> List[ConversationInfo]:
    """Desktop-only sessions (see scan_desktop_only_sessions) belonging to one
    project, matched by encoded directory name."""
    result = []
    for cwd, convs in scan_desktop_only_sessions().items():
        if encode_project_path(cwd) == encoded_dir:
            result.extend(convs)
    return result


def delete_desktop_only_session(index_path: str) -> List[str]:
    """Delete a Desktop-only session's index entry (no local transcript to
    remove — this file is the only record of it)."""
    removed = []
    if os.path.isfile(index_path) and is_within(DESKTOP_SESSIONS_DIR, index_path):
        os.remove(index_path)
        removed.append(index_path)
    return removed


def scan_all_projects() -> List[ProjectInfo]:
    projects = []
    desktop_titles = desktop_titles_by_cli_session_id()

    for entry in sorted(os.listdir(PROJECTS_DIR)) if os.path.isdir(PROJECTS_DIR) else []:
        proj_dir = os.path.join(PROJECTS_DIR, entry)
        if not os.path.isdir(proj_dir):
            continue

        conversations = []
        total_size = 0
        for fname in os.listdir(proj_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(proj_dir, fname)
            if not os.path.isfile(fpath):
                continue
            conv = scan_conversation(fpath)
            if not conv.title:
                conv.title = desktop_titles.get(conv.session_id, "")
            conversations.append(conv)

        for dirpath, _, filenames in os.walk(proj_dir):
            for fn in filenames:
                fpath = os.path.join(dirpath, fn)
                try:
                    total_size += os.path.getsize(fpath)
                except OSError:
                    pass

        memories = scan_memories(os.path.join(proj_dir, "memory"))
        conversations.sort(key=lambda c: c.timestamp or "", reverse=True)

        projects.append(ProjectInfo(
            encoded_dir=entry,
            display_name=resolve_project_realpath(proj_dir),
            conversations=conversations,
            memories=memories,
            total_size=total_size,
        ))

    # Merge in Desktop-only (cloud/remote Cowork) sessions that have no local
    # transcript — either into their matching project, or as a new
    # cloud-only project if no local ~/.claude/projects directory exists for
    # that cwd at all.
    home = os.path.expanduser("~")
    for cwd, convs in scan_desktop_only_sessions().items():
        encoded = encode_project_path(cwd)
        match = next((p for p in projects if p.encoded_dir == encoded), None)
        extra_size = sum(c.total_size for c in convs)
        if match:
            match.conversations.extend(convs)
            match.conversations.sort(key=lambda c: c.timestamp or "", reverse=True)
            match.total_size += extra_size
        else:
            display = "~" + cwd[len(home):] if cwd.startswith(home) else cwd
            projects.append(ProjectInfo(
                encoded_dir=encoded,
                display_name=display,
                conversations=sorted(convs, key=lambda c: c.timestamp or "", reverse=True),
                memories=[],
                total_size=extra_size,
            ))

    projects.sort(key=lambda p: p.total_size, reverse=True)
    return projects


def _get_last_plan_exit(jsonl_path: str) -> Optional[Tuple[str, str, str]]:
    """Get plan status from the last ExitPlanMode in a session.
    Returns (status, slug, timestamp) or None.
    """
    exits = []
    session_slug = ""
    try:
        with open(jsonl_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not session_slug and obj.get("slug"):
                    session_slug = obj["slug"]
                ts = obj.get("timestamp", "")
                msg = obj.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("name") == "ExitPlanMode":
                                exits.append((item.get("input", {}), ts))
    except Exception as e:
        print(f"Warning: failed to scan plan exits in {jsonl_path}: {e}", file=sys.stderr)

    if not exits:
        return None

    last_input, last_ts = exits[-1]
    plan_path = last_input.get("planFilePath", "")
    plan_content = last_input.get("plan", "")
    has_prompts = bool(last_input.get("allowedPrompts"))

    if plan_path:
        slug = os.path.splitext(os.path.basename(plan_path))[0]
    else:
        for inp, _ in reversed(exits[:-1]):
            pp = inp.get("planFilePath", "")
            if pp:
                slug = os.path.splitext(os.path.basename(pp))[0]
                break
        else:
            slug = session_slug

    if not slug:
        return None

    if has_prompts:
        status = PLAN_APPROVED
    elif not plan_content and not plan_path:
        status = PLAN_CANCELLED
    else:
        status = PLAN_PENDING

    return (status, slug, last_ts)


def scan_all_plans() -> List[PlanInfo]:
    """Scan all sessions to find plans and their status based on the last ExitPlanMode."""
    entries = []

    if not os.path.isdir(PROJECTS_DIR):
        return entries

    for entry in sorted(os.listdir(PROJECTS_DIR)):
        proj_dir = os.path.join(PROJECTS_DIR, entry)
        if not os.path.isdir(proj_dir):
            continue

        display_name = resolve_project_realpath(proj_dir)

        for fname in os.listdir(proj_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(proj_dir, fname)
            if not os.path.isfile(fpath):
                continue

            session_id = os.path.splitext(fname)[0]
            result = _get_last_plan_exit(fpath)
            if result is None:
                continue

            status, slug, ts = result
            entries.append((slug, status, ts, entry, display_name, session_id))

    # Keep latest entry per slug (by timestamp)
    plans_by_slug = {}
    for slug, status, ts, proj_dir, display, sid in entries:
        if slug not in plans_by_slug or (ts and ts > plans_by_slug[slug][2]):
            plans_by_slug[slug] = (slug, status, ts, proj_dir, display, sid)

    plans = []
    for slug, status, ts, proj_dir, display, sid in plans_by_slug.values():
        plan_paths = []
        global_plan = os.path.join(PLANS_DIR, slug + ".md")
        proj_plan = os.path.join(PROJECTS_DIR, proj_dir, "plans", slug + ".md")
        if os.path.isfile(global_plan):
            plan_paths.append(global_plan)
        if os.path.isfile(proj_plan):
            plan_paths.append(proj_plan)

        plans.append(PlanInfo(
            slug=slug,
            status=status,
            plan_paths=plan_paths,
            project_dir=proj_dir,
            project_display=display,
            last_session_id=sid,
            timestamp=ts,
        ))

    return sorted(plans, key=lambda p: p.timestamp or "", reverse=True)


def get_conversation_messages(session_id: str, proj_path: str) -> List[dict]:
    fpath = os.path.join(PROJECTS_DIR, proj_path, session_id + ".jsonl")
    messages = []
    if not os.path.isfile(fpath):
        return messages
    try:
        with open(fpath, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") in ("user", "assistant"):
                    messages.append(obj)
    except Exception as e:
        print(f"Warning: failed to read messages from {fpath}: {e}", file=sys.stderr)
    return messages


def extract_block_text(content) -> str:
    """Flatten a tool_result's nested `content` (string or list of blocks)
    into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return ""


# ---------------------------------------------------------------------------
# Transcript export/import (cross-tool converter — see
# plans/transcript-converter-plan.md)
# ---------------------------------------------------------------------------

def export_transcript(session_id: str, encoded_dir: str):
    """Read a conversation's raw jsonl and convert every block (text,
    thinking, tool_use, tool_result) into IR messages, preserving full
    fidelity — not the lossy display-rendered text used by the viewer."""
    from transcript_ir import Transcript, TranscriptMessage

    raw_msgs = get_conversation_messages(session_id, encoded_dir)
    proj_dir = os.path.join(PROJECTS_DIR, encoded_dir)
    cwd = os.path.expanduser(resolve_project_realpath(proj_dir))

    messages = []
    created_at = ""
    updated_at = ""
    for raw in raw_msgs:
        ts = raw.get("timestamp", "")
        if ts:
            created_at = created_at or ts
            updated_at = ts
        role = raw.get("message", {}).get("role") or raw.get("type", "?")
        content = raw.get("message", {}).get("content", "")
        blocks = content if isinstance(content, list) else (
            [{"type": "text", "text": content}] if content else []
        )
        for block in blocks:
            if isinstance(block, str):
                if block:
                    messages.append(TranscriptMessage(role=role, kind="text", text=block, timestamp=ts))
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                messages.append(TranscriptMessage(role=role, kind="text", text=block["text"], timestamp=ts))
            elif btype == "thinking" and block.get("thinking"):
                messages.append(TranscriptMessage(role=role, kind="thinking", text=block["thinking"], timestamp=ts))
            elif btype == "tool_use":
                inp = block.get("input", {})
                messages.append(TranscriptMessage(
                    role=role, kind="tool_call",
                    tool_name=block.get("name", "?"),
                    tool_input=inp if isinstance(inp, dict) else {"_raw": inp},
                    timestamp=ts,
                ))
            elif btype == "tool_result":
                messages.append(TranscriptMessage(
                    role=role, kind="tool_result",
                    text=extract_block_text(block.get("content", "")),
                    timestamp=ts,
                ))

    fpath = os.path.join(proj_dir, session_id + ".jsonl")
    conv = scan_conversation(fpath) if os.path.isfile(fpath) else None
    title = (conv.title or conv.slug) if conv else ""
    if not title:
        title = desktop_titles_by_cli_session_id().get(session_id, "")

    return Transcript(
        source_tool="claude",
        session_id=session_id,
        title=title or session_id[:12],
        cwd=cwd,
        created_at=created_at,
        updated_at=updated_at,
        messages=messages,
    )


def _current_claude_version() -> str:
    try:
        import subprocess
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
        # "2.1.201 (Claude Code)" -> "2.1.201"
        return out.stdout.strip().split(" ")[0] or "0.0.0"
    except Exception:
        return "0.0.0"


def _git_branch(target_cwd: str) -> str:
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", target_cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        branch = out.stdout.strip()
        return branch if out.returncode == 0 and branch else "main"
    except Exception:
        return "main"


def import_transcript(transcript, target_cwd: str) -> str:
    """Write a new Claude Code session from a Transcript IR. Registers
    target_cwd in ~/.claude.json if not already a known project. Returns
    the new session's .jsonl path. One top-level jsonl event per IR
    message (a simplification vs. the original — which may have grouped
    several blocks into one assistant turn — but reads back identically
    through get_conversation_messages/scan_conversation).

    Fields (gitBranch, promptId, origin, permissionMode, promptSource,
    version) are filled in to match a real transcript's shape as closely
    as possible — see plans/transcript-converter-plan.md's findings on
    the CLI's own --resume picker for why this matters and its limits."""
    import uuid as _uuid

    new_session_id = str(_uuid.uuid4())
    encoded = encode_project_path(target_cwd)
    proj_dir = os.path.join(PROJECTS_DIR, encoded)
    os.makedirs(proj_dir, exist_ok=True)
    fpath = os.path.join(proj_dir, new_session_id + ".jsonl")

    version = _current_claude_version()
    git_branch = _git_branch(target_cwd)

    lines = [json.dumps({
        "type": "custom-title",
        "customTitle": transcript.title,
        "uuid": str(_uuid.uuid4()),
        "timestamp": transcript.created_at or "",
        "sessionId": new_session_id,
    })]

    parent_uuid = None
    for msg in transcript.messages:
        event_uuid = str(_uuid.uuid4())
        ts = msg.timestamp or transcript.updated_at or ""
        role = msg.role if msg.role in ("user", "assistant") else "assistant"

        if msg.kind == "text":
            content = msg.text
        elif msg.kind == "thinking":
            content = [{"type": "thinking", "thinking": msg.text, "signature": ""}]
        elif msg.kind == "tool_call":
            content = [{
                "type": "tool_use",
                "id": f"toolu_{event_uuid.replace('-', '')[:24]}",
                "name": msg.tool_name or "?",
                "input": msg.tool_input or {},
            }]
        elif msg.kind == "tool_result":
            content = [{
                "type": "tool_result",
                "tool_use_id": f"toolu_{event_uuid.replace('-', '')[:24]}",
                "content": msg.text,
                "is_error": False,
            }]
        else:
            content = msg.text

        event = {
            "parentUuid": parent_uuid,
            "isSidechain": False,
            "type": role,
            "message": {"role": role, "content": content},
            "uuid": event_uuid,
            "timestamp": ts,
            "sessionId": new_session_id,
            "cwd": target_cwd,
            "userType": "external",
            "entrypoint": "transcript-import",
            "version": version,
            "gitBranch": git_branch,
        }
        if role == "user":
            event["promptId"] = str(_uuid.uuid4())
            event["origin"] = {"kind": "human"}
            event["permissionMode"] = "acceptEdits"
            event["promptSource"] = "sdk"

        lines.append(json.dumps(event))
        parent_uuid = event_uuid

    with open(fpath, "w") as f:
        f.write("\n".join(lines) + "\n")

    data = load_config()
    if target_cwd not in data.get("projects", {}):
        data.setdefault("projects", {})[target_cwd] = {}
        save_config(data)

    return fpath


def get_memory_content(filepath: str) -> Tuple[str, str]:
    try:
        with open(filepath, "r", errors="replace") as f:
            content = f.read()
    except Exception as e:
        print(f"Warning: failed to read {filepath}: {e}", file=sys.stderr)
        return "", "(error reading file)"
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if fm_match:
        return fm_match.group(1), fm_match.group(2)
    return "", content

# ---------------------------------------------------------------------------
# Unified deletion
# ---------------------------------------------------------------------------

def _desktop_index_files() -> List[str]:
    return glob.glob(os.path.join(DESKTOP_SESSIONS_DIR, "*", "*", "local_*.json"))


def _read_desktop_index(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _delete_session_artifacts(session_id: str) -> List[str]:
    """Remove session artifacts across session-env/, file-history/, sessions/,
    and the Claude Desktop app's session index (which mirrors CLI sessions by
    cliSessionId and would otherwise be left pointing at a deleted transcript)."""
    removed = []
    for base_dir in (SESSION_ENV_DIR, FILE_HISTORY_DIR):
        d = os.path.join(base_dir, session_id)
        if os.path.isdir(d):
            shutil.rmtree(d)
            removed.append(d)
    if os.path.isdir(SESSIONS_DIR):
        for sf in os.listdir(SESSIONS_DIR):
            if not sf.endswith(".json"):
                continue
            sfp = os.path.join(SESSIONS_DIR, sf)
            try:
                with open(sfp) as f:
                    sess = json.load(f)
                if sess.get("sessionId") == session_id:
                    os.remove(sfp)
                    removed.append(sfp)
            except (OSError, json.JSONDecodeError):
                pass
    for ip in _desktop_index_files():
        idx = _read_desktop_index(ip)
        if idx and idx.get("cliSessionId") == session_id:
            os.remove(ip)
            removed.append(ip)
    return removed


def find_orphan_desktop_sessions() -> List[str]:
    """Desktop app session-index entries whose cliSessionId no longer matches
    any ~/.claude/projects/*/*.jsonl transcript (e.g. deleted before this tool
    covered the Desktop index, or never synced)."""
    existing_ids = set()
    if os.path.isdir(PROJECTS_DIR):
        for entry in os.listdir(PROJECTS_DIR):
            proj_dir = os.path.join(PROJECTS_DIR, entry)
            if not os.path.isdir(proj_dir):
                continue
            for fname in os.listdir(proj_dir):
                if fname.endswith(".jsonl"):
                    existing_ids.add(os.path.splitext(fname)[0])

    orphans = []
    for ip in _desktop_index_files():
        idx = _read_desktop_index(ip)
        if idx is None:
            continue
        cli_id = idx.get("cliSessionId")
        if cli_id and cli_id not in existing_ids:
            orphans.append(ip)
    return orphans


def delete_orphan_desktop_sessions(paths: List[str]) -> int:
    removed = 0
    for p in paths:
        if os.path.isfile(p) and is_within(DESKTOP_SESSIONS_DIR, p):
            os.remove(p)
            removed += 1
    return removed


def _extract_slug_from_jsonl(jsonl_path: str) -> Optional[str]:
    """Read the slug from the first user entry in a conversation file."""
    try:
        with open(jsonl_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("slug"):
                    return obj["slug"]
    except Exception as e:
        print(f"Warning: failed to extract slug from {jsonl_path}: {e}", file=sys.stderr)
    return None


def _delete_plan_files(slug: str, encoded_dir: str = None) -> List[str]:
    """Remove plan files matching a slug from both global and per-project plans dirs."""
    removed = []
    if not slug:
        return removed
    slug = os.path.basename(slug)
    if not slug or slug.startswith("."):
        return removed
    # Global plans: ~/.claude/plans/{slug}.md
    global_plan = os.path.join(PLANS_DIR, slug + ".md")
    if os.path.isfile(global_plan) and is_within(PLANS_DIR, global_plan):
        os.remove(global_plan)
        removed.append(global_plan)
    # Per-project plans: ~/.claude/projects/{dir}/plans/{slug}.md
    if encoded_dir:
        proj_plan = os.path.join(PROJECTS_DIR, encoded_dir, "plans", slug + ".md")
        if os.path.isfile(proj_plan) and is_within(PROJECTS_DIR, proj_plan):
            os.remove(proj_plan)
            removed.append(proj_plan)
    return removed


def delete_plan(plan_info) -> List[str]:
    """Delete plan files for a given PlanInfo."""
    removed = []
    for path in plan_info.plan_paths:
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return removed


def _collect_sessions_and_slugs(proj_dir: str) -> Tuple[List[str], List[str]]:
    """Walk a project directory collecting session IDs and unique slugs in one pass."""
    session_ids = []
    slugs = set()
    if not os.path.isdir(proj_dir):
        return session_ids, list(slugs)
    for fname in sorted(os.listdir(proj_dir)):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(proj_dir, fname)
        if not os.path.isfile(fpath):
            continue
        session_ids.append(os.path.splitext(fname)[0])
        slug = _extract_slug_from_jsonl(fpath)
        if slug:
            slugs.add(slug)
    return session_ids, list(slugs)


def delete_conversation(session_id: str, encoded_dir: str) -> List[str]:
    """Delete a single conversation and all its artifacts. Returns removed paths."""
    removed = []
    jsonl_path = os.path.join(PROJECTS_DIR, encoded_dir, session_id + ".jsonl")
    conv_dir = os.path.join(PROJECTS_DIR, encoded_dir, session_id)

    # Extract slug before deleting the jsonl
    slug = _extract_slug_from_jsonl(jsonl_path)

    if os.path.isfile(jsonl_path):
        os.remove(jsonl_path)
        removed.append(jsonl_path)
    if os.path.isdir(conv_dir):
        shutil.rmtree(conv_dir)
        removed.append(conv_dir)

    removed.extend(_delete_session_artifacts(session_id))
    removed.extend(_delete_plan_files(slug, encoded_dir))
    return removed


def delete_project_filesystem(real_path: str) -> List[str]:
    """Delete all filesystem data for a project by its real path (e.g. /Users/mitra/Projects/foo)."""
    removed = []
    encoded = encode_project_path(real_path)
    proj_dir = os.path.join(PROJECTS_DIR, encoded)

    if os.path.isdir(proj_dir):
        session_ids, slugs = _collect_sessions_and_slugs(proj_dir)
        shutil.rmtree(proj_dir)
        removed.append(proj_dir)
        for sid in session_ids:
            removed.extend(_delete_session_artifacts(sid))
        for slug in slugs:
            removed.extend(_delete_plan_files(slug, encoded))

    return removed


def delete_project_filesystem_by_dir(encoded_dir: str) -> List[str]:
    """Delete filesystem data by encoded directory name (when no JSON key is known)."""
    removed = []
    proj_dir = os.path.join(PROJECTS_DIR, encoded_dir)

    if os.path.isdir(proj_dir):
        session_ids, slugs = _collect_sessions_and_slugs(proj_dir)
        shutil.rmtree(proj_dir)
        removed.append(proj_dir)
        for sid in session_ids:
            removed.extend(_delete_session_artifacts(sid))
        for slug in slugs:
            removed.extend(_delete_plan_files(slug, encoded_dir))

    return removed


def delete_project_config(data: dict, project_path: str) -> bool:
    """Remove a project entry from .claude.json. Returns True if found and removed."""
    projects = data.get("projects", {})
    if project_path in projects and is_project_key(project_path):
        del projects[project_path]
        save_config(data)
        return True
    return False


def delete_project_unified(project_path: str) -> dict:
    """Delete a project completely: .claude.json entry + all filesystem data."""
    data = load_config()
    config_deleted = delete_project_config(data, project_path)
    fs_removed = delete_project_filesystem(project_path)
    return {
        "project_path": project_path,
        "config_deleted": config_deleted,
        "filesystem_removed": fs_removed,
    }
