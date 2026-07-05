# session-cleaner

CLI and TUI tools for browsing and cleaning up local session data left behind
by Claude Code, Cursor, Codex CLI, and OpenCode. All four tools share the same
navigation model — **project list → conversation/session list → message
deep-dive** — and the same look, built on a common TUI toolkit.

## Architecture

| File | Purpose |
|------|---------|
| `common.py` | Low-level utilities shared by everything: size/timestamp formatting, JSON I/O, path-safety checks, and tool-call/tool-result rendering (`format_tool_call`, `format_tool_result`, `strip_top_lines`) used by all five backends' message viewers. |
| `tui_kit.py` | Shared `prompt_toolkit` scaffolding: canonical style sheet, app bootstrapping (`run_app`/`run_custom`), declarative key-binding wiring (`bind_keys`), the confirm-before-delete dialog (`ConfirmMixin`), and the scrollable message-transcript viewer (`MessageScrollMixin`, used by all five tools). |
| `browser_tui.py` | Generic **project → item → message** browser (`ListDrillTUI`). Codex, OpenCode, and Cursor's primary chat view are thin subclasses of this: they configure a handful of class attributes (noun labels, optional archive/reconcile/multi-select) and implement small data-access hooks (`_scan_top`, `_mid_row_text`, `_delete_mid_one`, ...); navigation, rendering scaffold, confirm dialog, key dispatch, and app bootstrap all live here once. |
| `claude_backend.py` / `claude_tui.py` | Claude Code: scans `~/.claude.json` and `~/.claude/projects/`, and (transparently, on every delete) the Claude Desktop app's own session index at `~/Library/Application Support/Claude/claude-code-sessions/{account}/{org}/local_*.json` — a separate mirror the Desktop app uses for its own session sidebar, keyed to the CLI transcript by `cliSessionId`. `ClaudeCleanerTUI` is **not** built on `browser_tui` — its dual-pane project-detail layout (conversations + memories/MCP/plans side-by-side) is a genuinely different shape — but it shares `tui_kit`'s confirm dialog and message-transcript viewer, and implements the same `Space`-to-select / bulk-delete pattern independently for both its project list and conversation list. |
| `cursor_backend.py` / `cursor_tui.py` | Cursor **IDE**: scans the global SQLite store (`state.vscdb`) and workspace mappings. `CursorCleanerTUI` subclasses `browser_tui.ListDrillTUI` for its workspace → conversation → message flow (opting into archive, reconcile, and top-level multi-select). It also embeds a second, independent `ListDrillTUI` instance, `CursorCliChatsTUI` (`c` key), for the **CLI** (`cursor-agent`)'s separate `~/.cursor/chats/` store — and layers a third, bespoke pair of views (`g`) for Cursor's local **agent projects** (Background Agents), whose shape (members are either real chats or agent-only, no per-member delete) doesn't fit the generic engine at all. |
| `cursor_crypt.py` | Decryption for Cursor's `EncryptedBlobStore` (AES-256-GCM), reverse-engineered from Cursor's own shipped JS — see the module docstring for the full writeup, including what it's actually used for. Pure crypto primitive (`derive_key`, `decrypt_blob`); `cursor_backend.py` owns finding candidate keys/ciphertext and wiring it in as a seamless fallback in `get_bubble_messages`. |
| `codex_backend.py` / `codex_tui.py` | Codex CLI: scans `~/.codex/session_index.jsonl`, `history.jsonl`, and the `sessions/` tree. Sessions are grouped into "projects" by the `cwd` recorded in each session's leading `session_meta`/`turn_context` event. `CodexCleanerTUI` is a ~90-line `browser_tui.ListDrillTUI` subclass. |
| `opencode_backend.py` / `opencode_tui.py` | OpenCode: scans `~/.local/share/opencode/opencode.db` (SQLite). Sessions are grouped into "projects" by `session.directory` directly. `OpencodeCleanerTUI` is a ~75-line `browser_tui.ListDrillTUI` subclass. |
| `pi_backend.py` / `pi_tui.py` | pi.dev: scans `~/.pi/agent/sessions/{encoded-cwd}/{timestamp}_{uuid}.jsonl` — sessions are already grouped one directory per project, and the real cwd is read directly from each session file's leading `session` event. `PiCleanerTUI` is a ~65-line `browser_tui.ListDrillTUI` subclass. |
| `claude-cleaner.py` / `cursor-cleaner.py` / `codex-cleaner.py` / `opencode-cleaner.py` / `pi-cleaner.py` | Thin entry points — each just launches its tool's TUI. |
| `claude-mcp.py` | CLI for MCP server management and project cleanup (Claude Code only — the others have no equivalent config). |
| `cleaner.py` | Unified dispatcher: `python cleaner.py <claude\|cursor\|codex\|opencode\|pi>`. |
| `settings-propagate.py` | Propagates default permissions and skill overrides to all `.claude/settings.local.json` files. |
| `settings.local.json` | Canonical defaults file used by `settings-propagate.py`. |

