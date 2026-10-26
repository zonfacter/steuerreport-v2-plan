#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from steuerreport_v2.domain.external_http import managed_urlopen
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.paths import PROJECT_ROOT

DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_WALLET = PortfolioService.KNOWN_JUP_WALLET
DEFAULT_FX_DB = Path("/root/.local/share/steuerreport/ai_readonly/steuerreport_ai_readonly.sqlite")
DEFAULT_CACHE_DIR = PROJECT_ROOT / "var" / "solscan_cache"
SOURCE = "solana_rpc"
SOLSCAN_SOURCE = "solscan_balance_change"

TOKEN_SYMBOLS = {
    "So11111111111111111111111111111111111111111": "SOL",
    "So11111111111111111111111111111111111111112": "SOL",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": "HNT",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "2uQsyo1fXXQkDtcpXnLofWy88PxcvnfH2L8FPSE62FVU": "JLWSOL",
    "Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8": "SPCXX",
}


class SolscanFetchError(RuntimeError):
    def __init__(self, reason: str, *, requests_used: int) -> None:
        super().__init__(reason)
        self.requests_used = requests_used


def main() -> int:
    parser = argparse.ArgumentParser(description="Importiert die Jup-Wallet-Historie aus Solscan Balance Change.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--fx-db", default=str(DEFAULT_FX_DB))
    parser.add_argument("--max-requests", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--from-time", type=int, default=None)
    parser.add_argument("--to-time", type=int, default=None)
    parser.add_argument("--cache-path", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    wallet = str(args.wallet)
    cache_path = Path(args.cache_path) if args.cache_path else _default_cache_path(wallet)
    result: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "db": str(db_path),
        "wallet": wallet,
        "cache_path": str(cache_path),
        "max_requests": max(0, int(args.max_requests)),
        "page_size": max(1, min(int(args.page_size), 100)),
        "from_time": args.from_time,
        "to_time": args.to_time,
        "target_changed": False,
    }
    try:
        fetched, fetch_meta = _fetch_balance_changes(
            wallet,
            max_requests=max(0, int(args.max_requests)),
            page_size=max(1, min(int(args.page_size), 100)),
            from_time=args.from_time,
            to_time=args.to_time,
            cache_path=cache_path,
            refresh=bool(args.refresh),
        )
    except SolscanFetchError as exc:
        result["fetch"] = {
            "status": "blocked",
            "reason": str(exc),
            "requests_used": exc.requests_used,
            "cache_used": False,
        }
        result["blocked_reason"] = str(exc)
        print(json.dumps(result, indent=2, default=str))
        return 2
    except RuntimeError as exc:
        result["fetch"] = {
            "status": "blocked",
            "reason": str(exc),
            "requests_used": 0,
            "cache_used": False,
        }
        result["blocked_reason"] = str(exc)
        print(json.dumps(result, indent=2, default=str))
        return 2
    rows = _rows_from_balance_changes(wallet, fetched)
    result["fetch"] = fetch_meta
    result["fetched_balance_changes"] = len(fetched)
    result["import_rows"] = len(rows)
    if args.fetch_only:
        print(json.dumps(result, indent=2, default=str))
        return 0 if fetched else 2
    if not rows:
        result["blocked_reason"] = "no_rows"
        print(json.dumps(result, indent=2, default=str))
        return 2

    stage_db = _snapshot_database(db_path, "jup_solscan_balance_change_stage")
    result["stage_db"] = str(stage_db)
    result["stage"] = _apply(stage_db, wallet=wallet, rows=rows, fx_db=Path(args.fx_db))
    if not result["stage"]["review"]["allow_export"]:
        result["blocked_reason"] = "stage_review_not_export_ready"
        print(json.dumps(result, indent=2, default=str))
        return 2
    if not _jup_reconciliation_export_ready(result["stage"]["reconciliation_rows"]):
        result["blocked_reason"] = "stage_jup_reconciliation_not_ready"
        print(json.dumps(result, indent=2, default=str))
        return 2
    if not args.execute:
        print(json.dumps(result, indent=2, default=str))
        return 0

    backup = _backup_database(db_path)
    result["backup"] = str(backup)
    try:
        result["applied"] = _apply(db_path, wallet=wallet, rows=rows, fx_db=Path(args.fx_db))
    except Exception as exc:
        shutil.copy2(backup, db_path)
        result["blocked_reason"] = "live_exception_restored_from_backup"
        result["error"] = repr(exc)
        print(json.dumps(result, indent=2, default=str))
        return 2
    if not result["applied"]["review"]["allow_export"]:
        shutil.copy2(backup, db_path)
        result["blocked_reason"] = "live_review_not_export_ready_restored_from_backup"
        print(json.dumps(result, indent=2, default=str))
        return 2
    if not _jup_reconciliation_export_ready(result["applied"]["reconciliation_rows"]):
        shutil.copy2(backup, db_path)
        result["blocked_reason"] = "live_jup_reconciliation_not_ready_restored_from_backup"
        print(json.dumps(result, indent=2, default=str))
        return 2
    result["target_changed"] = True
    print(json.dumps(result, indent=2, default=str))
    return 0


def _fetch_balance_changes(
    wallet: str,
    *,
    max_requests: int,
    page_size: int,
    from_time: int | None,
    to_time: int | None,
    cache_path: Path,
    refresh: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        data = cached.get("data") if isinstance(cached, dict) else None
        rows = data if isinstance(data, list) else []
        return [item for item in rows if isinstance(item, dict)], {
            "status": "cache",
            "requests_used": 0,
            "cache_used": True,
            "cache_path": str(cache_path),
            "warnings": cached.get("warnings", []) if isinstance(cached, dict) else [],
        }
    key = _solscan_api_key()
    if not key:
        raise RuntimeError("solscan_api_key_missing_or_unusable")
    if max_requests <= 0:
        raise RuntimeError("solscan_max_requests_zero")
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    requests_used = 0
    for page in range(1, max_requests + 1):
        params = {
            "address": wallet,
            "page": page,
            "page_size": page_size,
            "sort_by": "block_time",
            "sort_order": "asc",
            "remove_spam": "false",
        }
        if from_time is not None:
            params["from_time"] = from_time
        if to_time is not None:
            params["to_time"] = to_time
        url = f"{PortfolioService.SOLSCAN_PRO_BASE_URL.rstrip('/')}/account/balance_change?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"token": key, "accept": "application/json"})
        try:
            with managed_urlopen(request, timeout=30) as response:
                requests_used += 1
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            requests_used += 1
            if exc.code in {401, 403}:
                raise SolscanFetchError(
                    f"solscan_auth_or_subscription_failed:{exc.code}",
                    requests_used=requests_used,
                ) from exc
            if exc.code == 429:
                warnings.append("solscan_rate_limited:429")
                break
            raise SolscanFetchError(
                f"solscan_http_error:{exc.code}",
                requests_used=requests_used,
            ) from exc
        data = payload.get("data") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(data, list) or not data:
            break
        rows.extend(item for item in data if isinstance(item, dict))
        if len(data) < page_size:
            break
        time.sleep(1.2)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "wallet": wallet,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "requests_used": requests_used,
                "page_size": page_size,
                "from_time": from_time,
                "to_time": to_time,
                "warnings": warnings,
                "data": rows,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return rows, {
        "status": "live",
        "requests_used": requests_used,
        "cache_used": False,
        "cache_path": str(cache_path),
        "warnings": warnings,
    }


def _solscan_api_key() -> str:
    for env_key in ("SOLSCAN_API_KEY", "SOLSCAN_PRO_API_KEY"):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    return PortfolioService(DuckDbStore(os.environ.get("STEUERREPORT_V2_DB") or DEFAULT_DB))._solscan_api_key()


def _default_cache_path(wallet: str) -> Path:
    return DEFAULT_CACHE_DIR / f"balance_change_{wallet[:8]}_{wallet[-8:]}.json"


def _rows_from_balance_changes(wallet: str, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tx: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in changes:
        tx_id = str(item.get("trans_id") or "")
        if tx_id:
            by_tx[tx_id].append(item)

    rows: list[dict[str, Any]] = []
    for item in changes:
        token_address = str(item.get("token_address") or "")
        asset = TOKEN_SYMBOLS.get(token_address)
        if asset is None:
            continue
        quantity = abs(_signed_quantity(item))
        if quantity == 0:
            continue
        tx_id = str(item.get("trans_id") or "")
        event_type = "sol_transfer" if asset == "SOL" else "token_transfer"
        side = "in" if item.get("change_type") == "inc" else "out"
        if asset == "SOL" and quantity <= Decimal("0.00001") and _only_sol_dust(by_tx.get(tx_id, [])):
            event_type = "fee"
            side = ""
        rows.append(
            {
                "timestamp_utc": _timestamp(item),
                "wallet_address": wallet,
                "asset": asset,
                "asset_address": token_address,
                "quantity": str(quantity),
                "price": "",
                "fee": "0",
                "fee_asset": "",
                "side": side,
                "event_type": event_type,
                "defi_label": "balance_change",
                "tx_id": tx_id,
                "source": SOLSCAN_SOURCE,
                "raw_row": item,
            }
        )
    return rows


def _apply(db_path: Path, *, wallet: str, rows: list[dict[str, Any]], fx_db: Path) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    deleted_batches = _delete_existing_jup_batches(store, wallet)
    file_hash = "sha256:" + hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    batch = CsvRawImporter(store).import_rows(
        SOURCE,
        "jup_wallet_solscan_balance_change_2026-05-27.json",
        file_hash,
        rows,
    )
    solscan_event_prices = _store_solscan_event_prices(store, rows, fx_db)
    pipeline = PipelineService(store).rebuild_all()
    backfill = ExternalPriceBackfillService(store).run(
        config_path=str(PROJECT_ROOT / "configs" / "crypto_price_sources.json"),
        v1_fx_db_path=str(fx_db),
        provider="coingecko",
        assets_filter=["SOL", "USDC"],
        max_requests=50,
        timeout_seconds=20,
        confidence=Decimal("0.95"),
        dry_run=False,
    )
    PortfolioService(store).refresh_reconciliation_snapshots(connectors=["jup_wallet"])
    _store_jlwsol_live_price(store)
    pipeline = PipelineService(store).rebuild_all()
    review = ReviewService(store).gate()
    reconciliation = PortfolioService(store).reconciliation_report()
    jup_rows = [
        row.model_dump(mode="json")
        for row in reconciliation.rows
        if row.source_group == "Jup Wallet GmHY...3yu"
    ]
    return {
        "deleted_batches": deleted_batches,
        "batch": batch.model_dump(mode="json"),
        "solscan_event_prices": solscan_event_prices,
        "initial_pipeline": pipeline.model_dump(mode="json"),
        "price_backfill": backfill.model_dump(mode="json"),
        "review": review.model_dump(mode="json"),
        "reconciliation_rows": jup_rows,
    }


def _delete_existing_jup_batches(store: DuckDbStore, wallet: str) -> list[str]:
    with store.connect() as con:
        batch_ids = [
            str(row[0])
            for row in con.execute(
                """
                select distinct b.batch_id
                from raw_import_batches b
                left join raw_objects ro on ro.batch_id = b.batch_id
                where b.source = ?
                  and (
                    b.filename like '%3b8h%'
                    or b.filename like '%jup_wallet_solscan%'
                    or coalesce(ro.payload_json, '') like ?
                  )
                order by b.batch_id
                """,
                [SOURCE, f"%{wallet}%"],
            ).fetchall()
        ]
    for batch_id in batch_ids:
        store.delete_import_batch(batch_id)
    return batch_ids


def _store_jlwsol_live_price(store: DuckDbStore) -> None:
    with store.connect() as con:
        row = con.execute(
            """
            select asset, source, fetched_at
            from portfolio_live_balance_snapshots
            where connector_id = 'jup_wallet'
              and upper(asset) = 'JLWSOL'
            order by fetched_at desc
            limit 1
            """
        ).fetchone()
    if row is None:
        return
    prices = PortfolioService(store)._latest_prices()
    sol_price = prices.get("SOL")
    if sol_price is None:
        return
    store.add_price_point(
        PricePointCreate(
            asset="JLWSOL",
            price_eur=sol_price.price_eur,
            priced_at=row[2],
            source=f"{row[1]}:jlwsol_tracks_sol",
            confidence=Decimal("0.90"),
        )
    )


def _store_solscan_event_prices(store: DuckDbStore, rows: list[dict[str, Any]], fx_db: Path) -> int:
    service = ExternalPriceBackfillService(store)
    prices: list[PricePointCreate] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        asset = str(row.get("asset") or "").upper()
        if asset not in {"SOL", "USDC", "JLWSOL"}:
            continue
        raw = row.get("raw_row")
        if not isinstance(raw, dict):
            continue
        value_usd = Decimal(str(raw.get("value") or "0"))
        quantity = Decimal(str(row.get("quantity") or "0"))
        if value_usd <= 0 or quantity <= 0:
            continue
        price_date = _timestamp(raw)[:10]
        key = (asset, price_date)
        if key in seen:
            continue
        usd_eur = service._usd_eur_rate(str(fx_db), price_date)
        if usd_eur <= 0:
            continue
        seen.add(key)
        prices.append(
            PricePointCreate(
                asset=asset,
                price_eur=(value_usd / quantity) * usd_eur,
                priced_at=datetime.fromisoformat(f"{price_date}T00:00:00+00:00"),
                source=f"solscan_balance_change:value_usd:usd_eur:v1_fx_cache:{price_date}",
                confidence=Decimal("0.90"),
            )
        )
    store.add_price_points(prices)
    return len(prices)


def _jup_reconciliation_export_ready(rows: list[dict[str, Any]]) -> bool:
    return not any(row.get("severity") == "blocker" for row in rows)


def _snapshot_database(db_path: Path, purpose: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = PROJECT_ROOT / "var" / f"{db_path.stem}_{purpose}_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_jup_solscan_balance_change_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _signed_quantity(item: dict[str, Any]) -> Decimal:
    decimals = int(item.get("token_decimals") or 0)
    quantity = Decimal(str(item.get("amount") or 0)) / (Decimal(10) ** decimals)
    return -quantity if item.get("change_type") == "dec" else quantity


def _only_sol_dust(items: list[dict[str, Any]]) -> bool:
    relevant = [
        item
        for item in items
        if not (
            str(item.get("token_address") or "") == "So11111111111111111111111111111111111111111"
            and abs(_signed_quantity(item)) <= Decimal("0.00001")
        )
    ]
    return not relevant


def _timestamp(item: dict[str, Any]) -> str:
    value = str(item.get("time") or "")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


if __name__ == "__main__":
    sys.exit(main())
