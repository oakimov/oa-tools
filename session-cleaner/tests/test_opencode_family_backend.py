"""Tests for opencode_family_backend.py

Uses an in-memory SQLite database that mirrors the OpenCode/KiloCode/MiMoCode
schema to verify scanning, message reading, and export logic without touching
real tool installations.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from opencode_family_backend import (
    ToolConfig,
    resolve_tool_config,
    scan_sessions,
    scan_projects,
    get_session_messages,
    export_transcript,
    _clear_cache,
    _get_db,
    _CHILD_TABLES,
    DEFAULT_PATHS,
)
from transcript_ir import Transcript, TranscriptMessage


def _build_memory_db(cfg: ToolConfig) -> sqlite3.Connection:
    conn = _get_db(cfg)
    conn.executescript("""
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL DEFAULT 'global',
            directory TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            version TEXT NOT NULL DEFAULT '',
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            slug TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL REFERENCES message(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE todo (
            session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            position INTEGER NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            PRIMARY KEY (session_id, position)
        );
        CREATE TABLE session_input (
            session_id TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE session_context_epoch (
            session_id TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE session_message (
            session_id TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE session_share (
            session_id TEXT NOT NULL,
            data TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn


class TestToolConfig(unittest.TestCase):

    def test_resolve_opencode_default(self):
        cfg = resolve_tool_config("OpenCode")
        self.assertEqual(cfg.display_name, "OpenCode")
        self.assertTrue(cfg.db_path.endswith("/opencode.db"))
        self.assertEqual(cfg.import_binary, "opencode")

    def test_resolve_kilo_default(self):
        cfg = resolve_tool_config("KiloCode")
        self.assertEqual(cfg.display_name, "KiloCode")
        self.assertTrue(cfg.db_path.endswith("/kilo.db"))
        self.assertEqual(cfg.import_binary, "kilo")

    def test_resolve_mimo_default(self):
        cfg = resolve_tool_config("MiMoCode")
        self.assertEqual(cfg.display_name, "MiMoCode")
        self.assertTrue(cfg.db_path.endswith("/mimocode.db"))
        self.assertEqual(cfg.import_binary, "mimo")

    def test_kilo_env_override(self):
        with patch.dict(os.environ, {"KILO_DB": "/custom/path/kilo.db"}):
            cfg = resolve_tool_config("KiloCode")
            self.assertEqual(cfg.db_path, "/custom/path/kilo.db")

    def test_mimo_env_override(self):
        with patch.dict(os.environ, {"MIMOCODE_DB": "/custom/path/mimo.db"}):
            cfg = resolve_tool_config("MiMoCode")
            self.assertEqual(cfg.db_path, "/custom/path/mimo.db")

    def test_kilo_env_memory(self):
        with patch.dict(os.environ, {"KILO_DB": ":memory:"}):
            cfg = resolve_tool_config("KiloCode")
            self.assertEqual(cfg.db_path, ":memory:")

    def test_invalid_tool(self):
        with self.assertRaises(ValueError):
            resolve_tool_config("NonExistent")

    def test_all_default_paths_present(self):
        for name in ("OpenCode", "KiloCode", "MiMoCode"):
            self.assertIn(name, DEFAULT_PATHS)
            d = DEFAULT_PATHS[name]
            self.assertIn("data_dir", d)
            self.assertIn("db_filename", d)
            self.assertIn("import_binary", d)


class TestScanning(unittest.TestCase):
    """Tests scan_sessions and scan_projects against an in-memory DB."""

    def setUp(self):
        _clear_cache()
        self.cfg = ToolConfig(display_name="TestDB", data_dir="", db_path=":memory:", import_binary="test")
        self.conn = _build_memory_db(self.cfg)
        self._populate()

    def _populate(self):
        now = 1720000000000
        self.conn.execute(
            "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ses_aaa", "global", "/home/user/proj1", "Session A", "1.0", now, now + 100, ""),
        )
        self.conn.execute(
            "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ses_bbb", "global", "/home/user/proj1", "Session B", "1.0", now + 200, now + 300, ""),
        )
        self.conn.execute(
            "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ses_ccc", "global", "/home/user/proj2", "Session C", "1.0", now + 400, now + 500, ""),
        )
        self.conn.commit()

    def test_scan_sessions_returns_all(self):
        sessions = scan_sessions(self.cfg)
        self.assertEqual(len(sessions), 3)

    def test_scan_sessions_ordered_by_updated_desc(self):
        sessions = scan_sessions(self.cfg)
        timestamps = [s.time_updated for s in sessions]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_scan_projects_groups_by_directory(self):
        projects = scan_projects(self.cfg)
        self.assertEqual(len(projects), 2)
        names = sorted(p.display_name for p in projects)
        self.assertEqual(names, sorted(["/home/user/proj1", "/home/user/proj2"]))

    def test_scan_projects_sorted_by_size(self):
        projects = scan_projects(self.cfg)
        sizes = [p.total_size for p in projects]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_scans_empty_db(self):
        _clear_cache()
        empty_cfg = ToolConfig(display_name="Empty", data_dir="", db_path=":memory:", import_binary="test")
        conn = _get_db(empty_cfg)
        conn.executescript("""
            CREATE TABLE session (
                id TEXT PRIMARY KEY, project_id TEXT, directory TEXT, title TEXT,
                version TEXT, time_created INTEGER, time_updated INTEGER, slug TEXT
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
                time_updated INTEGER, data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                time_created INTEGER, time_updated INTEGER, data TEXT
            );
        """)
        conn.commit()
        sessions = scan_sessions(empty_cfg)
        self.assertEqual(sessions, [])
        projects = scan_projects(empty_cfg)
        self.assertEqual(projects, [])


class TestMessages(unittest.TestCase):
    """Tests get_session_messages and export_transcript."""

    def setUp(self):
        _clear_cache()
        self.cfg = ToolConfig(display_name="TestDB", data_dir="", db_path=":memory:", import_binary="test")
        conn = _build_memory_db(self.cfg)
        now = 1720000000000

        conn.execute(
            "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ses_001", "global", "/home/user/proj", "Test Session", "1.0", now, now + 500, ""),
        )

        msg_data = json.dumps({"role": "user", "time": {"created": now}})
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            ("msg_001", "ses_001", now, now, msg_data),
        )

        part_text = json.dumps({"type": "text", "text": "Hello, what is 2+2?"})
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_001", "msg_001", "ses_001", now, now, part_text),
        )

        msg_data2 = json.dumps({"role": "assistant", "time": {"created": now + 100}})
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            ("msg_002", "ses_001", now + 100, now + 100, msg_data2),
        )

        part_reasoning = json.dumps({"type": "reasoning", "text": "This is simple math"})
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_002", "msg_002", "ses_001", now + 100, now + 100, part_reasoning),
        )

        part_text2 = json.dumps({"type": "text", "text": "2 + 2 = 4"})
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_003", "msg_002", "ses_001", now + 100, now + 100, part_text2),
        )

        msg_data3 = json.dumps({"role": "assistant", "time": {"created": now + 200}})
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            ("msg_003", "ses_001", now + 200, now + 200, msg_data3),
        )

        part_tool = json.dumps({
            "type": "tool",
            "tool": "Bash",
            "callID": "call_001",
            "state": {
                "status": "completed",
                "input": {"command": "echo hello"},
                "output": "hello\n",
                "title": "Bash",
                "metadata": {},
                "time": {"start": now + 200, "end": now + 300},
            },
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_004", "msg_003", "ses_001", now + 200, now + 200, part_tool),
        )

        conn.commit()

    def test_get_session_messages_returns_correct_order(self):
        msgs = get_session_messages(self.cfg, "ses_001")
        self.assertEqual(len(msgs), 3)
        self.assertIn("Hello, what is 2+2?", msgs[0]["text"])
        self.assertIn("2 + 2 = 4", msgs[1]["text"])
        self.assertIn("[tool call]", msgs[2]["text"])

    def test_get_session_messages_empty_session(self):
        msgs = get_session_messages(self.cfg, "nonexistent")
        self.assertEqual(msgs, [])

    def test_export_transcript_produces_valid_ir(self):
        transcript = export_transcript(self.cfg, "ses_001")
        self.assertIsInstance(transcript, Transcript)
        self.assertEqual(transcript.source_tool, "testdb")
        self.assertEqual(transcript.session_id, "ses_001")
        self.assertEqual(transcript.title, "Test Session")
        self.assertEqual(transcript.cwd, "/home/user/proj")

    def test_export_transcript_message_kinds(self):
        transcript = export_transcript(self.cfg, "ses_001")
        kinds = [m.kind for m in transcript.messages]
        self.assertEqual(kinds, ["text", "thinking", "text", "tool_call", "tool_result"])

    def test_export_transcript_unknown_session(self):
        with self.assertRaises(ValueError):
            export_transcript(self.cfg, "nonexistent")

    def test_export_transcript_json_roundtrip(self):
        transcript = export_transcript(self.cfg, "ses_001")
        json_str = transcript.to_json()
        restored = Transcript.from_json(json_str)
        self.assertEqual(restored.session_id, transcript.session_id)
        self.assertEqual(len(restored.messages), len(transcript.messages))
        for orig, rt in zip(transcript.messages, restored.messages):
            self.assertEqual(orig.kind, rt.kind)
            self.assertEqual(orig.role, rt.role)


class TestExportTranscriptEdgeCases(unittest.TestCase):
    """Edge cases: empty parts, no messages, tool-only turns."""

    def setUp(self):
        _clear_cache()
        self.cfg = ToolConfig(display_name="TestDB", data_dir="", db_path=":memory:", import_binary="test")
        self.conn = _build_memory_db(self.cfg)
        now = 1720000000000

        self.conn.execute(
            "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ses_empty", "global", "/tmp/test", "", "1.0", now, now, ""),
        )

    def test_export_empty_session_has_no_messages(self):
        transcript = export_transcript(self.cfg, "ses_empty")
        self.assertEqual(len(transcript.messages), 0)
        self.assertEqual(transcript.title, "ses_empty")

    def test_export_handles_unparseable_message_data(self):
        self.conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            ("msg_bad", "ses_empty", 0, 0, "not json"),
        )
        transcript = export_transcript(self.cfg, "ses_empty")
        self.assertEqual(len(transcript.messages), 0)


if __name__ == "__main__":
    unittest.main()
