#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_WALLET_MONTH = (
    Path("/workspace/steuerreport/usertransfer")
    / "Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv"
)


def _copy_preview_db(db_path: Path) -> Path:
    target = Path(tempfile.gettempdir()) / "steuerreport_v2_wallet_month_preview.duckdb"
    if target.exists():
        target.unlink()
    shutil.copy2(db_path, target)
    return target


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    wallet_path = Path(args.wallet_month)
    preview_db = _copy_preview_db(db_path)
    store = DuckDbStore(preview_db)
    importer = FileRawImporter(CsvRawImporter(store))
    content = base64.b64encode(wallet_path.read_bytes()).decode("ascii")
    preview = importer.preview_base64("helium", wallet_path.name, content)
    batch = importer.import_base64("helium", wallet_path.name, content)
    events, report = RawNormalizer(store).normalize_batch_with_report(batch.batch_id)

    count_by_asset = Counter(event.asset for event in events)
    count_by_asset_year = Counter((event.asset, event.event_time.year) for event in events)
    quantity_by_asset: defaultdict[str, Decimal] = defaultdict(Decimal)
    for event in events:
        quantity_by_asset[event.asset] += event.quantity

    pipeline = PipelineService(store).rebuild_all()
    gate = ReviewService(store).gate()
    coverage = PriceCoverageService(store).report()
    print(
        json.dumps(
            {
                "mode": "preview",
                "preview_db": str(preview_db),
                "source_file": str(wallet_path),
                "file_preview": {
                    "rows": preview.row_count,
                    "can_import": preview.can_import,
                    "missing_required_groups": preview.missing_required_groups,
                },
                "batch": {
                    "batch_id": batch.batch_id,
                    "raw_objects": batch.raw_object_count,
                },
                "normalization": {
                    "raw_objects": report.raw_objects,
                    "created_events": report.created_events,
                    "skipped_raw_objects": report.skipped_raw_objects,
                },
                "events_by_asset": dict(count_by_asset),
                "events_by_asset_year": {
                    f"{asset}:{year}": count
                    for (asset, year), count in sorted(count_by_asset_year.items())
                },
                "quantity_by_asset": {
                    asset: str(quantity)
                    for asset, quantity in sorted(quantity_by_asset.items())
                },
                "pipeline": pipeline.model_dump(mode="json"),
                "review": {
                    "allow_export": gate.allow_export,
                    "issues_open": gate.issues_open,
                },
                "price_coverage": {
                    "missing_count": coverage.missing_count,
                    "missing_assets": coverage.missing_assets,
                },
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simuliert den Helium-Wallet-Monatsimport auf einer temporaeren Datenbank."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet-month", default=str(DEFAULT_WALLET_MONTH))
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
