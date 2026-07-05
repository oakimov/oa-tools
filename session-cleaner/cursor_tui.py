"""Interactive TUI for browsing and cleaning up Cursor AI chat history:
workspace list -> conversation list -> message viewer, built on the shared
browser_tui.ListDrillTUI engine (the same one Codex and OpenCode use).

Cursor has three surfaces, all reachable from CursorCleanerTUI:
- **IDE** (the default view): workspace -> conversation -> message, from the
  global SQLite store.
- **CLI** (`c` key): `CursorCliChatsTUI`, a second, independent ListDrillTUI
  instance for cursor-agent's ~/.cursor/chats/ store — embedded rather than
  subclassed since a single class can't hold two different ListDrillTUI
  configurations at once; CursorCleanerTUI delegates rendering and key
  dispatch to it while `self.mode == "cli"`.
- **Agent projects** (`g` key): Cursor's local "Background Agents" — a
  bespoke pair of views implemented directly here, since members are either
  real chats or agent-only with no per-member delete, which doesn't fit the
  project/session/message shape at all.
"""

import os

import cursor_backend as backend
from browser_tui import VIEW_CONFIRM, VIEW_MESSAGES, VIEW_MID, VIEW_TOP, ListDrillTUI
from common import format_relative_ms, format_size

VIEW_AGENTS = "agents"
VIEW_AGENT_MEMBERS = "agent_members"


class CursorCliChatsTUI(ListDrillTUI):
    """cursor-agent CLI chat browser: workspace -> chat -> message. Embedded
    (not run standalone) by CursorCleanerTUI's `c` view."""

    APP_TITLE = "Cursor CLI Chats"
    TOP_NOUN = "workspace"
    TOP_NOUN_PLURAL = "workspaces"
    MID_NOUN_PLURAL = "chats"
    NO_TOP_MSG = "(no CLI chats found)"
    NO_MID_MSG = "(no chats)"
    SUPPORTS_TOP_SELECT = True

    def _scan_top(self):
        return backend.scan_cli_workspaces()

    def _top_label(self, ws):
        return ws.display_name

    def _top_children(self, ws):
        return ws.chats

    def _top_size(self, ws):
        return ws.total_size

    def _mid_row_text(self, chat):
        ts = format_relative_ms(chat.updated_at)
        sz = format_size(chat.total_size)
        name = chat.title.strip() or "(untitled)"
        return f"{ts:<10s} {name:<34.34}  {chat.prompt_count:3d}p  {sz:>6s}  {chat.chat_id[:8]}\n"

    def _mid_name(self, chat):
        return chat.title.strip() or chat.chat_id[:12]

    def _get_messages(self, chat):
        return backend.get_cli_chat_messages(chat)

    def _confirm_detail_one(self, chat):
        return f"{chat.chat_id[:20]}…  |  {chat.prompt_count} prompts  |  {format_size(chat.total_size)}"

    def _confirm_detail_many(self, chats):
        total_sz = sum(c.total_size for c in chats)
        names = [self._mid_name(c) for c in chats]
        return f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''}  |  {format_size(total_sz)}"

    def _delete_mid_one(self, chat):
        r = backend.delete_cli_chat(chat)
        extra = ", transcript removed" if r["transcript_removed"] else ""
        return f"Deleted: {self._mid_name(chat)} ({format_size(r['bytes'])}{extra})"

    def _delete_mid_many(self, chats):
        r = backend.delete_cli_chats(chats)
        return f"Deleted {r['chats']} chats ({format_size(r['bytes'])}, {r['transcripts']} transcripts removed)"

    def _delete_top_many(self, workspaces):
        all_chats = [c for w in workspaces for c in w.chats]
        return self._delete_mid_many(all_chats)


