from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.flows import FlowService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_flow_summary_uses_net_eur_transfers_not_trades(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "time,coin,change,type,account\n"
            "2021-04-28T10:00:00Z,USDT,100,deposit,pionex-main\n"
            "2021-04-29T10:00:00Z,USDT,-25,withdrawal,pionex-main\n"
            "2021-04-30T10:00:00Z,BTC,0.1,buy,pionex-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    entries = FlowService(store).rebuild()
    summary = FlowService(store).summary()

    assert len(entries) == 2
    assert summary.total_visible_value_eur == Decimal("67.500000000000000000000000000000000000")
    assert [(edge.source_node, edge.target_node) for edge in summary.edges] == [
        ("external", "pionex-main"),
    ]
    assert summary.edges[0].event_count == 2


def test_flow_summary_nets_bidirectional_edges(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "time,coin,change,type,account\n"
            "2021-04-28T10:00:00Z,USDT,100,deposit,Spot\n"
            "2021-04-29T10:00:00Z,USDT,-80,withdrawal,Spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    FlowService(store).rebuild()
    summary = FlowService(store).summary()

    assert len(summary.edges) == 1
    assert summary.edges[0].source_node == "external"
    assert summary.edges[0].target_node == "Spot"
    assert summary.edges[0].value_eur == Decimal("18.000000000000000000")
    assert summary.edges[0].event_count == 2
    assert summary.total_visible_value_eur == Decimal("18.000000000000000000")


def test_flow_summary_reports_missing_price_assets(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,BTC,0.5,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    FlowService(store).rebuild()
    summary = FlowService(store).summary()

    assert summary.total_visible_value_eur == Decimal("0")
    assert summary.edges == []
    assert summary.missing_price_assets == ["BTC"]


def test_flow_summary_merges_unique_truncated_wallet_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV"
    short_wallet = "133iWieuw...xU6WUW8v"
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="wallets.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2024-01-01T00:00:00Z,HNT,10,deposit,{wallet}\n"
            f"2024-01-02T00:00:00Z,HNT,2,deposit,{short_wallet} \n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("5.00"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    FlowService(store).rebuild()
    summary = FlowService(store).summary()

    assert len(summary.edges) == 1
    assert summary.edges[0].source_node == "external"
    assert summary.edges[0].target_node == wallet
    assert summary.edges[0].event_count == 2
    assert summary.total_visible_value_eur == Decimal("60.000000000000000000")


def test_flow_summary_filters_by_year_and_reports_available_years(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "time,coin,change,type,account\n"
            "2021-04-28T10:00:00Z,USDT,100,deposit,pionex-main\n"
            "2022-04-28T10:00:00Z,USDT,50,deposit,pionex-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1.00"),
            priced_at=datetime(2022, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    FlowService(store).rebuild()
    summary = FlowService(store).summary(year=2021)

    assert summary.year == 2021
    assert summary.available_years == [2021, 2022]
    assert summary.total_visible_value_eur == Decimal("90.000000000000000000000000000000000000")
    assert len(summary.edges) == 1


def test_flow_rebuild_uses_historical_price_at_event_time(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,USDT,100,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.80"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="old-price",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1.10"),
            priced_at=datetime(2021, 4, 30, tzinfo=timezone.utc),
            source="future-price",
        )
    )

    FlowService(store).rebuild()
    summary = FlowService(store).summary()

    assert summary.total_visible_value_eur == Decimal("80.000000000000000000000000000000000000")
    assert summary.edges[0].value_eur == Decimal("80.000000000000000000")


def test_flow_rebuild_prefers_event_quote_eur_over_price_ledger(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "time,coin,change,type,quote_asset,quote_quantity\n"
            "2021-04-28T10:00:00Z,USDT,100,deposit,EUR,91\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.80"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="price-ledger",
        )
    )

    entries = FlowService(store).rebuild()
    summary = FlowService(store).summary()

    assert entries[0].value_eur == Decimal("91.000000000000000000")
    assert entries[0].price_source == "event_quote"
    assert summary.total_visible_value_eur == Decimal("91.000000000000000000")
