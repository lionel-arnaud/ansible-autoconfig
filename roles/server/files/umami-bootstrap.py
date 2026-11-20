#!/usr/bin/env python3
"""Initialize Umami via its API; never print or persist API tokens."""

import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid5

# Ansible's to_uuid default namespace; stable IDs survive a database rebuild.
NAMESPACE = UUID("361e6d51-faec-444a-9079-341386da8e2e")


def bootstrap(base_url, password_file, websites_file):
    password = Path(password_file).read_text().strip()
    if not password:
        raise ValueError("Admin password file is empty")
    token = None

    def api(path, data=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            base_url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def login(value):
        return api("/api/auth/login", {"username": "admin", "password": value})["token"]

    def reset_admin_password(value):
        """Reset a managed admin password when its prior value is unavailable.

        Umami's API correctly requires the old password.  The Ansible-managed
        secret can be rotated independently, though, so use the co-located
        trusted containers to recover that one managed account.  The plaintext
        is passed on stdin only; neither it nor the generated bcrypt hash is
        printed or written to disk.
        """
        bcrypt_program = """
const bcrypt = require("bcryptjs");
let password = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { password += chunk; });
process.stdin.on("end", () => {
  process.stdout.write(bcrypt.hashSync(password, 10));
});
"""
        password_hash = subprocess.run(
            ["docker", "exec", "-i", "umami", "node", "-e", bcrypt_program],
            input=value,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        updated = subprocess.run(
            [
                "docker", "exec", "-i", "umami-db",
                "psql", "-v", "ON_ERROR_STOP=1",
                "-U", "umami", "-d", "umami",
                "-v", f"password_hash={password_hash}",
                "-tAc",
                """UPDATE "user"
                   SET password = :'password_hash', updated_at = NOW()
                   WHERE username = 'admin'
                   RETURNING 1""",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        if updated != "1":
            raise RuntimeError("Expected to reset exactly one Umami admin account")

    changed = False
    try:
        token = login(password)
    except HTTPError as error:
        if error.code != 401:
            raise
        # Only a fresh installation accepts the upstream default password.
        try:
            token = login("umami")
        except HTTPError as default_error:
            if default_error.code != 401:
                raise
            reset_admin_password(password)
        else:
            api("/api/me/password", {"currentPassword": "umami", "newPassword": password})
        token = login(password)
        changed = True

    for website in json.loads(Path(websites_file).read_text()):
        website_id = str(uuid5(NAMESPACE, website["domain"]))
        try:
            existing = api(f"/api/websites/{website_id}")
        except HTTPError as error:
            if error.code not in (401, 403, 404):
                raise
            existing = None
        if existing is None:
            api("/api/websites", {
                "id": website_id,
                "name": website["name"],
                "domain": website["domain"],
            })
            changed = True
    print("changed" if changed else "ok")


if __name__ == "__main__":
    bootstrap(*sys.argv[1:])
