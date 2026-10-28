from contextlib import contextmanager
import json
import logging
from pathlib import Path
from threading import Event

import httpx
import pytest

from steuerreport_v2.contracts.request_limits import RequestLimitsConfig, RequestLimitProfile
from steuerreport_v2.domain.external_http import managed_client, outbound_scope, request_signer, retry_after, endpoint_for, request_cost
from steuerreport_v2.domain.request_limits import RequestLimiter, RequestCancelled, RequestDeadlineExceeded


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    limiter = RequestLimiter(state_root=tmp_path, clock=clock, monotonic=clock, sleep=clock.sleep, random=lambda: 0)
    profile = RequestLimitProfile(requests_per_second=2, requests_per_minute=60, burst=2, timeout_seconds=5.0, job_deadline_seconds=120.0)
    limiter.write_config(RequestLimitsConfig(default_profile=profile), expected_revision=0)
    return clock, limiter


@contextmanager
def client_for(setup, handler, provider="binance"):
    clock, limiter = setup
    with managed_client(transport=httpx.MockTransport(handler), limiter=limiter, provider=provider, clock=clock, monotonic=clock) as client:
        yield client


def test_each_retry_reserves_and_resigns_after_retry_after(setup, caplog):
    clock, limiter = setup
    times, signatures = [], []
    def handler(request):
        times.append(clock.now)
        signatures.append(request.headers["x-synthetic-time"])
        logging.getLogger("httpx").warning("url=%s", str(request.url))
        return httpx.Response(429 if len(times) == 1 else 200, json={"ok": True}, headers={"Retry-After": "5", "x-mbx-used-weight-1m": "20"})
    def sign(request):
        request.headers["x-synthetic-time"] = str(clock.now)
    with request_signer(sign), client_for(setup, handler) as client:
        response = client.get("https://api.binance.com/api/v3/account?signature=synthetic-sensitive-query")
    assert response.status_code == 200
    assert len(times) == 2 and times[1] - times[0] >= 5
    assert signatures[0] != signatures[1]
    assert "synthetic-sensitive-query" not in caplog.text
    assert "signature" not in str(response.request.url)
    assert all(row.requests_last_minute == 2 for row in limiter.status().groups)


@pytest.mark.parametrize("method,body,expected", [
    ("POST", {"model": "synthetic", "messages": []}, 1),
    ("POST", {"jsonrpc": "2.0", "method": "sendTransaction"}, 1),
    ("POST", {"jsonrpc": "2.0", "method": "getTransaction"}, 3),
    ("GET", None, 3),
])
def test_retry_budget_and_idempotence_are_enforced(setup, method, body, expected):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "synthetic"}, headers={"Retry-After": "1"})
    with client_for(setup, handler, "helius") as client:
        assert client.request(method, "https://synthetic.invalid/", json=body).status_code == 429
    assert len(calls) == expected


def test_auth_failure_never_retries(setup):
    calls = []
    with client_for(setup, lambda request: calls.append(request) or httpx.Response(401)) as client:
        assert client.get("https://synthetic.invalid/").status_code == 401
    assert len(calls) == 1


def test_caller_can_only_tighten_retry_and_response_limits(setup):
    clock, limiter = setup
    calls = []
    with managed_client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(429)),
                        limiter=limiter, provider="github_updates", clock=clock, monotonic=clock, max_retries=0) as client:
        assert client.get("https://synthetic.invalid/").status_code == 429
    assert len(calls) == 1
    clock.sleep(5)
    with managed_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"too-large")),
                        limiter=limiter, provider="github_updates", clock=clock, monotonic=clock, max_response_bytes=4) as client:
        with pytest.raises(httpx.TransportError):
            client.get("https://synthetic.invalid/")
    assert all(row.in_flight == 0 for row in limiter.status().groups)


@pytest.mark.parametrize("options", [
    {"max_response_bytes": 0}, {"max_response_bytes": -1}, {"max_response_bytes": True},
    {"max_response_bytes": 64 * 1024 * 1024 + 1}, {"max_retries": -1}, {"max_retries": True},
])
def test_invalid_caller_transport_limits_fail_closed(options):
    with pytest.raises(ValueError):
        managed_client(**options)


