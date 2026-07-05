#!/usr/bin/env python3
"""
Import MCP server configurations from Claude Code's settings file
into opencode's global config, replacing the existing mcp section.

Usage:
    python3 import-mcp-from-claude.py                         # import from default source
    python3 import-mcp-from-claude.py ~/custom.json           # custom source file
    python3 import-mcp-from-claude.py --target PATH           # custom target config
    python3 import-mcp-from-claude.py --dry-run               # preview without writing
    python3 import-mcp-from-claude.py --clean-up              # delete all mcp servers
    python3 import-mcp-from-claude.py --clean-up --dry-run    # preview deletion
"""

import json
import os
import sys
import argparse

CLAUDE_DEFAULT = os.path.expanduser("~/.claude.json")


def find_opencode_config():
    config_dir = os.path.expanduser("~/.config/opencode")
    for c in ["opencode.jsonc", "opencode.json", "config.json"]:
        path = os.path.join(config_dir, c)
        if os.path.exists(path):
            return path
    return os.path.join(config_dir, "opencode.jsonc")


def convert_servers(mcp_servers):
    converted = {}
    for name, entry in mcp_servers.items():
        has_command = isinstance(entry.get("command"), str)
        has_url = isinstance(entry.get("url"), str)
        entry_type = entry.get("type")

        result = {"enabled": False}

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


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Import MCP servers from Claude Code settings to opencode",
    )
    parser.add_argument(
        "source", nargs="?", default=None,
        help=f"Claude settings file (default: {CLAUDE_DEFAULT})",
    )
    parser.add_argument(
        "--target", "-t",
        help="Opencode config file (default: auto-detect)",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Preview changes without writing",
    )
    parser.add_argument(
        "--clean-up", action="store_true",
        help="Delete all mcp servers from opencode config (mutually exclusive with source import)",
    )
    args = parser.parse_args()

    source = args.source or CLAUDE_DEFAULT
    target = args.target or find_opencode_config()

    if args.clean_up and args.source:
        print("Error: --clean-up and a source file are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.clean_up:
        if args.dry_run:
            print(f"[DRY RUN] Would remove mcp section from: {target}")
            return

        if not os.path.exists(target):
            print(f"Target not found: {target}")
            return

        cfg = read_json(target)
        if "mcp" not in cfg:
            print("No mcp section found in config.")
            return

        del cfg["mcp"]
        write_json(target, cfg)
        print(f"Removed mcp section from {target}")
        return

    if not os.path.exists(source):
        print(f"Error: source file not found: {source}", file=sys.stderr)
        sys.exit(1)

    claude_cfg = read_json(source)
    mcp_servers = claude_cfg.get("mcpServers", {})
    if not mcp_servers:
        print("No mcpServers found in source file.")
        return

    converted = convert_servers(mcp_servers)

    if not converted:
        print("No MCP servers could be converted.")
        return

    if args.dry_run:
        print(f"[DRY RUN] Would update: {target}")
        print()
        print(json.dumps({"mcp": converted}, indent=2))
        return

    opencode_cfg = {}
    if os.path.exists(target):
        opencode_cfg = read_json(target)

    opencode_cfg["mcp"] = converted
    write_json(target, opencode_cfg)

    print(f"Imported {len(converted)} MCP server(s) to {target}")
    print("All servers set to enabled: false. Use opencode mcp or edit the config to enable.")


if __name__ == "__main__":
    main()
