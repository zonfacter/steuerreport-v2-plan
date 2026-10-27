from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceApply, HistoricalPriceFetch, HistoricalPriceQuery
from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as module
from steuerreport_v2.domain.external_http import managed_client
from steuerreport_v2.domain.historical_prices import HistoricalPriceError, HistoricalPriceService
from steuerreport_v2.domain.request_limits import RequestLimiter


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "test.duckdb")
    store.add_canonical_event(CanonicalEventCreate(source="solana_rpc", source_ref="synthetic-reward", asset="SOL", quantity=Decimal("2"),
        event_time=datetime(2024, 6, 2, 12, tzinfo=timezone.utc), event_type="reward"))
    service = HistoricalPriceService(store)
    monkeypatch.setattr(HistoricalPriceService, "mappings", lambda self: {"SOL": {"asset": "SOL", "coingecko_id": "solana", "defillama_id": None}})
    clock = [1_000_000.0]
    limiter = RequestLimiter(state_root=tmp_path / "limits", clock=lambda: clock[0], monotonic=lambda: clock[0], sleep=lambda value: clock.__setitem__(0, clock[0] + value))
    config = RequestLimitsConfig(default_profile=RequestLimitProfile(requests_per_second=1000, requests_per_minute=60000, burst=1000, max_retries=1))
    limiter.write_config(config, expected_revision=0)
    calls = []
    def handle(request):
        calls.append(request)
        if "frankfurter" in request.url.host:
            return httpx.Response(200, json=[{"base": "USD", "quote": "EUR", "date": "2024-05-24", "rate": "0.90"}, {"base": "USD", "quote": "EUR", "date": "2024-05-31", "rate": "0.92"}])
        if "coingecko" in request.url.host:
            return httpx.Response(200, json={"id": "solana", "market_data": {"current_price": {"eur": "140.123456789123456789"}}})
        timestamp = int(request.url.path.split("/")[3])
        return httpx.Response(200, json={"coins": {"coingecko:solana": {"price": "150", "timestamp": timestamp}}})
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(module, "managed_client", lambda **kwargs: managed_client(transport=transport, limiter=limiter, **kwargs))
    return store, service, calls, monkeypatch, limiter


def fetched(service, **kwargs):
    query = HistoricalPriceQuery(**kwargs)
    plan = service.plan(query)
    request = HistoricalPriceFetch(**query.model_dump(), request_id=uuid4(), plan_sha256=plan["plan_sha256"], confirm_external_request=True)
    return request, service.fetch(request)


def test_plan_is_read_only_and_groups_requirements(setup):
    store, service, calls, *_ = setup
    before = service._revision()
    plan = service.plan(HistoricalPriceQuery(year=2024))
    assert plan["fetchable_count"] == 1 and plan["events_count"] == 1
    assert not calls and not service.root.exists()
    assert service._revision() == before


def test_historical_eur_without_v1_is_isolated_and_explicitly_applied(setup):
    store, service, calls, *_ = setup
    before = service._revision()
    request, preview = fetched(service)
    assert preview["requests_started"] == len(calls) == 2
    assert preview["prices_count"] == 1
    assert preview["rows"][0]["price_eur"] == "138.000000000000000000"
    assert preview["rows"][0]["fx_date"] == "2024-05-31"
    assert service._revision() == before and not store.list_price_points()
    result = service.apply(request.request_id, HistoricalPriceApply(preview_sha256=preview["preview_sha256"], actor="Testperson", confirm_prices=True, confirm_recalculation=True))
    assert result["applied"]
    assert any(p.price_eur == Decimal("138") for p in store.list_price_points())
    assert store.list_review_decisions()[0].actor == "Testperson"
    assert store.list_canonical_events()[0].quantity == Decimal("2")
    assert service.apply(request.request_id, HistoricalPriceApply(preview_sha256=preview["preview_sha256"], actor="Testperson", confirm_prices=True, confirm_recalculation=True)) == result
    (service._directory(request.request_id) / "applied.json").unlink()
    assert service.apply(request.request_id, HistoricalPriceApply(preview_sha256=preview["preview_sha256"], actor="Testperson", confirm_prices=True, confirm_recalculation=True)) == result


def test_direct_coingecko_eur_preserves_decimal_precision_and_needs_no_fx(setup):
    store, service, calls, *_ = setup
    _, preview = fetched(service, provider="coingecko")
    assert preview["requests_started"] == 1
    assert preview["rows"][0]["price_eur"] == "140.123456789123456789"
    assert preview["rows"][0]["fx_date"] is None


