from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.tax import TaxService


def _event(
    *,
    source: str,
    event_time: datetime,
    event_type: str,
    asset: str,
    quantity: str,
    quote_quantity: str,
    account: str,
) -> CanonicalEventCreate:
    return CanonicalEventCreate(
        source=source,
        event_time=event_time,
        event_type=event_type,
        asset=asset,
        quantity=Decimal(quantity),
        quote_asset="EUR",
        quote_quantity=Decimal(quote_quantity),
        account=account,
    )


def _seed_reward_origins(store: DuckDbStore) -> None:
    store.add_canonical_events(
        [
            _event(
                source="helium",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="mining",
                asset="HNT",
                quantity="10",
                quote_quantity="20",
                account="legacy-wallet",
            ),
            _event(
                source="helium",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity="-5",
                quote_quantity="15",
                account="legacy-wallet",
            ),
            _event(
                source="solana_rpc",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="IOT",
                quantity="100",
                quote_quantity="4",
                account="solana-wallet",
            ),
            _event(
                source="solana_rpc",
                event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="IOT",
                quantity="-100",
                quote_quantity="1",
                account="solana-wallet",
            ),
            _event(
                source="binance",
                event_time=datetime(2024, 5, 1, tzinfo=timezone.utc),
                event_type="staking",
                asset="MOBILE",
                quantity="100",
                quote_quantity="10",
                account="Spot",
            ),
            _event(
                source="binance",
                event_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="MOBILE",
                quantity="-100",
                quote_quantity="5",
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()


def test_business_reward_inventory_review_classifies_origin_spheres_read_only(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_reward_origins(store)
    tax_service = TaxService(store)
    line_count_before = len(tax_service.list_tax_lines())
    lot_count_before = len(tax_service.list_tax_lots())

    report = BusinessRewardInventoryReviewService(store).review()

    by_asset = {row.asset: row for row in report.rows}
    assert report.strict_ready is False
    assert report.affected_years == [2024]
    assert report.total_tax_lines_count == 3
    assert report.potential_business_tax_lines_count == 1
    assert report.unresolved_tax_lines_count == 2
    assert by_asset["HNT"].classification == "potential_business_inventory"
    assert by_asset["HNT"].gain_loss_eur == Decimal("5.000000000000000000")
    assert by_asset["IOT"].classification == "origin_classification_review"
    assert by_asset["MOBILE"].classification == "separate_income_review"
    assert len(tax_service.list_tax_lines()) == line_count_before
    assert len(tax_service.list_tax_lots()) == lot_count_before


def test_business_reward_inventory_review_api_endpoint(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_reward_origins(store)

    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/business-reward-inventory-review"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["strict_ready"] is False
    assert data["potential_business_tax_lines_count"] == 1
    assert any(row["asset"] == "HNT" for row in data["rows"])