def test_cancellation_stops_following_requests_and_releases_parallelism(setup):
    cancel = Event()
    def handler(request):
        cancel.set()
        return httpx.Response(200, content=b"synthetic")
    clock, limiter = setup
    with outbound_scope(provider="binance", cancel=cancel, deadline=clock.now + 20, clock=clock, monotonic=clock), client_for(setup, handler) as client:
        with pytest.raises(RequestCancelled):
            client.get("https://synthetic.invalid/")
    assert all(row.in_flight == 0 for row in limiter.status().groups)


def test_signed_transport_errors_do_not_expose_credentials(setup):
    def handler(request):
        raise httpx.ConnectError("secret-in-exception synthetic-token", request=request)
    with client_for(setup, handler) as client:
        with pytest.raises(httpx.TransportError) as caught:
            client.get("https://synthetic.invalid/private/synthetic-token?api-key=synthetic-token")
    assert "synthetic-token" not in str(caught.value)
    assert "synthetic-token" not in str(caught.value.request.url)


def test_job_deadline_includes_budget_wait(setup):
    clock, limiter = setup
    limiter.pause("binance", 20)
    with outbound_scope(provider="binance", deadline=clock.now + 2, clock=clock, monotonic=clock), client_for(setup, lambda _request: pytest.fail("Deadline bypass")) as client:
        with pytest.raises(RequestDeadlineExceeded):
            client.get("https://synthetic.invalid/")


def test_redirect_hops_and_metadata_use_same_budget(setup):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(302, headers={"Location": "/metadata"}) if request.url.path == "/start" else httpx.Response(200, json={"ok": True})
    clock, limiter = setup
    with client_for(setup, handler) as client:
        assert client.get("https://synthetic.invalid/start", follow_redirects=True).status_code == 200
    assert calls == ["/start", "/metadata"]
    assert all(row.requests_last_minute == 2 for row in limiter.status().groups)


def test_jupiter_reset_is_not_treated_as_full_refill(setup):
    clock, limiter = setup
    calls = []
    def handler(request):
        calls.append(clock.now)
        return httpx.Response(200, json={}, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(clock.now + 5)})
    with client_for(setup, handler, "jupiter") as client:
        client.get("https://api.jup.ag/tokens/v2/search")
        client.get("https://api.jup.ag/tokens/v2/search")
    assert calls[1] - calls[0] >= 5
    assert retry_after("Thu, 01 Jan 1970 00:17:00 GMT", 1000) == 20


def test_package_request_paths_do_not_construct_unmanaged_clients():
    import ast
    root = Path(__file__).resolve().parents[2] / "src/steuerreport_v2"
    violations = []
    for path in root.rglob("*.py"):
        if path.name == "external_http.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = ast.unparse(node.func)
                if name in {"httpx.Client", "httpx.AsyncClient", "httpx.get", "httpx.post", "urllib.request.urlopen", "requests.get", "requests.post"}:
                    violations.append(f"{path.name}:{node.lineno}:{name}")
    assert not violations, json.dumps(violations)


@pytest.mark.parametrize("batch", [False, True])
def test_private_rpc_under_internal_api_prefix_still_reserves_budget(setup, monkeypatch, batch):
    import urllib.request
    from steuerreport_v2.domain import external_http
    clock, limiter = setup
    original = external_http.managed_client
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"result": 1})
    monkeypatch.setattr(external_http, "managed_client", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), limiter=limiter, clock=clock, monotonic=clock, **kwargs,
    ))
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": ["synthetic-wallet"]}
    request = urllib.request.Request("http://127.0.0.1:8899/api/v1/rpc", data=json.dumps([payload] if batch else payload).encode())
    with external_http.managed_urlopen(request) as response:
        assert json.load(response) == {"result": 1}
    assert calls == ["/api/v1/rpc"]
    assert next(item for item in limiter.status().groups if item.group == "ip:global").requests_last_minute == 1


