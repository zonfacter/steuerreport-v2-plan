from datetime import datetime
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derived_prices import (
    DERIVED_EVENT_QUOTE_SOURCE,
    DerivedPriceService,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_derived_prices_create_direct_eur_and_stable_quote_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="prices.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2021-01-01T00:00:00Z,USDT,100,deposit,EUR,82,test\n"
            "2021-01-02T00:00:00Z,HNT,10,buy,USDT,50,test\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = DerivedPriceService(store).rebuild_from_event_quotes()
    prices = {
        (point.asset, point.priced_at): point
        for point in store.list_price_points(limit=100)
        if point.source == DERIVED_EVENT_QUOTE_SOURCE
    }

    assert result.created == 2
    assert {asset for asset, _ in prices} == {"HNT", "USDT"}
    assert next(point for (asset, _), point in prices.items() if asset == "USDT").price_eur == Decimal(
        "0.820000000000000000"
    )
    assert next(point for (asset, _), point in prices.items() if asset == "HNT").price_eur == Decimal(
        "4.100000000000000000"
    )


def test_derived_prices_make_stable_quote_fifo_lot_nonzero(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="fifo.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2021-01-01T00:00:00Z,USDT,100,deposit,EUR,82,test\n"
            "2021-01-02T00:00:00Z,HNT,10,buy,USDT,50,test\n"
            "2021-03-01T00:00:00Z,HNT,-5,sell,USDT,30,test\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    DerivedPriceService(store).rebuild_from_event_quotes()

    result = TaxService(store).rebuild_fifo()

    assert len(result.tax_lines) == 2
    hnt_line = next(line for line in result.tax_lines if line.asset == "HNT")
    assert hnt_line.acquisition_cost_eur == Decimal("20.5000000000000000000")
    assert hnt_line.disposal_proceeds_eur == Decimal("24.600000000000000000")


def test_derived_prices_use_same_timestamp_counterflow_group(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "26-02-02 15:51:51,Spot,Transaction Buy,DOGE,17\n"
            "26-02-02 15:51:51,Spot,Transaction Buy,DOGE,373\n"
            "26-02-02 15:51:51,Spot,Transaction Spend,EUR,-36.4257\n"
            "26-02-02 15:51:51,Spot,Transaction Spend,EUR,-1.52898\n"
            "26-02-02 15:51:51,Spot,Transaction Fee,BNB,-0.00000168\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = DerivedPriceService(store).rebuild_from_event_quotes()
    price = next(
        point
        for point in store.list_price_points(limit=100)
        if point.asset == "DOGE" and point.source == DERIVED_EVENT_QUOTE_SOURCE
    )

    assert result.created == 1
    assert price.price_eur == Decimal("0.097319692307692308")


def test_price_requirements_do_not_treat_derived_quotes_as_primary_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="derived-requirement.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2024-10-06T05:47:02Z,ZEUS,100,buy,IOT,100000,test\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    with store.connect() as con:
        con.execute("update canonical_events set source = 'solana_rpc'")
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.0000004"),
            priced_at=datetime(2024, 10, 6, 5, 47, 2),
            source=DERIVED_EVENT_QUOTE_SOURCE,
            confidence=Decimal("0.85"),
        )
    )

    requirements = PriceCoverageService(store).requirements().requirements

    assert any(item.asset == "IOT" for item in requirements)


def test_price_requirements_require_same_day_primary_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="same-day-requirement.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2024-10-06T05:47:02Z,ZEUS,100,buy,IOT,100000,test\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    with store.connect() as con:
        con.execute("update canonical_events set source = 'solana_rpc'")
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.0011"),
            priced_at=datetime(2024, 8, 29, 0, 0, 0),
            source="defillama_coingecko_history:usd_eur:v1_fx_cache",
            confidence=Decimal("1"),
        )
    )

    requirements = PriceCoverageService(store).requirements().requirements

    assert any(
        item.asset == "IOT" and item.price_date.isoformat() == "2024-10-06"
        for item in requirements
    )
