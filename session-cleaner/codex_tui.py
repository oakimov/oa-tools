"""Codex CLI session browser: project list (grouped by cwd) -> session list
-> message viewer, built on the shared browser_tui.ListDrillTUI engine.
"""

import codex_backend as backend
from browser_tui import ListDrillTUI
from common import format_relative, format_size


class CodexCleanerTUI(ListDrillTUI):
    APP_TITLE = "Codex Session Cleaner"
    TOP_NOUN = "project"
    TOP_NOUN_PLURAL = "projects"
    MID_NOUN_PLURAL = "sessions"
    NO_TOP_MSG = "(no sessions found)"
    NO_MID_MSG = "(no sessions found)"
    SUPPORTS_RECONCILE = True
    SUPPORTS_TOP_SELECT = True

    # ---- data access ------------------------------------------------

    def _scan_top(self):
        return backend.scan_projects()

    def _top_label(self, top):
        return top.display_name

    def _top_children(self, top):
        return top.sessions

    def _top_size(self, top):
        return top.total_size

    def _mid_row_text(self, s):
        dt = backend.parse_ts(s.updated_at)
        ts = format_relative(dt) if dt else ""
        sz = format_size(s.file_size) if s.file_size else "—"
        prompt_count = f"{s.history_count}p" if s.history_count else "  "
        flags = ""
        if s.orphan_file:
            flags += " [file-only]"
        if s.orphan_index:
            flags += " [index-only]"
        name = s.thread_name.strip() or "(empty)"
        return (f"{ts:<10s} {name:<34.34}  "
                f"{prompt_count:>3s}  {sz:>6s}  {s.session_id[:8]}{flags}\n")

    def _mid_name(self, s):
        return s.thread_name.strip() or s.session_id[:12]

    def _get_messages(self, s):
        return backend.get_session_messages(s)

    def _empty_fields_for_mid(self, s):
        if not s:
            return []
        return [
            ("ID", s.session_id),
            ("Updated", s.updated_at or "(unknown)"),
            ("Created", s.created_at or "(unknown)"),
            ("Prompts", str(s.history_count)),
            ("File size", format_size(s.file_size) if s.file_size else "(none on disk)"),
            ("File path", s.file_path or "(none)"),
            ("Status", "file-only" if s.orphan_file else "index-only" if s.orphan_index else "OK"),
        ]

    # ---- confirm dialogs ----------------------------------------------

    def _confirm_detail_one(self, s):
        return f"{s.session_id[:20]}…  |  {s.history_count} prompts  |  {format_size(s.file_size)}"

    def _confirm_detail_many(self, sessions):
        total_sz = sum(s.file_size for s in sessions)
        names = [self._mid_name(s) for s in sessions]
        return f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''}  |  {format_size(total_sz)}"

    # ---- deletion -------------------------------------------------------

    def _delete_mid_one(self, s):
        r = backend.delete_session(s.session_id)
        return (f"Deleted: {self._mid_name(s)} (index:{r['index']}, "
                f"history:{r['history']}, file:{format_size(r['file'])})")

    def _delete_mid_many(self, sessions):
        r = backend.delete_sessions([s.session_id for s in sessions])
        return (f"Deleted {r['files']} sessions "
                f"(index:{r['index']}, history:{r['history']}, {format_size(r['bytes'])})")

    def _delete_top_many(self, projects):
        all_sessions = [s for p in projects for s in p.sessions]
        return self._delete_mid_many(all_sessions)

    def _reconcile_action(self):
        r = backend.reconcile_sessions()
        return f"{r['file_orphans']} file-only, {r['index_orphans']} index-only sessions"
