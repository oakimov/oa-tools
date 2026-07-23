"""MigrationBackend adapters for all 9 tools.

Each tool gets a class implementing the `MigrationBackend` protocol, wrapping
its specific backend module's functions. A `BACKENDS` registry dict maps
display name → constructor for the TUI to discover and instantiate.
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from transcript_ir import Transcript

# ---------------------------------------------------------------------------
# Abstract protocol
# ---------------------------------------------------------------------------


class MigrationBackend(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def detect(self) -> bool:
        """Whether this tool's storage is accessible."""
        ...

    @abstractmethod
    def scan_projects(self) -> List[Any]:
        """Return list of project-like objects."""
        ...

    @abstractmethod
    def get_messages(self, session_obj) -> List[dict]:
        """Return messages for a session object (one from top_children)."""
        ...

    @abstractmethod
    def export_transcript(self, session_obj) -> Transcript:
        """Export a session to Transcript IR."""
        ...

    @abstractmethod
    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        """Import a transcript, return the new session id."""
        ...

    @abstractmethod
    def session_id(self, session_obj) -> str:
        """Extract the unique session identifier from a session object."""
        ...

    @abstractmethod
    def top_label(self, project) -> str:
        ...

    @abstractmethod
    def top_children(self, project) -> list:
        ...

    @abstractmethod
    def top_size(self, project) -> int:
        ...

    @abstractmethod
    def mid_row_text(self, session_obj) -> str:
        ...

    @abstractmethod
    def mid_name(self, session_obj) -> str:
        ...

    @abstractmethod
    def empty_fields(self, session_obj) -> List[Tuple[str, str]]:
        ...

    @abstractmethod
    def is_exportable(self, session_obj) -> bool:
        """Whether this session can be exported (has local data)."""
        ...


# ---------------------------------------------------------------------------
# OpenCode-family adapters
# ---------------------------------------------------------------------------


class OpencodeFamilyBackend(MigrationBackend):
    def __init__(self, display_name: str):
        from opencode_family_backend import (
            ToolConfig,
            resolve_tool_config,
            scan_projects,
            get_session_messages,
            export_transcript as fb_export,
            import_transcript as fb_import,
        )
        cfg = resolve_tool_config(display_name)
        self._cfg = cfg
        self._scan_fn = lambda: scan_projects(cfg)
        self._msgs_fn = lambda sid: get_session_messages(cfg, sid)
        self._export_fn = lambda sid: fb_export(cfg, sid)
        self._import_fn = lambda t, c: fb_import(cfg, t, c)
        self._fname = display_name

    @property
    def name(self) -> str:
        return self._fname

    def detect(self) -> bool:
        if self._cfg.db_path == ":memory:":
            return True
        return os.path.isfile(self._cfg.db_path)

    def scan_projects(self) -> list:
        return self._scan_fn()

    def get_messages(self, session_obj) -> list:
        return self._msgs_fn(self.session_id(session_obj))

    def export_transcript(self, session_obj) -> Transcript:
        return self._export_fn(self.session_id(session_obj))

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        return self._import_fn(transcript, target_cwd)

    def session_id(self, session_obj) -> str:
        return getattr(session_obj, "session_id", "") or ""

    def top_label(self, project) -> str:
        return project.display_name

    def top_children(self, project) -> list:
        return getattr(project, "sessions", [])

    def top_size(self, project) -> int:
        return project.total_size

    def mid_row_text(self, session_obj) -> str:
        from common import format_relative_ms, format_size
        name = session_obj.title.strip() or "(empty)"
        ts = format_relative_ms(session_obj.time_updated)
        sz = format_size(session_obj.total_size)
        return f"{ts:<10s} {name:<34.34s}  {session_obj.message_count:4d} msgs  {sz:>6s}  {session_obj.session_id[:8]}\n"

    def mid_name(self, session_obj) -> str:
        return session_obj.title.strip() or session_obj.session_id[:12]

    def empty_fields(self, session_obj) -> list:
        from common import format_relative_ms, format_size
        return [
            ("ID", session_obj.session_id),
            ("Directory", session_obj.directory or "(unknown)"),
            ("Updated", format_relative_ms(session_obj.time_updated)),
            ("Created", format_relative_ms(session_obj.time_created)),
            ("Size", format_size(session_obj.total_size)),
        ]

    def is_exportable(self, session_obj) -> bool:
        return True


