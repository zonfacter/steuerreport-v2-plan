#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter

OPENING_BALANCE_SOURCE = "opening-balance"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create explicit opening-balance adjustments for negative account balances."
    )
    parser.add_argument("--db", default="data/steuerreport_v2.duckdb")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--accounts", nargs="*", default=None)
    parser.add_argument("--assets", nargs="*", default=None)
    parser.add_argument(
        "--replace-source",
        action="store_true",
        help=(
            "Ersetzt die bestehende Opening-Balance-Quelle. Ohne diese Option "
            "werden gefilterte Adjustments in eine eigene Scope-Quelle geschrieben."
        ),
    )
    args = parser.parse_args()

    store = DuckDbStore(args.db)
    accounts = {item for item in args.accounts} if args.accounts else None
    assets = {item.upper() for item in args.assets} if args.assets else None
    source = _source_for_scope(accounts=accounts, assets=assets, replace_source=args.replace_source)
    pipeline = None
    deleted_existing = 0
    if args.execute:
        deleted_existing = store.delete_import_batches_by_source(source)
        if deleted_existing:
            PipelineService(store).rebuild_all()
    adjustments = _negative_balance_adjustments(
        store,
        accounts=accounts,
        assets=assets,
    )
    if args.execute:
        if adjustments:
            content = _adjustments_csv(adjustments)
            batch = CsvRawImporter(store).import_text(
                source=source,
                filename="opening-balance-adjustments.csv",
                content=content,
            )
            pipeline = PipelineService(store).rebuild_after_import(batch.batch_id).model_dump(mode="json")
        else:
            pipeline = PipelineService(store).rebuild_all().model_dump(mode="json")

    print(
        json.dumps(
            {
                "mode": "execute" if args.execute else "dry-run",
                "source": source,
                "base_source": OPENING_BALANCE_SOURCE,
                "scoped": source != OPENING_BALANCE_SOURCE,
                "adjustments": _json_ready(adjustments),
                "deleted_existing": deleted_existing,
                "pipeline": pipeline,
            },
            indent=2,
        )
    )


def _source_for_scope(
    *,
    accounts: set[str] | None,
    assets: set[str] | None,
    replace_source: bool,
) -> str:
    if replace_source or (accounts is None and assets is None):
        return OPENING_BALANCE_SOURCE
    scope = json.dumps(
        {
            "accounts": sorted(accounts or []),
            "assets": sorted(assets or []),
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(scope.encode("utf-8")).hexdigest()[:12]
    return f"{OPENING_BALANCE_SOURCE}-scope-{digest}"


def _negative_balance_adjustments(
    store: DuckDbStore,
    *,
    accounts: set[str] | None,
    assets: set[str] | None,
) -> list[dict[str, Any]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select account, asset
            from balance_ledger
            group by account, asset
            having sum(delta_quantity) < -0.00000001
            order by account, asset
            """
        ).fetchall()
        adjustments: list[dict[str, Any]] = []
        for account, asset in rows:
            if accounts is not None and account not in accounts:
                continue
            if assets is not None and asset.upper() not in assets:
                continue
            minimum, first_negative_at = con.execute(
                """
                select min(balance_quantity), min(event_time) filter (where balance_quantity < -0.00000001)
                from balance_ledger
                where account = ? and asset = ?
                """,
                [account, asset],
            ).fetchone()
            first_event_at = con.execute(
                """
                select min(event_time)
                from balance_ledger
                where account = ? and asset = ?
                """,
                [account, asset],
            ).fetchone()[0]
            if minimum is None or minimum >= 0:
                continue
            adjustment_time = first_event_at - timedelta(seconds=1)
            adjustments.append(
                {
                    "time": adjustment_time,
                    "account": account,
                    "asset": asset,
                    "amount": abs(Decimal(minimum)),
                    "type": "opening transfer",
                    "note": f"Opening balance required before first negative balance at {first_negative_at}",
                }
            )
    return adjustments


def _adjustments_csv(adjustments: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["time", "asset", "amount", "type", "account", "note"])
    writer.writeheader()
    for adjustment in adjustments:
        writer.writerow(
            {
                "time": adjustment["time"].isoformat(),
                "asset": adjustment["asset"],
                "amount": str(adjustment["amount"]),
                "type": adjustment["type"],
                "account": adjustment["account"],
                "note": adjustment["note"],
            }
        )
    return buffer.getvalue()


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    main()
