from datetime import datetime
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup


def test_lookup_prefers_primary_same_day_price_over_later_derived_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    primary = store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.0012"),
            priced_at=datetime(2024, 10, 6, 0, 0),
            source="defillama_coingecko_history:usd_eur:v1_fx_cache",
            confidence=Decimal("1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.0000004"),
            priced_at=datetime(2024, 10, 6, 5, 47),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )

    price = HistoricalPriceLookup(store).at_or_before(
        "IOT",
        datetime(2024, 10, 6, 6, 0),
    )

    assert price is not None
    assert price.price_id == primary.price_id


def test_lookup_can_require_non_derived_primary_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("240972.922372"),
            priced_at=datetime(2023, 4, 25, 4, 17),
            source="derived:event_quote",
            confidence=Decimal("0.80"),
        )
    )

    lookup = HistoricalPriceLookup(store)

    assert lookup.at_or_before(
        "SOL",
        datetime(2023, 4, 25, 5, 0),
    ) is not None
    assert (
        lookup.at_or_before(
            "SOL",
            datetime(2023, 4, 25, 5, 0),
            allow_derived=False,
        )
        is None
    )
