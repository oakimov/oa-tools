import os
from typing import Set, Optional

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application.current import get_app
from prompt_toolkit.widgets import Frame
from prompt_toolkit.layout.containers import (
    HSplit, Window, Float, FloatContainer, ConditionalContainer,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.filters import Condition

from archive_helpers import (
    get_extractor,
    _member_name,
    _member_size,
    format_size,
)


def _is_dir(name: str) -> bool:
    return name.endswith("/")


def _hex_dump(data: bytes, limit: int = 2048) -> str:
    """Produce a hex dump string from raw bytes."""
    lines = []
    for offset in range(0, min(len(data), limit), 16):
        chunk = data[offset:offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {offset:08x}  {hex_part:<48s}  |{ascii_part}|")
    if len(data) > limit:
        lines.append(f"  ... ({len(data) - limit} more bytes)")
    return "\n".join(lines)


class ArchiveTUI:
    def __init__(self, archive_path, extract_path=None, overwrite=False, password=None):
        self.archive_path = archive_path
        self.extract_path = extract_path
        self.overwrite = overwrite
        self.password = password

        self.extractor = get_extractor(archive_path, extract_path, overwrite)
        self.all_members = self.extractor.get_members()

        self.members = []
        for m in self.all_members:
            full = _member_name(m)
            self.members.append({
                "full": full,
                "size": _member_size(m),
                "is_dir": _is_dir(full),
            })

        # Browser state
        self.current_path = ""
        self.cursor_idx = 0
        self.selected: Set[str] = set()

        # Preview popup state
        self.preview_active = False
        self.preview_raw: Optional[bytes] = None
        self.preview_filename = ""
        self.preview_fullpath = ""
        self.preview_scroll = 0
        self.preview_hex_mode = False

        # Cache
        self._filtered_cache = None
        self._filtered_path = None

    # ------------------------------------------------------------------
    # Directory content
    # ------------------------------------------------------------------

    def _get_visible(self):
        if self._filtered_path == self.current_path and self._filtered_cache is not None:
            return self._filtered_cache

        visible = []
        prefix = self.current_path

        for entry in self.members:
            full = entry["full"]
            if full == prefix:
                continue
            if prefix:
                if not full.startswith(prefix):
                    continue
                rest = full[len(prefix):].rstrip("/")
                if "/" in rest:
                    continue
            else:
                rest = full.rstrip("/")
                if "/" in rest:
                    continue

            display = full[len(prefix):] if prefix else full
            visible.append({
                "display": display,
                "full": full,
                "size": entry["size"],
                "is_dir": entry["is_dir"],
            })

        visible.sort(key=lambda e: (not e["is_dir"], e["display"].lower()))
        self._filtered_cache = visible
        self._filtered_path = self.current_path
        return visible

    def _invalidate_cache(self):
        self._filtered_cache = None
        self._filtered_path = None

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def _render_list(self):
        visible = self._get_visible()
        lines = []

        path_display = self.current_path.rstrip("/") if self.current_path else "/"
        sel_count = len(self.selected)
        status = f"  📂 {path_display}  ({len(visible)} items)"
        if sel_count:
            status += f"  [{sel_count} selected]"
        lines.append(("", status + "\n"))

        for idx, entry in enumerate(visible):
            is_cursor = idx == self.cursor_idx
            is_selected = entry["full"] in self.selected

            sel_marker = "[X]" if is_selected else "[ ]"
            type_icon = "📁 " if entry["is_dir"] else "📄 "
            display = entry["display"].rstrip("/")
            size_str = format_size(entry["size"]) if not entry["is_dir"] else "<dir>"
            cursor_marker = " > " if is_cursor else "   "

            line = f"{cursor_marker}{sel_marker} {type_icon}{display}  {size_str}"
            lines.append(("", line + "\n"))

        if not visible:
            lines.append(("", "  (empty directory)\n"))

        lines.append(("", "\n"))
        lines.append(("", "  ↑↓ Navigate │ Enter: Open/Preview │ Space: Select │ *: Select All │ d: Deselect │ x: Extract │ Backspace: Up │ q: Quit"))
        return lines

    def _render_preview_popup(self):
        """Render the preview popup content, respecting scroll offset."""
        if not self.preview_active:
            return [("")]

        mode_label = "HEX" if self.preview_hex_mode else "TEXT"

        if self.preview_raw is None:
            body = "  (no content)"
        elif self.preview_hex_mode:
            body = _hex_dump(self.preview_raw)
        else:
            body = self.preview_raw.decode("utf-8", errors="replace")

        # Split into lines and apply scroll
        all_lines = body.split("\n")
        total = len(all_lines)
        max_scroll = max(0, total - 1)
        if self.preview_scroll > max_scroll:
            self.preview_scroll = max_scroll

        # Take a window of lines from the scroll position
        visible_lines = all_lines[self.preview_scroll:]

        header = (
            f"  {self.preview_filename}  │  {mode_label} mode  │  "
            f"Lines {self.preview_scroll + 1}-{min(total, self.preview_scroll + 100)}/{total}"
        )
        footer = "  ↑↓/PgUp/PgDn: Scroll │ Tab: Text/Hex │ x: Extract │ Esc/Backspace: Close"

        text = header + "\n\n" + "\n".join(visible_lines) + "\n\n" + footer
        return [("", text)]

    # ------------------------------------------------------------------
    # Preview open / close
    # ------------------------------------------------------------------

    def _open_preview(self, entry):
        """Open the preview popup for a file entry."""
        member_obj = None
        for m in self.all_members:
            if _member_name(m) == entry["full"]:
                member_obj = m
                break
        if member_obj is None:
            return

        try:
            content = self.extractor.get_member_content(member_obj, self.password)
        except Exception as e:
            content = f"Error reading file: {e}".encode()

        self.preview_raw = content
        self.preview_filename = entry["display"].rstrip("/")
        self.preview_fullpath = entry["full"]
        self.preview_scroll = 0
        self.preview_hex_mode = False
        self.preview_active = True

    def _close_preview(self):
        self.preview_active = False
        self.preview_raw = None
        self.preview_scroll = 0

    def _preview_scroll_up(self, n=1):
        self.preview_scroll = max(0, self.preview_scroll - n)

    def _preview_scroll_down(self, n=1):
        if self.preview_raw is None:
            return
        total = len(
            (_hex_dump(self.preview_raw) if self.preview_hex_mode
             else self.preview_raw.decode("utf-8", errors="replace")).split("\n")
        )
        self.preview_scroll = min(total - 1, self.preview_scroll + n)

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        kb = KeyBindings()

        is_preview = Condition(lambda: self.preview_active)
        is_browser = Condition(lambda: not self.preview_active)

        # ---- Shared bindings (dispatch based on mode) ----

        @kb.add("escape")
        def _escape(event):
            if self.preview_active:
                self._close_preview()
                event.app.invalidate()

        @kb.add("backspace")
        def _backspace(event):
            if self.preview_active:
                self._close_preview()
                event.app.invalidate()
            elif self.current_path:
                parts = self.current_path.strip("/").split("/")
                if len(parts) <= 1:
                    self.current_path = ""
                else:
                    self.current_path = "/".join(parts[:-1]) + "/"
                self.cursor_idx = 0
                self._invalidate_cache()
                event.app.invalidate()

        @kb.add("up")
        def _up(event):
            if self.preview_active:
                self._preview_scroll_up(1)
            else:
                visible = self._get_visible()
                if visible:
                    self.cursor_idx = max(0, self.cursor_idx - 1)
            event.app.invalidate()

        @kb.add("down")
        def _down(event):
            if self.preview_active:
                self._preview_scroll_down(1)
            else:
                visible = self._get_visible()
                if visible:
                    self.cursor_idx = min(len(visible) - 1, self.cursor_idx + 1)
            event.app.invalidate()

        @kb.add("pageup")
        def _pgup(event):
            if self.preview_active:
                self._preview_scroll_up(20)
                event.app.invalidate()

        @kb.add("pagedown")
        def _pgdn(event):
            if self.preview_active:
                self._preview_scroll_down(20)
                event.app.invalidate()

        @kb.add("x")
        def _extract(event):
            if self.preview_active:
                if self.preview_fullpath:
                    event.app.exit(result=[self.preview_fullpath])
            else:
                if self.selected:
                    event.app.exit(result=list(self.selected))

        # ---- Preview-only bindings ----

        @kb.add("tab")
        def _toggle_hex(event):
            if self.preview_active:
                self.preview_hex_mode = not self.preview_hex_mode
                self.preview_scroll = 0
                event.app.invalidate()

        # ---- Browser-only bindings ----

        @kb.add("q", filter=is_browser)
        def _quit(event):
            event.app.exit()

        @kb.add("space", filter=is_browser)
        def _toggle_select(event):
            visible = self._get_visible()
            if visible and 0 <= self.cursor_idx < len(visible):
                name = visible[self.cursor_idx]["full"]
                if name in self.selected:
                    self.selected.remove(name)
                else:
                    self.selected.add(name)
            event.app.invalidate()

        @kb.add("*", filter=is_browser)
        def _select_all(event):
            for entry in self._get_visible():
                self.selected.add(entry["full"])
            event.app.invalidate()

        @kb.add("d", filter=is_browser)
        def _deselect(event):
            visible = self._get_visible()
            if visible and 0 <= self.cursor_idx < len(visible):
                self.selected.discard(visible[self.cursor_idx]["full"])
            event.app.invalidate()

        @kb.add("enter", filter=is_browser)
        def _enter(event):
            visible = self._get_visible()
            if not visible:
                return
            entry = visible[self.cursor_idx]
            if entry["is_dir"]:
                self.current_path = entry["full"]
                self.cursor_idx = 0
                self._invalidate_cache()
            else:
                self._open_preview(entry)
            event.app.invalidate()

        # ---- Layout ----

        list_control = FormattedTextControl(self._render_list)

        browser = HSplit([
            Window(
                content=FormattedTextControl(
                    lambda: f"  Archive: {os.path.basename(self.archive_path)}"
                ),
                height=1,
            ),
            Window(height=1, char="─"),
            Window(content=list_control),
        ])

        # Preview popup (float, centered)
        preview_control = FormattedTextControl(self._render_preview_popup)
        preview_frame = Frame(
            Window(content=preview_control),
            title=lambda: f" Preview: {self.preview_filename} ",
        )

        def _popup_width():
            try:
                cols = get_app().renderer.output.get_size().columns
            except Exception:
                cols = 80
            return max(40, int(cols * 0.9))

        def _popup_height():
            try:
                rows = get_app().renderer.output.get_size().rows
            except Exception:
                rows = 24
            return max(10, int(rows * 0.9))

        root = FloatContainer(
            content=browser,
            floats=[
                Float(
                    content=ConditionalContainer(
                        content=preview_frame,
                        filter=Condition(lambda: self.preview_active),
                    ),
                    width=_popup_width,
                    height=_popup_height,
                ),
            ],
        )

        app = Application(
            layout=Layout(root),
            key_bindings=kb,
            full_screen=True,
        )

        return app.run()
