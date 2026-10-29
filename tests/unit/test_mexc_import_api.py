import base64
from io import BytesIO
import hashlib
import json
import socket

from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


HEADERS = ["UID", "Creation Time(UTC+01:00)", "Crypto", "Transaction Type", "Direction", "Quantity"]
ROW = ["SYNTHETIC-ACCOUNT", "2031-07-09 12:00:00", "DEMOCOIN", "Airdrop", "Inflow", "2.5"]


def xlsx(headers=HEADERS, rows=None):
    book = Workbook()
    book.active.append(headers)
    for row in [ROW] if rows is None else rows:
        book.active.append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def payload(content, kind="spot_statement", **options):
    return {"source": "mexc", "filename": "synthetic.xlsx", "import_mode": "file",
            "content_base64": base64.b64encode(content).decode(),
            "mexc": {"account": "synthetic-spot", "export_kind": kind, **options}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "configs"))

    def blocked(*args, **kwargs):
        raise AssertionError("Synthetische MEXC-Tests duerfen kein Netzwerk verwenden")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    with TestClient(create_app(store)) as client:
        yield client, store


def test_native_assistant_trace_original_and_review_gate(api):
    client, store = api
    original = xlsx()
    request = payload(original)
    pre = client.post("/api/v1/import/assistant/preview", json=request).json()["data"]
    assert pre["can_execute"] and pre["preview"]["mexc"]["bookable_rows"] == 1
    assert store.list_import_batches() == []
    assert not (store.path.parent / "mexc_originals").exists()
    result = client.post("/api/v1/import/assistant/execute", json=request).json()
    assert result["status"] == "ok"
    batch = result["data"]["batch"]["batch_id"]
    trace = client.get(f"/api/v1/import/batches/{batch}/trace.json").json()
    assert len(trace["canonical_events"]) == 1
    event = trace["canonical_events"][0]
    assert event["event_type"] == "unknown" and event["quantity"] == "2.500000000000000000"
    assert event["event_time"] == "2031-07-09T11:00:00Z"
    assert trace["raw_objects"][0]["row_number"] == 2
    meta = json.loads(json.loads(trace["raw_objects"][0]["payload_json"])["_mexc"])
    assert meta["file_sha256"] == "sha256:" + hashlib.sha256(original).hexdigest()
    assert meta["sheet_name"] == "Sheet"
    assert len(trace["mexc_evidence"]) == 1
    assert client.get(f"/api/v1/import/batches/{batch}/original").content == original
    gate = ReviewService(store).gate()
    assert not gate.allow_export
    assert any(i.code == "mexc_classification_required" for i in gate.issues)
    with store.connect() as con:
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 0
    assert client.post("/api/v1/import/assistant/execute", json=request).json()["status"] == "error"
    assert len(store.list_import_batches()) == 1


def test_execute_revalidates_overlap_and_links_both_originals(api):
    client, store = api
    first = payload(xlsx())
    headers = ["UID", "Time", "Crypto", "Type", "Quantity", "Status", "Remark"]
    second = payload(xlsx(headers, [["SYNTHETIC-ACCOUNT", ROW[1], ROW[2], "Airdrop", "2.5", "", ""]]),
                     "funding_other", timezone="UTC+01:00")
    assert client.post("/api/v1/import/assistant/preview", json=second).json()["data"]["can_execute"]
    root = client.post("/api/v1/import/assistant/execute", json=first).json()["data"]["batch"]["batch_id"]
    stale = client.post("/api/v1/import/assistant/execute", json=second).json()
    assert stale["status"] == "error" and len(store.list_import_batches()) == 1
    raw_id = store.list_raw_objects(root)[0].raw_object_id
    current = client.post("/api/v1/import/assistant/preview", json=second).json()["data"]["preview"]["mexc"]["rows"][0]
    second["mexc"]["decisions"] = {"2": {"action": "link_existing", "target_raw_object_id": raw_id,
        "reason": "Synthetisches Belegpaar anhand Originaldaten geprueft.", "input_digest": current["input_digest"]}}
    linked = client.post("/api/v1/import/assistant/execute", json=second).json()
    assert linked["status"] == "ok"
    other = linked["data"]["batch"]["batch_id"]
    assert len(store.list_canonical_events()) == 1
    for batch in (root, other):
        evidence = client.get(f"/api/v1/import/batches/{batch}/trace.json").json()["mexc_evidence"]
        assert len(evidence) == 2
    assert other not in store.unmapped_raw_object_counts()


