from decimal import Decimal

import httpx

from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService


def test_legacy_coingecko_history_uses_documented_iso_date() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"market_data": {"current_price": {"usd": 12.5}}})

    service = object.__new__(ExternalPriceBackfillService)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        value = service._fetch_coingecko_history_price(client, "synthetic-coin", "2025-02-03")

    assert value == Decimal("12.5")
    assert len(calls) == 1
    assert calls[0].url.path == "/api/v3/coins/synthetic-coin/history"
    assert calls[0].url.params["date"] == "2025-02-03"
    assert calls[0].url.params["localization"] == "false"


def test_legacy_coingecko_history_keeps_rate_limit_as_missing() -> None:
    service = object.__new__(ExternalPriceBackfillService)
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(429))) as client:
        value = service._fetch_coingecko_history_price(client, "synthetic-coin", "2025-02-03")

    assert value == Decimal("0")
