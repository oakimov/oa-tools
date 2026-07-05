"""Interactive TUI for browsing and cleaning up Claude Code project data:
project list -> project detail (conversations + memories/MCP/plans) ->
conversation viewer / memory viewer, with a confirm-before-delete dialog.
"""

import json
import os

import claude_backend as backend
from claude_backend import (
    PLAN_APPROVED,
    PLAN_CANCELLED,
    PROJECTS_DIR,
    extract_block_text,
)
from common import format_size, format_date_short, format_tool_call, format_tool_result, is_within
from tui_kit import ConfirmMixin, MessageScrollMixin, bind_keys, require_tui, run_custom

try:
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.widgets import Frame
except ImportError:
    pass  # tui_kit.require_tui() guards actual use at run() time

VIEW_PROJECTS = "projects"
VIEW_PROJECT_DETAIL = "project_detail"
VIEW_CONVERSATION = "conversation"
VIEW_MEMORY = "memory"
VIEW_CONFIRM_DELETE = "confirm_delete"
VIEW_PLANS = "plans"


def _normalize_message(raw: dict) -> dict:
    """Convert a raw ~/.claude/projects/*.jsonl event into the {role, text,
    timestamp} shape the shared message viewer expects. Includes tool_use
    (command/name + args) and tool_result (output) blocks, not just prose
    text — a turn that's purely a tool call/result otherwise renders as
    "(no text content)"."""
    content = raw.get("message", {}).get("content", "")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                parts.append(format_tool_call(block.get("name", "?"), block.get("input", {})))
            elif btype == "tool_result":
                parts.append(format_tool_result(extract_block_text(block.get("content", ""))))
        content = "\n".join(p for p in parts if p)
    return {
        "role": raw.get("type", "?").upper(),
        "text": content,
        "timestamp": raw.get("timestamp", ""),
    }


