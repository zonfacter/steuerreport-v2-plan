"""Feste Issue-2-Sollwerte, Original-CSV-Generator und echte Consumer."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


PATH = Path(__file__).resolve().parents[2] / "docs/audit/2026-10-28/issues/issue2-original.py"
assert hashlib.sha256(PATH.read_bytes()).hexdigest() == "840308d2e39a5617558086743a8cc8abda3990ebce071d873b18f897af90dfb1"
SPEC = importlib.util.spec_from_file_location("bitget_issue2_original", PATH)
REPRO = importlib.util.module_from_spec(SPEC)
_BYTECODE = sys.dont_write_bytecode
SPEC.loader.exec_module(REPRO)
sys.dont_write_bytecode = _BYTECODE

CASES = [
    ("native_date", "bitget", REPRO.native_csv("open_long", "0", "-0.37", date_header="Date"), "-0.37", ["derivative"]),
    ("native_open", "bitget", REPRO.native_csv("open_long", "0", "-0.37"), "-0.37", ["derivative"]),
    ("native_profit", "bitget", REPRO.native_csv("close_long", "12.80", "-0.20"), "12.60", ["derivative"]),
    ("native_loss", "bitget", REPRO.native_csv("close_short", "-8.40", "-0.15"), "-8.55", ["derivative"]),
    ("funding_paid", "bitget", REPRO.native_csv("contract_margin_settle_fee", "-2.30", "0"), "-2.30", ["derivative"]),
    ("funding_received", "bitget", REPRO.native_csv("contract_margin_settle_fee", "1.10", "0"), "1.10", ["derivative"]),
    ("funding_fee", "bitget", REPRO.native_csv("contract_margin_settle_fee", "-2.30", "-0.02"), "-2.32", ["derivative"]),
    ("collateral", "bitget", REPRO.native_csv("adjust_margin_ifm", "25", "0", opening_balance_row=True), "100", ["derivative", "transfer"]),
    ("leverage", "bitget", REPRO.native_csv("adjust_down_leverage", "-10", "0", opening_balance_row=True), "100", ["derivative", "transfer"]),
    ("legacy_open", "bitget", REPRO.legacy_csv("open_long", "-0.37", "-0.37"), "-0.37", ["derivative"]),
    ("legacy_funding", "bitget", REPRO.legacy_csv("contract_margin_settle_fee", "-2.32", "-0.02"), "-2.32", ["derivative"]),
    ("generic_derivative", "manual-csv", REPRO.generic_csv("derivative", "-8.55"), "-8.55", ["derivative"]),
    ("generic_fee", "manual-csv", REPRO.generic_csv("derivative", "-8.40", "-0.15"), "-8.55", ["derivative"]),
    ("offset", "bitget", REPRO.native_csv("trans_from_exchange", "10", "0"), "10", ["transfer"]),
    ("cash_control", "manual-csv", REPRO.csv_text(["timestamp", "type", "asset", "amount", "account", "id"],
        [[REPRO.SYNTHETIC_TIME, "unknown", "USDT", "-8.40", "Synthetic Account", "principal"],
         [REPRO.SYNTHETIC_TIME, "fee", "USDT", "-0.15", "Synthetic Account", "fee"],
         [REPRO.SYNTHETIC_TIME, "unknown", "USDT", "0", "Synthetic Account", "neutral"]]), "-8.55", ["unknown", "fee", "unknown"]),
]


@pytest.mark.parametrize("name,source,content,expected,types", CASES, ids=[row[0] for row in CASES])
def test_issue2_csv_to_cash_and_derivative_eur(tmp_path, name, source, content, expected, types):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    importer = CsvRawImporter(store)
    preview = importer.preview_text(source=source, filename="synthetic.csv", content=content)
    assert preview.can_import
    batch = importer.import_text(source=source, filename="synthetic.csv", content=content)
    before = [(r.raw_object_id, r.payload_json) for r in store.list_raw_objects(batch.batch_id)]
    events, report = RawNormalizer(store).normalize_batch_with_report(batch.batch_id)
    assert report.skipped_raw_objects == 0
    assert sorted(e.event_type for e in events) == sorted(types)
    assert all(e.event_time.hour == (4 if name.startswith("legacy") else 11) for e in events if e.quantity != Decimal("100"))
    entries = BalanceLedgerBuilder(store).rebuild()
    assert sum((e.delta_quantity for e in entries if e.asset == "USDT"), Decimal("0")) == Decimal(expected)
    store.add_price_point(PricePointCreate(asset="USDT", price_eur=Decimal("0.9"),
        priced_at=datetime(2031, 7, 9, tzinfo=timezone.utc), source="synthetic:observed"))
    derivative = DerivativesManager(store).rebuild()
    if all(t == "derivative" for t in types):
        assert derivative.summary.realized_pnl_eur == Decimal(expected) * Decimal("0.9")
    elif name in {"collateral", "leverage"}:
        assert derivative.summary.realized_pnl_eur == 0
        assert derivative.summary.derivative_lines_count == 0
    assert [(r.raw_object_id, r.payload_json) for r in store.list_raw_objects(batch.batch_id)] == before
    assert all(isinstance(json.loads(payload), dict) for _, payload in before)