## Usage

```bash
python cleaner.py claude    # or: python claude-cleaner.py
python cleaner.py cursor    # or: python cursor-cleaner.py  (press 'c' inside for CLI chats)
python cleaner.py codex     # or: python codex-cleaner.py
python cleaner.py opencode  # or: python opencode-cleaner.py
python cleaner.py pi        # or: python pi-cleaner.py

python claude-mcp.py tui   # same Claude TUI, reached through the MCP CLI
python claude-mcp.py list  # list registered Claude Code project paths
```

## Views (all five tools)

| View | Description |
|------|-------------|
| **Project list** | Projects/workspaces sorted by total size, with conversation/session counts. |
| **Conversation / session list** | Items within a project, newest first. Claude Code also shows a memories/MCP/plans side panel here. |
| **Message viewer** | Full message history for the selected conversation/session, scrollable. Renders tool calls and their results too (`[tool call] name: args` / `[tool result]\n...`), not just prose text — a turn that's purely a tool invocation used to render as "(no text content)". Tool *result* text has its first 5 lines stripped (`common.strip_top_lines`) to drop the boilerplate preamble some tools prepend (e.g. Codex's exec_command: chunk id, wall time, exit code, token count, an "Output:" marker). |
| **Confirm delete** | Confirm prompt before removing any item. |

### Keybindings

| Key | Context | Action |
|-----|---------|--------|
| `↑`/`↓` | everywhere | Navigate / scroll |
| `PgUp`/`PgDn` | message/memory viewer | Scroll pages |
| `Enter` | project list, item list | Open selected item |
| `Space` | project list, item list | Toggle multi-select — at both levels, in all five tools |
| `d` | everywhere | Delete current item, or every selected item if any are checked |
| `y` | confirm | Confirm action |
| `Esc` / `Backspace` | everywhere | Go back |
| `q` | top level | Quit; elsewhere, go back |

Claude Code adds `Tab` (switch conversations/memories pane), `1`/`2` (sort by
date/size), `m` (toggle MCP status), `D`/`A` (disable MCP for one/all
projects), `p` (plans cleanup view), `r` (reconcile — removes Claude Desktop
session-index entries that no longer point at a real transcript). Cursor adds `a` (archive), `A`
(delete all in workspace), `r` (reconcile — sweeps orphaned chat records **and**
leftover agent-store artifacts), `g` (open the agent-projects view), and `c`
(open the CLI-chats view — a second, independent project → chat → message
browser for `cursor-agent`'s own store; `Esc`/`q` at its top level returns to
the IDE view). Codex adds `D` (delete all sessions in project) and `r`
(reconcile — reports orphaned index/file entries). OpenCode adds `D` (delete
all sessions in project), matching Codex. pi.dev adds `D` (delete all
sessions in project), also matching Codex.

## Data models

### Claude Code

`~/.claude.json` holds project registration and MCP config. `~/.claude/projects/{encoded-path}/` holds one `.jsonl` per conversation plus `subagents/`, `tool-results/`, `memory/`, and `plans/` subdirectories. Session-level artifacts also live in `~/.claude/session-env/`, `~/.claude/file-history/`, and `~/.claude/sessions/`.