# ---------------------------------------------------------------------------
# Claude Code adapter
# ---------------------------------------------------------------------------


class _ClaudeBackendBase(MigrationBackend):
    def __init__(self, name: str):
        import claude_backend as cb
        self._cb = cb
        self._fname = name
        self._projects: list = []
        self._current_encoded_dir: Optional[str] = None

    def _ensure_encoded_dir(self, session_obj) -> str:
        """Find the encoded dir for a session. Uses the current project
        context if set, otherwise scans all projects."""
        encoded = getattr(self, "_current_encoded_dir", None)
        if encoded:
            return encoded
        for p in self._projects:
            for c in p.conversations:
                if getattr(c, "session_id", None) == getattr(session_obj, "session_id", None):
                    self._current_encoded_dir = p.encoded_dir
                    return p.encoded_dir
        return ""

    @property
    def name(self) -> str:
        return self._fname

    def top_label(self, project) -> str:
        return project.display_name

    def top_children(self, project) -> list:
        return project.conversations

    def top_size(self, project) -> int:
        return project.total_size

    def mid_row_text(self, session_obj) -> str:
        from common import format_message_timestamp, format_size
        name = session_obj.title.strip() or session_obj.slug.strip() or "(empty)"
        ts = format_message_timestamp(session_obj.timestamp)
        sz = format_size(session_obj.total_size)
        return f"{ts:<20s} {name:<34.34s}  {session_obj.message_count:4d} msgs  {sz:>6s}\n"

    def mid_name(self, session_obj) -> str:
        return session_obj.title.strip() or session_obj.slug.strip() or session_obj.session_id[:12]

    def empty_fields(self, session_obj) -> list:
        from common import format_message_timestamp, format_size
        return [
            ("ID", session_obj.session_id),
            ("Msgs", str(session_obj.message_count)),
            ("Updated", format_message_timestamp(session_obj.timestamp)),
            ("Size", format_size(session_obj.total_size)),
        ]

    def session_id(self, session_obj) -> str:
        return session_obj.session_id

    def set_encoded_dir(self, encoded_dir: str) -> None:
        self._current_encoded_dir = encoded_dir


class ClaudeCodeBackend(_ClaudeBackendBase):
    def __init__(self):
        super().__init__("Claude Code")

    def detect(self) -> bool:
        return os.path.isdir(self._cb.PROJECTS_DIR)

    def scan_projects(self) -> list:
        self._projects = self._cb.scan_all_projects()
        return self._projects

    def get_messages(self, session_obj) -> list:
        ed = self._ensure_encoded_dir(session_obj)
        if not ed:
            return []
        return self._cb.get_conversation_messages(session_obj.session_id, ed)

    def export_transcript(self, session_obj) -> Transcript:
        ed = self._ensure_encoded_dir(session_obj)
        if not ed:
            raise ValueError("No project found for session")
        return self._cb.export_transcript(session_obj.session_id, ed)

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        return self._cb.import_transcript(transcript, target_cwd)

    def is_exportable(self, session_obj) -> bool:
        return not getattr(session_obj, "desktop_only", False)


class ClaudeDesktopBackend(_ClaudeBackendBase):
    def __init__(self):
        super().__init__("Claude Desktop")

    def detect(self) -> bool:
        return os.path.isdir(self._cb.DESKTOP_SESSIONS_DIR)

    def scan_projects(self) -> list:
        self._projects = self._cb.scan_all_projects()
        return self._projects

    def get_messages(self, session_obj) -> list:
        if not self.is_exportable(session_obj):
            return []
        ed = self._ensure_encoded_dir(session_obj)
        if not ed:
            return []
        return self._cb.get_conversation_messages(session_obj.session_id, ed)

    def export_transcript(self, session_obj) -> Transcript:
        if not self.is_exportable(session_obj):
            raise ValueError("Cloud-only Desktop session has no local transcript to export")
        ed = self._ensure_encoded_dir(session_obj)
        if not ed:
            raise ValueError("No project found for session")
        return self._cb.export_transcript(session_obj.session_id, ed)

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        return self._cb.import_transcript(transcript, target_cwd)

    def is_exportable(self, session_obj) -> bool:
        return not getattr(session_obj, "desktop_only", False)


