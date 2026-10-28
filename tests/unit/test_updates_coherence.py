"""Metadatencache ist keine Aktualitaetsgarantie bei unvollstaendiger Kette."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json

import httpx

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.updates import CACHE_KEY, UpdateService


def service_and_success(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])))
    service = UpdateService(store, client=client, installed_version="0.2.0rc32",
        state_dir=tmp_path / "state", clock=lambda: datetime(2026, 10, 28, 22, tzinfo=timezone.utc))
    assert service.check().status == "up_to_date"
    success = next(json.loads(x.value_json) for x in store.list_admin_settings() if x.key == CACHE_KEY)
    return store, service, success, client


def write_cache(store, value):
    store.upsert_admin_setting(AdminSettingWrite(key=CACHE_KEY, value_json=json.dumps(value)))


def test_missing_following_page_cannot_claim_up_to_date(tmp_path):
    store, service, success, client = service_and_success(tmp_path)
    try:
        success["pages"]["1"]["has_next"] = True
        write_cache(store, success)
        result = service.status()
        assert result.status == "unavailable"
        assert result.stale or result.incomplete
    finally:
        client.close()


def test_status_reads_success_completed_while_taking_lock(tmp_path, monkeypatch):
    store, service, success, client = service_and_success(tmp_path)
    try:
        unfinished = {**success, "error": "Die letzte Update-Pruefung wurde nicht abgeschlossen."}
        write_cache(store, unfinished)

        @contextmanager
        def completed_during_lock(*, create):
            write_cache(store, success)
            yield True

        monkeypatch.setattr(service, "_lock", completed_during_lock)
        result = service.status()
        assert result.status == "up_to_date"
        assert "nicht abgeschlossen" not in result.message
    finally:
        client.close()
