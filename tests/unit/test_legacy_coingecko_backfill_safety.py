import importlib.util
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import httpx

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/backfill_coingecko_prices_v2.py"
SPEC = importlib.util.spec_from_file_location("backfill_coingecko_prices_v2", SCRIPT)
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)


def test_execute_rejected_before_database_or_network(monkeypatch):
    monkeypatch.setattr("sys.argv", ["backfill", "--execute"])

    def unexpected(*args, **kwargs):
        raise AssertionError("no database or provider access allowed")

    monkeypatch.setattr(legacy, "DuckDbStore", unexpected)
    monkeypatch.setattr(legacy.httpx, "get", unexpected)
    with pytest.raises(SystemExit, match="--execute gesperrt"):
        legacy.main()


def test_history_request_uses_utc_iso_date_and_reference_midnight(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"market_data": {"current_price": {"eur": "12.34"}}}

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(legacy.httpx, "get", get)
    event = datetime(2025, 7, 2, 1, tzinfo=timezone(timedelta(hours=2)))
    value, timestamp, source = legacy._fetch_price_eur(
        coin_id="example", event_time=event, timeout=5, allow_current_fallback=False
    )
    assert captured["params"]["date"] == "2025-07-01"
    assert value == Decimal("12.34")
    assert timestamp == datetime(2025, 7, 1, tzinfo=timezone.utc)
    assert source == legacy.COINGECKO_SOURCE


def test_history_error_does_not_silently_use_current_price(monkeypatch):
    request = httpx.Request("GET", "https://example.invalid/history")
    response = httpx.Response(429, request=request)

    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("limited", request=request, response=response)

    monkeypatch.setattr(legacy, "_fetch_history_price_eur", fail)
    monkeypatch.setattr(
        legacy, "_fetch_current_price_eur", lambda **kwargs: pytest.fail("unexpected fallback")
    )
    with pytest.raises(httpx.HTTPStatusError):
        legacy._fetch_price_eur(
            coin_id="example", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            timeout=5, allow_current_fallback=False,
        )


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_current_price_fallback_requires_explicit_permission(monkeypatch, status):
    request = httpx.Request("GET", "https://example.invalid/history")
    response = httpx.Response(status, request=request)

    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("provider error", request=request, response=response)

    monkeypatch.setattr(legacy, "_fetch_history_price_eur", fail)
    monkeypatch.setattr(legacy, "_fetch_current_price_eur", lambda **kwargs: Decimal("9"))
    price, _, source = legacy._fetch_price_eur(
        coin_id="example", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        timeout=5, allow_current_fallback=True,
    )
    assert price == Decimal("9")
    assert source == legacy.COINGECKO_CURRENT_SOURCE


def test_server_error_does_not_trigger_fallback_even_when_enabled(monkeypatch):
    request = httpx.Request("GET", "https://example.invalid/history")
    response = httpx.Response(500, request=request)
    monkeypatch.setattr(legacy.httpx, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        legacy, "_fetch_current_price_eur", lambda **kwargs: pytest.fail("unexpected fallback")
    )
    with pytest.raises(httpx.HTTPStatusError):
        legacy._fetch_price_eur(
            coin_id="example", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            timeout=5, allow_current_fallback=True,
        )


def test_dry_run_identifies_candidate_as_unverified(monkeypatch, capsys):
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("sys.argv", ["backfill"])
    monkeypatch.setattr(legacy, "DuckDbStore", lambda *args: object())
    monkeypatch.setattr(legacy, "_missing_portfolio_targets", lambda *args: [
        {"asset": "LINK", "priced_at": timestamp}
    ])
    monkeypatch.setattr(legacy, "_fetch_price_eur", lambda **kwargs: (
        Decimal("1.25"), timestamp, legacy.COINGECKO_SOURCE
    ))
    legacy.main()
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["targets"][0]["status"] == "candidate_unverified"
    assert output["targets"][0]["price_at_is_verified"] is False
    assert output["ready"] == output["created"] == 0
    assert output["candidates_unverified"] == 1
    assert output["pipeline"] is None
