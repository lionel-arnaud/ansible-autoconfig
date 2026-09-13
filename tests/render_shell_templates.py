#!/usr/bin/env python3
"""Render every shell-producing Jinja template with representative variables and
hand the result to shellcheck.

Why this exists: the bugs this repo has actually shipped were not YAML errors,
which yamllint and ansible-lint already catch. They were shell and Jinja
problems that only surfaced at run time on the target.

What this actually catches, verified by deliberately reintroducing each:
  * a variable typo, because rendering uses StrictUndefined — Jinja's default
    would silently emit an empty string;
  * unrendered `{{ ... }}` surviving into a deployed file, which is exactly what
    put `ExecStart={{ opencode_binary }}` into a live systemd unit;
  * shell word-splitting that shellcheck cannot prove safe (SC2086) — the class
    that made an unquoted `install -d` create two directories named "{{" and "}}".

What it does NOT catch: a template that renders to valid shell but does the
wrong thing (the TCP-only firewall guard rendered perfectly). Only reading it,
or a live assertion, catches that.

Templates are rendered with the role defaults where possible, so the fixtures
below only need to cover what defaults cannot supply.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

REPO = Path(__file__).resolve().parent.parent

def discover_shell_templates():
    """Every *.sh.j2 under every role, mapped to the role whose defaults feed it.

    Discovered rather than listed. The list used to be hardcoded, so a new
    shell template shipped unchecked — which is the same shape of bug as a
    collaborator that is never wired up: nothing fails, so nothing says so.
    """
    found = {}
    for path in sorted((REPO / "roles").glob("*/templates/**/*.sh.j2")):
        rel = path.relative_to(REPO).as_posix()
        found[rel] = path.relative_to(REPO / "roles").parts[0]
    return found


SHELL_TEMPLATES = discover_shell_templates()

# Only what the role defaults do not already define.
EXTRA_VARS = {
    "inventory_hostname": "serverannah",
    "desktop_user": "lion",
    "dotfiles_user": "lion",
    "autoconfig_branch": "main",
    "autoconfig_playbook": "local.yml",
    "server_lan_only_published_ports": [3000, 8089, 8080, 8971, 8554, 8555],
    "server_lan_cidrs": ["192.168.1.0/24"],
}


def load_defaults(role: str) -> dict:
    path = REPO / "roles" / role / "defaults" / "main.yml"
    return yaml.safe_load(path.read_text()) or {}


def resolve(values: dict) -> dict:
    """Role defaults reference each other through Jinja; flatten them so a
    template does not receive a literal '{{ other_var }}' as a value."""
    # Deliberately lenient: role defaults legitimately reference variables that
    # only host_vars supplies, and flattening must not fail on those.
    lenient = Environment(trim_blocks=True, lstrip_blocks=True)
    out = dict(values)
    for _ in range(5):
        changed = False
        for key, value in list(out.items()):
            if isinstance(value, str) and "{{" in value:
                try:
                    rendered = lenient.from_string(value).render(**out)
                except Exception:
                    continue
                if rendered != value:
                    out[key] = rendered
                    changed = True
        if not changed:
            break
    return out


def main() -> int:
    # StrictUndefined, not the default: Jinja renders an unknown name as an
    # empty string, so a typo in a variable silently produces `cat ` with no
    # path instead of an error. Undefined must be loud here.
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    failures = 0

    for rel, role in SHELL_TEMPLATES.items():
        values = {**load_defaults(role), **EXTRA_VARS}
        values = resolve(values)
        source = (REPO / rel).read_text()

        try:
            rendered = env.from_string(source).render(**values)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"FAIL  {rel}\n      render error: {exc}")
            failures += 1
            continue

        # An unrendered marker means a variable was missing, which on a host
        # would be written into the script verbatim.
        if "{{" in rendered or "{%" in rendered:
            print(f"FAIL  {rel}\n      unrendered Jinja survived into the output")
            failures += 1
            continue

        proc = subprocess.run(
            # severity=info, not warning: SC2086 (unquoted variable, i.e. the
            # word-splitting class that created two directories named "{{" and
            # "}}" on this very homelab) is reported at info level and would be
            # filtered out at warning.
            ["shellcheck", "--shell=sh", "--severity=info", "-"],
            input=rendered, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(f"FAIL  {rel}\n{proc.stdout}")
            failures += 1
        else:
            print(f"ok    {rel}")

    print(f"\n{len(SHELL_TEMPLATES) - failures}/{len(SHELL_TEMPLATES)} shell templates clean")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
