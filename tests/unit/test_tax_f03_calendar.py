"""Independent synthetic F03 fixtures: EUR consideration, no provider requests."""

from datetime import datetime
from decimal import Decimal

import duckdb
import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.fifo_methods import GLOBAL_ASSET_FIFO_SCOPE, active_fifo_scope
from steuerreport_v2.domain.reports import ReportCenterService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import (
    as_utc,
    private_disposal_tax_free_at,
    private_disposal_within_year,
    private_disposal_within_year_sql,
    reporting_tax_year,
    tax_line_within_year_sql,
)
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService


def dt(value):
    return datetime.fromisoformat(value)


# Explicit dates are the oracle, not a second implementation of the helper.
CASES = [
    ("2023-03-01T12:00:00Z", "2024-03-01T22:59:59Z", True, "2024-03-01T23:00:00Z"),
    ("2023-03-01T12:00:00Z", "2024-03-01T23:00:00Z", False, "2024-03-01T23:00:00Z"),
    ("2024-02-29T12:00:00Z", "2025-02-28T22:59:59Z", True, "2025-02-28T23:00:00Z"),
    ("2024-02-29T12:00:00Z", "2025-02-28T23:00:00Z", False, "2025-02-28T23:00:00Z"),
    ("2023-12-31T23:30:00Z", "2025-01-01T22:59:59Z", True, "2025-01-01T23:00:00Z"),
    ("2023-12-31T23:30:00Z", "2025-01-01T23:00:00Z", False, "2025-01-01T23:00:00Z"),
    ("2023-03-31T22:30:00Z", "2024-04-01T21:59:59Z", True, "2024-04-01T22:00:00Z"),
    ("2023-03-31T22:30:00Z", "2024-04-01T22:00:00Z", False, "2024-04-01T22:00:00Z"),
    ("2024-03-29T23:30:00Z", "2025-03-30T01:30:00Z", True, "2025-03-30T22:00:00Z"),
    ("2024-10-25T22:30:00Z", "2025-10-26T00:30:00Z", True, "2025-10-26T23:00:00Z"),
    ("2024-10-25T22:30:00Z", "2025-10-26T01:30:00Z", True, "2025-10-26T23:00:00Z"),
    ("2024-10-25T22:30:00Z", "2025-10-26T23:00:00Z", False, "2025-10-26T23:00:00Z"),
]


@pytest.mark.parametrize("acquired,disposed,within,free_at", CASES)
@pytest.mark.parametrize("naive", [False, True])
def test_python_sql_and_planning_share_calendar_boundary(acquired, disposed, within, free_at, naive):
    acquired_at, disposed_at = dt(acquired), dt(disposed)
    if naive:
        acquired_at = acquired_at.replace(tzinfo=None)
        disposed_at = disposed_at.replace(tzinfo=None)
    assert private_disposal_within_year(acquired_at, disposed_at) is within
    assert private_disposal_tax_free_at(acquired_at) == dt(free_at)
    assert TaxService._tax_free_at(acquired_at) == dt(free_at)
    with duckdb.connect() as con:
        # Deliberately not Berlin: the expression must not depend on session TZ.
        con.execute("set TimeZone='Pacific/Honolulu'")
        result = con.execute(
            f"select {private_disposal_within_year_sql('acquired_at', 'disposed_at')} "
            "from (select ?::timestamp acquired_at, ?::timestamp disposed_at)",
            [as_utc(acquired_at).replace(tzinfo=None), as_utc(disposed_at).replace(tzinfo=None)],
        ).fetchone()[0]
    assert result is within


