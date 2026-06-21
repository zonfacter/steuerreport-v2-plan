#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_V1_DB = Path("/workspace/steuerreport/var/ai_readonly/steuerreport_ai_readonly.tmp.sqlite")
DEFAULT_PRICE_CONFIG = PROJECT_ROOT / "configs" / "crypto_price_sources.json"
SOURCE = "solana_rpc"


def _load_v1_rows(v1_db: Path, *, max_year: int | None = None) -> list[dict[str, Any]]:
    with sqlite3.connect(v1_db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            select unique_event_id, row_index, payload_json
            from raw_events
            where json_extract(payload_json, '$.source') = ?
            order by json_extract(payload_json, '$.timestamp_utc'), unique_event_id
            """,
            [SOURCE],
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        timestamp = str(payload.get("timestamp_utc") or "")
        if max_year is not None:
            try:
                year = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).year
            except ValueError:
                continue
            if year > max_year:
                continue
        payload["v1_unique_event_id"] = row["unique_event_id"]
        payload["v1_row_index"] = row["row_index"]
        result.append(payload)
    result = _drop_unconfigured_token_transfers(result)
    return _enrich_missing_wallets(result)


def _drop_unconfigured_token_transfers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known_assets = _known_asset_aliases(DEFAULT_PRICE_CONFIG)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        asset = str(row.get("asset") or row.get("symbol") or row.get("mint") or "").strip().upper()
        event_type = str(row.get("event_type") or row.get("type") or "").strip().lower()
        quantity = _decimal_or_none(row.get("quantity") or row.get("amount"))
        if (
            asset
            and asset not in known_assets
            and event_type == "token_transfer"
            and quantity is not None
            and quantity > 0
        ):
            continue
        filtered.append(row)
    return filtered


def _known_asset_aliases(config_path: Path) -> set[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for item in payload.get("assets", []):
        for value in [item.get("symbol"), *item.get("aliases", []), *item.get("store_keys", [])]:
            alias = str(value or "").strip().upper()
            if alias:
                result.add(alias)
    return result


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _enrich_missing_wallets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wallets_by_tx: dict[str, str] = {}
    known_wallets = sorted({_wallet(row) for row in rows if _wallet(row)})
    default_wallet = known_wallets[0] if len(known_wallets) == 1 else None
    for row in rows:
        tx_id = _tx_id(row)
        wallet = _wallet(row)
        if tx_id and wallet:
            wallets_by_tx.setdefault(tx_id, wallet)

    for row in rows:
        if _wallet(row):
            continue
        tx_id = _tx_id(row)
        wallet = wallets_by_tx.get(tx_id or "")
        if wallet:
            row["wallet_address"] = wallet
            row["v1_wallet_inferred_from_tx"] = tx_id
        elif default_wallet:
            row["wallet_address"] = default_wallet
            row["v1_wallet_inferred_from_single_wallet_source"] = True
    return rows


def _tx_id(row: dict[str, Any]) -> str | None:
    value = row.get("tx_id") or row.get("signature") or row.get("transaction_hash")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _wallet(row: dict[str, Any]) -> str | None:
    value = row.get("wallet_address") or row.get("account") or row.get("wallet")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _snapshot_database(db_path: Path, purpose: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(tempfile.gettempdir()) / f"{db_path.stem}_{purpose}_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_v1_solana_rpc_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _apply(db_path: Path, rows: list[dict[str, Any]], *, replace_source: bool) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    if replace_source:
        store.delete_import_batches_by_source(SOURCE)
    batch = CsvRawImporter(store).import_rows(
        source=SOURCE,
        filename=str(DEFAULT_V1_DB),
        file_hash=f"v1-sqlite:{DEFAULT_V1_DB}:source={SOURCE}:rows={len(rows)}",
        rows=rows,
    )
    pipeline = PipelineService(store).rebuild_all()
    gate = ReviewService(store).gate()
    return {
        "batch_id": batch.batch_id,
        "raw_objects": batch.raw_object_count,
        "pipeline": pipeline.model_dump(mode="json"),
        "review": gate.model_dump(mode="json"),
    }


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    v1_db = Path(args.v1_db)
    rows = _load_v1_rows(v1_db, max_year=args.max_year)
    result: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "db": str(db_path),
        "v1_db": str(v1_db),
        "source": SOURCE,
        "max_year": args.max_year,
        "rows": len(rows),
        "target_changed": False,
    }
    if not rows:
        print(json.dumps(result, indent=2))
        return 2

    stage_db = _snapshot_database(db_path, "v1_solana_rpc_stage")
    preflight = _apply(stage_db, rows, replace_source=args.replace_source)
    result["preflight_db"] = str(stage_db)
    result["preflight"] = preflight
    if not preflight["review"]["allow_export"]:
        result["blocked_reason"] = "preflight_review_not_export_ready"
        print(json.dumps(result, indent=2))
        return 2
    if not args.execute:
        print(json.dumps(result, indent=2))
        return 0

    backup = _backup_database(db_path)
    applied = _apply(db_path, rows, replace_source=args.replace_source)
    result["backup"] = str(backup)
    result["applied"] = applied
    result["target_changed"] = True
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migriert V1-Solana-RPC-Primaerdaten nach V2.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--v1-db", default=str(DEFAULT_V1_DB))
    parser.add_argument("--max-year", type=int)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replace-source", action="store_true", default=True)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
