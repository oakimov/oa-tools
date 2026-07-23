#!/usr/bin/env python3
"""
Import MCP server configurations from Claude Code's settings into installed
product configs (opencode, mimo, kilo, cursor, codex, claude-desktop).

Only **missing** server names are added. Existing definitions are left unchanged.
Newly added servers default to **disabled**; pass ``--enabled`` to add them enabled
(Codex CLI + ChatGPT desktop GUI share ``~/.codex/config.toml``).

Usage:
    python3 import-mcp-from-claude.py                         # all installed targets
    python3 import-mcp-from-claude.py ~/custom.json           # custom Claude source
    python3 import-mcp-from-claude.py --target mimo,codex     # filter products
    python3 import-mcp-from-claude.py --target claude-desktop
    python3 import-mcp-from-claude.py --enabled               # add servers enabled
    python3 import-mcp-from-claude.py --disabled              # explicit default
    python3 import-mcp-from-claude.py --dry-run               # preview without writing
    python3 import-mcp-from-claude.py --clean-up              # remove MCP from targets
    python3 import-mcp-from-claude.py --clean-up --dry-run    # preview deletion
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tomllib
from typing import Any

CLAUDE_DEFAULT = os.path.expanduser("~/.claude.json")

PRODUCT_IDS = ("opencode", "mimo", "kilo", "cursor", "codex", "claude-desktop")

OPENCODE_FAMILY: dict[str, dict[str, Any]] = {
    "opencode": {
        "dir": "~/.config/opencode",
        "files": ["opencode.jsonc", "opencode.json", "config.json"],
    },
    "mimo": {
        "dir": "~/.config/mimocode",
        "files": ["mimocode.jsonc", "mimocode.json", "config.json"],
    },
    "kilo": {
        "dir": "~/.config/kilo",
        "files": [
            "kilo.jsonc",
            "kilo.json",
            "opencode.jsonc",
            "opencode.json",
            "config.json",
        ],
    },
}

CURSOR_DIR = "~/.cursor"
CURSOR_MCP_FILE = "mcp.json"
CURSOR_VSCDB_DEFAULT = os.path.expanduser(
    "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
)
CURSOR_DISABLED_KEY = "cursor/disabledGlobalMcpServers"

CODEX_DIR = "~/.codex"
CODEX_CONFIG = "config.toml"

CLAUDE_DESKTOP_CONFIG_FILE = "claude_desktop_config.json"


def claude_desktop_dir() -> str:
    """Claude Desktop app support dir (macOS / Windows)."""
    override = os.environ.get("CLAUDE_DESKTOP_DIR")
    if override:
        return expand(override)
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "Claude")
    return expand("~/Library/Application Support/Claude")


def claude_desktop_config_path() -> str:
    return os.path.join(claude_desktop_dir(), CLAUDE_DESKTOP_CONFIG_FILE)


def expand(path: str) -> str:
    return os.path.expanduser(path)


def resolve_config_path(config_dir: str, files: list[str]) -> str:
    for name in files:
        path = os.path.join(config_dir, name)
        if os.path.exists(path):
            return path
    return os.path.join(config_dir, files[0])


def parse_target_filter(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    ids = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not ids:
        return None
    unknown = [i for i in ids if i not in PRODUCT_IDS]
    if unknown:
        raise SystemExit(
            f"Error: unknown --target id(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(PRODUCT_IDS)}"
        )
    # preserve order, unique
    seen: set[str] = set()
    ordered: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    return ordered


def detect_targets(filter_ids: list[str] | None) -> list[str]:
    wanted = filter_ids if filter_ids is not None else list(PRODUCT_IDS)
    found: list[str] = []
    for product_id in wanted:
        if product_id in OPENCODE_FAMILY:
            d = expand(OPENCODE_FAMILY[product_id]["dir"])
            if os.path.isdir(d):
                found.append(product_id)
        elif product_id == "cursor":
            if os.path.isdir(expand(CURSOR_DIR)):
                found.append(product_id)
        elif product_id == "codex":
            if os.path.isdir(expand(CODEX_DIR)):
                found.append(product_id)
        elif product_id == "claude-desktop":
            if os.path.isdir(claude_desktop_dir()):
                found.append(product_id)
    return found


def read_json(path: str) -> dict[str, Any]:
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def convert_opencode_family(
    mcp_servers: dict[str, Any], *, enabled: bool = False
) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for name, entry in mcp_servers.items():
        if not isinstance(entry, dict):
            print(f"  skipping '{name}' — expected object", file=sys.stderr)
            continue
        has_command = isinstance(entry.get("command"), str)
        has_url = isinstance(entry.get("url"), str)
        entry_type = entry.get("type")

        result: dict[str, Any] = {"enabled": enabled}

        if has_command:
            command = [entry["command"]]
            if isinstance(entry.get("args"), list):
                command.extend(entry["args"])
            result["type"] = "local"
            result["command"] = command
            if isinstance(entry.get("env"), dict) and entry["env"]:
                result["environment"] = entry["env"]
        elif has_url or entry_type in ("http", "sse", "remote"):
            result["type"] = "remote"
            if has_url:
                result["url"] = entry["url"]
            if isinstance(entry.get("headers"), dict) and entry["headers"]:
                result["headers"] = entry["headers"]
        else:
            print(f"  skipping '{name}' — cannot determine server type", file=sys.stderr)
            continue

        converted[name] = result
    return converted


def convert_cursor(mcp_servers: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for name, entry in mcp_servers.items():
        if not isinstance(entry, dict):
            print(f"  skipping '{name}' — expected object", file=sys.stderr)
            continue
        has_command = isinstance(entry.get("command"), str)
        has_url = isinstance(entry.get("url"), str)
        entry_type = entry.get("type")

        result: dict[str, Any] = {}

        if has_command:
            result["command"] = entry["command"]
            if isinstance(entry.get("args"), list) and entry["args"]:
                result["args"] = entry["args"]
            if isinstance(entry.get("env"), dict) and entry["env"]:
                result["env"] = entry["env"]
        elif has_url or entry_type in ("http", "sse", "remote"):
            if has_url:
                result["url"] = entry["url"]
            if isinstance(entry_type, str) and entry_type in ("http", "sse"):
                result["type"] = entry_type
            elif has_url:
                result["type"] = "http"
            if isinstance(entry.get("headers"), dict) and entry["headers"]:
                result["headers"] = entry["headers"]
        else:
            print(f"  skipping '{name}' — cannot determine server type", file=sys.stderr)
            continue

        converted[name] = result
    return converted


def convert_claude_desktop(
    mcp_servers: dict[str, Any], *, enabled: bool = False
) -> dict[str, Any]:
    """Claude Desktop uses Claude-shaped mcpServers in claude_desktop_config.json."""
    converted = convert_cursor(mcp_servers)
    for entry in converted.values():
        # Claude Code/Desktop convention: per-server "disabled" flag.
        entry["disabled"] = not enabled
    return converted


def convert_codex(
    mcp_servers: dict[str, Any], *, enabled: bool = False
) -> dict[str, dict[str, Any]]:
    converted: dict[str, dict[str, Any]] = {}
    for name, entry in mcp_servers.items():
        if not isinstance(entry, dict):
            print(f"  skipping '{name}' — expected object", file=sys.stderr)
            continue
        has_command = isinstance(entry.get("command"), str)
        has_url = isinstance(entry.get("url"), str)
        entry_type = entry.get("type")

        # Codex CLI + ChatGPT desktop GUI share ~/.codex/config.toml.
        result: dict[str, Any] = {"enabled": enabled}

        if has_command:
            result["command"] = entry["command"]
            if isinstance(entry.get("args"), list):
                result["args"] = entry["args"]
            elif "args" not in entry:
                result["args"] = []
            if isinstance(entry.get("env"), dict) and entry["env"]:
                # only string values for TOML env table
                env = {
                    str(k): str(v)
                    for k, v in entry["env"].items()
                    if isinstance(k, str) and isinstance(v, (str, int, float, bool))
                }
                if env:
                    result["env"] = env
        elif has_url or entry_type in ("http", "sse", "remote"):
            if has_url:
                result["url"] = entry["url"]
            bearer = entry.get("bearer_token_env_var") or entry.get("bearerTokenEnvVar")
            if isinstance(bearer, str) and bearer:
                result["bearer_token_env_var"] = bearer
            headers = entry.get("headers")
            if isinstance(headers, dict) and headers and "bearer_token_env_var" not in result:
                # Prefer header *names* that look like env vars (e.g. CONTEXT7_API_KEY)
                envish = [
                    str(k)
                    for k in headers
                    if isinstance(k, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", k)
                ]
                if len(envish) == 1:
                    result["bearer_token_env_var"] = envish[0]
                elif headers:
                    print(
                        f"  note: '{name}' has headers; Codex uses bearer_token_env_var — "
                        "could not infer a single env var name",
                        file=sys.stderr,
                    )
        else:
            print(f"  skipping '{name}' — cannot determine server type", file=sys.stderr)
            continue

        converted[name] = result
    return converted


def cursor_disable_id(name: str) -> str:
    return f"user-{name}"


def cursor_vscdb_path() -> str:
    return os.environ.get("CURSOR_STATE_VSCDB") or CURSOR_VSCDB_DEFAULT


def read_cursor_disabled(conn: sqlite3.Connection) -> list[str]:
    row = conn.execute(
        "SELECT value FROM ItemTable WHERE key = ?",
        (CURSOR_DISABLED_KEY,),
    ).fetchone()
    if not row or row[0] is None:
        return []
    raw = row[0]
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


def write_cursor_disabled(conn: sqlite3.Connection, ids: list[str]) -> None:
    payload = json.dumps(ids, separators=(",", ":"))
    exists = conn.execute(
        "SELECT 1 FROM ItemTable WHERE key = ?",
        (CURSOR_DISABLED_KEY,),
    ).fetchone()
    if exists:
        conn.execute(
            "UPDATE ItemTable SET value = ? WHERE key = ?",
            (payload, CURSOR_DISABLED_KEY),
        )
    else:
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            (CURSOR_DISABLED_KEY, payload),
        )
    conn.commit()


def toml_escape_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toml_format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return toml_escape_string(value)
    if isinstance(value, list):
        return "[ " + ", ".join(toml_format_value(v) for v in value) + " ]"
    raise TypeError(f"unsupported TOML value type: {type(value)}")


def toml_table_key(name: str) -> str:
    # bare keys when safe; otherwise quote
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return name
    return toml_escape_string(name)


def serialize_codex_mcp(servers: dict[str, dict[str, Any]]) -> str:
    chunks: list[str] = []
    for name, entry in servers.items():
        key = toml_table_key(name)
        lines = [f"[mcp_servers.{key}]"]
        # stable-ish order: enabled, command/args/url, then other scalars
        if "enabled" in entry:
            lines.append(f"enabled = {toml_format_value(entry['enabled'])}")
        for field in ("command", "args", "url", "bearer_token_env_var", "cwd"):
            if field in entry and field != "env":
                lines.append(f"{field} = {toml_format_value(entry[field])}")
        for field, value in entry.items():
            if field in ("enabled", "command", "args", "url", "bearer_token_env_var", "cwd", "env"):
                continue
            if isinstance(value, (str, bool, int, float, list)):
                lines.append(f"{field} = {toml_format_value(value)}")
        chunks.append("\n".join(lines) + "\n")
        env = entry.get("env")
        if isinstance(env, dict) and env:
            env_lines = [f"[mcp_servers.{key}.env]"]
            for ek, ev in env.items():
                env_lines.append(f"{toml_table_key(str(ek))} = {toml_format_value(str(ev))}")
            chunks.append("\n".join(env_lines) + "\n")
    return "\n".join(chunks).rstrip() + ("\n" if chunks else "")


def strip_codex_mcp_sections(text: str) -> str:
    """Remove all [mcp_servers.*] tables (including nested .env) from TOML text."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1]
            if inner.startswith("mcp_servers."):
                skipping = True
                continue
            skipping = False
            out.append(line)
            continue
        if not skipping:
            out.append(line)
    result = "".join(out)
    # collapse excessive blank lines at end / between sections
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.rstrip() + ("\n" if result.strip() else "")


