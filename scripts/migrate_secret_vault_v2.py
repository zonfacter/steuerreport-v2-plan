#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secret_vault import migrate_secret_vault


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Encrypt V2 secret.* settings in place without printing secret values."
    )
    parser.add_argument("--db", help="DuckDB path; defaults to STEUERREPORT_V2_DB.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag only a count-only preview is returned.",
    )
    args = parser.parse_args()
    result = migrate_secret_vault(DuckDbStore(args.db), apply=args.apply)
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=True))
    return 0 if result.status != "blocked" or not args.apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
