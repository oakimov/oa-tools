"""Shared prompt_toolkit scaffolding used by every cleaner TUI (Claude, Cursor,
Codex). Centralizes the style sheet, app bootstrapping, key-binding wiring, and
the confirm-before-delete dialog so each backend's TUI only implements its own
views and data access.
"""

import sys

from common import format_message_timestamp

try:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.styles import Style
    HAS_TUI = True
except ImportError:
    HAS_TUI = False

# Canonical look shared by every cleaner TUI — a superset of all three tools'
# style needs (project/plan/MCP colors from Claude, selection color from
# Cursor/Codex).
STYLE = Style.from_dict({
    "toolbar": "bg:#d6e4ff #1a2a3a",
    "toolbar.warn": "bg:#ff4444 #ffffff bold",
    "toolbar.count": "bg:#d6e4ff #cc6600 bold",
    "cursor": "reverse",
    "selected": "bold #ffff00",
    "mcp": "#ffcc00",
    "cloud": "#00aaff italic",
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
}) if HAS_TUI else None


def require_tui() -> None:
    if not HAS_TUI:
        print("Error: prompt_toolkit is required for TUI mode.", file=sys.stderr)
        print("Install with: pip install prompt_toolkit", file=sys.stderr)
        raise SystemExit(1)


def bind_keys(handlers: dict) -> "KeyBindings":
    """Build a KeyBindings object from a {key_name: handler(event)} mapping."""
    kb = KeyBindings()
    for key, handler in handlers.items():
        kb.add(key)(lambda event, _h=handler: _h(event))
    return kb


def run_app(toolbar_fn, main_fn, status_fn, keybindings) -> None:
    """Run a simple single-pane TUI: toolbar / main / status, each full width.
    Used by tools whose views don't need a split-pane layout (Cursor, Codex).
    """
    require_tui()
    root = HSplit([
        Window(content=FormattedTextControl(toolbar_fn), height=1),
        Window(height=1, char="─"),
        Window(content=FormattedTextControl(main_fn), wrap_lines=False),
        Window(height=1, char="─"),
        Window(content=FormattedTextControl(status_fn), height=1),
    ])
    run_custom(root, keybindings)


def run_custom(root, keybindings) -> None:
    """Run a TUI with a caller-built root container (used when a tool needs a
    custom split-pane layout, e.g. Claude's project/detail sidebars)."""
    require_tui()
    app = Application(layout=Layout(root), key_bindings=keybindings, style=STYLE, full_screen=True)
    app.run()


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


class ConfirmMixin:
    """Generic confirm-before-delete dialog state and rendering. The host TUI
    is responsible for its own view stack: it switches into/out of its confirm
    view and calls `_run_confirm()` on 'y'.
    """

    def _init_confirm(self):
        self.confirm_target = ""
        self.confirm_detail = ""
        self.confirm_action = None
        self.confirm_return_view = None

    def _start_confirm(self, target: str, detail: str, action, return_view=None) -> None:
        self.confirm_target = target
        self.confirm_detail = detail
        self.confirm_action = action
        self.confirm_return_view = return_view

    def _render_confirm(self, title="Confirm"):
        return [
            ("class:header", f" {title}\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
            ("", "\n"),
            ("class:warn", f"  {self.confirm_target}\n"),
            ("", "\n"),
            ("class:detail", f"  {self.confirm_detail}\n"),
            ("", "\n"),
            ("", "  Press [y] to confirm, [Esc] or [q] to cancel.\n"),
        ]

    def _run_confirm(self) -> None:
        if self.confirm_action:
            self.confirm_action()
        self.confirm_action = None


class MessageScrollMixin:
    """Generic scrollable message-transcript view, shared by every cleaner's
    message viewer (Claude, Cursor, Codex, OpenCode). The host is responsible
    for populating `self.current_messages` (a list of {"role", "text",
    "timestamp"} dicts, oldest-or-newest first per the host's own convention)
    and `self.msg_title` before switching into the message view; this mixin
    owns `self.msg_scroll` and the rendering/navigation around it.
    """

    def _init_message_view(self):
        self.current_messages = []
        self.msg_scroll = 0
        self.msg_title = ""

    def _empty_message_fields(self):
        """Optional (label, value) pairs shown in place of a transcript when
        a session has no text messages (e.g. metadata for an orphaned or
        import-only session). Override to opt in; default shows nothing extra."""
        return []

    def _render_messages(self):
        lines = [
            ("class:header", f" {self.msg_title}\n"),
            ("class:separator", " " + "─" * 80 + "\n"),
        ]

        msgs = self.current_messages
        total = len(msgs)
        if total == 0:
            fields = self._empty_message_fields()
            if fields:
                lines.append(("", "  (no messages — session metadata below)\n\n"))
                for label, val in fields:
                    lines.append(("", f"  {label:<12s}  {val}\n"))
            else:
                lines.append(("", "  (no messages)\n"))
            return lines

        self.msg_scroll = clamp(self.msg_scroll, 0, max(0, total - 1))
        page = msgs[self.msg_scroll:self.msg_scroll + 200]

        for msg in page:
            role = msg.get("role", "?")
            ts = format_message_timestamp(msg.get("timestamp"))
            text = msg.get("text") or "(no text content)"
            if len(text) > 2000:
                text = text[:2000] + "\n... (truncated)"
            lines.append(("class:role", f" [{role}] {ts}\n"))
            for text_line in text.split("\n"):
                # prompt_toolkit renders raw control chars (e.g. tabs from
                # tool-result file contents) as "^I" instead of expanding them —
                # it does its own column-precise layout rather than delegating
                # to the terminal's tab stops.
                lines.append(("", f"  {text_line.expandtabs(4)}\n"))
            lines.append(("", "\n"))

        if total > 1:
            pct = int(self.msg_scroll / max(1, total) * 100)
            lines.append(("class:footer", f"  Message {self.msg_scroll + 1}/{total} ({pct}%)\n"))

        return lines

    def _handle_msg_up(self):
        if self.current_messages:
            self.msg_scroll = max(0, self.msg_scroll - 1)

    def _handle_msg_down(self):
        if self.current_messages:
            self.msg_scroll = min(len(self.current_messages) - 1, self.msg_scroll + 1)

    def _handle_msg_page_up(self):
        self.msg_scroll = max(0, self.msg_scroll - 25)

    def _handle_msg_page_down(self):
        if self.current_messages:
            self.msg_scroll = min(len(self.current_messages) - 1, self.msg_scroll + 25)
