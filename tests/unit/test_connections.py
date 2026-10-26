from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import multiprocessing
import os
import sys
import threading
import time
from types import ModuleType
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from steuerreport_v2.api.connections import build_connections_router
from steuerreport_v2.contracts.admin import AdminSettingWrite, ApiKeyWrite, CexCredentialWrite
from steuerreport_v2.contracts.connections import ConnectionAction, ConnectionCreate, ConnectionUpdate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain.connections import (
    ConnectionError, ConnectionService, JOB_PREFIX, MAX_RETAINED, _JobCancellation,
)
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV, is_encrypted_envelope


@pytest.fixture
def store(tmp_path, monkeypatch):
    key = tmp_path / "vault.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    return DuckDbStore(tmp_path / "isolated.duckdb")


@pytest.fixture
def service(store):
    return ConnectionService(store)


@pytest.fixture
def scheduler(monkeypatch):
    module = ModuleType("steuerreport_v2.domain.external_http")
    calls = []

    @contextmanager
    def outbound_scope(**kwargs):
        calls.append(kwargs)
        yield

    module.outbound_scope = outbound_scope
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


@pytest.fixture
def queued(monkeypatch):
    jobs = []
    monkeypatch.setattr(ConnectionService, "_launch", lambda _self, job_id: jobs.append(job_id))
    return jobs


def create(service, *, label="Testkonto", provider="binance", budget="ip:global", marker="one"):
    return service.create(ConnectionCreate(
        provider=provider, label=label, account=f"synthetic-{marker}", subaccount="synthetic-sub",
        budget_group=budget, api_key=SecretStr(f"mock-key-{marker}"),
        api_secret=SecretStr(f"mock-secret-{marker}"),
        passphrase=SecretStr(f"mock-pass-{marker}") if provider == "bitget" else None,
    ))


def action(sync=False, seconds=120):
    return ConnectionAction(confirm_external_request=True,
                            confirm_balance_snapshot=sync, deadline_seconds=seconds)


def snapshot(provider, fetched_at, marker="one"):
    return PortfolioLiveBalanceSnapshot(
        snapshot_id=f"synthetic-{marker}", connector_id=provider, asset="EUR",
        quantity=Decimal("1.123456789123456789"), source="synthetic", fetched_at=fetched_at,
    )


def test_two_accounts_encrypted_persist_after_new_store_and_no_activation(service, store):
    first = create(service, marker="one")
    second = create(service, marker="two")
    assert first.id != second.id
    assert first.credentials.status == "configured"
    assert first.credentials.encrypted
    assert first.tax_source_activated is False
    restarted = ConnectionService(DuckDbStore(store.path))
    assert len(restarted.list().connections) == 2
    assert restarted.credentials(first.id, "binance") == ("mock-key-one", "mock-secret-one", "")
    assert restarted.credentials(second.id, "binance") == ("mock-key-two", "mock-secret-two", "")
    settings = store.list_admin_settings()
    secrets = [item for item in settings if item.key.startswith("secret.")]
    assert len(secrets) == 4
    assert all(is_encrypted_envelope(item.value_json) for item in secrets)
    assert "mock-key" not in json.dumps([item.model_dump(mode="json") for item in settings])
    assert "mock-secret" not in restarted.list().model_dump_json()
    with store.connect() as con:
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == 0
        assert con.execute("select count(*) from portfolio_live_balance_snapshots").fetchone()[0] == 0
        assert con.execute("select count(*) from review_decisions").fetchone()[0] == 0


def test_no_vault_blocks_new_and_legacy_and_generic_cex_writes(service, store, monkeypatch):
    monkeypatch.delenv(KEY_FILE_ENV)
    assert service.list().vault_ready is False
    with pytest.raises(ConnectionError, match="^secret_vault_key_required$"):
        create(service)
    with pytest.raises(RuntimeError, match="^secret_vault_key_required$"):
        AdminService(store).save_cex_credentials(CexCredentialWrite(
            connector_id="binance", api_key="mock-key", api_secret="mock-secret"))
    with pytest.raises(RuntimeError, match="^secret_vault_key_required$"):
        AdminService(store).upsert_setting(AdminSettingWrite(
            key="secret.cex.binance.api_key", value_json='"mock-key"'))
    assert store.list_admin_settings() == []


