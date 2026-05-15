import os
from typing import Dict, List, Optional, Set, Tuple

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

from archive_helpers import format_size, get_extractor, _member_name, _member_size


def _is_dir(name: str) -> bool:
    return name.endswith("/")


def _hex_dump(data: bytes, limit: int = 4096) -> str:
    lines = []
    for offset in range(0, min(len(data), limit), 16):
        chunk = data[offset:offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_part:<48s}  |{ascii_part}|")
    if len(data) > limit:
        lines.append(f"... ({len(data) - limit} more bytes)")
    return "\n".join(lines)


class ArchiveTUI:
    """7-Zip-like archive browser with extensible commands."""

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
            self.members.append(
                {
                    "full": full,
                    "size": _member_size(m),
                    "is_dir": _is_dir(full),
                }
            )

        # browser state
        self.current_path = ""
        self.cursor_idx = 0
        self.selected: Set[str] = set()

        # tree state
        self.tree_cursor_idx = 0
        self.active_pane = "files"  # files | tree
        self.expanded_dirs: Set[str] = {""}

        # filter / sorting
        self.filter_mode = False
        self.filter_query = ""
        self.sort_key = "name"  # name | size | type
        self.sort_desc = False

        # preview popup
        self.preview_active = False
        self.preview_raw: Optional[bytes] = None
        self.preview_filename = ""
        self.preview_fullpath = ""
        self.preview_scroll = 0
        self.preview_hex_mode = False

        # status
        self.status_message = "Ready"

        # caches
        self._visible_cache = None
        self._visible_cache_key: Optional[Tuple[str, str, str, bool]] = None

        # directory index
        self._dir_children: Dict[str, Set[str]] = {}
        self._build_directory_index()

        # extensible command registry
        self.commands = {
            "quit": self._cmd_quit,
            "up": self._cmd_up,
            "down": self._cmd_down,
            "page_up": self._cmd_page_up,
            "page_down": self._cmd_page_down,
            "enter": self._cmd_enter,
            "go_up": self._cmd_go_up,
            "toggle_select": self._cmd_toggle_select,
            "select_all": self._cmd_select_all,
            "deselect": self._cmd_deselect,
            "extract": self._cmd_extract,
            "toggle_preview_mode": self._cmd_toggle_preview_mode,
            "toggle_pane": self._cmd_toggle_pane,
            "sort_name": self._cmd_sort_name,
            "sort_size": self._cmd_sort_size,
            "sort_type": self._cmd_sort_type,
            "toggle_filter": self._cmd_toggle_filter,
            "clear_filter": self._cmd_clear_filter,
            "close_preview": self._cmd_close_preview,
            "tree_expand_collapse": self._cmd_tree_expand_collapse,
        }

    # ------------------------------------------------------------------
    # Data index / helpers
    # ------------------------------------------------------------------

    def _build_directory_index(self):
        dirs = {""}
        for entry in self.members:
            full = entry["full"]
            parts = full.strip("/").split("/")
            if entry["is_dir"]:
                path = ""
                for part in parts:
                    path += part + "/"
                    dirs.add(path)
            else:
                path = ""
                for part in parts[:-1]:
                    path += part + "/"
                    dirs.add(path)

        children: Dict[str, Set[str]] = {d: set() for d in dirs}
        for d in dirs:
            if not d:
                continue
            parent_parts = d.strip("/").split("/")[:-1]
            parent = ("/".join(parent_parts) + "/") if parent_parts else ""
            children.setdefault(parent, set()).add(d)

        self._dir_children = children

    def _invalidate_visible_cache(self):
        self._visible_cache = None
        self._visible_cache_key = None

    def _set_status(self, text: str):
        self.status_message = text

    def _tree_rows(self) -> List[dict]:
        rows = []

        def walk(path: str, depth: int):
            children = sorted(self._dir_children.get(path, []), key=lambda p: p.lower())
            for child in children:
                has_children = bool(self._dir_children.get(child))
                rows.append(
                    {
                        "path": child,
                        "depth": depth,
                        "has_children": has_children,
                        "expanded": child in self.expanded_dirs,
                        "name": child.strip("/").split("/")[-1],
                    }
                )
                if child in self.expanded_dirs:
                    walk(child, depth + 1)

        rows.append(
            {
                "path": "",
                "depth": 0,
                "has_children": bool(self._dir_children.get("")),
                "expanded": True,
                "name": "/",
            }
        )
        walk("", 1)
        return rows

    def _ensure_tree_cursor_visible(self):
        rows = self._tree_rows()
        target = self.current_path
        for i, row in enumerate(rows):
            if row["path"] == target:
                self.tree_cursor_idx = i
                return
        self.tree_cursor_idx = 0

    def _sort_visible(self, visible: List[dict]) -> List[dict]:
        def key_name(e):
            return e["display"].lower()

        def key_size(e):
            return e["size"]

        def key_type(e):
            ext = os.path.splitext(e["display"].rstrip("/"))[1].lower()
            return (ext, e["display"].lower())

        sort_map = {"name": key_name, "size": key_size, "type": key_type}
        key_fn = sort_map.get(self.sort_key, key_name)

        dirs = [e for e in visible if e["is_dir"]]
        files = [e for e in visible if not e["is_dir"]]
        dirs = sorted(dirs, key=key_fn, reverse=self.sort_desc)
        files = sorted(files, key=key_fn, reverse=self.sort_desc)
        return dirs + files

    def _get_visible(self):
        cache_key = (self.current_path, self.filter_query, self.sort_key, self.sort_desc)
        if self._visible_cache_key == cache_key and self._visible_cache is not None:
            return self._visible_cache

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
            if self.filter_query and self.filter_query.lower() not in display.lower():
                continue

            visible.append(
                {
                    "display": display,
                    "full": full,
                    "size": entry["size"],
                    "is_dir": entry["is_dir"],
                }
            )

        visible = self._sort_visible(visible)
        self._visible_cache = visible
        self._visible_cache_key = cache_key
        return visible

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_toolbar(self):
        return [
            ("class:toolbar", " Extract[x]  "),
            ("class:toolbar", " View[Enter]  "),
            ("class:toolbar", " Select[*]  "),
            ("class:toolbar", " Deselect[d]  "),
            ("class:toolbar", " Up[Backspace]  "),
            ("class:toolbar", " Quit[q]  "),
        ]

    def _render_address(self):
        current = self.current_path.rstrip("/") if self.current_path else "/"
        filter_label = f" | Filter: {self.filter_query}" if self.filter_query else ""
        mode_label = " [Filter mode]" if self.filter_mode else ""
        return [
            ("class:address", f" Archive: {os.path.basename(self.archive_path)} "),
            ("class:address", f"| Path: {current}{filter_label}{mode_label} "),
        ]

    def _render_tree(self):
        rows = self._tree_rows()
        if self.tree_cursor_idx >= len(rows):
            self.tree_cursor_idx = max(0, len(rows) - 1)

        out = [("class:header", " Folders\n")]
        for i, row in enumerate(rows):
            is_cursor = i == self.tree_cursor_idx and self.active_pane == "tree"
            is_current = row["path"] == self.current_path
            indent = "  " * row["depth"]
            if row["has_children"]:
                branch = "[-] " if row["expanded"] or row["path"] == "" else "[+] "
            else:
                branch = "    "
            marker = "▶ " if is_cursor else "  "
            current = "• " if is_current else "  "
            text = f"{marker}{indent}{branch}{current}{row['name']}\n"
            style = "class:tree.current" if is_current else ""
            out.append((style, text))

        return out

    def _render_file_list(self):
        visible = self._get_visible()
        if self.cursor_idx >= len(visible):
            self.cursor_idx = max(0, len(visible) - 1)

        sort_dir = "↓" if self.sort_desc else "↑"
        hdr = f" Name ({self.sort_key} {sort_dir})"
        lines = [("class:header", f" {hdr:<45} {'Size':>12}  Type\n")]
        lines.append(("class:separator", " " + "-" * 75 + "\n"))

        for idx, entry in enumerate(visible):
            is_cursor = idx == self.cursor_idx and self.active_pane == "files"
            is_selected = entry["full"] in self.selected
            icon = "DIR" if entry["is_dir"] else "FILE"
            name = entry["display"].rstrip("/")
            size = "<DIR>" if entry["is_dir"] else format_size(entry["size"])
            line = f" {'>' if is_cursor else ' '} {'[x]' if is_selected else '[ ]'} {name:<40.40} {size:>12}  {icon}\n"
            style = "class:list.cursor" if is_cursor else ""
            lines.append((style, line))

        if not visible:
            lines.append(("", "  (empty)\n"))

        return lines

    def _render_status_bar(self):
        sel = len(self.selected)
        pane = self.active_pane.upper()
        sort_info = f"Sort:{self.sort_key}{' desc' if self.sort_desc else ' asc'}"
        hint = "Tab:Pane  /:Filter  1/2/3:Sort"
        return [
            ("class:status", f" {sel} selected | Pane:{pane} | {sort_info} | {self.status_message} "),
            ("class:status.right", f"{hint} "),
        ]

    def _preview_text(self):
        if self.preview_raw is None:
            return "(no content)"
        if self.preview_hex_mode:
            return _hex_dump(self.preview_raw)
        return self.preview_raw.decode("utf-8", errors="replace")

    def _render_preview_popup(self):
        if not self.preview_active:
            return [("", "")]

        body = self._preview_text()
        lines = body.split("\n")
        total = len(lines)
        self.preview_scroll = max(0, min(self.preview_scroll, max(0, total - 1)))
        page = lines[self.preview_scroll: self.preview_scroll + 120]

        mode = "HEX" if self.preview_hex_mode else "TEXT"
        header = (
            f" {self.preview_filename} | {mode} | "
            f"Lines {self.preview_scroll + 1}-{min(total, self.preview_scroll + len(page))}/{total}"
        )
        footer = " ↑↓/PgUp/PgDn scroll | Tab mode | x extract | Esc close "
        return [("class:preview.header", header + "\n\n"), ("", "\n".join(page)), ("class:preview.footer", "\n\n" + footer)]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_preview(self, entry):
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
        total = len(self._preview_text().split("\n"))
        self.preview_scroll = min(max(0, total - 1), self.preview_scroll + n)

    def _go_up_path(self):
        if not self.current_path:
            return
        parts = self.current_path.strip("/").split("/")
        self.current_path = "" if len(parts) <= 1 else "/".join(parts[:-1]) + "/"
        self.cursor_idx = 0
        self._ensure_tree_cursor_visible()
        self._invalidate_visible_cache()

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _dispatch(self, name: str, event=None):
        cmd = self.commands.get(name)
        if cmd:
            cmd(event)

    def _cmd_quit(self, event):
        if event:
            event.app.exit()

    def _cmd_close_preview(self, event):
        if self.preview_active:
            self._close_preview()

    def _cmd_up(self, event):
        if self.preview_active:
            self._preview_scroll_up(1)
            return
        if self.active_pane == "tree":
            rows = self._tree_rows()
            if rows:
                self.tree_cursor_idx = max(0, self.tree_cursor_idx - 1)
        else:
            visible = self._get_visible()
            if visible:
                self.cursor_idx = max(0, self.cursor_idx - 1)

    def _cmd_down(self, event):
        if self.preview_active:
            self._preview_scroll_down(1)
            return
        if self.active_pane == "tree":
            rows = self._tree_rows()
            if rows:
                self.tree_cursor_idx = min(len(rows) - 1, self.tree_cursor_idx + 1)
        else:
            visible = self._get_visible()
            if visible:
                self.cursor_idx = min(len(visible) - 1, self.cursor_idx + 1)

    def _cmd_page_up(self, event):
        if self.preview_active:
            self._preview_scroll_up(25)

    def _cmd_page_down(self, event):
        if self.preview_active:
            self._preview_scroll_down(25)

    def _cmd_enter(self, event):
        if self.preview_active:
            return

        if self.active_pane == "tree":
            rows = self._tree_rows()
            if not rows:
                return
            row = rows[self.tree_cursor_idx]
            self.current_path = row["path"]
            self.cursor_idx = 0
            self._invalidate_visible_cache()
            self._set_status(f"Opened {self.current_path or '/'}")
            return

        visible = self._get_visible()
        if not visible:
            return

        entry = visible[self.cursor_idx]
        if entry["is_dir"]:
            self.current_path = entry["full"]
            self.cursor_idx = 0
            self._ensure_tree_path_expanded(self.current_path)
            self._ensure_tree_cursor_visible()
            self._invalidate_visible_cache()
            self._set_status(f"Opened {self.current_path}")
        else:
            self._open_preview(entry)
            self._set_status(f"Preview {entry['display']}")

    def _cmd_go_up(self, event):
        if self.preview_active:
            self._close_preview()
            return
        self._go_up_path()

    def _cmd_toggle_select(self, event):
        if self.preview_active or self.active_pane != "files":
            return
        visible = self._get_visible()
        if visible and 0 <= self.cursor_idx < len(visible):
            name = visible[self.cursor_idx]["full"]
            if name in self.selected:
                self.selected.remove(name)
            else:
                self.selected.add(name)

    def _cmd_select_all(self, event):
        if self.preview_active:
            return
        for entry in self._get_visible():
            self.selected.add(entry["full"])

    def _cmd_deselect(self, event):
        if self.preview_active or self.active_pane != "files":
            return
        visible = self._get_visible()
        if visible and 0 <= self.cursor_idx < len(visible):
            self.selected.discard(visible[self.cursor_idx]["full"])

    def _cmd_extract(self, event):
        if not event:
            return
        if self.preview_active:
            if self.preview_fullpath:
                event.app.exit(result=[self.preview_fullpath])
            return
        if self.selected:
            event.app.exit(result=list(self.selected))

    def _cmd_toggle_preview_mode(self, event):
        if self.preview_active:
            self.preview_hex_mode = not self.preview_hex_mode
            self.preview_scroll = 0

    def _cmd_toggle_pane(self, event):
        if self.preview_active:
            return
        self.active_pane = "tree" if self.active_pane == "files" else "files"

    def _set_sort(self, key: str):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = key
            self.sort_desc = False
        self._invalidate_visible_cache()

    def _cmd_sort_name(self, event):
        self._set_sort("name")

    def _cmd_sort_size(self, event):
        self._set_sort("size")

    def _cmd_sort_type(self, event):
        self._set_sort("type")

    def _cmd_toggle_filter(self, event):
        if self.preview_active:
            return
        self.filter_mode = not self.filter_mode
        self._set_status("Filter mode" if self.filter_mode else "Filter mode off")

    def _cmd_clear_filter(self, event):
        if self.preview_active:
            return
        self.filter_query = ""
        self.filter_mode = False
        self._invalidate_visible_cache()

    def _ensure_tree_path_expanded(self, path: str):
        current = ""
        for part in path.strip("/").split("/"):
            if not part:
                continue
            current += part + "/"
            self.expanded_dirs.add(current)

    def _cmd_tree_expand_collapse(self, event):
        if self.preview_active or self.active_pane != "tree":
            return
        rows = self._tree_rows()
        if not rows:
            return
        row = rows[self.tree_cursor_idx]
        path = row["path"]
        if not path:
            return
        if path in self.expanded_dirs:
            self.expanded_dirs.remove(path)
        else:
            self.expanded_dirs.add(path)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        kb = KeyBindings()

        is_browser = Condition(lambda: not self.preview_active)

        @kb.add("q", filter=is_browser)
        def _(event):
            self._dispatch("quit", event)

        @kb.add("escape")
        def _(event):
            if self.preview_active:
                self._dispatch("close_preview", event)
            elif self.filter_mode:
                self.filter_mode = False
            event.app.invalidate()

        @kb.add("backspace")
        def _(event):
            if self.filter_mode and not self.preview_active:
                self.filter_query = self.filter_query[:-1]
                self._invalidate_visible_cache()
            else:
                self._dispatch("go_up", event)
            event.app.invalidate()

        @kb.add("up")
        def _(event):
            self._dispatch("up", event)
            event.app.invalidate()

        @kb.add("down")
        def _(event):
            self._dispatch("down", event)
            event.app.invalidate()

        @kb.add("pageup")
        def _(event):
            self._dispatch("page_up", event)
            event.app.invalidate()

        @kb.add("pagedown")
        def _(event):
            self._dispatch("page_down", event)
            event.app.invalidate()

        @kb.add("enter", filter=is_browser)
        def _(event):
            self._dispatch("enter", event)
            event.app.invalidate()

        @kb.add("space", filter=is_browser)
        def _(event):
            self._dispatch("toggle_select", event)
            event.app.invalidate()

        @kb.add("*")
        def _(event):
            self._dispatch("select_all", event)
            event.app.invalidate()

        @kb.add("d", filter=is_browser)
        def _(event):
            self._dispatch("deselect", event)
            event.app.invalidate()

        @kb.add("x")
        def _(event):
            self._dispatch("extract", event)

        @kb.add("tab")
        def _(event):
            if self.preview_active:
                self._dispatch("toggle_preview_mode", event)
            else:
                self._dispatch("toggle_pane", event)
            event.app.invalidate()

        @kb.add("/")
        def _(event):
            self._dispatch("toggle_filter", event)
            event.app.invalidate()

        @kb.add("c-l")
        def _(event):
            self._dispatch("clear_filter", event)
            event.app.invalidate()

        @kb.add("1")
        def _(event):
            self._dispatch("sort_name", event)
            event.app.invalidate()

        @kb.add("2")
        def _(event):
            self._dispatch("sort_size", event)
            event.app.invalidate()

        @kb.add("3")
        def _(event):
            self._dispatch("sort_type", event)
            event.app.invalidate()

        @kb.add("left")
        def _(event):
            if not self.preview_active and self.active_pane == "tree":
                self._dispatch("tree_expand_collapse", event)
                event.app.invalidate()

        @kb.add("right")
        def _(event):
            if not self.preview_active and self.active_pane == "tree":
                self._dispatch("tree_expand_collapse", event)
                event.app.invalidate()

        @kb.add("<any>")
        def _(event):
            if self.filter_mode and not self.preview_active:
                ch = event.data
                if ch and ch.isprintable() and ch not in ("\r", "\n", "\t"):
                    self.filter_query += ch
                    self._invalidate_visible_cache()
                    event.app.invalidate()

        toolbar = Window(content=FormattedTextControl(self._render_toolbar), height=1)
        address = Window(content=FormattedTextControl(self._render_address), height=1)

        tree_panel = Frame(
            Window(content=FormattedTextControl(self._render_tree), wrap_lines=False),
            title=lambda: " Folder Tree " + ("*" if self.active_pane == "tree" else ""),
        )

        list_panel = Frame(
            Window(content=FormattedTextControl(self._render_file_list), wrap_lines=False),
            title=lambda: " Files " + ("*" if self.active_pane == "files" else ""),
        )

        main = VSplit([tree_panel, list_panel], padding=1, padding_char="│")

        status = Window(content=FormattedTextControl(self._render_status_bar), height=1)

        browser = HSplit([
            toolbar,
            Window(height=1, char="─"),
            address,
            Window(height=1, char="═"),
            main,
            Window(height=1, char="─"),
            status,
        ])

        preview_control = FormattedTextControl(self._render_preview_popup)
        preview_frame = Frame(
            Window(content=preview_control, wrap_lines=False),
            title=lambda: f" Preview: {self.preview_filename} ",
        )

        def _popup_width():
            try:
                cols = get_app().renderer.output.get_size().columns
            except Exception:
                cols = 80
            return max(50, int(cols * 0.92))

        def _popup_height():
            try:
                rows = get_app().renderer.output.get_size().rows
            except Exception:
                rows = 24
            return max(12, int(rows * 0.9))

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
                )
            ],
        )

        style = Style.from_dict(
            {
                "toolbar": "bg:#d6e4ff #1a2a3a",
                "address": "bg:#f1f5ff #102030",
                "header": "bold",
                "separator": "#808080",
                "tree.current": "bold #00afff",
                "list.cursor": "reverse",
                "status": "bg:#204a87 #ffffff",
                "status.right": "bg:#204a87 #d6e4ff",
                "preview.header": "bg:#2e3436 #ffffff",
                "preview.footer": "bg:#2e3436 #d6e4ff",
            }
        )

        app = Application(
            layout=Layout(root),
            key_bindings=kb,
            style=style,
            full_screen=True,
        )

        return app.run()