@pytest.mark.parametrize("acquired,disposed,within,free_at", CASES[:8])
def test_fifo_reports_and_year_services_end_to_end(tmp_path, acquired, disposed, within, free_at):
    store = DuckDbStore(tmp_path / "f03.duckdb")
    store.add_canonical_events([
        CanonicalEventCreate(
            source="binance", account="fixture-spot", event_time=dt(at),
            event_type="trade", asset="USDC", quantity=Decimal(quantity),
            quote_asset="EUR", quote_quantity=Decimal(value),
        )
        for at, quantity, value in [(acquired, "1", "100"), (disposed, "-1", "150")]
    ])
    tax = TaxService(store)
    run = tax.rebuild_fifo()
    assert run.unmatched_disposals == 0
    line = tax.list_tax_lines()[0]
    assert line.acquisition_cost_eur == Decimal("100")
    assert line.disposal_proceeds_eur == Decimal("150")
    assert line.gain_loss_eur == Decimal("50")
    if acquired == CASES[0][0] and within:
        assert line.holding_days == 366
    # holding_days is deliberately corrupt: all consumers must still use dates.
    with store.connect() as con:
        con.execute("update tax_lines set holding_days = ?", [9999 if within else 0])
        con.execute("update tax_lots set acquired_at = '2000-01-01'")
        assert con.execute(f"select {tax_line_within_year_sql()} from tax_lines").fetchone()[0] is within
        con.execute("update tax_lots set acquired_at = ?", [as_utc(dt(acquired)).replace(tzinfo=None)])
        assert con.execute(f"select {tax_line_within_year_sql()} from tax_lines").fetchone()[0] is within
        # Older global rows lack acquired_at; the lot date remains usable.
        con.execute("update tax_lines set acquired_at = null")
        assert con.execute(f"select {tax_line_within_year_sql()} from tax_lines").fetchone()[0] is within
    service = TaxYearService(store)
    year = reporting_tax_year(dt(disposed))
    taxable_gain = Decimal("50") if within else Decimal("0")
    free_gain = Decimal("0") if within else Decimal("50")
    status = service.detail(year)
    assert status.realized_gain_loss_eur == taxable_gain
    assert status.tax_free_gain_loss_eur == free_gain
    payment = service._payment_tax_totals_by_year()[year]
    assert payment["gain_loss"] == taxable_gain
    assert payment["tax_free_gain_loss"] == free_gain
    drivers = service.driver_report(year)
    assert drivers.taxable_gain_loss_eur == taxable_gain
    assert drivers.tax_free_gain_loss_eur == free_gain
    assert service.asset_fifo_drilldown(year, asset="USDC").lines[0].taxable is within
    assert service._stablecoin_fifo_lines(year)[0].taxable is within
    assert bool(service.gain_evidence_review(year).lines) is within
    cards = ReportCenterService(store)._year_cards(
        allow_export=False, has_created_package=False, latest_created_at=None,
    )
    card = next(card for card in cards if card.year == year)
    assert Decimal(card.realized_gain_loss_eur) == taxable_gain
    assert Decimal(card.tax_free_private_disposals_eur) == free_gain
    wallet = WalletFifoPreviewService(store).replay(as_of=dt(disposed))
    assert wallet.tax_lines[0].gain_loss_eur == Decimal("50")
    assert service._is_taxable_private_disposal(wallet.tax_lines[0]) is within
    assert active_fifo_scope(store) == GLOBAL_ASSET_FIFO_SCOPE


def test_line_acquisition_date_precedes_lot_fallback_and_missing_date_is_not_free(tmp_path):
    store = DuckDbStore(tmp_path / "fallback.duckdb")
    with store.connect() as con:
        con.execute("create temporary table fixture(lot_id varchar, acquired_at timestamp, disposed_at timestamp)")
        con.execute("insert into fixture values ('no-lot', '2024-01-01', '2025-01-01'), ('missing', null, '2025-01-01')")
        assert con.execute(f"select {tax_line_within_year_sql('fixture')} from fixture").fetchall() == [(True,), (True,)]


def test_open_lot_planning_uses_berlin_midnight_and_local_day_count(tmp_path):
    store = DuckDbStore(tmp_path / "planning.duckdb")
    store.add_canonical_events([CanonicalEventCreate(
        source="binance", account="fixture-spot", event_time=dt("2023-03-31T22:30:00Z"),
        event_type="trade", asset="USDC", quantity=Decimal("1"),
        quote_asset="EUR", quote_quantity=Decimal("100"),
    )])
    tax = TaxService(store)
    tax.rebuild_fifo()
    store.add_price_point(PricePointCreate(
        asset="USDC", price_eur=Decimal("150"), source="fixture-only",
        priced_at=dt("2024-04-01T12:00:00Z"),
    ))
    for as_of, days in [("2024-04-01T21:59:59Z", 1), ("2024-04-01T22:00:00Z", 0)]:
        lot = tax.holding_period_report(as_of=dt(as_of)).lots[0]
        assert lot.tax_free_at == dt("2024-04-01T22:00:00Z")
        assert lot.days_until_tax_free == days
        assert (lot.bucket == "tax_free_now") is (days == 0)


