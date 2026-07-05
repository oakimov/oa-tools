# Cross-tool transcript converter — plan

**Status (2026-07-05): prototype validated on a real migration.**
`transcript_ir.py` + Claude Code export/import + OpenCode import are
implemented and were used to actually migrate a real 201-message session
("CCR API 400 model parsing error") from Claude Code into a new Claude
Code session and a new OpenCode session — verified via the real installed
`claude`/`opencode` CLIs, zero content mismatches. This resolved all but
one of the plan's original open questions; see "Open questions —
confirmed by real migration" below for what changed and why. Remaining:
the pi.dev, Codex, Cursor CLI, and Cursor IDE writers (Steps 2/4/6/7), and
the 4 remaining exporters in Step 1 (Cursor, Codex, OpenCode, pi.dev), are
still per the original design, not yet prototyped against a real app.

## Goal

A utility to export a conversation/session transcript from any of the 5
tools session-cleaner already supports (Claude Code, Cursor IDE, Cursor CLI,
Codex CLI, OpenCode, pi.dev) and import it into any other, individually or
in bulk ("export all", "import all"). Read-only against the source; writes
new sessions into the target (never mutates existing sessions).

## Verdict: feasible, and cheaper than it looks

We already have a working, verified reader for every tool's message format
— that's most of the hard part. `claude_backend.get_conversation_messages`,
`cursor_backend.get_bubble_messages`/`get_cli_chat_messages`,
`codex_backend.get_session_messages`, `opencode_backend.get_session_messages`,
`pi_backend.get_session_messages` all already parse role, text, tool calls,
and tool results correctly (verified against real data this session). The
new work is almost entirely on the **write** side: constructing files/DB rows
that each tool's own app will recognize as a real session.

Building this as **N readers + N writers through one shared intermediate
format** (5+5=10 units) is far cheaper than N×(N-1) bespoke pairwise
converters (20 units), and is the only sane way to do "export all / import
all" anyway.

## Architecture

```
source tool  --[reader]-->  canonical IR (JSON)  --[writer]-->  target tool
```

### Canonical IR schema — as implemented in `transcript_ir.py`

Revised during implementation: the first draft flattened tool turns
through `common.format_tool_call`/`format_tool_result` (the *display*
rendering) straight into the IR, and dropped `thinking`/`reasoning`
blocks entirely. That's lossy in the wrong place — a viewer-display
concern (5-line truncation, human-readable formatting) baked permanently
into the export, and real content (thinking/reasoning turns) silently
discarded. The IR instead preserves every block's **raw structured
fields**, not a pre-rendered string, and `kind` covers `thinking` too:

```json
{
  "schema_version": 1,
  "source_tool": "claude|cursor-ide|cursor-cli|codex|opencode|pi",
  "session_id": "original id, kept for traceability only",
  "title": "string",
  "cwd": "/absolute/realpath-resolved/working/directory",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "messages": [
    {
      "role": "user|assistant",
      "kind": "text|thinking|tool_call|tool_result",
      "text": "prose, thinking content, or tool_result output — raw, untruncated",
      "tool_name": "string, only for kind=tool_call",
      "tool_input": "raw dict, only for kind=tool_call — not a formatted string",
      "timestamp": "ISO-8601 or null"
    }
  ]
}
```

