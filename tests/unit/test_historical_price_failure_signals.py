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


@pytest.mark.parametrize("coin", [None, [], {}, {"prices": None}, {"prices": {}},
                                  {"prices": [None]}, {"prices": [{}]},
                                  {"prices": [{"timestamp": "1717327800", "price": "1"}]}])
def test_malformed_batch_coin_or_element_is_invalid(coin):
    with pytest.raises(HistoricalPriceError, match="^historical_price_response_invalid$"):
        historical_quote({"coins": {"coingecko:test": coin}}, row(), positive, fail)


def test_absent_batch_coin_remains_missing():
    with pytest.raises(HistoricalPriceError, match="^historical_price_quote_missing$"):
        historical_quote({"coins": {}}, row(), positive, fail)


@pytest.mark.parametrize("bad", [None, "NaN", "-1", "0", "invalid"])
@pytest.mark.parametrize("reverse", [False, True])
def test_invalid_price_does_not_hide_a_valid_nearby_quote(bad, reverse):
    instant = int(datetime(2024, 6, 2, 11, 30, tzinfo=timezone.utc).timestamp())
    quotes = [{"timestamp": instant, "price": bad}, {"timestamp": instant + 60, "price": "3"}]
    if reverse:
        quotes.reverse()
    value, priced_at = historical_quote({"coins": {"coingecko:test": {"prices": quotes}}}, row(), positive, fail)
    assert value == Decimal("3") and int(priced_at.timestamp()) == instant + 60


def test_all_invalid_nearby_prices_are_not_reported_as_timestamp_mismatch():
    instant = int(datetime(2024, 6, 2, 11, 30, tzinfo=timezone.utc).timestamp())
    payload = {"coins": {"coingecko:test": {"prices": [{"timestamp": instant, "price": "NaN"}]}}}
    with pytest.raises(HistoricalPriceError, match="^historical_price_value_invalid$"):
        historical_quote(payload, row(), positive, fail)


def test_conflicting_valid_prices_remain_rejected_after_an_invalid_candidate():
    instant = int(datetime(2024, 6, 2, 11, 30, tzinfo=timezone.utc).timestamp())
    payload = {"coins": {"coingecko:test": {"prices": [
        {"timestamp": instant, "price": "NaN"}, {"timestamp": instant, "price": "3"},
        {"timestamp": instant, "price": "4"},
    ]}}}
    with pytest.raises(HistoricalPriceError, match="^historical_price_quote_conflict$"):
        historical_quote(payload, row(), positive, fail)


def test_invalid_confidence_does_not_hide_another_valid_quote():
    instant = int(datetime(2024, 6, 2, 11, 30, tzinfo=timezone.utc).timestamp())
    payload = {"coins": {"coingecko:test": {"prices": [
        {"timestamp": instant, "price": "2", "confidence": "NaN"},
        {"timestamp": instant + 60, "price": "3", "confidence": "0.95"},
    ]}}}
    value, priced_at = historical_quote(payload, row(), positive, fail)
    assert value == Decimal("3") and int(priced_at.timestamp()) == instant + 60


@pytest.mark.parametrize("stage", ["primary", "fallback"])
@pytest.mark.parametrize("batch_status", [429, 503])
def test_failed_batch_keeps_prior_fx_and_response_evidence(tmp_path, stage, batch_status):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    scope = SimpleNamespace(budget=SimpleNamespace(requests_started=0))
    calls = []
    old_sha = "a" * 64
    old_evidence = {"provider": "defillama", "sha256": old_sha}

    def handle(request):
        calls.append(request)
        scope.budget.requests_started += 1
        if request.url.host == "api.frankfurter.dev":
            return httpx.Response(200, json=[{"base": "USD", "quote": "EUR", "date": "2024-05-31", "rate": "0.9"}])
        assert request.url.host == "coins.llama.fi"
        return httpx.Response(batch_status, json={"error": "synthetic failure"})

    @contextmanager
    def scope_factory(**kwargs):
        yield scope

    query = SimpleNamespace(provider="defillama", max_requests=10, strategy="automatic")
    initial = {**row(), "evidence_sha256": [old_sha], "lookup_stage": stage}
    rows, evidence, prices, _, _ = collect_section(
        service, query, [initial], {"evidence": [old_evidence]}, lambda _: None, positive, fail,
        client_factory=lambda **_: httpx.Client(transport=httpx.MockTransport(handle)), scope_factory=scope_factory,
    )
    assert len(calls) == 2 and not prices
    assert rows[0]["status"] == "open" and rows[0]["reason"] == f"historical_price_http_{batch_status}"
    assert set(rows[0]["evidence_sha256"]) == {item["sha256"] for item in evidence}


