#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter

PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_ARTIFACT = (
    PROJECT_ROOT
    / "var"
    / "staging_audits"
    / "helium_solana_reward_evidence_wbr_20260619_2140_combined.json"
)
DEFAULT_FX_DB = Path("/root/.local/share/steuerreport/ai_readonly/steuerreport_ai_readonly.sqlite")
DEFAULT_PRICE_CONFIG = PROJECT_ROOT / "configs" / "crypto_price_sources.json"
IMPORT_SOURCE = "solana_rpc"
IMPORT_FILENAME = "helium_solana_reward_rpc_evidence_2026-06-19_wbr.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importiert belegte Helium/Solana Reward-Evidence in V2 Raw-Objects."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--fx-db", default=str(DEFAULT_FX_DB))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    artifact_path = Path(args.artifact)
    rows = rows_from_artifact(artifact_path)
    result: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "db": str(db_path),
        "artifact": str(artifact_path),
        "source": IMPORT_SOURCE,
        "filename": IMPORT_FILENAME,
        "rows": len(rows),
        "target_changed": False,
    }
    if not rows:
        result["blocked_reason"] = "no_reward_rows"
        print(json.dumps(result, indent=2, default=str))
        return 2

    stage_db = snapshot_database(db_path, "helium_solana_reward_evidence_stage")
    result["stage_db"] = str(stage_db)
    result["stage"] = apply_import(stage_db, rows=rows, fx_db=Path(args.fx_db))
    if not result["stage"]["review"]["allow_export"]:
        result["blocked_reason"] = "stage_review_not_export_ready"
        print(json.dumps(result, indent=2, default=str))
        return 2
    if not args.execute:
        print(json.dumps(result, indent=2, default=str))
        return 0

    backup = backup_database(db_path)
    result["backup"] = str(backup)
    try:
        result["applied"] = apply_import(db_path, rows=rows, fx_db=Path(args.fx_db))
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
    result["target_changed"] = True
    print(json.dumps(result, indent=2, default=str))
    return 0


