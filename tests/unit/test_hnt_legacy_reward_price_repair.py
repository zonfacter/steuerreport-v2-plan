from datetime import UTC, date, datetime
from decimal import Decimal

import importlib.util
import sys
import sqlite3
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_hnt_legacy_reward_price_repair_20260626.py"
)
SPEC = importlib.util.spec_from_file_location("run_hnt_legacy_reward_price_repair_20260626", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_load_reward_days_uses_existing_lookup_and_groups_by_date(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="helium", filename="legacy.csv"))
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"row":1}'),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                source_ref="a",
                event_time=datetime(2021, 9, 15, 10, 0, tzinfo=UTC),
                event_type="mining",
                asset="HNT",
                quantity=Decimal("2.5"),
                raw_object_id=raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                source_ref="b",
                event_time=datetime(2021, 9, 15, 20, 0, tzinfo=UTC),
                event_type="reward",
                asset="HNT",
                quantity=Decimal("1.5"),
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("20"),
            priced_at=datetime(2021, 9, 15, 0, 0, tzinfo=UTC),
            source="defillama_coingecko_history:usd_eur:v1_fx_cache",
            confidence=Decimal("0.95"),
        )
    )

    days = MODULE.load_reward_days(store=store, year=2021, asset="HNT", source="helium")

    assert len(days) == 1
    assert days[0].price_date == date(2021, 9, 15)
    assert days[0].event_count == 2
    assert days[0].quantity == Decimal("4.0")
    assert days[0].current_income_eur == Decimal("80.0")
    assert days[0].current_price_sources == ("defillama_coingecko_history:usd_eur:v1_fx_cache",)


def test_build_price_points_skips_existing_primary_dates():
    reward_days = [
        MODULE.RewardDay(
            price_date=date(2021, 9, 15),
            event_count=2,
            quantity=Decimal("4"),
            current_income_eur=Decimal("4"),
            current_price_sources=("derived:event_quote",),
        ),
        MODULE.RewardDay(
            price_date=date(2021, 9, 16),
            event_count=1,
            quantity=Decimal("3"),
            current_income_eur=Decimal("3"),
            current_price_sources=("derived:event_quote",),
        ),
    ]
    external_prices = {
        date(2021, 9, 15): MODULE.ExternalPrice(
            price_date=date(2021, 9, 15),
            price_usd=Decimal("20"),
            usd_eur=Decimal("0.85"),
            price_eur=Decimal("17.00"),
            provider_timestamp=1631664286,
            source=MODULE.SOURCE_LABEL,
        ),
        date(2021, 9, 16): MODULE.ExternalPrice(
            price_date=date(2021, 9, 16),
            price_usd=Decimal("22"),
            usd_eur=Decimal("0.86"),
            price_eur=Decimal("18.92"),
            provider_timestamp=1631750686,
            source=MODULE.SOURCE_LABEL,
        ),
    }

    points = MODULE.build_price_points(
        asset="HNT",
        reward_days=reward_days,
        external_prices=external_prices,
        existing_primary_dates={date(2021, 9, 15)},
    )

    assert len(points) == 1
    assert points[0].asset == "HNT"
    assert points[0].price_eur == Decimal("18.92")
    assert points[0].priced_at == datetime(2021, 9, 16, 0, 0, tzinfo=UTC)
    assert points[0].source == MODULE.SOURCE_LABEL


def test_build_report_shows_delta_and_importability():
    reward_day = MODULE.RewardDay(
        price_date=date(2021, 11, 15),
        event_count=3,
        quantity=Decimal("10"),
        current_income_eur=Decimal("10"),
        current_price_sources=("derived:event_quote",),
    )
    external = MODULE.ExternalPrice(
        price_date=date(2021, 11, 15),
        price_usd=Decimal("52.994419171856975"),
        usd_eur=Decimal("0.87321"),
        price_eur=Decimal("46.28115737081019483975"),
        provider_timestamp=1636934652,
        source=MODULE.SOURCE_LABEL,
    )

    report = MODULE.build_report(
        mode="dry-run",
        year=2021,
        asset="HNT",
        source="helium",
        reward_days=[reward_day],
        external_prices={date(2021, 11, 15): external},
        existing_primary_dates=set(),
        failures=[],
    )

    assert report["summary"]["current_income_eur"] == "10"
    assert report["summary"]["repaired_income_eur"] == "462.81157370810194839750"
    assert report["summary"]["delta_eur"] == "452.81157370810194839750"
    assert report["summary"]["importable_price_days"] == 1
    assert report["rows"][0]["will_import"] is True


def test_fetch_cached_eur_price_uses_asset_usd_and_usd_eur_fx_cache(tmp_path):
    fx_db = tmp_path / "steuerreport.db"
    with sqlite3.connect(fx_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text not null,
                base_ccy text not null,
                quote_ccy text not null,
                rate text not null,
                source text not null,
                source_rate_date text,
                updated_at_utc text not null
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2022-01-15", "HNT", "USD", "30", "defillama", "2022-01-15", "2026-01-01T00:00:00Z"),
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2022-01-15", "USD", "EUR", "0.88", "frankfurter", "2022-01-15", "2026-01-01T00:00:00Z"),
        )

    price = MODULE.fetch_cached_eur_price(
        asset="HNT",
        price_date=date(2022, 1, 15),
        v1_fx_db_path=fx_db,
        source_label="test_source",
    )

    assert price is not None
    assert price.price_usd == Decimal("30")
    assert price.usd_eur == Decimal("0.88")
    assert price.price_eur == Decimal("26.40")
    assert price.source == "test_source:asset_usd_v1_fx_cache"
