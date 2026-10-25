#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.pionex_reconciliation import (
    PionexHntReconciliationService,
)
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_CONFIG = PROJECT_ROOT / "configs/pionex_hnt_reconciliation.json"
DEFAULT_SOURCE_DIR = Path("/workspace/steuerreport/usertransfer/pionex")
DEFAULT_BACKUP_DIR = Path("/root/steuerreport_v2_backups")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_pionex_batches(config: dict[str, object]) -> dict[str, str]:
    source_files = config["source_files"]
    raw = source_files["raw_trading_details"]
    return {
        "deposit-withdraw.csv": "sha256:a2efec5498ebf77ff4f2c0ce7b796818cffc87970302f3cbd43f27cd5ffab21e",
        "dust-collector.csv": "sha256:5c708492eabd555186eba2441f83addf5799abf9e199daf9b4bf98d629d8bb4d",
        str(raw["filename"]): f"sha256:{raw['sha256']}",
    }


def _validate_current_batches(
    store: DuckDbStore, expected: dict[str, str]
) -> list[dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select b.filename, b.file_hash, count(r.raw_object_id)
            from raw_import_batches b
            left join raw_objects r using(batch_id)
            where lower(b.source) = 'pionex'
            group by b.filename, b.file_hash
            order by b.filename
            """
        ).fetchall()
    actual = {str(row[0]): str(row[1]) for row in rows}
    if actual != expected:
        raise RuntimeError(
            "unexpected_pionex_batches:"
            + json.dumps({"expected": expected, "actual": actual}, sort_keys=True)
        )
    return [
        {"filename": str(row[0]), "file_hash": str(row[1]), "raw_objects": int(row[2])}
        for row in rows
    ]


def _backup(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_pionex_hnt_reconciliation_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    if target.stat().st_size != db_path.stat().st_size or _sha256(target) != _sha256(db_path):
        target.unlink(missing_ok=True)
        raise RuntimeError("backup_integrity_failed")
    return target


def _import_file(
    importer: FileRawImporter, *, source: str, path: Path
) -> dict[str, object]:
    batch = importer.import_base64(
        source,
        path.name,
        base64.b64encode(path.read_bytes()).decode("ascii"),
    )
    return {
        "batch_id": batch.batch_id,
        "source": batch.source,
        "filename": batch.filename,
        "raw_objects": batch.raw_object_count,
    }


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    config_path = Path(args.config)
    source_dir = Path(args.source_dir)
    config_sha = _sha256(config_path)
    if args.execute and args.expected_config_sha256 != config_sha:
        raise RuntimeError(
            f"config_sha_mismatch:expected={args.expected_config_sha256}:actual={config_sha}"
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    store = DuckDbStore(db_path)
    service = PionexHntReconciliationService(
        store,
        config_path=config_path,
        source_dir=source_dir,
    )
    before = service.report()
    current_batches = _validate_current_batches(
        store, _expected_pionex_batches(config)
    )
    print(
        json.dumps(
            {
                "mode": "execute" if args.execute else "dry-run",
                "config_sha256": config_sha,
                "current_batches": current_batches,
                "preflight": before.model_dump(mode="json"),
            },
            indent=2,
            default=str,
        ),
        flush=True,
    )
    if not before.preflight_ready:
        raise RuntimeError("pionex_reconciliation_preflight_not_ready")
    if not args.execute:
        return 0

    backup = _backup(db_path, Path(args.backup_dir))
    try:
        store.delete_import_batches_by_source("pionex")
        importer = FileRawImporter(CsvRawImporter(store))
        imported = [
            _import_file(importer, source="pionex", path=source_dir / filename)
            for filename in (
                "deposit-withdraw.csv",
                "dust-collector.csv",
                str(config["source_files"]["raw_trading_details"]["filename"]),
            )
        ]
        adjustment_path = config_path.parent / str(config["adjustment"]["filename"])
        imported.append(
            _import_file(importer, source=str(config["adjustment"]["source"]), path=adjustment_path)
        )
        pipeline = PipelineService(store).rebuild_all()
        after = service.report()
        gate = ReviewService(store).gate()
        if not after.reconciliation_ready:
            raise RuntimeError("pionex_reconciliation_postcheck_not_ready")
        if not gate.allow_export:
            raise RuntimeError("review_gate_not_ready_after_pionex_reconciliation")
    except Exception:
        shutil.copy2(backup, db_path)
        raise
    print(
        json.dumps(
            {
                "backup": str(backup),
                "backup_size_bytes": backup.stat().st_size,
                "backup_sha256": _sha256(backup),
                "imported": imported,
                "pipeline": pipeline.model_dump(mode="json"),
                "reconciliation": after.model_dump(mode="json"),
                "review_gate": gate.model_dump(mode="json"),
            },
            indent=2,
            default=str,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wendet die SHA-gebundene Pionex-HNT-Minimalreconciliation an."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-config-sha256", default="")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
