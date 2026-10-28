"""Produktiver Defaultpfad nutzt denselben Limiter wie alle Connectoren."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_http import managed_client, outbound_scope
from steuerreport_v2.domain.request_limits import RequestLimiter, RequestLimitError
from steuerreport_v2.domain import updates


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.mark.parametrize("rate_limited", [False, True])
@pytest.mark.parametrize("uptime", [10.0, 1000.0])
def test_default_path_pagination_and_429_reserve_shared_budget(tmp_path, monkeypatch, rate_limited, uptime):
    clock = Clock(uptime)
    limiter = RequestLimiter(state_root=tmp_path, clock=clock, monotonic=clock, sleep=clock.sleep, random=lambda: 0)
    calls = []

    def handler(request):
        calls.append((clock.now, request.url.params["page"]))
        assert request.url.host == "api.github.com" and "authorization" not in request.headers
        if rate_limited:
            return httpx.Response(429, headers={"Retry-After": "120"})
        headers = {"Link": f'<{updates.RELEASE_API}?per_page=100&page=2>; rel="next"'} if len(calls) == 1 else {}
        return httpx.Response(200, json=[], headers=headers)

    def factory(**kwargs):
        assert kwargs["provider"] == "github_updates"
        assert kwargs["max_response_bytes"] == updates.MAX_PAGE_BYTES
        assert kwargs["max_retries"] == 0
        kwargs["limiter"] = limiter
        return managed_client(transport=httpx.MockTransport(handler), clock=clock, monotonic=clock, **kwargs)

    def scope(**kwargs):
        # Scope und Transport muessen dieselbe Testuhr verwenden, auch auf jungen VMs.
        assert kwargs["deadline"] == clock.now + 45
        return outbound_scope(clock=clock, monotonic=clock, **kwargs)

    monkeypatch.setattr(updates, "managed_client", factory)
    monkeypatch.setattr(updates, "outbound_scope", scope)
    monkeypatch.setattr(updates, "time", SimpleNamespace(time=clock))
    service = updates.UpdateService(DuckDbStore(tmp_path / "synthetic.duckdb"), state_dir=tmp_path,
                                    installed_version="0.2.0rc32", clock=lambda: NOW)
    result = service.check()
    count = 1 if rate_limited else 2
    assert len(calls) == count
    assert result.status == ("unavailable" if rate_limited else "up_to_date")
    assert all(row.requests_last_minute == count for row in limiter.status().groups)
    assert {row.group for row in limiter.status().groups} >= {"ip:global", "provider:github_updates"}
    assert all(row.in_flight == 0 for row in limiter.status().groups)
    if rate_limited:
        assert (result.retry_at - NOW).total_seconds() == 120
    else:
        assert calls[1][0] - calls[0][0] >= 1


def test_coordinator_failure_is_fail_closed_without_secret_echo(tmp_path, monkeypatch):
    def fail(**kwargs):
        raise RequestLimitError("synthetic-sensitive-coordinator-detail")

    monkeypatch.setattr(updates, "RequestLimiter", fail)
    monkeypatch.setattr(updates, "managed_client", lambda **kwargs: pytest.fail("Limiter darf nicht umgangen werden"))
    service = updates.UpdateService(DuckDbStore(tmp_path / "synthetic.duckdb"), state_dir=tmp_path,
                                    installed_version="0.2.0rc32", clock=lambda: NOW)
    result = service.check()
    assert result.status == "unavailable"
    assert "synthetic-sensitive" not in result.model_dump_json()


def test_large_public_asset_metadata_fits_bounded_default_transport(tmp_path, monkeypatch):
    clock = Clock(10)
    limiter = RequestLimiter(state_root=tmp_path, clock=clock, monotonic=clock, sleep=clock.sleep, random=lambda: 0)
    payload = [{"id": 35, "tag_name": "v0.2.0rc35", "name": "Synthetischer Release",
                "draft": False, "prerelease": False, "published_at": "2026-10-27T12:00:00Z",
                "html_url": "https://github.com/zonfacter/steuerreport-v2-plan/releases/tag/v0.2.0rc35",
                "body": "Begrenzte Metadatenabfrage.",
                "assets": [{"id": n, "label": "x" * 1500} for n in range(400)]}]
    body = json.dumps(payload).encode()
    assert 512 * 1024 < len(body) < updates.MAX_PAGE_BYTES
    starts = []

    def handler(request):
        starts.append(request.url.host)
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})

    def factory(**kwargs):
        assert kwargs["max_response_bytes"] == 1024 * 1024
        assert kwargs["max_retries"] == 0
        kwargs["limiter"] = limiter
        return managed_client(transport=httpx.MockTransport(handler),
                              clock=clock, monotonic=clock, **kwargs)

    monkeypatch.setattr(updates, "managed_client", factory)
    monkeypatch.setattr(updates, "time", SimpleNamespace(time=clock))
    monkeypatch.setattr(updates, "outbound_scope", lambda **kwargs: outbound_scope(clock=clock, monotonic=clock, **kwargs))
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    service = updates.UpdateService(store, state_dir=tmp_path, installed_version="0.2.0rc34", clock=lambda: NOW)
    result = service.check()
    assert result.status == "update_available"
    assert "v0.2.0rc35" in result.model_dump_json()
    assert starts == ["api.github.com"]
    assert all(row.requests_last_minute == 1 and row.in_flight == 0 for row in limiter.status().groups)
    assert "assets" not in result.model_dump_json()
    assert updates.MAX_TOTAL_BYTES == 2 * 1024 * 1024