**Claude Desktop's session index.** The desktop app keeps a separate per-account/org index at `~/Library/Application Support/Claude/claude-code-sessions/{account}/{org}/local_*.json` — metadata only (title, cwd, model, timestamps), no message content — that it uses for its own session sidebar, linked to the real transcript via a `cliSessionId` field. Deleting a conversation or project through this tool removes the matching index entry too, so nothing is orphaned in the Desktop app. Some entries have no `cliSessionId` at all and are flagged `transcriptUnavailable` — those are real remote/cloud Cowork sessions that ran without ever producing a local `.jsonl` transcript. `scan_all_projects` surfaces these directly (merged into their project's conversation list by matching `cwd`, or as a new project if that `cwd` has no local `~/.claude/projects/` directory at all) so they're actually visible and deletable in the TUI — marked with a `☁` tag and a "turns" count instead of "msgs" (there's no local transcript to open, so the message viewer shows an explanatory placeholder instead). `r` (reconcile) is a separate, narrower cleanup: it only removes index entries whose `cliSessionId` pointed at a transcript that's since been deleted — it correctly leaves the cloud sessions alone since they were never orphaned, just never local. The desktop app also keeps `local-agent-mode-sessions/` (plugin manifests, feature-flag caches) — that's app config, not session data, and isn't touched.

### Cursor

Everything lives in one SQLite DB (`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`). Cursor has changed this schema at least once:

- **Older versions**: the `composerHeaders` table (one row per conversation, with a `workspaceId` column) is authoritative, and message "bubbles" live at `bubbleId:{composerId}:{uuid}` in `cursorDiskKV` (`type` `1` = user, `2` = assistant, plus a `text` field). Workspace → project-folder mapping comes from `~/Library/Application Support/Cursor/User/workspaceStorage/{hash}/workspace.json`.
- **Newer versions** (detected automatically): `composerHeaders` is no longer kept complete — some real conversations exist only in the `composer.composerHeaders` blob under `ItemTable`, which is read as the authoritative list instead. Each entry there embeds the workspace path directly (`workspaceIdentifier.uri.fsPath`), so no separate `workspace.json` lookup is needed for those. Its title (`subtitle` in this schema, replacing the old `name` field) is read from there too. A conversation is considered real (not a discardable empty draft) via its `isDraft` flag, the same signal Cursor's own UI uses, since a conversation can have real content with an empty title or vice versa.
- Message content normally lives at `bubbleId:{composerId}:{uuid}` as plain JSON, and the message viewer reads it from there directly. A bubble with empty `text` and a `toolFormerData` field is a tool call — unlike Claude/Codex/pi.dev, Cursor stores the call *and* its result in the same bubble (`toolFormerData.name`/`.params`/`.result`), rendered the same `[tool call]`/`[tool result]` way. As a **seamless fallback** for the rare case where that comes up empty on a real (non-draft) conversation, `get_bubble_messages` also speaks Cursor's `EncryptedBlobStore` format directly via `cursor_crypt.py` (full writeup there): AES-256-GCM, key = `SHA-256(UTF-8 bytes of blobEncryptionKey-or-speculativeSummarizationEncryptionKey)`, both read fresh from that specific conversation's own `composerData` record — never hardcoded, since every conversation has its own random key. Candidate ciphertext is any binary-typed row under `composer.content.*`; GCM's authentication tag makes trying the wrong key a clean, safe no-op (no false-positive decrypts), so this fallback can't corrupt or misattribute anything. In practice every real conversation we've populated so far kept its messages in the plain `bubbleId:*` store, so this fallback hasn't had a live ciphertext example to decrypt yet — but it's wired in and will fire automatically the moment one exists, with no user action needed. Requires the `cryptography` package (`pip install cryptography`); if it's missing, the fallback silently yields nothing instead of erroring, so Cursor still works without it.
- Workspaces without a saved folder (quick-open windows, `Cmd+N` scratch windows) show as `[orphan] {id}` — this is expected, not a bug; Cursor itself has nowhere to persist a name for them either.

