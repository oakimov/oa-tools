"""Generic project -> item -> message browser shared by Codex, OpenCode, and
Cursor's primary chat view. All three tools have the same navigation shape —
a list of projects, each holding a list of sessions/conversations, each
viewable as a message transcript — and differ only in field names, row
formatting, and a couple of optional behaviors (reconcile, archive, top-level
multi-select). Those differences are expressed as class attributes and small
hook methods; everything else (navigation, rendering scaffold, confirm
dialog, key dispatch, app bootstrap) lives here once.

Claude Code's TUI is NOT built on this engine — its dual-pane project/detail
layout with memories/MCP/plans is a genuinely different shape, not a variant
of this one. It still shares `tui_kit.MessageScrollMixin` and `ConfirmMixin`.
"""

from common import format_size
from tui_kit import ConfirmMixin, MessageScrollMixin, bind_keys, run_app

VIEW_TOP = "top"
VIEW_MID = "mid"
VIEW_MESSAGES = "messages"
VIEW_CONFIRM = "confirm"


class ListDrillTUI(ConfirmMixin, MessageScrollMixin):
    """Project list -> item list -> message viewer, with a confirm-before-
    delete dialog. Subclasses configure the class attributes below and
    implement the hook methods; see codex_tui.py / opencode_tui.py for the
    minimal case and cursor_tui.py for one that opts into every extra.
    """

    # ---- display config -------------------------------------------------
    APP_TITLE = "Session Cleaner"
    TOP_NOUN = "project"
    TOP_NOUN_PLURAL = "projects"
    MID_NOUN_PLURAL = "items"
    NO_TOP_MSG = "(no projects found)"
    NO_MID_MSG = "(no items found)"

    # ---- optional behaviors ----------------------------------------------
    SUPPORTS_RECONCILE = False
    SUPPORTS_TOP_SELECT = False
    SUPPORTS_ARCHIVE = False
    DELETE_ALL_KEY = "D"

    def __init__(self):
        self.top_items = []
        self.view = VIEW_TOP

        self.top_cursor = 0
        self.current_top = None
        self.sel_top = set()

        self.mid_cursor = 0
        self.current_mid = None
        self.sel_mid = set()

        self._init_message_view()
        self._init_confirm()
        self.status_message = "Ready"

    # ------------------------------------------------------------------
    # Hooks — data access (subclasses must implement)
    # ------------------------------------------------------------------

    def _scan_top(self):
        """Return the full list of top-level project objects."""
        raise NotImplementedError

    def _top_label(self, top) -> str:
        raise NotImplementedError

    def _top_children(self, top) -> list:
        """All mid-level items (sessions/conversations) under a project."""
        raise NotImplementedError

    def _top_size(self, top) -> int:
        raise NotImplementedError

    def _mid_row_text(self, item) -> str:
        """Full formatted row content for the item list, marker excluded,
        ending in '\\n'."""
        raise NotImplementedError

    def _mid_name(self, item) -> str:
        raise NotImplementedError

    def _get_messages(self, item) -> list:
        raise NotImplementedError

    def _confirm_detail_one(self, item) -> str:
        raise NotImplementedError

    def _confirm_detail_many(self, items) -> str:
        raise NotImplementedError

    def _delete_mid_one(self, item) -> str:
        """Perform the deletion and return a status message."""
        raise NotImplementedError

    def _delete_mid_many(self, items) -> str:
        """Perform a bulk deletion and return a status message."""
        raise NotImplementedError

    # ---- hooks with sensible defaults ------------------------------------

    def _visible_children(self, top) -> list:
        """Mid-items to display for a project — override to filter/sort
        (e.g. Cursor hides empty drafts and sorts newest-first)."""
        return self._top_children(top)

    def _delete_top_one(self, top) -> str:
        """Delete an entire project. Default: delete every child through the
        normal bulk path. Override when the backend has a dedicated
        whole-project delete (e.g. Cursor's workspace directory removal)."""
        return self._delete_mid_many(self._top_children(top))

    def _delete_top_many(self, tops) -> str:
        raise NotImplementedError("SUPPORTS_TOP_SELECT requires _delete_top_many")

    def _reconcile_action(self) -> str:
        raise NotImplementedError("SUPPORTS_RECONCILE requires _reconcile_action")

    def _archive_mid(self, item) -> str:
        raise NotImplementedError("SUPPORTS_ARCHIVE requires _archive_mid")

    def _empty_fields_for_mid(self, item) -> list:
        return []

    def _empty_message_fields(self):
        return self._empty_fields_for_mid(self.current_mid)

    def _mid_header_suffix(self, top, items) -> str:
        """Extra text appended to the mid-list header line (after the item
        count), e.g. Cursor's '(N empty drafts hidden)' note."""
        return ""

    def _mid_header_detail_lines(self, top) -> list:
        """Extra lines rendered under the mid-list header (e.g. Cursor's
        full workspace path)."""
        return []

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_back(self):
        if self.view == VIEW_MESSAGES:
            self.view = VIEW_MID
        elif self.view == VIEW_MID:
            self.view = VIEW_TOP
        elif self.view == VIEW_CONFIRM:
            self.view = self.confirm_return_view

    def _enter_top(self):
        if not self.top_items or self.top_cursor >= len(self.top_items):
            return
        self.current_top = self.top_items[self.top_cursor]
        self.mid_cursor = 0
        self.sel_mid.clear()
        self.view = VIEW_MID

    def _enter_mid(self):
        if not self.current_top:
            return
        items = self._visible_children(self.current_top)
        if not items or self.mid_cursor >= len(items):
            return
        item = items[self.mid_cursor]
        self.current_mid = item
        self.current_messages = self._get_messages(item)
        self.msg_scroll = 0
        self.msg_title = f"{self._mid_name(item)}  ({len(self.current_messages)} messages)"
        self.view = VIEW_MESSAGES

    def _rescan(self):
        self.top_items = self._scan_top()
        self.top_cursor = min(self.top_cursor, max(0, len(self.top_items) - 1)) if self.top_items else 0
        if self.current_top:
            found = [t for t in self.top_items if self._top_label(t) == self._top_label(self.current_top)]
            self.current_top = found[0] if found else None
            self.mid_cursor = 0
            self.sel_mid.clear()

    # ------------------------------------------------------------------
    # Delete flows
    # ------------------------------------------------------------------

    def _set_status(self, text):
        self.status_message = text

    def _confirm_detail_top(self, top) -> str:
        return f"{len(self._top_children(top))} {self.MID_NOUN_PLURAL}, {format_size(self._top_size(top))}"

    def _delete_current_top(self):
        if self.view != VIEW_TOP or not self.top_items:
            return
        top = self.top_items[self.top_cursor]
        self._start_confirm(
            f"Delete {self.TOP_NOUN}: {self._top_label(top)}",
            self._confirm_detail_top(top),
            lambda: (self._set_status(self._delete_top_one(top)), self._rescan()),
            VIEW_TOP,
        )
        self.view = VIEW_CONFIRM

    def _delete_selected_tops(self):
        idxs = sorted(self.sel_top)
        tops = [self.top_items[i] for i in idxs]
        names = [self._top_label(t) for t in tops]
        self._start_confirm(
            f"Delete {len(idxs)} {self.TOP_NOUN_PLURAL}",
            ", ".join(names),
            lambda: (self._set_status(self._delete_top_many(tops)), self.sel_top.clear(), self._rescan()),
            VIEW_TOP,
        )
        self.view = VIEW_CONFIRM

    def _delete_current_mid(self):
        if self.view not in (VIEW_MID, VIEW_MESSAGES) or not self.current_top:
            return
        if self.view == VIEW_MESSAGES:
            item = self.current_mid
        else:
            items = self._visible_children(self.current_top)
            if not items or self.mid_cursor >= len(items):
                return
            item = items[self.mid_cursor]
        if not item:
            return
        self._start_confirm(
            f"Delete: {self._mid_name(item)}",
            self._confirm_detail_one(item),
            lambda: (self._set_status(self._delete_mid_one(item)), self._rescan()),
            self.view,
        )
        self.view = VIEW_CONFIRM

    def _delete_selected_mid(self):
        idxs = sorted(self.sel_mid)
        items = [self._visible_children(self.current_top)[i] for i in idxs]
        self._start_confirm(
            f"Delete {len(idxs)} {self.MID_NOUN_PLURAL}",
            self._confirm_detail_many(items),
            lambda: (self._set_status(self._delete_mid_many(items)), self.sel_mid.clear(), self._rescan()),
            VIEW_MID,
        )
        self.view = VIEW_CONFIRM

    def _delete_all_in_top(self):
        """Delete every child item in the current project via the normal
        bulk item-delete path — distinct from `_delete_top_one`, which may
        perform a more thorough whole-project removal (e.g. Cursor also
        drops the workspace storage directory). "Delete all sessions" and
        "delete the project" are the same effect for tools with no dedicated
        project-level delete, but not for ones that have one."""
        if not self.current_top or not self._top_children(self.current_top):
            return
        top = self.current_top
        children = self._top_children(top)
        self._start_confirm(
            f"Delete ALL ({len(children)}) {self.MID_NOUN_PLURAL}",
            f"In: {self._top_label(top)} — {format_size(self._top_size(top))}",
            lambda: (self._set_status(self._delete_mid_many(children)), self._rescan()),
            VIEW_TOP,
        )
        self.view = VIEW_CONFIRM

    def _toggle_mid_selection(self):
        if self.view == VIEW_MID and self.current_top:
            n = len(self._visible_children(self.current_top))
            if n and self.mid_cursor < n:
                self.sel_mid.symmetric_difference_update({self.mid_cursor})

    def _toggle_top_selection(self):
        if self.view == VIEW_TOP and self.top_items:
            self.sel_top.symmetric_difference_update({self.top_cursor})

    def _do_reconcile(self):
        self._set_status(self._reconcile_action())
        self._rescan()

    def _do_archive_current(self):
        if self.view != VIEW_MID or not self.current_top:
            return
        items = self._visible_children(self.current_top)
        if not items or self.mid_cursor >= len(items):
            return
        self._set_status(self._archive_mid(items[self.mid_cursor]))
        self._rescan()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_top(self):
        lines = [("class:header", f" {self.APP_TITLE}\n")]
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        for i, top in enumerate(self.top_items):
            cursor = i == self.top_cursor
            selected = i in self.sel_top
            n = len(self._top_children(top))
            sz = format_size(self._top_size(top))
            sel_char = "✓" if selected else " "
            marker = f"▸{sel_char}" if cursor else f" {sel_char}"
            style = "class:cursor" if cursor else ("class:selected" if selected else "")
            line = f" {marker} {self._top_label(top):<47.47}  {n:3d} {self.MID_NOUN_PLURAL}  {sz:>6s}\n"
            lines.append((style, line))

        if not self.top_items:
            lines.append(("", f"  {self.NO_TOP_MSG}\n"))

        total = sum(len(self._top_children(t)) for t in self.top_items)
        total_sz = sum(self._top_size(t) for t in self.top_items)
        lines.append(("class:footer",
                       f"\n  {len(self.top_items)} {self.TOP_NOUN_PLURAL}, {total} total "
                       f"{self.MID_NOUN_PLURAL}, {format_size(total_sz)}\n"))
        return lines

    def _render_mid(self):
        top = self.current_top
        if not top:
            return [("", "")]
        items = self._visible_children(top)
        suffix = self._mid_header_suffix(top, items)
        header = f" {self._top_label(top)}  —  {len(items)} {self.MID_NOUN_PLURAL}{suffix}\n"
        lines = [("class:header", header)]
        lines.extend(self._mid_header_detail_lines(top))
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        for i, item in enumerate(items):
            cursor = i == self.mid_cursor
            selected = i in self.sel_mid
            sel_char = "✓" if selected else " "
            marker = f"▸{sel_char}" if cursor else f" {sel_char}"
            style = "class:cursor" if cursor else ("class:selected" if selected else "")
            lines.append((style, f" {marker} {self._mid_row_text(item)}"))

        if not items:
            lines.append(("", f"  {self.NO_MID_MSG}\n"))

        lines.append(("class:footer", f"\n  {len(items)} {self.MID_NOUN_PLURAL}\n"))
        return lines

    def _render_main(self):
        if self.view == VIEW_TOP:
            return self._render_top()
        elif self.view == VIEW_MID:
            return self._render_mid()
        elif self.view == VIEW_MESSAGES:
            return self._render_messages()
        elif self.view == VIEW_CONFIRM:
            return self._render_confirm("Confirm")
        return [("", "")]

    def _render_toolbar(self):
        if self.view == VIEW_TOP:
            items = []
            if self.SUPPORTS_TOP_SELECT:
                items.append(("class:toolbar", " Space:Select  "))
            items += [
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", f" d:Delete {self.TOP_NOUN}  "),
            ]
            if self.SUPPORTS_RECONCILE:
                items.append(("class:toolbar", " r:Reconcile  "))
            items += [("class:toolbar", " q:Quit  "), ("class:toolbar", " ↑↓:Navigate  ")]
            if self.SUPPORTS_TOP_SELECT and self.sel_top:
                items.append(("class:toolbar.count", f" {len(self.sel_top)} selected  "))
            return items
        elif self.view == VIEW_MID:
            items = [
                ("class:toolbar", " Space:Select  "),
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " d:Delete  "),
            ]
            if self.SUPPORTS_ARCHIVE:
                items.append(("class:toolbar", " a:Archive  "))
            items += [
                ("class:toolbar", f" {self.DELETE_ALL_KEY}:Delete all  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " ↑↓:Navigate  "),
            ]
            if self.sel_mid:
                items.append(("class:toolbar.count", f" {len(self.sel_mid)} selected  "))
            return items
        elif self.view == VIEW_MESSAGES:
            items = [("class:toolbar", " ↑↓:Scroll  "), ("class:toolbar", " d:Delete  ")]
            if self.SUPPORTS_ARCHIVE:
                items.append(("class:toolbar", " a:Archive  "))
            items.append(("class:toolbar", " Esc:Back  "))
            return items
        elif self.view == VIEW_CONFIRM:
            return [
                ("class:toolbar.warn", " y:Confirm  "),
                ("class:toolbar", " Esc/q:Cancel  "),
            ]
        return []

    def _render_status_bar(self):
        return [
            ("class:status", f" {self.status_message} "),
            ("class:status.right", f" {self.APP_TITLE} "),
        ]

    # ------------------------------------------------------------------
    # Key dispatch
    # ------------------------------------------------------------------

    def _handle_up(self, event):
        if self.view == VIEW_TOP and self.top_items:
            self.top_cursor = max(0, self.top_cursor - 1)
        elif self.view == VIEW_MID and self.current_top:
            n = len(self._visible_children(self.current_top))
            self.mid_cursor = max(0, self.mid_cursor - 1) if n else 0
        elif self.view == VIEW_MESSAGES:
            self._handle_msg_up()
        event.app.invalidate()

    def _handle_down(self, event):
        if self.view == VIEW_TOP and self.top_items:
            self.top_cursor = min(len(self.top_items) - 1, self.top_cursor + 1)
        elif self.view == VIEW_MID and self.current_top:
            n = len(self._visible_children(self.current_top))
            if n:
                self.mid_cursor = min(n - 1, self.mid_cursor + 1)
        elif self.view == VIEW_MESSAGES:
            self._handle_msg_down()
        event.app.invalidate()

    def _handle_page_up(self, event):
        if self.view == VIEW_MESSAGES:
            self._handle_msg_page_up()
        event.app.invalidate()

    def _handle_page_down(self, event):
        if self.view == VIEW_MESSAGES:
            self._handle_msg_page_down()
        event.app.invalidate()

    def _handle_enter(self, event):
        if self.view == VIEW_TOP:
            self._enter_top()
        elif self.view == VIEW_MID:
            self._enter_mid()
        event.app.invalidate()

    def _handle_escape(self, event):
        if self.view != VIEW_TOP:
            self._go_back()
        event.app.invalidate()

    def _handle_q(self, event):
        if self.view == VIEW_TOP:
            event.app.exit()
        else:
            self._go_back()

    def _handle_d(self, event):
        if self.view == VIEW_TOP:
            if self.SUPPORTS_TOP_SELECT and self.sel_top:
                self._delete_selected_tops()
            else:
                self._delete_current_top()
        elif self.view == VIEW_MID:
            if self.sel_mid:
                self._delete_selected_mid()
            else:
                self._delete_current_mid()
        elif self.view == VIEW_MESSAGES:
            self._delete_current_mid()
        event.app.invalidate()

    def _handle_delete_all(self, event):
        if self.view == VIEW_MID:
            self._delete_all_in_top()
        event.app.invalidate()

    def _handle_space(self, event):
        if self.view == VIEW_TOP:
            self._toggle_top_selection()
        elif self.view == VIEW_MID:
            self._toggle_mid_selection()
        event.app.invalidate()

    def _handle_r(self, event):
        if self.SUPPORTS_RECONCILE and self.view == VIEW_TOP:
            self._do_reconcile()
        event.app.invalidate()

    def _handle_a(self, event):
        if self.SUPPORTS_ARCHIVE and self.view == VIEW_MID:
            self._do_archive_current()
        event.app.invalidate()

    def _handle_y(self, event):
        if self.view == VIEW_CONFIRM and self.confirm_action:
            self._run_confirm()
            self._go_back()
        event.app.invalidate()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _setup_keybindings(self):
        keys = {
            "up": self._handle_up,
            "down": self._handle_down,
            "pageup": self._handle_page_up,
            "pagedown": self._handle_page_down,
            "enter": self._handle_enter,
            "escape": self._handle_escape,
            "q": self._handle_q,
            "space": self._handle_space,
            "d": self._handle_d,
            self.DELETE_ALL_KEY: self._handle_delete_all,
            "y": self._handle_y,
            "backspace": self._handle_escape,
        }
        if self.SUPPORTS_RECONCILE:
            keys["r"] = self._handle_r
        if self.SUPPORTS_ARCHIVE:
            keys["a"] = self._handle_a
        return keys

    def _no_data_message(self):
        """Return a message to print (instead of launching the TUI) when
        there's nothing to show at all. Default: never — show the TUI with
        its own "no data" empty state."""
        return None

    def run(self):
        self.top_items = self._scan_top()
        if not self.top_items:
            msg = self._no_data_message()
            if msg:
                print(msg)
                return
        kb = bind_keys(self._setup_keybindings())
        run_app(self._render_toolbar, self._render_main, self._render_status_bar, kb)
