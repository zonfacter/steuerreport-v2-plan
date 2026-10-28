"""Paket D: generierte Konten, echte Services, nur HTTP-Gegenstelle simuliert."""
from datetime import datetime, timezone
from decimal import Decimal
import os
import shutil
import time

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.connections import ConnectionAction, ConnectionCreate
from steuerreport_v2.contracts.admin import ApiKeyWrite
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import external_http
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.history_cex import CexHistoryCollector
from steuerreport_v2.domain.history_types import HistoryOptions, HistoryTarget
from steuerreport_v2.domain.request_limits import RequestLimiter
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV, is_encrypted_envelope
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.workspace import WorkspaceService, source_ref
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.source_history_importer import import_records, prepare_records


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    key = tmp_path / "generated-vault.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    store = DuckDbStore(tmp_path / "accounts.duckdb")
    service = ConnectionService(store)
    rows = [service.create(ConnectionCreate(
        provider="binance", label="Gleicher Anzeigename", account="same-label",
        budget_group="budget:shared", api_key=SecretStr(f"synthetic-key-{index}"),
        api_secret=SecretStr(f"synthetic-secret-{index}"),
    )) for index in (1, 2)]
    return store, service, rows


@pytest.fixture
def provider(tmp_path, monkeypatch):
    elapsed = [0.0]
    wall, mono = time.time(), time.monotonic()
    clock = lambda: wall + elapsed[0]
    monotonic = lambda: mono + elapsed[0]
    def sleep(seconds):
        elapsed[0] += seconds
    limiter = RequestLimiter(state_root=tmp_path / "request-budget", clock=clock,
                             monotonic=monotonic, sleep=sleep, random=lambda: 0.5)
    calls = []
    retry = [True]
    at = datetime(2025, 6, 1, 12, tzinfo=timezone.utc)
    def respond(request):
        path, key = request.url.path, request.headers.get("X-MBX-APIKEY", "public")
        calls.append((path, key, elapsed[0]))
        if path == "/api/v3/account":
            if key == "synthetic-key-1" and retry[0]:
                retry[0] = False
                return httpx.Response(429, headers={"Retry-After": "1"}, json={"code": -1003})
            value = "1" if key.endswith("1") else "2"
            return httpx.Response(200, json={"balances": [{"asset": "EUR", "free": value, "locked": "0"}]})
        if "flexible/position" in path:
            rows = [{"asset": "EUR", "totalAmount": "0"}] * 100 if request.url.params.get("current") == "1" else []
            return httpx.Response(200, json={"rows": rows})
        if "locked/position" in path:
            return httpx.Response(200, json={"rows": []})
        if path == "/api/v3/myTrades":
            return httpx.Response(200, json=[{
                "symbol": "BTCEUR", "id": 7, "orderId": 8,
                "time": int(at.timestamp() * 1000), "isBuyer": True,
                "qty": "1", "quoteQty": "100", "commission": "0.25", "commissionAsset": "EUR",
            }])
        if path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json={"symbols": [{"symbol": "BTCEUR", "baseAsset": "BTC", "quoteAsset": "EUR"}]})
        if path == "/tokens/v2/search":
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected fake-provider path: {path}")
    factory = external_http.managed_client
    def client(**kwargs):
        return factory(transport=httpx.MockTransport(respond), limiter=limiter,
                       clock=clock, monotonic=monotonic, **kwargs)
    monkeypatch.setattr(external_http, "managed_client", client)
    return limiter, calls


