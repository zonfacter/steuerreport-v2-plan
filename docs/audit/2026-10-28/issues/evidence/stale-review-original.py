"""Zwei unabhaengige Altstand-Repros, keine Aenderung am Coordinator."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket

ROOT = Path("/tmp/sr-issues-20261028-bitget-review")
REPO = Path("/tmp/steuerreport-migration-20261028-coordinator")
os.environ["STEUERREPORT_PRIVATE_PROFILE"] = ""
os.environ["STEUERREPORT_PRIVATE_CONFIG_DIR"] = str(ROOT / "empty-private-config")
os.environ["STEUERREPORT_STATE_DIR"] = str(ROOT / "runtime")
os.environ["STEUERREPORT_V2_DB"] = str(ROOT / "unused-default.duckdb")

import duckdb
import pytest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder

D = Decimal


@pytest.fixture(scope="session", autouse=True)
def frozen_sources():
    files = [
        "domain/derivative_cash.py", "domain/derivatives.py", "domain/review.py",
        "ledger/balance.py", "importers/source_profiles.py", "importers/raw_normalizer.py",
    ]
    def hashes():
        return {name: hashlib.sha256((REPO / "src/steuerreport_v2" / name).read_bytes()).hexdigest() for name in files}
    before = hashes()
    yield
    after = hashes()
    (ROOT / "source-freeze.json").write_text(json.dumps({"before": before, "after": after, "unchanged": before == after}, indent=2) + "\n")
    assert before == after


@pytest.fixture
def case(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(ROOT)
    def blocked(*args, **kwargs):
        raise OSError("Review-Repro: kein Netzwerk")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "runtime"))
    original = duckdb.connect
    def guarded(database=":memory:", *args, **kwargs):
        assert str(database) == ":memory:" or Path(database).resolve().is_relative_to(tmp_path.resolve())
        return original(database, *args, **kwargs)
    monkeypatch.setattr(duckdb, "connect", guarded)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_price_point(PricePointCreate(
        asset="USDT", price_eur=D("0.9"),
        priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc), source="synthetic-observation",
    ))
    yield store
    assert sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file()) < 500 * 1024 * 1024


def ingest(store, content):
    batch = CsvRawImporter(store).import_text(source="bitget", filename="independent-synthetic.csv", content=content)
    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    return batch, events


def snapshot(store):
    with store.connect() as con:
        return {table: con.execute(f"select * from {table} order by 1").fetchall() for table in (
            "raw_objects", "canonical_events", "balance_ledger", "derivative_lines", "derivative_run_summaries",
        )}


def test_funding_renormalization_does_not_silently_approve_stale_zero_derivative_summary(case):
    store = case
    content = (
        "Order;Date;Coin;Futures;Margin Mode;Type;Amount;Fee;Wallet balance\n"
        "opening;2024-02-01T11:00:00Z;USDT;DEMOUSDT;Single-asset;trans_from_exchange;100;0;100\n"
        "funding;2024-02-01T12:00:00Z;USDT;DEMOUSDT;Single-asset;contract_margin_settle_fee;-2.30;0;97.70\n"
    )
    batch, events = ingest(store, content)
    funding = next(e for e in events if e.event_type == "derivative")
    # Alter Normalizer klassifizierte Funding als fee, nicht derivative.
    with store.connect() as con:
        con.execute("update canonical_events set event_type='fee' where event_id=?", [funding.event_id])
    BalanceLedgerBuilder(store).rebuild()
    old = DerivativesManager(store).rebuild()
    assert old.summary.realized_pnl_eur == D("0")
    assert old.summary.derivative_lines_count == 0
    RawNormalizer(store).normalize_batch(batch.batch_id)
    assert any(e.event_type == "derivative" and e.quantity == D("-2.30") for e in store.list_canonical_events())
    before = snapshot(store)
    gate = ReviewService(store).gate()
    assert snapshot(store) == before
    codes = sorted(issue.code for issue in gate.issues)
    fresh = DerivativesManager(store).rebuild()
    assert fresh.summary.realized_pnl_eur == D("-2.07")
    report = dict(
        synthetic_only=True, old_summary_eur="0", expected_eur="-2.07",
        fresh_summary_eur=str(fresh.summary.realized_pnl_eur), gate_allow_export=gate.allow_export,
        issue_codes=codes, raw_sha256=hashlib.sha256(content.encode()).hexdigest(),
    )
    (ROOT / "funding-stale-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    assert "derivative_cash_recalculation_required" in codes


def test_existing_gross_canonical_must_not_be_reinterpreted_as_after_fee_net(case):
    store = case
    content = (
        "Coin;Trading Pair;Action (English);Amount;Surplus/deduction (after fee);Fee;Timestamp UTC+8 (Order)\n"
        "USDT;DEMOUSDT_UMCBL;close_long;12.80;12.60;-0.20;2024-02-01 12:00:00\n"
    )
    batch, events = ingest(store, content)
    assert len(events) == 1 and events[0].quantity == D("12.60")
    # HEAD-Profil waehlte Amount vor After-fee: gespeicherter Altwert 12.80.
    with store.connect() as con:
        con.execute("update canonical_events set quantity=12.80")
    ledger = BalanceLedgerBuilder(store).rebuild()
    old = DerivativesManager(store).rebuild()
    assert sum((entry.delta_quantity for entry in ledger), D("0")) == D("12.80")
    assert old.summary.realized_pnl_eur == D("11.52")
    before = snapshot(store)
    gate = ReviewService(store).gate()
    assert snapshot(store) == before
    codes = sorted(issue.code for issue in gate.issues)
    RawNormalizer(store).normalize_batch(batch.batch_id)
    corrected = DerivativesManager(store).rebuild()
    assert corrected.summary.realized_pnl_eur == D("11.34")
    report = dict(
        synthetic_only=True, stored_canonical="12.80", raw_net="12.60",
        incorrectly_interpreted_eur="11.52", expected_eur="11.34",
        gate_allow_export=gate.allow_export, issue_codes=codes,
        raw_sha256=hashlib.sha256(content.encode()).hexdigest(),
    )
    (ROOT / "canonical-gross-vs-net.json").write_text(json.dumps(report, indent=2) + "\n")
    assert "derivative_normalization_required" in codes or "derivative_fee_semantics_required" in codes