Exporters split each raw event's content blocks into one IR message per
block (see Claude's `export_transcript`), rather than joining everything
in one event into a single flattened string — this is what lets a writer
faithfully reconstruct thinking blocks and raw tool arguments instead of
a display-only rendering. Writers that need the human-readable
`[tool call]`/`[tool result]` format (e.g. for a tool that stores call+
result as one combined string, unlike Claude/Codex/pi.dev's separate
events) still call `common.format_tool_call`/`format_tool_result` at
*write* time, not export time.

## Per-tool status

| Tool | Reader (export) | Writer (import) | Notes |
|---|---|---|---|
| Claude Code | done, reuse as-is | new | needs `sessionId`, `parentUuid` chain, `cwd`, plus a `~/.claude.json` project entry if the target path isn't already registered |
| pi.dev | done, reuse as-is | new | flat `.jsonl`, no separate index — simplest target |
| Codex | done, reuse as-is | new | rollout `.jsonl` **plus** an appended `session_index.jsonl` entry, or `codex resume` won't list it |
| OpenCode | done, reuse as-is | new | SQLite `INSERT`s into `session`/`message`/`part` with correct id generation and foreign keys |
| Cursor IDE | done, reuse as-is | new | SQLite `composerHeaders`/`cursorDiskKV` bubbles **plus** merging into the `ItemTable` `composer.composerHeaders` JSON blob, possibly a `workspaceStorage/{hash}/workspace.json` if the target workspace doesn't exist yet. Highest complexity/risk — this schema has already migrated once (found earlier this session) and needs the same version-detection defensiveness the reader uses. |
| Cursor CLI | done, reuse as-is | new | write the `agent-transcripts/{chatId}/{chatId}.jsonl` mirror format (simple) rather than the Merkle-DAG `store.db` (hard, not worth reproducing for a static import) |

## Known limitations (be upfront about these, don't try to solve in v1)

- **Lossy, but less than the first draft.** The IR captures
  role/text/thinking/tool-call/tool-result/timestamps with raw (not
  display-rendered) fidelity — verified with zero mismatches across a
  real 201-message migration. What's still dropped: tool-specific extras
  that don't map to any of those four kinds (Claude subagent sidechains,
  Cursor code-block diffs/lint state, OpenCode snapshots/patches). Document
  this plainly in the tool's `--help` and in any confirmation prompt.
