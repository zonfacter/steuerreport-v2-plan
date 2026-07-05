from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_fifo_tax_rebuild_creates_gain_loss_line(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,BTC,1,buy,EUR,10000\n"
            "2021-06-01T00:00:00Z,BTC,-0.4,sell,EUR,6000\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = TaxService(store).rebuild_fifo()
    summary = TaxService(store).latest_summary()

    assert result.unmatched_disposals == 0
    assert len(result.lots) == 1
    assert result.lots[0].quantity_remaining == Decimal("0.600000000000000000")
    assert TaxService(store).list_tax_lots()[0].quantity_remaining == Decimal("0.600000000000000000")
    assert len(result.tax_lines) == 1
    assert result.tax_lines[0].acquisition_cost_eur == Decimal(
        "4000.000000000000000000000000000000000000"
    )
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal(
        "6000.000000000000000000"
    )
    assert result.tax_lines[0].gain_loss_eur == Decimal(
        "2000.000000000000000000000000000000000000"
    )
    assert summary is not None
    assert summary.tax_lines_count == 1
    assert summary.unmatched_disposals == 0


def test_holding_period_report_filters_dust_and_buckets_tax_free_lots(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="holding.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2024-01-01T00:00:00Z,SOL,2,buy,EUR,20,Spot\n"
            "2025-12-28T00:00:00Z,JUP,10,buy,EUR,5,Spot\n"
            "2025-12-31T00:00:00Z,BONK,1,buy,EUR,0.1,Spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("12"),
            priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.5"),
            priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BONK",
            price_eur=Decimal("0.1"),
            priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = TaxService(store).holding_period_report(
        min_value_eur=Decimal("1"),
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert report.visible_lots_count == 2
    assert report.hidden_dust_lots_count == 1
    assert report.tax_free_now_value_eur == Decimal("24.000000000000000000")
    assert report.next_year_value_eur == Decimal("5.000000000000000000")
    by_asset = {lot.asset: lot for lot in report.lots}
    assert by_asset["SOL"].bucket == "tax_free_now"
    assert by_asset["JUP"].bucket == "next_year"
    assert by_asset["JUP"].days_until_tax_free == 362
    assert by_asset["SOL"].source == "binance"
    assert by_asset["SOL"].account == "Spot"


def test_fifo_tax_reports_unmatched_disposal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content="time,asset,amount,type,quote_asset,quote_quantity\n2021-01-01T00:00:00Z,ETH,-1,sell,EUR,1000\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = TaxService(store).rebuild_fifo()
    summary = TaxService(store).latest_summary()

    assert result.unmatched_disposals == 1
    assert result.tax_lines == []
    assert summary is not None
    assert summary.unmatched_disposals == 1


def test_fifo_tax_ignores_fiat_eur_movements(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="fiat.csv",
        content=(
            "time,asset,amount,type\n"
            "2021-01-01T00:00:00Z,EUR,100,deposit\n"
            "2021-02-01T00:00:00Z,EUR,-50,sell\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = TaxService(store).rebuild_fifo()
    summary = TaxService(store).latest_summary()

    assert result.lots == []
    assert result.tax_lines == []
    assert result.unmatched_disposals == 0
    assert summary is not None
    assert summary.unmatched_disposals == 0


def test_fifo_creates_lot_from_positive_transfer_with_quote_value(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="fiat-buy.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,USDT,100,transfer,EUR,82\n"
            "2021-02-01T00:00:00Z,USDT,-40,sell,EUR,36\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert len(result.lots) == 1
    assert result.lots[0].cost_basis_eur_total == Decimal("82.000000000000000000")
    assert result.tax_lines[0].acquisition_cost_eur == Decimal(
        "32.800000000000000000000000000000000000"
    )


def test_income_events_create_fifo_lots_for_later_sales(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="hnt.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,HNT,10,mining,EUR,20\n"
            "2021-06-01T00:00:00Z,HNT,-4,sell,EUR,40\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert len(result.lots) == 1
    assert result.lots[0].quantity_remaining == Decimal("6.000000000000000000")
    assert result.tax_lines[0].acquisition_cost_eur == Decimal(
        "8.000000000000000000000000000000000000"
    )
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal("40.000000000000000000")
    assert result.tax_lines[0].gain_loss_eur == Decimal(
        "32.000000000000000000000000000000000000"
    )


def test_fifo_uses_historical_price_when_quote_value_is_missing(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="hnt.csv",
        content=(
            "time,asset,amount,type\n"
            "2021-01-01T00:00:00Z,HNT,10,mining\n"
            "2021-06-01T00:00:00Z,HNT,-4,sell\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="acquisition-price",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("7"),
            priced_at=datetime(2021, 6, 1, tzinfo=timezone.utc),
            source="sale-price",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert result.tax_lines[0].acquisition_cost_eur == Decimal(
        "8.000000000000000000000000000000000000"
    )
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal("28.000000000000000000")


def test_fifo_values_crypto_quote_quantity_with_historical_quote_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="mxc.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,MXC,100,buy,USDT,10\n"
            "2021-06-01T00:00:00Z,MXC,-40,sell,USDT,8\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.80"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="usdt-buy-price",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 6, 1, tzinfo=timezone.utc),
            source="usdt-sell-price",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="MXC",
            price_eur=Decimal("999"),
            priced_at=datetime(2021, 6, 1, tzinfo=timezone.utc),
            source="should-not-be-used",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert result.lots[0].cost_basis_eur_total == Decimal("8.000000000000000000")
    assert result.tax_lines[0].acquisition_cost_eur == Decimal(
        "3.200000000000000000000000000000000000"
    )
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal("7.200000000000000000")


def test_fifo_creates_quote_asset_disposal_for_crypto_to_crypto_buy(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="sol-jup.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,SOL,10,buy,EUR,1000\n"
            "2024-02-01T00:00:00Z,JUP,100,buy,SOL,2\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("120"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="sol-price",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert len(result.tax_lines) == 1
    assert result.tax_lines[0].asset == "SOL"
    assert result.tax_lines[0].quantity == Decimal("2.000000000000000000")
    assert result.tax_lines[0].acquisition_cost_eur == Decimal(
        "200.000000000000000000000000000000000000"
    )
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal("240.000000000000000000")
    lots_by_asset = {lot.asset: lot for lot in result.lots}
    assert lots_by_asset["JUP"].cost_basis_eur_total == Decimal("240.000000000000000000")


def test_fifo_reports_unmatched_quote_asset_disposal_for_crypto_buy(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="btc-sol.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,BTC,0.01,buy,EUR,250\n"
            "2024-02-01T00:00:00Z,SOL,20,buy,BTC,0.02\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("30000"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="btc-price",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 1
    assert len(result.tax_lines) == 1
    assert result.tax_lines[0].asset == "BTC"
    assert result.tax_lines[0].quantity == Decimal("0.010000000000000000")
    assert result.unmatched[0].asset == "BTC"
    assert result.unmatched[0].quantity == Decimal("0.020000000000000000")
    assert result.unmatched[0].missing_quantity == Decimal("0.010000000000000000")


def test_fifo_ignores_tiny_sol_quote_dust_disposal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="solana_rpc",
        filename="sol-dust.csv",
        content=(
            "timestamp_utc,asset,quantity,event_type,quote_asset,quote_quantity,wallet_address\n"
            "2023-04-25T04:17:52Z,IOT,100,swap_in_aggregated,SOL,0.00001,wallet-1\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("19"),
            priced_at=datetime(2023, 4, 25, tzinfo=timezone.utc),
            source="unit",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert result.unmatched == []


def test_fifo_creates_stable_quote_asset_disposal_for_crypto_buy(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="usdc-sol.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,USDC,12000,buy,EUR,11000\n"
            "2024-02-01T00:00:00Z,SOL,46.5,buy,USDC,11289.078251\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="usdc-price",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert len(result.tax_lines) == 1
    assert result.tax_lines[0].asset == "USDC"
    assert result.tax_lines[0].quantity == Decimal("11289.078251000000000000")
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal(
        "10385.951990920000000000"
    )


def test_fifo_creates_non_stable_quote_asset_lot_for_crypto_sale(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="jup-usdc.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,JUP,100,buy,EUR,50\n"
            "2024-02-01T00:00:00Z,JUP,-40,sell,SOL,0.3\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("90"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="sol-price",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    assert result.tax_lines[0].asset == "JUP"
    assert result.tax_lines[0].disposal_proceeds_eur == Decimal("27.000000000000000000")
    lots_by_asset = {lot.asset: lot for lot in result.lots}
    assert lots_by_asset["SOL"].quantity_total == Decimal("0.300000000000000000")
    assert lots_by_asset["SOL"].cost_basis_eur_total == Decimal("27.000000000000000000")


def test_fifo_values_quote_asset_disposal_with_received_stable_asset_value(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="trump-usdt.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-20T07:12:26Z,TRUMP,140,buy,USDT,8252.81\n"
            "2025-01-20T08:49:58Z,USDT,8363.63,buy,TRUMP,140\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.96"),
            priced_at=datetime(2025, 1, 20, 7, 12, 26, tzinfo=timezone.utc),
            source="usdt-price",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="TRUMP",
            price_eur=Decimal("35"),
            priced_at=datetime(2025, 1, 20, 7, 12, 26, tzinfo=timezone.utc),
            source="should-not-price-disposal-proceeds",
        )
    )

    result = TaxService(store).rebuild_fifo()

    assert result.unmatched_disposals == 0
    trump_line = next(line for line in result.tax_lines if line.asset == "TRUMP")
    assert trump_line.acquisition_cost_eur == Decimal("7922.697600000000000000")
    assert trump_line.disposal_proceeds_eur == Decimal("8029.084800000000000000")
    assert trump_line.gain_loss_eur == Decimal("106.387200000000000000")
