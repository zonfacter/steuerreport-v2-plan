from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import httpx
import pytest

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain import external_http
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService


def test_binance_earn_has_no_second_retry_loop(tmp_path, monkeypatch):
    service = BinanceEarnHistoryService(DuckDbStore(tmp_path / "earn.duckdb"))
    calls = []

    def fail(*args):
        calls.append(args)
        raise httpx.ReadTimeout("synthetic timeout")

    monkeypatch.setattr(service, "_signed_get", fail)
    with pytest.raises(httpx.ReadTimeout):
        service._signed_get_with_retries("synthetic-key", "synthetic-secret", "/test", {})
    assert len(calls) == 1


class _WaitingLimiter:
    """Kontrollierte Quotenwartezeit, kein realer Netzwerk- oder Sleep-Aufruf."""

    def __init__(self, clock):
        self.clock = clock
        self.acquisitions = 0
        self.pauses = []

    def profile(self, *_args, **_kwargs):
        return SimpleNamespace(job_deadline_seconds=300, max_retries=1, backoff_base_seconds=1)

    def read_config(self):
        return SimpleNamespace(endpoint_costs={})

    @contextmanager
    def acquire(self, *_args, **_kwargs):
        self.acquisitions += 1
        self.clock[0] += 40
        yield SimpleNamespace(timeout_seconds=20, start=lambda *, prepare=None: prepare() if prepare else None)

    def pause(self, provider, delay, **_kwargs):
        self.pauses.append((provider, delay))

    def retry_delay(self, *_args, **_kwargs):
        return 1


def _jwt_payload(token):
    value = token.removeprefix("Bearer ").split(".")[1]
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


@pytest.mark.parametrize("provider", ["binance", "bitget", "pionex", "coinbase"])
def test_auth_is_signed_after_budget_wait_and_again_for_each_retry(tmp_path, monkeypatch, provider):
    clock = [1000]
    limiter = _WaitingLimiter(clock)
    calls = []
    key = "synthetic-api-key"
    secret = "synthetic-api-secret"
    if provider == "coinbase":
        secret = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")

    def handle(request):
        calls.append((str(request.url), dict(request.headers), clock[0]))
        return httpx.Response(429 if len(calls) == 1 else 200,
                              headers={"Retry-After": "60"}, json={})

    original_client = external_http.managed_client
    monkeypatch.setattr(external_http, "managed_client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handle), limiter=limiter, **kwargs,
    ))
    # Nur die Uhr des Signierers ersetzen, nicht die Prozess-/Transport-Uhr.
    monkeypatch.setattr("steuerreport_v2.domain.cex_balances.time", SimpleNamespace(time=lambda: clock[0]))
    service = CexBalanceService(DuckDbStore(tmp_path / "signing.duckdb"))
    if provider == "binance":
        service._binance_get("/api/v3/account", key, secret, {"omitZeroBalances": "true"})
    elif provider == "bitget":
        service._bitget_get("/api/v2/spot/account/assets", key, secret, "synthetic-pass", {"assetType": "hold_only"})
    elif provider == "pionex":
        service._pionex_get("/api/v1/account/balances", key, secret)
    else:
        service._coinbase_get("/api/v3/brokerage/accounts", key, secret, {"limit": "1"})

    assert limiter.acquisitions == 2
    assert [at for _, _, at in calls] == [1040, 1080]
    assert limiter.pauses
    for url, headers, now in calls:
        if provider == "binance":
            unsigned, signature = url.split("?", 1)[1].rsplit("&signature=", 1)
            assert parse_qs(unsigned)["timestamp"] == [str(now * 1000)]
            assert signature == hmac.new(secret.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
            assert headers["x-mbx-apikey"] == key
        elif provider == "bitget":
            assert headers["access-timestamp"] == str(now * 1000)
            body = f"{now * 1000}GET/api/v2/spot/account/assets?assetType=hold_only"
            assert headers["access-sign"] == base64.b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode()
            assert headers["access-passphrase"] == "synthetic-pass"
        elif provider == "pionex":
            query = urlencode({"timestamp": str(now * 1000)})
            assert url.endswith("?" + query)
            body = f"GET/api/v1/account/balances?{query}"
            assert headers["pionex-signature"] == hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        else:
            assert _jwt_payload(headers["authorization"])["nbf"] == now
            assert _jwt_payload(headers["authorization"])["exp"] == now + 120


def test_auth_error_has_no_sensitive_url_or_retry(tmp_path, monkeypatch):
    limiter = _WaitingLimiter([1000])
    original_client = external_http.managed_client
    monkeypatch.setattr(external_http, "managed_client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(
            401, json={"msg": "SENSITIVE-MOCK-SECRET"})), limiter=limiter, **kwargs,
    ))
    service = CexBalanceService(DuckDbStore(tmp_path / "auth.duckdb"))
    with pytest.raises(RuntimeError, match="^cex_authentication_failed$") as error:
        service._binance_get("/api/v3/account", "SENSITIVE-MOCK-KEY", "SENSITIVE-MOCK-SECRET", {})
    assert "SENSITIVE-MOCK" not in str(error.value)
    assert error.value.__cause__ is None
    assert limiter.acquisitions == 1
