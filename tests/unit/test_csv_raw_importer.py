import json

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


def test_csv_raw_import_preserves_rows_as_raw_objects(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)

    batch = importer.import_text(
        source="binance",
        filename="binance.csv",
        content="Time,Asset,Amount\n2021-01-01,BTC,0.1\n2021-01-02,ETH,2\n",
    )

    assert batch.status == "loaded"
    assert batch.raw_object_count == 2
    assert batch.file_hash.startswith("sha256:")


def test_csv_raw_import_keeps_source_columns(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)
    batch = importer.import_text(
        source="pionex",
        filename="pionex.csv",
        content="coin,change,type\nUSDT,100,deposit\n",
    )

    with store.connect() as con:
        row = con.execute(
            "select payload_json from raw_objects where batch_id = ?",
            [batch.batch_id],
        ).fetchone()

    assert json.loads(row[0]) == {
        "change": "100",
        "coin": "USDT",
        "type": "deposit",
    }


def test_csv_preview_matches_binance_columns_without_persisting(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)

    preview = importer.preview_text(
        source="binance",
        filename="binance.csv",
        content="UTC Time,Operation,Coin,Change\n2021-01-01 00:00:00,Buy,BTC,0.1\n",
    )

    assert preview.can_import is True
    assert preview.row_count == 1
    assert preview.matched_columns["time"] == "UTC Time"
    assert preview.matched_columns["asset"] == "Coin"
    assert preview.matched_columns["quantity"] == "Change"
    assert preview.missing_required_groups == []
    assert store.list_import_batches() == []


def test_csv_preview_reports_missing_required_columns(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)

    preview = importer.preview_text(
        source="pionex",
        filename="broken.csv",
        content="time,asset,note\n2021-01-01T00:00:00Z,BTC,no amount\n",
    )

    assert preview.can_import is False
    assert preview.missing_required_groups == ["quantity"]


def test_csv_import_returns_existing_batch_for_duplicate_content(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)
    content = "Time,Asset,Amount\n2021-01-01,BTC,0.1\n"

    first = importer.import_text(source="binance", filename="a.csv", content=content)
    second = importer.import_text(source="binance", filename="b.csv", content=content)
    preview = importer.preview_text(source="binance", filename="b.csv", content=content)

    assert second.batch_id == first.batch_id
    assert second.raw_object_count == 1
    assert len(store.list_import_batches()) == 1
    assert preview.duplicate_batch_id == first.batch_id


def test_csv_import_skips_zero_quantity_helium_reward_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)

    batch = importer.import_text(
        source="helium",
        filename="helium.csv",
        content=(
            "block,date,type,transaction_hash,hnt_amount,mobile_amount\n"
            "1,22.09.2022 21:17,rewards_v1,tx-zero,0,0\n"
            "2,22.09.2022 21:18,rewards_v1,tx-real,0.5,0\n"
        ),
    )

    assert batch.raw_object_count == 1


def test_csv_import_skips_spacer_rows_without_time_or_amount(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)

    batch = importer.import_text(
        source="helium",
        filename="heliumtracker.csv",
        content=(
            "Sender,Receiver,Memo,Amount,Time\n"
            ",138bCXPVf,,,\n"
            "sender,receiver,,12.5,2022-10-14 at 09:41PM\n"
        ),
    )

    assert batch.raw_object_count == 1
