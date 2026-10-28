"""Zwei feste Altstand-Referenzen: Review darf Daten nur markieren, nie reparieren."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import socket

import duckdb
import pytest

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
import steuerreport_v2.domain.derivative_cash as cash_module
import steuerreport_v2.domain.derivatives as derivatives_module
import steuerreport_v2.domain.review as review_module
import steuerreport_v2.importers.raw_normalizer as normalizer_module
import steuerreport_v2.importers.source_profiles as profiles_module
import steuerreport_v2.ledger.balance as balance_module


D = Decimal


@pytest.fixture(scope="session", autouse=True)
def frozen_sources(tmp_path_factory):
    modules = (
        cash_module,
        derivatives_module,
        review_module,
        normalizer_module,
        profiles_module,
        balance_module,
    )

    def hashes():
        return {
            module.__name__: hashlib.sha256(
                Path(module.__file__).read_bytes()
            ).hexdigest()
            for module in modules
        }

    before = hashes()
    yield
    after = hashes()
    (tmp_path_factory.getbasetemp() / "bitget-stale-source-freeze.json").write_text(
        json.dumps(
            {"before": before, "after": after, "unchanged": before == after}, indent=2
        )
        + "\n"
    )
    assert before == after, "Runtime waehrend Referenzlauf veraendert"


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv(
        "STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "private-configs")
    )
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(tmp_path / "synthetic.duckdb"))
    original = duckdb.connect

    def guarded(database=":memory:", *args, **kwargs):
        assert str(database) == ":memory:" or Path(database).resolve().is_relative_to(
            tmp_path.resolve()
        )
        return original(database, *args, **kwargs)

    def blocked(*args, **kwargs):
        raise OSError("Bitget-Referenz: kein Netzwerk")

    monkeypatch.setattr(duckdb, "connect", guarded)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=D("0.9"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="synthetic-observation",
        )
    )
    yield store, tmp_path
    assert (
        sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file())
        < 500 * 1024 * 1024
    )


def ingest(store, content):
    from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter

    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="independent-stale-synthetic.csv",
        content=content,
    )
    events = normalizer_module.RawNormalizer(store).normalize_batch(batch.batch_id)
    return batch, events


def snapshot(store):
    with store.connect() as con:
        return {
            table: con.execute(f"select * from {table} order by 1").fetchall()
            for table in (
                "raw_objects",
                "canonical_events",
                "balance_ledger",
                "derivative_lines",
                "derivative_run_summaries",
                "price_ledger",
            )
        }


def test_funding_renormalization_blocks_stale_zero_summary_even_without_fee(case):
    store, path = case
    content = (
        "Order;Date;Coin;Futures;Margin Mode;Type;Amount;Fee;Wallet balance\n"
        "opening;2024-02-01T11:00:00Z;USDT;DEMOUSDT;Single-asset;trans_from_exchange;100;0;100\n"
        "funding;2024-02-01T12:00:00Z;USDT;DEMOUSDT;Single-asset;contract_margin_settle_fee;-2.30;0;97.70\n"
    )
    batch, events = ingest(store, content)
    funding = next(event for event in events if event.event_type == "derivative")
    # Synthetischer gespeicherter Altstand: Funding war als fee klassifiziert.
    with store.connect() as con:
        con.execute(
            "update canonical_events set event_type='fee' where event_id=?",
            [funding.event_id],
        )
    balance_module.BalanceLedgerBuilder(store).rebuild()
    old = derivatives_module.DerivativesManager(store).rebuild()
    assert old.summary.realized_pnl_eur == D("0")
    assert old.summary.derivative_lines_count == 0
    normalizer_module.RawNormalizer(store).normalize_batch(batch.batch_id)
    assert any(
        event.event_type == "derivative" and event.quantity == D("-2.30")
        for event in store.list_canonical_events()
    )
    before = snapshot(store)
    gate = review_module.ReviewService(store).gate()
    assert snapshot(store) == before
    codes = {issue.code for issue in gate.issues if issue.blocks_export}
    (path / "observed-before-explicit-rebuild.json").write_text(
        json.dumps(
            {
                "synthetic_only": True,
                "stored_eur": "0",
                "expected_eur": "-2.07",
                "gate_allow_export": gate.allow_export,
                "blocking_codes": sorted(codes),
            },
            indent=2,
        )
        + "\n"
    )
    assert "derivative_cash_recalculation_required" in codes
    assert gate.allow_export is False
    # Nur der explizite Fixture-Rebuild darf die gespeicherte Auswertung ersetzen.
    ledger = balance_module.BalanceLedgerBuilder(store).rebuild()
    fresh = derivatives_module.DerivativesManager(store).rebuild()
    assert sum((entry.delta_quantity for entry in ledger), D("0")) == D("97.70")
    assert fresh.summary.realized_pnl_eur == D("-2.07")
    assert "derivative_cash_recalculation_required" not in {
        issue.code for issue in review_module.ReviewService(store).gate().issues
    }


def test_existing_gross_canonical_conflicts_with_explicit_after_fee_net(case):
    store, path = case
    content = (
        "Coin;Trading Pair;Action (English);Amount;Surplus/deduction (after fee);Fee;Timestamp UTC+8 (Order)\n"
        "USDT;DEMOUSDT_UMCBL;close_long;12.80;12.60;-0.20;2024-02-01 12:00:00\n"
    )
    batch, events = ingest(store, content)
    assert len(events) == 1 and events[0].quantity == D("12.60")
    # Altes Profil priorisierte Amount; dieser Altwert darf nicht still Netto werden.
    with store.connect() as con:
        con.execute("update canonical_events set quantity=12.80")
    ledger = balance_module.BalanceLedgerBuilder(store).rebuild()
    old = derivatives_module.DerivativesManager(store).rebuild()
    assert sum((entry.delta_quantity for entry in ledger), D("0")) == D("12.80")
    assert old.summary.realized_pnl_eur == D("11.52")
    before = snapshot(store)
    gate = review_module.ReviewService(store).gate()
    assert snapshot(store) == before
    codes = {issue.code for issue in gate.issues if issue.blocks_export}
    (path / "observed-before-explicit-normalization.json").write_text(
        json.dumps(
            {
                "synthetic_only": True,
                "canonical_quantity": "12.80",
                "raw_net": "12.60",
                "stored_eur": "11.52",
                "expected_eur": "11.34",
                "gate_allow_export": gate.allow_export,
                "blocking_codes": sorted(codes),
            },
            indent=2,
        )
        + "\n"
    )
    assert codes & {
        "derivative_normalization_required",
        "derivative_fee_semantics_required",
    }
    assert gate.allow_export is False
    normalizer_module.RawNormalizer(store).normalize_batch(batch.batch_id)
    ledger = balance_module.BalanceLedgerBuilder(store).rebuild()
    corrected = derivatives_module.DerivativesManager(store).rebuild()
    assert sum((entry.delta_quantity for entry in ledger), D("0")) == D("12.60")
    assert corrected.summary.realized_pnl_eur == D("11.34")
    assert not (
        {"derivative_normalization_required", "derivative_fee_semantics_required"}
        & {issue.code for issue in review_module.ReviewService(store).gate().issues}
    )
