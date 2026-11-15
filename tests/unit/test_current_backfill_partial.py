import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


@pytest.fixture
def current(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2025, 6, 2, 12, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.datetime", Clock)
    store = DuckDbStore(tmp_path / "isolated.duckdb")
    config = tmp_path / "assets.json"
    config.write_text('{"assets":[{"symbol":"AAA","coingecko_id":"a"},{"symbol":"BBB","defillama_id":"synthetic:b"}]}')
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.BalanceLedgerBuilder", lambda store: SimpleNamespace(
        positions=lambda: [SimpleNamespace(asset=a, quantity=Decimal("1")) for a in ("AAA", "BBB")]
    ))
    monkeypatch.setattr(ExternalPriceBackfillService, "_token_risk_statuses", lambda self: {})
    calls = []
    def coin(self, client, ids):
        calls.append("coin")
        return {"a": Decimal("2")}
    def defi(self, client, ids):
        calls.append("defi")
        return {"synthetic:b": Decimal("3")}
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", coin)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", defi)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", lambda *args: (Decimal("0.9"), "2025-06-01"))
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: PipelineResult(
        normalized_events=0, balance_entries=0, flow_entries=0, tax_lines=0, review_issues_open=0, allow_export=False,
    ))
    payload = {"config_path": str(config), "dry_run": False, "request_id": str(uuid4())}
    return store, payload, calls


def test_success_ids_and_replay_blocked_after_restart(current):
    store, payload, calls = current
    client = TestClient(create_app(store))
    first = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert first.status_code == 200
    data = first.json()["data"]
    assert data["imported_prices"] == 2 and data["pipeline_status"] == "completed"
    assert set(data["stored_price_ids"]) == {p.price_id for p in store.list_price_points()}
    second = TestClient(create_app(DuckDbStore(store.path))).post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert second.status_code == 409 and second.json()["errors"][0]["code"] == "current_backfill_replay_blocked"
    assert calls == ["coin", "defi"] and len(store.list_price_points()) == 2
    changed = {**payload, "assets": ["AAA"]}
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=changed).status_code == 409


def test_legacy_payload_repeat_blocked_and_new_explicit_request(current):
    store, payload, calls = current
    payload.pop("request_id")
    client = TestClient(create_app(store))
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert len(calls) == 2
    payload["request_id"] = str(uuid4())
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200
    assert len(store.list_price_points()) == 4


@pytest.mark.parametrize("failed_provider", ["coin", "defi", "fx"])
def test_provider_failure_is_sanitized_and_other_prices_survive(current, monkeypatch, caplog, failed_provider):
    store, payload, _ = current
    canary = "SYNTHETIC_PROVIDER_SECRET_49"
    method = {"coin": "_fetch_coingecko_simple_prices_eur", "defi": "_fetch_defillama_current_prices_usd", "fx": "_fetch_frankfurter_usd_eur"}[failed_provider]
    def fail(*args, **kwargs):
        raise RuntimeError(f"/private/path?token={canary}")
    monkeypatch.setattr(ExternalPriceBackfillService, method, fail)
    caplog.set_level(logging.ERROR)
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    body = response.json()
    assert body["data"]["failed"] == 1 and body["data"]["imported_prices"] == 1
    assert "price_provider_error" in {w["code"] for w in body["warnings"]}
    assert canary not in response.text + caplog.text and "/private/path" not in response.text + caplog.text
    assert set(body["data"]["stored_price_ids"]) == {p.price_id for p in store.list_price_points()}


@pytest.mark.parametrize("signal", [RequestCancelled, RequestDeadlineExceeded])
def test_cancel_or_deadline_stops_before_price_write_and_pipeline(current, monkeypatch, caplog, signal):
    store, payload, calls = current
    def fail(*args):
        raise signal("SYNTHETIC_CANCELLATION_SECRET")
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", fail)
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: pytest.fail("pipeline must not run"))
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    result = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert result.status_code == 503 and result.json()["data"]["storage_status"] == "not_started"
    assert not store.list_price_points() and "SYNTHETIC_CANCELLATION_SECRET" not in result.text + caplog.text
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert calls == ["coin"]


@pytest.mark.parametrize("insert_before_failure", [False, True])
def test_storage_failure_unknown_before_and_after_write_blocks_repeat(current, monkeypatch, caplog, insert_before_failure):
    store, payload, calls = current
    original = store.add_price_points
    def fail(prices):
        if insert_before_failure:
            original(prices)
        raise RuntimeError("SYNTHETIC_STORAGE_SECRET")
    monkeypatch.setattr(store, "add_price_points", fail)
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: pytest.fail("pipeline must not run"))
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 500
    assert response.json()["data"] == {"storage_status": "unknown", "pipeline_status": "not_started"}
    assert "SYNTHETIC_STORAGE_SECRET" not in response.text + caplog.text
    assert len(store.list_price_points()) == (2 if insert_before_failure else 0)
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert calls == ["coin", "defi"]


def test_pipeline_failure_has_ids_unknown_effects_no_secret_and_no_retry(current, monkeypatch, caplog):
    store, payload, calls = current
    def fail(self):
        raise RuntimeError("SYNTHETIC_PIPELINE_SECRET")
    monkeypatch.setattr(PipelineService, "rebuild_all", fail)
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    data = response.json()["data"]
    assert data["pipeline_status"] == "failed" and data["pipeline_effects"] == "unknown_or_partial"
    assert set(data["stored_price_ids"]) == {p.price_id for p in store.list_price_points()}
    assert "SYNTHETIC_PIPELINE_SECRET" not in response.text + caplog.text
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert calls == ["coin", "defi"]


def test_dry_run_does_not_reserve_apply_key(current):
    store, payload, calls = current
    client = TestClient(create_app(store))
    assert client.post("/api/v1/prices/backfill/current-portfolio", json={**payload, "dry_run": True}).status_code == 200
    assert calls == [] and not store.list_price_points()
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200


def test_provider_context_exception_does_not_leak_and_blocks_replay(current, monkeypatch, caplog):
    store, payload, calls = current
    def fail(**kwargs):
        raise RuntimeError("SYNTHETIC_CONTEXT_SECRET")
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", fail)
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 503 and response.json()["data"]["storage_status"] == "not_started"
    assert "SYNTHETIC_CONTEXT_SECRET" not in response.text + caplog.text
    assert not store.list_price_points() and calls == []
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409


def test_provider_and_pipeline_warnings_coexist(current, monkeypatch):
    store, payload, _ = current
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic")))
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: (_ for _ in ()).throw(RuntimeError("synthetic")))
    body = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload).json()
    assert {w["code"] for w in body["warnings"]} >= {"price_provider_error", "price_backfill_partial_failure", "price_backfill_pipeline_failed", "usd_eur_daily_reference_unverified"}
    assert len(body["data"]["stored_price_ids"]) == 1


def test_concurrent_duplicate_request_has_only_one_price_write(current):
    store, payload, calls = current
    client = TestClient(create_app(store))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/api/v1/prices/backfill/current-portfolio", json=payload), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert calls == ["coin", "defi"] and len(store.list_price_points()) == 2
