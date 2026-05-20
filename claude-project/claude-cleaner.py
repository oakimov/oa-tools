#!/usr/bin/env python3
"""Cross-project Claude Code session & memory browser/cleanup tool."""

import os

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

from claude_shared import (
    PLAN_APPROVED,
    PLAN_CANCELLED,
    PLAN_PENDING,
    PROJECTS_DIR,
    ConversationInfo,
    MemoryInfo,
    PlanInfo,
    ProjectInfo,
    delete_conversation,
    delete_plan,
    delete_project_config,
    delete_project_filesystem_by_dir,
    delete_project_unified,
    find_json_key_for_dir,
    format_size,
    format_timestamp_short,
    get_conversation_messages,
    get_global_mcp_servers,
    get_memory_content,
    get_project_mcp_status,
    get_project_paths,
    load_config,
    save_config,
    scan_all_plans,
    scan_all_projects,
    scan_conversation,
    scan_memories,
)

# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------

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
        """Get existing (files on disk) plans for a project."""
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
        if self.delete_callback:
            self.delete_callback()
        self._go_back()

    def _do_delete_project(self):
        proj = self.projects[self.proj_cursor]

        # Try unified delete via JSON key
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
            # Fallback: filesystem only
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
        if os.path.isfile(self.delete_path):
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
            convs.append(scan_conversation(fpath))
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
            # Yellow highlight when project has enabled MCP servers
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

        # MCP servers section
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

        # Memories section
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

        # Plans section
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

        # MCP status mode
        if self.show_mcp:
            try:
                data = load_config()
                # Find JSON key for this project
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

        # Default: size breakdown
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

        # MCP servers
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

        # Memories
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

        # Plans
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

        # Stats
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


def main():
    CleanerTUI().run()


if __name__ == "__main__":
    main()
