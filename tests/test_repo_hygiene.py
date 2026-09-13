"""ACCEPTANCE G3/G4 — repo-level guarantees, asserted rather than remembered.

These are the checks that are easy to run once by hand and then never again.
Making them tests means the pre-commit hook runs them on every commit.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Shapes, not values. Listing the actual secrets here would be the very thing
# this test exists to prevent.
SECRET_PATTERNS = (
    r"\bPK[A-Z0-9]{18,}\b",             # Alpaca key id
    r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}", # Telegram bot token
    r"-----BEGIN [A-Z ]*PRIVATE KEY",
)


def _tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return [ROOT / p for p in out.stdout.split("\n") if p.strip()]


def test_g3_no_secret_shaped_string_in_any_tracked_file():
    offenders = []
    for path in _tracked_files():
        if not path.is_file() or path.suffix in (".png", ".jpg", ".db"):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        # Vault files are ciphertext by definition.
        if text.startswith("$ANSIBLE_VAULT"):
            continue
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(ROOT)} :: {pattern}")
    assert not offenders, f"secret-shaped strings found: {offenders}"


def test_g3_vault_files_are_actually_encrypted():
    """A vault file saved in plaintext looks identical in a diff listing."""
    # Tracked files only. An rglob walks into .lint-venv and finds Ansible's
    # own vault.yml plugin, which is a source file and not a secret — scoping
    # to what git tracks is also the right definition of "in this repo".
    for path in _tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        is_vault = path.name == "vault.yml" or rel.startswith("files/dotfiles-secret/")
        if not is_vault or not path.is_file():
            continue
        assert path.read_text(errors="ignore").startswith("$ANSIBLE_VAULT"), \
            f"{rel} should be vault-encrypted and is plaintext"


def test_g3_the_vault_password_itself_is_gitignored():
    ignored = (ROOT / ".gitignore").read_text()
    for name in ("secret.txt", ".ansible-vault-pass"):
        assert name in ignored, f"{name} must be gitignored"


def test_g4_every_python_module_imports_cleanly():
    """A module that cannot be imported fails at 3am on the Pi, not here."""
    import importlib

    for path in (ROOT / "trading_agent").glob("*.py"):
        if path.name == "__init__.py":
            continue
        importlib.import_module(f"trading_agent.{path.stem}")


def test_g4_no_build_output_is_tracked():
    """Committed bytecode is both noise and a supply-chain smell: a .pyc can
    disagree with the .py next to it and nobody reads it to notice."""
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in _tracked_files()
        if p.suffix in (".pyc", ".pyo") or "__pycache__" in p.parts
    ]
    assert not offenders, f"build output is tracked: {offenders}"


def test_every_declared_dependency_is_actually_imported():
    """A dependency nobody imports is install weight and audit surface on a
    host that places orders. Pinning one is a decision; keeping a dead one is
    an oversight."""
    import re
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as fh:
        declared = tomllib.load(fh)["project"]["dependencies"]
    names = [re.split(r"[=<>~\[]", d)[0].strip() for d in declared]
    # Distribution name to the module it provides, where they differ.
    module = {"alpaca-py": "alpaca", "python-telegram-bot": "telegram",
              "python-dotenv": "dotenv"}
    source = "\n".join(
        p.read_text() for p in (ROOT / "trading_agent").glob("*.py")
    )
    for name in names:
        mod = module.get(name, name.replace("-", "_"))
        assert re.search(rf"(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b",
                         source, re.M), f"{name} is declared but never imported"