@pytest.mark.parametrize("coin", [None, {"prices": None}, {"prices": [None]}])
def test_invalid_batch_coin_does_not_trigger_automatic_fallback(tmp_path, coin):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    scope = SimpleNamespace(budget=SimpleNamespace(requests_started=0))
    calls = []

    def handle(request):
        calls.append(request)
        scope.budget.requests_started += 1
        if request.url.host == "api.frankfurter.dev":
            return httpx.Response(200, json=[{"base": "USD", "quote": "EUR", "date": "2024-05-31", "rate": "0.9"}])
        return httpx.Response(200, json={"coins": {"coingecko:test": coin}})

    @contextmanager
    def scope_factory(**kwargs):
        yield scope

    query = SimpleNamespace(provider="defillama", max_requests=10, strategy="automatic")
    rows, evidence, prices, _, _ = collect_section(
        service, query, [row()], None, lambda _: None, positive, fail,
        client_factory=lambda **_: httpx.Client(transport=httpx.MockTransport(handle)), scope_factory=scope_factory,
    )
    assert len(calls) == 2 and not prices
    assert rows[0]["status"] == "open" and rows[0]["reason"] == "historical_price_response_invalid"
    assert set(rows[0]["evidence_sha256"]) == {item["sha256"] for item in evidence}


def test_failed_continuation_reuses_stored_fx_and_keeps_original_evidence(tmp_path):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    previous_evidence = []
    fx_payload = [{"base": "USD", "quote": "EUR", "date": "2024-05-31", "rate": "0.9"}]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=fx_payload))) as client:
        service._request(client, "fx", "https://api.frankfurter.dev/v2/providers/ecb/rates", {}, previous_evidence)
    fx_entry = previous_evidence[0]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"coins": {}}))) as client:
        service._request(client, "defillama", "https://coins.llama.fi/batchHistorical", {}, previous_evidence)
    primary_entry = previous_evidence[1]
    scope = SimpleNamespace(budget=SimpleNamespace(requests_started=0))
    calls = []

    def handle(request):
        calls.append(request)
        scope.budget.requests_started += 1
        assert request.url.host == "coins.llama.fi"
        return httpx.Response(429, json={"error": "synthetic failure"})

    @contextmanager
    def scope_factory(**kwargs):
        yield scope

    query = SimpleNamespace(provider="defillama", max_requests=10, strategy="automatic")
    initial = {**row(), "evidence_sha256": [primary_entry["sha256"]], "lookup_stage": "fallback"}
    previous = {"evidence": previous_evidence, "fx_series": {"2024": fx_entry}}
    rows, evidence, prices, _, _ = collect_section(
        service, query, [initial], previous, lambda _: None, positive, fail,
        client_factory=lambda **_: httpx.Client(transport=httpx.MockTransport(handle)), scope_factory=scope_factory,
    )
    assert len(calls) == 1 and not prices
    assert rows[0]["reason"] == "historical_price_http_429"
    assert set(rows[0]["evidence_sha256"]) == {item["sha256"] for item in evidence}
    assert all(service._path("evidence", item["sha256"] + ".body").is_file() for item in evidence)


@pytest.mark.parametrize("bad_coin,reason", [
    ({"prices": [None]}, "historical_price_response_invalid"),
    ({"prices": [{"timestamp": 1717327800, "price": "NaN"}]}, "historical_price_value_invalid"),
])
def test_invalid_coin_does_not_block_other_batch_rows_or_trigger_fallback(tmp_path, bad_coin, reason):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    scope = SimpleNamespace(budget=SimpleNamespace(requests_started=0))
    calls = []

    def handle(request):
        calls.append(request)
        scope.budget.requests_started += 1
        if request.url.host == "api.frankfurter.dev":
            return httpx.Response(200, json=[{"base": "USD", "quote": "EUR", "date": "2024-05-31", "rate": "0.9"}])
        return httpx.Response(200, json={"coins": {
            "coingecko:test": bad_coin,
            "coingecko:other": {"prices": [{"timestamp": 1717327800, "price": "3"}]},
        }})

    @contextmanager
    def scope_factory(**kwargs):
        yield scope

    query = SimpleNamespace(provider="defillama", max_requests=10, strategy="automatic")
    rows, evidence, prices, _, _ = collect_section(
        service, query, [row("BAD"), {**row("GOOD"), "provider_id": "coingecko:other"}],
        None, lambda _: None, positive, fail,
        client_factory=lambda **_: httpx.Client(transport=httpx.MockTransport(handle)), scope_factory=scope_factory,
    )
    assert len(calls) == 2 and len(prices) == 1
    assert rows[0]["status"] == "open" and rows[0]["reason"] == reason
    assert rows[1]["status"] == "fetched" and prices[0].price_eur == Decimal("2.7")
    assert all(set(item["evidence_sha256"]) == {entry["sha256"] for entry in evidence} for item in rows)


def test_identical_response_bodies_do_not_distinguish_request_metadata(tmp_path):
    service = HistoricalPriceService(SimpleNamespace(path=tmp_path / "synthetic.duckdb"))
    evidence = []
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429, json={"error": "limited"}))) as client:
        for attempt in (1, 2):
            with pytest.raises(HistoricalPriceError, match="^historical_price_http_429$"):
                service._request(client, "defillama", "https://coins.llama.fi/batchHistorical", {"attempt": attempt}, evidence)
    assert evidence[0]["sha256"] == evidence[1]["sha256"]
    assert evidence[0]["params"] != evidence[1]["params"]


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
