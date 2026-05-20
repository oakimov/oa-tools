#!/usr/bin/env python3
"""Manage MCP server configuration across projects in .claude.json."""

import argparse
import json
import os
import sys

from claude_shared import (
    PLAN_APPROVED,
    PLAN_CANCELLED,
    PLAN_PENDING,
    CleanerTUI,
    delete_plan,
    delete_project_unified,
    format_timestamp_short,
    get_global_mcp_servers,
    get_project_paths,
    is_project_key,
    load_config,
    save_config,
    scan_all_plans,
)


def cmd_list(data, args):
    for path in get_project_paths(data):
        print(path)


def cmd_delete(data, args):
    project_path = args.project_path
    projects = data.setdefault("projects", {})
    if project_path not in projects or not is_project_key(project_path):
        print(f"Project not found: {project_path}")
        sys.exit(1)

    result = delete_project_unified(project_path)
    if result["config_deleted"]:
        print(f"Deleted config entry: {project_path}")
    else:
        print(f"Config entry not found: {project_path}")

    fs = result["filesystem_removed"]
    if fs:
        print(f"Removed {len(fs)} dirs/files from filesystem")
    else:
        print("No filesystem data found")


GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def _format_server_list(servers, local_set):
    """Color-code servers: green=local, cyan=global."""
    parts = []
    for s in servers:
        if s in local_set:
            parts.append(f"{GREEN}{s}{RESET}")
        else:
            parts.append(f"{CYAN}{s}{RESET}")
    return ", ".join(parts) if parts else "(none)"


def cmd_show_enabled(data, args):
    global_servers = set(get_global_mcp_servers(data))
    for path in get_project_paths(data):
        project = data["projects"][path]
        local_servers = set(project.get("mcpServers", {}).keys())
        disabled = set(project.get("disabledMcpServers", []))
        enabled = sorted((global_servers | local_servers) - disabled)

        if args.verbose:
            mcp = project.get("mcpServers", {})
            print(f"{path}:")
            print(f"  enabled:   {_format_server_list(enabled, local_servers) or '(none)'}")
            print(f"  disabled:  {DIM}{', '.join(sorted(disabled)) or '(none)'}{RESET}")
            if mcp:
                print(f"  local config: {json.dumps(mcp, indent=4)}")
        else:
            if enabled:
                print(f"{path}: [{_format_server_list(enabled, local_servers)}]")
            else:
                print(f"{path}: []")


def cmd_clean(data, args):
    projects = data.setdefault("projects", {})
    if args.project_path in projects and is_project_key(args.project_path):
        project = projects[args.project_path]
        project["mcpServers"] = {}
        project["disabledMcpServers"] = []
        save_config(data)
        print(f"Cleaned project: {args.project_path}")
    else:
        print(f"Project not found: {args.project_path}")
        sys.exit(1)


def cmd_disable_all(data, args):
    global_servers = get_global_mcp_servers(data)
    projects = data.setdefault("projects", {})
    count = 0
    for path in get_project_paths(data):
        projects[path]["disabledMcpServers"] = list(global_servers)
        count += 1
    save_config(data)
    print(f"Disabled all MCP servers for {count} projects")


def cmd_disable(data, args):
    global_servers = set(get_global_mcp_servers(data))
    projects = data.setdefault("projects", {})
    if args.project_path in projects and is_project_key(args.project_path):
        project = projects[args.project_path]
        local_servers = set(project.get("mcpServers", {}).keys())
        disabled = sorted(global_servers | local_servers)
        project["disabledMcpServers"] = disabled
        save_config(data)
        print(f"Disabled MCP servers for: {args.project_path}")
    else:
        print(f"Project not found: {args.project_path}")
        sys.exit(1)


def cmd_clean_plans(data, args):
    plans = scan_all_plans()
    if not plans:
        print("No plans found.")
        return

    removable = [p for p in plans if p.status in (PLAN_APPROVED, PLAN_CANCELLED)]
    keep = [p for p in plans if p.status == PLAN_PENDING]

    if removable:
        print("Plans that can be removed:\n")
        for p in removable:
            ts = format_timestamp_short(p.timestamp)
            has_file = "file" if p.plan_paths else "no file"
            print(f"  [{p.status:>9s}]  {p.slug:<40s}  {p.project_display:<30s}  {ts}  {has_file}")
        print()

    if keep:
        print("Plans to keep (pending):\n")
        for p in keep:
            ts = format_timestamp_short(p.timestamp)
            has_file = "file" if p.plan_paths else "no file"
            print(f"  [{p.status:>9s}]  {p.slug:<40s}  {p.project_display:<30s}  {ts}  {has_file}")
        print()

    if not removable:
        print("No removable plans found.")
        return

    with_files = [p for p in removable if p.plan_paths]
    if not with_files:
        print("Removable plans have no files on disk.")
        return

    answer = input(f"Remove {len(with_files)} plan(s)? [y/N] ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return

    total = 0
    for p in with_files:
        removed = delete_plan(p)
        total += len(removed)
        for path in removed:
            print(f"  Deleted: {path}")
    print(f"Removed {total} plan file(s).")


def cmd_tui(data, args):
    CleanerTUI().run()


def main():
    parser = argparse.ArgumentParser(
        description="Manage MCP server configuration in .claude.json"
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List all projects")
    p_list.set_defaults(func=cmd_list)

    p_delete = sub.add_parser("delete", help="Delete a project (config + filesystem)")
    p_delete.add_argument("project_path", help="Full project path")
    p_delete.set_defaults(func=cmd_delete)

    p_show = sub.add_parser(
        "show-enabled", help="Show non-disabled servers per project"
    )
    p_show.add_argument("-v", "--verbose", action="store_true",
                        help="Show local config and disabled servers")
    p_show.set_defaults(func=cmd_show_enabled)

    p_clean = sub.add_parser(
        "clean", help="Reset mcpServers and disabledMcpServers for a project"
    )
    p_clean.add_argument("project_path", help="Full project path")
    p_clean.set_defaults(func=cmd_clean)

    p_da = sub.add_parser(
        "disable-all", help="Disable all MCP servers for all projects"
    )
    p_da.set_defaults(func=cmd_disable_all)

    p_d = sub.add_parser(
        "disable", help="Disable all MCP servers for a specific project"
    )
    p_d.add_argument("project_path", help="Full project path")
    p_d.set_defaults(func=cmd_disable)

    p_tui = sub.add_parser("tui", help="Launch interactive TUI")
    p_tui.set_defaults(func=cmd_tui)

    p_plans = sub.add_parser(
        "clean-plans", help="Remove approved and cancelled plan files"
    )
    p_plans.set_defaults(func=cmd_clean_plans)

    args = parser.parse_args()
    data = load_config()
    if args.command is None:
        args.verbose = False
        cmd_show_enabled(data, args)
    else:
        args.func(data, args)


if __name__ == "__main__":
    main()
