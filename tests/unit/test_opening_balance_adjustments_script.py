import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_scoped_opening_adjustment_does_not_delete_base_opening_source(tmp_path):
    db_path = tmp_path / "steuerreport_v2.duckdb"
    store = DuckDbStore(db_path)
    importer = CsvRawImporter(store)
    importer.import_text(
        source="opening-balance",
        filename="existing.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2020-12-31T23:59:00Z,USDT,100,opening transfer,pionex\n"
        ),
    )
    importer.import_text(
        source="manual-csv",
        filename="solana-negative.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-01-01T00:00:00Z,SOL,-1,withdrawal,Solana\n"
        ),
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2020, 12, 31, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("80"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    PipelineService(store).rebuild_all()
    assert ReviewService(store).gate().allow_export is False

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/apply_opening_balance_adjustments_v2.py",
            "--db",
            str(db_path),
            "--execute",
            "--accounts",
            "Solana",
            "--assets",
            "SOL",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(proc.stdout)

    assert payload["scoped"] is True
    assert payload["source"].startswith("opening-balance-scope-")
    assert payload["deleted_existing"] == 0
    assert payload["adjustments"][0]["account"] == "Solana"
    assert payload["adjustments"][0]["asset"] == "SOL"

    refreshed = DuckDbStore(db_path)
    sources = {batch.source for batch in refreshed.list_import_batches()}
    assert "opening-balance" in sources
    assert payload["source"] in sources
    assert ReviewService(refreshed).gate().allow_export is True


def test_scoped_opening_adjustment_is_idempotent(tmp_path):
    db_path = tmp_path / "steuerreport_v2.duckdb"
    store = DuckDbStore(db_path)
    importer = CsvRawImporter(store)
    importer.import_text(
        source="manual-csv",
        filename="solana-negative.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-01-01T00:00:00Z,SOL,-1,withdrawal,Solana\n"
        ),
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("80"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    PipelineService(store).rebuild_all()

    command = [
        sys.executable,
        "scripts/apply_opening_balance_adjustments_v2.py",
        "--db",
        str(db_path),
        "--execute",
        "--accounts",
        "Solana",
        "--assets",
        "SOL",
    ]
    first = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    second = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["adjustments"][0]["amount"] == "1.000000000000000000"
    assert second_payload["deleted_existing"] == 1
    assert second_payload["adjustments"][0]["amount"] == "1.000000000000000000"
    assert ReviewService(DuckDbStore(db_path)).gate().allow_export is True