def apply_codex_mcp(text: str, servers: dict[str, dict[str, Any]] | None) -> str:
    """Replace all mcp_servers tables (used by --clean-up and full rewrite tests)."""
    base = strip_codex_mcp_sections(text)
    if not servers:
        return base if base.endswith("\n") or base == "" else base + "\n"
    block = serialize_codex_mcp(servers)
    if base.strip():
        return base.rstrip() + "\n\n" + block
    return block


def append_codex_mcp(text: str, servers: dict[str, dict[str, Any]]) -> str:
    """Append mcp_servers tables without removing existing ones."""
    if not servers:
        return text if text.endswith("\n") or text == "" else text + "\n"
    block = serialize_codex_mcp(servers)
    if text.strip():
        return text.rstrip() + "\n\n" + block
    return block


def partition_by_existing(
    incoming: dict[str, Any],
    existing_names: set[str] | list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Return (to_add, skipped_names) — skip keys already present."""
    existing = set(existing_names)
    to_add = {k: v for k, v in incoming.items() if k not in existing}
    skipped = [k for k in incoming if k in existing]
    return to_add, skipped


def format_name_list(names: list[str], *, limit: int = 12) -> str:
    if not names:
        return "(none)"
    shown = names[:limit]
    text = ", ".join(shown)
    if len(names) > limit:
        text += f", … (+{len(names) - limit} more)"
    return text


def report_add_skip(product_id: str, added: list[str], skipped: list[str], *, dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(
        f"{prefix}[{product_id}] add {len(added)}: {format_name_list(added)} | "
        f"skip existing {len(skipped)}: {format_name_list(skipped)}"
    )


def apply_opencode_family(
    product_id: str,
    servers: dict[str, Any] | None,
    *,
    dry_run: bool,
    clean_up: bool,
) -> None:
    meta = OPENCODE_FAMILY[product_id]
    config_dir = expand(meta["dir"])
    path = resolve_config_path(config_dir, meta["files"])

    if clean_up:
        if dry_run:
            print(f"[DRY RUN] [{product_id}] Would remove mcp section from: {path}")
            return
        if not os.path.exists(path):
            print(f"[{product_id}] Target not found: {path}")
            return
        cfg = read_json(path)
        if "mcp" not in cfg:
            print(f"[{product_id}] No mcp section found in {path}")
            return
        del cfg["mcp"]
        write_json(path, cfg)
        print(f"[{product_id}] Removed mcp section from {path}")
        return

    assert servers is not None
    cfg: dict[str, Any] = {}
    if os.path.exists(path):
        cfg = read_json(path)
    existing_mcp = cfg.get("mcp") if isinstance(cfg.get("mcp"), dict) else {}
    to_add, skipped = partition_by_existing(servers, existing_mcp.keys())
    report_add_skip(product_id, list(to_add.keys()), skipped, dry_run=dry_run)

    if dry_run:
        print(f"[DRY RUN] [{product_id}] Would update: {path}")
        if to_add:
            print(json.dumps({"mcp_add": to_add}, indent=2))
        print()
        return

    if not to_add:
        print(f"[{product_id}] Nothing new to add in {path}")
        return

    merged = dict(existing_mcp)
    merged.update(to_add)
    cfg["mcp"] = merged
    write_json(path, cfg)
    print(f"[{product_id}] Added {len(to_add)} MCP server(s) to {path}")


def apply_cursor(
    servers: dict[str, Any] | None,
    *,
    dry_run: bool,
    clean_up: bool,
    enabled: bool = False,
) -> None:
    path = os.path.join(expand(CURSOR_DIR), CURSOR_MCP_FILE)
    vscdb = cursor_vscdb_path()

    if clean_up:
        existing_names: list[str] = []
        if os.path.exists(path):
            try:
                cfg = read_json(path)
                ms = cfg.get("mcpServers") or {}
                if isinstance(ms, dict):
                    existing_names = list(ms.keys())
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"[cursor] Warning: could not read {path}: {exc}", file=sys.stderr)

        remove_ids = {cursor_disable_id(n) for n in existing_names}
        if dry_run:
            print(f"[DRY RUN] [cursor] Would clear mcpServers in: {path}")
            print(
                f"[DRY RUN] [cursor] Would remove from {CURSOR_DISABLED_KEY}: "
                f"{sorted(remove_ids)}"
            )
            return

        if os.path.exists(path):
            cfg = read_json(path)
            cfg["mcpServers"] = {}
            write_json(path, cfg)
            print(f"[cursor] Cleared mcpServers in {path}")
        else:
            print(f"[cursor] Target not found: {path}")

        if os.path.exists(vscdb) and remove_ids:
            try:
                with sqlite3.connect(vscdb) as conn:
                    current = read_cursor_disabled(conn)
                    updated = [x for x in current if x not in remove_ids]
                    write_cursor_disabled(conn, updated)
                print(
                    f"[cursor] Updated {CURSOR_DISABLED_KEY} in {vscdb} "
                    f"(removed {len(remove_ids)} id(s))"
                )
            except sqlite3.Error as exc:
                print(f"[cursor] Error updating vscdb: {exc}", file=sys.stderr)
        elif not os.path.exists(vscdb):
            print(f"[cursor] Warning: vscdb not found ({vscdb}); skipped disable cleanup")
        return

    assert servers is not None
    cfg: dict[str, Any] = {}
    if os.path.exists(path):
        cfg = read_json(path)
    existing_ms = cfg.get("mcpServers") if isinstance(cfg.get("mcpServers"), dict) else {}
    to_add, skipped = partition_by_existing(servers, existing_ms.keys())
    report_add_skip("cursor", list(to_add.keys()), skipped, dry_run=dry_run)
    # Cursor enable/disable is tracked in state.vscdb, not mcp.json.
    disable_ids = [] if enabled else [cursor_disable_id(n) for n in to_add]

    if dry_run:
        print(f"[DRY RUN] [cursor] Would update: {path}")
        if to_add:
            print(json.dumps({"mcpServers_add": to_add}, indent=2))
        print()
        if enabled:
            print("[DRY RUN] [cursor] Servers would be left enabled (no new disable ids)")
            print()
            return
        if not disable_ids:
            print("[DRY RUN] [cursor] No new disable ids to add")
            print()
            return
        planned = disable_ids
        if os.path.exists(vscdb):
            try:
                with sqlite3.connect(f"file:{vscdb}?mode=ro", uri=True) as conn:
                    current = read_cursor_disabled(conn)
                planned = list(dict.fromkeys([*current, *disable_ids]))
            except sqlite3.Error as exc:
                print(f"[DRY RUN] [cursor] Warning: could not read vscdb: {exc}", file=sys.stderr)
        else:
            print(f"[DRY RUN] [cursor] Warning: vscdb not found ({vscdb})")
        print(f"[DRY RUN] [cursor] Would set {CURSOR_DISABLED_KEY} = {planned}")
        print()
        return

    if to_add:
        merged = dict(existing_ms)
        merged.update(to_add)
        cfg["mcpServers"] = merged
        write_json(path, cfg)
        print(f"[cursor] Added {len(to_add)} MCP server(s) to {path}")
    else:
        print(f"[cursor] Nothing new to add in {path}")

    if enabled or not disable_ids:
        return

    if not os.path.exists(vscdb):
        print(
            f"[cursor] Warning: vscdb not found ({vscdb}); "
            "mcp.json written but IDE disabled list not updated",
            file=sys.stderr,
        )
        return

    try:
        with sqlite3.connect(vscdb) as conn:
            current = read_cursor_disabled(conn)
            updated = list(dict.fromkeys([*current, *disable_ids]))
            write_cursor_disabled(conn, updated)
        print(f"[cursor] Updated {CURSOR_DISABLED_KEY} ({len(disable_ids)} new id(s))")
    except sqlite3.Error as exc:
        print(f"[cursor] Error updating vscdb: {exc}", file=sys.stderr)


def apply_claude_desktop(
    servers: dict[str, Any] | None,
    *,
    dry_run: bool,
    clean_up: bool,
) -> None:
    path = claude_desktop_config_path()

    if clean_up:
        if dry_run:
            print(f"[DRY RUN] [claude-desktop] Would clear mcpServers in: {path}")
            return
        if not os.path.exists(path):
            print(f"[claude-desktop] Target not found: {path}")
            return
        cfg = read_json(path)
        cfg["mcpServers"] = {}
        write_json(path, cfg)
        print(f"[claude-desktop] Cleared mcpServers in {path}")
        return

    assert servers is not None
    cfg: dict[str, Any] = {}
    if os.path.exists(path):
        cfg = read_json(path)
    existing_ms = cfg.get("mcpServers") if isinstance(cfg.get("mcpServers"), dict) else {}
    to_add, skipped = partition_by_existing(servers, existing_ms.keys())
    report_add_skip("claude-desktop", list(to_add.keys()), skipped, dry_run=dry_run)

    if dry_run:
        print(f"[DRY RUN] [claude-desktop] Would update: {path}")
        if to_add:
            print(json.dumps({"mcpServers_add": to_add}, indent=2))
        print()
        return

    if not to_add:
        print(f"[claude-desktop] Nothing new to add in {path}")
        return

    merged = dict(existing_ms)
    merged.update(to_add)
    cfg["mcpServers"] = merged
    write_json(path, cfg)
    print(f"[claude-desktop] Added {len(to_add)} MCP server(s) to {path}")


def apply_codex(
    servers: dict[str, dict[str, Any]] | None,
    *,
    dry_run: bool,
    clean_up: bool,
) -> None:
    path = os.path.join(expand(CODEX_DIR), CODEX_CONFIG)
    existing = ""
    parsed: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()
        try:
            parsed = tomllib.loads(existing)
        except tomllib.TOMLDecodeError as exc:
            print(f"[codex] Error: invalid TOML in {path}: {exc}", file=sys.stderr)
            return

    if clean_up:
        new_text = apply_codex_mcp(existing, None)
        if dry_run:
            print(f"[DRY RUN] [codex] Would strip mcp_servers from: {path}")
            return
        if not os.path.exists(path):
            print(f"[codex] Target not found: {path}")
            return
        with open(path, "w") as f:
            f.write(new_text)
        print(f"[codex] Removed mcp_servers tables from {path}")
        return

    assert servers is not None
    existing_names = set((parsed.get("mcp_servers") or {}).keys()) if isinstance(
        parsed.get("mcp_servers"), dict
    ) else set()
    to_add, skipped = partition_by_existing(servers, existing_names)
    report_add_skip("codex", list(to_add.keys()), skipped, dry_run=dry_run)

    if dry_run:
        print(f"[DRY RUN] [codex] Would update: {path}")
        if to_add:
            print(serialize_codex_mcp(to_add))
        print()
        return

    if not to_add:
        print(f"[codex] Nothing new to add in {path}")
        return

    new_text = append_codex_mcp(existing, to_add)
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        print(f"[codex] Error: generated invalid TOML: {exc}", file=sys.stderr)
        return

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(new_text)
    print(f"[codex] Added {len(to_add)} MCP server(s) to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import MCP servers from Claude Code settings into installed product "
            "configs (opencode, mimo, kilo, cursor, codex). "
            "Only missing names are added; existing definitions are kept. "
            "Newly added servers are disabled by default; use --enabled to enable."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help=f"Claude settings file (default: {CLAUDE_DEFAULT})",
    )
    parser.add_argument(
        "--target",
        "-t",
        help=(
            "Comma-separated product ids to sync "
            f"({', '.join(PRODUCT_IDS)}). Default: all installed"
        ),
    )
    enable_group = parser.add_mutually_exclusive_group()
    enable_group.add_argument(
        "--enabled",
        dest="servers_enabled",
        action="store_true",
        help="Add new MCP servers as enabled",
    )
    enable_group.add_argument(
        "--disabled",
        dest="servers_enabled",
        action="store_false",
        help="Add new MCP servers as disabled (default)",
    )
    parser.set_defaults(servers_enabled=False)
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview changes without writing",
    )
    parser.add_argument(
        "--clean-up",
        action="store_true",
        help="Delete MCP server config from selected targets",
    )
    args = parser.parse_args()

    if args.clean_up and args.source:
        print("Error: --clean-up and a source file are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    try:
        filter_ids = parse_target_filter(args.target)
    except SystemExit:
        raise

    targets = detect_targets(filter_ids)
    if not targets:
        dirs = {
            "opencode": expand("~/.config/opencode"),
            "mimo": expand("~/.config/mimocode"),
            "kilo": expand("~/.config/kilo"),
            "cursor": expand(CURSOR_DIR),
            "codex": expand(CODEX_DIR),
            "claude-desktop": claude_desktop_dir(),
        }
        scope = filter_ids or list(PRODUCT_IDS)
        print("Error: no installed targets detected among:", file=sys.stderr)
        for pid in scope:
            print(f"  {pid}: {dirs[pid]}", file=sys.stderr)
        sys.exit(1)

    if args.clean_up:
        print(f"Targets: {', '.join(targets)}")
        for product_id in targets:
            if product_id in OPENCODE_FAMILY:
                apply_opencode_family(product_id, None, dry_run=args.dry_run, clean_up=True)
            elif product_id == "cursor":
                apply_cursor(None, dry_run=args.dry_run, clean_up=True)
            elif product_id == "codex":
                apply_codex(None, dry_run=args.dry_run, clean_up=True)
            elif product_id == "claude-desktop":
                apply_claude_desktop(None, dry_run=args.dry_run, clean_up=True)
        return

    source = args.source or CLAUDE_DEFAULT
    if not os.path.exists(source):
        print(f"Error: source file not found: {source}", file=sys.stderr)
        sys.exit(1)

    claude_cfg = read_json(source)
    mcp_servers = claude_cfg.get("mcpServers", {})
    if not isinstance(mcp_servers, dict) or not mcp_servers:
        print("No mcpServers found in source file.")
        return

    need_family = any(t in OPENCODE_FAMILY for t in targets)
    need_cursor = "cursor" in targets
    need_codex = "codex" in targets
    need_claude_desktop = "claude-desktop" in targets
    servers_enabled = bool(args.servers_enabled)

    family = (
        convert_opencode_family(mcp_servers, enabled=servers_enabled) if need_family else {}
    )
    cursor_servers = convert_cursor(mcp_servers) if need_cursor else {}
    codex_servers = (
        convert_codex(mcp_servers, enabled=servers_enabled) if need_codex else {}
    )
    claude_desktop_servers = (
        convert_claude_desktop(mcp_servers, enabled=servers_enabled)
        if need_claude_desktop
        else {}
    )

    if (
        (need_family and not family)
        and (not need_cursor or not cursor_servers)
        and (not need_codex or not codex_servers)
        and (not need_claude_desktop or not claude_desktop_servers)
    ):
        print("No MCP servers could be converted.")
        return

    state = "enabled" if servers_enabled else "disabled"
    print(f"Targets: {', '.join(targets)} (new servers: {state})")

    for product_id in targets:
        if product_id in OPENCODE_FAMILY:
            if not family:
                print(f"[{product_id}] skipped — nothing converted for OpenCode family")
                continue
            apply_opencode_family(
                product_id, family, dry_run=args.dry_run, clean_up=False
            )
        elif product_id == "cursor":
            if not cursor_servers:
                print("[cursor] skipped — nothing converted")
                continue
            apply_cursor(
                cursor_servers,
                dry_run=args.dry_run,
                clean_up=False,
                enabled=servers_enabled,
            )
        elif product_id == "codex":
            if not codex_servers:
                print("[codex] skipped — nothing converted")
                continue
            apply_codex(codex_servers, dry_run=args.dry_run, clean_up=False)
        elif product_id == "claude-desktop":
            if not claude_desktop_servers:
                print("[claude-desktop] skipped — nothing converted")
                continue
            apply_claude_desktop(
                claude_desktop_servers, dry_run=args.dry_run, clean_up=False
            )

    if not args.dry_run:
        print(f"Done. Newly added servers were written as {state}.")


if __name__ == "__main__":
    main()