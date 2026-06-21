#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_V1_DB = Path("/workspace/steuerreport/var/ai_readonly/steuerreport_ai_readonly.tmp.sqlite")
DEFAULT_WALLET_MONTH = Path(
    "/workspace/steuerreport/usertransfer/Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv"
)
DEFAULT_PRICE_CONFIG = PROJECT_ROOT / "configs" / "crypto_price_sources.json"
DEFAULT_WALLET = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
PRICE_ASSETS = ["IOT", "CWIF", "USDC"]

sys.path.insert(0, str(SCRIPT_DIR))
from import_v1_solana_rpc_v2 import _apply as _apply_solana_rpc  # noqa: E402
from import_v1_solana_rpc_v2 import _load_v1_rows  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduzierbarer Staging-/Live-Lauf fuer V1-Solana-RPC plus Wallet-Monatsdaten."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--v1-db", default=str(DEFAULT_V1_DB))
    parser.add_argument("--wallet-month-csv", default=str(DEFAULT_WALLET_MONTH))
    parser.add_argument("--price-config", default=str(DEFAULT_PRICE_CONFIG))
    parser.add_argument("--max-year", type=int, default=2024)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    stage_db = _snapshot_database(db_path, "v1_solana_full_stage")
    result: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "db": str(db_path),
        "stage_db": str(stage_db),
        "v1_db": str(args.v1_db),
        "wallet_month_csv": str(args.wallet_month_csv),
        "max_year": args.max_year,
        "target_changed": False,
    }

    try:
        result["stage"] = _run_full_import(
            stage_db,
            v1_db=Path(args.v1_db),
            wallet_month_csv=Path(args.wallet_month_csv),
            price_config=Path(args.price_config),
            max_year=args.max_year,
        )
    except Exception as exc:
        result["blocked_reason"] = "stage_exception"
        result["error"] = repr(exc)
        print(json.dumps(result, indent=2, default=str))
        return 2

    if not result["stage"]["review"]["allow_export"]:
        result["blocked_reason"] = "stage_review_not_export_ready"
        print(json.dumps(result, indent=2, default=str))
        return 2

    if not args.execute:
        print(json.dumps(result, indent=2, default=str))
        return 0

    backup = _backup_database(db_path)
    result["backup"] = str(backup)
    try:
        result["applied"] = _run_full_import(
            db_path,
            v1_db=Path(args.v1_db),
            wallet_month_csv=Path(args.wallet_month_csv),
            price_config=Path(args.price_config),
            max_year=args.max_year,
        )
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


def _run_full_import(
    db_path: Path,
    *,
    v1_db: Path,
    wallet_month_csv: Path,
    price_config: Path,
    max_year: int | None,
) -> dict[str, Any]:
    rows = _load_v1_rows(v1_db, max_year=max_year)
    solana = _apply_solana_rpc(db_path, rows, replace_source=True)
    wallet = _import_wallet_month(db_path, wallet_month_csv)
    opening = _apply_opening_balance(db_path)
    price_backfill = _backfill_prices(db_path, v1_db=v1_db, price_config=price_config)
    store = DuckDbStore(db_path)
    pipeline = PipelineService(store).rebuild_all()
    review = ReviewService(store).gate()
    requirements = PriceCoverageService(store).requirements()
    portfolio = PortfolioService(store).snapshot()
    return {
        "solana": solana,
        "wallet_month": wallet,
        "opening_balance": opening,
        "price_backfill": price_backfill,
        "pipeline": pipeline.model_dump(mode="json"),
        "review": review.model_dump(mode="json"),
        "price_requirements": requirements.model_dump(mode="json"),
        "portfolio": {
            "total_value_eur": str(portfolio.total_value_eur),
            "positions": len(portfolio.positions),
        },
    }


def _import_wallet_month(db_path: Path, wallet_month_csv: Path) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    importer = FileRawImporter(CsvRawImporter(store))
    content = base64.b64encode(wallet_month_csv.read_bytes()).decode("ascii")
    batch = importer.import_base64("helium", wallet_month_csv.name, content)
    pipeline = PipelineService(store).rebuild_all()
    return {
        "batch": batch.model_dump(mode="json"),
        "pipeline": pipeline.model_dump(mode="json"),
    }


def _apply_opening_balance(db_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "apply_opening_balance_adjustments_v2.py"),
            "--db",
            str(db_path),
            "--accounts",
            DEFAULT_WALLET,
            "--assets",
            "SOL",
            "USDT",
            "--execute",
        ],
        cwd=str(PROJECT_ROOT),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(completed.stdout)


def _backfill_prices(db_path: Path, *, v1_db: Path, price_config: Path) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    service = ExternalPriceBackfillService(store)
    result = service.run(
        config_path=str(price_config),
        v1_fx_db_path=str(v1_db),
        provider="auto",
        assets_filter=PRICE_ASSETS,
        max_requests=20,
        timeout_seconds=30,
        confidence=Decimal("0.80"),
        dry_run=False,
    )
    return result.model_dump(mode="json")


def _snapshot_database(db_path: Path, purpose: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(tempfile.gettempdir()) / f"{db_path.stem}_{purpose}_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_v1_solana_full_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


if __name__ == "__main__":
    raise SystemExit(main())
