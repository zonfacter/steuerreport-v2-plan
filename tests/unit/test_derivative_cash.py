"""Quellkonvention, Wallet und EUR-Auswertung getrennt absichern."""
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivative_cash import derivative_cash, derivative_raw_rows
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


D = Decimal
STAMP = "2031-07-09T12:00:00+01:00"
HEADER = "Order;Date;Coin;Futures;Margin Mode;Type;Amount;Fee;Wallet balance\n"


def prepare(tmp_path, content, source="bitget"):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    importer = CsvRawImporter(store)
    batch = importer.import_text(source=source, filename="synthetic.csv", content=content)
    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    for asset, price in (("USDT", "0.9"), ("EUR", "1")):
        store.add_price_point(PricePointCreate(asset=asset, price_eur=D(price),
            priced_at=datetime(2031, 7, 9, tzinfo=timezone.utc), source="synthetic:observed"))
    return store, batch, events


@pytest.mark.parametrize("amount,fee,expected", [("0", "-0.37", "-0.37"), ("12.8", "-0.2", "12.6"), ("0", "0.05", "0.05")])
def test_native_signed_fee_and_rebate_are_not_lost(tmp_path, amount, fee, expected):
    store, _, events = prepare(tmp_path, HEADER + f"a;{STAMP};USDT;DEMOUSDT;Single-asset;close_long;{amount};{fee};100\n")
    before = store.list_canonical_events()[0].model_dump()
    ledger = BalanceLedgerBuilder(store).rebuild()
    result = DerivativesManager(store).rebuild()
    assert sum((x.delta_quantity for x in ledger), D("0")) == D(expected)
    assert result.summary.realized_pnl_eur == D(expected) * D("0.9")
    assert result.summary.missing_price_count == 0
    assert store.list_canonical_events()[0].model_dump() == before
    assert derivative_cash(events[0], derivative_raw_rows(store)[events[0].event_id]).policy == "bitget_signed_separate_fee"


def test_generic_foreign_fee_keeps_cash_but_requires_lot_review(tmp_path):
    store, _, _ = prepare(tmp_path,
        "timestamp;type;asset;amount;fee_asset;fee_quantity;id\n"
        f"{STAMP};derivative;USDT;10;EUR;1;synthetic\n", "manual-csv")
    ledger = BalanceLedgerBuilder(store).rebuild()
    assert {x.asset: x.delta_quantity for x in ledger} == {"USDT": D("10"), "EUR": D("-1")}
    result = DerivativesManager(store).rebuild()
    assert result.summary.realized_pnl_eur == D("8")
    gate = ReviewService(store).gate()
    assert "derivative_fee_semantics_required" in {x.code for x in gate.issues}
    assert not gate.allow_export


@pytest.mark.parametrize("fee", ["0.15", "-0.15"])
def test_explicit_generic_fee_is_a_cost_in_either_export_sign(tmp_path, fee):
    store, _, _ = prepare(tmp_path,
        "timestamp;type;asset;amount;fee_asset;fee_quantity;id\n"
        f"{STAMP};derivative;USDT;-8.4;USDT;{fee};synthetic\n", "manual-csv")
    ledger = BalanceLedgerBuilder(store).rebuild()
    assert sum((x.delta_quantity for x in ledger), D("0")) == D("-8.55")
    assert DerivativesManager(store).rebuild().summary.realized_pnl_eur == D("-7.695")


def test_unproven_existing_derivative_fee_is_not_guessed_or_approved(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_canonical_event(CanonicalEventCreate(source="synthetic", event_type="derivative",
        event_time=STAMP, asset="USDT", quantity=D("5"), fee_asset="USDT", fee_quantity=D("1")))
    ledger = BalanceLedgerBuilder(store).rebuild()
    assert sum((x.delta_quantity for x in ledger), D("0")) == 5
    gate = ReviewService(store).gate()
    issue = next(x for x in gate.issues if x.code == "derivative_fee_semantics_required")
    assert "fee_convention_missing" in issue.message and issue.blocks_export


def test_old_cash_calculation_is_visible_until_explicit_rebuild(tmp_path):
    store, _, _ = prepare(tmp_path, HEADER + f"a;{STAMP};USDT;DEMOUSDT;Single-asset;open_long;0;-0.37;99.63\n")
    BalanceLedgerBuilder(store).rebuild()
    DerivativesManager(store).rebuild()
    with store.connect() as con:
        con.execute("update balance_ledger set delta_quantity=0,balance_quantity=0")
        con.execute("update derivative_lines set quantity=0,value_eur=0")
    before = [x.model_dump() for x in store.list_canonical_events()]
    assert "derivative_cash_recalculation_required" in {x.code for x in ReviewService(store).gate().issues}
    assert before == [x.model_dump() for x in store.list_canonical_events()]
    BalanceLedgerBuilder(store).rebuild()
    DerivativesManager(store).rebuild()
    assert "derivative_cash_recalculation_required" not in {x.code for x in ReviewService(store).gate().issues}


def test_old_funding_classification_requires_renormalization(tmp_path):
    store, batch, _ = prepare(tmp_path, HEADER + f"a;{STAMP};USDT;DEMOUSDT;Single-asset;contract_margin_settle_fee;-2.3;0;97.7\n")
    with store.connect() as con:
        con.execute("update canonical_events set event_type='fee'")
    assert "derivative_normalization_required" in {x.code for x in ReviewService(store).gate().issues}
    RawNormalizer(store).normalize_batch(batch.batch_id)
    assert "derivative_normalization_required" not in {x.code for x in ReviewService(store).gate().issues}


def test_repeated_import_preserves_raw_rows_and_does_not_double_cash(tmp_path):
    content = HEADER + f"a;{STAMP};USDT;DEMOUSDT;Single-asset;close_long;12.8;-0.2;112.6\n"
    store, batch, _ = prepare(tmp_path, content)
    raw = [(r.raw_object_id, json.loads(r.payload_json)) for r in store.list_raw_objects(batch.batch_id)]
    for _ in range(2):
        same = CsvRawImporter(store).import_text(source="bitget", filename="synthetic.csv", content=content)
        assert same.batch_id == batch.batch_id
        events = RawNormalizer(store).normalize_batch(batch.batch_id)
        assert len(events) == 1
        assert sum((x.delta_quantity for x in BalanceLedgerBuilder(store).rebuild()), D("0")) == D("12.6")
    assert [(r.raw_object_id, json.loads(r.payload_json)) for r in store.list_raw_objects(batch.batch_id)] == raw