@pytest.mark.parametrize("quote_time,accepted", [
    ("2025-05-01T23:59:59Z", False),
    ("2025-05-02T00:00:00Z", True),
    ("2025-05-02T00:30:00Z", True),
    ("2025-05-02T00:30:01Z", False),
    ("2025-05-03T00:00:00Z", False),
])
def test_custom_income_price_index_enforces_utc_day_and_no_future(tmp_path, quote_time, accepted):
    store = DuckDbStore(tmp_path / "income-price.duckdb")
    store.add_price_point(PricePointCreate(
        asset="HNT", price_eur=Decimal("5"), source="fixture-only", priced_at=dt(quote_time),
    ))
    service = TaxYearService(store)
    lookup = service._income_price_lookup(["HNT"])
    for event_time in [dt("2025-05-02T00:30:00Z"), dt("2025-05-02T02:30:00+02:00")]:
        result = service._income_price_at("hnt", event_time, lookup)
        assert (result is not None) is accepted
        if accepted:
            assert result[0] == Decimal("5")


def test_income_price_does_not_fall_back_to_old_primary_quote(tmp_path):
    store = DuckDbStore(tmp_path / "income-derived.duckdb")
    for at, source, value in [
        ("2025-05-01T23:59:59Z", "primary", "99"),
        ("2025-05-02T00:00:00Z", "derived:fixture", "5"),
        ("2025-05-02T01:00:00Z", "primary", "100"),
    ]:
        store.add_price_point(PricePointCreate(asset="HNT", price_eur=Decimal(value), source=source, priced_at=dt(at)))
    service = TaxYearService(store)
    result = service._income_price_at("HNT", dt("2025-05-02T00:30:00Z"), service._income_price_lookup(["HNT"]))
    assert result[0:2] == (Decimal("5"), "derived:fixture")


def test_reward_income_and_later_disposal_use_same_basis_without_double_income(tmp_path):
    store = DuckDbStore(tmp_path / "reward.duckdb")
    store.add_canonical_events([
        CanonicalEventCreate(
            source="binance", account="fixture-spot", event_time=dt(at),
            event_type=kind, asset="HNT", quantity=Decimal(quantity),
            quote_asset="EUR", quote_quantity=Decimal(value),
        )
        for at, kind, quantity, value in [
            ("2024-06-01T10:00:00Z", "staking", "1", "100"),
            ("2024-06-02T10:00:00Z", "trade", "-1", "150"),
        ]
    ])
    global_run = TaxService(store).rebuild_fifo()
    wallet_run = WalletFifoPreviewService(store).replay()
    assert global_run.lots[0].cost_basis_eur_total == Decimal("100")
    assert global_run.tax_lines[0].gain_loss_eur == Decimal("50")
    assert wallet_run.tax_lines[0].acquisition_cost_eur == Decimal("100")
    assert wallet_run.tax_lines[0].gain_loss_eur == Decimal("50")
    income = TaxYearService(store).income_report(2024)
    assert income.total_income_eur == Decimal("100")
    assert income.events_count == 1
    assert income.missing_value_count == 0
    assert active_fifo_scope(store) == GLOBAL_ASSET_FIFO_SCOPE


def test_missing_reward_price_remains_missing_despite_provisional_zero_basis(tmp_path):
    store = DuckDbStore(tmp_path / "missing-reward.duckdb")
    store.add_canonical_events([CanonicalEventCreate(
        source="binance", account="fixture-spot", event_time=dt("2024-06-01T10:00:00Z"),
        event_type="staking", asset="HNT", quantity=Decimal("1"),
    )])
    TaxService(store).rebuild_fifo()
    income = TaxYearService(store).income_report(2024)
    assert income.missing_value_count == 1
    assert income.events[0].income_eur is None
    assert income.events[0].valuation_status == "missing_price"
    assert TaxYearService(store).detail(2024).missing_price_groups > 0


@pytest.mark.parametrize("price", ["0", "-1"])
def test_income_price_nonpositive_candidate_is_not_usable(price):
    at = dt("2025-05-02T00:00:00")
    item = (at, Decimal(price), "fixture", Decimal("1"), "fixture-id")
    assert TaxYearService._income_price_at("HNT", at, {"HNT": ([at], [item])}) is None
