from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.bmf_fifo_staging import BmfFifoStagingRunRequest
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_fifo_staging import BmfCombinedFifoStagingService
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.tax import TaxService


def _staging_store(tmp_path) -> DuckDbStore:
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    mining_at = datetime(2024, 12, 1, tzinfo=timezone.utc)
    swap_at = datetime(2025, 1, 15, tzinfo=timezone.utc)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=mining_at,
                event_type="mining",
                asset="HNT",
                quantity=Decimal("10"),
                wallet="own-wallet",
                tx_id="mining-tx",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=swap_at,
                event_type="trade",
                asset="JUP",
                quantity=Decimal("10"),
                quote_asset="HNT",
                quote_quantity=Decimal("5"),
                wallet="own-wallet",
                tx_id="swap-tx",
            ),
        ]
    )
    for point in (
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1"),
            priced_at=mining_at,
            source="unit",
        ),
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=swap_at,
            source="unit",
        ),
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1.5"),
            priced_at=swap_at,
            source="unit",
        ),
    ):
        store.add_price_point(point)
    TaxService(store).rebuild_fifo()
    return store


def test_bmf_combined_fifo_staging_is_read_only_and_separates_effects(tmp_path):
    store = _staging_store(tmp_path)
    service = BmfCombinedFifoStagingService(
        store,
        artifact_root=tmp_path / "bmf-fifo-staging",
    )
    before_lots = TaxService(store).list_tax_lots()
    before_lines = TaxService(store).list_tax_lines()

    report = service.run(
        BmfFifoStagingRunRequest(
            years=[2024, 2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )

    assert report.status == "blocked"
    assert report.read_only is True
    assert report.strict_ready is False
    assert report.productive_tax_tables_unchanged is True
    assert report.active_global.gain_loss_eur == Decimal("5")
    assert report.received_first_global.gain_loss_eur == Decimal("10")
    assert report.active_wallet.gain_loss_eur == Decimal("5")
    assert report.received_first_wallet.gain_loss_eur == Decimal("10")
    assert report.price_policy_delta_eur == Decimal("5")
    assert report.wallet_scope_delta_eur == Decimal("0")
    assert report.combined_delta_eur == Decimal("5")
    assert report.interaction_delta_eur == Decimal("0")
    assert report.potential_business_inventory_tax_lines_count == 1
    assert report.unresolved_reward_origin_tax_lines_count == 0
    hnt_sphere = next(
        row
        for row in report.sphere_rows
        if row.asset == "HNT"
        and row.classification == "potential_business_inventory"
    )
    assert hnt_sphere.tax_lines_count == 1
    assert hnt_sphere.gain_loss_eur == Decimal("10")
    assert report.top_events[0].tx_id == "swap-tx"
    assert report.top_events[0].origin_classifications == [
        "potential_business_inventory"
    ]
    assert service.latest() is not None
    assert TaxService(store).list_tax_lots() == before_lots
    assert TaxService(store).list_tax_lines() == before_lines


def test_bmf_combined_fifo_staging_api_run_and_latest(tmp_path):
    store = _staging_store(tmp_path)
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/tax/bmf-combined-fifo-staging/run",
        json={
            "years": [2024, 2025],
            "as_of": "2025-12-31T23:59:59Z",
            "limit": 20,
        },
    )
    latest = client.get("/api/v1/tax/bmf-combined-fifo-staging/latest")

    assert response.status_code == 200
    assert Decimal(response.json()["data"]["combined_delta_eur"]) == Decimal("5")
    assert latest.status_code == 200
    assert latest.json()["data"]["run_id"] == response.json()["data"]["run_id"]


def test_onchain_reward_origin_is_potential_business_inventory():
    classification, _reason = BusinessRewardInventoryReviewService.classify_origin(
        "solana_rpc",
        "reward",
    )

    assert classification == "potential_business_inventory"