class CursorCleanerTUI(ListDrillTUI):
    APP_TITLE = "Cursor Chat Cleaner"
    TOP_NOUN = "workspace"
    TOP_NOUN_PLURAL = "workspaces"
    MID_NOUN_PLURAL = "conversations"
    NO_TOP_MSG = "(no conversations found)"
    NO_MID_MSG = "(no conversations)"
    SUPPORTS_RECONCILE = True
    SUPPORTS_TOP_SELECT = True
    SUPPORTS_ARCHIVE = True
    DELETE_ALL_KEY = "A"

    def __init__(self):
        super().__init__()
        self.msg_return_view = VIEW_MID

        # Agent projects (Cursor "glass" Background Agents)
        self.agent_projects = []
        self.agent_cursor = 0
        self.current_agent = None
        self.agent_members = []
        self.amem_cursor = 0

        # CLI chats (cursor-agent) — a second, independently-scanned
        # ListDrillTUI embedded here; see CursorCliChatsTUI above.
        self.mode = "main"
        self.cli_browser = None

    def _in_cli_mode(self):
        return self.mode == "cli" and self.cli_browser is not None

    def _enter_cli_mode(self):
        if self.cli_browser is None:
            self.cli_browser = CursorCliChatsTUI()
            self.cli_browser.top_items = backend.scan_cli_workspaces()
        self.mode = "cli"

    # ------------------------------------------------------------------
    # ListDrillTUI hooks — workspace -> conversation -> message flow
    # ------------------------------------------------------------------

    def _display_folder(self, folder):
        return os.path.basename(os.path.normpath(folder)) if folder and os.path.sep in folder else folder

    def _scan_top(self):
        return backend.scan_conversations()

    def _top_label(self, ws):
        return self._display_folder(ws.project_folder)

    def _top_children(self, ws):
        return ws.conversations

    def _top_size(self, ws):
        return ws.total_size

    def _visible_children(self, ws):
        """Conversations worth showing, newest first — filters out empty
        drafts. Newer Cursor versions store message content encrypted
        per-composer (see cursor_backend.get_bubble_messages), so a real
        (non-draft) conversation can have zero locally-readable bubbles and
        no title; `is_draft` is what Cursor itself uses to decide this, so
        we trust it the same way the backend's workspace-level filter does."""
        return [c for c in sorted(ws.conversations, key=lambda c: c.updated_at, reverse=True)
                if c.bubble_count > 0 or c.name or not c.is_draft]

    def _mid_header_suffix(self, ws, items):
        total = len(ws.conversations)
        shown = len(items)
        return f" ({total - shown} empty drafts hidden)" if shown < total else ""

    def _mid_header_detail_lines(self, ws):
        if os.path.sep in ws.project_folder:
            return [("class:detail", f"  {ws.project_folder}\n")]
        return []

    def _mid_row_text(self, conv):
        name = conv.name or ("(empty)" if conv.is_draft else "(untitled)")
        ts = format_relative_ms(conv.updated_at)
        sz = format_size(conv.total_size)
        msgs = f"{conv.bubble_count:4d} msgs" if conv.bubble_count else "   n/a"
        flags = ""
        if conv.is_archived:
            flags += " [archived]"
        if conv.is_subagent:
            flags += " [sub]"
        return f"{ts:<10s} {name:<34.34}  {msgs}  {sz:>6s}{flags}\n"

    def _mid_name(self, conv):
        return conv.name or conv.composer_id[:12]

    def _get_messages(self, conv):
        return backend.get_bubble_messages(conv.composer_id)

    def _empty_fields_for_mid(self, conv):
        if not conv or conv.is_draft:
            return []
        return [
            ("Status", "no readable transcript (checked plain storage and "
                       "attempted encrypted-blob decryption)"),
            ("Note", "still fully deletable — a real (non-draft) session can "
                     "have no locally readable messages yet, e.g. still in progress"),
            ("ID", conv.composer_id),
            ("Workspace", conv.workspace_id),
        ]

    def _enter_mid(self):
        super()._enter_mid()
        if self.view == VIEW_MESSAGES:
            self.msg_return_view = VIEW_MID

    # ---- confirm dialogs ----------------------------------------------

    def _confirm_detail_top(self, ws):
        return (f"{len(ws.conversations)} conversations, {format_size(ws.total_size)} — "
                f"removes all data including workspace storage")

    def _confirm_detail_one(self, conv):
        return f"{conv.bubble_count} bubbles, {format_size(conv.total_size)}"

    def _confirm_detail_many(self, convs):
        names = [self._mid_name(c) for c in convs]
        total_sz = sum(c.total_size for c in convs)
        return f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''} — {format_size(total_sz)}"

    # ---- deletion -------------------------------------------------------

    def _delete_top_one(self, ws):
        """Thorough workspace delete — also removes the workspace storage
        directory. Distinct from `_delete_mid_many`, which only empties out
        conversations one by one (used by "delete all in workspace")."""
        try:
            r = backend.delete_workspace(ws.workspace_id)
        except Exception as e:
            return f"Error: {e}"
        parts = [f"{r['conversations']} convs, {r['bubbles']} bubbles"]
        if "workspace_dir" in r:
            parts.append("workspace dir removed")
        return f"Deleted: {self._top_label(ws)} ({', '.join(parts)})"

    def _delete_top_many(self, workspaces):
        total = {"conversations": 0, "bubbles": 0, "workspaces": 0}
        for ws in workspaces:
            try:
                r = backend.delete_workspace(ws.workspace_id)
                total["conversations"] += r["conversations"]
                total["bubbles"] += r["bubbles"]
                total["workspaces"] += 1
            except Exception as e:
                return f"Error deleting {ws.project_folder[:20]}: {e}"
        return (f"Deleted {total['workspaces']} workspaces "
                f"({total['conversations']} convs, {total['bubbles']} bubbles)")

    def _delete_mid_one(self, conv):
        try:
            r = backend.delete_conversation(conv.composer_id)
            return (f"Deleted: {self._mid_name(conv)} (header:{r['composer_header']}, "
                    f"bubbles:{r['bubbles']}, checkpoints:{r['checkpoints']})")
        except Exception as e:
            return f"Error: {e}"

    def _delete_mid_many(self, convs):
        total_c = 0
        total_b = 0
        for conv in convs:
            try:
                r = backend.delete_conversation(conv.composer_id)
                total_c += 1
                total_b += r["bubbles"]
            except Exception as e:
                return f"Error deleting {conv.composer_id[:12]}: {e}"
        return f"Deleted {total_c} conversations ({total_b} bubbles)"

    def _archive_mid(self, conv):
        new_state = not conv.is_archived
        backend.archive_conversation(conv.composer_id, new_state)
        conv.is_archived = 1 if new_state else 0
        status = "Archived" if new_state else "Unarchived"
        return f"{status}: {self._mid_name(conv)}"

    def _reconcile_action(self):
        try:
            r = backend.reconcile_storage()
            a = backend.reconcile_agents()
        except Exception as e:
            return f"Error: {e}"
        if "error" in r:
            return f"Reconcile error: {r['error']}"
        parts = [f"{r['table']} table", f"{r['bubbles']} bubbles", f"{r['checkpoints']} checkpoints"]
        agent_bits = a["membership"] + a["ui_state"] + a["selected"] + a["blobs"]
        if agent_bits:
            parts.append(f"agents: {a['blobs']} blobs/{format_size(a['bytes'])}, "
                         f"{a['membership']} memberships")
        return f"Reconciled ({', '.join(parts)})"

    # ------------------------------------------------------------------
    # Agent projects (Cursor "glass" Background Agents) — bespoke sub-browser
    # ------------------------------------------------------------------

    def _enter_agents(self):
        self.agent_projects = backend.scan_agent_projects()
        self.agent_cursor = 0
        self.view = VIEW_AGENTS

    def _enter_agent_members(self):
        if not self.agent_projects or self.agent_cursor >= len(self.agent_projects):
            return
        self.current_agent = self.agent_projects[self.agent_cursor]
        self.agent_members = backend.get_agent_members(self.current_agent.project_id)
        self.amem_cursor = 0
        self.view = VIEW_AGENT_MEMBERS

    def _enter_agent_member_messages(self):
        if not self.agent_members or self.amem_cursor >= len(self.agent_members):
            return
        m = self.agent_members[self.amem_cursor]
        if not m["is_composer"]:
            self._set_status("Agent-only member — no viewable chat transcript")
            return
        self.current_messages = backend.get_bubble_messages(m["member_id"])
        self.msg_scroll = 0
        self.msg_title = f"{m['member_id'][:12]}  ({len(self.current_messages)} messages)"
        self.msg_return_view = VIEW_AGENT_MEMBERS
        self.view = VIEW_MESSAGES

    def _delete_agent(self):
        if not self.agent_projects or self.agent_cursor >= len(self.agent_projects):
            return
        a = self.agent_projects[self.agent_cursor]
        preserved = (f"  ({len(a.composer_member_ids)} real chats will be kept)"
                     if a.composer_member_ids else "")
        self._start_confirm(
            f"Delete agent project: {a.name}",
            f"{len(a.member_ids)} members, ~{format_size(a.attributed_size)} agent cache — "
            f"removes grouping, UI state & agent blobs{preserved}",
            self._do_delete_agent,
            VIEW_AGENTS,
        )
        self.view = VIEW_CONFIRM

    def _do_delete_agent(self):
        a = self.agent_projects[self.agent_cursor]
        try:
            r = backend.delete_agent_project(a.project_id)
            msg = (f"Deleted agent project: {a.name} "
                   f"({r['members']} members, {r['blobs']} blobs/{format_size(r['bytes'])}, "
                   f"{r['ui_state']} UI keys)")
            if r["preserved_chats"]:
                msg += f" — {r['preserved_chats']} real chats preserved"
            self._set_status(msg)
        except Exception as e:
            self._set_status(f"Error: {e}")
        self.agent_projects = backend.scan_agent_projects()
        self.agent_cursor = min(self.agent_cursor, max(0, len(self.agent_projects) - 1))

    # ------------------------------------------------------------------
    # Rendering — agent views (base engine renders workspace/conv/messages)
    # ------------------------------------------------------------------

    def _render_agents(self):
        lines = [("class:header", " Cursor Agent Projects (Background Agents)\n")]
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        for i, a in enumerate(self.agent_projects):
            cursor = i == self.agent_cursor
            marker = "▸ " if cursor else "  "
            style = "class:cursor" if cursor else ""
            folder = self._display_folder(a.workspace_path)
            real = f"  {len(a.composer_member_ids)} real chats" if a.composer_member_ids else ""
            arch = " [archived]" if a.is_archived else ""
            line = (f" {marker}{a.name[:34]:<34.34}  {folder:<20.20}  "
                    f"{len(a.member_ids):3d} members  ~{format_size(a.attributed_size):>6s}{real}{arch}\n")
            lines.append((style, line))

        if not self.agent_projects:
            lines.append(("", "  (no agent projects)\n"))

        total_mem = sum(len(a.member_ids) for a in self.agent_projects)
        total_sz = sum(a.attributed_size for a in self.agent_projects)
        lines.append(("class:footer",
                       f"\n  {len(self.agent_projects)} agent projects, {total_mem} members, "
                       f"~{format_size(total_sz)} attributable agent cache\n"))
        lines.append(("class:detail",
                       "  Real chats that are also agent members are preserved on delete; "
                       "use Reconcile (r) to sweep leftover agent blobs.\n"))
        return lines

    def _render_agent_members(self):
        a = self.current_agent
        if not a:
            return [("", "")]
        lines = [("class:header", f" {a.name}  —  {len(self.agent_members)} members\n")]
        lines.append(("class:detail", f"  workspace: {a.workspace_path}\n"))
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        for i, m in enumerate(self.agent_members):
            cursor = i == self.amem_cursor
            marker = "▸ " if cursor else "  "
            style = "class:cursor" if cursor else ""
            if m["is_composer"]:
                kind = f"real chat, {m['bubble_count']} msgs"
                kstyle = "class:mcp_local"
            else:
                kind = "agent-only"
                kstyle = "class:detail"
            lines.append((style, f" {marker}{m['member_id']:<40.40}  "))
            lines.append((style if cursor else kstyle, f"{kind}\n"))

        real = len(a.composer_member_ids)
        lines.append(("class:footer",
                       f"\n  {len(self.agent_members)} members ({real} real chats preserved on delete, "
                       f"{len(self.agent_members) - real} agent-only)\n"))
        return lines

    def _render_main(self):
        if self._in_cli_mode():
            return self.cli_browser._render_main()
        if self.view == VIEW_AGENTS:
            return self._render_agents()
        elif self.view == VIEW_AGENT_MEMBERS:
            return self._render_agent_members()
        return super()._render_main()

    def _render_toolbar(self):
        if self._in_cli_mode():
            items = list(self.cli_browser._render_toolbar())
            if self.cli_browser.view == VIEW_TOP:
                items.append(("class:toolbar", " Esc:Back to Cursor  "))
            return items
        if self.view == VIEW_TOP:
            sel = len(self.sel_top)
            return [
                ("class:toolbar", " Space:Select  "),
                ("class:toolbar", " d:Delete  "),
                ("class:toolbar", " r:Reconcile  "),
                ("class:toolbar", " g:Agent projects  "),
                ("class:toolbar", " c:CLI chats  "),
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " q:Quit  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ] + ([("class:toolbar.count", f" {sel} selected  ")] if sel else [])
        elif self.view == VIEW_AGENTS:
            return [
                ("class:toolbar", " Enter:Members  "),
                ("class:toolbar", " d:Delete project  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
        elif self.view == VIEW_AGENT_MEMBERS:
            return [
                ("class:toolbar", " Enter:View chat  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
        return super()._render_toolbar()

    def _render_status_bar(self):
        if self._in_cli_mode():
            return [
                ("class:status", f" {self.cli_browser.status_message} "),
                ("class:status.right", " Cursor CLI Chats "),
            ]
        return [
            ("class:status", f" {self.status_message} "),
            ("class:status.right", " Cursor Chat Cleaner "),
        ]

    # ------------------------------------------------------------------
    # Key dispatch — agent views and the embedded CLI browser, both
    # layered on top of the base engine
    # ------------------------------------------------------------------

    def _go_back(self):
        if self._in_cli_mode():
            self.cli_browser._go_back()
        elif self.view == VIEW_MESSAGES:
            self.view = self.msg_return_view
        elif self.view == VIEW_AGENT_MEMBERS:
            self.view = VIEW_AGENTS
        elif self.view == VIEW_AGENTS:
            self.view = VIEW_TOP
        else:
            super()._go_back()

    def _handle_up(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_up(event)
        elif self.view == VIEW_AGENTS and self.agent_projects:
            self.agent_cursor = max(0, self.agent_cursor - 1)
            event.app.invalidate()
        elif self.view == VIEW_AGENT_MEMBERS and self.agent_members:
            self.amem_cursor = max(0, self.amem_cursor - 1)
            event.app.invalidate()
        else:
            super()._handle_up(event)

    def _handle_down(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_down(event)
        elif self.view == VIEW_AGENTS and self.agent_projects:
            self.agent_cursor = min(len(self.agent_projects) - 1, self.agent_cursor + 1)
            event.app.invalidate()
        elif self.view == VIEW_AGENT_MEMBERS and self.agent_members:
            self.amem_cursor = min(len(self.agent_members) - 1, self.amem_cursor + 1)
            event.app.invalidate()
        else:
            super()._handle_down(event)

    def _handle_page_up(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_page_up(event)
        else:
            super()._handle_page_up(event)

    def _handle_page_down(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_page_down(event)
        else:
            super()._handle_page_down(event)

    def _handle_enter(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_enter(event)
        elif self.view == VIEW_AGENTS:
            self._enter_agent_members()
            event.app.invalidate()
        elif self.view == VIEW_AGENT_MEMBERS:
            self._enter_agent_member_messages()
            event.app.invalidate()
        else:
            super()._handle_enter(event)

    def _handle_escape(self, event):
        if self._in_cli_mode():
            if self.cli_browser.view == VIEW_TOP:
                self.mode = "main"
                event.app.invalidate()
            else:
                self.cli_browser._handle_escape(event)
        else:
            super()._handle_escape(event)

    def _handle_q(self, event):
        if self._in_cli_mode():
            if self.cli_browser.view == VIEW_TOP:
                self.mode = "main"
                event.app.invalidate()
            else:
                self.cli_browser._handle_q(event)
        else:
            super()._handle_q(event)

    def _handle_d(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_d(event)
            return
        if self.view == VIEW_MESSAGES and self.msg_return_view != VIEW_MID:
            event.app.invalidate()
            return
        if self.view == VIEW_AGENTS:
            self._delete_agent()
            event.app.invalidate()
            return
        super()._handle_d(event)

    def _handle_delete_all(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_delete_all(event)
        else:
            super()._handle_delete_all(event)

    def _handle_space(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_space(event)
        else:
            super()._handle_space(event)

    def _handle_r(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_r(event)
        else:
            super()._handle_r(event)

    def _handle_a(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_a(event)
        else:
            super()._handle_a(event)

    def _handle_y(self, event):
        if self._in_cli_mode():
            self.cli_browser._handle_y(event)
        else:
            super()._handle_y(event)

    def _handle_g(self, event):
        if not self._in_cli_mode() and self.view == VIEW_TOP:
            self._enter_agents()
        event.app.invalidate()

    def _handle_c(self, event):
        if not self._in_cli_mode() and self.view == VIEW_TOP:
            self._enter_cli_mode()
        event.app.invalidate()

    def _setup_keybindings(self):
        keys = super()._setup_keybindings()
        keys["g"] = self._handle_g
        keys["c"] = self._handle_c
        return keys
