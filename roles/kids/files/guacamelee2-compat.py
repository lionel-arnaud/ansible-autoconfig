#!/usr/bin/env python3
"""Idempotently set one entry in Steam's CompatToolMapping VDF block.

Steam does not provide a system-wide launch-options file.  This preserves the
user's existing VDF and changes only the app entry selected by the role.
"""

import os
import re
import stat
import sys


def closing_brace(data: str, opening: int) -> int:
    """Return the matching close brace, respecting quoted VDF strings."""
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
            continue
        if char == '"':
            quote = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position
    raise ValueError("unterminated VDF block")


def direct_entry(data: str, start: int, end: int, appid: str):
    """Find the app's direct child block inside CompatToolMapping."""
    token = re.compile(r'(?m)^(?P<indent>[ \t]*)"' + re.escape(appid) + r'"[ \t]*\n[ \t]*\{')
    for match in token.finditer(data, start, end):
        open_brace = data.find("{", match.start(), match.end())
        if open_brace < end:
            close_brace = closing_brace(data, open_brace)
            if close_brace <= end:
                return match.start(), close_brace + 1, match.group("indent")
    return None


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: config.vdf appid compatibility-tool config")
    path, appid, tool, config = sys.argv[1:]
    if not os.path.exists(path):
        print("unchanged (Steam has not initialized config.vdf yet)")
        return 0

    original_stat = os.stat(path)
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        data = handle.read()

    mapping = re.search(r'"CompatToolMapping"[ \t]*\r?\n[ \t]*\{', data)
    if not mapping:
        raise SystemExit("CompatToolMapping was not found in Steam config")
    opening = data.find("{", mapping.start(), mapping.end())
    closing = closing_brace(data, opening)
    line_ending = "\r\n" if "\r\n" in data else "\n"
    base_indent = re.search(r'(?m)^([ \t]*)"CompatToolMapping"', data[mapping.start():]).group(1)
    entry_indent = base_indent + "\t"
    entry = (
        f'{entry_indent}"{appid}"{line_ending}'
        f'{entry_indent}{{{line_ending}'
        f'{entry_indent}\t"name"\t\t"{tool}"{line_ending}'
        f'{entry_indent}\t"config"\t\t"{config}"{line_ending}'
        f'{entry_indent}\t"priority"\t\t"250"{line_ending}'
        f'{entry_indent}}}{line_ending}'
    )
    existing = direct_entry(data, opening + 1, closing, appid)
    if existing:
        old_start, old_end, _ = existing
        # The existing block's following newline belongs to ``data[old_end:]``.
        # Do not add another one on replacement, or every reconciliation would
        # grow the file by one blank line.
        updated = data[:old_start] + entry.rstrip("\r\n") + data[old_end:]
    else:
        updated = data[:opening + 1] + line_ending + entry + data[opening + 1:]

    if updated == data:
        print("unchanged")
        return 0
    temporary = path + ".ansible-guacamelee2.tmp"
    with open(temporary, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.write(updated)
    os.chown(temporary, original_stat.st_uid, original_stat.st_gid)
    os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
    os.replace(temporary, path)
    print("changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
