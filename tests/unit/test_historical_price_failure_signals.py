from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from steuerreport_v2.domain.historical_price_collection import collect_section, historical_quote
from steuerreport_v2.domain.historical_prices import HistoricalPriceError, HistoricalPriceService, fail, positive


def row(asset="TEST"):
    return {"asset": asset, "price_date": "2024-06-02", "first_event_at": "2024-06-02T12:00:00+00:00",
            "provider_id": "coingecko:test", "status": "pending"}


@pytest.mark.parametrize("payload", [None, [], {"coins": None}, {"coins": []}])
def test_malformed_batch_response_is_invalid(payload):
    with pytest.raises(HistoricalPriceError, match="^historical_price_response_invalid$"):
        historical_quote(payload, row(), positive, fail)


def test_out_of_range_timestamp_is_a_time_mismatch():
    payload = {"coins": {"coingecko:test": {"prices": [{"timestamp": 10**30, "price": "2"}]}}}
    with pytest.raises(HistoricalPriceError, match="^historical_price_timestamp_mismatch$"):
        historical_quote(payload, row(), positive, fail)


def test_out_of_range_timestamp_does_not_mask_a_valid_quote():
    instant = int(datetime(2024, 6, 2, 11, 30, tzinfo=timezone.utc).timestamp())
    payload = {"coins": {"coingecko:test": {"prices": [
        {"timestamp": 10**30, "price": "2"}, {"timestamp": instant, "price": "3"},
    ]}}}
    value, priced_at = historical_quote(payload, row(), positive, fail)
    assert value == Decimal("3") and int(priced_at.timestamp()) == instant


@pytest.mark.parametrize("fx_status,fx_payload,reason", [
    (429, {"error": "limited"}, "historical_price_http_429"),
    (200, [], "historical_price_fx_date_invalid"),
    (200, [{"base": "USD", "quote": "EUR", "date": "2024-05-01", "rate": "0.9"}], "historical_price_fx_date_invalid"),
])
def test_all_rows_link_reused_fx_failure_evidence(tmp_path, fx_status, fx_payload, reason):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    scope = SimpleNamespace(budget=SimpleNamespace(requests_started=0))
    calls = []

    def handle(request):
        calls.append(request)
        scope.budget.requests_started += 1
        assert request.url.host == "api.frankfurter.dev"
        return httpx.Response(fx_status, json=fx_payload)

    @contextmanager
    def scope_factory(**kwargs):
        yield scope

    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handle))

    query = SimpleNamespace(provider="defillama", max_requests=10, strategy="manual")
    rows, evidence, prices, _, _ = collect_section(
        service, query, [row("TEST1"), row("TEST2")], None, lambda _: None, positive, fail,
        client_factory=client_factory, scope_factory=scope_factory,
    )
    assert len(calls) == 1 and not prices
    assert len(evidence) == 1 and evidence[0]["provider"] == "fx"
    assert all(item["status"] == "open" and item["reason"] == reason for item in rows)
    assert all(item["evidence_sha256"] == [evidence[0]["sha256"]] for item in rows)


@pytest.mark.parametrize("payload", [None, [], {"id": "test", "market_data": None},
                                   {"id": "test", "market_data": {"current_price": []}}])
def test_coingecko_malformed_response_is_signalled_as_invalid(tmp_path, payload):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        with pytest.raises(HistoricalPriceError, match="^historical_price_response_invalid$"):
            service._quote(client, {**row(), "provider_id": "test"}, SimpleNamespace(provider="coingecko"), [], {})


@pytest.mark.parametrize("payload", [[], {"coins": None}, {"coins": []}])
def test_direct_defillama_malformed_response_is_signalled_as_invalid(tmp_path, payload):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        with pytest.raises(HistoricalPriceError, match="^historical_price_response_invalid$"):
            service._quote(client, row(), SimpleNamespace(provider="defillama"), [], {})
