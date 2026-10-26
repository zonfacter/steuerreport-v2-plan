"""Ein gemeinsamer, fail-closed HTTP-Transport fuer externe Anwendungsaufrufe."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
import json
import io
import ipaddress
import logging
import math
import time
import urllib.error
from threading import Event, Lock
from typing import Callable

import httpx

from steuerreport_v2.domain.request_limits import RequestLimiter, RequestCancelled, RequestDeadlineExceeded


@dataclass
class ScopeBudget:
    started_monotonic: float
    deadline_monotonic: float | None
    lock: Lock = field(default_factory=Lock)


@dataclass(frozen=True)
class OutboundScope:
    provider: str | None = None
    connection_id: str | None = None
    groups: tuple[str, ...] = ()
    cancel: Event | None = None
    deadline: float | None = None
    budget: ScopeBudget | None = None


_scope: ContextVar[OutboundScope] = ContextVar("outbound_scope", default=OutboundScope())
_signer: ContextVar[Callable[[httpx.Request], None] | None] = ContextVar("request_signer", default=None)
RPC_READS = frozenset({
    "getTransaction", "getSignaturesForAddress", "getBalance", "getAccountInfo",
    "getMultipleAccounts", "getTokenAccountsByOwner", "getTokenAccountBalance",
    "getAsset", "getAssetsByOwner", "getAssetsByGroup", "getAssetBatch", "getAssetProof",
    "getBlock", "getBlockTime", "getBlockHeight", "getSlot", "getHealth", "getVersion",
    "getProgramAccounts", "getSignatureStatuses", "getLatestBlockhash",
})
HOST_PROVIDERS = {
    "binance.com": "binance", "binance.us": "binance", "bitget.com": "bitget",
    "pionex.com": "pionex", "coinbase.com": "coinbase", "solscan.io": "solscan",
    "helius-rpc.com": "helius", "helius.xyz": "helius", "helius.dev": "helius",
    "alchemy.com": "alchemy", "alchemyapi.io": "alchemy", "jup.ag": "jupiter",
    "solana.com": "solana_rpc", "coingecko.com": "coingecko", "cryptocompare.com": "cryptocompare",
    "ecb.europa.eu": "ecb", "frankfurter.app": "fx", "frankfurter.dev": "fx",
    "openrouter.ai": "ai_openrouter",
}
HTTP_ENDPOINTS = {
    "/api/v3/account": "account", "/api/v2/spot/account/assets": "spot_assets",
    "/api/v1/account/balances": "balances", "/api/v3/brokerage/accounts": "accounts",
    "/sapi/v1/simple-earn/flexible/position": "earn_flexible_position",
    "/sapi/v1/simple-earn/locked/position": "earn_locked_position",
    "/sapi/v1/simple-earn/flexible/history/subscriptionRecord": "earn_flexible_subscription",
    "/sapi/v1/simple-earn/flexible/history/redemptionRecord": "earn_flexible_redemption",
    "/sapi/v1/simple-earn/flexible/history/rewardsRecord": "earn_flexible_rewards",
    "/sapi/v1/simple-earn/locked/history/subscriptionRecord": "earn_locked_subscription",
    "/sapi/v1/simple-earn/locked/history/redemptionRecord": "earn_locked_redemption",
    "/sapi/v1/simple-earn/locked/history/rewardsRecord": "earn_locked_rewards",
    "/sapi/v1/capital/withdraw/history": "withdrawals",
    "/sapi/v1/asset/assetDividend": "dividends",
    "/api/v2/spot/wallet/withdrawal-records": "withdrawals",
    "/v2.0/account/portfolio": "account_portfolio",
    "/v2.0/account/balance_change": "balance_changes",
    "/v2.0/account/transactions": "account_transactions",
    "/v2.0/transaction/detail": "transaction_detail",
    "/tokens/v2/search": "token_search", "/price/v3": "prices", "/price/v2": "prices",
}


@contextmanager
def outbound_scope(*, provider=None, connection_id=None, groups=(), cancel=None, deadline=None, clock=time.time, monotonic=time.monotonic):
    started = monotonic()
    budget = ScopeBudget(started, started + max(0, deadline - clock()) if deadline is not None else None)
    token = _scope.set(OutboundScope(provider, str(connection_id) if connection_id else None, tuple(groups), cancel, deadline, budget))
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def request_signer(callback):
    token = _signer.set(callback)
    try:
        yield
    finally:
        _signer.reset(token)


def provider_for(request: httpx.Request, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    host = request.url.host.lower()
    for suffix, provider in HOST_PROVIDERS.items():
        if host == suffix or host.endswith("." + suffix):
            return provider
    try:
        payload = json.loads(request.content)
        if isinstance(payload, dict) and payload.get("jsonrpc") == "2.0":
            return "solana_rpc"
    except (ValueError, httpx.RequestNotRead):
        pass
    return "other"


def endpoint_for(request: httpx.Request) -> str:
    # No paths, wallet addresses, signed query strings or access keys in telemetry.
    try:
        payload = json.loads(request.content)
        if isinstance(payload, dict) and payload.get("method") in RPC_READS:
            return "rpc_" + payload["method"].lower()
    except (ValueError, httpx.RequestNotRead):
        pass
    return HTTP_ENDPOINTS.get(request.url.path, "default")


def request_cost(request, costs):
    fallback = costs.get("default", 1)
    try:
        payload = json.loads(request.content)
        if isinstance(payload, list) and payload and all(isinstance(row, dict) and row.get("jsonrpc") == "2.0" for row in payload):
            return sum(costs.get("rpc_" + str(row.get("method", "")).lower(), fallback) for row in payload)
    except (ValueError, httpx.RequestNotRead):
        pass
    return costs.get(endpoint_for(request), fallback)


def retry_safe(request: httpx.Request) -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    if request.method != "POST":
        return False
    try:
        payload = json.loads(request.content)
        rows = payload if isinstance(payload, list) else [payload]
        return bool(rows) and all(isinstance(row, dict) and row.get("jsonrpc") == "2.0" and row.get("method") in RPC_READS for row in rows)
    except (ValueError, httpx.RequestNotRead):
        return False


def retry_after(value: str | None, now: float) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            seconds = date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp() - now
        except (ValueError, OverflowError, TypeError):
            return None
    return min(604800.0, max(0.0, seconds)) if math.isfinite(seconds) else None


class _SafeHttpLog(logging.Filter):
    def filter(self, record):
        if record.name == "httpx" or record.name == "httpcore" or record.name.startswith("httpcore."):
            record.msg, record.args, record.exc_info, record.exc_text = "External HTTP transport event (details omitted)", (), None, None
        return True


def _protect_http_logs():
    factory = logging.getLogRecordFactory()
    if not getattr(factory, "_steuerreport_redacted", False):
        def safe_record(*args, **kwargs):
            record = factory(*args, **kwargs)
            _SafeHttpLog().filter(record)
            return record
        safe_record._steuerreport_redacted = True
        logging.setLogRecordFactory(safe_record)
    # httpx can otherwise log signed URLs. No request/response bodies are logged here.
    for name in ["httpx", "httpcore", *logging.Logger.manager.loggerDict]:
        if name == "httpx" or name == "httpcore" or name.startswith("httpcore."):
            logger = logging.getLogger(name)
            if not any(isinstance(item, _SafeHttpLog) for item in logger.filters):
                logger.addFilter(_SafeHttpLog())
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class LimitedTransport(httpx.BaseTransport):
    def __init__(self, inner=None, *, limiter=None, provider=None, clock=time.time, monotonic=time.monotonic):
        self.inner = inner if inner is not None else httpx.HTTPTransport(retries=0, trust_env=False)
        self.limiter = limiter
        self.provider = provider
        self.clock, self.monotonic = clock, monotonic

    def handle_request(self, request):
        limiter = self.limiter or RequestLimiter()
        scope = _scope.get()
        provider = provider_for(request, self.provider or scope.provider)
        groups = list(scope.groups)
        profile = limiter.profile(provider, groups=groups)
        deadline = self.monotonic() + profile.job_deadline_seconds
        if scope.budget is not None:
            with scope.budget.lock:
                scoped = scope.budget.started_monotonic + profile.job_deadline_seconds
                scope.budget.deadline_monotonic = min(scoped, scope.budget.deadline_monotonic) if scope.budget.deadline_monotonic is not None else scoped
                deadline = min(deadline, scope.budget.deadline_monotonic)
        safe = retry_safe(request)
        costs = getattr(limiter.read_config(), "endpoint_costs", {}).get(provider, {})
        cost = request_cost(request, costs)
        attempt = 0
        while True:
            if scope.cancel is not None and scope.cancel.is_set():
                raise RequestCancelled("request_cancelled")
            if self.monotonic() >= deadline:
                raise RequestDeadlineExceeded("request_deadline_exceeded")
            response = None
            with limiter.acquire(provider, cost=cost, groups=groups, cancel=scope.cancel, deadline=deadline) as lease:
                # Sign only after waiting. Every retry obtains a fresh timestamp/signature.
                signer = _signer.get()
                def prepare():
                    refresh = getattr(scope.cancel, "refresh", None)
                    if refresh is not None:
                        refresh()
                    if scope.cancel is not None and scope.cancel.is_set():
                        raise RequestCancelled("request_cancelled")
                    if signer is not None:
                        signer(request)
                lease.start(prepare=prepare)
                if self.monotonic() >= deadline:
                    raise RequestDeadlineExceeded("request_deadline_exceeded")
                if scope.cancel is not None and scope.cancel.is_set():
                    raise RequestCancelled("request_cancelled")
                previous = request.extensions.get("timeout", {})
                request.extensions["timeout"] = {name: min(previous[name], lease.timeout_seconds) if previous.get(name) is not None else lease.timeout_seconds for name in ("connect", "read", "write", "pool")}
                try:
                    response = self.inner.handle_request(request)
                    wait = self._observe_headers(limiter, provider, response, groups, profile)
                    chunks, size = [], 0
                    body = [response.content] if response.is_stream_consumed else response.iter_bytes()
                    for chunk in body:
                        if scope.cancel is not None and scope.cancel.is_set():
                            raise RequestCancelled("request_cancelled")
                        if self.monotonic() >= deadline:
                            raise RequestDeadlineExceeded("request_deadline_exceeded")
                        size += len(chunk)
                        if size > 64 * 1024 * 1024:
                            raise httpx.TransportError("provider_response_too_large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                except httpx.TimeoutException:
                    raise httpx.TimeoutException("provider_timeout", request=httpx.Request(request.method, "https://provider.invalid/")) from None
                except httpx.HTTPError:
                    raise httpx.TransportError("provider_transport_failed", request=httpx.Request(request.method, "https://provider.invalid/")) from None
                finally:
                    if response is not None:
                        response.close()
                # Never retain signed URLs or authorization headers in error objects.
                clean_request = httpx.Request(request.method, request.url.copy_with(query=None))
                if provider != "legal":
                    clean_request = httpx.Request(request.method, f"{request.url.scheme}://{request.url.host}/")
                headers = dict(response.headers)
                headers.pop("content-encoding", None)
                headers.pop("content-length", None)
                result = httpx.Response(response.status_code, headers=headers, content=content,
                                        extensions=response.extensions, request=clean_request)
                if not safe or result.status_code not in {429, 502, 503, 504} or attempt >= profile.max_retries:
                    return result
                attempt += 1
                delay = limiter.retry_delay(provider, attempt, retryable=True, idempotent=True, retry_after=wait, groups=groups)
                limiter.pause(provider, max(delay, 0.001), groups=groups)

    def _observe_headers(self, limiter, provider, result, groups, profile):
        wait = retry_after(result.headers.get("retry-after"), self.clock())
        observation = {}
        used = result.headers.get("x-mbx-used-weight-1m")
        if used and used.isdigit():
            observation["used_weight_1m"] = int(used)
        # Jupiter documents signed remaining counts and an absolute Unix reset.
        if provider == "jupiter" and result.status_code in {200, 429}:
            remaining = result.headers.get("x-ratelimit-remaining", "")
            reset = result.headers.get("x-ratelimit-reset", "")
            try:
                left, reset_at = int(remaining), float(reset)
                if math.isfinite(reset_at) and reset_at >= 0:
                    observation.update(remaining_requests=left, reset_at=reset_at)
                    if left <= 0 and reset_at > self.clock():
                        wait = max(wait or 0, min(reset_at - self.clock(), 604800))
                        limiter.pause(provider, max(wait, 0.001), groups=groups)
            except ValueError:
                pass
        if result.status_code in {429, 418}:
            observation["rate_limited"] = True
            limiter.pause(provider, max(wait or profile.backoff_base_seconds, 0.001), groups=groups)
        if observation and hasattr(limiter, "observe"):
            limiter.observe(provider, **observation)
        return wait

    def close(self):
        self.inner.close()


def _clean_request(request, provider):
    url = request.url.copy_with(query=None) if provider == "legal" else httpx.URL(f"{request.url.scheme}://{request.url.host}/")
    return httpx.Request(request.method, url)


class BudgetHttpClient(httpx.Client):
    def _build_redirect_request(self, request, response):
        target = super()._build_redirect_request(request, response)
        sensitive_headers = {"authorization", "token", "x-api-key", "api-key", "x-mbx-apikey", "access-key", "access-passphrase", "pionex-key"}
        sensitive_query = {"api-key", "api_key", "apikey", "key", "token", "access_token", "signature"}
        provider = provider_for(request, getattr(self, "budget_provider", None) or _scope.get().provider)
        protected = bool(sensitive_headers.intersection(request.headers) or sensitive_query.intersection(request.url.params)) or provider in {"alchemy", "helius", "solana_rpc", "ai_cloud", "ai_local", "ai_openrouter"}
        if protected and (request.url.scheme, request.url.host, request.url.port) != (target.url.scheme, target.url.host, target.url.port):
            target.extensions["steuerreport_redirect_blocked"] = True
        return target

    def _send_single_request(self, request):
        if request.extensions.get("steuerreport_redirect_blocked"):
            raise httpx.TransportError("provider_authenticated_redirect_blocked", request=httpx.Request(request.method, "https://provider.invalid/"))
        return super()._send_single_request(request)

    def send(self, request, **kwargs):
        try:
            response = super().send(request, **kwargs)
        except httpx.TimeoutException:
            raise httpx.TimeoutException("provider_timeout", request=httpx.Request(request.method, "https://provider.invalid/")) from None
        except httpx.HTTPError:
            raise httpx.TransportError("provider_transport_failed", request=httpx.Request(request.method, "https://provider.invalid/")) from None
        # httpx assigns the original request after the transport returns. Clean it
        # at the public boundary too, including redirect history and error objects.
        for item in [*response.history, response]:
            provider = provider_for(item.request, getattr(self, "budget_provider", None) or _scope.get().provider)
            item.request = _clean_request(item.request, provider)
        return response


def managed_client(*, transport=None, limiter=None, provider=None, clock=time.time, monotonic=time.monotonic, **kwargs):
    _protect_http_logs()
    kwargs.setdefault("trust_env", False)
    # Redirect hops and pagination each enter handle_request and reserve their own budget.
    client = BudgetHttpClient(transport=LimitedTransport(transport, limiter=limiter, provider=provider, clock=clock, monotonic=monotonic), **kwargs)
    client.budget_provider = provider
    return client


def managed_post(url, **kwargs):
    timeout = kwargs.pop("timeout", 30)
    with managed_client(timeout=timeout) as client:
        return client.post(url, **kwargs)


class BufferedHttpResponse(io.BytesIO):
    def __init__(self, response):
        super().__init__(response.content)
        self.status, self.headers, self.url = response.status_code, response.headers, str(response.url)

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url


def managed_urlopen(request, timeout=30):
    """Compatibility for existing CLI readers; internal API relays are not provider calls."""
    _protect_http_logs()
    url = httpx.URL(request if isinstance(request, str) else request.full_url)
    method = "GET" if isinstance(request, str) else request.get_method()
    data = None if isinstance(request, str) else request.data
    headers = {} if isinstance(request, str) else dict(request.header_items())
    try:
        private = ipaddress.ip_address(url.host).is_private
    except ValueError:
        private = url.host == "localhost" or url.host.endswith((".local", ".home"))
    ai = url.path.endswith(("/chat/completions", "/api/generate", "/api/chat"))
    try:
        payload = json.loads(data) if data else None
        rpc_items = payload if isinstance(payload, list) else [payload]
        rpc = any(isinstance(item, dict) and item.get("jsonrpc") == "2.0" for item in rpc_items)
    except (ValueError, TypeError, UnicodeDecodeError):
        rpc = False
    internal = private and url.path.startswith("/api/v1/") and not ai and not rpc
    provider = ("ai_local" if private else "ai_cloud") if ai else None
    # Holding a provider lease for an internal relay would deadlock its downstream
    # provider call. The server enforces that call; the relay is never retried here.
    factory = httpx.Client if internal else managed_client
    options = {} if internal else {"provider": provider}
    with factory(timeout=timeout, follow_redirects=not internal, trust_env=False, **options) as client:
        response = client.request(method, str(url), content=data, headers=headers)
    if response.status_code >= 400:
        raise urllib.error.HTTPError(str(response.url), response.status_code, "provider_http_error", response.headers, io.BytesIO())
    return BufferedHttpResponse(response)
