from decimal import Decimal

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.import_context import bitget_import_context
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_fee_deducted_in_remains_fee_asset_and_not_quote_asset(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic-bitget.duckdb")
    context = bitget_import_context(
        export_timezone="UTC", product_scope="spot", margin_pair=None,
    )
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="synthetic-bitget.csv",
        content=(
            "Date,Coin,Type,Amount,Amount (USDT),Fee Deducted In,Fee\n"
            "2025-01-02T12:00:00+00:00,DEMOCOIN,buy,5,100,BGB,0.1\n"
        ),
        import_context=context,
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "trade"
    assert event.quote_asset == "USDT"
    assert event.quote_quantity == Decimal("100")
    assert event.fee_asset == "BGB"
    assert event.fee_quantity == Decimal("0.1")
