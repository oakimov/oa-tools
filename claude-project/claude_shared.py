"""Shared constants, data model, scanning, and deletion logic for claude-project tools."""

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

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

# ---------------------------------------------------------------------------
# Config I/O (.claude.json)
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


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
    file_size: int = 0
    chat_size: int = 0
    subagent_size: int = 0
    tool_size: int = 0


@dataclass
class MemoryInfo:
    filepath: str
    name: str = ""
    description: str = ""
    mem_type: str = ""
    origin_session: str = ""


@dataclass
class ProjectInfo:
    path: str
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
            except Exception:
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
    except Exception:
        pass
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
        file_size=total_sz,
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
        except Exception:
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


def scan_all_projects() -> List[ProjectInfo]:
    projects = []
    if not os.path.isdir(PROJECTS_DIR):
        return projects

    for entry in sorted(os.listdir(PROJECTS_DIR)):
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
            path=entry,
            display_name=resolve_project_realpath(proj_dir),
            conversations=conversations,
            memories=memories,
            total_size=total_size,
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
    except Exception:
        pass

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
    except Exception:
        pass
    return messages


def get_memory_content(filepath: str) -> Tuple[str, str]:
    try:
        with open(filepath, "r", errors="replace") as f:
            content = f.read()
    except Exception:
        return "", "(error reading file)"
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if fm_match:
        return fm_match.group(1), fm_match.group(2)
    return "", content

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_size(sz: int) -> str:
    if sz < 1024:
        return f"{sz}B"
    elif sz < 1024 * 1024:
        return f"{sz / 1024:.0f}K"
    else:
        return f"{sz / 1024 / 1024:.1f}M"


def format_timestamp_short(ts: str) -> str:
    if not ts or len(ts) < 10:
        return ts[:10] if ts else ""
    try:
        dt = datetime.fromisoformat(ts[:19])
        now = datetime.now()
        if (now - dt).days > 180:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%b %d")
    except Exception:
        return ts[:10]

# ---------------------------------------------------------------------------
# Unified deletion
# ---------------------------------------------------------------------------

def _delete_session_artifacts(session_id: str) -> List[str]:
    """Remove session artifacts across session-env/, file-history/, sessions/."""
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
    except Exception:
        pass
    return None


def _delete_plan_files(slug: str, encoded_dir: str = None) -> List[str]:
    """Remove plan files matching a slug from both global and per-project plans dirs."""
    removed = []
    if not slug:
        return removed
    # Global plans: ~/.claude/plans/{slug}.md
    global_plan = os.path.join(PLANS_DIR, slug + ".md")
    if os.path.isfile(global_plan):
        os.remove(global_plan)
        removed.append(global_plan)
    # Per-project plans: ~/.claude/projects/{dir}/plans/{slug}.md
    if encoded_dir:
        proj_plan = os.path.join(PROJECTS_DIR, encoded_dir, "plans", slug + ".md")
        if os.path.isfile(proj_plan):
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


def _collect_session_ids(proj_dir: str) -> List[str]:
    session_ids = []
    if not os.path.isdir(proj_dir):
        return session_ids
    for fname in os.listdir(proj_dir):
        if fname.endswith(".jsonl") and os.path.isfile(os.path.join(proj_dir, fname)):
            session_ids.append(os.path.splitext(fname)[0])
    return session_ids


def _collect_slugs(proj_dir: str) -> List[str]:
    """Collect all unique slugs from conversation files in a project directory."""
    slugs = set()
    if not os.path.isdir(proj_dir):
        return list(slugs)
    for fname in os.listdir(proj_dir):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(proj_dir, fname)
        if not os.path.isfile(fpath):
            continue
        slug = _extract_slug_from_jsonl(fpath)
        if slug:
            slugs.add(slug)
    return list(slugs)


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
        session_ids = _collect_session_ids(proj_dir)
        slugs = _collect_slugs(proj_dir)
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
        session_ids = _collect_session_ids(proj_dir)
        slugs = _collect_slugs(proj_dir)
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
