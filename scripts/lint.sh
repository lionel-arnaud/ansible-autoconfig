#!/bin/sh
set -eu
# Local-only linting. No CI service, no cloud cost: this just runs yamllint and
# ansible-lint against the repo on your own machine.
#
# On first run it builds a throwaway Python virtualenv (.lint-venv, gitignored)
# so the linters do not have to be installed system-wide. Delete that folder any
# time to force a clean reinstall.
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
venv_dir="$repo_dir/.lint-venv"

if [ ! -x "$venv_dir/bin/ansible-lint" ]; then
  echo "== setting up local lint virtualenv (first run only) =="
  python3 -m venv "$venv_dir"
  "$venv_dir/bin/pip" install --quiet --upgrade pip
  "$venv_dir/bin/pip" install --quiet yamllint ansible-lint
fi

cd "$repo_dir"

echo "== yamllint =="
"$venv_dir/bin/yamllint" .

echo "== ansible-lint =="
"$venv_dir/bin/ansible-lint"

# Renders the shell-producing templates and shellchecks the result. yamllint and
# ansible-lint both see only the YAML; this is what looks at what actually lands
# on a host.
echo "== rendered shell templates =="
if command -v shellcheck >/dev/null 2>&1; then
  "$venv_dir/bin/python" "$repo_dir/tests/render_shell_templates.py"
else
  echo "SKIP: shellcheck not installed (pacman -S shellcheck / apt install shellcheck)"
fi

# The trading agent handles money; its tests are part of the gate, not an
# optional extra. Skipped cleanly when the package is not present.
if [ -d "$repo_dir/trading_agent" ]; then
  echo "== trading agent tests =="
  if "$venv_dir/bin/python" -c "import pytest" 2>/dev/null; then
    "$venv_dir/bin/python" -m pytest "$repo_dir/tests" -q
  else
    echo "SKIP: pytest not in .lint-venv (pip install pytest)"
  fi
fi

echo "== lint OK =="
