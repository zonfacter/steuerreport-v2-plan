from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.product_readiness import ProductReadinessService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _seed_binance_position(store: DuckDbStore) -> None:
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="product-readiness.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T00:00:00Z,USDT,10,deposit,Spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:USDT:test",
                connector_id="binance",
                asset="USDT",
                quantity=Decimal("10"),
                source="unit-test",
                fetched_at=priced_at,
            )
        ]
    )


def test_product_readiness_reports_existing_sources_and_setup_blockers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_binance_position(store)

    report = ProductReadinessService(store).report()

    assert report.overall_status == "setup_required"
    assert report.can_prepare_tax_report is False
    assert any(check.key == "sources_connected" and check.status == "blocker" for check in report.checks)
    assert any(source.source_id == "binance" for source in report.sources)
    assert report.setup_required_sources >= 1
    assert "keine Connectoren abgefragt" in report.methodology


def test_product_readiness_api_route_returns_report(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    app = create_app(store)
    client = TestClient(app)

    response = client.get("/api/v1/product/readiness")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["overall_status"] in {"ready", "review", "blocked", "setup_required"}
    assert "checks" in payload
    assert "sources" in payload


def test_product_readiness_treats_conservative_ready_years_as_info(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = ProductReadinessService(store)

    check = service._tax_years_check(
        "available",
        SimpleNamespace(
            blocked_years=[],
            review_years=[],
            conservative_appendix_years=[2021, 2022, 2023, 2024, 2025],
            ready_years=[],
        ),
    )

    assert check.status == "info"
    assert check.count == 0
    assert "konservativ abgabefaehig" in check.detail
