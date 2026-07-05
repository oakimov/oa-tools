"""pi.dev session browser: project list (grouped by session directory) ->
session list -> message viewer, built on the shared browser_tui.ListDrillTUI
engine.
"""

import pi_backend as backend
from browser_tui import ListDrillTUI
from common import format_relative, format_size


class PiCleanerTUI(ListDrillTUI):
    APP_TITLE = "pi.dev Session Cleaner"
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
        dt = backend.parse_ts(s.updated_at)
        ts = format_relative(dt) if dt else ""
        sz = format_size(s.file_size)
        name = s.title.strip() or "(empty)"
        return f"{ts:<10s} {name:<34.34}  {s.message_count:4d} msgs  {sz:>6s}  {s.session_id[:8]}\n"

    def _mid_name(self, s):
        return s.title.strip() or s.session_id[:12]

    def _get_messages(self, s):
        return backend.get_session_messages(s)

    # ---- confirm dialogs ----------------------------------------------

    def _confirm_detail_one(self, s):
        return f"{s.session_id[:20]}…  |  {s.message_count} messages  |  {format_size(s.file_size)}"

    def _confirm_detail_many(self, sessions):
        total_sz = sum(s.file_size for s in sessions)
        names = [self._mid_name(s) for s in sessions]
        return f"{', '.join(names[:5])}{'...' if len(names) > 5 else ''}  |  {format_size(total_sz)}"

    # ---- deletion -------------------------------------------------------

    def _delete_mid_one(self, s):
        r = backend.delete_session(s)
        return f"Deleted: {self._mid_name(s)} ({format_size(r['file'])})"

    def _delete_mid_many(self, sessions):
        r = backend.delete_sessions(sessions)
        return f"Deleted {r['sessions']} sessions ({format_size(r['bytes'])})"

    def _delete_top_many(self, projects):
        all_sessions = [s for p in projects for s in p.sessions]
        return self._delete_mid_many(all_sessions)