def test_two_accounts_real_jobs_retry_pagination_and_shared_budget(accounts, provider, monkeypatch):
    store, service, rows = accounts
    limiter, calls = provider
    monkeypatch.setattr(ConnectionService, "_launch", lambda self, job_id: None)
    for connection in rows:
        job = service.start(connection.id, "sync", ConnectionAction(
            confirm_external_request=True, confirm_balance_snapshot=True))
        service._run(str(job.id))
    assert all(job.status == "succeeded" for job in service.jobs().jobs)
    assert [service.snapshots(row.id).snapshots[0].quantity for row in rows] == [Decimal("1"), Decimal("2")]
    assert service.snapshots(rows[0].id).snapshots[0].snapshot_id != service.snapshots(rows[1].id).snapshots[0].snapshot_id
    # First account: retry + account + two flexible pages + locked; second: four starts.
    assert len(calls) == 9
    assert [key for path, key, _ in calls if path == "/api/v3/account"] == ["synthetic-key-1", "synthetic-key-1", "synthetic-key-2"]
    assert calls[-1][2] >= 8
    groups = {group.group: group for group in limiter.status().groups}
    assert groups["ip:global"].requests_last_minute == 9
    assert groups["provider:binance"].requests_last_minute == 9
    assert groups["budget:shared"].requests_last_minute == 9
    with store.connect() as con:
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == 0
    secrets = [s for s in store.list_admin_settings() if s.key.startswith("secret.cex.connection.")]
    assert len(secrets) == 4 and all(is_encrypted_envelope(s.value_json) for s in secrets)
    client = TestClient(create_app(store))
    for path in ["/api/v1/admin/connections", "/api/v1/admin/connections/jobs"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "synthetic-key-" not in response.text and "synthetic-secret-" not in response.text
    before = len(calls)
    job = service.start(rows[1].id, "test", ConnectionAction(confirm_external_request=True))
    service._run(str(job.id))
    assert len(calls) == before + 1
    assert service.snapshots(rows[1].id).snapshots[0].quantity == Decimal("2")


def test_repeat_csv_api_import_and_copy_preserve_accounts_raw_and_review(accounts, provider, tmp_path):
    store, service, connections = accounts
    limiter, calls = provider
    targets = [HistoryTarget(source_ref("connection:" + str(c.id)), c.label, "binance",
        "connection:" + str(c.id), connection_id=str(c.id), budget_groups=("budget:shared",)) for c in connections]
    options = HistoryOptions(datetime(2025, 6, 1, tzinfo=timezone.utc), datetime(2025, 6, 2, tzinfo=timezone.utc), ("BTCEUR",))
    for target in targets:
        with external_http.outbound_scope(provider="binance", connection_id=target.connection_id, groups=target.budget_groups):
            page = CexHistoryCollector(store, target, options).fetch_page({}, lambda: None)
        assert not page.complete_history_proven
        assert len(page.records) == 1
        assert page.records[0].raw["payload"]["commission"] == "0.25"
        accepted, duplicates = prepare_records(store, target, page.records)
        assert len(accepted) == 1 and duplicates == 0
        for batch in import_records(store, target, accepted, "fixture-first"):
            PipelineService(store).rebuild_after_import(batch.batch_id)
            # Same completion transition as HistoryPreview.prepare, not an approval.
            with store.connect() as con:
                con.execute("update raw_import_batches set status='normalized' where batch_id=?", [batch.batch_id])
        accepted, duplicates = prepare_records(store, target, page.records)
        assert accepted == [] and duplicates == 1
        assert import_records(store, target, accepted, "fixture-repeat") == []
    events = store.list_canonical_events()
    assert len(events) == 2
    assert {event.account for event in events} == {t.account for t in targets}
    assert len({event.source_ref for event in events}) == 2
    assert all(event.fee_asset == "EUR" and event.fee_quantity == Decimal("0.25") for event in events)
    csv = "time,asset,amount,type,quote_asset,quote_quantity,account\n2025-06-01T12:00:00Z,SOL,2,buy,EUR,20,csv-own\n2025-06-02T12:00:00Z,SOL,-1,sell,EUR,15,csv-own\n"
    importer = CsvRawImporter(store)
    batch = importer.import_text("manual-csv", "fixture.csv", csv)
    RawNormalizer(store).normalize_batch(batch.batch_id)
    first = TaxService(store).rebuild_fifo()
    repeated = importer.import_text("manual-csv", "renamed.csv", csv)
    RawNormalizer(store).normalize_batch(repeated.batch_id)
    second = TaxService(store).rebuild_fifo()
    assert repeated.batch_id == batch.batch_id
    assert len(store.list_canonical_events()) == 4
    assert sum(line.gain_loss_eur for line in first.tax_lines) == sum(line.gain_loss_eur for line in second.tax_lines)
    assert sum(lot.quantity_remaining for lot in first.lots) == sum(lot.quantity_remaining for lot in second.lots)
    event = next(event for event in events if event.account == targets[0].account)
    decision = store.add_review_decision(ReviewDecisionCreate(
        decision_type="evidence_note", scope="event:" + event.event_id, title="Kontenbindung",
        rationale="Generierter Pruefbeleg, keine Steuerfreigabe", evidence_ref="raw:" + event.raw_object_id,
        affected_ids=[event.event_id], payload={"source_ref": targets[0].source_ref}))
    original = [(r.raw_object_id, r.batch_id, r.payload_json) for r in store.list_raw_objects(limit=None)]
    before_calls = len(calls)
    copied_path = tmp_path / "copy.duckdb"
    shutil.copy2(store.path, copied_path)
    copied = DuckDbStore(copied_path)
    assert [(r.raw_object_id, r.batch_id, r.payload_json) for r in copied.list_raw_objects(limit=None)] == original
    assert copied.list_review_decisions()[0].decision_id == decision.decision_id
    assert copied.list_review_decisions()[0].payload["source_ref"] == targets[0].source_ref
    assert {e.account for e in copied.list_canonical_events()} == {t.account for t in targets} | {"csv-own"}
    assert ConnectionService(copied).credentials(connections[0].id, "binance")[0] == "synthetic-key-1"
    refs = {scope.item.ref for scope in WorkspaceService(copied).source_scopes()}
    assert all(t.source_ref in refs for t in targets)
    assert len(calls) == before_calls
    assert {g.group: g for g in limiter.status().groups}["provider:binance"].requests_last_minute == 4


def test_default_read_queries_do_not_fetch_but_jupiter_get_really_does(accounts, provider, monkeypatch):
    store, service, connections = accounts
    limiter, calls = provider
    client = TestClient(create_app(store))
    for path in ["/api/v1/admin/connections", "/api/v1/admin/connections/jobs",
                 "/api/v1/workspace/sources",
                 f"/api/v1/workspace/sources/{source_ref('connection:' + str(connections[0].id))}/history"]:
        assert client.get(path).status_code == 200
    assert client.post("/api/v1/activity/query", json={}).status_code == 200
    assert calls == []
    AdminService(store).save_jupiter_api_key(ApiKeyWrite(api_key="synthetic-jupiter-key"))
    monkeypatch.setattr("steuerreport_v2.domain.jupiter.managed_client", external_http.managed_client)
    response = client.get("/api/v1/sources/jupiter/tokens/search", params={"query": "BTC"})
    assert response.status_code == 200 and response.json()["data"]["configured"] is True
    assert "synthetic-jupiter-key" not in response.text
    assert len(calls) == 1 and calls[0][0] == "/tokens/v2/search"
    assert {g.group: g for g in limiter.status().groups}["provider:jupiter"].requests_last_minute == 1
