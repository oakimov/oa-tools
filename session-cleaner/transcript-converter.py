#!/usr/bin/env python3
"""Cross-tool session migration TUI.

Select a source tool and a target tool from the dropdowns at the top,
browse the source tool's projects and sessions, then press Ctrl+M to
migrate selected sessions into the target tool.
"""

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from tui_kit import (
    ConfirmMixin,
    MessageScrollMixin,
    STYLE,
    bind_keys,
    clamp,
    HAS_TUI,
    require_tui,
    run_custom,
)

from convert_backends import BACKENDS, MigrationBackend
from transcript_ir import Transcript, TranscriptMessage

# ---------------------------------------------------------------------------
# View states
# ---------------------------------------------------------------------------

V_TOOLBAR = "toolbar"     # focusing on source/target selector
V_TOP = "top"             # project list
V_MID = "mid"             # session list
V_MSGS = "messages"       # message viewer
V_CONFIRM = "confirm"     # confirm dialog
V_DROPDOWN = "dropdown"   # tool selection overlay

# ---------------------------------------------------------------------------
# Migration state
# ---------------------------------------------------------------------------

M_IDLE = "idle"
M_RUNNING = "running"
M_DONE = "done"

# ---------------------------------------------------------------------------
# Converter TUI
# ---------------------------------------------------------------------------


