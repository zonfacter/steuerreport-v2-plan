from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pionex_reconciliation import (
    PionexHntReconciliationService,
)
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[DuckDbStore, Path, Path]:
    source_dir = tmp_path / "pionex"
    source_dir.mkdir()
    raw_path = source_dir / "raw-trading-details.csv"
    raw_path.write_text(
        "date(UTC+0),executed_qty,amount,price,order_type,side,symbol,state,fee,fee_coin,market_type,tax_id\n"
        "2022-01-01 00:00:00,1,10,10,LIMIT,BUY,HNT_USDT,FILLED,0.1,HNT,Spot,s_1\n"
        "2022-01-02 00:00:00,1,12,12,LIMIT,SELL,HNT_USDT,CANCELED,0.01,USDT,Spot,s_2\n",
        encoding="utf-8",
    )
    summary_path = source_dir / "trading.csv"
    summary_path.write_text(
        "date(UTC+0),executed_qty,amount,price,side,symbol,fee,fee_coin,market_type,tax_id\n"
        "2022-01-01 00:00:00,1,10,10,BUY,HNT_USDT,0.1,HNT,Spot,s_1\n"
        "2022-01-02 00:00:00,1,12,12,SELL,HNT_USDT,0.01,USDT,Spot,s_2\n",
        encoding="utf-8",
    )
    adjustment_path = tmp_path / "pionex-hnt-adjustment.csv"
    adjustment_path.write_text(
        "time,asset,amount,account,type,quote_asset,quote_quantity,tx_id,note\n"
        "2022-01-01T23:59:59Z,HNT,0.1,pionex,opening transfer,EUR,0,"
        "pionex-hnt-test-reconciliation,conservative test reconciliation\n",
        encoding="utf-8",
    )
    probe_path = tmp_path / "pionex-api-probe.json"
    probe_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "success",
                "rows_count": 0,
                "history_available": False,
                "contains_credentials": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "pionex-reconciliation.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": True,
                "account": "pionex",
                "asset": "HNT",
                "source_files": {
                    "raw_trading_details": {
                        "filename": raw_path.name,
                        "sha256": _sha256(raw_path),
                        "rows": 2,
                    },
                    "trading_summary": {
                        "filename": summary_path.name,
                        "sha256": _sha256(summary_path),
                        "rows": 2,
                    },
                    "aggregate_groups": 2,
                },
                "executed_canceled_partials": {
                    "count": 1,
                    "buy_quantity": "0",
                    "sell_quantity": "1",
                    "base_fee_quantity": "0",
                    "net_quantity": "-1",
                },
                "historical_api_probe": {
                    "filename": probe_path.name,
                    "sha256": _sha256(probe_path),
                    "expected_rows": 0,
                    "history_available": False,
                },
                "deficit_event_time": "2022-01-02T00:00:00Z",
                "adjustment": {
                    "source": "opening-balance",
                    "filename": adjustment_path.name,
                    "sha256": _sha256(adjustment_path),
                    "event_time": "2022-01-01T23:59:59Z",
                    "quantity": "0.1",
                    "quote_asset": "EUR",
                    "quote_quantity": "0",
                    "tx_id": "pionex-hnt-test-reconciliation",
                    "cost_basis_eur_total": "0",
                    "tax_treatment": (
                        "conservative_zero_cost_basis_missing_primary_acquisition_evidence"
                    ),
                    "classification": "documented_minimum_inventory_reconciliation",
                    "asserts_external_deposit": False,
                    "asserts_reward": False,
                },
                "adjusted_balance": {
                    "minimum_quantity": "0",
                    "final_quantity": "0",
                },
                "evidence_refs": ["unit-test"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)
    raw_batch = importer.import_text("pionex", raw_path.name, raw_path.read_text())
    adjustment_batch = importer.import_text(
        "opening-balance", adjustment_path.name, adjustment_path.read_text()
    )
    RawNormalizer(store).normalize_batch(raw_batch.batch_id)
    RawNormalizer(store).normalize_batch(adjustment_batch.batch_id)
    for priced_at in (
        datetime(2022, 1, 1, tzinfo=timezone.utc),
        datetime(2022, 1, 2, tzinfo=timezone.utc),
    ):
        store.add_price_point(
            PricePointCreate(
                asset="USDT",
                price_eur=Decimal("1"),
                priced_at=priced_at,
                source="unit",
            )
        )
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()
    return store, config_path, source_dir


def test_pionex_reconciliation_binds_partial_fills_and_zero_cost_lot(
    tmp_path, monkeypatch
):
    store, config_path, source_dir = _fixture(tmp_path)
    monkeypatch.setattr(
        PionexHntReconciliationService, "DEFAULT_CONFIG_PATH", config_path
    )
    monkeypatch.setattr(
        PionexHntReconciliationService, "DEFAULT_SOURCE_DIR", source_dir
    )

    report = PionexHntReconciliationService(store).report()

    assert report.status == "conservative_reconciliation_ready"
    assert report.preflight_ready is True
    assert report.reconciliation_ready is True
    assert report.wallet_fifo_ready is True
    assert report.strict_ready is False
    assert report.missing_primary_acquisition_evidence is True
    assert report.canceled_partial_fills_count == 1
    assert report.imported_canceled_events == 1
    assert report.balance_min_quantity == 0
    assert report.balance_final_quantity == 0
    assert report.zero_cost_lot_consumed_quantity == Decimal("0.1")
    assert report.zero_cost_lot_gain_loss_eur > 0
    assert all(report.decision_layer.model_dump().values())
    gate = ReviewService(store).gate()
    assert "zero_cost_tax_lots" not in {issue.code for issue in gate.issues}

    response = TestClient(create_app(store)).get(
        "/api/v1/tax/pionex-hnt-reconciliation"
    )
    assert response.status_code == 200
    assert response.json()["data"]["reconciliation_ready"] is True

    app = create_app(store)
    package_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )
    package_response = package_route.endpoint(2022)
    with ZipFile(BytesIO(package_response.body)) as package:
        reconciliation = json.loads(
            package.read(
                "06_Solana_FIFO_Belege/tax-year-2022-pionex-hnt-reconciliation.json"
            ).decode("utf-8")
        )
        manifest = json.loads(
            package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8")
        )
    assert reconciliation["reconciliation_ready"] is True
    assert reconciliation["missing_primary_acquisition_evidence"] is True
    assert "/api/v1/tax/pionex-hnt-reconciliation" in manifest["required_refs"]
    assert any(
        file["path"]
        == "06_Solana_FIFO_Belege/tax-year-2022-pionex-hnt-reconciliation.json"
        for file in manifest["files"]
    )


def test_pionex_reconciliation_is_ready_to_apply_before_database_import(
    tmp_path, monkeypatch
):
    _store, config_path, source_dir = _fixture(tmp_path)
    empty_store = DuckDbStore(tmp_path / "empty.duckdb")
    monkeypatch.setattr(
        PionexHntReconciliationService, "DEFAULT_CONFIG_PATH", config_path
    )
    monkeypatch.setattr(
        PionexHntReconciliationService, "DEFAULT_SOURCE_DIR", source_dir
    )

    report = PionexHntReconciliationService(empty_store).report()

    assert report.status == "ready_to_apply"
    assert report.preflight_ready is True
    assert report.reconciliation_ready is False
    assert report.decision_layer.database_primary_import_complete is False
    assert report.decision_layer.adjustment_event_bound is False