- **Imported sessions must be non-resumable/archived.** These are static
  history, not live agent state — none of the target tools' own tool-calling
  loop should be pointed at a foreign transcript and asked to "continue" it
  (tool call IDs, model state, etc. won't line up). Mark imported sessions
  read-only/archived where the target format supports it (e.g. Codex/OpenCode
  have archive flags; note where one doesn't).
- **Close the target app before importing**, same safety rule already in
  the README for direct deletes — writing into a live SQLite DB the app has
  open risks the exact overwrite/corruption class of issue already called
  out for Cursor.
- **Images/attachments out of scope for v1** — render a `[attachment omitted]`
  placeholder rather than trying to convert binary formats across tools.
- **Tool name passthrough.** A "Bash" call exported from Claude shows up
  literally as "Bash" in, say, OpenCode's transcript. Fine for a static
  read-only history; explicitly not attempting name-mapping in v1.

## Effort estimate

**Total: ~8–10 working days** for full bidirectional coverage across all 5
tools. Order goes easiest/lowest-risk first (pi.dev → Claude → Codex →
OpenCode → Cursor CLI → Cursor IDE), saving Cursor IDE — the one with real
schema-compatibility risk — for last, once the IR/CLI scaffold is already
proven on four simpler targets. Full breakdown below.

## Step-by-step execution plan

Each step's **acceptance criteria** must pass before starting the next step
that depends on it. Steps 2–7 (the writers) are independent of each other
and can be done in any order or in parallel — the suggested order is by
risk, not dependency.

---

### Step 0 — Canonical IR schema — **done, prototyped 2026-07-05**

**Description.** Define the shared intermediate representation every
reader produces and every writer consumes: a `Transcript` dataclass
(session_id, title, cwd, created_at, updated_at, source_tool, messages) and
a `TranscriptMessage` dataclass (role, kind, text, tool_name, tool_input,
timestamp) — revised from the original sketch to preserve raw block
fidelity including `thinking`, not pre-rendered display text (see the
Canonical IR schema section above for why). Include JSON (de)serialization.

**Input.** The IR schema sketch in this document; the existing shapes
already returned by `get_conversation_messages`/`get_bubble_messages`/
`get_cli_chat_messages`/`get_session_messages` (all 5 tools) as the
ground truth for what fields are actually available to populate it.

**Deliverable.** New file `transcript_ir.py`: `Transcript` and
`TranscriptMessage` dataclasses, `Transcript.to_json()` /
`Transcript.from_json()`, `SCHEMA_VERSION` constant. **Implemented.**

**Acceptance criteria.**
- A hand-built `Transcript` with at least one of each `kind`
  (text/tool_call/tool_result) round-trips through `to_json()` →
  `from_json()` with zero field loss (`assert original == roundtripped`).
- `python3 -c "import ast; ast.parse(...)"` passes; no other module imports
  broken.

---

### Step 1 — Exporters (one per tool) — **Claude Code done, 4 remaining**

**Description.** Add an `export_transcript(session_ref) -> Transcript`
function per backend module. Not quite as thin an adapter as first
planned — to preserve per-block `kind` (text vs. thinking vs. tool_call
vs. tool_result) rather than one flattened string per raw event, the
exporter iterates each raw event's content blocks individually rather
than reusing `get_*_messages()`'s already-joined output as-is (see
Claude's `export_transcript` in `claude_backend.py`, which reads the same
raw events `get_conversation_messages` returns but re-splits them).

**Input.** `transcript_ir.py` (Step 0); each backend's existing
`ConversationInfo`/`CodexSession`/`PiSession`/etc. dataclasses and
`get_*_messages` functions.

**Deliverable.** `export_transcript()` added to `claude_backend.py`
(**done**), `cursor_backend.py` (two variants: IDE composer, CLI chat —
pending), `codex_backend.py` (pending), `opencode_backend.py` (pending —
only the writer was prototyped for OpenCode, not the reader/exporter),
`pi_backend.py` (pending).

**Acceptance criteria.**
- For one real, already-populated session per tool (reuse sessions already
  verified in this project, e.g. Claude's "CCR API 400 model parsing
  error", a Cursor bubble conversation with `toolFormerData`, a Codex
  session with `function_call`/`function_call_output`, an OpenCode session
  with a `tool` part, a pi.dev session with `toolCall`/`toolResult`):
  the exported `Transcript.messages` count and role sequence exactly match
  what that tool's own `get_*_messages()` already returns, and every
  `[tool call]`/`[tool result]` rendering is preserved verbatim in `text`.
- Exporting a session with zero messages produces a `Transcript` with an
  empty `messages` list, not an exception.

---

### Step 2 — pi.dev writer

**Description.** Write a new `.jsonl` session file that pi.dev's own
reader (`pi_backend.scan_projects`/`get_session_messages`) recognizes:
a leading `session` event (cwd, timestamp) followed by `message` events
(role, content blocks) reconstructed from the IR.

**Input.** A `Transcript` object (Step 1 output); `pi_backend.py`'s
`SESSIONS_DIR`, path-encoding convention (`{encoded-cwd}/{timestamp}_{uuid}.jsonl`).

**Deliverable.** `import_transcript(transcript, target_cwd) -> str` (returns
the new file path) in `pi_backend.py`.

**Acceptance criteria.**
- After writing, `pi_backend.scan_projects()` lists the new session under
  `target_cwd`'s project.
- `pi_backend.get_session_messages()` on the new session returns the same
  role/text sequence as the source `Transcript.messages` (order preserved).
- The written file parses as valid JSONL (every line is valid JSON) with
  no partial/corrupt lines.

---

### Step 3 — Claude Code writer — **done, prototyped 2026-07-05**

**Description.** Write a new `.jsonl` under `~/.claude/projects/{encoded}/`
with a linear `parentUuid` chain (one event per IR message — a
simplification vs. the original, which may group several blocks into one
turn, but reads back identically), reconstructing `text`/`thinking`/
`tool_use`/`tool_result` content blocks per the IR message's `kind`. If
`target_cwd` has no entry in `~/.claude.json`, add one. Also writes a
leading `custom-title` event so the title survives even when the source
`.jsonl` itself never had one (this session's real title only existed in
Claude Desktop's session index, not the transcript — see the enrichment
work earlier in this project).

**Input.** A `Transcript` object; `claude_backend.py`'s `PROJECTS_DIR`,
`encode_project_path`, `CONFIG_PATH`/`load_config`/`save_config`.
**`target_cwd` must be `os.path.realpath()`-resolved** — see Open
Questions below.

**Deliverable.** `import_transcript(transcript, target_cwd)` in
`claude_backend.py` — **implemented**. Required extra event fields found
by trial and error against the real `claude --resume` picker: `gitBranch`
(via `git rev-parse --abbrev-ref HEAD` in `target_cwd`), `promptId`,
`origin`, `permissionMode`, `promptSource` (user events only), and a real
`version` string (via `claude --version`) — a bare-bones event that our
own reader parsed fine was silently invisible to the real picker without
these.

**Acceptance criteria — all met:**
- `claude_backend.scan_all_projects()` lists the new conversation under
  the target project with the correct message count.
- `claude_backend.get_conversation_messages()` returns matching role/text
  — verified with **zero mismatches across all 201 messages** of a real
  migrated session (43 text / 79 tool_call / 79 tool_result).
- `~/.claude.json` gets a new `projects[target_cwd]` entry when one didn't
  exist; existing entries are left untouched.
- `claude --resume` (the real CLI) lists the session under the target
  project with the correct title, once `target_cwd` is realpath-resolved.

---

### Step 4 — Codex writer

**Description.** Write a new `rollout-*.jsonl` under
`~/.codex/sessions/YYYY/MM/DD/` with `response_item` events
(`message`/`function_call`/`function_call_output` payloads reconstructed
from IR `kind`), and append a matching entry to `session_index.jsonl` so
the session isn't `[index-only]`/`[file-only]`.

**Input.** A `Transcript` object; `codex_backend.py`'s `SESSIONS_DIR`,
`session_index.jsonl` format (id/thread_name/updated_at).

**Deliverable.** `import_transcript(transcript, target_cwd)` in
`codex_backend.py`.

**Acceptance criteria.**
- `codex_backend.scan_sessions()` lists the new session with
  `orphan_file=False` and `orphan_index=False`.
- `codex_backend.get_session_messages()` returns matching role/text,
  including reconstructed `function_call`/`function_call_output` turns.
- (Manual, if `codex` CLI installed) `codex resume` lists the session.

---

### Step 5 — OpenCode writer — **done, prototyped 2026-07-05**

**Description.** ~~Insert new rows directly into `opencode.db`~~ — superseded:
OpenCode ships its own `opencode export [sessionID]` / `opencode import
<file>` commands (found via `opencode --help`). Shell out to `opencode
import` with a JSON file in its native
`{"info": {...}, "messages": [{"info": {...}, "parts": [...]}]}` shape
(reverse-engineered from a real `opencode export`) instead of hand-crafting
SQLite rows — guaranteed compatible with the installed version's schema,
and the tool's own writer handles project creation/id generation for you.
tool_call + the following tool_result merge into one native `"tool"` part
(`state.input`/`state.output`) since OpenCode keeps call+result together,
like Cursor.

**Input.** A `Transcript` object; `target_cwd` (must be
`os.path.realpath()`-resolved — see Open Questions); the `opencode` binary
on PATH.

**Deliverable.** `import_transcript(transcript, target_cwd)` in
`opencode_backend.py` — **implemented**, see the function for the full
field set required (`slug`, `version`, `agent`, `parentID` on assistant
messages, `state.title`/`metadata`/`time` on tool parts — all found by
trial and error against the real `opencode import` validator).

**Acceptance criteria — all met:**
- `opencode import` exits 0 and reports the new session id.
- `opencode_backend.get_session_messages()` on the new session returns the
  same role/text/tool-call sequence as the source `Transcript` — verified
  with **zero mismatches across all 122 messages** of a real migrated
  session.
- `opencode session list` (the real CLI, run from the target directory)
  shows the session with the correct title.
- On `opencode import` failure, no orphaned partial session is left behind
  (the writer detects and deletes it — see Open Questions: this failure
  mode is real and was hit repeatedly during development).

---

### Step 6 — Cursor CLI writer

**Description.** Write `meta.json` and the `agent-transcripts/{chatId}/
{chatId}.jsonl` mirror format (not the `store.db` Merkle-DAG — not worth
reproducing for a one-shot static import) under
`~/.cursor/chats/{md5(target_cwd)}/{chatId}/` and
`~/.cursor/projects/{slugified-cwd}/agent-transcripts/{chatId}/`.

**Input.** A `Transcript` object; `cursor_backend.py`'s `CLI_CHATS_DIR`,
`CLI_PROJECTS_DIR`, `_slugify_cwd`, `_agent_transcript_path`.

**Deliverable.** `import_transcript_cli(transcript, target_cwd)` in
`cursor_backend.py`.

**Acceptance criteria.**
- `cursor_backend.scan_cli_workspaces()` lists the new chat under the
  target workspace hash.
- `cursor_backend.get_cli_chat_messages()` returns matching role/text
  (reads via the transcript-mirror path, confirmed by inspecting which
  branch of `get_cli_chat_messages` served the read).

---

### Step 7 — Cursor IDE writer (highest risk — do last)

**Description.** Insert `bubbleId:{composerId}:{uuid}` rows into
`cursorDiskKV`, add an entry to the `composer.composerHeaders` JSON blob
in `ItemTable` (the schema this project already found to be authoritative
on current Cursor versions), and create a
`workspaceStorage/{hash}/workspace.json` if the target workspace doesn't
already have one. Detect schema version the same defensive way the reader
does (`_load_composer_headers()` vs. legacy `composerHeaders` table) and
write to whichever the installed Cursor version expects.

**Input.** A `Transcript` object; `cursor_backend.py`'s `CURSOR_GLOBAL_DB`,
`WORKSPACE_STORAGE`, `_load_composer_headers`, `encode_project_path`-
equivalent for Cursor's workspace hashing.

**Deliverable.** `import_transcript_ide(transcript, target_cwd)` in
`cursor_backend.py`.

**Acceptance criteria.**
- `cursor_backend.scan_conversations()` lists the new conversation under
  the target workspace.
- `cursor_backend.get_bubble_messages()` returns matching role/text.
- (Manual, **Cursor IDE fully closed during import**) reopening Cursor
  shows the conversation in its sidebar with correct title and message
  content — this is the one target that most needs live verification
  since it's the one with real schema-compatibility risk.

---

### Step 8 — CLI wrapper

**Description.** A single entry point tying every reader/writer together:
`transcript-convert.py --from TOOL --to TOOL --session ID --target-cwd PATH`
for one session, and `--all` to export+import every session from the
source tool. Prints a summary (N exported, N imported, N failed with
reasons) rather than failing silently or aborting the whole batch on one
bad session.

**Input.** All Step 1–7 functions.

**Deliverable.** `transcript-convert.py` entry point, added to `cleaner.py`
dispatcher if useful.

**Acceptance criteria.**
- Single-session mode works end-to-end for at least one real pair
  (export a real session, import it, verify via the target tool's own
  `scan_*`/`get_*_messages`).
- `--all` mode processes every session from a source tool without
  aborting when one session fails (e.g. unparseable/corrupt source data)
  — failures are reported, not fatal.
- Running against a source/target with zero sessions exits cleanly with
  a clear "nothing to do" message, not an exception.

---

### Step 9 — Cross-tool smoke tests

**Description.** A handful of real, representative end-to-end conversions
(not all 20 possible pairs — the per-writer acceptance criteria in Steps
2–7 already cover round-tripping through each tool's own reader). Pick
pairs that exercise different IR message kinds (plain text, tool_use/
tool_call, tool_result) and different writer complexity classes (simple:
pi.dev/Codex; DB-backed: OpenCode; Cursor-specific: IDE/CLI).

**Input.** The `transcript-convert.py` CLI (Step 8); real populated
sessions already used throughout this project (e.g. the
"claude-code-router" project's sessions, a Cursor conversation with tool
calls).

**Deliverable.** A short test log (which pairs were run, pass/fail) —
following this project's existing pty-based non-destructive verification
methodology (launch the target tool's session-cleaner TUI, navigate to
the imported session, confirm it renders correctly, never confirm an
actual delete during verification).

**Acceptance criteria.**
- At least: Claude Code → OpenCode, Cursor IDE → pi.dev, Codex → Cursor
  CLI (or equivalent pairs chosen for coverage) all show correctly
  rendered messages — including tool calls/results — in the target
  tool's own session-cleaner TUI message viewer after import.

---

### Step 10 — Documentation

**Description.** Document the tool in the project README: usage,
supported tool-pairs, the lossy-conversion and non-resumable-import
caveats, and the "close the target app first" safety note.

**Input.** Finished, tested implementation (Steps 0–9).

**Deliverable.** New README section; `transcript-convert.py --help` text
covering all flags and both single/`--all` modes.

**Acceptance criteria.**
- README section reviewed against the actual CLI behavior (flags, output
  format) rather than the plan's original intent — update either the
  docs or the code if they've drifted during implementation.

## Open questions — confirmed by real migration (2026-07-05)

Prototyped `transcript_ir.py` + Claude Code export/import + OpenCode import
and actually migrated a real session ("CCR API 400 model parsing error",
201 IR messages: 43 text / 79 tool_call / 79 tool_result — no `thinking`
blocks in this particular session, but the code path handles them) from
Claude Code into a fresh Claude Code session and a fresh OpenCode session.
Both verified via **real installed CLIs** (`claude`, `opencode`), not just
our own readers. Findings:

- [x] **Foreign/synthetic sessions are accepted by both tools** — once the
      writer's event/row shape closely matches a real transcript's fields.
      This took real trial and error against the actual apps, not
      documentation: Claude Code's jsonl needed `gitBranch`, `promptId`,
      `origin`, `permissionMode`, `promptSource`, and a real `version`
      string (matching the installed CLI's own `--version`) before its
      `--resume` picker would show the session at all — a bare-minimum
      valid-looking event was silently invisible to the picker even though
      our own reader parsed it fine. OpenCode's native import validator
      rejected five different missing-field errors in sequence
      (`slug`, `version`, `agent`, `parentID`, `state.title`) before a
      full field set (matching a real `opencode export` sample) succeeded.
      **Takeaway: match the full real event/row shape, not just the
      minimal fields your own reader happens to need — the target tool's
      own loader is stricter than a lenient reader you wrote yourself.**
- [x] **Target-project path must be the realpath-resolved absolute path,
      not a symlinked form.** This was the actual root cause the first
      time the import "failed" to show up: the session was written with
      `cwd: "/tmp/transcript-migration-test"`, and it displayed correctly
      in "show all projects" (Claude) / when run from a different cwd
      (OpenCode), but was invisible under "current project" scoping —
      because macOS's `/tmp` is a symlink to `/private/tmp`, and both
      tools' current-project filters compare against the resolved path.
      Re-importing with `/private/tmp/transcript-migration-test` fixed it
      immediately. **Every writer must `os.path.realpath()` the target cwd
      before using it.**
- [x] **Target project doesn't need to exist beforehand** — both tools
      happily created one on the fly (Claude Code: added a
      `~/.claude.json` entry; OpenCode: `opencode import` created its own
      `project` row) for a directory neither had ever seen before
      (`/private/tmp/transcript-migration-test`, a fresh empty git repo).
      No "project must already exist" precondition needed.
- [x] **Prefer a tool's native export/import command over reverse-engineered
      writes, when one exists.** OpenCode ships `opencode export
      [sessionID]` / `opencode import <file>` (found via `opencode --help`
      — not documented anywhere else we looked). Its JSON shape
      (`{"info": {...}, "messages": [{"info": {...}, "parts": [...]}]}`)
      was reverse-engineered by running a real export, and the writer now
      shells out to `opencode import` instead of hand-crafting SQLite rows
      — guaranteed compatible with whatever schema the installed version
      expects, rather than a guess frozen at plan-writing time. **Check
      for a native export/import command before building a direct-storage
      writer for any tool not yet prototyped (Codex, Cursor IDE/CLI,
      pi.dev).**
- [x] **`opencode import` is not atomic on failure.** During development,
      every failed import attempt (missing-field validation errors) left
      an orphaned partial session behind in the database — sometimes with
      0 messages, sometimes with a few, depending on how far it got before
      failing. The writer now checks for and deletes the partial session
      if the `opencode import` subprocess returns non-zero. **Any writer
      that shells out to a tool's own CLI must assume partial failure is
      possible and clean up after itself — don't assume atomicity.**
- [ ] Not yet tested: whether "import all" needs to be resumable/idempotent
      for large batches — this run was a single session. Still open.
- [x] Default target-project mapping confirmed: same `cwd` on this
      machine, realpath-resolved. No per-session prompting needed as long
      as that path is used consistently.
