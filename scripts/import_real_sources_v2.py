#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
USERTRANSFER = Path("/workspace/steuerreport/usertransfer")


@dataclass(frozen=True)
class ImportCandidate:
    source: str
    path: Path


def curated_candidates(root: Path = USERTRANSFER) -> list[ImportCandidate]:
    candidates: list[ImportCandidate] = []

    # Binance/export 2021 is the active primary export set for the curated
    # import. Older root/legacy copies and account-statement pivots stay
    # reference unless a dedicated reviewed importer handles a narrow subset.
    binance_export = root / "Binance" / "export 2021"
    for path in sorted(binance_export.glob("Binance-*.xlsx")):
        if "C2C-Order-History" in path.name:
            continue
        candidates.append(ImportCandidate("binance", path))

    # V1 docs identify these root files as the canonical Pionex export set.
    # The generated year folders miss the 2021-12-25 opening deposit/trades.
    pionex_root = root / "pionex"
    for filename in ("deposit-withdraw.csv", "dust-collector.csv", "raw-trading-details.csv"):
        path = pionex_root / filename
        if path.exists():
            candidates.append(ImportCandidate("pionex", path))

    # Bitget exports contain overlapping ledgers. Spot Financial Record is the
    # complete spot balance ledger; Spot Trading and Deposit-Withdrawal are
    # supporting proofs and would create incomplete or duplicate movements.
    # Futures Financial Record is the cash-settlement ledger for derivatives.
    bitget_trade_record = root / "bitget" / "support"
    for filename in ("Spot Financial Record.csv", "Futures Financial Record.csv"):
        path = bitget_trade_record / filename
        if path.exists():
            candidates.append(ImportCandidate("bitget", path))

    # Helium uses the consolidated Fairspot-style raw export as active primary
    # evidence. Older yearly raw/CoinTracking files and monthly Heliumtracker
    # reward reports overlap by TXID or are reference-only in V1 audits.
    helium_raw = root / "Helium" / "helium-1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV-all-raw_12122024.csv"
    if helium_raw.exists():
        candidates.append(ImportCandidate("helium", helium_raw))

    # The Heliumtracker 2021 workbook is kept as a narrow transfer-list proof
    # for legacy HNT movements, not as a broad reward source.
    helium_transfers = root / "legacy_daten" / "Heliumtracker" / "advance" / "Heliumtracker 2021.xlsx"
    if helium_transfers.exists():
        candidates.append(ImportCandidate("helium", helium_transfers))

    return candidates


def backup_database(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_real_sources_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def preview_database(db_path: Path) -> Path:
    if not db_path.exists():
        return db_path
    target = Path(tempfile.gettempdir()) / f"{db_path.stem}_real_sources_preview{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def preview_candidate(importer: FileRawImporter, candidate: ImportCandidate) -> dict[str, object]:
    content = base64.b64encode(candidate.path.read_bytes()).decode("ascii")
    preview = importer.preview_base64(candidate.source, candidate.path.name, content)
    return {
        "source": candidate.source,
        "path": str(candidate.path),
        "rows": preview.row_count,
        "can_import": preview.can_import,
        "missing": preview.missing_required_groups,
        "sheet": preview.sheet_name,
        "columns": preview.columns[:12],
    }


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    store_path = db_path if args.execute else preview_database(db_path)
    store = DuckDbStore(store_path)
    importer = FileRawImporter(CsvRawImporter(store))
    candidates = curated_candidates(Path(args.usertransfer))

    previews = [preview_candidate(importer, candidate) for candidate in candidates]
    skipped_empty = [item for item in previews if item["rows"] == 0]
    rejected = [item for item in previews if item["rows"] != 0 and not item["can_import"]]
    accepted = [item for item in previews if item["can_import"] and item["rows"] != 0]

    print(
        json.dumps(
            {
                "mode": "execute" if args.execute else "dry-run",
                "accepted": accepted,
                "skipped_empty": skipped_empty,
                "rejected": rejected,
            },
            indent=2,
        )
    )
    if rejected:
        return 2
    if not args.execute:
        return 0

    backup = backup_database(db_path)
    if args.replace_sources:
        for source in ("binance", "pionex", "helium", "bitget"):
            store.delete_import_batches_by_source(source)
    if args.clear_demo:
        store.delete_import_batches_by_source("demo")
        store.delete_price_points_by_source("demo")

    imported: list[dict[str, object]] = []
    accepted_paths = {item["path"] for item in accepted}
    for candidate in candidates:
        if str(candidate.path) not in accepted_paths:
            continue
        content = base64.b64encode(candidate.path.read_bytes()).decode("ascii")
        batch = importer.import_base64(candidate.source, candidate.path.name, content)
        imported.append(
            {
                "batch_id": batch.batch_id,
                "source": batch.source,
                "filename": batch.filename,
                "raw_objects": batch.raw_object_count,
            }
        )

    pipeline = PipelineService(store).rebuild_all()
    print(
        json.dumps(
            {
                "backup": str(backup) if backup is not None else None,
                "imported": imported,
                "pipeline": pipeline.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Importiert kuratierte reale Steuerreport-V2-Quellen.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--usertransfer", default=str(USERTRANSFER))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--clear-demo", action="store_true", default=True)
    parser.add_argument("--replace-sources", action="store_true", default=True)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
