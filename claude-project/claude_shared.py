"""Shared constants, data model, scanning, and deletion logic for claude-project tools."""

import json
import os
import re
import shutil
import sys
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


def load_json_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json_file(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
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

def _is_within(parent: str, child: str) -> bool:
    """Check that child path resolves within parent directory."""
    return os.path.realpath(child).startswith(os.path.realpath(parent) + os.sep)


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
    except Exception as e:
        print(f"Warning: failed to scan {path}: {e}", file=sys.stderr)
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
        print(f"Warning: failed to read messages from {path}: {e}", file=sys.stderr)
    return messages


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
    except Exception as e:
        print(f"Warning: failed to extract slug from {jsonl_path}: {e}", file=sys.stderr)
    return None


def _delete_plan_files(slug: str, encoded_dir: str = None) -> List[str]:
    """Remove plan files matching a slug from both global and per-project plans dirs."""
    removed = []
    if not slug:
        return removed
    # Global plans: ~/.claude/plans/{slug}.md
    global_plan = os.path.join(PLANS_DIR, slug + ".md")
    if os.path.isfile(global_plan) and _is_within(PLANS_DIR, global_plan):
        os.remove(global_plan)
        removed.append(global_plan)
    # Per-project plans: ~/.claude/projects/{dir}/plans/{slug}.md
    if encoded_dir:
        proj_plan = os.path.join(PROJECTS_DIR, encoded_dir, "plans", slug + ".md")
        if os.path.isfile(proj_plan) and _is_within(PROJECTS_DIR, proj_plan):
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

# ---------------------------------------------------------------------------
# TUI (requires prompt_toolkit)
# ---------------------------------------------------------------------------

try:
    from prompt_toolkit import Application
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import (
        ConditionalContainer,
        HSplit,
        VSplit,
        Window,
    )
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Frame
    _HAS_TUI = True
except ImportError:
    _HAS_TUI = False

VIEW_PROJECTS = "projects"
VIEW_PROJECT_DETAIL = "project_detail"
VIEW_CONVERSATION = "conversation"
VIEW_MEMORY = "memory"
VIEW_CONFIRM_DELETE = "confirm_delete"
VIEW_PLANS = "plans"


class CleanerTUI:
    def __init__(self):
        self.projects = []
        self.view = VIEW_PROJECTS

        self.proj_cursor = 0

        self.current_project = None
        self.detail_pane = "conversations"
        self.conv_cursor = 0
        self.mem_cursor = 0
        self.conv_sort_key = "date"
        self.conv_sort_desc = True

        self.current_messages = []
        self.conv_msg_scroll = 0
        self.conv_title = ""

        self.current_memory = None
        self.memory_fm = ""
        self.memory_body = ""
        self.memory_scroll = 0

        self.delete_target = ""
        self.delete_path = ""
        self.delete_callback = None
        self.delete_return_view = VIEW_PROJECT_DETAIL
        self.confirm_title = "Confirm Delete"

        self.show_mcp = False
        self.config = {}
        self.status_message = "Ready"
        self.all_plans = []
        self.plan_cursor = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text):
        self.status_message = text

    def _project_has_enabled_mcp(self, encoded_dir):
        if not self.config:
            return False
        json_key = find_json_key_for_dir(self.config, encoded_dir)
        if not json_key:
            return False
        status = get_project_mcp_status(self.config, json_key)
        return len(status["enabled"]) > 0

    def _get_project_plans(self, encoded_dir):
        return [p for p in self.all_plans if p.project_dir == encoded_dir and p.plan_paths]

    def _reset_all_scroll(self):
        self.conv_msg_scroll = 0
        self.memory_scroll = 0

    def _enter_view(self, view):
        self.view = view
        self._reset_all_scroll()

    def _go_back(self):
        if self.view == VIEW_PROJECT_DETAIL:
            self._enter_view(VIEW_PROJECTS)
        elif self.view == VIEW_CONVERSATION:
            self._enter_view(VIEW_PROJECT_DETAIL)
        elif self.view == VIEW_MEMORY:
            self._enter_view(VIEW_PROJECT_DETAIL)
        elif self.view == VIEW_CONFIRM_DELETE:
            self._enter_view(self.delete_return_view)
        elif self.view == VIEW_PLANS:
            self._enter_view(VIEW_PROJECTS)

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------

    def _enter_project(self):
        if not self.projects or self.proj_cursor >= len(self.projects):
            return
        self.current_project = self.projects[self.proj_cursor]
        self.conv_cursor = 0
        self.mem_cursor = 0
        self.detail_pane = "conversations"
        self.show_mcp = False
        self._enter_view(VIEW_PROJECT_DETAIL)

    def _sorted_convs(self):
        convs = list(self.current_project.conversations)
        if self.conv_sort_key == "size":
            convs.sort(key=lambda c: c.file_size, reverse=self.conv_sort_desc)
        elif self.conv_sort_key == "date":
            convs.sort(key=lambda c: c.timestamp or "", reverse=self.conv_sort_desc)
        return convs

    def _enter_conversation(self):
        if not self.current_project:
            return
        convs = self._sorted_convs()
        if not convs or self.conv_cursor >= len(convs):
            return
        conv = convs[self.conv_cursor]
        msgs = get_conversation_messages(conv.session_id, self.current_project.path)
        msgs.reverse()
        self.current_messages = msgs
        self.conv_msg_scroll = 0
        name = conv.title or conv.slug or conv.session_id[:12]
        self.conv_title = f"{name}  ({len(msgs)} messages)"
        self._enter_view(VIEW_CONVERSATION)

    def _enter_memory(self):
        if not self.current_project:
            return
        mems = self.current_project.memories
        if not mems or self.mem_cursor >= len(mems):
            return
        self.current_memory = mems[self.mem_cursor]
        self.memory_fm, self.memory_body = get_memory_content(self.current_memory.filepath)
        self.memory_scroll = 0
        self._enter_view(VIEW_MEMORY)

    def _delete_current_item(self):
        if self.view == VIEW_CONVERSATION:
            if not self.current_project or not self.current_messages:
                return
            session_id = None
            for msg in self.current_messages:
                sid = msg.get("sessionId")
                if sid:
                    session_id = sid
                    break
            if not session_id:
                return
            conv = next((c for c in self.current_project.conversations if c.session_id == session_id), None)
            if not conv:
                return
            self.delete_target = f"Conversation: {conv.slug or conv.session_id[:12]}"
            self.delete_path = os.path.join(
                PROJECTS_DIR, self.current_project.path, conv.session_id + ".jsonl"
            )
            self.delete_callback = self._do_delete_conversation
            self.delete_return_view = VIEW_PROJECT_DETAIL
        elif self.view == VIEW_PROJECTS:
            if not self.projects or self.proj_cursor >= len(self.projects):
                return
            proj = self.projects[self.proj_cursor]
            self.delete_target = f"Project: {proj.display_name}"
            self.delete_path = os.path.join(PROJECTS_DIR, proj.path)
            self.delete_callback = self._do_delete_project
            self.delete_return_view = VIEW_PROJECTS
        elif self.view == VIEW_PROJECT_DETAIL:
            if self.detail_pane == "conversations":
                convs = self._sorted_convs()
                if not convs or self.conv_cursor >= len(convs):
                    return
                conv = convs[self.conv_cursor]
                self.delete_target = f"Conversation: {conv.slug or conv.session_id[:12]}"
                self.delete_path = os.path.join(
                    PROJECTS_DIR, self.current_project.path, conv.session_id + ".jsonl"
                )
                self.delete_callback = self._do_delete_conversation
                self.delete_return_view = VIEW_PROJECT_DETAIL
            else:
                mems = self.current_project.memories if self.current_project else []
                if not mems or self.mem_cursor >= len(mems):
                    return
                mem = mems[self.mem_cursor]
                self.delete_target = f"Memory: {mem.name}"
                self.delete_path = mem.filepath
                self.delete_callback = self._do_delete_memory
                self.delete_return_view = VIEW_PROJECT_DETAIL
        else:
            return
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _confirm_delete(self):
        if self.delete_callback:
            self.delete_callback()
        self._go_back()

    def _do_delete_project(self):
        proj = self.projects[self.proj_cursor]
        try:
            data = load_config()
            json_key = find_json_key_for_dir(data, proj.path)
            if json_key:
                result = delete_project_unified(json_key)
                n = len(result["filesystem_removed"])
                self._set_status(f"Deleted: {proj.display_name} (config + {n} items)")
            else:
                removed = delete_project_filesystem_by_dir(proj.path)
                self._set_status(f"Deleted: {proj.display_name} ({len(removed)} filesystem items)")
        except Exception:
            removed = delete_project_filesystem_by_dir(proj.path)
            self._set_status(f"Deleted: {proj.display_name} ({len(removed)} filesystem items)")
        self.projects = [p for p in self.projects if p.path != proj.path]
        self.proj_cursor = min(self.proj_cursor, max(0, len(self.projects) - 1))

    def _do_delete_conversation(self):
        session_id = os.path.splitext(os.path.basename(self.delete_path))[0]
        removed = delete_conversation(session_id, self.current_project.path)
        conv_name = self.delete_target.split(":", 1)[-1].strip() if self.delete_target else session_id[:12]
        self._set_status(f"Deleted: {conv_name} ({len(removed)} items)")
        if self.current_project:
            self._rescan_project(self.current_project)

    def _do_delete_memory(self):
        if os.path.isfile(self.delete_path) and _is_within(PROJECTS_DIR, self.delete_path):
            os.remove(self.delete_path)
        self._set_status(f"Deleted memory: {os.path.basename(self.delete_path)}")
        if self.current_project:
            self._rescan_project(self.current_project)

    def _rescan_project(self, proj):
        proj_dir = os.path.join(PROJECTS_DIR, proj.path)
        convs = []
        total_size = 0
        for fname in os.listdir(proj_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(proj_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                convs.append(scan_conversation(fpath))
            except (FileNotFoundError, OSError):
                continue
        for dirpath, _, filenames in os.walk(proj_dir):
            for fn in filenames:
                try:
                    total_size += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
        convs.sort(key=lambda c: c.timestamp or "", reverse=True)
        proj.conversations = convs
        proj.total_size = total_size
        proj.memories = scan_memories(os.path.join(proj_dir, "memory"))
        self.conv_cursor = min(self.conv_cursor, max(0, len(convs) - 1)) if convs else 0
        self.mem_cursor = min(self.mem_cursor, max(0, len(proj.memories) - 1)) if proj.memories else 0

    # ------------------------------------------------------------------
    # Plan cleanup
    # ------------------------------------------------------------------

    def _enter_plans(self):
        self.plan_cursor = 0
        self._enter_view(VIEW_PLANS)

    def _delete_plan_item(self):
        if not self.all_plans or self.plan_cursor >= len(self.all_plans):
            return
        plan = self.all_plans[self.plan_cursor]
        if plan.status == PLAN_PENDING:
            self._set_status("Cannot delete pending plan")
            return
        if not plan.plan_paths:
            self._set_status("No plan files on disk")
            return
        self.delete_target = f"Plan: {plan.slug} [{plan.status}]"
        self.delete_path = ", ".join(plan.plan_paths)
        self.delete_callback = self._do_delete_plan
        self.delete_return_view = VIEW_PLANS
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _delete_all_removable_plans(self):
        removable = [p for p in self.all_plans
                     if p.status in (PLAN_APPROVED, PLAN_CANCELLED) and p.plan_paths]
        if not removable:
            self._set_status("No removable plans with files")
            return
        self.delete_target = f"All removable plans ({len(removable)})"
        self.delete_path = "(multiple files)"
        self.delete_callback = lambda: self._do_delete_all_plans(removable)
        self.delete_return_view = VIEW_PLANS
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_delete_plan(self):
        plan = self.all_plans[self.plan_cursor]
        removed = delete_plan(plan)
        self._set_status(f"Deleted plan: {plan.slug} ({len(removed)} files)")
        self._rescan_plans()

    def _do_delete_all_plans(self, plans):
        total = 0
        for p in plans:
            total += len(delete_plan(p))
        self._set_status(f"Deleted {len(plans)} plans ({total} files)")
        self._rescan_plans()

    def _rescan_plans(self):
        self.all_plans = scan_all_plans()
        self.plan_cursor = min(self.plan_cursor, max(0, len(self.all_plans) - 1))

    # ------------------------------------------------------------------
    # MCP disable
    # ------------------------------------------------------------------

    def _disable_project_mcp(self):
        if self.view == VIEW_PROJECT_DETAIL:
            proj = self.current_project
        elif self.view == VIEW_PROJECTS:
            if not self.projects or self.proj_cursor >= len(self.projects):
                return
            proj = self.projects[self.proj_cursor]
        else:
            return

        if not proj:
            return

        data = load_config()
        json_key = find_json_key_for_dir(data, proj.path)
        if not json_key:
            self._set_status("No .claude.json entry for this project")
            return

        global_servers = set(get_global_mcp_servers(data))
        local_servers = set(data["projects"][json_key].get("mcpServers", {}).keys())
        all_servers = sorted(global_servers | local_servers)

        if not all_servers:
            self._set_status("No MCP servers to disable")
            return

        self.delete_target = f"Disable MCP servers for: {proj.display_name}"
        self.delete_path = f"{len(all_servers)} servers: {', '.join(all_servers)}"
        self.delete_callback = lambda: self._do_disable_mcp(json_key, all_servers, data)
        self.delete_return_view = self.view
        self.confirm_title = "Confirm Disable"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _disable_all_mcp(self):
        data = load_config()
        global_servers = set(get_global_mcp_servers(data))
        paths = get_project_paths(data)

        if not global_servers:
            self._set_status("No global MCP servers to disable")
            return

        self.delete_target = f"Disable MCP servers for all {len(paths)} projects"
        self.delete_path = f"{len(global_servers)} servers: {', '.join(sorted(global_servers))}"
        self.delete_callback = lambda: self._do_disable_all_mcp(global_servers, paths, data)
        self.delete_return_view = VIEW_PROJECTS
        self.confirm_title = "Confirm Disable All"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_disable_mcp(self, json_key, servers, data):
        data["projects"][json_key]["disabledMcpServers"] = servers
        save_config(data)
        self.config = data
        self._set_status(f"Disabled {len(servers)} MCP servers")

    def _do_disable_all_mcp(self, servers, paths, data):
        for path in paths:
            data["projects"][path]["disabledMcpServers"] = list(servers)
        save_config(data)
        self.config = data
        self._set_status(f"Disabled {len(servers)} MCP servers for {len(paths)} projects")

    # ------------------------------------------------------------------
    # Rendering — Project list
    # ------------------------------------------------------------------

    def _render_projects(self):
        lines = [("class:header", " Projects\n")]
        lines.append(("class:separator", " " + "─" * 80 + "\n"))
        for i, proj in enumerate(self.projects):
            is_cursor = i == self.proj_cursor
            n_convs = len(proj.conversations)
            n_mems = len(proj.memories)
            n_plans = len(self._get_project_plans(proj.path))
            sz = format_size(proj.total_size)
            marker = "▸ " if is_cursor else "  "
            line = (
                f" {marker}{proj.display_name:<42.42}"
                f" {n_convs:3d} convs  {n_mems:2d} mems  {n_plans:2d} plans  {sz:>6s}\n"
            )
            has_mcp = self._project_has_enabled_mcp(proj.path)
            if is_cursor:
                style = "class:cursor"
            elif has_mcp:
                style = "class:mcp"
            else:
                style = ""
            lines.append((style, line))
        if not self.projects:
            lines.append(("", "  (no projects found)\n"))
        return lines

    # ------------------------------------------------------------------
    # Rendering — Project detail
    # ------------------------------------------------------------------

    def _render_conv_list(self):
        proj = self.current_project
        if not proj:
            return [("", "")]
        sort_indicator = f" (sort: {self.conv_sort_key}{' ↓' if self.conv_sort_desc else ' ↑'})"
        lines = [("class:header", f" {proj.display_name}{sort_indicator}\n")]
        lines.append(("class:separator", " " + "─" * 50 + "\n"))

        is_active = self.detail_pane == "conversations"
        convs = self._sorted_convs()
        for i, conv in enumerate(convs):
            is_cursor = i == self.conv_cursor and is_active
            name = conv.title or conv.slug or conv.session_id[:12]
            ts = format_timestamp_short(conv.timestamp)
            sz = format_size(conv.file_size)
            marker = "▸ " if is_cursor else "  "
            line = f" {marker}{ts:<8s} {name:<28.28} {conv.message_count:3d}msgs {sz:>5s}\n"
            style = "class:cursor" if is_cursor else ""
            lines.append((style, line))
        if not convs:
            lines.append(("", "  (no conversations)\n"))

        lines.append(("class:footer", f"\n  {len(convs)} conversations\n"))
        return lines

    def _render_mem_list(self):
        proj = self.current_project
        if not proj:
            return [("", "")]
        lines = [("class:header", " MCP Servers & Memories\n")]
        lines.append(("class:separator", " " + "─" * 28 + "\n"))

        json_key = find_json_key_for_dir(self.config, proj.path) if self.config else None
        if json_key:
            status = get_project_mcp_status(self.config, json_key)
            local_set = set(status["local"])
            if status["enabled"]:
                lines.append(("class:header", " Enabled:\n"))
                for srv in status["enabled"]:
                    style = "class:mcp_local" if srv in local_set else "class:mcp_global"
                    lines.append((style, f"   {srv}\n"))
            if status["disabled"]:
                lines.append(("class:detail", " Disabled:\n"))
                for srv in status["disabled"]:
                    lines.append(("class:detail", f"   {srv}\n"))
            if not status["enabled"] and not status["disabled"]:
                lines.append(("", "  (no MCP servers)\n"))
        else:
            lines.append(("", "  (no .claude.json entry)\n"))

        lines.append(("class:separator", " " + "─" * 28 + "\n"))

        is_active = self.detail_pane == "memories"
        mems = proj.memories
        if mems:
            lines.append(("class:header", " Memories\n"))
        for i, mem in enumerate(mems):
            is_cursor = i == self.mem_cursor and is_active
            marker = "▸ " if is_cursor else "  "
            line = f" {marker}{mem.name:<23.23} [{mem.mem_type or '?'}]\n"
            style = "class:cursor" if is_cursor else ""
            lines.append((style, line))
            if is_cursor and mem.description:
                lines.append(("class:detail", f"    {mem.description[:42]}\n"))

        lines.append(("class:footer", f"\n  {len(mems)} memories\n"))

        plans = self._get_project_plans(proj.path)
        if plans:
            lines.append(("class:separator", " " + "─" * 28 + "\n"))
            lines.append(("class:header", " Plans\n"))
            for p in plans:
                if p.status == PLAN_APPROVED:
                    style = "class:plan_approved"
                elif p.status == PLAN_CANCELLED:
                    style = "class:plan_cancelled"
                else:
                    style = "class:plan_pending"
                lines.append((style, f"   {p.slug[:23]}\n"))

        lines.append(("class:footer", f"  {len(plans)} plans\n"))
        return lines

    # ------------------------------------------------------------------
    # Rendering — Conversation viewer
    # ------------------------------------------------------------------

    def _render_conversation(self):
        lines = [
            ("class:header", f" {self.conv_title}\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
        ]

        msgs = self.current_messages
        total = len(msgs)
        if total == 0:
            lines.append(("", "  (no messages)\n"))
            return lines

        self.conv_msg_scroll = max(0, min(self.conv_msg_scroll, max(0, total - 1)))
        page = msgs[self.conv_msg_scroll:self.conv_msg_scroll + 200]

        for msg in page:
            role = msg.get("type", "?").upper()
            content = msg.get("message", {}).get("content", "")
            ts = msg.get("timestamp", "")[:19] if msg.get("timestamp") else ""
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        texts.append(block)
                content = "\n".join(texts)
            if not content:
                content = "(no text content)"
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            lines.append(("class:role", f" [{role}] {ts}\n"))
            for text_line in content.split("\n"):
                lines.append(("", f"  {text_line}\n"))
            lines.append(("", "\n"))

        if total > 1:
            pct = int(self.conv_msg_scroll / max(1, total) * 100)
            lines.append(("class:footer", f"  Message {self.conv_msg_scroll + 1}/{total} ({pct}%)\n"))

        return lines

    # ------------------------------------------------------------------
    # Rendering — Memory view
    # ------------------------------------------------------------------

    def _render_memory(self):
        mem = self.current_memory
        if not mem:
            return [("", "")]
        lines = [
            ("class:header", f" {mem.name}\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
        ]
        if self.memory_fm:
            lines.append(("class:detail", f" Type: {mem.mem_type or '?'}\n"))
            lines.append(("class:detail", f" Description: {mem.description}\n"))
            if mem.origin_session:
                lines.append(("class:detail", f" Origin session: {mem.origin_session}\n"))
            lines.append(("class:separator", " " + "─" * 80 + "\n"))

        body_lines = self.memory_body.split("\n")
        self.memory_scroll = max(0, min(self.memory_scroll, max(0, len(body_lines) - 1)))
        page = body_lines[self.memory_scroll:self.memory_scroll + 200]
        for text_line in page:
            lines.append(("", f" {text_line}\n"))

        return lines

    # ------------------------------------------------------------------
    # Rendering — Confirm delete
    # ------------------------------------------------------------------

    def _render_confirm_delete(self):
        return [
            ("class:header", f" {self.confirm_title}\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
            ("", "\n"),
            ("class:warn", f"  {self.delete_target}\n"),
            ("", "\n"),
            ("class:detail", f"  {self.delete_path}\n"),
            ("", "\n"),
            ("", "  Press [y] to confirm, [Esc] or [q] to cancel.\n"),
        ]

    # ------------------------------------------------------------------
    # Rendering — Plans view
    # ------------------------------------------------------------------

    def _render_plans(self):
        lines = [("class:header", " Plans Cleanup\n")]
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        if not self.all_plans:
            lines.append(("", "  (no plans found)\n"))
            return lines

        for i, plan in enumerate(self.all_plans):
            is_cursor = i == self.plan_cursor
            ts = format_timestamp_short(plan.timestamp)
            has_file = "file" if plan.plan_paths else "no file"
            marker = "▸ " if is_cursor else "  "
            line = f" {marker}[{plan.status:>9s}]  {plan.slug:<40s}  {plan.project_display:<25s}  {ts}  {has_file}\n"

            if is_cursor:
                style = "class:cursor"
            elif plan.status == PLAN_APPROVED:
                style = "class:plan_approved"
            elif plan.status == PLAN_CANCELLED:
                style = "class:plan_cancelled"
            else:
                style = "class:plan_pending"
            lines.append((style, line))

        removable = sum(1 for p in self.all_plans
                        if p.status in (PLAN_APPROVED, PLAN_CANCELLED) and p.plan_paths)
        pending = sum(1 for p in self.all_plans if p.status == PLAN_PENDING)
        lines.append(("class:footer",
                       f"\n  {len(self.all_plans)} plans | {removable} removable | {pending} pending\n"))
        return lines

    # ------------------------------------------------------------------
    # Main render coordinates
    # ------------------------------------------------------------------

    def _render_main(self):
        if self.view == VIEW_PROJECTS:
            return self._render_projects()
        elif self.view == VIEW_CONVERSATION:
            return self._render_conversation()
        elif self.view == VIEW_MEMORY:
            return self._render_memory()
        elif self.view == VIEW_CONFIRM_DELETE:
            return self._render_confirm_delete()
        elif self.view == VIEW_PLANS:
            return self._render_plans()
        return [("", "")]

    def _render_toolbar(self):
        if self.view == VIEW_PROJECTS:
            return [
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " d:Delete project  "),
                ("class:toolbar", " D:Disable MCP  "),
                ("class:toolbar", " Ctrl-D:Disable all  "),
                ("class:toolbar", " p:Plans cleanup  "),
                ("class:toolbar", " q:Quit  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
        elif self.view == VIEW_PLANS:
            return [
                ("class:toolbar", " d:Delete plan  "),
                ("class:toolbar", " a:Delete all removable  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " q:Quit  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
        elif self.view == VIEW_PROJECT_DETAIL:
            return [
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " d:Delete  "),
                ("class:toolbar", " D:Disable MCP  "),
                ("class:toolbar", " Tab:Switch pane  "),
                ("class:toolbar", " m:MCP status  "),
                ("class:toolbar", " 1:Sort date  "),
                ("class:toolbar", " 2:Sort size  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " q:Quit  "),
            ]
        elif self.view == VIEW_CONFIRM_DELETE:
            return [
                ("class:toolbar.warn", " y:Confirm delete  "),
                ("class:toolbar", " Esc/q:Cancel  "),
            ]
        elif self.view == VIEW_CONVERSATION:
            return [
                ("class:toolbar", " ↑↓:Scroll  "),
                ("class:toolbar", " d:Delete  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " q:Quit  "),
            ]
        else:
            return [
                ("class:toolbar", " ↑↓:Scroll  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " q:Quit  "),
            ]

    def _render_status_bar(self):
        proj_count = len(self.projects)
        conv_total = sum(len(p.conversations) for p in self.projects)
        mem_total = sum(len(p.memories) for p in self.projects)

        if self.view == VIEW_PROJECTS:
            info = f" {proj_count} projects | {conv_total} conversations | {mem_total} memories "
        elif self.view == VIEW_CONFIRM_DELETE:
            info = " confirm delete "
        else:
            info = f" {self.status_message} "

        return [
            ("class:status", info),
            ("class:status.right", " Claude Project Cleaner "),
        ]

    # ------------------------------------------------------------------
    # Key dispatch
    # ------------------------------------------------------------------

    def _handle_up(self, event):
        if self.view == VIEW_PROJECTS and self.projects:
            self.proj_cursor = max(0, self.proj_cursor - 1)
        elif self.view == VIEW_PLANS and self.all_plans:
            self.plan_cursor = max(0, self.plan_cursor - 1)
        elif self.view == VIEW_PROJECT_DETAIL:
            if self.detail_pane == "conversations" and self.current_project:
                if self.current_project.conversations:
                    self.conv_cursor = max(0, self.conv_cursor - 1)
            elif self.current_project:
                if self.current_project.memories:
                    self.mem_cursor = max(0, self.mem_cursor - 1)
        elif self.view == VIEW_CONVERSATION and self.current_messages:
            self.conv_msg_scroll = max(0, self.conv_msg_scroll - 1)
        elif self.view == VIEW_MEMORY and self.memory_body:
            self.memory_scroll = max(0, self.memory_scroll - 1)
        event.app.invalidate()

    def _handle_down(self, event):
        if self.view == VIEW_PROJECTS and self.projects:
            self.proj_cursor = min(len(self.projects) - 1, self.proj_cursor + 1)
        elif self.view == VIEW_PLANS and self.all_plans:
            self.plan_cursor = min(len(self.all_plans) - 1, self.plan_cursor + 1)
        elif self.view == VIEW_PROJECT_DETAIL:
            if self.detail_pane == "conversations" and self.current_project:
                if self.current_project.conversations:
                    self.conv_cursor = min(len(self.current_project.conversations) - 1, self.conv_cursor + 1)
            elif self.current_project:
                if self.current_project.memories:
                    self.mem_cursor = min(len(self.current_project.memories) - 1, self.mem_cursor + 1)
        elif self.view == VIEW_CONVERSATION and self.current_messages:
            self.conv_msg_scroll = min(len(self.current_messages) - 1, self.conv_msg_scroll + 1)
        elif self.view == VIEW_MEMORY and self.memory_body:
            body_lines = self.memory_body.split("\n")
            self.memory_scroll = min(len(body_lines) - 1, self.memory_scroll + 1)
        event.app.invalidate()

    def _handle_page_up(self, event):
        if self.view == VIEW_CONVERSATION:
            self.conv_msg_scroll = max(0, self.conv_msg_scroll - 25)
        elif self.view == VIEW_MEMORY:
            self.memory_scroll = max(0, self.memory_scroll - 25)
        event.app.invalidate()

    def _handle_page_down(self, event):
        if self.view == VIEW_CONVERSATION and self.current_messages:
            self.conv_msg_scroll = min(len(self.current_messages) - 1, self.conv_msg_scroll + 25)
        elif self.view == VIEW_MEMORY and self.memory_body:
            body_lines = self.memory_body.split("\n")
            self.memory_scroll = min(len(body_lines) - 1, self.memory_scroll + 25)
        event.app.invalidate()

    def _handle_enter(self, event):
        if self.view == VIEW_PROJECTS:
            self._enter_project()
        elif self.view == VIEW_PROJECT_DETAIL:
            if self.detail_pane == "conversations":
                self._enter_conversation()
            else:
                self._enter_memory()
        event.app.invalidate()

    def _handle_escape(self, event):
        if self.view in (VIEW_PROJECT_DETAIL, VIEW_CONVERSATION, VIEW_MEMORY, VIEW_PLANS, VIEW_CONFIRM_DELETE):
            self._go_back()
        event.app.invalidate()

    def _handle_q(self, event):
        if self.view == VIEW_CONFIRM_DELETE:
            self._go_back()
        else:
            event.app.exit()

    def _handle_d(self, event):
        if self.view == VIEW_PLANS:
            self._delete_plan_item()
        elif self.view in (VIEW_PROJECTS, VIEW_PROJECT_DETAIL, VIEW_CONVERSATION):
            self._delete_current_item()
        event.app.invalidate()

    def _handle_y(self, event):
        if self.view == VIEW_CONFIRM_DELETE:
            self._confirm_delete()
        event.app.invalidate()

    def _handle_tab(self, event):
        if self.view == VIEW_PROJECT_DETAIL:
            self.detail_pane = "memories" if self.detail_pane == "conversations" else "conversations"
        event.app.invalidate()

    def _handle_conv_sort(self, key, event):
        if self.view == VIEW_PROJECT_DETAIL and self.detail_pane == "conversations":
            if self.conv_sort_key == key:
                self.conv_sort_desc = not self.conv_sort_desc
            else:
                self.conv_sort_key = key
                self.conv_sort_desc = True
            self.conv_cursor = 0
        event.app.invalidate()

    def _handle_toggle_mcp(self, event):
        if self.view == VIEW_PROJECT_DETAIL:
            self.show_mcp = not self.show_mcp
        event.app.invalidate()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _render_detail_preview(self):
        proj = self.current_project
        if not proj:
            return [("", "")]

        if self.show_mcp:
            try:
                data = load_config()
                json_key = find_json_key_for_dir(data, proj.path)
                if json_key:
                    status = get_project_mcp_status(data, json_key)
                    enabled = ",".join(status["enabled"]) or "none"
                    disabled = ",".join(status["disabled"]) or "none"
                    return [
                        ("class:detail.bold", f" MCP servers: "),
                        ("class:detail", f"enabled:[{enabled}] "),
                        ("class:warn", f"disabled:[{disabled}]"),
                    ]
                else:
                    return [("class:detail", " No .claude.json entry for this project")]
            except Exception:
                return [("class:detail", " Error reading config")]

        if self.detail_pane == "conversations" and proj.conversations:
            convs = self._sorted_convs()
            if self.conv_cursor >= len(convs):
                return [("", "")]
            conv = convs[self.conv_cursor]
            chat = format_size(conv.chat_size)
            sub = format_size(conv.subagent_size)
            tool = format_size(conv.tool_size)
            total = format_size(conv.file_size)
            parts = f"chat:{chat}  subagents:{sub}  tools:{tool}  total:{total}"
            line = f" {conv.session_id[:12]}  {parts}"
            try:
                width = get_app().renderer.output.get_size().columns
            except Exception:
                width = 80
            return [("class:detail.bold", line.rjust(width))]
        elif self.detail_pane == "memories" and proj.memories:
            mem = proj.memories[self.mem_cursor]
            desc = mem.description[:120] if mem.description else "(no description)"
            return [("class:detail", f" {mem.name} — {desc} ")]
        return [("", "")]

    def _make_detail_layout(self):
        conv_window = Window(
            content=FormattedTextControl(self._render_conv_list),
            wrap_lines=False,
            width=Dimension(weight=4),
        )
        mem_window = Window(
            content=FormattedTextControl(self._render_mem_list),
            wrap_lines=False,
            width=Dimension(weight=1),
        )

        conv_frame = Frame(
            conv_window,
            title=lambda: " Conversations " + ("*" if self.detail_pane == "conversations" else ""),
        )
        mem_frame = Frame(
            mem_window,
            title=lambda: " MCP & Memories " + ("*" if self.detail_pane == "memories" else ""),
        )

        split = VSplit([conv_frame, mem_frame], padding=1, padding_char="│")
        preview_bar = Window(
            content=FormattedTextControl(self._render_detail_preview),
            height=1,
        )
        return HSplit([split, preview_bar])

    def _render_proj_sidebar(self):
        if not self.projects or self.proj_cursor >= len(self.projects):
            return [("", "")]
        proj = self.projects[self.proj_cursor]
        lines = [("class:header", f" {proj.display_name}\n")]
        lines.append(("class:separator", " " + "─" * 28 + "\n"))

        json_key = find_json_key_for_dir(self.config, proj.path) if self.config else None
        if json_key:
            status = get_project_mcp_status(self.config, json_key)
            local_set = set(status["local"])
            if status["enabled"]:
                lines.append(("class:header", " MCP enabled:\n"))
                for srv in status["enabled"]:
                    style = "class:mcp_local" if srv in local_set else "class:mcp_global"
                    lines.append((style, f"   {srv}\n"))
            if status["disabled"]:
                lines.append(("class:detail", " MCP disabled:\n"))
                for srv in status["disabled"]:
                    lines.append(("class:detail", f"   {srv}\n"))
            if not status["enabled"] and not status["disabled"]:
                lines.append(("", "  (no MCP servers)\n"))
        else:
            lines.append(("", "  (no .claude.json entry)\n"))

        lines.append(("class:separator", " " + "─" * 28 + "\n"))
        mems = proj.memories
        if mems:
            lines.append(("class:header", f" {len(mems)} memories\n"))
            for mem in mems[:10]:
                lines.append(("", f"   {mem.name}\n"))
            if len(mems) > 10:
                lines.append(("", f"   ... +{len(mems) - 10} more\n"))
        else:
            lines.append(("", "  (no memories)\n"))

        plans = self._get_project_plans(proj.path)
        lines.append(("class:separator", " " + "─" * 28 + "\n"))
        if plans:
            lines.append(("class:header", f" {len(plans)} plans\n"))
            for p in plans[:5]:
                if p.status == PLAN_APPROVED:
                    style = "class:plan_approved"
                elif p.status == PLAN_CANCELLED:
                    style = "class:plan_cancelled"
                else:
                    style = "class:plan_pending"
                lines.append((style, f"   {p.slug[:23]}\n"))
            if len(plans) > 5:
                lines.append(("", f"   ... +{len(plans) - 5} more\n"))
        else:
            lines.append(("", "  (no plans)\n"))

        lines.append(("class:separator", " " + "─" * 28 + "\n"))
        lines.append(("class:footer", f" {len(proj.conversations)} convs\n"))
        lines.append(("class:footer", f" {format_size(proj.total_size)}\n"))
        return lines

    def _make_projects_layout(self):
        proj_list = Window(
            content=FormattedTextControl(self._render_projects),
            wrap_lines=False,
            width=Dimension(weight=4),
        )
        sidebar = Window(
            content=FormattedTextControl(self._render_proj_sidebar),
            wrap_lines=False,
            width=Dimension(weight=1),
        )
        proj_frame = Frame(proj_list, title=" Projects ")
        side_frame = Frame(sidebar, title=" Details ")
        return VSplit([proj_frame, side_frame], padding=1, padding_char="│")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        if not _HAS_TUI:
            print("Error: prompt_toolkit is required for TUI mode.", file=sys.stderr)
            print("Install with: pip install prompt_toolkit", file=sys.stderr)
            raise SystemExit(1)

        self.projects = scan_all_projects()
        self.all_plans = scan_all_plans()
        try:
            self.config = load_config()
        except Exception:
            self.config = {}

        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            self._handle_up(event)

        @kb.add("down")
        def _(event):
            self._handle_down(event)

        @kb.add("pageup")
        def _(event):
            self._handle_page_up(event)

        @kb.add("pagedown")
        def _(event):
            self._handle_page_down(event)

        @kb.add("enter")
        def _(event):
            self._handle_enter(event)

        @kb.add("escape")
        def _(event):
            self._handle_escape(event)

        @kb.add("q")
        def _(event):
            self._handle_q(event)

        @kb.add("d")
        def _(event):
            self._handle_d(event)

        @kb.add("y")
        def _(event):
            self._handle_y(event)

        @kb.add("1")
        def _(event):
            self._handle_conv_sort("date", event)

        @kb.add("2")
        def _(event):
            self._handle_conv_sort("size", event)

        @kb.add("tab")
        def _(event):
            self._handle_tab(event)

        @kb.add("m")
        def _(event):
            self._handle_toggle_mcp(event)

        @kb.add("p")
        def _(event):
            if self.view == VIEW_PROJECTS:
                self._enter_plans()
            event.app.invalidate()

        @kb.add("a")
        def _(event):
            if self.view == VIEW_PLANS:
                self._delete_all_removable_plans()
            event.app.invalidate()

        @kb.add("D")
        def _(event):
            if self.view in (VIEW_PROJECTS, VIEW_PROJECT_DETAIL):
                self._disable_project_mcp()
            event.app.invalidate()

        @kb.add("c-d")
        def _(event):
            if self.view == VIEW_PROJECTS:
                self._disable_all_mcp()
            event.app.invalidate()

        @kb.add("backspace")
        def _(event):
            self._handle_escape(event)

        toolbar = Window(content=FormattedTextControl(self._render_toolbar), height=1)
        sep1 = Window(height=1, char="─")

        projects_content = ConditionalContainer(
            content=self._make_projects_layout(),
            filter=Condition(lambda: self.view == VIEW_PROJECTS),
        )
        other_content = ConditionalContainer(
            content=Window(content=FormattedTextControl(self._render_main), wrap_lines=False),
            filter=Condition(lambda: self.view not in (VIEW_PROJECTS, VIEW_PROJECT_DETAIL)),
        )
        detail_content = ConditionalContainer(
            content=self._make_detail_layout(),
            filter=Condition(lambda: self.view == VIEW_PROJECT_DETAIL),
        )

        sep2 = Window(height=1, char="─")
        status = Window(content=FormattedTextControl(self._render_status_bar), height=1)

        root = HSplit([toolbar, sep1, projects_content, other_content, detail_content, sep2, status])

        style = Style.from_dict({
            "toolbar": "bg:#d6e4ff #1a2a3a",
            "toolbar.warn": "bg:#ff4444 #ffffff bold",
            "cursor": "reverse",
            "mcp": "#ffcc00",
            "mcp_local": "#00cc00 bold",
            "mcp_global": "#00cccc",
            "plan_approved": "#00cc00",
            "plan_cancelled": "#888888",
            "plan_pending": "#ffcc00",
            "header": "bold",
            "separator": "#808080",
            "detail": "#555555 italic",
            "detail.bold": "bold #ffffff",
            "role": "bold #0055cc",
            "footer": "italic #888888",
            "warn": "bold #ff4444",
            "status": "bg:#204a87 #ffffff",
            "status.right": "bg:#204a87 #d6e4ff",
        })

        app = Application(
            layout=Layout(root),
            key_bindings=kb,
            style=style,
            full_screen=True,
        )

        app.run()
