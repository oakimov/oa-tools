"""Canonical intermediate representation for cross-tool transcript
export/import. See plans/transcript-converter-plan.md for the design.

Captures every block kind actually present in a transcript — not just
prose text. `kind` is the block's own semantic category (not the source
tool's native field name), so writers only need to handle four cases:

  - "text"        prose
  - "thinking"     extended-thinking / reasoning content (Claude "thinking"
                   blocks, Codex "reasoning" response_items, OpenCode
                   "reasoning" parts, pi.dev "thinking" blocks, Cursor's
                   `allThinkingBlocks`)
  - "tool_call"    a tool invocation — name + raw structured input,
                   preserved as-is (not pre-rendered to a display string)
  - "tool_result"  a tool's raw output, preserved in full (no truncation —
                   that's a message-viewer display concern, not an export
                   concern)
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
KINDS = ("text", "thinking", "tool_call", "tool_result")


@dataclass
class TranscriptMessage:
    role: str                          # "user" | "assistant"
    kind: str                          # one of KINDS
    text: str = ""                     # prose / thinking content / tool_result output
    tool_name: Optional[str] = None    # kind == "tool_call" | "tool_result"
    tool_input: Optional[Dict[str, Any]] = None  # kind == "tool_call", raw structured args
    timestamp: Optional[str] = None


@dataclass
class Transcript:
    source_tool: str
    session_id: str
    title: str
    cwd: str
    created_at: str
    updated_at: str
    messages: List[TranscriptMessage] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @staticmethod
    def from_json(s: str) -> "Transcript":
        d = json.loads(s)
        d["messages"] = [TranscriptMessage(**m) for m in d.get("messages", [])]
        return Transcript(**d)
