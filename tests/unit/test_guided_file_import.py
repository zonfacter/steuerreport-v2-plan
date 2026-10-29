import base64
import csv
import hashlib
from html.parser import HTMLParser
from io import BytesIO, StringIO
import os
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfReader
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.connections import ConnectionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV


CSV_BYTES = b"\xef\xbb\xbftime;asset;amount;type;account\r\n2025-02-01T10:00:00Z;EUR;10;deposit;test-account\r\n"


def payload(content=CSV_BYTES, filename="export.csv", sheet=None):
    return {"source": "manual-csv", "import_mode": "file", "filename": filename,
            "content_base64": base64.b64encode(content).decode(), "sheet_name": sheet}


def create_same_name_binance_connections(store, tmp_path, monkeypatch):
    key = tmp_path / "synthetic-vault.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    service = ConnectionService(store)
    return tuple(service.create(ConnectionCreate(
        provider="binance", label="Gleiches Spotkonto", account="Spot",
    )) for _ in range(2))


def test_csv_upload_preserves_original_byte_hash_and_preview_is_readonly(tmp_path):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    client = TestClient(create_app(store))
    request = payload()
    response = client.post("/api/v1/import/assistant/preview", json=request)
    assert response.status_code == 200
    preview = response.json()["data"]
    assert preview["can_execute"]
    digest = "sha256:" + hashlib.sha256(CSV_BYTES).hexdigest()
    assert preview["preview"]["file_sha256"] == digest
    assert preview["preview"]["import_fingerprint"] == digest
    assert preview["preview"]["row_count"] == 1
    assert preview["preview"]["sample_rows"][0]["asset"] == "EUR"
    assert store.list_import_batches() == []
    result = client.post("/api/v1/import/assistant/execute", json=request).json()
    assert result["status"] == "ok"
    assert result["data"]["batch"]["file_hash"] == digest
    assert result["data"]["run"]["normalized_events"] == 1
    duplicate = client.post("/api/v1/import/assistant/preview", json=payload(filename="renamed.csv")).json()["data"]
    assert not duplicate["can_execute"]
    assert duplicate["preview"]["duplicate_batch_id"] == result["data"]["batch"]["batch_id"]
    repeated = client.post("/api/v1/import/assistant/execute", json=request).json()
    assert repeated["status"] == "error"
    assert len(store.list_import_batches()) == 1
    trace = client.get("/api/v1/import/batches/" + result["data"]["batch"]["batch_id"] + "/trace.json").json()
    assert trace["batch"]["file_hash"] == digest
    assert len(trace["raw_objects"]) == len(trace["canonical_events"]) == 1


def test_excel_hash_is_original_file_but_import_identity_includes_sheet(tmp_path):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    client = TestClient(create_app(store))
    book = Workbook()
    for index, name in enumerate(("History", "Funding")):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = name
        sheet.append(["time", "asset", "amount", "type", "account"])
        sheet.append(["2025-02-01T10:00:00Z", "EUR", index + 1, "deposit", "test-account"])
    buffer = BytesIO()
    book.save(buffer)
    content = buffer.getvalue()
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    for name in ("History", "Funding"):
        request = payload(content, "history.xlsx", name)
        preview = client.post("/api/v1/import/assistant/preview", json=request).json()["data"]
        assert preview["can_execute"]
        assert preview["preview"]["file_sha256"] == digest
        assert preview["preview"]["import_fingerprint"] == digest + "#sheet=" + name
        assert preview["preview"]["sheet_names"] == ["History", "Funding"]
        result = client.post("/api/v1/import/assistant/execute", json=request).json()
        assert result["status"] == "ok"
        assert result["data"]["batch"]["file_hash"] == digest + "#sheet=" + name
        assert not client.post("/api/v1/import/assistant/preview", json=request).json()["data"]["can_execute"]
    assert len(store.list_import_batches()) == 2


@pytest.mark.parametrize("content,filename,status", [(b"", "empty.csv", "warning"), (b"not an excel file", "broken.xlsx", "error"), (b"\xff\xfe\xff", "bad-encoding.csv", "error")])
def test_unreadable_upload_has_a_safe_error_and_does_not_import(tmp_path, content, filename, status):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    client = TestClient(create_app(store))
    response = client.post("/api/v1/import/assistant/preview", json=payload(content, filename))
    assert response.status_code == 200
    assert response.json()["status"] == status
    if status == "error":
        assert response.json()["errors"][0]["code"] == "import_assistant_invalid_file"
    else:
        assert not response.json()["data"]["can_execute"]
    assert store.list_import_batches() == []