def test_request_budget_counts_fx_and_leaves_unfinished_price_open(setup):
    store, service, calls, *_ = setup
    _, preview = fetched(service, max_requests=1)
    assert len(calls) == preview["requests_started"] == 1
    assert preview["prices_count"] == 0
    assert preview["rows"][0]["status"] == "open"
    assert not store.list_price_points()


@pytest.mark.parametrize("failure", ["future_quote", "old_quote", "future_fx", "old_fx", "negative", "nan", "identity", "http_403", "http_429"])
def test_invalid_quotes_remain_open_without_invented_prices(setup, failure):
    store, service, calls, monkeypatch, limiter = setup
    def handle(request):
        calls.append(request)
        if failure.startswith("http"):
            return httpx.Response(int(failure[-3:]), json={"error": "not available"})
        if "frankfurter" in request.url.host:
            return httpx.Response(200, json=[{"base": "USD", "quote": "EUR", "date": "2024-06-03" if failure == "future_fx" else "2024-05-01" if failure == "old_fx" else "2024-05-31", "rate": "0.92"}])
        timestamp = int(request.url.path.split("/")[3])
        if failure == "future_quote":
            timestamp += 86400
        if failure == "old_quote":
            timestamp -= 86400
        return httpx.Response(200, json={"coins": {"other" if failure == "identity" else "coingecko:solana": {"price": "-1" if failure == "negative" else "NaN" if failure == "nan" else "150", "timestamp": timestamp}}})
    monkeypatch.setattr(module, "managed_client", lambda **kwargs: managed_client(transport=httpx.MockTransport(handle), limiter=limiter, **kwargs))
    _, preview = fetched(service)
    assert preview["prices_count"] == 0
    assert not store.list_price_points()
    assert len(calls) <= 10


def test_retry_also_consumes_budget(setup):
    store, service, calls, monkeypatch, limiter = setup
    def reject(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "limit"})
    monkeypatch.setattr(module, "managed_client", lambda **kwargs: managed_client(transport=httpx.MockTransport(reject), limiter=limiter, **kwargs))
    _, preview = fetched(service, max_requests=1)
    assert len(calls) == preview["requests_started"] == 1


def test_preview_rejects_changed_database_and_changed_evidence(setup):
    store, service, calls, *_ = setup
    request, preview = fetched(service)
    approval = HistoricalPriceApply(preview_sha256=preview["preview_sha256"], actor="Testperson", confirm_prices=True, confirm_recalculation=True)
    store.add_canonical_event(CanonicalEventCreate(source="manual", source_ref="later", event_time=datetime(2024, 6, 2, 14, tzinfo=timezone.utc), event_type="reward", asset="SOL", quantity=Decimal("1")))
    with pytest.raises(HistoricalPriceError, match="preview_stale"):
        service.apply(request.request_id, approval)
    body = next((service.root / "evidence").glob("*.body"))
    body.chmod(0o600)
    body.write_bytes(b"changed")
    with pytest.raises(HistoricalPriceError, match="evidence_changed"):
        service.get(request.request_id)


def test_same_request_is_idempotent(setup):
    _, service, calls, *_ = setup
    request, preview = fetched(service)
    count = len(calls)
    assert service.fetch(request) == preview
    assert len(calls) == count


def test_route_validation_demo_and_mapping_persistence(tmp_path):
    store = DuckDbStore(tmp_path / "test.duckdb")
    app = FastAPI()
    app.include_router(build_historical_prices_router(store, lambda: None))
    client = TestClient(app)
    base = "/api/v1/prices/historical"
    mapping = {"asset": "TEST", "defillama_id": "solana:syntheticmint"}
    assert client.put(base + "/mappings", json=mapping).status_code == 200
    assert HistoricalPriceService(DuckDbStore(store.path)).mappings()["TEST"]["defillama_id"] == mapping["defillama_id"]
    assert client.put(base + "/mappings", json={"asset": "TEST", "coingecko_id": "https://invalid.example"}).status_code == 422
    assert client.post(base + "/plan", json={"max_requests": -1}).status_code == 422
    app.state.ux_sandbox = True
    assert client.put(base + "/mappings", json=mapping).status_code == 403
    assert client.post(base + "/plan", json={}).status_code == 200
