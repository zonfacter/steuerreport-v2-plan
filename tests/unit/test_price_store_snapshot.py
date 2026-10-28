from datetime import datetime, timedelta, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


def test_explicit_full_price_snapshot_does_not_change_bounded_default(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    store.add_price_points([PricePointCreate(asset="SYNTHETIC", price_eur=Decimal("1"),
        priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
        source="synthetic:test") for day in range(501)])
    assert len(store.list_price_points()) == 500
    assert len(store.list_price_points(limit=1)) == 1
    full = store.list_price_points(limit=None)
    assert len(full) == 501
    assert full[-1].priced_at.replace(tzinfo=timezone.utc) == datetime(2021, 1, 1, tzinfo=timezone.utc)
