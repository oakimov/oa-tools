"""Tests for convert_backends.py — registry, detection, metadata."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import codex_backend
import cursor_backend
import pi_backend
from codex_backend import CodexSession
from cursor_backend import CliChat
from pi_backend import PiSession
from transcript_ir import Transcript, TranscriptMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from convert_backends import (
    BACKENDS,
    detect_tools,
    OpencodeFamilyBackend,
    ClaudeCodeBackend,
    ClaudeDesktopBackend,
    CursorIdeBackend,
    CursorCliBackend,
    CodexBackend,
    PiBackend,
)


class TestBackendRegistry(unittest.TestCase):
    def test_all_tools_present(self):
        expected = {
            "Claude Code",
            "Claude Desktop",
            "Cursor IDE",
            "Cursor CLI",
            "Codex CLI",
            "OpenCode",
            "KiloCode",
            "MiMoCode",
            "pi.dev",
        }
        self.assertEqual(set(BACKENDS.keys()), expected)

    def test_detect_returns_all_nine(self):
        results = detect_tools()
        self.assertEqual(len(results), 9)
        names = [r[0] for r in results]
        self.assertIn("OpenCode", names)
        self.assertIn("KiloCode", names)
        self.assertIn("MiMoCode", names)

    def test_each_factory_returns_instance(self):
        for name, factory in BACKENDS.items():
            inst = factory()
            self.assertEqual(inst.name, name)


class TestOcodeFamilyBackendMetadata(unittest.TestCase):
    def test_opencode_defaults(self):
        b = OpencodeFamilyBackend("OpenCode")
        self.assertEqual(b.name, "OpenCode")
        self.assertEqual(b.session_id(None), "")  # session_id handles None obj

    def test_kilo_defaults(self):
        b = OpencodeFamilyBackend("KiloCode")
        self.assertEqual(b.name, "KiloCode")

    def test_mimo_defaults(self):
        b = OpencodeFamilyBackend("MiMoCode")
        self.assertEqual(b.name, "MiMoCode")

    def test_session_id_missing_attr(self):
        b = OpencodeFamilyBackend("OpenCode")
        class Fake:
            session_id = ""
        self.assertEqual(b.session_id(Fake()), "")

    def test_top_children_missing_sessions_attr(self):
        b = OpencodeFamilyBackend("OpenCode")
        class Fake:
            pass
        self.assertEqual(b.top_children(Fake()), [])


class TestBackendNames(unittest.TestCase):
    def test_claude_code_name(self):
        b = ClaudeCodeBackend()
        self.assertEqual(b.name, "Claude Code")

    def test_claude_desktop_name(self):
        b = ClaudeDesktopBackend()
        self.assertEqual(b.name, "Claude Desktop")

    def test_cursor_ide_name(self):
        b = CursorIdeBackend()
        self.assertEqual(b.name, "Cursor IDE")

    def test_cursor_cli_name(self):
        b = CursorCliBackend()
        self.assertEqual(b.name, "Cursor CLI")

    def test_codex_name(self):
        b = CodexBackend()
        self.assertEqual(b.name, "Codex CLI")

    def test_pi_name(self):
        b = PiBackend()
        self.assertEqual(b.name, "pi.dev")




class TestCodexExportImport(unittest.TestCase):
    """Round-trip test: write a session file → export → import → verify."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._sessions_dir = os.path.join(self._tmpdir.name, "sessions")
        os.makedirs(self._sessions_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_round_trip(self):
        sid = "00000000-0000-0000-0000-000000000001"
        fname = f"2024-01-01T00-00-00_{sid}.jsonl"
        fpath = os.path.join(self._sessions_dir, fname)
        with open(fpath, "w") as f:
            f.write(json.dumps({"type": "session_meta", "timestamp": "2024-01-01T00:00:00Z", "payload": {"cwd": "/tmp/test"}}) + "\n")
            f.write(json.dumps({"type": "response_item", "timestamp": "2024-01-01T00:00:01Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}}) + "\n")
            f.write(json.dumps({"type": "response_item", "timestamp": "2024-01-01T00:00:02Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi there"}]}}) + "\n")
            f.write(json.dumps({"type": "response_item", "timestamp": "2024-01-01T00:00:03Z", "payload": {"type": "function_call", "name": "Bash", "arguments": json.dumps({"command": "ls"})}}) + "\n")
            f.write(json.dumps({"type": "response_item", "timestamp": "2024-01-01T00:00:04Z", "payload": {"type": "function_call_output", "output": "file1\nfile2"}}) + "\n")

        sess = CodexSession(session_id=sid, thread_name="test", updated_at="2024-01-01T00:00:00Z", file_path=fpath, file_size=os.path.getsize(fpath))
        transcript = codex_backend.export_transcript(sess)
        self.assertEqual(transcript.source_tool, "codex")
        self.assertEqual(len(transcript.messages), 4)
        self.assertEqual(transcript.messages[0].kind, "text")
        self.assertEqual(transcript.messages[0].role, "user")
        self.assertEqual(transcript.messages[2].kind, "tool_call")
        self.assertEqual(transcript.messages[2].tool_name, "Bash")
        self.assertEqual(transcript.messages[3].kind, "tool_result")

    def test_import_produces_readable_file(self):
        t = Transcript(source_tool="codex", session_id="test", title="Test", cwd="/tmp", created_at="", updated_at="", messages=[
            TranscriptMessage(role="user", kind="text", text="hello"),
            TranscriptMessage(role="assistant", kind="text", text="world"),
        ])
        with patch("codex_backend.SESSIONS_DIR", self._sessions_dir), \
             patch("codex_backend.SESSION_INDEX", os.path.join(self._tmpdir.name, "session_index.jsonl")), \
             patch("codex_backend.HISTORY_FILE", os.path.join(self._tmpdir.name, "history.jsonl")):
            new_id = codex_backend.import_transcript(t, "/tmp/test")
            self.assertTrue(len(new_id) > 10)
            sessions = codex_backend.scan_sessions()
            ids = [s.session_id for s in sessions]
            self.assertIn(new_id, ids)


class TestPiExportImport(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._sessions_dir = os.path.join(self._tmpdir.name, "sessions")
        os.makedirs(self._sessions_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_round_trip(self):
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        fname = f"2024-06-15T10-00-00_{sid}.jsonl"
        proj_dir = os.path.join(self._sessions_dir, "--home-user-project--")
        os.makedirs(proj_dir, exist_ok=True)
        fpath = os.path.join(proj_dir, fname)
        with open(fpath, "w") as f:
            f.write(json.dumps({"type": "session", "id": sid, "cwd": "/home/user/project", "timestamp": "2024-06-15T10:00:00Z"}) + "\n")
            f.write(json.dumps({"type": "message", "timestamp": "2024-06-15T10:00:01Z", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}) + "\n")
            f.write(json.dumps({"type": "message", "timestamp": "2024-06-15T10:00:02Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}, {"type": "toolCall", "name": "Bash", "arguments": {"command": "pwd"}}]}}) + "\n")
            f.write(json.dumps({"type": "message", "timestamp": "2024-06-15T10:00:03Z", "message": {"role": "toolResult", "content": [{"type": "text", "text": "/home/user/project"}]}}) + "\n")

        sess = PiSession(session_id=sid, file_path=fpath, title="Test", created_at="2024-06-15T10:00:00Z", updated_at="2024-06-15T10:00:03Z", message_count=3, file_size=os.path.getsize(fpath))
        transcript = pi_backend.export_transcript(sess)
        self.assertEqual(transcript.source_tool, "pi")
        self.assertEqual(len(transcript.messages), 4)
        self.assertEqual(transcript.messages[0].kind, "text")
        self.assertEqual(transcript.messages[2].kind, "tool_call")
        self.assertEqual(transcript.messages[2].tool_name, "Bash")
        self.assertEqual(transcript.messages[3].kind, "tool_result")

    def test_import_produces_readable_file(self):
        t = Transcript(source_tool="pi", session_id="test", title="Test", cwd="/tmp", created_at="", updated_at="", messages=[
            TranscriptMessage(role="user", kind="text", text="hello"),
            TranscriptMessage(role="assistant", kind="text", text="world"),
        ])
        with patch("pi_backend.SESSIONS_DIR", self._sessions_dir):
            new_id = pi_backend.import_transcript(t, "/tmp/test")
            self.assertTrue(len(new_id) > 10)
            projects = pi_backend.scan_projects()
            all_ids = [s.session_id for p in projects for s in p.sessions]
            self.assertIn(new_id, all_ids)


class TestCursorCliExportImport(unittest.TestCase):
    """Test Cursor CLI export from agent-transcripts JSONL + import."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._chats_dir = os.path.join(self._tmpdir.name, "chats")
        self._projects_dir = os.path.join(self._tmpdir.name, "projects")
        os.makedirs(self._chats_dir)
        os.makedirs(self._projects_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_export_from_agent_transcript(self):
        chat_id = "11111111-2222-3333-4444-555555555555"
        transcript_dir = os.path.join(self._projects_dir, "hash", "agent-transcripts", chat_id)
        os.makedirs(transcript_dir)
        tpath = os.path.join(transcript_dir, f"{chat_id}.jsonl")
        with open(tpath, "w") as f:
            f.write(json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}}) + "\n")
            f.write(json.dumps({"message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}) + "\n")
            f.write(json.dumps({"message": {"role": "assistant", "content": [{"type": "tool_result", "content": [{"type": "text", "text": "file1"}]}]}}) + "\n")

        chat_dir = os.path.join(self._chats_dir, "hash", chat_id)
        os.makedirs(chat_dir)
        with open(os.path.join(chat_dir, "meta.json"), "w") as f:
            json.dump({"title": "Test Chat", "createdAtMs": 1718400000000, "updatedAtMs": 1718400010000}, f)
        with open(os.path.join(chat_dir, "prompt_history.json"), "w") as f:
            json.dump([], f)

        chat = CliChat(chat_id=chat_id, workspace_hash="hash", dir_path=chat_dir, title="Test Chat", created_at=1718400000000, updated_at=1718400010000)
        with patch("cursor_backend.CLI_PROJECTS_DIR", self._projects_dir), \
             patch("cursor_backend.CLI_CHATS_DIR", self._chats_dir):
            transcript = cursor_backend.export_cli_transcript(chat)

        self.assertEqual(transcript.source_tool, "cursor_cli")
        self.assertEqual(len(transcript.messages), 4)
        self.assertEqual(transcript.messages[0].text, "hello")
        self.assertEqual(transcript.messages[2].kind, "tool_call")
        self.assertEqual(transcript.messages[2].tool_name, "Bash")
        self.assertEqual(transcript.messages[3].kind, "tool_result")
        self.assertIn("file1", transcript.messages[3].text)

    def test_import_creates_files(self):
        t = Transcript(source_tool="cursor_cli", session_id="test", title="Test", cwd="/tmp", created_at="", updated_at="", messages=[
            TranscriptMessage(role="user", kind="text", text="hello"),
            TranscriptMessage(role="assistant", kind="text", text="world"),
        ])
        with patch("cursor_backend.CLI_PROJECTS_DIR", self._projects_dir), \
             patch("cursor_backend.CLI_CHATS_DIR", self._chats_dir):
            new_id = cursor_backend.import_cli_transcript(t, "/tmp/test")

        self.assertTrue(len(new_id) > 10)
        transcript_dir = os.path.join(self._projects_dir, "tmp-test", "agent-transcripts", new_id)
        tpath = os.path.join(transcript_dir, f"{new_id}.jsonl")
        self.assertTrue(os.path.isfile(tpath))
        chat_dir = os.path.join(self._chats_dir, hashlib.md5(b"/tmp/test").hexdigest(), new_id)
        self.assertTrue(os.path.isfile(os.path.join(chat_dir, "meta.json")))


class TestCursorIdeImport(unittest.TestCase):
    def test_import_raises_not_implemented(self):
        b = CursorIdeBackend()
        with self.assertRaises(NotImplementedError):
            b.import_transcript(None, "/tmp")


if __name__ == "__main__":
    unittest.main()