**Agent projects (Background Agents).** Cursor's local agent runs are a separate subsystem (internally namespaced `glass`). A *local agent project* is a folder grouping agent conversations; its index is a JSON array in `ItemTable` under `glass.localAgentProjects.v1`, its member→project map is `glass.localAgentProjectMembership.v1`, and per-member UI state lives under `cursor/glass.tabs.v2/...` and `cursor/glass.editorPanelFullscreen/...`. The bulky content is a content-addressed, heavily-deduplicated blob store: `agentKv:blob:{sha256}` in `cursorDiskKV` (this is what "a number of sessions grouped under *What is 17 × 23?*" was — a test-seeded agent project and its ~68 MB of blobs). Crucially, **some agent members are also real regular chats** (they have their own `bubbleId`/`composerHeaders` data), so deleting an agent project must never touch a member's real conversation. The `g` view lists these projects; `Enter` drills into members (flagged *real chat* vs *agent-only*), and `Enter` again opens the transcript for real-chat members.

**CLI chats (`cursor-agent`, the `c` view).** The CLI has its own storage, entirely separate from the IDE's: `~/.cursor/chats/{md5(cwd)}/{chatId}/` holds `meta.json` (title/timestamps), `prompt_history.json`, and `store.db` — a SQLite `blobs` table forming a content-addressed Merkle DAG. Most blobs are protobuf structural nodes (skipped — they simply fail JSON parsing); the actual `{"role", "content"}` message blobs are plain JSON, and reading them in `rowid` (insertion) order reconstructs a coherent transcript without decoding the DAG. The real cwd for a workspace hash isn't stored as a discrete field anywhere — it's recovered by scanning blobs for an injected `Workspace Path: X` context line. Substantial chats are additionally mirrored as a fully-readable JSONL transcript under `~/.cursor/projects/{slugified-cwd}/agent-transcripts/{chatId}/{chatId}.jsonl` (the same directory that also backs the `g` Agent-projects view) — the message viewer prefers this when present since it's already in order and far simpler to parse; deleting a CLI chat removes both copies.

### Codex CLI

Flat JSONL under `~/.codex/`: `session_index.jsonl` (id/thread_name/updated_at), `history.jsonl` (per-prompt log), and `sessions/YYYY/MM/DD/rollout-*.jsonl` (full event stream per session — `session_meta`/`turn_context` events carry `cwd`; `response_item` events with `type: "message"` carry the actual user/assistant turns, `type: "function_call"`/`"function_call_output"` carry tool invocations and their output, both shown in the message viewer). Sessions may exist in the index without a file, or vice versa — flagged `[index-only]` / `[file-only]`.

### OpenCode

One SQLite database, `~/.local/share/opencode/opencode.db`: `session` rows (id, directory, title, timestamps), `message` rows (one per turn, `data` JSON has `role`), and `part` rows (one per content block, `data` JSON has `type`/`text`/`tool`/`state` — `text` and `tool` parts are both shown in the message viewer, `tool` rendered as its name/input/output). `todo`, `session_input`, `session_context_epoch`, `session_message`, and `session_share` are session-scoped side tables. A parallel diff file lives at `storage/session_diff/{session_id}.json`. Note: `session.project_id` is frequently `"global"` even for sessions that ran in a real project directory, so projects are grouped by `session.directory` instead — the same approach used for Codex's `cwd`. `snapshot/`, `repos/`, and `tool-output/` are shared caches keyed by content hash, not by session, and are intentionally left alone.

### pi.dev

