#!/usr/bin/env python3
"""Propagate default permissions to all .claude/settings.local.json files."""

import argparse
import json
import os
import sys


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def find_settings_files(root):
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        if ".claude" in dirnames:
            candidate = os.path.join(dirpath, ".claude", "settings.local.json")
            if os.path.isfile(candidate):
                results.append(candidate)
    return sorted(results)


def merge_permissions(target_path, default_allow, default_deny, dry_run=False):
    changed = False
    added_allow = []
    added_deny = []

    if os.path.isfile(target_path):
        data = load_json(target_path)
    else:
        data = {}

    perms = data.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    deny = perms.setdefault("deny", [])

    existing_allow = set(allow)
    existing_deny = set(deny)

    for entry in default_allow:
        if entry not in existing_allow:
            allow.append(entry)
            added_allow.append(entry)
            changed = True

    for entry in default_deny:
        if entry not in existing_deny:
            deny.append(entry)
            added_deny.append(entry)
            changed = True

    if changed and not dry_run:
        save_json(target_path, data)

    return changed, added_allow, added_deny


def merge_skill_overrides(target_path, default_overrides, dry_run=False):
    """Replace skillOverrides in target file with defaults. Returns True if changed."""
    if not default_overrides:
        return False

    if os.path.isfile(target_path):
        data = load_json(target_path)
    else:
        data = {}

    existing = data.get("skillOverrides", {})
    if existing == default_overrides:
        return False

    if not dry_run:
        data["skillOverrides"] = dict(default_overrides)
        save_json(target_path, data)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Propagate default permissions to .claude/settings.local.json files"
    )
    parser.add_argument(
        "search_root", nargs="?", default=os.path.expanduser("~"),
        help="Directory to search from (default: ~)"
    )
    parser.add_argument(
        "--defaults-file", default=None,
        help="JSON file with canonical permissions (default: settings.local.json next to script)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing"
    )
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))

    if args.defaults_file:
        defaults_path = args.defaults_file
    else:
        defaults_path = os.path.join(here, "settings.local.json")

    if not os.path.isfile(defaults_path):
        print(f"Defaults file not found: {defaults_path}", file=sys.stderr)
        sys.exit(1)

    defaults = load_json(defaults_path)
    default_allow = defaults.get("permissions", {}).get("allow", [])
    default_deny = defaults.get("permissions", {}).get("deny", [])
    default_skill_overrides = defaults.get("skillOverrides", {})

    files = find_settings_files(args.search_root)
    if not files:
        print("No .claude/settings.local.json files found.")
        return

    updated = 0
    unchanged = 0

    updated_sk = 0
    unchanged_sk = 0

    for fpath in files:
        changed, added_a, added_d = merge_permissions(fpath, default_allow, default_deny, args.dry_run)
        rel = os.path.relpath(fpath, args.search_root)
        if changed:
            updated += 1
            verb = "Would update" if args.dry_run else "Updated"
            print(f"  {verb}: {rel}")
            for entry in added_a:
                print(f"    + allow: {entry}")
            for entry in added_d:
                print(f"    + deny: {entry}")
        else:
            unchanged += 1

        sk_changed = merge_skill_overrides(fpath, default_skill_overrides, args.dry_run)
        if sk_changed:
            updated_sk += 1
        else:
            unchanged_sk += 1

    summary = f"Permissions: {len(files)} scanned, {updated} "
    summary += "would be updated" if args.dry_run else "updated"
    summary += f", {unchanged} unchanged"
    print(f"\n{summary}")

    sk_verb = "Would update" if args.dry_run else "Updated"
    print(f"SkillOverrides: {len(files)} scanned, {updated_sk} {sk_verb.lower()}, {unchanged_sk} unchanged")


if __name__ == "__main__":
    main()
