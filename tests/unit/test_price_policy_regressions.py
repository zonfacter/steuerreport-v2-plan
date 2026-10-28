"""Eigene F02-Repros, kein exakter Replay nicht vorliegender V1/V2-Dateien."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.exports import PdfExportRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derived_prices import DerivedPriceService
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.flows import FlowService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.price_policy import SOURCE_WHITESPACE
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.valuation import PriceCoverageService


EVENT_TIME = datetime(2025, 7, 1, 12, tzinfo=timezone.utc)


def _price(store, *, asset="HNT", at=EVENT_TIME, value="7", source="fixture:EUR"):
    return store.add_price_point(PricePointCreate(
        asset=asset, price_eur=Decimal(value), priced_at=at, source=source,
    ))


def _event(store, *, at=EVENT_TIME, **kwargs):
    return store.add_canonical_event(CanonicalEventCreate(
        source="manual-test", event_time=at, account="fixture", **kwargs,
    ))


@pytest.mark.parametrize("offset", [timedelta(days=-1642), timedelta(seconds=1)])
def test_stale_or_future_price_cannot_finalize_real_service_chain(tmp_path, offset):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    _event(store, at=EVENT_TIME - timedelta(days=1), event_type="trade",
           asset="HNT", quantity=Decimal("10"), quote_asset="EUR", quote_quantity=Decimal("20"))
    disposal = _event(store, event_type="trade", asset="HNT", quantity=Decimal("-4"))
    _price(store, at=EVENT_TIME + offset)

    lookup = HistoricalPriceLookup(store).at_or_before("HNT", EVENT_TIME)
    coverage = PriceCoverageService(store).report()
    requirements = PriceCoverageService(store).requirements()
    tax = TaxService(store).rebuild_fifo()
    gate = ReviewService(store).gate()
    exports = ExportService(store)
    package = exports.create_pdf_packages(PdfExportRequest(label="F02-own-repro", estimated_pages=1))

    # Independent algebra: 4 / 10 * 20 = 8 EUR basis; no eligible proceeds.
    line = next(line for line in tax.tax_lines if line.source_event_id == disposal.event_id)
    observed = (lookup is None, coverage.missing_count, requirements.requirements_count,
                line.acquisition_cost_eur, line.disposal_proceeds_eur,
                gate.allow_export, package.blocked)
    assert observed == (True, 1, 1, Decimal("8"), Decimal("0"), False, True)
    assert coverage.missing[0].sample_event_ids == [disposal.event_id]
    assert requirements.requirements[0].price_date == EVENT_TIME.date()
    assert line.gain_loss_eur == Decimal("-8")  # Provisional, not a final tax conclusion.
    issue = next(issue for issue in gate.issues if issue.code == "missing_event_price")
    assert issue.blocks_export
    assert issue.scope == ("price_coverage:asset:HNT:year:2025:source:manual-test:"
                           "event_type:trade:role:asset")
    assert not exports.readiness().allow_export
    assert package.packages[0].status == "blocked"
    assert exports.render_pdf_package(package.packages[0].package_id) is None


@pytest.mark.parametrize("offset", [timedelta(days=-1642), timedelta(seconds=1)])
@pytest.mark.parametrize("direction", ["quote_to_asset", "asset_to_quote", "counterflow"])
def test_old_quote_cannot_be_laundered_into_fresh_derived_price(tmp_path, offset, direction):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    _price(store, asset="USDT", at=EVENT_TIME + offset, value="0.8")
    if direction == "quote_to_asset":
        _event(store, event_type="trade", asset="HNT", quantity=Decimal("10"),
               quote_asset="USDT", quote_quantity=Decimal("50"))
    elif direction == "asset_to_quote":
        _event(store, event_type="trade", asset="USDT", quantity=Decimal("-50"),
               quote_asset="HNT", quote_quantity=Decimal("10"))
    else:
        _event(store, event_type="trade", asset="USDT", quantity=Decimal("-50"))
        _event(store, event_type="trade", asset="HNT", quantity=Decimal("10"))
    # An independent HNT income event would otherwise consume the freshly laundered price.
    income = _event(store, event_type="income", asset="HNT", quantity=Decimal("2"))

    result = DerivedPriceService(store).rebuild_from_event_quotes()
    tax = TaxService(store).rebuild_fifo()
    coverage = PriceCoverageService(store).report()
    requirements = PriceCoverageService(store).requirements()
    gate = ReviewService(store).gate()
    exports = ExportService(store).create_pdf_packages(
        PdfExportRequest(label="F02-derived-own-repro", estimated_pages=1))

    income_lot = next(lot for lot in tax.lots if lot.source_event_id == income.event_id)
    observed = (result.created, HistoricalPriceLookup(store).at_or_before("HNT", EVENT_TIME),
                income_lot.cost_basis_eur_total, gate.allow_export, exports.blocked)
    assert observed == (0, None, Decimal("0"), False, True)
    assert not any(point.source == "derived:event_quote" for point in store.list_price_points())
    assert any(item.asset == "HNT" and item.event_type == "income" for item in coverage.missing)
    assert any(item.asset == "HNT" and item.price_date == EVENT_TIME.date()
               for item in requirements.requirements)
    assert any(issue.code == "missing_event_price" and "asset:HNT:" in issue.scope
               and "event_type:income:" in issue.scope and issue.blocks_export for issue in gate.issues)


@pytest.mark.parametrize("role", ["asset", "quote_asset", "fee_asset"])
@pytest.mark.parametrize("source", ["manual-test", "solana_rpc"])
@pytest.mark.parametrize("offset,value,price_source,accepted", [
    (timedelta(days=-1642), "7", "fixture:EUR", False),
    (timedelta(seconds=1), "7", "fixture:EUR", False),
    (timedelta(seconds=-1), "0", "fixture:EUR", False),
    (timedelta(seconds=-1), "-7", "fixture:EUR", False),
    (timedelta(seconds=-1), "7", "fixture:EUR", True),
    (timedelta(0), "7", "  DeRiVeD:event_quote", None),
])
def test_python_and_sql_coverage_apply_identical_policy_to_all_roles(
    tmp_path, role, source, offset, value, price_source, accepted,
):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    kwargs = dict(event_type="income", asset="HNT", quantity=Decimal("2"))
    if role == "quote_asset":
        kwargs.update(asset="TOKEN", quote_asset="HNT", quote_quantity=Decimal("2"))
    elif role == "fee_asset":
        kwargs.update(asset="EUR", fee_asset="HNT", fee_quantity=Decimal("2"))
    event = store.add_canonical_event(CanonicalEventCreate(
        source=source, event_time=EVENT_TIME, **kwargs))
    _price(store, at=EVENT_TIME + offset, value=value, source=price_source)
    service = PriceCoverageService(store)
    expected = accepted if accepted is not None else source != "solana_rpc"

    assert service._has_acceptable_price("HNT", event) is expected
    assert service.report().missing_count == (0 if expected else 1)
    assert service.requirements().requirements_count == (0 if expected else 1)
    if not expected:
        assert service.report().missing[0].role == role


def test_documented_eur_consideration_is_not_replaced_by_market_price(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    _event(store, at=EVENT_TIME - timedelta(days=1), event_type="trade", asset="HNT",
           quantity=Decimal("10"), quote_asset="EUR", quote_quantity=Decimal("20"))
    _event(store, event_type="trade", asset="HNT", quantity=Decimal("-4"),
           quote_asset="EUR", quote_quantity=Decimal("28"))
    _price(store, at=EVENT_TIME - timedelta(days=1642), value="999")

    tax = TaxService(store).rebuild_fifo()
    assert tax.tax_lines[0].acquisition_cost_eur == Decimal("8")
    assert tax.tax_lines[0].disposal_proceeds_eur == Decimal("28")
    assert tax.tax_lines[0].gain_loss_eur == Decimal("20")
    assert PriceCoverageService(store).report().missing_count == 0
    assert PriceCoverageService(store).requirements().requirements_count == 0


def test_solana_sql_and_python_reject_derived_sources_with_all_strip_characters(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    event = store.add_canonical_event(CanonicalEventCreate(
        source="solana_rpc", event_time=EVENT_TIME, event_type="income",
        asset="HNT", quantity=Decimal("2")))
    _price(store, source="derived:event_quote")
    for whitespace in SOURCE_WHITESPACE:
        with store.connect() as con:
            con.execute("update price_ledger set source = ?", [whitespace + "DeRiVeD:event_quote" + whitespace])
        service = PriceCoverageService(store)
        assert not service._has_acceptable_price("HNT", event), repr(whitespace)
        assert service.report().missing_count == 1, repr(whitespace)
        assert service.requirements().requirements_count == 1, repr(whitespace)


@pytest.mark.parametrize("event_time,price_time,expected", [
    ("2025-07-02T00:30:00+02:00", "2025-07-01T22:00:00+00:00", True),
    ("2025-07-02T00:30:00+02:00", "2025-07-01T21:00:00-02:00", False),
    ("2025-07-02T00:00:00+00:00", "2025-07-01T23:59:59+00:00", False),
])
def test_sql_coverage_and_lookup_agree_at_utc_day_boundaries(tmp_path, event_time, price_time, expected):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    event = _event(store, at=datetime.fromisoformat(event_time), event_type="income",
                   asset="HNT", quantity=Decimal("2"))
    _price(store, at=datetime.fromisoformat(price_time))
    service = PriceCoverageService(store)
    assert service._has_acceptable_price("HNT", event) is expected
    assert service.report().missing_count == (0 if expected else 1)
    assert service.requirements().requirements_count == (0 if expected else 1)


def test_flow_marks_old_price_as_missing_instead_of_valuing_transfer(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    _event(store, event_type="transfer", asset="HNT", quantity=Decimal("10"))
    _price(store, at=EVENT_TIME - timedelta(days=1642))
    entries = FlowService(store).rebuild()
    assert len(entries) == 1
    assert entries[0].value_eur is None
    assert entries[0].price_source is None
    summary = FlowService(store).summary()
    assert summary.missing_price_assets == ["HNT"]
    assert summary.edges == []