def rows_from_artifact(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    wallet = str(payload.get("summary", {}).get("wallet") or "")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in payload.get("rows", []):
        if not isinstance(item, dict):
            continue
        if item.get("classification") != "helium_reward":
            continue
        signature = str(item.get("signature") or "")
        if not signature or signature in seen:
            continue
        seen.add(signature)
        rows.append(
            {
                "timestamp_utc": item.get("event_time"),
                "event_type": "token_transfer",
                "asset": item.get("asset"),
                "quantity": item.get("quantity"),
                "side": "in",
                "tx_id": signature,
                "wallet_address": wallet,
                "source": "helium_solana_reward_rpc_evidence",
                "artifact_path": str(path),
                "reward_instruction_logs": item.get("reward_instruction_logs") or [],
                "reward_instruction_detected": True,
            }
        )
    return rows


def apply_import(db_path: Path, *, rows: list[dict[str, object]], fx_db: Path) -> dict[str, object]:
    store = DuckDbStore(db_path)
    deleted_batches = delete_existing_batches(store)
    file_hash = "sha256:" + hashlib.sha256(
        json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    batch = CsvRawImporter(store).import_rows(
        source=IMPORT_SOURCE,
        filename=IMPORT_FILENAME,
        file_hash=file_hash,
        rows=rows,
    )
    pipeline = PipelineService(store).rebuild_after_import(batch.batch_id)
    review = ReviewService(store).gate()
    price_backfill = None
    if not review.allow_export and any(
        issue.code == "missing_event_price"
        and "asset:HNT" in issue.scope
        and "year:2026" in issue.scope
        for issue in review.issues
    ):
        price_backfill = store_hnt_reward_prices(store, rows=rows, fx_db=fx_db)
        pipeline = PipelineService(store)._rebuild_ledgers(0)
        review = ReviewService(store).gate()
    summary = TaxYearService(store).detail(2026)
    income = TaxYearService(store).income_report(2026)
    return {
        "deleted_batches": deleted_batches,
        "batch": batch.model_dump(mode="json"),
        "pipeline": pipeline.model_dump(mode="json"),
        "price_backfill": price_backfill,
        "review": review.model_dump(mode="json"),
        "tax_year_2026": {
            "rewards_income_eur": str(summary.rewards_income_eur),
            "rewards_events_count": summary.rewards_events_count,
            "income_reward_eur": str(income.reward_income_eur),
            "classification_counts": income.classification_counts,
        },
    }


def store_hnt_reward_prices(
    store: DuckDbStore,
    *,
    rows: list[dict[str, object]],
    fx_db: Path,
) -> dict[str, object]:
    service = ExternalPriceBackfillService(store)
    assets = service._load_assets(str(DEFAULT_PRICE_CONFIG))
    asset = service._alias_map(assets).get("HNT")
    if asset is None:
        return {"status": "skipped", "reason": "hnt_not_configured", "imported_prices": 0}
    dates = sorted(
        {
            datetime.fromisoformat(str(row["timestamp_utc"]).replace("Z", "+00:00")).date().isoformat()
            for row in rows
            if str(row.get("asset") or "").upper() == "HNT" and row.get("timestamp_utc")
        }
    )
    prices: list[PricePointCreate] = []
    jobs: list[dict[str, object]] = []
    with httpx.Client(timeout=20, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
        for price_date in dates:
            usd_eur = service._usd_eur_rate(str(fx_db), price_date)
            price_usd, source = service._fetch_price_usd(
                client=client,
                coingecko_id=asset.coingecko_id,
                date_str=price_date,
                provider="coingecko",
            )
            if price_usd <= 0:
                price_usd, source, source_date = service._fetch_first_available_price_usd_after(
                    client=client,
                    coingecko_id=asset.coingecko_id,
                    date_str=price_date,
                    provider="coingecko",
                    max_days_after=7,
                )
                if price_usd > 0:
                    usd_eur = service._usd_eur_rate(str(fx_db), source_date)
                    source = f"{source}:first_available_after:{source_date}"
            else:
                source_date = price_date
            if price_usd <= 0 or usd_eur <= 0:
                jobs.append(
                    {
                        "asset": "HNT",
                        "price_date": price_date,
                        "status": "failed",
                        "reason": "price_or_fx_missing",
                    }
                )
                continue
            source_label = f"{source}:usd_eur:v1_fx_cache:{source_date}"
            prices.append(
                PricePointCreate(
                    asset="HNT",
                    price_eur=price_usd * usd_eur,
                    priced_at=datetime.fromisoformat(f"{price_date}T00:00:00+00:00"),
                    source=source_label,
                    confidence=Decimal("0.95"),
                )
            )
            jobs.append(
                {
                    "asset": "HNT",
                    "price_date": price_date,
                    "status": "imported",
                    "price_usd": str(price_usd),
                    "usd_eur": str(usd_eur),
                    "price_eur": str(price_usd * usd_eur),
                    "source": source_label,
                }
            )
    if prices:
        store.add_price_points(prices)
    return {
        "status": "ok" if prices else "failed",
        "imported_prices": len(prices),
        "jobs": jobs,
    }


def delete_existing_batches(store: DuckDbStore) -> list[str]:
    with store.connect() as con:
        batch_ids = [
            str(row[0])
            for row in con.execute(
                """
                select batch_id
                from raw_import_batches
                where source = ?
                  and filename = ?
                order by created_at
                """,
                [IMPORT_SOURCE, IMPORT_FILENAME],
            ).fetchall()
        ]
    for batch_id in batch_ids:
        store.delete_import_batch(batch_id)
    return batch_ids


def snapshot_database(db_path: Path, purpose: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = PROJECT_ROOT / "var" / f"{db_path.stem}_{purpose}_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_helium_solana_reward_evidence_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


if __name__ == "__main__":
    sys.exit(main())