def test_missing_columns_blocks_execution_and_does_not_import(tmp_path):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    client = TestClient(create_app(store))
    request = payload(b"time,asset\n2025-02-01T10:00:00Z,EUR\n")
    preview = client.post("/api/v1/import/assistant/preview", json=request).json()["data"]
    assert not preview["can_execute"]
    assert "quantity" in preview["preview"]["missing_required_groups"]
    assert client.post("/api/v1/import/assistant/execute", json=request).json()["status"] == "error"
    assert store.list_import_batches() == []


def test_binance_file_binding_is_explicit_stable_and_scoped_per_connection(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    first, second = create_same_name_binance_connections(store, tmp_path, monkeypatch)
    assert first.provider == second.provider == "binance"
    assert first.label == second.label and first.id != second.id
    client = TestClient(create_app(store))
    content = (
        b"utc time,coin,change,operation,quote_asset,quote_quantity,id\r\n"
        b"2025-02-01T10:00:00Z,BTC,0.1,buy,EUR,100,fill-42\r\n"
    )
    digest = "sha256:" + hashlib.sha256(content).hexdigest()

    unbound = client.post(
        "/api/v1/import/assistant/preview",
        json=payload(content, "spot.csv") | {"source": "binance"},
    ).json()["data"]
    assert not unbound["can_execute"]
    assert "ausdrueckliche Bindung" in unbound["blocked_reason"]
    assert store.list_import_batches() == []

    def request(connection_id):
        return payload(content, "spot.csv") | {
            "source": "binance", "connection_id": str(connection_id),
        }

    for connection in (first, second):
        preview = client.post("/api/v1/import/assistant/preview", json=request(connection.id)).json()["data"]
        assert preview["can_execute"] is True
        assert preview["preview"]["connection_id"] == str(connection.id)
        assert preview["preview"]["file_sha256"] == digest
        assert preview["preview"]["sample_rows"] == [{
            "utc time": "2025-02-01T10:00:00Z", "coin": "BTC", "change": "0.1",
            "operation": "buy", "quote_asset": "EUR", "quote_quantity": "100", "id": "fill-42",
        }]
        imported = client.post("/api/v1/import/assistant/execute", json=request(connection.id)).json()["data"]
        assert imported["batch"]["connection_id"] == str(connection.id)
        assert imported["batch"]["file_hash"] == digest

    repeated = client.post("/api/v1/import/assistant/preview", json=request(first.id)).json()["data"]
    assert not repeated["can_execute"]
    assert repeated["preview"]["duplicate_batch_connection_id"] == str(first.id)
    batches = store.list_import_batches()
    batches_by_connection = {str(batch.connection_id): batch for batch in batches}
    assert set(batches_by_connection) == {str(first.id), str(second.id)}
    raw_rows = [
        store.list_raw_objects(batches_by_connection[str(connection.id)].batch_id, limit=None)[0].payload_json
        for connection in (first, second)
    ]
    assert raw_rows[0] == raw_rows[1]
    assert all("connection_id" not in row for row in raw_rows)
    assert all(row == '{"change": "0.1", "coin": "BTC", "id": "fill-42", "operation": "buy", "quote_asset": "EUR", "quote_quantity": "100", "utc time": "2025-02-01T10:00:00Z"}' for row in raw_rows)
    events = store.list_canonical_events()
    assert {event.account for event in events} == {f"connection:{first.id}", f"connection:{second.id}"}


def test_binance_binding_rejects_wrong_provider_and_preserves_unbound_legacy_duplicate(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    key = tmp_path / "synthetic-vault.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    wrong_provider = ConnectionService(store).create(ConnectionCreate(
        provider="bitget", label="Gleiches Spotkonto", account="Spot",
    ))
    client = TestClient(create_app(store))
    content = b"utc time,coin,change,operation\n2025-02-01T10:00:00Z,BTC,0.1,buy\n"
    invalid = client.post(
        "/api/v1/import/assistant/preview",
        json=payload(content) | {"source": "binance", "connection_id": str(wrong_provider.id)},
    ).json()
    assert invalid["status"] == "error"
    assert invalid["errors"][0]["code"] == "connection_provider_mismatch"
    assert store.list_import_batches() == []

    from steuerreport_v2.importers.file_raw_importer import FileRawImporter
    from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
    legacy = FileRawImporter(CsvRawImporter(store)).import_base64(
        "binance", "old.csv", base64.b64encode(content).decode(),
    )
    valid_provider = ConnectionService(store).create(ConnectionCreate(
        provider="binance", label="Binance-Verbindung", account="Spot",
    ))
    blocked = client.post(
        "/api/v1/import/assistant/preview",
        json=payload(content) | {"source": "binance", "connection_id": str(valid_provider.id)},
    ).json()
    assert blocked["data"]["preview"]["duplicate_batch_id"] == legacy.batch_id
    assert blocked["data"]["preview"]["duplicate_batch_connection_id"] is None
    assert not blocked["data"]["can_execute"]