@pytest.mark.parametrize("endpoint", ["/api/v1/import/file/raw", "/api/v1/import/assistant/execute"])
def test_raw_routes_cannot_bypass_missing_assignment(api, endpoint):
    client, store = api
    request = payload(xlsx())
    del request["mexc"]
    response = client.post(endpoint, json=request)
    assert response.status_code == 200 and response.json()["status"] == "error"
    assert store.list_import_batches() == []


@pytest.mark.parametrize("data", [b"broken-xlsx", b"", b"\xff\xff"])
def test_bad_native_files_have_safe_errors(api, data):
    client, store = api
    response = client.post("/api/v1/import/assistant/preview", json=payload(data))
    assert response.status_code == 200 and response.json()["status"] == "error"
    assert store.list_import_batches() == []


def test_native_decimal_and_running_balance_do_not_round_at_28_digits(api):
    from decimal import Decimal
    client, store = api
    value = "1234567890123456789.123456789012345678"
    request = payload(xlsx(rows=[[*ROW[:4], "Outflow", value]]))
    result = client.post("/api/v1/import/assistant/execute", json=request).json()
    assert result["status"] == "ok"
    expected = Decimal("-" + value)
    event = store.list_canonical_events()[0]
    assert event.quantity == expected
    entries = BalanceLedgerBuilder(store).rebuild()
    assert len(entries) == 1 and entries[0].delta_quantity == expected
    assert entries[0].balance_quantity == expected


def test_snapshot_without_events_still_links_its_review_to_the_import_source(api):
    from steuerreport_v2.domain.workspace import WorkspaceService
    client, store = api
    content = xlsx(["UID", "Date(UTC+8)", "Account", "Crypto", "Total", "USDT Valuation"],
        [["SYNTHETIC-ACCOUNT", "20310709", "Spot", "DEMOCOIN", "2.5", "123"]])
    result = client.post("/api/v1/import/assistant/execute", json=payload(content, "asset_snapshot")).json()
    assert result["status"] == "ok" and store.list_canonical_events() == []
    workspace = WorkspaceService(store)
    scopes = workspace.source_scopes()
    tasks = ReviewService(store).tasks().tasks
    resolved = workspace._review_items(tasks, scopes)
    task = next(item for item in resolved if item.task.decision_status == "mexc_snapshot_reconciliation_required")
    assert task.context_status == "matched" and task.source_ref


@pytest.mark.parametrize("status", ["Failed", "Pending", "Completed"])
def test_funding_status_is_preserved_without_claiming_a_completed_booking(api, status):
    client, store = api
    content = xlsx(["UID", "Time", "Crypto", "Type", "Quantity", "Status", "Remark"],
        [["SYNTHETIC-ACCOUNT", ROW[1], ROW[2], "Airdrop", "2.5", status, "synthetic"]])
    request = payload(content, "funding_other", timezone="UTC+01:00")
    preview = client.post("/api/v1/import/assistant/preview", json=request).json()["data"]
    assert preview["can_execute"] and preview["preview"]["mexc"]["bookable_rows"] == 0
    result = client.post("/api/v1/import/assistant/execute", json=request).json()
    assert result["status"] == "ok" and store.list_canonical_events() == []
    raw, = store.list_raw_objects(result["data"]["batch"]["batch_id"])
    assert json.loads(raw.payload_json)["Status"] == status
    assert BalanceLedgerBuilder(store).positions() == []
    assert not ReviewService(store).gate().allow_export
