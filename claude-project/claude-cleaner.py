#!/usr/bin/env python3
"""Cross-project Claude Code session & memory browser/cleanup tool."""

import json
import os
import re
import shutil
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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

CLAUDE_DIR = os.path.expanduser("~/.claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")
SESSION_ENV_DIR = os.path.join(CLAUDE_DIR, "session-env")
FILE_HISTORY_DIR = os.path.join(CLAUDE_DIR, "file-history")


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


# ---------------------------------------------------------------------------
# Data scanning
# ---------------------------------------------------------------------------

def resolve_project_realpath(project_dir: str) -> str:
    """Extract the real project path from ~/.claude/projects/ subdirectory.

    The dirname encodes the path by replacing / with -, which is lossy
    when directory names contain hyphens. Read cwd from the first user
    message in any conversation file instead.
    """
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
    # Fallback: heuristic decode for home dir
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
            for dirpath, dirnames, filenames in os.walk(subagent_dir):
                for fn in filenames:
                    try:
                        subagent_sz += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
        if os.path.isdir(tool_dir):
            for dirpath, dirnames, filenames in os.walk(tool_dir):
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

        for dirpath, dirnames, filenames in os.walk(proj_dir):
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


def format_size(sz: int) -> str:
    if sz < 1024:
        return f"{sz}B"
    elif sz < 1024 * 1024:
        return f"{sz / 1024:.0f}K"
    else:
        return f"{sz / 1024 / 1024:.1f}M"


def format_timestamp_short(ts: str) -> str:
    """Like 'May 20' or '2025-12-01' if older than 6 months."""
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
# TUI
# ---------------------------------------------------------------------------

VIEW_PROJECTS = "projects"
VIEW_PROJECT_DETAIL = "project_detail"
VIEW_CONVERSATION = "conversation"
VIEW_MEMORY = "memory"
VIEW_CONFIRM_DELETE = "confirm_delete"