# ---------------------------------------------------------------------------
# Cursor IDE adapter
# ---------------------------------------------------------------------------


class CursorIdeBackend(MigrationBackend):
    def __init__(self):
        import cursor_backend as cur
        self._cur = cur
        self._projects: list = []

    @property
    def name(self) -> str:
        return "Cursor IDE"

    def detect(self) -> bool:
        return os.path.isfile(self._cur.CURSOR_GLOBAL_DB)

    def scan_projects(self) -> list:
        self._projects = self._cur.scan_conversations()
        return self._projects

    def get_messages(self, session_obj) -> list:
        return self._cur.get_bubble_messages(session_obj.composer_id)

    def export_transcript(self, session_obj) -> Transcript:
        return self._cur.export_bubble_transcript(session_obj)

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        raise NotImplementedError("Cursor IDE import not supported — encrypted KV storage")

    def session_id(self, session_obj) -> str:
        return session_obj.composer_id

    def top_label(self, project) -> str:
        return project.display_name or project.encoded_dir

    def top_children(self, project) -> list:
        return project.conversations

    def top_size(self, project) -> int:
        return project.total_size

    def mid_row_text(self, session_obj) -> str:
        from common import format_size
        name = session_obj.title.strip() or "(empty)"
        sz = format_size(session_obj.total_size)
        return f"{name:<50.50s}  {sz:>6s}\n"

    def mid_name(self, session_obj) -> str:
        return session_obj.title.strip() or session_obj.composer_id[:12]

    def empty_fields(self, session_obj) -> list:
        from common import format_size
        return [
            ("ID", session_obj.composer_id),
            ("Size", format_size(session_obj.total_size)),
        ]

    def is_exportable(self, session_obj) -> bool:
        return True


# ---------------------------------------------------------------------------
# Cursor CLI adapter
# ---------------------------------------------------------------------------


class CursorCliBackend(MigrationBackend):
    def __init__(self):
        import cursor_backend as cur
        self._cur = cur
        self._projects: list = []

    @property
    def name(self) -> str:
        return "Cursor CLI"

    def detect(self) -> bool:
        return os.path.isdir(self._cur.CLI_CHATS_DIR)

    def scan_projects(self) -> list:
        self._projects = self._cur.scan_cli_workspaces()
        return self._projects

    def get_messages(self, session_obj) -> list:
        return self._cur.get_cli_chat_messages(session_obj)

    def export_transcript(self, session_obj) -> Transcript:
        return self._cur.export_cli_transcript(session_obj)

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        return self._cur.import_cli_transcript(transcript, target_cwd)

    def session_id(self, session_obj) -> str:
        return session_obj.chat_id

    def top_label(self, project) -> str:
        return project.display_name or project.workspace_hash

    def top_children(self, project) -> list:
        return project.chats

    def top_size(self, project) -> int:
        return project.total_size

    def mid_row_text(self, session_obj) -> str:
        from common import format_size
        name = session_obj.title.strip() or "(empty)"
        sz = format_size(session_obj.total_size)
        return f"{name:<50.50s}  {sz:>6s}\n"

    def mid_name(self, session_obj) -> str:
        return session_obj.title.strip() or session_obj.chat_id[:12]

    def empty_fields(self, session_obj) -> list:
        from common import format_size
        return [
            ("ID", session_obj.chat_id),
            ("Size", format_size(session_obj.total_size)),
        ]

    def is_exportable(self, session_obj) -> bool:
        return True


# ---------------------------------------------------------------------------
# Codex CLI adapter
# ---------------------------------------------------------------------------