@pytest.mark.parametrize("key", ["secret.jupiter.api_key", "secret.helius.api_key", "SECRET.ALCHEMY.API_KEY", "secret.ai.external.api_key"])
def test_every_generic_secret_write_fails_closed_without_vault(store, monkeypatch, key):
    monkeypatch.delenv(KEY_FILE_ENV)
    with pytest.raises(RuntimeError, match="^secret_vault_key_required$"):
        AdminService(store).upsert_setting(AdminSettingWrite(key=key, value_json='"mock-sensitive-value"'))
    assert store.list_admin_settings() == []


def test_old_jupiter_secret_entrypoint_is_also_fail_closed(store, monkeypatch):
    admin = AdminService(store)
    monkeypatch.delenv(KEY_FILE_ENV)
    with pytest.raises(RuntimeError, match="^secret_vault_key_required$"):
        admin.save_jupiter_api_key(ApiKeyWrite(api_key="mock-sensitive-value"))
    assert store.list_admin_settings() == []


def test_generic_provider_secret_is_encrypted_and_redacted(store):
    saved = AdminService(store).upsert_setting(AdminSettingWrite(
        key="secret.helius.api_key", value_json='"mock-sensitive-value"'))
    assert saved.value_json == '"***"'
    assert is_encrypted_envelope(store.list_admin_settings()[0].value_json)
    assert "mock-sensitive-value" not in store.list_admin_settings()[0].value_json


def test_encryption_failure_leaves_no_partial_connection(service, store, monkeypatch):
    original = __import__("steuerreport_v2.domain.connections", fromlist=["encrypt_secret_setting"]).encrypt_secret_setting
    called = []

    def fail_second(key, value, vault):
        called.append(key)
        if len(called) == 2:
            raise RuntimeError("synthetic-encryption-failure")
        return original(key, value, vault)

    monkeypatch.setattr("steuerreport_v2.domain.connections.encrypt_secret_setting", fail_second)
    with pytest.raises(RuntimeError, match="synthetic-encryption-failure"):
        create(service)
    assert store.list_admin_settings() == []


