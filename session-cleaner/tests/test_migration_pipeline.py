"""Integration test: full migration pipeline end-to-end with temp-file DBs.

Creates two temp-file SQLite databases (source + target) that match the
OpenCode-family schema, populates the source with test sessions, exports
via IR, imports into target, and verifies data integrity.

The import step normally calls an external binary via subprocess; these
tests mock that call and simulate the DB writes inline.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from opencode_family_backend import (
    ToolConfig,
    _clear_cache,
    _get_db,
    scan_projects,
    scan_sessions,
    get_session_messages,
    export_transcript as fb_export,
    import_transcript as fb_import,
    delete_session,
)
from transcript_ir import Transcript


def _mock_import_run(tgt_cfg: ToolConfig, *run_args, **run_kwargs):
    """Simulate what the real import CLI does: read the JSON file and
    write session/message/part rows into the target database."""
    cmd_args = run_args[0]
    json_path = cmd_args[2]
    with open(json_path) as f:
        data = json.load(f)

    info = data["info"]
    conn = _get_db(tgt_cfg)
    sid = info["id"]
    slug = info.get("slug", "")
    directory = info.get("directory", "")
    title = info.get("title", "Imported")
    version = info.get("version", "")
    time_created = info.get("time", {}).get("created", 0)
    time_updated = info.get("time", {}).get("updated", 0)

    conn.execute(
        "INSERT INTO session (id, project_id, directory, title, version, "
        "time_created, time_updated, slug) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, "", directory, title, version, time_created, time_updated, slug),
    )

    for msg in data.get("messages", []):
        msg_info = msg["info"]
        mid = msg_info["id"]
        role = msg_info.get("role", "user")
        msg_time = msg_info.get("time", {})
        msg_created = msg_time.get("created", time_created)
        msg_updated = msg_time.get("completed", msg_created)
        msg_row_data = json.dumps({"role": role, "time": msg_time})

        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (mid, sid, msg_created, msg_updated, msg_row_data),
        )

        for part in msg.get("parts", []):
            pid = part["id"]
            part_created = msg_time.get("created", time_created)
            part_updated = msg_time.get("completed", part_created)
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, "
                "time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, mid, sid, part_created, part_updated, json.dumps(part)),
            )

    conn.commit()
    return subprocess.CompletedProcess(cmd_args, 0, "ok", "")


def _build_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS session;
        DROP TABLE IF EXISTS message;
        DROP TABLE IF EXISTS part;
        DROP TABLE IF EXISTS todo;
        DROP TABLE IF EXISTS session_input;
        DROP TABLE IF EXISTS session_context_epoch;
        DROP TABLE IF EXISTS session_message;
        DROP TABLE IF EXISTS session_share;

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
        CREATE TABLE todo (
            session_id TEXT, content TEXT, status TEXT, position INTEGER,
            time_created INTEGER, time_updated INTEGER,
            PRIMARY KEY (session_id, position)
        );
        CREATE TABLE session_input (session_id TEXT, data TEXT);
        CREATE TABLE session_context_epoch (session_id TEXT, data TEXT);
        CREATE TABLE session_message (session_id TEXT, data TEXT);
        CREATE TABLE session_share (session_id TEXT, data TEXT);
    """)
    conn.commit()


def _populate_source(conn: sqlite3.Connection) -> None:
    now = 1720000000000

    conn.execute(
        "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src_ses_001", "p_abc", "/home/user/project_a", "Test Source Session", "1.0", now, now + 1000, ""),
    )

    msg_data = json.dumps({"role": "user", "time": {"created": now}})
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        ("src_msg_001", "src_ses_001", now, now, msg_data),
    )
    part_data = json.dumps({"type": "text", "text": "Hello! Can you help me with Python?"})
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        ("src_prt_001", "src_msg_001", "src_ses_001", now, now, part_data),
    )

    msg_data2 = json.dumps({"role": "assistant", "time": {"created": now + 100}})
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        ("src_msg_002", "src_ses_001", now + 100, now + 100, msg_data2),
    )
    part_data2 = json.dumps({"type": "reasoning", "text": "The user wants Python help..."})
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        ("src_prt_002", "src_msg_002", "src_ses_001", now + 100, now + 100, part_data2),
    )
    part_data3 = json.dumps({"type": "text", "text": "Sure! I can help with Python. What specifically do you need?"})
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        ("src_prt_003", "src_msg_002", "src_ses_001", now + 150, now + 150, part_data3),
    )

    msg_data3 = json.dumps({"role": "assistant", "time": {"created": now + 200}})
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        ("src_msg_003", "src_ses_001", now + 200, now + 200, msg_data3),
    )
    part_data4 = json.dumps({
        "type": "tool", "tool": "Bash", "callID": "call_001",
        "state": {
            "status": "completed", "input": {"command": "python3 --version"},
            "output": "Python 3.14.0\n", "title": "Bash",
            "metadata": {}, "time": {"start": now + 200, "end": now + 300},
        },
    })
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        ("src_prt_004", "src_msg_003", "src_ses_001", now + 200, now + 200, part_data4),
    )

    conn.commit()


def _check_session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM session WHERE id = ?", (session_id,)).fetchone()
    return row is not None