def test_internal_api_relay_never_follows_redirects_or_holds_external_budget(monkeypatch):
    from steuerreport_v2.domain import external_http
    original = httpx.Client
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://foreign.invalid/"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(external_http.httpx, "Client", client)
    monkeypatch.setattr(external_http, "managed_client", lambda **kwargs: pytest.fail("Internal relay held provider budget"))
    with external_http.managed_urlopen("http://127.0.0.1:8010/api/v1/health") as response:
        assert response.status == 302
    assert calls == ["127.0.0.1"]


@pytest.mark.parametrize("header", ["token", "X-API-Key", "Authorization"])
def test_credentials_never_follow_cross_origin_redirect(setup, header):
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://foreign.invalid/collect"})
    with client_for(setup, handler, "solscan") as client:
        with pytest.raises(httpx.TransportError):
            client.get("https://pro-api.solscan.io/v2.0/account/portfolio", headers={header: "SYNTHETIC-NOT-TO-FOREIGN"}, follow_redirects=True)
    assert calls == ["pro-api.solscan.io"]


def test_monotonic_scope_deadline_survives_wall_clock_rollback(tmp_path):
    class DualClock:
        wall = 1000.0
        mono = 0.0
        def sleep(self, seconds):
            self.wall += seconds
            self.mono += seconds
    clock = DualClock()
    limiter = RequestLimiter(state_root=tmp_path, clock=lambda: clock.wall, monotonic=lambda: clock.mono, sleep=clock.sleep)
    calls = []
    with outbound_scope(provider="binance", deadline=1010, clock=lambda: clock.wall, monotonic=lambda: clock.mono):
        with managed_client(limiter=limiter, clock=lambda: clock.wall, monotonic=lambda: clock.mono, transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
            client.get("https://api.binance.com/api/v3/account")
            clock.wall -= 3600
            clock.mono = 12
            with pytest.raises(RequestDeadlineExceeded):
                client.get("https://api.binance.com/api/v3/account")
    assert len(calls) == 1


def test_observed_rate_limit_is_persisted_before_lease_release(setup, monkeypatch):
    clock, limiter = setup
    original = limiter._release
    observations = []
    def release(identifier):
        observations.append(all(group.paused_until >= clock.now + 5 for group in limiter.status().groups))
        original(identifier)
    monkeypatch.setattr(limiter, "_release", release)
    with client_for(setup, lambda _request: httpx.Response(429, headers={"Retry-After": "5"})) as client:
        assert client.post("https://api.binance.com/non-idempotent").status_code == 429
    assert observations == [True]


def test_expired_signature_preparation_cannot_start_network(setup):
    clock, limiter = setup
    def slow_prepare(_request):
        clock.now += 20
    with outbound_scope(provider="binance", deadline=clock.now + 5, clock=clock, monotonic=clock), request_signer(slow_prepare):
        with client_for(setup, lambda _request: pytest.fail("Expired request reached network")) as client:
            with pytest.raises(RequestDeadlineExceeded):
                client.get("https://api.binance.com/api/v3/account")
    assert all(group.in_flight == 0 for group in limiter.status().groups)


def test_distinct_endpoint_weights_and_rpc_batches_have_explicit_costs():
    assert endpoint_for(httpx.Request("GET", "https://api.binance.com/sapi/v1/simple-earn/flexible/position")) == "earn_flexible_position"
    costs = {"rpc_getbalance": 10, "rpc_gettransaction": 20}
    request = httpx.Request("POST", "https://rpc.invalid/", json=[{"jsonrpc": "2.0", "method": "getBalance"}, {"jsonrpc": "2.0", "method": "getTransaction"}])
    assert request_cost(request, costs) == 30


def test_redirect_response_without_follow_is_preserved_but_next_request_is_blocked(setup):
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://foreign.invalid/collect"})
    with client_for(setup, handler, "ai_local") as client:
        response = client.get("https://original.invalid/start", headers={"token": "SYNTHETIC-SECRET"}, follow_redirects=False)
        assert response.status_code == 302
        with pytest.raises(httpx.TransportError):
            client.send(response.next_request)
    assert calls == ["original.invalid"]
