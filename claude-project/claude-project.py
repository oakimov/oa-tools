#!/usr/bin/env python3
"""Manage MCP server configuration across projects in .claude.json."""

import argparse
import json
import sys

CONFIG_PATH = "/Users/mitra/.claude.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def is_project_key(key):
    return key.startswith("/")


def get_projects(data):
    return {k: v for k, v in data.get("projects", {}).items() if is_project_key(k)}


def get_project_paths(data):
    return sorted(get_projects(data).keys())


def get_global_mcp_servers(data):
    return sorted(data.get("mcpServers", {}).keys())


def cmd_list(data, args):
    for path in get_project_paths(data):
        print(path)


def cmd_delete(data, args):
    projects = data.setdefault("projects", {})
    if args.project_path in projects and is_project_key(args.project_path):
        del projects[args.project_path]
        save_config(data)
        print(f"Deleted project: {args.project_path}")
    else:
        print(f"Project not found: {args.project_path}")
        sys.exit(1)


def cmd_check(data, args):
    for path in get_project_paths(data):
        project = data["projects"][path]
        mcp = project.get("mcpServers", {})
        print(f"{path}: {json.dumps(mcp)}")


def cmd_show_enabled(data, args):
    global_servers = set(get_global_mcp_servers(data))
    for path in get_project_paths(data):
        project = data["projects"][path]
        local_servers = set(project.get("mcpServers", {}).keys())
        disabled = set(project.get("disabledMcpServers", []))
        enabled = sorted((global_servers | local_servers) - disabled)
        print(f"{path}: {json.dumps(enabled)}")


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


def main():
    parser = argparse.ArgumentParser(
        description="Manage MCP server configuration in .claude.json"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List all projects")
    p_list.set_defaults(func=cmd_list)

    p_delete = sub.add_parser("delete", help="Delete a project entry")
    p_delete.add_argument("project_path", help="Full project path")
    p_delete.set_defaults(func=cmd_delete)

    p_check = sub.add_parser("check", help="Show local mcpServers per project")
    p_check.set_defaults(func=cmd_check)

    p_show = sub.add_parser(
        "show-enabled", help="Show non-disabled servers per project"
    )
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

    args = parser.parse_args()
    data = load_config()
    args.func(data, args)


if __name__ == "__main__":
    main()