def test_selected_connection_overrides_file_account_label_without_changing_raw_data(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    connection, _ = create_same_name_binance_connections(store, tmp_path, monkeypatch)
    client = TestClient(create_app(store))
    content = (
        b"time,asset,amount,type,account\n"
        b"2025-02-01T10:00:00Z,BTC,0.1,buy,untrusted-export-label\n"
    )
    request = payload(content) | {"source": "binance", "connection_id": str(connection.id)}

    result = client.post("/api/v1/import/assistant/execute", json=request).json()
    assert result["status"] == "ok"
    batch = store.get_import_batch(result["data"]["batch"]["batch_id"])
    assert batch is not None and str(batch.connection_id) == str(connection.id)
    raw = store.list_raw_objects(batch.batch_id, limit=None)[0]
    assert "untrusted-export-label" in raw.payload_json
    event = store.list_canonical_events(batch_id=batch.batch_id)[0]
    assert event.account == f"connection:{connection.id}"


@pytest.mark.parametrize("route", ["/api/v1/import/csv/raw", "/api/v1/import/file/raw"])
def test_legacy_raw_upload_routes_require_and_apply_binance_binding(route, tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "guided.duckdb")
    connection, _ = create_same_name_binance_connections(store, tmp_path, monkeypatch)
    client = TestClient(create_app(store))
    content = b"time,asset,amount,type\n2025-02-01T10:00:00Z,BTC,0.1,buy\n"

    def body(connection_id=None):
        value = {"source": "binance", "filename": "spot.csv"}
        if route.endswith("csv/raw"):
            value["content"] = content.decode()
        else:
            value["content_base64"] = base64.b64encode(content).decode()
        if connection_id is not None:
            value["connection_id"] = str(connection_id)
        return value

    blocked = client.post(route, json=body()).json()
    assert blocked["status"] == "error"
    assert blocked["errors"][0]["code"] == "connection_binding_required"
    assert store.list_import_batches() == []

    accepted = client.post(route, json=body(connection.id)).json()
    assert accepted["status"] == "ok"
    batch = store.get_import_batch(accepted["data"]["batch_id"])
    assert batch is not None and str(batch.connection_id) == str(connection.id)
    from steuerreport_v2.importers.raw_normalizer import RawNormalizer

    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    assert len(events) == 1
    assert events[0].account == f"connection:{connection.id}"


def test_public_guide_and_empty_template_are_complete():
    root = Path(__file__).resolve().parents[2]
    public = root / "frontend/public"

    class Links(HTMLParser):
        ids = set()
        anchors = []

        def handle_starttag(self, tag, attrs):
            data = dict(attrs)
            if "id" in data:
                self.ids.add(data["id"])
            if tag == "a" and data.get("href", "").startswith("#"):
                self.anchors.append(data["href"][1:])

    html = (public / "benutzerleitfaden.html").read_text()
    document = Links()
    document.feed(html)
    assert len(document.anchors) >= 10
    assert all(anchor in document.ids for anchor in document.anchors)
    assert "25 MB" in html and "100 MB" in html
    assert "nicht automatisch die vollstaendige Handelsgeschichte" in html
    pdf = PdfReader(public / "benutzerleitfaden.pdf")
    assert 2 <= len(pdf.pages) <= 100
    assert "Dateien importieren" in "\n".join(page.extract_text() for page in pdf.pages)
    template = csv.DictReader(StringIO((public / "import-vorlage.csv").read_text()))
    assert {"time", "asset", "amount", "type"} <= set(template.fieldnames)
    assert list(template) == []
    source = (root / "frontend/src/main.tsx").read_text()
    navigation = source.split("const navItems:", 1)[1].split("const API_BASE", 1)[0]
    assert "V1/V2" not in navigation and 'id: "parity"' not in navigation
    assert 'label: "Einrichtung"' in navigation
    assert 'label: "V1 Cache"' not in source
    wizard = (root / "frontend/src/FileImportWizard.tsx").read_text()
    offered_sources = wizard.split("const SOURCES =", 1)[1].split(";", 1)[0]
    assert "blockpit" not in offered_sources
