"""Unabhaengige G04-Sollwerte, nur eigene DBs und dokumentierte EUR-Belege."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.fifo_methods import GLOBAL_ASSET_FIFO_SCOPE, active_fifo_scope
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


D = Decimal


def trade(store, asset, quantity, value, *, day=10, fee_asset=None, fee=None,
          quote="EUR", account="Spot", kind="trade"):
    return store.add_canonical_events([CanonicalEventCreate(
        source="binance", account=account, event_type=kind,
        event_time=datetime(2024, 1, day, 12, tzinfo=timezone.utc),
        asset=asset, quantity=D(quantity), quote_asset=quote,
        quote_quantity=D(value) if value is not None else None,
        fee_asset=fee_asset, fee_quantity=D(fee) if fee is not None else None,
    )])[0]


def point(store, asset="BNB", value="30", *, day=10):
    store.add_price_point(PricePointCreate(
        asset=asset, price_eur=D(value), source="synthetic:g04-evidence",
        priced_at=datetime(2024, 1, day, tzinfo=timezone.utc),
    ))


@pytest.fixture(params=["global", "wallet"])
def engine(request, tmp_path):
    store = DuckDbStore(tmp_path / "g04.duckdb")
    def run():
        if request.param == "global":
            result = TaxService(store).rebuild_fifo()
            return result.lots, result.tax_lines, result.unmatched
        state = WalletFifoPreviewService(store).replay()
        assert active_fifo_scope(store) == GLOBAL_ASSET_FIFO_SCOPE
        return state.all_lots, state.tax_lines, state.unmatched
    return store, run


def remaining(lots, asset):
    return sum((lot.quantity_remaining for lot in lots if lot.asset == asset), D("0"))


def remaining_basis(lots, asset):
    return sum((lot.cost_basis_eur_total * lot.quantity_remaining / lot.quantity_total
                for lot in lots if lot.asset == asset and lot.quantity_total), D("0"))


def test_eur_buy_capitalizes_fee_and_fee_token_has_own_realization_once(engine):
    store, run = engine
    trade(store, "BNB", "1", "20", day=5)
    buy = trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    lots, lines, unmatched = run()
    assert unmatched == []
    assert remaining(lots, "BNB") == D("0.9")
    assert remaining_basis(lots, "BNB") == D("18")
    assert next(lot for lot in lots if lot.asset == "BTC").cost_basis_eur_total == D("103")
    assert len(lines) == 1
    fee = lines[0]
    assert (fee.asset, fee.quantity, fee.acquisition_cost_eur,
            fee.disposal_proceeds_eur, fee.gain_loss_eur) == ("BNB", D("0.1"), D("2"), D("3"), D("1"))
    assert fee.source_event_id == buy.event_id
    trade(store, "BTC", "-10", "150", day=12)
    lots, lines, unmatched = run()
    assert unmatched == []
    assert next(line for line in lines if line.asset == "BTC").gain_loss_eur == D("47")
    assert sum((line.gain_loss_eur for line in lines), D("0")) == D("48")
    assert remaining_basis(lots, "BNB") == D("18")


def test_eur_sale_deducts_fee_once_and_consumes_fee_lot(engine):
    store, run = engine
    trade(store, "BNB", "1", "20", day=5)
    trade(store, "BTC", "10", "100", day=6)
    trade(store, "BTC", "-10", "150", fee_asset="BNB", fee="0.1")
    point(store)
    lots, lines, unmatched = run()
    assert unmatched == []
    sale = next(line for line in lines if line.asset == "BTC")
    assert (sale.disposal_proceeds_eur, sale.acquisition_cost_eur, sale.gain_loss_eur) == (D("147"), D("100"), D("47"))
    assert next(line for line in lines if line.asset == "BNB").gain_loss_eur == D("1")
    assert sum((line.gain_loss_eur for line in lines), D("0")) == D("48")
    assert remaining(lots, "BNB") == D("0.9")
    assert remaining_basis(lots, "BNB") == D("18")


def test_eur_fee_control_is_allocated_without_crypto_fee_disposal(engine):
    store, run = engine
    trade(store, "BTC", "1", "100", day=5, fee_asset="EUR", fee="2")
    trade(store, "BTC", "-1", "150", fee_asset="EUR", fee="3")
    _, lines, unmatched = run()
    assert unmatched == [] and len(lines) == 1
    assert (lines[0].acquisition_cost_eur, lines[0].disposal_proceeds_eur,
            lines[0].gain_loss_eur) == (D("102"), D("147"), D("45"))


def test_acquired_asset_fee_stays_net_not_a_second_disposal(engine):
    store, run = engine
    event = trade(store, "BTC", "10", "100", fee_asset="BTC", fee="0.1")
    lots, lines, unmatched = run()
    assert unmatched == [] and lines == []
    assert remaining(lots, "BTC") == D("9.9")
    assert remaining_basis(lots, "BTC") == D("100")
    fee = TaxService(store).trade_fee_accounting(event)
    assert fee.allocation == "included_in_net_quantity"
    assert not fee.separate_disposal


def test_disposed_asset_fee_consumed_after_main_quantity_without_double_basis(engine):
    store, run = engine
    trade(store, "BTC", "11", "110", day=5)
    trade(store, "BTC", "-10", "150", fee_asset="BTC", fee="0.1")
    point(store, "BTC", "15")
    lots, lines, unmatched = run()
    assert unmatched == [] and len(lines) == 2
    assert [line.quantity for line in lines] == [D("10"), D("0.1")]
    assert [line.gain_loss_eur for line in lines] == [D("48.5"), D("0.5")]
    assert sum((line.acquisition_cost_eur for line in lines), D("0")) == D("101")
    assert remaining(lots, "BTC") == D("0.9")
    assert remaining_basis(lots, "BTC") == D("9")


@pytest.mark.parametrize("direction", ["buy", "sell"])
def test_swap_third_fee_consumed_but_cost_role_remains_unallocated(engine, direction):
    store, run = engine
    trade(store, "BNB", "1", "20", day=5)
    trade(store, "ETH", "1", "40", day=6)
    if direction == "buy":
        event = trade(store, "BTC", "10", "1", quote="ETH", fee_asset="BNB", fee="0.1")
    else:
        event = trade(store, "ETH", "-1", "10", quote="BTC", fee_asset="BNB", fee="0.1")
    point(store)
    point(store, "BTC", "10")
    point(store, "ETH", "100")
    lots, lines, unmatched = run()
    assert unmatched == []
    assert remaining(lots, "BNB") == D("0.9")
    assert remaining_basis(lots, "BTC") == D("100")  # Not blindly capitalized as 103.
    assert next(line for line in lines if line.asset == "ETH").disposal_proceeds_eur == D("100")
    assert next(line for line in lines if line.asset == "BNB").gain_loss_eur == D("1")
    assert TaxService(store).trade_fee_accounting(event).allocation == "review_required"


@pytest.mark.parametrize("price_kind", ["absent", "old", "future"])
def test_unvalued_fee_still_consumes_quantity_but_is_not_known_zero(engine, price_kind):
    store, run = engine
    trade(store, "BNB", "1", "20", day=5)
    event = trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    if price_kind != "absent":
        point(store, day=9 if price_kind == "old" else 11)
    lots, lines, unmatched = run()
    assert unmatched == []
    assert remaining(lots, "BNB") == D("0.9")
    assert remaining_basis(lots, "BNB") == D("18")
    assert TaxService(store).trade_fee_accounting(event).value_eur is None
    assert lines[0].disposal_proceeds_eur == D("0")  # Decimal-only provisional row, NOT a valuation.
    # Quantity is corrected; missing valuation remains a specific export blocker.
    TaxService(store).rebuild_fifo()
    gate = ReviewService(store).gate()
    assert not gate.allow_export
    assert any(issue.code == "fee_token_valuation_missing" and issue.blocks_export for issue in gate.issues)


def test_complete_fee_accounting_no_longer_reports_unimplemented_fifo(tmp_path):
    store = DuckDbStore(tmp_path / "fee-gate.duckdb")
    trade(store, "BNB", "1", "20", day=5)
    trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    TaxService(store).rebuild_fifo()
    codes = {issue.code for issue in ReviewService(store).gate().issues}
    assert "fee_token_lot_accounting_review_required" not in codes
    assert "fee_token_valuation_missing" not in codes
    assert "swap_fee_allocation_review_required" not in codes


def test_swap_fee_cost_role_stays_blocked_after_quantity_fix(tmp_path):
    store = DuckDbStore(tmp_path / "swap-gate.duckdb")
    trade(store, "ETH", "1", "40", day=5)
    trade(store, "BTC", "10", "1", quote="ETH", fee_asset="BTC", fee="0.1")
    TaxService(store).rebuild_fifo()
    assert any(issue.code == "swap_fee_allocation_review_required" and issue.blocks_export
               for issue in ReviewService(store).gate().issues)


@pytest.mark.parametrize("direction", ["buy", "sell"])
def test_swap_acquired_asset_fee_is_net_but_still_needs_cost_role_review(engine, direction):
    store, run = engine
    trade(store, "ETH", "1", "40", day=5)
    if direction == "buy":
        event = trade(store, "BTC", "10", "1", quote="ETH", fee_asset="BTC", fee="0.1")
    else:
        event = trade(store, "ETH", "-1", "10", quote="BTC", fee_asset="BTC", fee="0.1")
    point(store, "BTC", "10")
    point(store, "ETH", "100")
    lots, lines, unmatched = run()
    assert unmatched == []
    assert remaining(lots, "BTC") == D("9.9")
    assert len(lines) == 1 and lines[0].asset == "ETH"
    fee = TaxService(store).trade_fee_accounting(event)
    assert not fee.separate_disposal
    assert fee.allocation == "review_required"


def test_missing_fee_inventory_is_unmatched_not_an_invented_purchase(engine):
    store, run = engine
    trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    lots, lines, unmatched = run()
    assert not any(lot.asset == "BNB" for lot in lots)
    assert not any(line.asset == "BNB" for line in lines)
    assert len(unmatched) == 1
    assert unmatched[0].asset == "BNB"
    assert unmatched[0].missing_quantity == D("0.1")


def test_partial_fee_inventory_consumed_and_remaining_gap_not_hidden(engine):
    store, run = engine
    trade(store, "BNB", "0.04", "0.8", day=5)
    trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    lots, lines, unmatched = run()
    assert remaining(lots, "BNB") == D("0")
    assert len(lines) == 1 and lines[0].quantity == D("0.04")
    assert lines[0].acquisition_cost_eur == D("0.8")
    assert lines[0].disposal_proceeds_eur == D("1.2")
    assert len(unmatched) == 1 and unmatched[0].missing_quantity == D("0.06")
    assert not any(lot.asset == "BNB" and lot.quantity_total == D("0.06") for lot in lots)


def test_fee_spans_fifo_lots_without_reusing_basis(engine):
    store, run = engine
    trade(store, "BNB", "0.04", "0.8", day=5)
    trade(store, "BNB", "1", "30", day=6)
    trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    lots, lines, unmatched = run()
    assert unmatched == [] and len(lines) == 2
    assert sum((line.quantity for line in lines), D("0")) == D("0.1")
    assert sum((line.acquisition_cost_eur for line in lines), D("0")) == D("2.6")
    assert sum((line.disposal_proceeds_eur for line in lines), D("0")) == D("3")
    assert sum((line.gain_loss_eur for line in lines), D("0")) == D("0.4")
    assert remaining(lots, "BNB") == D("0.94")
    assert remaining_basis(lots, "BNB") == D("28.2")


def test_explicit_micro_fee_has_missing_lot_even_when_trade_dust_is_ignored(engine):
    store, run = engine
    trade(store, "BTC", "10", "100", fee_asset="SOL", fee="0.000001")
    point(store, "SOL", "20")
    _, lines, unmatched = run()
    assert lines == []
    assert len(unmatched) == 1 and unmatched[0].missing_quantity == D("0.000001")


def test_fee_above_sale_proceeds_is_not_silently_clipped(engine):
    store, run = engine
    trade(store, "BNB", "1", "20", day=5)
    trade(store, "BTC", "1", "1", day=6)
    trade(store, "BTC", "-1", "2", fee_asset="BNB", fee="0.1")
    point(store)
    _, lines, unmatched = run()
    assert unmatched == []
    assert next(line for line in lines if line.asset == "BTC").disposal_proceeds_eur == D("-1")
    assert sum((line.gain_loss_eur for line in lines), D("0")) == D("-1")


def test_unproven_fee_basis_remains_blocking(engine):
    store, run = engine
    trade(store, "BNB", "1", None, day=5, quote=None, kind="income")
    trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    lots, _, _ = run()
    assert remaining(lots, "BNB") == D("0.9")
    TaxService(store).rebuild_fifo()
    assert any(issue.code == "unproven_zero_cost_basis" and issue.blocks_export for issue in ReviewService(store).gate().issues)


def test_wallet_cannot_take_fee_inventory_from_other_pool(tmp_path):
    store = DuckDbStore(tmp_path / "pools.duckdb")
    trade(store, "BNB", "1", "20", day=5, account="Other")
    trade(store, "BTC", "10", "100", fee_asset="BNB", fee="0.1")
    point(store)
    state = WalletFifoPreviewService(store).replay()
    assert remaining(state.all_lots, "BNB") == D("1")
    assert state.unmatched[0].missing_quantity == D("0.1")
    assert "trade_fee_without_wallet_lot" in state.unmatched[0].reason


def test_original_raw_and_ledger_movement_stay_unchanged_across_rebuilds(tmp_path):
    store = DuckDbStore(tmp_path / "raw.duckdb")
    batch = CsvRawImporter(store).import_text("binance", "g04.csv",
        "time,asset,amount,type,quote_asset,quote_quantity,fee_asset,fee_quantity,account\n"
        "2024-01-05T12:00:00Z,BNB,1,buy,EUR,20,,,Spot\n"
        "2024-01-10T12:00:00Z,BTC,10,buy,EUR,100,BNB,0.1,Spot\n")
    RawNormalizer(store).normalize_batch(batch.batch_id)
    raw = [item.model_dump() for item in store.list_raw_objects(limit=None)]
    events = [item.model_dump() for item in store.list_canonical_events()]
    point(store)
    BalanceLedgerBuilder(store).rebuild()
    for _ in range(2):
        result = TaxService(store).rebuild_fifo()
        assert remaining(result.lots, "BNB") == D("0.9")
        assert sum((line.gain_loss_eur for line in result.tax_lines), D("0")) == D("1")
    assert raw == [item.model_dump() for item in store.list_raw_objects(limit=None)]
    assert events == [item.model_dump() for item in store.list_canonical_events()]
    positions = BalanceLedgerBuilder(store).positions()
    assert next(position.quantity for position in positions if position.asset == "BNB") == D("0.9")
