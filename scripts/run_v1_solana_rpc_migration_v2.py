#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import argparse
import base64
import json
import subprocess
import sys
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
    "/workspace/steuerreport/usertransfer/Wallet.6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP-month.csv"
)
DEFAULT_PRICE_CONFIG = PROJECT_ROOT / "configs" / "crypto_price_sources.json"
DEFAULT_WALLET = private_value('primary_solana_wallet')
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

    result: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "db": str(args.db),
        "v1_db": str(args.v1_db),
        "wallet_month_csv": str(args.wallet_month_csv),
        "max_year": args.max_year,
        "target_changed": False,
        "blocked_reason": "unsafe_database_snapshot_and_restore_unavailable",
        "stage_attempted": False,
        "restore_attempted": False,
    }
    print(json.dumps(result, indent=2, default=str))
    return 2


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


if __name__ == "__main__":
    raise SystemExit(main())
