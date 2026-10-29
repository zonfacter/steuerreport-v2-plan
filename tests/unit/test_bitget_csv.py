import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.bitget_csv import BitgetCsvStructureError
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_bitget_direct_csv_path_discards_only_empty_surplus_fields_and_keeps_hash(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    importer = CsvRawImporter(store)
    content = (
        "Date,Coin,Type,Amount,Fee,Fee asset\n"
        "2025-01-02 12:00:00,DEMOCOIN,deposit,4,0,BGB,, \n"
    )

    preview = importer.preview_text("bitget", "synthetic.csv", content)
    batch = importer.import_text("bitget", "synthetic.csv", content)

    assert preview.can_import is True
    assert preview.row_count == 1
    assert preview.file_sha256 == importer.hash_text(content)
    assert batch.file_hash == importer.hash_text(content)
    raw = store.list_raw_objects(batch.batch_id)
    assert len(raw) == 1
    payload = json.loads(raw[0].payload_json)
    assert payload == {
        "Amount": "4",
        "Coin": "DEMOCOIN",
        "Date": "2025-01-02 12:00:00",
        "Fee": "0",
        "Fee asset": "BGB",
        "Type": "deposit",
    }
    assert "None" not in payload


def test_bitget_native_file_preview_and_import_keep_original_byte_hash(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    raw_bytes = (
        b"Date,Coin,Type,Amount,Fee,Fee asset\r\n"
        b"2025-01-02 12:00:00,DEMOCOIN,deposit,4,0,BGB,,\r\n"
    )
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    expected_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    preview = importer.preview_base64("bitget", "synthetic.csv", encoded)
    batch = importer.import_base64("bitget", "synthetic.csv", encoded)
    repeated = importer.import_base64("bitget", "synthetic.csv", encoded)

    assert preview.can_import is True
    assert preview.row_count == 1
    assert preview.sample_rows == [{
        "Date": "2025-01-02 12:00:00",
        "Coin": "DEMOCOIN",
        "Type": "deposit",
        "Amount": "4",
        "Fee": "0",
        "Fee asset": "BGB",
    }]
    assert preview.file_sha256 == expected_hash
    assert batch.file_hash == expected_hash
    assert repeated.batch_id == batch.batch_id
    assert len(store.list_import_batches()) == 1
    raw = store.list_raw_objects(batch.batch_id)
    assert len(raw) == 1
    assert json.loads(raw[0].payload_json) == preview.sample_rows[0]


def test_bitget_direct_csv_path_reports_nonempty_surplus_row_and_creates_no_batch(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    importer = CsvRawImporter(store)
    content = (
        "Date,Coin,Type,Amount,Fee,Fee asset\n"
        "2025-01-02 12:00:00,DEMOCOIN,deposit,4,0,BGB\n"
        "2025-01-03 12:00:00,DEMOCOIN,deposit,5,0,BGB,UNMAPPED\n"
    )

    with pytest.raises(BitgetCsvStructureError, match=r"Zeile 3 enthaelt nichtleere"):
        importer.preview_text("bitget", "synthetic.csv", content)
    with pytest.raises(BitgetCsvStructureError, match=r"Zeile 3 enthaelt nichtleere"):
        importer.import_text("bitget", "synthetic.csv", content)

    assert store.list_import_batches() == []


@pytest.mark.parametrize("route", ["/api/v1/import/csv/preview", "/api/v1/import/csv/raw"])
def test_bitget_api_reports_nonempty_surplus_row_without_server_error_or_batch(tmp_path, route):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    client = TestClient(create_app(store))
    content = (
        "Date,Coin,Type,Amount,Fee,Fee asset\n"
        "2025-01-02 12:00:00,DEMOCOIN,deposit,4,0,BGB\n"
        "2025-01-03 12:00:00,DEMOCOIN,deposit,5,0,BGB,UNMAPPED\n"
    )

    response = client.post(route, json={
        "source": "bitget", "filename": "synthetic.csv", "content": content,
    })

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "bitget_csv_structure_invalid"
    assert "Zeile 3 enthaelt nichtleere" in result["errors"][0]["message"]
    assert result["errors"][0]["field"] == "content"
    assert store.list_import_batches() == []


@pytest.mark.parametrize(
    ("route", "content_kind"),
    [
        ("/api/v1/import/csv/preview", "text"),
        ("/api/v1/import/csv/raw", "text"),
        ("/api/v1/import/file/preview", "base64"),
        ("/api/v1/import/file/raw", "base64"),
        ("/api/v1/import/assistant/preview", "text"),
        ("/api/v1/import/assistant/preview", "base64"),
        ("/api/v1/import/assistant/execute", "text"),
        ("/api/v1/import/assistant/execute", "base64"),
    ],
)
def test_bitget_csv_and_file_apis_share_structured_surplus_error(
    tmp_path, route, content_kind,
):
    store = DuckDbStore(tmp_path / f"{route.rsplit('/', 1)[-1]}-{content_kind}.duckdb")
    client = TestClient(create_app(store))
    rows = [f"2025-01-{day:02d} 12:00:00,DEMOCOIN,deposit,{day},0,BGB" for day in range(1, 7)]
    rows.append("2025-01-07 12:00:00,DEMOCOIN,deposit,7,0,BGB,UNMAPPED")
    content = "Date,Coin,Type,Amount,Fee,Fee asset\n" + "\n".join(rows) + "\n"
    request = {"source": "bitget", "filename": "synthetic.csv"}
    if content_kind == "text":
        request["content"] = content
    else:
        request["content_base64"] = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(route, json=request)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "bitget_csv_structure_invalid"
    assert result["errors"][0]["field"] == (
        "content_base64" if content_kind == "base64" else "content"
    )
    assert "Zeile 8 enthaelt nichtleere" in result["errors"][0]["message"]
    assert store.list_import_batches() == []


@pytest.mark.parametrize(
    ("route", "content_kind"),
    [
        ("/api/v1/import/csv/preview", "text"),
        ("/api/v1/import/file/preview", "base64"),
        ("/api/v1/import/assistant/preview", "text"),
        ("/api/v1/import/assistant/preview", "base64"),
    ],
)
def test_bitget_csv_preview_parity_for_empty_surplus_and_original_hash(
    tmp_path, route, content_kind,
):
    store = DuckDbStore(tmp_path / f"preview-{route.rsplit('/', 1)[-1]}-{content_kind}.duckdb")
    client = TestClient(create_app(store))
    content = (
        "Date,Coin,Type,Amount,Fee,Fee asset\n"
        "2025-01-02 12:00:00,DEMOCOIN,deposit,4,0,BGB,, \n"
    )
    request = {"source": "bitget", "filename": "synthetic.csv"}
    if content_kind == "text":
        request["content"] = content
        expected_hash = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    else:
        raw_bytes = content.encode("utf-8")
        request["content_base64"] = base64.b64encode(raw_bytes).decode("ascii")
        expected_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    response = client.post(route, json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "warning"}
    preview = body["data"]
    if route == "/api/v1/import/assistant/preview":
        preview = preview["preview"]
    assert preview["row_count"] == 1
    assert preview["sample_rows"] == [{
        "Date": "2025-01-02 12:00:00",
        "Coin": "DEMOCOIN",
        "Type": "deposit",
        "Amount": "4",
        "Fee": "0",
        "Fee asset": "BGB",
    }]
    assert preview["file_sha256"] == expected_hash
    assert store.list_import_batches() == []


def test_bitget_time_header_uses_only_its_declared_utc_plus_8_timezone(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    importer = CsvRawImporter(store)
    batch = importer.import_text(
        "bitget",
        "synthetic.csv",
        "Coin,Type,Amount,Timestamp UTC+8 (Order)\n"
        "DEMOCOIN,deposit,1,2025-01-02 12:00:00\n",
    )

    event = RawNormalizer(store).normalize_batch(batch.batch_id)[0]

    assert event.event_time == datetime(2025, 1, 2, 4, 0, tzinfo=timezone.utc)


def test_bitget_explicit_datetime_offset_is_not_replaced_by_legacy_default(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    batch = CsvRawImporter(store).import_text(
        "bitget",
        "synthetic.csv",
        "Coin,Type,Amount,Date\n"
        "DEMOCOIN,deposit,1,2025-01-02T12:00:00+01:00\n",
    )

    event = RawNormalizer(store).normalize_batch(batch.batch_id)[0]

    assert event.event_time == datetime(2025, 1, 2, 11, 0, tzinfo=timezone.utc)