class ConverterTUI(ConfirmMixin, MessageScrollMixin):
    APP_TITLE = "Session Converter"

    def __init__(self):
        require_tui()

        # Tool backends
        self._source_name: str = "OpenCode"
        self._target_name: str = "Claude Code"
        self._source: Optional[MigrationBackend] = None
        self._target: Optional[MigrationBackend] = None
        self._toolbar_focus: int = 0  # 0=source, 1=target

        # Dropdown state
        self._dropdown_open: bool = False
        self._dropdown_type: int = 0  # 0=source, 1=target
        self._dropdown_cursor: int = 0
        self._dropdown_tools: List[str] = []
        self._dropdown_available: Dict[str, bool] = {}

        # Navigation state
        self._view: str = V_TOP

        # Project/session tree
        self._projects: list = []
        self._top_cursor: int = 0
        self._sel_top: set = set()
        self._current_project: Any = None

        self._mid_cursor: int = 0
        self._sel_mid: set = set()
        self._current_session: Any = None

        # Migration state
        self._migrate_state: str = M_IDLE
        self._migrate_total: int = 0
        self._migrate_done: int = 0
        self._migrate_ok: int = 0
        self._migrate_fail: int = 0
        self._migrate_errors: List[str] = []

        # Message viewer
        self._init_message_view()
        self._init_confirm()
        self._empty_fields_for_session: list = []

        self._status_msg: str = "Ready"
        self._init_backends()

    def _init_backends(self) -> None:
        from convert_backends import BACKENDS, detect_tools
        self._tool_factories = BACKENDS
        self._tool_available = dict(detect_tools())
        self._tool_names = list(BACKENDS.keys())

        # Find first available tools as defaults
        avail = [n for n, a in self._tool_available.items() if a]
        if len(avail) >= 2:
            self._source_name = avail[0]
            self._target_name = avail[1]
        elif len(avail) == 1:
            self._source_name = avail[0]
            # target stays as default
        self._rebuild_backends()

    def _rebuild_backends(self) -> None:
        self._source = self._tool_factories[self._source_name]()
        self._target = self._tool_factories[self._target_name]()
        self._rescan()

    def _rescan(self) -> None:
        if self._source:
            try:
                self._projects = self._source.scan_projects()
            except Exception as e:
                self._projects = []
                self._status_msg = f"Scan failed: {e}"
        else:
            self._projects = []
        self._top_cursor = min(self._top_cursor, max(0, len(self._projects) - 1)) if self._projects else 0
        self._current_project = None
        self._current_session = None
        self._sel_top.clear()
        self._sel_mid.clear()
        self._view = V_TOP

    # ------------------------------------------------------------------
    # Dropdown helpers
    # ------------------------------------------------------------------

    def _open_dropdown(self, dtype: int) -> None:
        self._dropdown_type = dtype
        self._dropdown_cursor = 0
        self._dropdown_tools = [n for n in self._tool_names if n != self._other_tool_name(dtype)]
        self._dropdown_available = {n: self._tool_available.get(n, False) for n in self._dropdown_tools}
        self._dropdown_open = True
        self._view = V_DROPDOWN

    def _other_tool_name(self, dtype: int) -> str:
        return self._target_name if dtype == 0 else self._source_name

    def _select_dropdown(self) -> None:
        if self._dropdown_cursor < len(self._dropdown_tools):
            name = self._dropdown_tools[self._dropdown_cursor]
            avail = self._dropdown_available.get(name, False)
            if not avail and name not in ("OpenCode", "KiloCode", "MiMoCode"):
                self._status_msg = f"{name} storage not found — skipping"
                return
            if self._dropdown_type == 0:
                self._source_name = name
            else:
                self._target_name = name
            self._rebuild_backends()
            self._status_msg = f"Source: {self._source_name}  →  Target: {self._target_name}"
        self._close_dropdown()

    def _close_dropdown(self) -> None:
        self._dropdown_open = False
        self._view = V_TOP

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _visible_children(self) -> list:
        if not self._current_project or not self._source:
            return []
        try:
            return self._source.top_children(self._current_project)
        except Exception:
            return []

    def _toggle_mid(self) -> None:
        if self._view == V_MID and self._current_project:
            items = self._visible_children()
            if items and self._mid_cursor < len(items):
                self._sel_mid.symmetric_difference_update({self._mid_cursor})

    def _toggle_top(self) -> None:
        if self._view == V_TOP:
            self._sel_top.symmetric_difference_update({self._top_cursor})

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_back(self) -> None:
        if self._view == V_MSGS:
            self._view = V_MID
        elif self._view == V_MID:
            self._view = V_TOP
            self._current_project = None
            self._sel_mid.clear()
        elif self._view == V_CONFIRM:
            self._view = self.confirm_return_view

    def _enter_top(self) -> None:
        if not self._projects or self._top_cursor >= len(self._projects):
            return
        self._current_project = self._projects[self._top_cursor]
        self._mid_cursor = 0
        self._sel_mid.clear()
        # Pass encoded_dir to Claude backends
        if hasattr(self._source, "set_encoded_dir") and hasattr(self._current_project, "encoded_dir"):
            self._source.set_encoded_dir(self._current_project.encoded_dir)
        self._view = V_MID

    def _enter_mid(self) -> None:
        if not self._current_project or not self._source:
            return
        items = self._visible_children()
        if not items or self._mid_cursor >= len(items):
            return
        session = items[self._mid_cursor]
        self._current_session = session
        msgs = self._source.get_messages(session)
        self.current_messages = msgs
        self.msg_scroll = 0
        title = self._source.mid_name(session)
        self.msg_title = f"{title}  ({len(msgs)} messages)"
        self._empty_fields_for_session = self._source.empty_fields(session)
        self._view = V_MSGS

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _collect_sessions(self) -> List[Any]:
        """Collect session objects to migrate based on current selection state."""
        sessions: List[Any] = []
        if self._view == V_TOP:
            idxs = sorted(self._sel_top)
            for i in idxs:
                if i < len(self._projects):
                    proj = self._projects[i]
                    sessions.extend(self._source.top_children(proj))
            if not idxs and self._projects:
                proj = self._projects[self._top_cursor]
                sessions = self._source.top_children(proj)
        elif self._view == V_MID:
            idxs = sorted(self._sel_mid)
            items = self._visible_children()
            for i in idxs:
                if i < len(items):
                    sessions.append(items[i])
            if not idxs and items:
                sessions.append(items[self._mid_cursor])
        elif self._view == V_MSGS and self._current_session:
            sessions = [self._current_session]
        return [s for s in sessions if self._source.is_exportable(s)]

    def _run_migration(self) -> None:
        if not self._source or not self._target:
            self._status_msg = "Source or target not configured"
            return
        if self._source_name == self._target_name:
            self._status_msg = "Source and target must be different tools"
            return

        sessions = self._collect_sessions()
        if not sessions:
            self._status_msg = "No exportable sessions selected"
            return

        self._migrate_state = M_RUNNING
        self._migrate_total = len(sessions)
        self._migrate_done = 0
        self._migrate_ok = 0
        self._migrate_fail = 0
        self._migrate_errors = []

        # We cannot yield control during migration in this simple sync TUI,
        # so we run the full batch and update state after.
        import tempfile
        target_cwd = os.getcwd()

        for session in sessions:
            name = self._source.mid_name(session)
            self._migrate_done += 1
            self._status_msg = f"Migrating {self._migrate_done}/{self._migrate_total}: {name[:40]}..."
            try:
                transcript = self._source.export_transcript(session)
                transcript.source_tool = self._source_name
                self._target.import_transcript(transcript, target_cwd)
                self._migrate_ok += 1
            except Exception as e:
                self._migrate_fail += 1
                err_msg = f"{name}: {e}"
                self._migrate_errors.append(err_msg)

        self._migrate_state = M_DONE
        parts = [f"{self._migrate_ok}/{self._migrate_total} migrated"]
        if self._migrate_fail:
            parts.append(f"{self._migrate_fail} failed")
            for e in self._migrate_errors[:3]:
                parts[-1] += f"; {e}"
        self._status_msg = "Done: " + ", ".join(parts)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_toolbar(self):
        from prompt_toolkit.formatted_text import FormattedText

        source_avail = self._tool_available.get(self._source_name, False)
        target_avail = self._tool_available.get(self._target_name, False)

        s_focus = "class:cursor" if self._view == V_TOOLBAR and self._toolbar_focus == 0 else ""
        t_focus = "class:cursor" if self._view == V_TOOLBAR and self._toolbar_focus == 1 else ""

        s_indicator = "✓" if source_avail else "✗"
        t_indicator = "✓" if target_avail else "✗"

        return [
            ("class:toolbar", f" Source: "),
            (s_focus or "", f"[{s_indicator} {self._source_name} ▼]"),
            ("class:toolbar", "  →  "),
            (t_focus or "", f"[{t_indicator} {self._target_name} ▼]"),
            ("class:toolbar", "  "),
        ]

    def _render_main(self):
        if self._view == V_TOP:
            return self._render_top()
        elif self._view == V_MID:
            return self._render_mid()
        elif self._view == V_MSGS:
            return self._render_messages()
        elif self._view == V_CONFIRM:
            return self._render_confirm("Confirm")
        elif self._view == V_DROPDOWN:
            return self._render_dropdown()
        return [("", "")]

    def _render_top(self):
        lines = [("class:header", f" {self.APP_TITLE}  —  {self._source_name}\n")]
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        for i, proj in enumerate(self._projects):
            cursor = i == self._top_cursor
            selected = i in self._sel_top
            sel_char = "✓" if selected else " "
            marker = f"▸{sel_char}" if cursor else f" {sel_char}"
            style = "class:cursor" if cursor else ("class:selected" if selected else "")
            label = self._source.top_label(proj) if self._source else ""
            n = len(self._source.top_children(proj)) if self._source else 0
            sz = self._source.top_size(proj) if self._source else 0
            from common import format_size
            line = f" {marker} {label:<47.47s}  {n:3d} sessions  {format_size(sz):>6s}\n"
            lines.append((style, line))

        if not self._projects:
            lines.append(("", "  (no projects found for selected source tool)\n"))

        from common import format_size
        total = sum(len(self._source.top_children(p)) for p in self._projects) if self._source else 0
        total_sz = sum(self._source.top_size(p) for p in self._projects)
        lines.append(("class:footer",
                       f"\n  {len(self._projects)} projects, {total} total sessions, {format_size(total_sz)}\n"))
        return lines

    def _render_mid(self):
        if not self._current_project or not self._source:
            return [("", "")]
        items = self._visible_children()
        label = self._source.top_label(self._current_project)
        header = f" {label}  —  {len(items)} sessions\n"
        lines = [("class:header", header)]
        lines.append(("class:separator", " " + "─" * 80 + "\n"))

        for i, session in enumerate(items):
            cursor = i == self._mid_cursor
            selected = i in self._sel_mid
            sel_char = "✓" if selected else " "
            marker = f"▸{sel_char}" if cursor else f" {sel_char}"
            style = "class:cursor" if cursor else ("class:selected" if selected else "")
            exportable = self._source.is_exportable(session)
            text = self._source.mid_row_text(session)
            if not exportable:
                text = f"(cloud session — no local transcript)  {session.session_id[:8]}\n"
            lines.append((style, f" {marker} {text}"))

        if not items:
            lines.append(("", "  (no sessions)\n"))

        lines.append(("class:footer", f"\n  {len(items)} sessions\n"))
        return lines

    def _render_messages(self):
        msgs = self.current_messages
        if not msgs and self._empty_fields_for_session:
            lines = [
                ("class:header", f" {self.msg_title}\n"),
                ("class:separator", " " + "─" * 80 + "\n"),
                ("", "  (no messages — metadata below)\n\n"),
            ]
            for label, val in self._empty_fields_for_session:
                lines.append(("", f"  {label:<12s}  {val}\n"))
            return lines
        return self._render_message_list()

    def _render_message_list(self):
        lines = [
            ("class:header", f" {self.msg_title}\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
        ]
        msgs = self.current_messages
        total = len(msgs)
        if total == 0:
            lines.append(("", "  (no messages)\n"))
            return lines

        self.msg_scroll = clamp(self.msg_scroll, 0, max(0, total - 1))
        page = msgs[self.msg_scroll:self.msg_scroll + 200]

        for msg in page:
            from common import format_message_timestamp
            role = msg.get("role", "?")
            ts = format_message_timestamp(msg.get("timestamp"))
            text = msg.get("text") or "(no text)"
            if len(text) > 2000:
                text = text[:2000] + "\n... (truncated)"
            lines.append(("class:role", f" [{role}] {ts}\n"))
            for text_line in text.split("\n"):
                lines.append(("", f"  {text_line.expandtabs(4)}\n"))
            lines.append(("", "\n"))

        if total > 1:
            pct = int(self.msg_scroll / max(1, total) * 100)
            lines.append(("class:footer", f"  Message {self.msg_scroll + 1}/{total} ({pct}%)\n"))
        return lines

    def _render_dropdown(self):
        title = "Select source tool" if self._dropdown_type == 0 else "Select target tool"
        lines = [("class:header", f" {title}\n")]
        lines.append(("class:separator", " " + "─" * 40 + "\n"))
        for i, name in enumerate(self._dropdown_tools):
            cursor = i == self._dropdown_cursor
            avail = self._dropdown_available.get(name, False)
            marker = "▸" if cursor else " "
            style = "class:cursor" if cursor else ""
            avail_tag = " ✓" if avail else " ✗"
            lines.append((style, f" {marker} {name:<20s}{avail_tag}\n"))
        lines.append(("class:footer", "\n  Enter:select  Esc:cancel\n"))
        return lines

    def _render_status_bar(self):
        mig = ""
        if self._migrate_state == M_RUNNING:
            mig = f" Migrating {self._migrate_done}/{self._migrate_total}... "
        elif self._migrate_state == M_DONE:
            mig = f" Done: {self._migrate_ok}/{self._migrate_total} ok, {self._migrate_fail} failed "

        left = f" {self._status_msg}{mig}"
        right = f" {self._source_name} → {self._target_name} "
        return [
            ("class:status", left),
            ("class:status.right", right),
        ]

    def _build_toolbar_items(self):
        """Status-bar keybinding hints based on current view."""
        if self._view == V_TOOLBAR:
            return [
                ("class:toolbar", " ←→:Switch field  "),
                ("class:toolbar", " Enter:Open dropdown  "),
                ("class:toolbar", " ↓:Projects  "),
                ("class:toolbar", " q:Quit  "),
            ]
        elif self._view == V_TOP:
            items = [
                ("class:toolbar", " Space:Select  "),
                ("class:toolbar", " Enter:Open  "),
                ("class:toolbar", " ↑:Toolbar  "),
                ("class:toolbar", " q:Quit  "),
            ]
            if self._sel_top:
                items.append(("class:toolbar.count", f" {len(self._sel_top)} projects  "))
            items.append(("class:toolbar", " Ctrl+M:Migrate  "))
            return items
        elif self._view == V_MID:
            items = [
                ("class:toolbar", " Space:Select  "),
                ("class:toolbar", " Enter:View  "),
                ("class:toolbar", " Esc:Back  "),
            ]
            if self._sel_mid:
                items.append(("class:toolbar.count", f" {len(self._sel_mid)} sessions  "))
            items.append(("class:toolbar", " Ctrl+M:Migrate  "))
            return items
        elif self._view == V_MSGS:
            return [
                ("class:toolbar", " ↑↓:Scroll  "),
                ("class:toolbar", " Esc:Back  "),
                ("class:toolbar", " Ctrl+M:Migrate  "),
            ]
        elif self._view == V_DROPDOWN:
            return [
                ("class:toolbar", " ↑↓:Navigate  "),
                ("class:toolbar", " Enter:Select  "),
                ("class:toolbar", " Esc:Cancel  "),
            ]
        elif self._view == V_CONFIRM:
            return [
                ("class:toolbar.warn", " y:Confirm  "),
                ("class:toolbar", " Esc/q:Cancel  "),
            ]
        return []

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl

        toolbar_ctrl = FormattedTextControl(self._render_toolbar)
        main_ctrl = FormattedTextControl(self._render_main)
        status_ctrl = FormattedTextControl(self._render_status_bar)

        root = HSplit([
            Window(content=toolbar_ctrl, height=1, dont_extend_height=True),
            Window(height=1, char="─", dont_extend_height=True),
            Window(content=main_ctrl, wrap_lines=False),
            Window(height=1, char="─", dont_extend_height=True),
            Window(content=status_ctrl, height=1, dont_extend_height=True),
        ])

        return root

    # ------------------------------------------------------------------
    # Key dispatch
    # ------------------------------------------------------------------

    def _handle_up(self, event):
        if self._view == V_DROPDOWN:
            self._dropdown_cursor = max(0, self._dropdown_cursor - 1)
        elif self._view == V_TOP and self._projects:
            self._top_cursor = max(0, self._top_cursor - 1)
        elif self._view == V_MID and self._current_project:
            n = len(self._visible_children())
            self._mid_cursor = max(0, self._mid_cursor - 1) if n else 0
        elif self._view == V_MSGS:
            self._handle_msg_up()
        elif self._view == V_TOOLBAR:
            self._view = V_TOP
        event.app.invalidate()

    def _handle_down(self, event):
        if self._view == V_DROPDOWN:
            self._dropdown_cursor = min(len(self._dropdown_tools) - 1, self._dropdown_cursor + 1)
        elif self._view == V_TOP and self._projects:
            self._top_cursor = min(len(self._projects) - 1, self._top_cursor + 1)
        elif self._view == V_MID and self._current_project:
            n = len(self._visible_children())
            if n:
                self._mid_cursor = min(n - 1, self._mid_cursor + 1)
        elif self._view == V_MSGS:
            self._handle_msg_down()
        elif self._view == V_TOOLBAR:
            self._view = V_TOP
        event.app.invalidate()

    def _handle_left(self, event):
        if self._view == V_TOOLBAR:
            self._toolbar_focus = 0
        elif self._view == V_TOP:
            self._view = V_TOOLBAR
            self._toolbar_focus = 0
        event.app.invalidate()

    def _handle_right(self, event):
        if self._view == V_TOOLBAR:
            self._toolbar_focus = 1
        elif self._view == V_TOP:
            self._view = V_TOOLBAR
            self._toolbar_focus = 1
        event.app.invalidate()

    def _handle_page_up(self, event):
        if self._view == V_MSGS:
            self._handle_msg_page_up()
        event.app.invalidate()

    def _handle_page_down(self, event):
        if self._view == V_MSGS:
            self._handle_msg_page_down()
        event.app.invalidate()

    def _handle_enter(self, event):
        if self._view == V_TOOLBAR:
            self._open_dropdown(self._toolbar_focus)
        elif self._view == V_DROPDOWN:
            self._select_dropdown()
        elif self._view == V_TOP:
            self._enter_top()
        elif self._view == V_MID:
            self._enter_mid()
        event.app.invalidate()

    def _handle_escape(self, event):
        if self._view == V_DROPDOWN:
            self._close_dropdown()
        elif self._view == V_CONFIRM:
            self.confirm_action = None
            self._go_back()
        elif self._view != V_TOP:
            self._go_back()
        else:
            self._view = V_TOOLBAR
        event.app.invalidate()

    def _handle_q(self, event):
        if self._view == V_DROPDOWN:
            self._close_dropdown()
        elif self._view == V_TOP:
            event.app.exit()
        elif self._view == V_TOOLBAR:
            event.app.exit()
        else:
            self._go_back()
        event.app.invalidate()

    def _handle_space(self, event):
        if self._view == V_TOP:
            self._toggle_top()
        elif self._view == V_MID:
            self._toggle_mid()
        event.app.invalidate()

    def _handle_tab(self, event):
        if self._view == V_TOOLBAR:
            self._toolbar_focus = 1 - self._toolbar_focus
        event.app.invalidate()

    def _handle_ctrl_m(self, event):
        if self._view not in (V_DROPDOWN, V_CONFIRM):
            self._run_migration()
        event.app.invalidate()

    def _handle_y(self, event):
        if self._view == V_CONFIRM and self.confirm_action:
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
            "left": self._handle_left,
            "right": self._handle_right,
            "pageup": self._handle_page_up,
            "pagedown": self._handle_page_down,
            "enter": self._handle_enter,
            "escape": self._handle_escape,
            "q": self._handle_q,
            "space": self._handle_space,
            "tab": self._handle_tab,
            "backspace": self._handle_escape,
            "c-m": self._handle_ctrl_m,
            "y": self._handle_y,
        }
        return keys

    def run(self):
        kb = bind_keys(self._setup_keybindings())
        root = self._build_layout()
        run_custom(root, kb)


def main():
    if not HAS_TUI:
        print("Error: prompt_toolkit is required.", file=sys.stderr)
        print("Install: pip install prompt_toolkit", file=sys.stderr)
        sys.exit(1)
    ConverterTUI().run()


if __name__ == "__main__":
    main()
