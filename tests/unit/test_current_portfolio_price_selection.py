from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.current_portfolio_prices import select_current_portfolio_prices
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def add_price(store, asset, value, at, source, confidence="1"):
    return store.add_price_point(PricePointCreate(
        asset=asset, price_eur=Decimal(value), priced_at=at,
        source=source, confidence=Decimal(confidence),
    ))


def add_balance(store, asset, quantity="2"):
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", source_ref=f"balance-{asset}",
        event_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        event_type="transfer", asset=asset, quantity=Decimal(quantity), account="synthetic-wallet",
    ))
    BalanceLedgerBuilder(store).rebuild()


def test_selector_rejects_invalid_candidates_and_falls_back(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    cutoff = datetime(2024, 5, 10, 12, tzinfo=timezone.utc)
    good = add_price(store, "TEST", "7", cutoff - timedelta(days=8), "independent")
    add_price(store, "TEST", "100", cutoff + timedelta(microseconds=1), "independent")
    add_price(store, "TEST", "-1", cutoff, "independent")
    add_price(store, "TEST", "0", cutoff, "independent")
    add_price(store, "TEST", "99", cutoff, "\u2003DeRiVeD:EvEnT_QuOtE:trade")

    result = select_current_portfolio_prices(store, cutoff)

    assert result.selected["TEST"].price_id == good.price_id
    diagnostic = result.diagnostics["TEST"]
    assert (diagnostic.candidate_count, diagnostic.future_count, diagnostic.nonpositive_count,
            diagnostic.event_quote_count, diagnostic.eligible_price_found) == (5, 1, 2, 1, True)


def test_equal_timestamp_uses_confidence_then_source_not_insertion_order(tmp_path):
    cutoff = datetime(2024, 5, 10, 12, tzinfo=timezone.utc)
    results = []
    for index, entries in enumerate((
        [("z-source", "10", "0.9"), ("a-source", "20", "0.9"), ("high-source", "30", "0.95")],
        [("high-source", "30", "0.95"), ("a-source", "20", "0.9"), ("z-source", "10", "0.9")],
    )):
        store = DuckDbStore(tmp_path / f"synthetic-{index}.duckdb")
        for source, value, confidence in entries:
            add_price(store, "TEST", value, cutoff, source, confidence)
        selection = select_current_portfolio_prices(store, cutoff)
        results.append((selection.selected["TEST"].source, selection.previous["TEST"].source))
    assert results == [("high-source", "a-source"), ("high-source", "a-source")]


def test_snapshot_api_reports_unpriced_position_and_partial_total(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    add_balance(store, "UNPRICED")
    add_balance(store, "PRICED")
    now = datetime.now(timezone.utc)
    add_price(store, "UNPRICED", "5", now + timedelta(days=1), "future")
    add_price(store, "UNPRICED", "-4", now, "negative")
    add_price(store, "UNPRICED", "9", now, "derived:event_quote")
    add_price(store, "PRICED", "3", now - timedelta(days=1), "independent")
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: (_ for _ in ()).throw(
        AssertionError("snapshot must not rebuild the pipeline")
    ))
    with store.connect() as con:
        price_count_before = con.execute("select count(*) from price_ledger").fetchone()[0]

    response = TestClient(create_app(store)).get("/api/v1/portfolio/snapshot")
    assert response.status_code == 200
    snapshot = response.json()["data"]
    unpriced = next(item for item in snapshot["positions"] if item["asset"] == "UNPRICED")
    assert unpriced["price_eur"] is None and unpriced["value_eur"] is None
    assert snapshot["missing_price_assets"] == ["UNPRICED"]
    assert snapshot["valuation_coverage_status"] == "partial"
    assert "valuation_status" not in snapshot
    assert "Teilwert" in snapshot["total_value_semantics"]
    assert Decimal(snapshot["total_value_eur"]) == Decimal("6")
    summary = next(item for item in snapshot["asset_summary"] if item["asset"] == "UNPRICED")
    assert summary["price_status"] == "missing"
    assert snapshot["account_summary"][0]["unpriced_position_count"] == 1
    diagnostic = next(item for item in snapshot["price_selection_diagnostics"] if item["asset"] == "UNPRICED")
    assert (diagnostic["future_count"], diagnostic["nonpositive_count"], diagnostic["event_quote_count"],
            diagnostic["eligible_price_found"]) == (1, 1, 1, False)

    audit = PortfolioService(store).valuation_audit()
    row = next(item for item in audit.rows if item.asset == "UNPRICED")
    assert audit.valuation_coverage_status == "partial"
    assert "Teilwert" in audit.total_value_semantics
    assert row.current_price_eur is None
    assert row.previous_price_eur is None
    assert audit.value_delta_eur is None
    assert audit.previous_total_value_eur is None
    with store.connect() as con:
        assert con.execute("select count(*) from price_ledger").fetchone()[0] == price_count_before


def test_snapshot_empty_and_no_candidate_are_explicit(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    assert PortfolioService(store).snapshot().valuation_coverage_status == "empty"
    add_balance(store, "MISSING")
    result = PortfolioService(store).snapshot()
    assert result.valuation_coverage_status == "partial"
    assert result.positions[0].value_eur is None
    assert result.price_selection_diagnostics[0].candidate_count == 0


def test_historical_lookup_and_global_latest_are_not_changed(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    cutoff = datetime(2024, 5, 10, 12, tzinfo=timezone.utc)
    derived = add_price(store, "TEST", "9", cutoff - timedelta(hours=1), "derived:event_quote")
    future = add_price(store, "TEST", "10", cutoff + timedelta(days=1), "independent")
    selection = select_current_portfolio_prices(store, cutoff)
    assert "TEST" not in selection.selected
    assert HistoricalPriceLookup(store).at_or_before("TEST", cutoff).price_id == derived.price_id
    assert store.latest_price_points()["TEST"].price_id == future.price_id


def test_embedded_virtual_wallet_uses_same_safe_prices(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    add_balance(store, "TEST")
    now = datetime.now(timezone.utc)
    add_price(store, "TEST", "9", now - timedelta(minutes=1), "derived:event_quote")
    monkeypatch.setattr(
        PortfolioService, "_separation_fiat_purchase_lots",
        lambda self, cutoff: [(SimpleNamespace(asset="TEST", quantity_remaining=Decimal("1")), None)],
    )
    wallet = PortfolioService(store).snapshot().separation_virtual_wallet
    assert wallet.missing_price_assets == ["TEST"]
    assert wallet.positions[0].price_eur is None
    assert wallet.positions[0].value_eur is None


def test_cutoff_and_overlapping_rejection_reasons_use_utc(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    cutoff = datetime(2024, 5, 10, 14, tzinfo=timezone(timedelta(hours=2)))
    instant = datetime(2024, 5, 10, 12, tzinfo=timezone.utc)
    good = add_price(store, "TEST", "3", instant, "independent")
    add_price(store, "TEST", "-1", instant + timedelta(seconds=1), "derived:event_quote")
    selection = select_current_portfolio_prices(store, cutoff)
    assert selection.selected["TEST"].price_id == good.price_id
    diagnostic = selection.diagnostics["TEST"]
    assert (diagnostic.future_count, diagnostic.nonpositive_count, diagnostic.event_quote_count) == (1, 1, 1)


def test_audit_previous_price_uses_only_eligible_candidates(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    add_balance(store, "TEST")
    now = datetime.now(timezone.utc)
    add_price(store, "TEST", "3", now - timedelta(hours=3), "independent")
    add_price(store, "TEST", "5", now - timedelta(hours=2), "independent")
    add_price(store, "TEST", "99", now - timedelta(hours=1), "derived:event_quote")
    add_price(store, "TEST", "-2", now, "independent")
    add_price(store, "TEST", "999", now + timedelta(days=1), "independent")

    audit = PortfolioService(store).valuation_audit()
    row = audit.rows[0]
    assert row.current_price_eur == Decimal("5")
    assert row.previous_price_eur == Decimal("3")
    assert row.value_delta_eur == Decimal("4")
    assert audit.value_delta_eur == Decimal("4")


def test_live_anchor_with_only_rejected_price_is_visible_as_unpriced(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    add_price(store, "TEST", "9", datetime.now(timezone.utc), "derived:event_quote")
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "synthetic-live-wallet")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "synthetic-other-wallet")
    monkeypatch.setattr(PortfolioService, "_connector_live_snapshot_is_current",
                        lambda self, connector_id: connector_id == "solana_wallet")
    monkeypatch.setattr(PortfolioService, "_stored_live_balance_snapshots",
                        lambda self, connector_id: {"TEST": Decimal("2")})

    snapshot = PortfolioService(store).snapshot()
    assert snapshot.positions[0].quantity == Decimal("2")
    assert snapshot.positions[0].value_eur is None
    assert snapshot.missing_price_assets == ["TEST"]
    assert snapshot.valuation_coverage_status == "partial"


def test_full_price_coverage_does_not_claim_old_price_is_fresh(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    add_balance(store, "TEST")
    add_price(store, "TEST", "3", datetime.now(timezone.utc) - timedelta(days=400), "independent")

    snapshot = PortfolioService(store).snapshot()
    assert snapshot.valuation_coverage_status == "complete"
    assert snapshot.asset_summary[0].price_status == "outdated"
    assert snapshot.asset_summary[0].price_age_days >= 400
    audit = PortfolioService(store).valuation_audit()
    assert audit.valuation_coverage_status == "complete"
    assert audit.rows[0].current_price_status == "outdated"
