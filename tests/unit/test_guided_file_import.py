import base64
import csv
import hashlib
from html.parser import HTMLParser
from io import BytesIO, StringIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfReader
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore


CSV_BYTES = b"\xef\xbb\xbftime;asset;amount;type;account\r\n2025-02-01T10:00:00Z;EUR;10;deposit;test-account\r\n"


def payload(content=CSV_BYTES, filename="export.csv", sheet=None):
    return {"source": "manual-csv", "import_mode": "file", "filename": filename,
            "content_base64": base64.b64encode(content).decode(), "sheet_name": sheet}


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