class TestMigrationPipeline(unittest.TestCase):
    """End-to-end test: source DB → export → IR → import → target DB."""

    @classmethod
    def setUpClass(cls):
        _clear_cache()
        cls._tmpdir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def setUp(self):
        _clear_cache()
        src_path = os.path.join(self._tmpdir.name, "source.db")
        tgt_path = os.path.join(self._tmpdir.name, "target.db")
        open(src_path, "a").close()
        open(tgt_path, "a").close()
        self.src_cfg = ToolConfig(display_name="SourceDB", data_dir="", db_path=src_path, import_binary="")
        self.tgt_cfg = ToolConfig(display_name="TargetDB", data_dir="", db_path=tgt_path, import_binary="")

        src_conn = _get_db(self.src_cfg)
        _build_schema(src_conn)
        _populate_source(src_conn)

        tgt_conn = _get_db(self.tgt_cfg)
        _build_schema(tgt_conn)

    def _do_import(self, transcript, directory):
        """Run import_transcript with subprocess.run patched away."""
        with patch(
            "opencode_family_backend.subprocess.run",
            lambda *a, **kw: _mock_import_run(self.tgt_cfg, *a, **kw),
        ):
            return fb_import(self.tgt_cfg, transcript, directory)

    def test_export_produces_valid_transcript(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        self.assertEqual(transcript.source_tool, "sourcedb")
        self.assertEqual(transcript.title, "Test Source Session")
        self.assertEqual(len(transcript.messages), 5)

        kinds = [m.kind for m in transcript.messages]
        roles = [m.role for m in transcript.messages]
        self.assertEqual(kinds, ["text", "thinking", "text", "tool_call", "tool_result"])
        self.assertEqual(roles, ["user", "assistant", "assistant", "assistant", "assistant"])

    def test_export_preserves_text_content(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        self.assertIn("Hello!", transcript.messages[0].text)
        self.assertIn("Python help", transcript.messages[1].text)
        self.assertIn("Sure!", transcript.messages[2].text)
        self.assertEqual(transcript.messages[3].tool_name, "Bash")
        self.assertIn("Python 3.14", transcript.messages[4].text)

    def test_import_creates_target_session(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        new_id = self._do_import(transcript, "/tmp/test-migration")
        self.assertTrue(new_id.startswith("ses_"))
        self.assertTrue(len(new_id) > 10)

    def test_imported_session_readable(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        new_id = self._do_import(transcript, "/tmp/test-migration")

        sessions = scan_sessions(self.tgt_cfg)
        ids = [s.session_id for s in sessions]
        self.assertIn(new_id, ids)

        for s in sessions:
            if s.session_id == new_id:
                self.assertEqual(s.title, "Test Source Session")
                self.assertEqual(s.directory, "/tmp/test-migration")
                break

    def test_imported_messages_match_source(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        new_id = self._do_import(transcript, "/tmp/test-migration")

        src_msgs = get_session_messages(self.src_cfg, "src_ses_001")
        tgt_msgs = get_session_messages(self.tgt_cfg, new_id)

        # IR flattens multi-part messages → more target messages
        self.assertGreaterEqual(len(tgt_msgs), len(src_msgs))
        # User text is preserved
        self.assertIn("Hello!", tgt_msgs[0]["text"])
        self.assertEqual(tgt_msgs[0]["role"], "USER")

    def test_ir_json_roundtrip(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        json_str = transcript.to_json()
        restored = Transcript.from_json(json_str)
        self.assertEqual(len(restored.messages), len(transcript.messages))
        for orig, rt in zip(transcript.messages, restored.messages):
            self.assertEqual(orig.kind, rt.kind)
            self.assertEqual(orig.text, rt.text)

    def test_migrate_two_sessions(self):
        now = 1720000001000
        conn = _get_db(self.src_cfg)
        conn.execute(
            "INSERT INTO session (id, project_id, directory, title, version, time_created, time_updated, slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("src_ses_002", "p_abc", "/home/user/project_a", "Second Session", "1.0", now, now + 100, ""),
        )
        msg_data = json.dumps({"role": "user", "time": {"created": now}})
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            ("src_msg_004", "src_ses_002", now, now, msg_data),
        )
        part_data = json.dumps({"type": "text", "text": "Another session here"})
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("src_prt_005", "src_msg_004", "src_ses_002", now, now, part_data),
        )
        conn.commit()

        for sid in ("src_ses_001", "src_ses_002"):
            t = fb_export(self.src_cfg, sid)
            self._do_import(t, "/tmp/test-migration")

        tgt_sessions = scan_sessions(self.tgt_cfg)
        self.assertEqual(len(tgt_sessions), 2)
        titles = sorted(s.title for s in tgt_sessions)
        self.assertEqual(titles, ["Second Session", "Test Source Session"])

    def test_imported_session_has_correct_message_count(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        self._do_import(transcript, "/tmp/test-migration")

        sessions = scan_sessions(self.tgt_cfg)
        self.assertEqual(sessions[0].message_count, 4)

    def test_export_nonexistent_session(self):
        with self.assertRaises(ValueError):
            fb_export(self.src_cfg, "nonexistent")

    def test_delete_imported_session(self):
        transcript = fb_export(self.src_cfg, "src_ses_001")
        new_id = self._do_import(transcript, "/tmp/test-migration")

        result = delete_session(self.tgt_cfg, new_id)
        self.assertEqual(result["session"], 1)
        self.assertGreater(result["message"], 0)
        self.assertGreater(result["part"], 0)

        self.assertFalse(_check_session_exists(_get_db(self.tgt_cfg), new_id))


if __name__ == "__main__":
    unittest.main()