Flat JSONL under `~/.pi/agent/sessions/{encoded-cwd}/{timestamp}_{uuid}.jsonl` — sessions are already grouped one directory per project, unlike Codex/OpenCode's flat layout. Each file's leading `session` event carries the real `cwd` directly (no multi-line scanning needed, unlike Codex). `message` events carry `message.role`/`message.content` (`text` and `toolCall` content blocks are both shown; `thinking` blocks are skipped; a separate `role: "toolResult"` message carries the tool's output). There's no separate index to go stale — deleting a session just removes its `.jsonl` file, and its parent project directory too if that was the last one in it.

## Unified deletion

Every "delete" action in every tool removes **all** artifacts for that item, not just the index entry:

- **Claude Code** — conversation delete removes the `.jsonl`, its `{uuid}/` subdirectory (subagents, tool-results), matching entries in `session-env/`, `file-history/`, `sessions/`, the plan file for that conversation's slug, and its Claude Desktop session-index entry (`claude-code-sessions/.../local_*.json`) if one exists. Project delete does all of that for every conversation plus the `.claude.json` entry. Desktop-only (cloud) sessions, which have no `.jsonl`, delete by simply removing their index entry — same `d`/`Space`+`d` flow as any other conversation. `r` (reconcile) sweeps any pre-existing Desktop index entries left orphaned before this tool covered them.
- **Cursor (IDE)** — conversation delete removes the `composerHeaders` row, all `bubbleId`/`checkpointId` entries, `composerData`, `composerVirtualRowHeights`, and the composer's entry in the `ItemTable` blob. Workspace delete does that for every conversation plus the `workspaceStorage/{hash}/` directory. **Agent-project delete** removes the project's entry from `glass.localAgentProjects.v1`, its members from the membership map, its per-member UI-state keys, and a dangling `selectedAgent` pointer — then garbage-collects the `agentKv` blob store: if no agent projects remain, the whole store is purged; otherwise only blobs unique to the deleted members are swept (a blob shared with a surviving project is kept). Members that are also real chats keep their `bubbleId`/`composerHeaders` data untouched. `r` (reconcile) additionally sweeps pre-existing agent orphans (membership pointing at missing projects, UI-state for unknown members, unreachable blobs).
- **Cursor (CLI)** — chat delete removes the whole `~/.cursor/chats/{hash}/{chatId}/` directory (meta.json, prompt_history.json, store.db) *and* its `agent-transcripts/{chatId}/` mirror if one exists — both are the same session, so removing only one would leave the other as a real orphan. Workspace delete does that for every chat sharing that hash.
- **Codex** — session delete removes the `session_index.jsonl` entry, all matching `history.jsonl` entries, and the session file on disk (plus now-empty parent date directories). Project delete does that for every session sharing that `cwd`.
- **OpenCode** — session delete removes the `part`, `message`, `todo`, `session_input`, `session_context_epoch`, `session_message`, and `session_share` rows for that session, the `session` row itself, and its `storage/session_diff/{id}.json` file. Project delete does that for every session sharing that `directory`.
- **pi.dev** — session delete removes the `.jsonl` file, and the parent project directory too if it was the last session in it. Project delete does that for every session in the directory.

## Safety

- Path containment checks (`common.is_within`) guard all file deletions against path traversal.
- `claude_backend.load_config()` handles a missing `.claude.json` gracefully and raises with context on corrupt JSON.
- Every delete action goes through the shared confirm dialog (`tui_kit.ConfirmMixin`) — nothing is removed without an explicit `y`.
- Cursor's database is queried in read mode until a delete action is confirmed. Deleting an agent project never touches a member's real conversation data — those remain first-class chats.
- **Close Cursor before deleting Cursor data.** The cleaner writes directly to Cursor's live SQLite DB; if Cursor is running it may hold cached state and overwrite the changes (or vice-versa).
- Scan failures log warnings to stderr instead of silently swallowing exceptions.

## Guard Rules: cc-safety-net

Dangerous commands (`git push --force`, `git reset --hard`, `find -delete`, `rm -rf` outside cwd, shell wrappers, interpreter one-liners) are blocked by the [cc-safety-net](https://github.com/kenryu42/claude-code-safety-net) plugin (1.3k stars, active).

Install once, applies to all projects:

```
/plugin marketplace add kenryu42/cc-marketplace
/plugin install safety-net@cc-marketplace
/reload-plugins
```

Custom rules (user-wide, central location): `~/.cc-safety-net/config.json`. Run `npx cc-safety-net doctor` to verify installation.