def test_simultaneous_workers_cannot_both_claim_same_connection(service, store, scheduler, queued):
    connection = create(service)
    barrier = threading.Barrier(3)
    result = []

    def start():
        barrier.wait(5)
        try:
            ConnectionService(DuckDbStore(store.path)).start(connection.id, "test", action())
            result.append("accepted")
        except ConnectionError as exc:
            result.append(exc.code)

    workers = [threading.Thread(target=start) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait(5)
    for worker in workers:
        worker.join(10)
        assert not worker.is_alive()
    assert sorted(result) == ["accepted", "connection_job_already_active"]
    assert len(queued) == 1


def test_distinct_processes_share_job_claim_lock(service, store, scheduler, queued):
    connection = create(service)
    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    release = ctx.Event()
    result = ctx.Queue()

    def claim():
        start.wait(10)
        try:
            ConnectionService(DuckDbStore(store.path)).start(connection.id, "test", action())
            result.put("accepted")
        except ConnectionError as exc:
            result.put(exc.code)
        finally:
            # Besitzerprozess am Leben halten, bis auch der Konkurrent pruefte.
            release.wait(10)

    workers = [ctx.Process(target=claim) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        start.set()
        results = [result.get(timeout=15) for _ in workers]
        assert sorted(results) == ["accepted", "connection_job_already_active"]
    finally:
        release.set()
        for worker in workers:
            worker.join(15)
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            assert worker.exitcode == 0
        result.close()
        result.join_thread()


def test_blank_update_retains_secret_and_separate_delete_keeps_identity(service, store, monkeypatch):
    connection = create(service, provider="bitget")
    original = {row.key: row.value_json for row in store.list_admin_settings() if row.key.startswith("secret.")}
    changed = service.update(connection.id, ConnectionUpdate(
        label="Neuer Anzeigename", api_key=SecretStr(" "), api_secret=SecretStr("")))
    assert changed.id == connection.id
    assert changed.label == "Neuer Anzeigename"
    assert {row.key: row.value_json for row in store.list_admin_settings() if row.key.startswith("secret.")} == original
    assert service.credentials(connection.id, "bitget")[2] == "mock-pass-one"
    monkeypatch.delenv(KEY_FILE_ENV)
    with pytest.raises(ConnectionError, match="secret_vault_key_required"):
        service.update(connection.id, ConnectionUpdate(label="Nicht speichern"))
    removed = service.delete_credentials(connection.id)
    assert removed.credentials.status == "missing"
    assert removed.id == connection.id
    assert len(service.list().connections) == 1


def test_legacy_stays_read_only_visible_and_original_plaintext_unchanged(service, store, monkeypatch):
    for field, value in (("api_key", "old-key"), ("api_secret", "old-secret")):
        store.upsert_admin_setting(AdminSettingWrite(
            key=f"secret.cex.binance.{field}", value_json=json.dumps(value)))
    before = store.list_admin_settings()
    monkeypatch.delenv(KEY_FILE_ENV)
    legacy = service.list().legacy_connections
    assert len(legacy) == 1
    assert legacy[0].id == "legacy:binance"
    assert legacy[0].read_only and not legacy[0].credentials.encrypted
    assert legacy[0].credentials.status == "configured"
    assert CexBalanceService(store)._credentials("binance") == ("old-key", "old-secret", "")
    assert service.list().connections == []
    assert store.list_admin_settings() == before
    with pytest.raises(ConnectionError, match="connection_id_invalid"):
        service.update("legacy:binance", ConnectionUpdate(label="Unzulaessig"))


def test_legacy_save_is_atomic_encrypted_and_blank_keeps_values(store, monkeypatch):
    class Diagnostics:
        diagnostics = [type("Diagnostic", (), {
            "connector_id": "binance", "credential_status": "configured",
            "status": "configured", "credential_issue": None,
        })()]

    monkeypatch.setattr("steuerreport_v2.domain.admin.SourceService.connector_diagnostics", lambda _self: Diagnostics())
    admin = AdminService(store)
    admin.save_cex_credentials(CexCredentialWrite(
        connector_id="binance", api_key="mock-key", api_secret="mock-secret"))
    admin.save_cex_credentials(CexCredentialWrite(connector_id="binance", api_key="", api_secret=""))
    assert CexBalanceService(store)._credentials("binance") == ("mock-key", "mock-secret", "")
    assert all(is_encrypted_envelope(row.value_json) for row in store.list_admin_settings())


def test_wrong_vault_and_corrupt_envelope_never_fall_back_to_legacy(service, store, monkeypatch, tmp_path):
    connection = create(service)
    wrong = tmp_path / "wrong.key"
    wrong.write_bytes(os.urandom(32))
    monkeypatch.setenv(KEY_FILE_ENV, str(wrong))
    assert service.list().connections[0].credentials.status == "invalid"
    with pytest.raises(ConnectionError, match="connection_credentials_unavailable"):
        service.credentials(connection.id, "binance")
    with pytest.raises(ConnectionError, match="connection_provider_mismatch"):
        service.credentials(connection.id, "pionex")
    with pytest.raises(ConnectionError, match="connection_not_found"):
        service.credentials(uuid4(), "binance")
    with pytest.raises(ConnectionError, match="connection_credentials_invalid"):
        store.upsert_admin_setting(AdminSettingWrite(
            key=f"secret.cex.connection.{connection.id}.api_key", value_json='"plain-text-disallowed"'))
        service.credentials(connection.id, "binance")


@pytest.mark.parametrize("key", ["connection.record.any", "connection.job.any", "connection.snapshot.any", "secret.cex.connection.any.api_key"])
def test_generic_admin_cannot_bypass_connection_namespace(store, key):
    with pytest.raises(ValueError, match="connection_settings_use_connections_api"):
        AdminService(store).upsert_setting(AdminSettingWrite(key=key, value_json='"synthetic"'))
    with pytest.raises(ValueError, match="connection_settings_use_connections_api"):
        AdminService(store).delete_setting(key)


def test_jobs_share_scope_and_separate_snapshots_without_global_overwrite(service, store, scheduler, queued, monkeypatch):
    one = create(service, budget="budget:shared", marker="one")
    two = create(service, budget="budget:shared", marker="two")
    fetched = []

    def fetch(self, provider, fetched_at):
        fetched.append((self.connection_id, self._credentials(provider)))
        return [snapshot(provider, fetched_at, self.connection_id)]

    monkeypatch.setattr(CexBalanceService, "fetch", fetch)
    first = service.start(one.id, "sync", action(True))
    second = ConnectionService(DuckDbStore(store.path)).start(two.id, "sync", action(True))
    service._run(str(first.id))
    service._run(str(second.id))
    assert len(scheduler) == 2
    assert all(call["provider"] == "binance" and call["groups"] == ["budget:shared", "ip:global"] for call in scheduler)
    assert {call["connection_id"] for call in scheduler} == {str(one.id), str(two.id)}
    assert all(isinstance(call["cancel"], threading.Event) for call in scheduler)
    assert all(call["deadline"] > time.time() for call in scheduler)
    assert [values[1][0] for values in fetched] == ["mock-key-one", "mock-key-two"]
    assert service.snapshots(one.id).snapshots[0].snapshot_id != service.snapshots(two.id).snapshots[0].snapshot_id
    assert service.snapshots(one.id).snapshots[0].quantity == Decimal("1.123456789123456789")
    assert all(job.status == "succeeded" for job in service.jobs().jobs)
    assert all(item.last_sync_at and not item.last_test_at for item in service.list().connections)
    with store.connect() as con:
        assert con.execute("select count(*) from portfolio_live_balance_snapshots").fetchone()[0] == 0


def test_connection_fetch_uses_own_credentials_and_namespaced_result(service, store, monkeypatch):
    one = create(service, marker="one")
    two = create(service, marker="two")
    observed = []

    def get(self, path, key, secret, params):
        observed.append((key, secret))
        return {"balances": [{"asset": "EUR", "free": "3", "locked": "0"}]} if path == "/api/v3/account" else {"rows": []}

    monkeypatch.setattr(CexBalanceService, "_binance_get", get)
    client = CexBalanceService(store)
    first = client.fetch("binance", datetime.now(timezone.utc), connection_id=str(one.id))
    second = client.fetch("binance", datetime.now(timezone.utc), connection_id=str(two.id))
    assert first[0].snapshot_id.startswith(f"connection:{one.id}:")
    assert second[0].snapshot_id.startswith(f"connection:{two.id}:")
    assert observed == [("mock-key-one", "mock-secret-one")] * 3 + [("mock-key-two", "mock-secret-two")] * 3


def test_explicit_test_is_not_sync_and_does_not_replace_prior_snapshot(service, scheduler, queued, monkeypatch):
    connection = create(service)
    monkeypatch.setattr(CexBalanceService, "fetch", lambda self, provider, at: [snapshot(provider, at)])
    sync = service.start(connection.id, "sync", action(True))
    service._run(str(sync.id))
    before = service.snapshots(connection.id)
    tested = []
    monkeypatch.setattr(CexBalanceService, "test_connection", lambda self, provider: tested.append(provider))
    test = service.start(connection.id, "test", action())
    service._run(str(test.id))
    assert tested == ["binance"]
    assert service.snapshots(connection.id) == before
    current = service.list().connections[0]
    assert current.last_test_at and current.last_sync_at


def test_delayed_old_job_cannot_overwrite_newer_result(service, store, scheduler, queued, monkeypatch):
    connection = create(service)
    old = service.start(connection.id, "sync", action(True))
    old_record = service._read()[f"{JOB_PREFIX}{old.id}"]
    old_record["deadline_at"] = "2000-01-01T00:00:00+00:00"
    old_record["_pid"] = 2147483647
    store.upsert_admin_setting(AdminSettingWrite(
        key=f"{JOB_PREFIX}{old.id}", value_json=json.dumps(old_record)))
    current = service.start(connection.id, "sync", action(True))
    monkeypatch.setattr(CexBalanceService, "fetch", lambda self, provider, at: [snapshot(provider, at, "newer")])
    service._run(str(current.id))
    connection_before = service.list().connections[0]
    snapshot_before = service.snapshots(connection.id)
    service._finish(str(old.id), "failed", error_code="cex_authentication_failed")
    assert service.list().connections[0] == connection_before
    assert service.snapshots(connection.id) == snapshot_before
    assert next(job for job in service.jobs().jobs if job.id == old.id).error_code == "connection_job_deadline_exceeded"


def test_worker_claim_is_not_replayed_after_completion(service, scheduler, queued, monkeypatch):
    connection = create(service)
    called = []
    monkeypatch.setattr(CexBalanceService, "test_connection", lambda *_args: called.append(True))
    job = service.start(connection.id, "test", action())
    service._run(str(job.id))
    service._run(str(job.id))
    assert called == [True]


def test_duplicate_jobs_and_credential_changes_blocked_while_active(service, store, scheduler, queued):
    connection = create(service)
    service.start(connection.id, "test", action())
    restarted = ConnectionService(DuckDbStore(store.path))
    with pytest.raises(ConnectionError, match="connection_job_already_active"):
        restarted.start(connection.id, "sync", action(True))
    with pytest.raises(ConnectionError, match="connection_job_already_active"):
        restarted.update(connection.id, ConnectionUpdate(label="Nicht waehrend Abruf"))
    with pytest.raises(ConnectionError, match="connection_job_already_active"):
        restarted.delete_credentials(connection.id)
    assert len(queued) == 1


def test_cancel_queued_job_avoids_all_provider_calls(service, scheduler, queued, monkeypatch):
    connection = create(service)
    job = service.start(connection.id, "test", action())
    monkeypatch.setattr(CexBalanceService, "test_connection", lambda *_args: pytest.fail("cancelled provider call"))
    cancelled = service.cancel(job.id)
    assert cancelled.cancel_requested
    service._run(str(job.id))
    assert service.jobs().jobs[0].status == "cancelled"
    assert scheduler == []


def test_cancel_during_request_discards_result_and_sees_other_store(service, store, scheduler, queued, monkeypatch):
    connection = create(service)
    job = service.start(connection.id, "sync", action(True))

    def fetch(self, provider, at):
        other = ConnectionService(DuckDbStore(store.path))
        other.cancel(job.id)
        assert scheduler[-1]["cancel"].is_set()
        assert scheduler[-1]["cancel"].wait(0)
        return [snapshot(provider, at)]

    monkeypatch.setattr(CexBalanceService, "fetch", fetch)
    service._run(str(job.id))
    assert service.jobs().jobs[0].status == "cancelled"
    assert service.snapshots(connection.id).snapshots == []
    assert service.list().connections[0].last_sync_at is None


def test_cancel_poll_is_memory_only_and_database_refresh_is_explicit(service, queued, monkeypatch):
    from steuerreport_v2.domain.connections import _JobCancellation
    connection = create(service)
    job = service.start(connection.id, "test", action())
    signal = _JobCancellation(service, str(job.id), time.time() + 60)
    calls = []
    def unavailable():
        calls.append(True)
        raise RuntimeError("synthetic DB unavailable")
    monkeypatch.setattr(service, "_read", unavailable)
    assert not signal.is_set() and calls == []
    assert signal.refresh() is True and calls == [True]
    assert signal.is_set() and calls == [True]


def test_job_limit_is_shared_across_services(service, store, scheduler, queued):
    connections = [create(service, marker=str(index)) for index in range(5)]
    for connection in connections[:4]:
        service.start(connection.id, "test", action())
    with pytest.raises(ConnectionError, match="connection_job_queue_full"):
        ConnectionService(DuckDbStore(store.path)).start(connections[4].id, "test", action())
    assert len(queued) == 4


@pytest.mark.parametrize("error,expected", [
    (RuntimeError("https://private.invalid/?api_key=NEVER-EXPOSE"), "connection_provider_request_failed"),
    (RuntimeError("cex_authentication_failed"), "cex_authentication_failed"),
    (RuntimeError("cex_request_timeout"), "cex_request_timeout"),
])
def test_provider_errors_codes_only_no_retries(service, scheduler, queued, monkeypatch, error, expected):
    connection = create(service)
    called = []

    def test(*_args):
        called.append(True)
        raise error

    monkeypatch.setattr(CexBalanceService, "test_connection", test)
    job = service.start(connection.id, "test", action())
    service._run(str(job.id))
    result = service.jobs().jobs[0]
    assert result.status == "failed" and result.error_code == expected
    assert len(called) == 1
    assert "NEVER-EXPOSE" not in result.model_dump_json()
    assert "NEVER-EXPOSE" not in service.list().model_dump_json()


def test_missing_scheduler_fails_closed_before_job_or_request(service, queued, monkeypatch):
    connection = create(service)
    monkeypatch.setitem(sys.modules, "steuerreport_v2.domain.external_http", ModuleType("steuerreport_v2.domain.external_http"))
    with pytest.raises(ConnectionError, match="external_http_unavailable"):
        service.start(connection.id, "test", action())
    assert service.jobs().jobs == [] and queued == []


def test_job_deadline_restart_and_retention_do_not_autorestart(service, store, scheduler, queued, monkeypatch):
    connection = create(service)
    job = service.start(connection.id, "test", action())
    records = service._read()
    record = records[f"{JOB_PREFIX}{job.id}"]
    record["deadline_at"] = "2000-01-01T00:00:00+00:00"
    record["_pid"] = 2147483647
    store.upsert_admin_setting(AdminSettingWrite(key=f"{JOB_PREFIX}{job.id}", value_json=json.dumps(record)))
    before = store.list_admin_settings()
    assert ConnectionService(DuckDbStore(store.path)).jobs().jobs[0].error_code == "connection_job_deadline_exceeded"
    assert store.list_admin_settings() == before
    assert len(queued) == 1
    # Abgelaufene Jobs duerfen beim Lesen nicht neu gestartet werden.
    assert _JobCancellation(service, str(job.id), 1).is_set()
    record.update(status="succeeded")
    writes = [AdminSettingWrite(key=f"{JOB_PREFIX}{uuid4()}", value_json=json.dumps({**record, "id": str(uuid4())}))
              for _ in range(MAX_RETAINED)]
    store.write_admin_settings_batch(writes, [])
    service.start(connection.id, "test", action())
    assert len([key for key in service._read() if key.startswith(JOB_PREFIX)]) == MAX_RETAINED


def test_deadline_does_not_free_still_running_worker_slot(service, store, scheduler, queued):
    connection = create(service)
    job = service.start(connection.id, "test", action())
    record = service._read()[f"{JOB_PREFIX}{job.id}"]
    record["deadline_at"] = "2000-01-01T00:00:00+00:00"
    store.upsert_admin_setting(AdminSettingWrite(key=f"{JOB_PREFIX}{job.id}", value_json=json.dumps(record)))
    assert service.jobs().jobs[0].error_code == "connection_job_deadline_exceeded"
    assert service.jobs().jobs[0].slot_reserved
    with pytest.raises(ConnectionError, match="connection_job_already_active"):
        service.start(connection.id, "test", action())
    # Cancel bleibt auch nach Deadline moeglich; kein physischer Threadkill.
    assert service.cancel(job.id).cancel_requested
    service._finish(str(job.id), "failed", error_code="connection_job_deadline_exceeded")
    assert not service.jobs().jobs[0].slot_reserved
    service.start(connection.id, "test", action())
    assert len(queued) == 2


def test_api_envelopes_secret_validation_errors_and_demo_mode(store, scheduler, queued):
    app = FastAPI()
    app.include_router(build_connections_router(store))
    with TestClient(app) as client:
        payload = {"provider": "binance", "label": "Synthetisches Konto", "api_key": "SENSITIVE-MOCK-KEY",
                   "api_secret": "SENSITIVE-MOCK-SECRET"}
        created = client.post("/api/v1/admin/connections", json=payload)
        assert created.status_code == 201
        assert "SENSITIVE-MOCK" not in created.text
        connection_id = created.json()["data"]["id"]
        assert client.get("/api/v1/admin/connections").json()["data"]["vault_ready"]
        invalid = client.post("/api/v1/admin/connections", json={**payload, "api_secret": {"raw": "SENSITIVE-MOCK-SECRET"}})
        assert invalid.status_code == 422 and "SENSITIVE-MOCK" not in invalid.text
        rejected = client.post(f"/api/v1/admin/connections/{connection_id}/sync", json={"confirm_external_request": True})
        assert rejected.status_code == 400
        assert rejected.json()["errors"][0]["code"] == "connection_effect_confirmation_required"
        for invalid in (1, "true", False):
            assert client.post(f"/api/v1/admin/connections/{connection_id}/test", json={"confirm_external_request": invalid}).status_code == 422
        accepted = client.post(f"/api/v1/admin/connections/{connection_id}/test", json={"confirm_external_request": True})
        assert accepted.status_code == 202
        job_id = accepted.json()["data"]["id"]
        assert client.get("/api/v1/admin/connections/jobs").json()["data"]["jobs"][0]["id"] == job_id
        assert client.post(f"/api/v1/admin/connections/jobs/{job_id}/cancel").status_code == 200
        assert client.get(f"/api/v1/admin/connections/{connection_id}/snapshots").json()["data"]["snapshots"] == []
        app.state.ux_sandbox = True
        assert client.post("/api/v1/admin/connections", json=payload).status_code == 403
        assert client.get("/api/v1/admin/connections").status_code == 200
        assert len(queued) == 1


def test_real_worker_completes_only_mock_request(service, scheduler, monkeypatch):
    connection = create(service)
    done = threading.Event()
    workers = []
    original = service._finish

    def finish(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            done.set()

    def launch(job_id):
        worker = threading.Thread(target=service._run, args=(job_id,))
        workers.append(worker)
        worker.start()

    monkeypatch.setattr(service, "_finish", finish)
    monkeypatch.setattr(service, "_launch", launch)
    monkeypatch.setattr(CexBalanceService, "test_connection", lambda *_args: None)
    try:
        job = service.start(connection.id, "test", action())
        assert done.wait(15)
        assert next(item for item in service.jobs().jobs if item.id == job.id).status == "succeeded"
    finally:
        for worker in workers:
            worker.join(15)
            assert not worker.is_alive()
