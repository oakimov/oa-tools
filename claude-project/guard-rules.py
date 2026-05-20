#!/usr/bin/env python3
"""PreToolUse hook: block dangerous commands via ~/.claude/hookify.guard-*.md.

Reads tool invocation JSON from stdin, evaluates hookify guard rules,
exits 2 (block) on match, exits 0 (allow) otherwise.
"""
import glob
import json
import os
import re
import sys


def parse_rules():
    rules = []
    home = os.path.expanduser("~")
    for path in sorted(glob.glob(os.path.join(home, ".claude", "hookify.guard-*.md"))):
        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            continue
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue
        fm = _parse_yaml_block(parts[1])
        if not fm.get("enabled", True):
            continue
        rules.append({
            "name": fm.get("name", os.path.basename(path)),
            "event": fm.get("event", "all"),
            "action": fm.get("action", "warn"),
            "conditions": fm.get("conditions", []),
        })
    return rules


def _parse_yaml_block(text):
    data = {}
    current_key = None
    current_list = []
    current_dict = {}
    in_list = False
    in_dict_item = False
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in line and not s.startswith("-"):
            if in_list and current_key:
                if in_dict_item and current_dict:
                    current_list.append(current_dict)
                    current_dict = {}
                data[current_key] = current_list
                in_list = False
                in_dict_item = False
                current_list = []
            key, _, value = line.partition(":")
            value = value.strip()
            if not value:
                current_key = key.strip()
                in_list = True
                current_list = []
            else:
                v = value.strip('"').strip("'")
                if v.lower() == "true":
                    v = True
                elif v.lower() == "false":
                    v = False
                data[key.strip()] = v
        elif s.startswith("-") and in_list:
            if in_dict_item and current_dict:
                current_list.append(current_dict)
                current_dict = {}
            item = s[1:].strip()
            if ":" in item:
                k, v = item.split(":", 1)
                current_dict = {k.strip(): v.strip().strip('"').strip("'")}
                in_dict_item = True
            else:
                current_list.append(item.strip('"').strip("'"))
                in_dict_item = False
        elif indent > 2 and in_dict_item and ":" in line:
            k, v = s.split(":", 1)
            current_dict[k.strip()] = v.strip().strip('"').strip("'")
    if in_list and current_key:
        if in_dict_item and current_dict:
            current_list.append(current_dict)
        data[current_key] = current_list
    return data


def match_rule(rule, command):
    if rule["event"] not in ("all", "bash"):
        return False
    if not rule["conditions"]:
        return False
    return all(_match_one(c, command) for c in rule["conditions"])


def _match_one(cond, value):
    op = cond.get("operator", "regex_match")
    pat = cond.get("pattern", "")
    if op == "regex_match":
        return bool(re.search(pat, value))
    elif op == "contains":
        return pat in value
    elif op == "equals":
        return value == pat
    elif op == "starts_with":
        return value.startswith(pat)
    elif op == "ends_with":
        return value.endswith(pat)
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = data.get("command", "")
    if not command:
        sys.exit(0)

    for rule in parse_rules():
        if match_rule(rule, command):
            out = {"systemMessage": f"Blocked by guard rule: {rule['name']}"}
            print(json.dumps(out), file=sys.stdout)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
