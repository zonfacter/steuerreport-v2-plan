"""Isolierte Altersdiagnose, kein neuer zugelassener Bewertungsweg."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.portfolio import PortfolioPosition
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup, LastKnownPriceDiagnostic
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


AT = datetime(2025, 7, 1, 12, tzinfo=timezone.utc)


def _price(store, *, at=AT, value="7", source="fixture:primary"):
    return store.add_price_point(PricePointCreate(
        asset="BTC", priced_at=at, price_eur=Decimal(value), source=source))


def _store(tmp_path):
    store = DuckDbStore(tmp_path / "diagnostics.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="fixture", account="wallet", event_time=AT - timedelta(days=1),
        event_type="transfer", asset="BTC", quantity=Decimal("1")))
    BalanceLedgerBuilder(store).rebuild()
    return store


@pytest.mark.parametrize("days,status", [(1642, "stale"), (1, "prior_day")])
@pytest.mark.parametrize("value", ["7", "0.00000001"])
def test_old_reference_classifies_gap_but_never_values_or_exempts_position(tmp_path, days, status, value):
    store = _store(tmp_path)
    point = _price(store, at=AT - timedelta(days=days), value=value)
    lookup = HistoricalPriceLookup(store)
    diagnostic = lookup.last_known_for_diagnostics("btc", AT)
    assert isinstance(diagnostic, LastKnownPriceDiagnostic)
    assert diagnostic.policy_id == "diagnostic_last_known_non_derived_not_after"
    assert diagnostic.policy_version == 1
    assert diagnostic.asset == "BTC"
    assert diagnostic.cutoff == AT
    assert diagnostic.point.price_id == point.price_id
    assert lookup.at_or_before("BTC", AT, allow_derived=False) is None

    portfolio_service = PortfolioService(store)
    snapshot = portfolio_service.as_of_snapshot(AT)
    before = snapshot.model_dump(mode="json")
    gate = DivorceEqualizationService(store)._valuation_gate(snapshot.positions, AT, Decimal("1"))
    report = AsOfPriceGateService(store).report(as_of=AT, materiality_threshold_eur=Decimal("1"))
    candidate = report.candidates[0]
    assert candidate.current_price_status == status
    assert candidate.current_price_age_days == days
    assert candidate.current_priced_at == point.priced_at.replace(tzinfo=timezone.utc)
    assert candidate.current_price_source == point.source
    assert candidate.current_price_eur == Decimal(value)
    assert candidate.value_eur == Decimal("0")  # Existing field, not quantity * diagnostic price.
    assert "nur zur Altersdiagnose" in candidate.reason
    assert not gate.strict_ready
    assert not report.strict_ready
    assert report.gate.material_positions_count == 1
    assert report.gate.affected_assets == ["BTC"]
    assert report.requirements_count == 1
    assert snapshot.positions[0].price_eur is None
    assert snapshot.positions[0].value_eur is None
    assert snapshot.total_value_eur == 0
    assert snapshot.missing_price_assets == ["BTC"]
    assert snapshot.model_dump(mode="json") == before
    assert portfolio_service.as_of_snapshot(AT).model_dump(mode="json") == before


@pytest.mark.parametrize("offset,value,source", [
    (timedelta(seconds=1), "7", "fixture:future"),
    (timedelta(days=-1642), "7", " \tDeRiVeD:event_quote"),
    (timedelta(days=-1642), "0", "fixture:zero"),
    (timedelta(days=-1642), "-7", "fixture:negative"),
])
def test_unusable_or_future_points_remain_missing_not_stale(tmp_path, offset, value, source):
    store = _store(tmp_path)
    _price(store, at=AT + offset, value=value, source=source)
    assert HistoricalPriceLookup(store).last_known_for_diagnostics("BTC", AT).point is None
    report = AsOfPriceGateService(store).report(as_of=AT)
    assert report.candidates[0].current_price_status == "missing"
    assert report.candidates[0].current_price_eur is None
    assert report.gate.missing_price_count == 1
    assert report.gate.stale_price_count == 0
    assert not report.strict_ready


def test_diagnostic_ignores_newer_derived_nonpositive_and_future_quotes(tmp_path):
    store = _store(tmp_path)
    primary = _price(store, at=AT - timedelta(days=1642))
    _price(store, at=AT, source="derived:event_quote", value="999")
    _price(store, at=AT, source="fixture:zero", value="0")
    _price(store, at=AT + timedelta(microseconds=1), source="fixture:future", value="999")
    lookup = HistoricalPriceLookup(store)
    assert lookup.last_known_for_diagnostics("BTC", AT).point.price_id == primary.price_id
    assert lookup.at_or_before("BTC", AT, allow_derived=False) is None
    # Existing permitted same-day derived behavior is not silently removed from tax lookup.
    assert lookup.at_or_before("BTC", AT).source == "derived:event_quote"
    assert AsOfPriceGateService(store).report(as_of=AT).candidates[0].current_price_status == "stale"


def test_diagnostic_eur_identity_and_current_primary_remain_separate(tmp_path):
    store = _store(tmp_path)
    point = _price(store)
    lookup = HistoricalPriceLookup(store)
    assert lookup.last_known_for_diagnostics("EUR", AT).point.price_eur == 1
    assert lookup.last_known_for_diagnostics("USD", AT).point is None
    assert lookup.last_known_for_diagnostics("BTC", AT).point.price_id == point.price_id
    assert lookup.at_or_before("BTC", AT).price_id == point.price_id
    report = AsOfPriceGateService(store).report(as_of=AT)
    assert report.candidates[0].current_price_status == "same_day"
    assert report.candidates[0].value_eur == Decimal("7")
    assert report.strict_ready


def test_current_diagnostic_never_fills_an_unpriced_snapshot_or_opens_gate(tmp_path):
    store = _store(tmp_path)
    _price(store)
    unpriced = PortfolioPosition(account="wallet", asset="BTC", quantity=Decimal("1"))
    gate = DivorceEqualizationService(store)._valuation_gate([unpriced], AT, Decimal("1"))
    assert gate.missing_price_count == 1
    assert not gate.strict_ready
    assert unpriced.price_eur is None and unpriced.value_eur is None


def test_stale_diagnostic_keeps_tax_coverage_review_and_export_blocked(tmp_path):
    store = DuckDbStore(tmp_path / "tax.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="fixture", account="wallet", event_time=AT - timedelta(days=1),
        event_type="trade", asset="BTC", quantity=Decimal("10"),
        quote_asset="EUR", quote_quantity=Decimal("20")))
    store.add_canonical_event(CanonicalEventCreate(
        source="fixture", account="wallet", event_time=AT,
        event_type="trade", asset="BTC", quantity=Decimal("-4")))
    _price(store, at=AT - timedelta(days=1642))
    BalanceLedgerBuilder(store).rebuild()
    portfolio_before = PortfolioService(store).as_of_snapshot(AT)
    lookup = HistoricalPriceLookup(store)
    assert lookup.last_known_for_diagnostics("BTC", AT).point is not None
    assert lookup.at_or_before("BTC", AT) is None
    assert lookup.explain("BTC", AT).selected_price is None
    assert PriceCoverageService(store).report().missing_count == 1
    assert PriceCoverageService(store).requirements().requirements_count == 1
    tax = TaxService(store).rebuild_fifo()
    # Independent algebra 4/10 * 20 = 8 basis; no admitted disposal price.
    assert tax.tax_lines[0].acquisition_cost_eur == Decimal("8")
    assert tax.tax_lines[0].disposal_proceeds_eur == Decimal("0")
    assert not ReviewService(store).gate().allow_export
    assert not ExportService(store).readiness().allow_export
    report = AsOfPriceGateService(store).report(as_of=AT)
    assert report.gate.stale_price_count == 1
    assert not report.strict_ready
    portfolio_after = PortfolioService(store).as_of_snapshot(AT)
    # The EUR purchase leg remains -20; six unpriced BTC contribute no fabricated value.
    assert portfolio_after.total_value_eur == Decimal("-20")
    btc = next(position for position in portfolio_after.positions if position.asset == "BTC")
    assert btc.quantity == Decimal("6") and btc.value_eur is None and btc.price_eur is None
    assert portfolio_after.model_dump(mode="json") == portfolio_before.model_dump(mode="json")
