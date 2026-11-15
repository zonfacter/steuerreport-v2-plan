from datetime import datetime, timezone
from decimal import Decimal

import duckdb
import pytest

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_years import TaxYearService


def price(value):
    return PricePointCreate(asset="SYNTH", price_eur=Decimal(value),
                            priced_at=datetime(2025, 1, 1, tzinfo=timezone.utc), source="synthetic")


def test_read_snapshot_keeps_one_version_across_store_calls(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    first = store.add_price_point(price("2"))
    writer = DuckDbStore(store.path)
    # Prepare the second connection without schema writes during the test.
    with writer.connect():
        pass
    with store.read_snapshot() as snapshot:
        assert [p.price_id for p in snapshot.list_price_points()] == [first.price_id]
        second = writer.add_price_point(price("3"))
        assert [p.price_id for p in snapshot.list_price_points()] == [first.price_id]
        with snapshot.connect() as con:
            assert con.execute("select count(*) from price_ledger").fetchone() == (1,)
    assert {p.price_id for p in store.list_price_points()} == {first.price_id, second.price_id}
    with pytest.raises(RuntimeError, match="read_snapshot_closed"):
        snapshot.list_price_points()


def test_read_snapshot_refuses_writes_and_releases_after_error(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_price_point(price("2"))
    with pytest.raises(duckdb.TransactionException):
        with store.read_snapshot() as snapshot:
            snapshot.add_price_point(price("9"))
    assert len(store.list_price_points()) == 1
    store.add_price_point(price("3"))
    assert len(store.list_price_points()) == 2


def test_closing_borrowed_connection_does_not_end_snapshot(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    with store.read_snapshot() as snapshot:
        with snapshot.connect() as con:
            con.close()
        assert snapshot.list_price_points() == []
        with snapshot.connect() as con:
            with pytest.raises(RuntimeError, match="not_supported"):
                con.commit()


def test_real_filing_summary_runs_inside_read_only_snapshot(tmp_path, monkeypatch):
    profile = tmp_path / "synthetic-profile.json"
    profile.write_text("{}")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path))
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    with store.read_snapshot() as snapshot:
        summary = TaxYearService(snapshot).filing_summary(2025)
        assert summary.year == 2025
        assert summary.taxable_private_disposals_eur == Decimal("0")
        assert "taxable_private_disposals_eur" in summary.model_fields_set