class CodexBackend(MigrationBackend):
    def __init__(self):
        import codex_backend as cx
        self._cx = cx
        self._projects: list = []

    @property
    def name(self) -> str:
        return "Codex CLI"

    def detect(self) -> bool:
        return os.path.isdir(self._cx.SESSIONS_DIR)

    def scan_projects(self) -> list:
        self._projects = self._cx.scan_projects()
        return self._projects

    def get_messages(self, session_obj) -> list:
        return self._cx.get_session_messages(session_obj)

    def export_transcript(self, session_obj) -> Transcript:
        return self._cx.export_transcript(session_obj)

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        return self._cx.import_transcript(transcript, target_cwd)

    def session_id(self, session_obj) -> str:
        return session_obj.session_id

    def top_label(self, project) -> str:
        return project.display_name or "(unknown)"

    def top_children(self, project) -> list:
        return project.sessions

    def top_size(self, project) -> int:
        return project.total_size

    def mid_row_text(self, session_obj) -> str:
        from common import format_size
        name = session_obj.title.strip() or "(empty)"
        sz = format_size(session_obj.total_size)
        return f"{name:<50.50s}  {session_obj.message_count:4d} msgs  {sz:>6s}\n"

    def mid_name(self, session_obj) -> str:
        return session_obj.title.strip() or session_obj.session_id[:12]

    def empty_fields(self, session_obj) -> list:
        from common import format_size
        return [
            ("ID", session_obj.session_id),
            ("Msgs", str(session_obj.message_count)),
            ("Size", format_size(session_obj.total_size)),
        ]

    def is_exportable(self, session_obj) -> bool:
        return True


# ---------------------------------------------------------------------------
# pi.dev adapter
# ---------------------------------------------------------------------------


class PiBackend(MigrationBackend):
    def __init__(self):
        import pi_backend as pi
        self._pi = pi
        self._projects: list = []

    @property
    def name(self) -> str:
        return "pi.dev"

    def detect(self) -> bool:
        return os.path.isdir(self._pi.SESSIONS_DIR)

    def scan_projects(self) -> list:
        self._projects = self._pi.scan_projects()
        return self._projects

    def get_messages(self, session_obj) -> list:
        return self._pi.get_session_messages(session_obj)

    def export_transcript(self, session_obj) -> Transcript:
        return self._pi.export_transcript(session_obj)

    def import_transcript(self, transcript: Transcript, target_cwd: str) -> str:
        return self._pi.import_transcript(transcript, target_cwd)

    def session_id(self, session_obj) -> str:
        return session_obj.session_id

    def top_label(self, project) -> str:
        return project.display_name or "(unknown)"

    def top_children(self, project) -> list:
        return project.sessions

    def top_size(self, project) -> int:
        return project.total_size

    def mid_row_text(self, session_obj) -> str:
        from common import format_size
        name = session_obj.title.strip() or "(empty)"
        sz = format_size(session_obj.total_size)
        return f"{name:<50.50s}  {session_obj.message_count:4d} msgs  {sz:>6s}\n"

    def mid_name(self, session_obj) -> str:
        return session_obj.title.strip() or session_obj.session_id[:12]

    def empty_fields(self, session_obj) -> list:
        from common import format_size
        return [
            ("ID", session_obj.session_id),
            ("Msgs", str(session_obj.message_count)),
            ("Size", format_size(session_obj.total_size)),
        ]

    def is_exportable(self, session_obj) -> bool:
        return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BACKENDS: Dict[str, Any] = {
    "Claude Code": lambda: ClaudeCodeBackend(),
    "Claude Desktop": lambda: ClaudeDesktopBackend(),
    "Cursor IDE": lambda: CursorIdeBackend(),
    "Cursor CLI": lambda: CursorCliBackend(),
    "Codex CLI": lambda: CodexBackend(),
    "OpenCode": lambda: OpencodeFamilyBackend("OpenCode"),
    "KiloCode": lambda: OpencodeFamilyBackend("KiloCode"),
    "MiMoCode": lambda: OpencodeFamilyBackend("MiMoCode"),
    "pi.dev": lambda: PiBackend(),
}


def detect_tools() -> List[Tuple[str, bool]]:
    results: List[Tuple[str, bool]] = []
    for name, factory in BACKENDS.items():
        inst = factory()
        results.append((name, inst.detect()))
    return results