class CleanerTUI:
    def __init__(self):
        self.projects: List[ProjectInfo] = []
        self.view = VIEW_PROJECTS

        # project list state
        self.proj_cursor = 0

        # project detail state
        self.current_project: Optional[ProjectInfo] = None
        self.detail_pane = "conversations"
        self.conv_cursor = 0
        self.mem_cursor = 0
        self.conv_sort_key = "date"  # "date" | "size"
        self.conv_sort_desc = True

        # conversation view state
        self.current_messages: List[dict] = []
        self.conv_msg_scroll = 0
        self.conv_title = ""

        # memory view state
        self.current_memory: Optional[MemoryInfo] = None
        self.memory_fm = ""
        self.memory_body = ""
        self.memory_scroll = 0

        # confirm delete state
        self.delete_target = ""
        self.delete_path = ""
        self.delete_callback = None
        self.delete_return_view = VIEW_PROJECT_DETAIL

        self.status_message = "Ready"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str):
        self.status_message = text

    def _reset_all_scroll(self):
        self.conv_msg_scroll = 0
        self.memory_scroll = 0

    def _enter_view(self, view: str):
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

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------

    def _enter_project(self):
        if not self.projects:
            return
        if self.proj_cursor >= len(self.projects):
            return
        self.current_project = self.projects[self.proj_cursor]
        self.conv_cursor = 0
        self.mem_cursor = 0
        self.detail_pane = "conversations"
        self._enter_view(VIEW_PROJECT_DETAIL)

    def _sorted_convs(self):
        """Return the current project's conversations sorted by current sort key."""
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
            if not self.current_project:
                return
            # find the conversation by matching session_id from current messages
            if not self.current_messages:
                return
            session_id = None
            for msg in self.current_messages:
                sid = msg.get("sessionId")
                if sid:
                    session_id = sid
                    break
            if not session_id:
                return
            convs = self.current_project.conversations
            conv = next((c for c in convs if c.session_id == session_id), None)
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
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _confirm_delete(self):
        if self.delete_callback:
            self.delete_callback()
        self._go_back()

    def _do_delete_project(self):
        path = self.delete_path
        proj_name = os.path.basename(path)
        if os.path.isdir(path):
            shutil.rmtree(path)
            self.projects = [p for p in self.projects if p.path != proj_name]
            self.proj_cursor = min(self.proj_cursor, max(0, len(self.projects) - 1))
            self._set_status(f"Deleted project: {self.delete_target}")

    def _do_delete_conversation(self):
        path = self.delete_path
        session_id = os.path.splitext(os.path.basename(path))[0]
        conv_dir = os.path.splitext(path)[0]
        if os.path.isfile(path):
            os.remove(path)
        if os.path.isdir(conv_dir):
            shutil.rmtree(conv_dir)
        # Clean up session artifacts across ~/.claude/
        env_dir = os.path.join(SESSION_ENV_DIR, session_id)
        if os.path.isdir(env_dir):
            shutil.rmtree(env_dir)
        fh_dir = os.path.join(FILE_HISTORY_DIR, session_id)
        if os.path.isdir(fh_dir):
            shutil.rmtree(fh_dir)
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
                except (OSError, json.JSONDecodeError):
                    pass
        conv_name = self.delete_target.split(":", 1)[-1].strip() if self.delete_target else session_id[:12]
        self._set_status(f"Deleted: {conv_name}")
        if self.current_project:
            self._rescan_project(self.current_project)

    def _do_delete_memory(self):
        path = self.delete_path
        if os.path.isfile(path):
            os.remove(path)
            self._set_status(f"Deleted memory: {os.path.basename(path)}")
            if self.current_project:
                self._rescan_project(self.current_project)

    def _rescan_project(self, proj: ProjectInfo):
        proj_dir = os.path.join(PROJECTS_DIR, proj.path)
        convs = []
        total_size = 0
        for fname in os.listdir(proj_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(proj_dir, fname)
            if not os.path.isfile(fpath):
                continue
            conv = scan_conversation(fpath)
            convs.append(conv)
        for dirpath, dirnames, filenames in os.walk(proj_dir):
            for fn in filenames:
                fpath = os.path.join(dirpath, fn)
                try:
                    total_size += os.path.getsize(fpath)
                except OSError:
                    pass
        convs.sort(key=lambda c: c.timestamp or "", reverse=True)
        proj.conversations = convs
        proj.total_size = total_size
        proj.memories = scan_memories(os.path.join(proj_dir, "memory"))
        # clamp cursors
        self.conv_cursor = min(self.conv_cursor, max(0, len(convs) - 1)) if convs else 0
        self.mem_cursor = min(self.mem_cursor, max(0, len(proj.memories) - 1)) if proj.memories else 0

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
            sz = format_size(proj.total_size)
            marker = "▸ " if is_cursor else "  "
            line = (
                f" {marker}{proj.display_name:<50.50}"
                f" {n_convs:3d} convs  {n_mems:2d} mems  {sz:>6s}\n"
            )
            style = "class:cursor" if is_cursor else ""
            lines.append((style, line))
        if not self.projects:
            lines.append(("", "  (no projects found)\n"))
        return lines

    # ------------------------------------------------------------------
    # Rendering — Project detail (conversations & memories in VSplit)
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

        total = len(convs)
        lines.append(("class:footer", f"\n  {total} conversations\n"))
        return lines

    def _render_mem_list(self):
        proj = self.current_project
        if not proj:
            return [("", "")]
        lines = [("class:header", " Memories\n")]
        lines.append(("class:separator", " " + "─" * 28 + "\n"))

        is_active = self.detail_pane == "memories"
        mems = proj.memories
        for i, mem in enumerate(mems):
            is_cursor = i == self.mem_cursor and is_active
            marker = "▸ " if is_cursor else "  "
            line = f" {marker}{mem.name:<23.23} [{mem.mem_type or '?'}]\n"
            style = "class:cursor" if is_cursor else ""
            lines.append((style, line))
            if is_cursor and mem.description:
                lines.append(("class:detail", f"    {mem.description[:42]}\n"))
        if not mems:
            lines.append(("", "  (no memories)\n"))

        total = len(mems)
        lines.append(("class:footer", f"\n  {total} memories\n"))
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
            ("class:header", " Confirm Delete\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
            ("", "\n"),
            ("class:warn", f"  Delete: {self.delete_target}\n"),
            ("", "\n"),
            ("class:detail", f"  Path: {self.delete_path}\n"),
            ("", "\n"),
            ("", "  Press [y] to confirm, [Esc] or [q] to cancel.\n"),
        ]

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
        return [("", "")]

    def _render_toolbar(self):
        if self.view == VIEW_PROJECTS:
            return [
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " d:Delete project  "),
                ("class:toolbar", " q:Quit  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
        elif self.view == VIEW_PROJECT_DETAIL:
            return [
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " d:Delete  "),
                ("class:toolbar", " Tab:Switch pane  "),
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
        if self.view in (VIEW_PROJECT_DETAIL, VIEW_CONVERSATION, VIEW_MEMORY, VIEW_CONFIRM_DELETE):
            self._go_back()
        event.app.invalidate()

    def _handle_q(self, event):
        if self.view == VIEW_CONFIRM_DELETE:
            self._go_back()
        else:
            event.app.exit()

    def _handle_d(self, event):
        if self.view in (VIEW_PROJECTS, VIEW_PROJECT_DETAIL, VIEW_CONVERSATION):
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

    def _handle_conv_sort(self, key: str, event):
        if self.view == VIEW_PROJECT_DETAIL and self.detail_pane == "conversations":
            if self.conv_sort_key == key:
                self.conv_sort_desc = not self.conv_sort_desc
            else:
                self.conv_sort_key = key
                self.conv_sort_desc = True
            self.conv_cursor = 0
        event.app.invalidate()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _render_detail_preview(self):
        proj = self.current_project
        if not proj:
            return [("", "")]
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
            title=lambda: " Memories " + ("*" if self.detail_pane == "memories" else ""),
        )

        split = VSplit([conv_frame, mem_frame], padding=1, padding_char="│")
        preview_bar = Window(
            content=FormattedTextControl(self._render_detail_preview),
            height=1,
        )
        return HSplit([split, preview_bar])

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        self.projects = scan_all_projects()

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

        @kb.add("backspace")
        def _(event):
            self._handle_escape(event)

        toolbar = Window(content=FormattedTextControl(self._render_toolbar), height=1)
        sep1 = Window(height=1, char="─")

        main_content = ConditionalContainer(
            content=Window(content=FormattedTextControl(self._render_main), wrap_lines=False),
            filter=Condition(lambda: self.view != VIEW_PROJECT_DETAIL),
        )
        detail_content = ConditionalContainer(
            content=self._make_detail_layout(),
            filter=Condition(lambda: self.view == VIEW_PROJECT_DETAIL),
        )

        sep2 = Window(height=1, char="─")
        status = Window(content=FormattedTextControl(self._render_status_bar), height=1)

        root = HSplit([toolbar, sep1, main_content, detail_content, sep2, status])

        style = Style.from_dict({
            "toolbar": "bg:#d6e4ff #1a2a3a",
            "toolbar.warn": "bg:#ff4444 #ffffff bold",
            "cursor": "reverse",
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


def main():
    CleanerTUI().run()


if __name__ == "__main__":
    main()