class ClaudeCleanerTUI(ConfirmMixin, MessageScrollMixin):
    def __init__(self):
        self.projects = []
        self.view = VIEW_PROJECTS

        self.proj_cursor = 0
        self.sel_proj = set()

        self.current_project = None
        self.detail_pane = "conversations"
        self.conv_cursor = 0
        self.sel_conv = set()
        self.mem_cursor = 0
        self.conv_sort_key = "date"
        self.conv_sort_desc = True

        self._init_message_view()
        self.current_conv_session_id = None

        self.current_memory = None
        self.memory_fm = ""
        self.memory_body = ""
        self.memory_scroll = 0

        self._init_confirm()
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
        json_key = backend.find_json_key_for_dir(self.config, encoded_dir)
        if not json_key:
            return False
        status = backend.get_project_mcp_status(self.config, json_key)
        return len(status["enabled"]) > 0

    def _get_project_plans(self, encoded_dir):
        return [p for p in self.all_plans if p.project_dir == encoded_dir and p.plan_paths]

    def _reset_all_scroll(self):
        self.msg_scroll = 0
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
            self._enter_view(self.confirm_return_view)
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
        self.sel_conv.clear()
        self.mem_cursor = 0
        self.detail_pane = "conversations"
        self.show_mcp = False
        self._enter_view(VIEW_PROJECT_DETAIL)

    def _sorted_convs(self):
        convs = list(self.current_project.conversations)
        if self.conv_sort_key == "size":
            convs.sort(key=lambda c: c.total_size, reverse=self.conv_sort_desc)
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
        self.current_conv_session_id = conv.session_id
        self.msg_scroll = 0
        name = conv.title or conv.slug or conv.session_id[:12]
        if conv.desktop_only:
            self.current_messages = [{
                "role": "INFO",
                "text": ("This session ran in Claude Desktop's Cowork/remote mode and has "
                         "no locally-stored transcript — only the Desktop app's own "
                         f"session-index metadata exists ({conv.message_count} completed "
                         "turns). It is still fully deletable."),
                "timestamp": conv.timestamp,
            }]
            self.msg_title = f"{name}  (Desktop-only, no local transcript)"
            self._enter_view(VIEW_CONVERSATION)
            return
        raw_msgs = backend.get_conversation_messages(conv.session_id, self.current_project.encoded_dir)
        raw_msgs.reverse()
        self.current_messages = [_normalize_message(m) for m in raw_msgs]
        self.msg_title = f"{name}  ({len(raw_msgs)} messages)"
        self._enter_view(VIEW_CONVERSATION)

    def _enter_memory(self):
        if not self.current_project:
            return
        mems = self.current_project.memories
        if not mems or self.mem_cursor >= len(mems):
            return
        self.current_memory = mems[self.mem_cursor]
        self.memory_fm, self.memory_body = backend.get_memory_content(self.current_memory.filepath)
        self.memory_scroll = 0
        self._enter_view(VIEW_MEMORY)

    def _start_conv_delete_confirm(self, conv):
        if conv.desktop_only:
            self._start_confirm(
                f"Desktop session: {conv.title or conv.session_id[:12]}",
                conv.desktop_index_path,
                lambda: self._do_delete_desktop_conv(conv),
                VIEW_PROJECT_DETAIL,
            )
        else:
            self._start_confirm(
                f"Conversation: {conv.slug or conv.session_id[:12]}",
                os.path.join(PROJECTS_DIR, self.current_project.encoded_dir, conv.session_id + ".jsonl"),
                self._do_delete_conversation,
                VIEW_PROJECT_DETAIL,
            )

    def _delete_current_item(self):
        if self.view == VIEW_CONVERSATION:
            if not self.current_project or not self.current_messages:
                return
            session_id = self.current_conv_session_id
            if not session_id:
                return
            conv = next((c for c in self.current_project.conversations if c.session_id == session_id), None)
            if not conv:
                return
            self._start_conv_delete_confirm(conv)
        elif self.view == VIEW_PROJECTS:
            if not self.projects or self.proj_cursor >= len(self.projects):
                return
            proj = self.projects[self.proj_cursor]
            self._start_confirm(
                f"Project: {proj.display_name}",
                os.path.join(PROJECTS_DIR, proj.encoded_dir),
                self._do_delete_project,
                VIEW_PROJECTS,
            )
        elif self.view == VIEW_PROJECT_DETAIL:
            if self.detail_pane == "conversations":
                convs = self._sorted_convs()
                if not convs or self.conv_cursor >= len(convs):
                    return
                conv = convs[self.conv_cursor]
                self._start_conv_delete_confirm(conv)
            else:
                mems = self.current_project.memories if self.current_project else []
                if not mems or self.mem_cursor >= len(mems):
                    return
                mem = mems[self.mem_cursor]
                self._start_confirm(
                    f"Memory: {mem.name}",
                    mem.filepath,
                    self._do_delete_memory,
                    VIEW_PROJECT_DETAIL,
                )
        else:
            return
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _confirm_delete(self):
        self._run_confirm()
        self._go_back()

    def _do_delete_project(self):
        proj = self.projects[self.proj_cursor]
        desktop_removed = sum(
            len(backend.delete_desktop_only_session(c.desktop_index_path))
            for c in proj.conversations if c.desktop_only
        )
        try:
            data = backend.load_config()
            json_key = backend.find_json_key_for_dir(data, proj.encoded_dir)
            if json_key:
                result = backend.delete_project_unified(json_key)
                n = len(result["filesystem_removed"]) + desktop_removed
                self._set_status(f"Deleted: {proj.display_name} (config + {n} items)")
            else:
                removed = backend.delete_project_filesystem_by_dir(proj.encoded_dir)
                self._set_status(f"Deleted: {proj.display_name} ({len(removed) + desktop_removed} filesystem items)")
        except (OSError, json.JSONDecodeError):
            removed = backend.delete_project_filesystem_by_dir(proj.encoded_dir)
            self._set_status(f"Deleted: {proj.display_name} ({len(removed) + desktop_removed} filesystem items)")
        self.projects = [p for p in self.projects if p.encoded_dir != proj.encoded_dir]
        self.proj_cursor = min(self.proj_cursor, max(0, len(self.projects) - 1))

    def _do_delete_conversation(self):
        session_id = os.path.splitext(os.path.basename(self.confirm_detail))[0]
        removed = backend.delete_conversation(session_id, self.current_project.encoded_dir)
        conv_name = self.confirm_target.split(":", 1)[-1].strip() if self.confirm_target else session_id[:12]
        self._set_status(f"Deleted: {conv_name} ({len(removed)} items)")
        if self.current_project:
            self._rescan_project(self.current_project)

    def _do_delete_desktop_conv(self, conv):
        backend.delete_desktop_only_session(conv.desktop_index_path)
        self._set_status(f"Deleted Desktop session: {conv.title or conv.session_id[:12]}")
        if self.current_project:
            self.current_project.conversations = [
                c for c in self.current_project.conversations if c.session_id != conv.session_id
            ]
            self.current_project.total_size -= conv.total_size
            self.conv_cursor = min(self.conv_cursor, max(0, len(self.current_project.conversations) - 1))
            self.sel_conv.clear()

    # ------------------------------------------------------------------
    # Multi-select — projects and conversations
    # ------------------------------------------------------------------

    def _toggle_proj_selection(self):
        if self.view == VIEW_PROJECTS and self.projects:
            self.sel_proj.symmetric_difference_update({self.proj_cursor})

    def _toggle_conv_selection(self):
        if self.view == VIEW_PROJECT_DETAIL and self.detail_pane == "conversations" and self.current_project:
            convs = self._sorted_convs()
            if convs and self.conv_cursor < len(convs):
                self.sel_conv.symmetric_difference_update({self.conv_cursor})

    def _delete_selected_projects(self):
        idxs = sorted(self.sel_proj)
        projs = [self.projects[i] for i in idxs]
        names = [p.display_name for p in projs]
        total_sz = sum(p.total_size for p in projs)
        self._start_confirm(
            f"Delete {len(idxs)} projects",
            f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''} — {format_size(total_sz)}",
            lambda: self._do_delete_selected_projects(projs),
            VIEW_PROJECTS,
        )
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_delete_selected_projects(self, projs):
        total_items = 0
        for proj in projs:
            total_items += sum(
                len(backend.delete_desktop_only_session(c.desktop_index_path))
                for c in proj.conversations if c.desktop_only
            )
            try:
                data = backend.load_config()
                json_key = backend.find_json_key_for_dir(data, proj.encoded_dir)
                if json_key:
                    result = backend.delete_project_unified(json_key)
                    total_items += len(result["filesystem_removed"])
                else:
                    total_items += len(backend.delete_project_filesystem_by_dir(proj.encoded_dir))
            except (OSError, json.JSONDecodeError):
                total_items += len(backend.delete_project_filesystem_by_dir(proj.encoded_dir))
        deleted_dirs = {p.encoded_dir for p in projs}
        self.projects = [p for p in self.projects if p.encoded_dir not in deleted_dirs]
        self.proj_cursor = min(self.proj_cursor, max(0, len(self.projects) - 1))
        self.sel_proj.clear()
        self._set_status(f"Deleted {len(projs)} projects ({total_items} filesystem items)")

    def _delete_selected_convs(self):
        idxs = sorted(self.sel_conv)
        convs = self._sorted_convs()
        items = [convs[i] for i in idxs]
        names = [c.slug or c.session_id[:12] for c in items]
        total_sz = sum(c.total_size for c in items)
        self._start_confirm(
            f"Delete {len(idxs)} conversations",
            f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''} — {format_size(total_sz)}",
            lambda: self._do_delete_selected_convs(items),
            VIEW_PROJECT_DETAIL,
        )
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_delete_selected_convs(self, convs):
        total_items = 0
        for conv in convs:
            if conv.desktop_only:
                total_items += len(backend.delete_desktop_only_session(conv.desktop_index_path))
            else:
                total_items += len(backend.delete_conversation(conv.session_id, self.current_project.encoded_dir))
        self.sel_conv.clear()
        self._set_status(f"Deleted {len(convs)} conversations ({total_items} items)")
        if self.current_project:
            self._rescan_project(self.current_project)

    def _do_delete_memory(self):
        if os.path.isfile(self.confirm_detail) and is_within(PROJECTS_DIR, self.confirm_detail):
            os.remove(self.confirm_detail)
        self._set_status(f"Deleted memory: {os.path.basename(self.confirm_detail)}")
        if self.current_project:
            self._rescan_project(self.current_project)

    def _rescan_project(self, proj):
        proj_dir = os.path.join(PROJECTS_DIR, proj.encoded_dir)
        convs = []
        total_size = 0
        if os.path.isdir(proj_dir):
            desktop_titles = backend.desktop_titles_by_cli_session_id()
            for fname in os.listdir(proj_dir):
                if not fname.endswith(".jsonl"):
                    continue
                fpath = os.path.join(proj_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    conv = backend.scan_conversation(fpath)
                except (FileNotFoundError, OSError):
                    continue
                if not conv.title:
                    conv.title = desktop_titles.get(conv.session_id, "")
                convs.append(conv)
            for dirpath, _, filenames in os.walk(proj_dir):
                for fn in filenames:
                    try:
                        total_size += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
        desktop_convs = backend.scan_desktop_sessions_for_project(proj.encoded_dir)
        convs.extend(desktop_convs)
        total_size += sum(c.total_size for c in desktop_convs)
        convs.sort(key=lambda c: c.timestamp or "", reverse=True)
        proj.conversations = convs
        proj.total_size = total_size
        proj.memories = backend.scan_memories(os.path.join(proj_dir, "memory")) if os.path.isdir(proj_dir) else []
        self.conv_cursor = min(self.conv_cursor, max(0, len(convs) - 1)) if convs else 0
        self.mem_cursor = min(self.mem_cursor, max(0, len(proj.memories) - 1)) if proj.memories else 0
        self.sel_conv.clear()

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
        if plan.status == backend.PLAN_PENDING:
            self._set_status("Cannot delete pending plan")
            return
        if not plan.plan_paths:
            self._set_status("No plan files on disk")
            return
        self._start_confirm(
            f"Plan: {plan.slug} [{plan.status}]",
            ", ".join(plan.plan_paths),
            self._do_delete_plan,
            VIEW_PLANS,
        )
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _delete_all_removable_plans(self):
        removable = [p for p in self.all_plans
                     if p.status in (PLAN_APPROVED, PLAN_CANCELLED) and p.plan_paths]
        if not removable:
            self._set_status("No removable plans with files")
            return
        self._start_confirm(
            f"All removable plans ({len(removable)})",
            "(multiple files)",
            lambda: self._do_delete_all_plans(removable),
            VIEW_PLANS,
        )
        self.confirm_title = "Confirm Delete"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_delete_plan(self):
        plan = self.all_plans[self.plan_cursor]
        removed = backend.delete_plan(plan)
        self._set_status(f"Deleted plan: {plan.slug} ({len(removed)} files)")
        self._rescan_plans()

    def _do_delete_all_plans(self, plans):
        total = 0
        for p in plans:
            total += len(backend.delete_plan(p))
        self._set_status(f"Deleted {len(plans)} plans ({total} files)")
        self._rescan_plans()

    def _rescan_plans(self):
        self.all_plans = backend.scan_all_plans()
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

        data = backend.load_config()
        json_key = backend.find_json_key_for_dir(data, proj.encoded_dir)
        if not json_key:
            self._set_status("No .claude.json entry for this project")
            return

        global_servers = set(backend.get_global_mcp_servers(data))
        local_servers = set(data["projects"][json_key].get("mcpServers", {}).keys())
        all_servers = sorted(global_servers | local_servers)

        if not all_servers:
            self._set_status("No MCP servers to disable")
            return

        self._start_confirm(
            f"Disable MCP servers for: {proj.display_name}",
            f"{len(all_servers)} servers: {', '.join(all_servers)}",
            lambda: self._do_disable_mcp(json_key, all_servers, data),
            self.view,
        )
        self.confirm_title = "Confirm Disable"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _disable_all_mcp(self):
        data = backend.load_config()
        global_servers = set(backend.get_global_mcp_servers(data))
        paths = backend.get_project_paths(data)

        if not global_servers:
            self._set_status("No global MCP servers to disable")
            return

        self._start_confirm(
            f"Disable MCP servers for all {len(paths)} projects",
            f"{len(global_servers)} servers: {', '.join(sorted(global_servers))}",
            lambda: self._do_disable_all_mcp(global_servers, paths, data),
            VIEW_PROJECTS,
        )
        self.confirm_title = "Confirm Disable All"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_disable_mcp(self, json_key, servers, data):
        data["projects"][json_key]["disabledMcpServers"] = servers
        backend.save_config(data)
        self.config = data
        self._set_status(f"Disabled {len(servers)} MCP servers")

    def _do_disable_all_mcp(self, servers, paths, data):
        for path in paths:
            data["projects"][path]["disabledMcpServers"] = list(servers)
        backend.save_config(data)
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
            is_selected = i in self.sel_proj
            n_convs = len(proj.conversations)
            n_mems = len(proj.memories)
            n_plans = len(self._get_project_plans(proj.encoded_dir))
            sz = format_size(proj.total_size)
            sel_char = "✓" if is_selected else " "
            marker = f"▸{sel_char}" if is_cursor else f" {sel_char}"
            line = (
                f" {marker}{proj.display_name:<42.42}"
                f" {n_convs:3d} convs  {n_mems:2d} mems  {n_plans:2d} plans  {sz:>6s}\n"
            )
            has_mcp = self._project_has_enabled_mcp(proj.encoded_dir)
            if is_cursor:
                style = "class:cursor"
            elif is_selected:
                style = "class:selected"
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
            is_selected = i in self.sel_conv
            name = conv.title or conv.slug or conv.session_id[:12]
            ts = format_date_short(conv.timestamp)
            sz = format_size(conv.total_size)
            sel_char = "✓" if is_selected else " "
            marker = f"▸{sel_char}" if is_cursor else f" {sel_char}"
            count_label = "turns" if conv.desktop_only else "msgs"
            cloud_tag = "☁" if conv.desktop_only else " "
            line = f" {marker}{ts:<8s} {cloud_tag}{name:<27.27} {conv.message_count:3d}{count_label} {sz:>5s}\n"
            if is_cursor:
                style = "class:cursor"
            elif is_selected:
                style = "class:selected"
            elif conv.desktop_only:
                style = "class:cloud"
            else:
                style = ""
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

        json_key = backend.find_json_key_for_dir(self.config, proj.encoded_dir) if self.config else None
        if json_key:
            status = backend.get_project_mcp_status(self.config, json_key)
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

        plans = self._get_project_plans(proj.encoded_dir)
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
        return self._render_messages()

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
            lines.append(("", f" {text_line.expandtabs(4)}\n"))

        return lines

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
            ts = format_date_short(plan.timestamp)
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
        pending = sum(1 for p in self.all_plans if p.status == backend.PLAN_PENDING)
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
            return self._render_confirm(self.confirm_title)
        elif self.view == VIEW_PLANS:
            return self._render_plans()
        return [("", "")]

    def _render_toolbar(self):
        if self.view == VIEW_PROJECTS:
            return [
                ("class:toolbar", " Space:Select  "),
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " d:Delete project  "),
                ("class:toolbar", " D:Disable MCP  "),
                ("class:toolbar", " A:Disable all  "),
                ("class:toolbar", " p:Plans cleanup  "),
                ("class:toolbar", " r:Desktop cleanup  "),
                ("class:toolbar", " q:Quit  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ] + ([("class:toolbar.count", f" {len(self.sel_proj)} selected  ")] if self.sel_proj else [])
        elif self.view == VIEW_PLANS:
            return [
                ("class:toolbar", " d:Delete plan  "),
                ("class:toolbar", " a:Delete all removable  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
        elif self.view == VIEW_PROJECT_DETAIL:
            items = [("class:toolbar", " Enter:Open  ")]
            if self.detail_pane == "conversations":
                items.append(("class:toolbar", " Space:Select  "))
            items += [
                ("class:toolbar", " d:Delete  "),
                ("class:toolbar", " D:Disable MCP  "),
                ("class:toolbar", " Tab:Switch pane  "),
                ("class:toolbar", " m:MCP status  "),
                ("class:toolbar", " 1:Sort date  "),
                ("class:toolbar", " 2:Sort size  "),
                ("class:toolbar", " Esc:Back  "),
            ]
            if self.sel_conv:
                items.append(("class:toolbar.count", f" {len(self.sel_conv)} selected  "))
            return items
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
            ]
        else:
            return [
                ("class:toolbar", " ↑↓:Scroll  "),
                ("class:toolbar", " Esc:Back  "),
            ]

    def _render_status_bar(self):
        proj_count = len(self.projects)
        conv_total = sum(len(p.conversations) for p in self.projects)
        mem_total = sum(len(p.memories) for p in self.projects)

        if self.view == VIEW_PROJECTS:
            info = f" {proj_count} projects | {conv_total} conversations | {mem_total} memories "
            if self.status_message and self.status_message != "Ready":
                info += f"| {self.status_message} "
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
        elif self.view == VIEW_CONVERSATION:
            self._handle_msg_up()
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
        elif self.view == VIEW_CONVERSATION:
            self._handle_msg_down()
        elif self.view == VIEW_MEMORY and self.memory_body:
            body_lines = self.memory_body.split("\n")
            self.memory_scroll = min(len(body_lines) - 1, self.memory_scroll + 1)
        event.app.invalidate()

    def _handle_page_up(self, event):
        if self.view == VIEW_CONVERSATION:
            self._handle_msg_page_up()
        elif self.view == VIEW_MEMORY:
            self.memory_scroll = max(0, self.memory_scroll - 25)
        event.app.invalidate()

    def _handle_page_down(self, event):
        if self.view == VIEW_CONVERSATION:
            self._handle_msg_page_down()
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
        if self.view == VIEW_PROJECTS:
            event.app.exit()
        else:
            self._go_back()

    def _handle_d(self, event):
        if self.view == VIEW_PLANS:
            self._delete_plan_item()
        elif self.view == VIEW_PROJECTS and self.sel_proj:
            self._delete_selected_projects()
        elif (self.view == VIEW_PROJECT_DETAIL and self.detail_pane == "conversations"
              and self.sel_conv):
            self._delete_selected_convs()
        elif self.view in (VIEW_PROJECTS, VIEW_PROJECT_DETAIL, VIEW_CONVERSATION):
            self._delete_current_item()
        event.app.invalidate()

    def _handle_space(self, event):
        if self.view == VIEW_PROJECTS:
            self._toggle_proj_selection()
        elif self.view == VIEW_PROJECT_DETAIL:
            self._toggle_conv_selection()
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

    def _handle_p(self, event):
        if self.view == VIEW_PROJECTS:
            self._enter_plans()
        event.app.invalidate()

    def _handle_plan_delete_all(self, event):
        if self.view == VIEW_PLANS:
            self._delete_all_removable_plans()
        event.app.invalidate()

    def _handle_disable_mcp_key(self, event):
        if self.view in (VIEW_PROJECTS, VIEW_PROJECT_DETAIL):
            self._disable_project_mcp()
        event.app.invalidate()

    def _handle_disable_all_mcp_key(self, event):
        if self.view == VIEW_PROJECTS:
            self._disable_all_mcp()
        event.app.invalidate()

    def _reconcile_desktop_sessions(self):
        orphans = backend.find_orphan_desktop_sessions()
        if not orphans:
            self._set_status("No orphaned Claude Desktop session entries")
            return
        self._start_confirm(
            "Claude Desktop session index cleanup",
            f"{len(orphans)} orphaned entries (no matching transcript) in claude-code-sessions/",
            lambda: self._do_reconcile_desktop(orphans),
            VIEW_PROJECTS,
        )
        self.confirm_title = "Confirm Cleanup"
        self._enter_view(VIEW_CONFIRM_DELETE)

    def _do_reconcile_desktop(self, orphans):
        n = backend.delete_orphan_desktop_sessions(orphans)
        self._set_status(f"Removed {n} orphaned Claude Desktop session index entries")

    def _handle_r(self, event):
        if self.view == VIEW_PROJECTS:
            self._reconcile_desktop_sessions()
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
                data = backend.load_config()
                json_key = backend.find_json_key_for_dir(data, proj.encoded_dir)
                if json_key:
                    status = backend.get_project_mcp_status(data, json_key)
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
            if conv.desktop_only:
                parts = "Desktop-only session (no local transcript, remote/cloud Cowork run)"
            else:
                chat = format_size(conv.chat_size)
                sub = format_size(conv.subagent_size)
                tool = format_size(conv.tool_size)
                total = format_size(conv.total_size)
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

        json_key = backend.find_json_key_for_dir(self.config, proj.encoded_dir) if self.config else None
        if json_key:
            status = backend.get_project_mcp_status(self.config, json_key)
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

        plans = self._get_project_plans(proj.encoded_dir)
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

    def _setup_keybindings(self):
        return bind_keys({
            "up": self._handle_up,
            "down": self._handle_down,
            "pageup": self._handle_page_up,
            "pagedown": self._handle_page_down,
            "enter": self._handle_enter,
            "escape": self._handle_escape,
            "q": self._handle_q,
            "space": self._handle_space,
            "d": self._handle_d,
            "y": self._handle_y,
            "1": lambda event: self._handle_conv_sort("date", event),
            "2": lambda event: self._handle_conv_sort("size", event),
            "tab": self._handle_tab,
            "m": self._handle_toggle_mcp,
            "p": self._handle_p,
            "a": self._handle_plan_delete_all,
            "D": self._handle_disable_mcp_key,
            "A": self._handle_disable_all_mcp_key,
            "r": self._handle_r,
            "backspace": self._handle_escape,
        })

    def run(self):
        require_tui()
        self.projects = backend.scan_all_projects()
        self.all_plans = backend.scan_all_plans()
        try:
            self.config = backend.load_config()
        except (OSError, json.JSONDecodeError):
            self.config = {}

        kb = self._setup_keybindings()

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
        run_custom(root, kb)
