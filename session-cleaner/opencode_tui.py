"""OpenCode session browser: project list (grouped by directory) -> session
list -> message viewer, built on the shared browser_tui.ListDrillTUI engine.
"""

import opencode_backend as backend
from browser_tui import ListDrillTUI
from common import format_relative_ms, format_size


class OpencodeCleanerTUI(ListDrillTUI):
    APP_TITLE = "OpenCode Session Cleaner"
    TOP_NOUN = "project"
    TOP_NOUN_PLURAL = "projects"
    MID_NOUN_PLURAL = "sessions"
    NO_TOP_MSG = "(no sessions found)"
    NO_MID_MSG = "(no sessions found)"
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
        name = s.title.strip() or "(empty)"
        ts = format_relative_ms(s.time_updated)
        sz = format_size(s.total_size)
        return f"{ts:<10s} {name:<34.34}  {s.message_count:4d} msgs  {sz:>6s}  {s.session_id[:8]}\n"

    def _mid_name(self, s):
        return s.title.strip() or s.session_id[:12]

    def _get_messages(self, s):
        return backend.get_session_messages(s.session_id)

    def _empty_fields_for_mid(self, s):
        if not s:
            return []
        return [
            ("ID", s.session_id),
            ("Directory", s.directory or "(unknown)"),
            ("Updated", format_relative_ms(s.time_updated)),
            ("Created", format_relative_ms(s.time_created)),
            ("Size", format_size(s.total_size)),
        ]

    # ---- confirm dialogs ----------------------------------------------

    def _confirm_detail_one(self, s):
        return f"{s.session_id[:20]}…  |  {s.message_count} messages  |  {format_size(s.total_size)}"

    def _confirm_detail_many(self, sessions):
        total_sz = sum(s.total_size for s in sessions)
        names = [self._mid_name(s) for s in sessions]
        return f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''}  |  {format_size(total_sz)}"

    # ---- deletion -------------------------------------------------------

    def _delete_mid_one(self, s):
        r = backend.delete_session(s.session_id)
        return (f"Deleted: {self._mid_name(s)} (messages:{r['message']}, parts:{r['part']}, "
                f"diff:{format_size(r['diff_file'])})")

    def _delete_mid_many(self, sessions):
        r = backend.delete_sessions([s.session_id for s in sessions])
        return (f"Deleted {r['sessions']} sessions "
                f"(messages:{r['messages']}, parts:{r['parts']}, {format_size(r['bytes'])})")

    def _delete_top_many(self, projects):
        all_sessions = [s for p in projects for s in p.sessions]
        return self._delete_mid_many(all_sessions)
