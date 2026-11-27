#!/usr/bin/env python3
"""Additive Odoo accounting import into Axelor 9 REST API.

The Odoo SQL dump is only parsed; it is never modified.  Every created object
has an importId, so rerunning the command is safe.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from decimal import Decimal
from pathlib import Path


TABLES = {
    "res_company": "company",
    "res_partner": "partner",
    "account_account": "account",
    "account_journal": "journal",
    "account_move": "move",
    "account_move_line": "line",
}


def dump_rows(path: Path, wanted: set[str]) -> dict[str, list[dict[str, str | None]]]:
    out = {key: [] for key in wanted}
    current = None
    columns: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            if raw.startswith("COPY public."):
                table = raw.split()[1].split(".")[1]
                current = table if table in wanted else None
                if current:
                    start, end = raw.index("(") + 1, raw.index(")")
                    columns = [x.strip() for x in raw[start:end].split(",")]
                continue
            if current:
                if raw == "\\.\n":
                    current = None
                    continue
                # pg_dump's COPY format uses a literal ``\N`` for NULL.  Do
                # not use csv.escapechar here: it would turn that marker
                # into the string "N" (and would also damage JSON values).
                values = raw.rstrip("\n").split("\t")
                values = [None if x == r"\N" else x.replace(r"\t", "\t").replace(r"\\", "\\")
                          for x in values]
                out[current].append(dict(zip(columns, (None if x == r"\N" else x for x in values))))
    return out


class Axelor:
    def __init__(self, base: str, user: str, password: str):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.open = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.request("/callback", {"username": user, "password": password})

    def request(self, path: str, payload=None, method="POST"):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self.open.open(req) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc
        result = json.loads(body or b"{}")
        if result.get("status", 0) < 0:
            raise RuntimeError(f"{method} {path}: {result.get('data', result)}")
        return result

    def find_import(self, model: str, import_id: str):
        result = self.request(
            f"/ws/rest/{model}/search",
            {"limit": 1, "data": {"criteria": [
                {"fieldName": "importId", "operator": "=", "value": import_id}
            ]},
             "fields": ["id", "version", "importId"]},
        )
        return (result.get("data") or [None])[0]

    def create(self, model: str, import_id: str, data: dict, dry: bool):
        existing = self.find_import(model, import_id)
        if existing:
            return existing["id"], "existing"
        if dry:
            return None, "dry-run"
        result = self.request(f"/ws/rest/{model}", {"data": {**data, "importId": import_id}})
        return result["data"][0]["id"], "created"

    def update(self, model: str, object_id: int, data: dict):
        return self.request(f"/ws/rest/{model}/{object_id}", {"data": data})


def iso_date(value: str | None) -> str | None:
    return value[:10] if value else None


def localized(value: str | None, fallback: str = "") -> str:
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return str(parsed.get("fr_FR") or parsed.get("en_US") or next(iter(parsed.values())))
    except (json.JSONDecodeError, StopIteration):
        pass
    return value


def account_code(value: str | None, source_id: str) -> str:
    return localized(value, f"ODOO-{source_id}")


def short(value: str | None, limit: int = 255) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:18080")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-moves", type=int)
    args = parser.parse_args()

    tables = dump_rows(Path(args.dump), set(TABLES))
    print("source rows:", " ".join(f"{k}={len(v)}" for k, v in tables.items()))
    if args.dry_run:
        print("dry-run: no Axelor connection or writes")
        return 0
    ax = Axelor(args.base, args.user, args.password)
    ids: dict[str, dict[str, int]] = {
        "company": {}, "partner": {}, "account": {}, "journal": {},
        "move": {}, "line": {}, "account-type": {}, "journal-type": {},
        "year": {}, "period": {}, "sequence": {},
    }

    def put(bucket, model, source_id, data):
        ident = f"odoo-{bucket}-{source_id}"
        obj_id, status = ax.create(model, ident, data, args.dry_run)
        if obj_id:
            ids[bucket][source_id] = obj_id
            if bucket == "journal" and status == "existing":
                # A previous partial run may have created the journal before
                # its compatible account type was known.
                ax.update(model, obj_id, {"validAccountTypeSet": [{"id": other_account_type}]})
        print(f"{bucket} {source_id}: {status}", file=sys.stderr)
        return obj_id

    companies = tables["res_company"]
    company = next((r for r in companies if r["id"] == "1"), companies[0])
    company_id = put("company", "com.axelor.apps.base.db.Company", company["id"], {
        "name": company["name"] or "Odoo company", "code": "DIN",
        "currency": {"id": 46},  # seeded EUR in the clean Axelor database
    })
    if not company_id:
        company_id = ax.find_import("com.axelor.apps.base.db.Company", f"odoo-company-{company['id']}")["id"]

    # Axelor installations do not necessarily seed accounting reference data.
    # These two references are intentionally generic and reusable.
    other_account_type = put("account-type", "com.axelor.apps.account.db.AccountType", "other", {
        "name": "Odoo miscellaneous", "technicalTypeSelect": "OTHER",
    })
    other_journal_type = put("journal-type", "com.axelor.apps.account.db.JournalType", "other", {
        "name": "Odoo other", "code": "ODOO", "technicalTypeSelect": 5,
    })
    if not other_account_type or not other_journal_type:
        raise RuntimeError("could not initialize Axelor accounting reference data")

    for row in tables["res_partner"]:
        if row["id"] in {"1", "2", "3", "4", "5", "6"}:
            continue
        put("partner", "com.axelor.apps.base.db.Partner", row["id"], {
            "name": localized(row["name"], f"Odoo partner {row['id']}"),
            "taxNbr": row["vat"], "emailAddress": row["email"],
            "phone": row["phone"], "description": row["comment"],
            "isCustomer": (row["customer_rank"] or "0") != "0",
            "isSupplier": (row["supplier_rank"] or "0") != "0",
        })

    for row in tables["account_account"]:
        put("account", "com.axelor.apps.account.db.Account", row["id"], {
            "code": account_code(row["code_store"], row["id"]),
            "name": localized(row["name"], f"Odoo account {row['id']}"),
            "company": {"id": company_id}, "accountType": {"id": other_account_type},
            "statusSelect": 1 if row["active"] == "t" else 0,
            "commonPosition": 2 if (row["account_type"] or "").startswith(("asset", "expense")) else 1,
        })

    for row in tables["account_journal"]:
        put("journal", "com.axelor.apps.account.db.Journal", row["id"], {
            "code": row["code"] or f"OJ{row['id']}", "name": localized(row["name"], "Odoo journal"),
            "company": {"id": company_id}, "journalType": {"id": other_journal_type},
            "statusSelect": 1 if row["active"] == "t" else 0,
            "validAccountTypeSet": [{"id": other_account_type}],
        })
    move_sequence = put("sequence", "com.axelor.apps.base.db.Sequence", "move", {
        "name": "Odoo imported moves", "company": {"id": company_id},
        "codeSelect": "move", "sequenceTypeSelect": "NUMBERS",
        "prefixe": "ODOO-", "padding": 4, "toBeAdded": 1,
        "yearlyResetOk": False, "monthlyResetOk": False,
    })
    if not move_sequence:
        move_sequence = ax.find_import(
            "com.axelor.apps.base.db.Sequence", "odoo-sequence-move"
        )["id"]
    migration_journal = put("journal", "com.axelor.apps.account.db.Journal", "migration-v2", {
        "code": "ODOO", "name": "Odoo imported entries", "company": {"id": company_id},
        "journalType": {"id": other_journal_type}, "statusSelect": 1,
        "validAccountTypeSet": [{"id": other_account_type}],
        "sequence": {"id": move_sequence},
    })
    if not migration_journal:
        migration_journal = ax.find_import(
            "com.axelor.apps.account.db.Journal", "odoo-journal-migration-v2"
        )["id"]

    years = sorted({iso_date(r["date"])[:4] for r in tables["account_move"] if r["date"]})
    year_ids = {}
    for year in years:
        year_id = put("year", "com.axelor.apps.base.db.Year", year, {
            "name": year, "code": year, "typeSelect": 0, "fromDate": f"{year}-01-01",
            "toDate": f"{year}-12-31", "company": {"id": company_id},
        })
        year_ids[year] = year_id or ax.find_import("com.axelor.apps.base.db.Year", f"odoo-year-{year}")["id"]
        put("period", "com.axelor.apps.base.db.Period", year, {
            "name": year, "code": year, "fromDate": f"{year}-01-01",
            "toDate": f"{year}-12-31", "year": {"id": year_ids[year]},
        })

    line_by_move: dict[str, list[dict]] = {}
    for line in tables["account_move_line"]:
        line_by_move.setdefault(line["move_id"], []).append(line)
    moves = tables["account_move"]
    if args.limit_moves:
        moves = moves[:args.limit_moves]
    for row in moves:
        date = iso_date(row["date"])
        if not date or row["company_id"] != company["id"]:
            continue
        year = date[:4]
        lines = []
        for line in line_by_move.get(row["id"], []):
            account_id = ids["account"].get(line["account_id"])
            if not account_id:
                continue
            if Decimal(line["debit"] or "0") == 0 and Decimal(line["credit"] or "0") == 0:
                continue
            lines.append({
                "account": {"id": account_id},
                "name": short(line["name"] or line["ref"] or ""),
                "date": iso_date(line["date"]) or date,
                "debit": line["debit"] or "0", "credit": line["credit"] or "0",
                "origin": f"odoo-move-line-{line['id']}",
            })
        if not lines:
            continue
        put("move", "com.axelor.apps.account.db.Move", row["id"], {
            # Axelor enforces reference uniqueness per company.  Prefix the
            # source move id so imported entries cannot collide with seeded
            # Axelor closing entries or with one another.
            "date": date,
            "reference": f"ODOO-{row['id']}"
            + (f" {row['ref']}" if row["ref"] != "N" else ""),
            "origin": row["name"],
            "description": short(None if row["narration"] == "N" else row["narration"]),
            "journal": {"id": migration_journal},
            "company": {"id": company_id}, "currency": {"id": 46},
            "period": {"id": ax.find_import("com.axelor.apps.base.db.Period", f"odoo-period-{year}")["id"]},
            "technicalOriginSelect": 4, "moveLineList": lines,
        })
    print("import complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
