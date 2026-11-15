#!/usr/bin/env python3
"""Set Guacamelee 2's Steam launch options in initialized user accounts."""

import glob
import os
import re
import stat
import sys


def closing_brace(data: str, opening: int) -> int:
    depth = 0
    quote = False
    escaped = False
    for position in range(opening, len(data)):
        char = data[position]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
        elif char == '"':
            quote = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position
    raise ValueError("unterminated VDF block")


def child_block(data: str, start: int, end: int, name: str):
    token = re.compile(r'(?m)^(?P<indent>[ \t]*)"' + re.escape(name) + r'"[ \t]*\r?\n[ \t]*\{')
    for match in token.finditer(data, start, end):
        opening = data.find("{", match.start(), match.end())
        closing = closing_brace(data, opening)
        if closing <= end:
            return match.start(), opening, closing, match.group("indent")
    return None


def update(path: str, appid: str, launch_options: str) -> bool:
    original_stat = os.stat(path)
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        data = handle.read()
    apps = child_block(data, 0, len(data), "apps")
    if not apps:
        raise ValueError(f"apps block was not found in {path}")
    _, apps_opening, apps_closing, _ = apps
    app = child_block(data, apps_opening + 1, apps_closing, appid)
    line_ending = "\r\n" if "\r\n" in data else "\n"
    if app:
        _, app_opening, app_closing, app_indent = app
        body_start, body_end = app_opening + 1, app_closing
        option = re.compile(r'(?m)^[ \t]*"LaunchOptions"[ \t]+"(?:\\.|[^"\\])*"[ \t]*\r?\n?')
        replacement = f'{app_indent}\t"LaunchOptions"\t\t"{launch_options}"{line_ending}'
        body = data[body_start:body_end]
        if option.search(body):
            body = option.sub(replacement, body, count=1)
        else:
            body = line_ending + replacement + body
        updated = data[:body_start] + body + data[body_end:]
    else:
        apps_indent = re.search(r'(?m)^([ \t]*)"apps"', data[apps[0]:]).group(1)
        app_indent = apps_indent + "\t"
        entry = (
            f'{line_ending}{app_indent}"{appid}"{line_ending}'
            f'{app_indent}{{{line_ending}'
            f'{app_indent}\t"LaunchOptions"\t\t"{launch_options}"{line_ending}'
            f'{app_indent}}}{line_ending}'
        )
        updated = data[:apps_opening + 1] + entry + data[apps_opening + 1:]
    if updated == data:
        return False
    temporary = path + ".ansible-guacamelee2.tmp"
    with open(temporary, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.write(updated)
    os.chown(temporary, original_stat.st_uid, original_stat.st_gid)
    os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
    os.replace(temporary, path)
    return True


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: steam-root appid launch-options")
    steam_root, appid, launch_options = sys.argv[1:]
    paths = glob.glob(os.path.join(steam_root, "userdata", "*", "config", "localconfig.vdf"))
    changed = sum(update(path, appid, launch_options) for path in paths)
    print("changed" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
