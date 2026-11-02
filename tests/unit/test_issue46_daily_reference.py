from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget_strategy_reconstruction import BitgetStrategyBasisReconstructionService
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.bmf_compliance import BmfComplianceMatrixService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.valuation_validity import PRICE_GATE_VERSION, project_valuation_validity
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


AT = datetime(2025, 6, 13, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("source", [
    "coingecko:usd_eur:v1_fx_cache:as_of_gate:2025-06-13:fx_date=2025-06-12",
    "defillama_history:usd_eur:v1_fx_cache:2025-06-13:fx_date=2025-06-12",
    "bmf_event_price_anchor:v1:provider_ts=2025-06-13T12:00:00Z",
    "stablecoin_fx_anchor:v1_fx_cache:2025-06-12",
    "bitget_strategy_basis_anchor:v1:stablecoin_usd_parity:usd_eur:frankfurter_v2_ecb:requested_date:2025-06-13:rate_date:2025-06-12:response_sha256:abc",
])
@pytest.mark.parametrize("value", [None, Decimal("0.00001"), Decimal("100")])
def test_known_daily_reference_blocks_even_below_materiality(tmp_path, source, value):
    service = DivorceEqualizationService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    position = SimpleNamespace(asset="BTC", value_eur=value, priced_at=AT.replace(hour=0), price_source=source)
    gate = service._valuation_gate([position], AT, Decimal("1"))
    assert not gate.strict_ready
    assert gate.unverified_daily_reference_count == 1
    assert gate.affected_assets == ["BTC"]
    assert service._price_status(priced_at=position.priced_at, price_source=source, valuation_at=AT)[1] == "unverified_daily_reference"


def test_other_same_day_source_retains_existing_behavior(tmp_path):
    service = DivorceEqualizationService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    position = SimpleNamespace(asset="BTC", value_eur=Decimal("100"), priced_at=AT, price_source="synthetic")
    assert service._valuation_gate([position], AT, Decimal("1")).strict_ready


@pytest.mark.parametrize("payload", [
    {"status": "strict_ready", "strict_ready": True},
    {"status": "strict_ready", "strict_ready": True, "strict_bmf_ready": True},
    {"status": "strict_ready", "strict_ready": True, "price_gate_version": "future_version"},
    {"status": "strict_ready", "strict_ready": True, "price_gate_version": "known_daily_references_v1"},
])
def test_legacy_projection_preserves_historical_values_and_blocks_bmf(tmp_path, payload):
    import json
    path = tmp_path / "legacy.json"
    original = json.dumps(payload).encode()
    path.write_bytes(original)
    projected = project_valuation_validity(payload)
    assert projected["historical_strict_ready"] is True
    assert projected["historical_status"] == "strict_ready"
    assert projected["strict_ready"] is False and projected["status"] == "blocked"
    assert not BmfComplianceMatrixService._artifact_state(path, valuation_gate=True)["strict_ready"]
    assert path.read_bytes() == original


def test_versioned_projection_does_not_override_run():
    payload = {"status": "strict_ready", "strict_ready": True, "price_gate_version": PRICE_GATE_VERSION}
    result = project_valuation_validity(payload)
    assert result["strict_ready"] is True
    assert result["current_validity"] == "versioned_gate"


@pytest.mark.parametrize("quantity", [Decimal("0.00001"), Decimal("2")])
@pytest.mark.parametrize("fx_date", [date(2025, 6, 12), date(2025, 6, 13)])
def test_bitget_anchor_blocks_gate_but_direct_price_readers_remain_unprotected(
    tmp_path, quantity, fx_date
):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_canonical_events([CanonicalEventCreate(
        source="synthetic", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_type="transfer", asset="USDT", quantity=quantity, account="wallet",
    )])
    source = BitgetStrategyBasisReconstructionService._reference_price_source(
        requested_date=AT.date(), rate_date=fx_date, response_sha256="a" * 64,
    )
    point = store.add_price_point(PricePointCreate(
        asset="USDT", price_eur=Decimal("0.9"), priced_at=AT.replace(hour=0),
        source=source,
    ))
    BalanceLedgerBuilder(store).rebuild()

    # These readers still select the anchor; this test documents the open risk.
    assert HistoricalPriceLookup(store).at_or_before("USDT", AT).price_id == point.price_id
    assert store.latest_price_points()["USDT"].price_id == point.price_id
    position = PortfolioService(store).as_of_snapshot(AT).positions[0]
    assert position.price_source == source
    assert position.value_eur == quantity * Decimal("0.9")

    response = TestClient(create_app(store)).get(
        "/api/v1/prices/as-of-gate", params={"as_of": AT.isoformat()},
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["strict_ready"] is False
    assert result["gate"]["unverified_daily_reference_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["current_price_source"] == source
    assert candidate["current_price_status"] == "unverified_daily_reference"
    assert candidate["daily_reference_date"] == "2025-06-13"
    assert candidate["observed_price_at"] is None
    assert candidate["fx_time_evidence"] == "not_verified"
