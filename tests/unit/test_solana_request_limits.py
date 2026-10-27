"""Solana-Limits mit kontrollierter Uhr, privatem Testzustand und HTTP-Mocks."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import multiprocessing

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from steuerreport_v2.api import request_limits as limits_api
from steuerreport_v2.contracts.request_limits import ProviderCeiling, RequestLimitProfile, RequestLimitsConfig
from steuerreport_v2.domain.external_http import managed_client, provider_for, request_signer
from steuerreport_v2.domain.request_limits import (
    ActiveLeaseConflict, RequestDeadlineExceeded, RequestLimitError, RequestLimiter,
    RevisionConflict, SOLANA_HISTORY_ENDPOINTS, SOLANA_HISTORY_PROFILE,
    SOLANA_PUBLIC_FREE, endpoint_group,
)


PREFIX = "/api/v1/admin/request-limits"
TX = "rpc_gettransaction"
BALANCE = "rpc_getbalance"


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.now += seconds


def limiter_at(root, clock):
    return RequestLimiter(state_root=root, clock=clock, monotonic=clock,
                          sleep=clock.sleep, random=lambda: 0.0)


def fast(**changes):
    return RequestLimitProfile(**{
        "requests_per_second": 100, "requests_per_minute": 1000,
        "burst": 1, "max_concurrency": 10, **changes,
    })


def update(limiter, **changes):
    config = limiter.read_config()
    return limiter.write_config(config.model_copy(update=changes), expected_revision=config.revision)


def start(limiter, endpoint=TX):
    with limiter.acquire("solana_rpc", endpoint=endpoint) as lease:
        lease.start()


def read_state(limiter):
    return json.loads((limiter.directory / "coordinator.json").read_text())


def group_status(limiter, group):
    return next(item for item in limiter.status().groups if item.group == group)


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    limiter = limiter_at(tmp_path / "runtime", clock)
    update(limiter, default_profile=fast())
    return clock, limiter


@pytest.fixture
def api(tmp_path, monkeypatch):
    root, clock = tmp_path / "runtime", Clock()
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(root))
    monkeypatch.setattr(limits_api, "RequestLimiter", lambda: limiter_at(root, clock))
    app = FastAPI()
    app.include_router(limits_api.build_request_limits_router())
    return TestClient(app), root, clock, app


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "30", 100001])
def test_ten_second_profile_and_ceiling_are_strict(value):
    with pytest.raises(ValidationError):
        RequestLimitProfile(requests_per_10_seconds=value)
    with pytest.raises(ValidationError):
        ProviderCeiling(requests_per_10_seconds=value, source_url="https://solana.com/docs/references/clusters",
                        checked_date="2026-10-27", scope="ip", plan="Public Free")


def test_optional_ten_second_dimension_and_burst_validation():
    assert RequestLimitProfile().requests_per_10_seconds is None
    ceiling = ProviderCeiling(requests_per_10_seconds=40, source_url="https://solana.com/docs/references/clusters",
                              checked_date="2026-10-27", scope="ip", plan="Public Free")
    assert ceiling.requests_per_10_seconds == 40
    with pytest.raises(ValidationError):
        fast(burst=3, requests_per_10_seconds=2)
    with pytest.raises(ValidationError):
        RequestLimitsConfig(endpoint_profiles={"solana_rpc": {"bad/key": fast()}})
    with pytest.raises(ValidationError):
        RequestLimitsConfig(endpoint_profiles={"solana_rpc": {f"method{i}": fast() for i in range(1001)}})
    with pytest.raises(ValidationError):
        RequestLimitsConfig(group_profiles={endpoint_group("solana_rpc", TX): fast()})


def test_rolling_ten_second_exact_boundary_and_status(setup):
    clock, limiter = setup
    update(limiter, default_profile=fast(requests_per_10_seconds=3))
    for offset in (0, 1, 2):
        clock.now = 1000.0 + offset
        start(limiter)
    clock.now = 1009.999
    status = group_status(limiter, "ip:global")
    assert status.requests_last_10_seconds == 3
    assert "rolling_10_seconds" in status.blocking_reasons
    assert status.next_start_at == 1010.0
    clock.now = 1010.0
    assert group_status(limiter, "ip:global").requests_last_10_seconds == 2
    start(limiter)
    assert clock.now == 1010.0
    assert group_status(limiter, "ip:global").requests_last_minute == 4


def test_ceiling_ten_second_window_is_additional(setup):
    clock, limiter = setup
    ceiling = ProviderCeiling(requests_per_10_seconds=1, source_url="https://solana.com/docs/references/clusters",
                              checked_date="2026-10-27", scope="ip", plan="Public Free")
    update(limiter, provider_ceilings={"solana_rpc": ceiling})
    start(limiter)
    start(limiter)
    assert clock.now == pytest.approx(1010.0)
    assert limiter.profile("solana_rpc", endpoint=TX).requests_per_10_seconds == 1


def test_endpoint_budget_is_independent_and_cannot_partially_reserve(setup):
    clock, limiter = setup
    update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(requests_per_10_seconds=1)}})
    start(limiter)
    clock.now = 1001.0
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("solana_rpc", endpoint=TX, deadline=1001.5)
    assert group_status(limiter, "provider:solana_rpc").requests_last_minute == 1
    assert group_status(limiter, "ip:global").requests_last_minute == 1
    start(limiter, BALANCE)
    assert group_status(limiter, "provider:solana_rpc").requests_last_minute == 2
    method = group_status(limiter, endpoint_group("solana_rpc", TX))
    assert method.requests_last_minute == 1
    assert (method.provider, method.endpoint) == ("solana_rpc", TX)
    assert not read_state(limiter)["active"] and not read_state(limiter)["waiters"]


def test_new_method_budget_inherits_history_and_retains_all_sixty_seconds(setup):
    clock, limiter = setup
    start(limiter)
    clock.now = 1001.0
    start(limiter, BALANCE)
    clock.now = 1015.0
    update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(requests_per_minute=1)}})
    method = group_status(limiter, endpoint_group("solana_rpc", TX))
    assert method.requests_last_10_seconds == 0 and method.requests_last_minute == 1
    assert "rolling_minute" in method.blocking_reasons
    start(limiter)
    assert clock.now == pytest.approx(1060.0)


def test_removed_and_readded_method_inherits_intervening_starts(setup):
    clock, limiter = setup
    profiles = {"solana_rpc": {TX: fast(requests_per_10_seconds=2)}}
    update(limiter, endpoint_profiles=profiles)
    start(limiter)
    clock.now = 1001.0
    update(limiter, endpoint_profiles={})
    start(limiter)
    clock.now = 1002.0
    update(limiter, endpoint_profiles=profiles)
    assert group_status(limiter, endpoint_group("solana_rpc", TX)).requests_last_minute == 2
    start(limiter)
    assert clock.now == pytest.approx(1010.0)


def test_new_group_attaches_to_already_acquired_and_running_leases(setup):
    clock, limiter = setup
    lease = limiter.acquire("solana_rpc", endpoint=TX)
    try:
        update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(max_concurrency=1)}})
        group = endpoint_group("solana_rpc", TX)
        assert group in read_state(limiter)["active"][lease.lease_id]["groups"]
        assert group_status(limiter, group).in_flight == 1
        with pytest.raises(RequestDeadlineExceeded):
            limiter.acquire("solana_rpc", endpoint=TX, deadline=clock.now + 0.1)
        lease.start()
        assert group in lease.groups
        update(limiter, endpoint_profiles={})
        update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(max_concurrency=1)}})
        assert group_status(limiter, group).in_flight == 1
        assert group_status(limiter, group).requests_last_minute == 1
    finally:
        lease.release()


@pytest.mark.parametrize("target", ["new_endpoint", "readded_endpoint", "endpoint_shrink", "global", "provider", "default"])
def test_two_acquired_leases_reject_new_or_stricter_concurrency_without_any_write(setup, target):
    clock, limiter = setup
    if target in {"readded_endpoint", "endpoint_shrink"}:
        update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(max_concurrency=2)}})
    leases = [limiter.acquire("solana_rpc", endpoint=TX) for _ in range(2)]
    try:
        if target == "readded_endpoint":
            update(limiter, endpoint_profiles={})
        changes = {"endpoint_profiles": {"solana_rpc": {TX: fast(max_concurrency=1)}}}
        if target in {"global", "provider"}:
            group = "ip:global" if target == "global" else "provider:solana_rpc"
            changes = {"group_profiles": {group: fast(max_concurrency=1)}}
        elif target == "default":
            changes = {"default_profile": fast(max_concurrency=1)}
        path = limiter.directory / "coordinator.json"
        before = path.read_bytes()
        now = clock.now
        with pytest.raises(ActiveLeaseConflict, match="^request_limits_active_leases_conflict$"):
            update(limiter, **changes)
        assert path.read_bytes() == before and clock.now == now
        assert not any(lease._started for lease in leases)
        assert set(read_state(limiter)["active"]) == {lease.lease_id for lease in leases}
        leases[0].release()
        update(limiter, **changes)
        leases[1].start()
    finally:
        for lease in leases:
            lease.release()


def test_new_binding_allows_exact_capacity_and_unrelated_updates_with_active_leases(setup):
    _clock, limiter = setup
    update(limiter, provider_groups={"solana_rpc": ["provider:custom.shared"]})
    leases = [limiter.acquire("solana_rpc", endpoint=TX) for _ in range(2)]
    try:
        update(limiter, group_profiles={"provider:binance": fast(max_concurrency=1)})
        update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(max_concurrency=2)}})
        for lease in leases:
            lease.start()
        assert group_status(limiter, endpoint_group("solana_rpc", TX)).in_flight == 2
    finally:
        for lease in leases:
            lease.release()


@pytest.mark.parametrize("preset", [False, True])
def test_api_active_lease_conflict_is_safe_409_and_preserves_entire_document(api, preset):
    client, root, clock, _app = api
    limiter = limiter_at(root, clock)
    config = update(limiter, default_profile=fast())
    leases = [limiter.acquire("solana_rpc", endpoint=TX) for _ in range(2)]
    try:
        path = limiter.directory / "coordinator.json"
        before = path.read_bytes()
        if preset:
            response = client.post(PREFIX + "/presets/solana_public_free", json={
                "confirmation": True, "expected_revision": config.revision,
            })
        else:
            proposed = config.model_copy(update={"endpoint_profiles": {"solana_rpc": {TX: fast(max_concurrency=1)}}})
            response = client.put(PREFIX, json={"config": proposed.model_dump(), "expected_revision": config.revision})
        assert response.status_code == 409
        assert response.json() == {"detail": "request_limits_active_leases_conflict"}
        assert path.read_bytes() == before
    finally:
        for lease in leases:
            lease.release()


def test_dispatch_rechecks_new_method_budget_after_prepare(setup):
    clock, limiter = setup
    start(limiter)
    clock.now = 1001.0
    calls = []
    with limiter.acquire("solana_rpc", endpoint=TX) as lease:
        def prepare():
            calls.append(clock.now)
            if len(calls) == 1:
                update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(requests_per_10_seconds=1)}})
        lease.start(prepare)
    assert clock.now == pytest.approx(1010.0)
    assert len(calls) >= 2
    assert group_status(limiter, endpoint_group("solana_rpc", TX)).requests_last_10_seconds == 1


def test_inherited_history_legacy_unknown_method_and_pause(setup):
    clock, limiter = setup
    with limiter.acquire("solana_rpc") as lease:
        lease.start()
    limiter.pause("solana_rpc", 5.0)
    update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(requests_per_10_seconds=1), BALANCE: fast()}})
    for endpoint in (TX, BALANCE):
        method = group_status(limiter, endpoint_group("solana_rpc", endpoint))
        assert method.requests_last_minute == 1 and method.paused_until == 1005.0
    start(limiter)
    assert clock.now == pytest.approx(1010.0)


def _shared_worker(root, queue):
    try:
        clock = Clock()
        limiter = limiter_at(root, clock)
        start(limiter)
        queue.put(("ok", clock.now))
    except Exception as exc:
        queue.put(("error", type(exc).__name__))


def test_endpoint_budget_is_shared_across_processes_and_restart(setup):
    clock, limiter = setup
    update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(requests_per_10_seconds=1)}})
    start(limiter)
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    worker = context.Process(target=_shared_worker, args=(limiter.directory.parent, queue))
    worker.start()
    try:
        result = queue.get(timeout=15)
        worker.join(timeout=15)
        assert worker.exitcode == 0 and result == ("ok", pytest.approx(1010.0))
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        queue.close()
    restarted = limiter_at(limiter.directory.parent, clock)
    assert group_status(restarted, endpoint_group("solana_rpc", TX)).requests_last_minute == 2


def test_mock_rpc_retries_reenter_method_ip_and_provider_budgets(setup):
    clock, limiter = setup
    update(limiter, endpoint_profiles={"solana_rpc": {TX: fast(requests_per_10_seconds=1)}})
    calls = []
    def handler(request):
        calls.append(clock.now)
        return httpx.Response(429 if len(calls) == 1 else 200,
                              headers={"Retry-After": "2"}, json={"result": None})
    with managed_client(transport=httpx.MockTransport(handler), limiter=limiter,
                        clock=clock, monotonic=clock) as client:
        assert client.post("https://api.mainnet.solana.com/?api-key=SECRET", json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": ["SECRET-WALLET"],
        }).status_code == 200
    assert calls == [1000.0, pytest.approx(1010.0)]
    for group in ("provider:solana_rpc", "ip:global", endpoint_group("solana_rpc", TX)):
        assert group_status(limiter, group).requests_last_minute == 2
    assert "SECRET" not in json.dumps(read_state(limiter))


@pytest.mark.parametrize("activate_during_prepare", [False, True])
@pytest.mark.parametrize("provider", [None, "solana_rpc"])
def test_rpc_arrays_fail_closed_even_if_method_budgets_added_during_dispatch(setup, activate_during_prepare, provider):
    clock, limiter = setup
    if not activate_during_prepare:
        update(limiter, endpoint_profiles={"solana_rpc": {TX: fast()}})
    def prepare(request):
        if activate_during_prepare:
            update(limiter, endpoint_profiles={"solana_rpc": {TX: fast()}})
    with request_signer(prepare), managed_client(
        transport=httpx.MockTransport(lambda request: pytest.fail("Batch reached HTTP")),
        limiter=limiter, provider=provider, clock=clock, monotonic=clock,
    ) as client:
        with pytest.raises(RequestLimitError, match="endpoint_batch_unsupported"):
            client.post("https://rpc.invalid/", json=[{"jsonrpc": "2.0", "method": "getTransaction"}] * 2)
    assert not read_state(limiter)["active"]


def test_provider_detection_and_private_rpc_override_remain_unchanged():
    request = httpx.Request("POST", "https://unknown.invalid/private/SECRET", json={"jsonrpc": "2.0", "method": "getTransaction"})
    assert provider_for(request) == "solana_rpc"
    assert provider_for(request, "helius") == "helius"
    assert provider_for(httpx.Request("POST", "https://api.mainnet.solana.com/")) == "solana_rpc"
    assert provider_for(httpx.Request("GET", "https://unknown.invalid/")) == "other"


def test_real_history_collector_uses_all_three_method_budgets_without_db_writes(setup, tmp_path, monkeypatch):
    from steuerreport_v2.db.duckdb_store import DuckDbStore
    from steuerreport_v2.domain import portfolio
    from steuerreport_v2.domain.history_solana import SolanaHistoryCollector
    from steuerreport_v2.domain.history_types import HistoryOptions, HistoryTarget

    clock, limiter = setup
    config = limiter.read_config()
    limiter.apply_solana_public_free(expected_revision=config.revision)
    wallet, signature = "1" * 32, "1" * 64
    calls = []
    def handler(request):
        method = json.loads(request.content)["method"]
        calls.append((method, clock.now))
        if method == "getTokenAccountsByOwner":
            result = {"value": []}
        elif method == "getSignaturesForAddress":
            result = [{"signature": signature, "blockTime": 1735689600}]
        else:
            assert method == "getTransaction"
            result = {
                "blockTime": 1735689600, "slot": 1,
                "transaction": {"message": {"accountKeys": [wallet]}},
                "meta": {"err": None, "fee": 5000, "preBalances": [100000],
                         "postBalances": [95000], "preTokenBalances": [], "postTokenBalances": []},
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})
    monkeypatch.setattr(portfolio, "managed_client", lambda **kwargs: managed_client(
        transport=httpx.MockTransport(handler), limiter=limiter, clock=clock, monotonic=clock, **kwargs,
    ))
    store = DuckDbStore(tmp_path / "collector.duckdb")
    collector = SolanaHistoryCollector(store, HistoryTarget(
        source_ref="wallet:synthetic", label="Synthetic", provider="solana_rpc",
        account="synthetic", wallet_address=wallet,
    ), HistoryOptions(start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                      end=datetime(2026, 1, 1, tzinfo=timezone.utc), public_rpc_only=True))
    page = collector.fetch_page({}, lambda: None)
    assert len(page.records) == 1 and page.requests == 4
    assert [method for method, _ in calls] == [
        "getTokenAccountsByOwner", "getTokenAccountsByOwner", "getSignaturesForAddress", "getTransaction",
    ]
    assert calls[-1][1] - calls[0][1] >= 1.0
    for endpoint, count in ((TX, 1), ("rpc_getsignaturesforaddress", 1), ("rpc_gettokenaccountsbyowner", 2)):
        assert group_status(limiter, endpoint_group("solana_rpc", endpoint)).requests_last_minute == count
    assert group_status(limiter, "ip:global").requests_last_minute == 4
    assert store.list_canonical_events() == [] and store.list_admin_settings() == []


def test_presets_get_is_read_only_and_apply_is_explicit_preserving_other_limits(api):
    client, root, clock, _app = api
    data = client.get(PREFIX + "/presets").json()["data"]
    preset = data["presets"][0]
    assert preset["label"] == "Solana Public RPC - Free"
    assert data["current_revision"] == preset["current_revision"] == 0
    assert preset["conflicts"] == [] and preset["data_budget_enforced"] is False
    assert set(preset["endpoint_profiles"]["solana_rpc"]) == set(SOLANA_HISTORY_ENDPOINTS)
    assert not (root / "request_limits").exists()
    limiter = limiter_at(root, clock)
    update(limiter, group_profiles={"provider:binance": fast()},
           endpoint_profiles={"solana_rpc": {BALANCE: fast()}, "helius": {TX: fast()}})
    response = client.post(PREFIX + "/presets/solana_public_free", json={"confirmation": True, "expected_revision": 1})
    assert response.status_code == 200
    config = RequestLimitsConfig.model_validate(response.json()["data"])
    assert config.revision == 2 and config.default_profile == RequestLimitProfile()
    assert config.group_profiles["provider:binance"] == fast()
    assert config.group_profiles["provider:solana_rpc"] == config.group_profiles["ip:global"] == SOLANA_PUBLIC_FREE
    assert config.endpoint_profiles["helius"][TX] == config.endpoint_profiles["solana_rpc"][BALANCE] == fast()
    for endpoint in SOLANA_HISTORY_ENDPOINTS:
        assert config.endpoint_profiles["solana_rpc"][endpoint] == SOLANA_HISTORY_PROFILE
    assert limiter.profile("solana_rpc", endpoint=TX).requests_per_minute == 180
    assert limiter.profile("binance").requests_per_second == 3


@pytest.mark.parametrize("payload", [
    {"confirmation": False, "expected_revision": 0},
    {"confirmation": 1, "expected_revision": 0},
    {"confirmation": "true", "expected_revision": 0},
    {"confirmation": True, "expected_revision": True},
    {"confirmation": True, "expected_revision": -1},
    {"expected_revision": 0},
    {"confirmation": True, "expected_revision": 0, "secret": "NEVER-ECHO"},
])
def test_preset_requires_exact_confirmation_without_state_creation(api, payload):
    client, root, _clock, _app = api
    response = client.post(PREFIX + "/presets/solana_public_free", json=payload)
    assert response.status_code == 422 and "NEVER-ECHO" not in response.text
    assert not (root / "request_limits").exists()


def test_preset_revision_and_sandbox_fail_without_writes(api):
    client, root, _clock, app = api
    path = PREFIX + "/presets/solana_public_free"
    assert client.post(path, json={"confirmation": True, "expected_revision": 2}).status_code == 409
    assert not (root / "request_limits").exists()
    app.state.ux_sandbox = True
    assert client.post(path, json={"confirmation": True, "expected_revision": 0}).status_code == 403
    assert client.get(PREFIX + "/presets").status_code == 200
    assert not (root / "request_limits").exists()


@pytest.mark.parametrize("target", ["ip", "provider", "endpoint", "ceiling"])
def test_preset_conflicts_are_reported_and_never_partially_written(api, target):
    client, root, clock, _app = api
    limiter = limiter_at(root, clock)
    changes = {"ip": {"group_profiles": {"ip:global": fast()}},
               "provider": {"group_profiles": {"provider:solana_rpc": fast()}},
               "endpoint": {"endpoint_profiles": {"solana_rpc": {TX: fast()}}},
               "ceiling": {"provider_ceilings": {"solana_rpc": ProviderCeiling(
                   requests_per_10_seconds=20, source_url="https://solana.com/docs/references/clusters",
                   checked_date="2026-10-27", scope="ip", plan="Synthetic")}}}[target]
    update(limiter, **changes)
    before = (limiter.directory / "coordinator.json").read_bytes()
    conflicts = client.get(PREFIX + "/presets").json()["data"]["presets"][0]["conflicts"]
    response = client.post(PREFIX + "/presets/solana_public_free", json={"confirmation": True, "expected_revision": 1})
    assert response.status_code == 409
    assert response.json() == {"detail": "request_limits_preset_conflict", "conflicts": conflicts}
    assert conflicts and (limiter.directory / "coordinator.json").read_bytes() == before


def test_preset_cas_rejects_intervening_config_write(setup, monkeypatch):
    _clock, limiter = setup
    original = limiter.write_config
    revision = limiter.read_config().revision
    def concurrent(config, *, expected_revision):
        original(limiter.read_config(), expected_revision=expected_revision)
        return original(config, expected_revision=expected_revision)
    monkeypatch.setattr(limiter, "write_config", concurrent)
    with pytest.raises(RevisionConflict):
        limiter.apply_solana_public_free(expected_revision=revision)
    assert not limiter.read_config().endpoint_profiles


def test_endpoint_ids_and_map_shape_are_validated_by_api(api):
    client, root, _clock, _app = api
    config = client.get(PREFIX).json()["data"]
    config["endpoint_profiles"] = {"solana_rpc": {"rpc_SECRET": fast().model_dump()}}
    response = client.put(PREFIX, json={"config": config, "expected_revision": 0})
    assert response.status_code == 422 and "SECRET" not in response.text
    assert not (root / "request_limits").exists()
    config["endpoint_profiles"] = {"solana_rpc": {TX: fast().model_dump()}}
    assert client.put(PREFIX, json={"config": config, "expected_revision": 0}).status_code == 200
    assert client.get(PREFIX).json()["data"]["endpoint_profiles"]["solana_rpc"][TX]["requests_per_10_seconds"] is None


def test_legacy_json_api_save_restart_preserves_starts_pause_and_active_leases(api):
    client, root, clock, _app = api
    limiter = limiter_at(root, clock)
    lease = limiter.acquire("solana_rpc")
    lease.start()
    limiter.pause("solana_rpc", 20.0)
    path = limiter.directory / "coordinator.json"
    legacy = json.loads(path.read_text())
    legacy["config"].pop("endpoint_profiles")
    legacy["config"]["default_profile"].pop("requests_per_10_seconds")
    for bucket in legacy["buckets"].values():
        for row in bucket["starts"]:
            row.pop("endpoint")
    for active in legacy["active"].values():
        active.pop("endpoint")
    path.write_text(json.dumps(legacy))
    try:
        config = client.get(PREFIX).json()["data"]
        assert config["endpoint_profiles"] == {} and config["default_profile"]["requests_per_10_seconds"] is None
        config["endpoint_profiles"] = {"solana_rpc": {TX: fast().model_dump()}}
        assert client.put(PREFIX, json={"config": config, "expected_revision": 0}).status_code == 200
        restart = limiter_at(root, clock)
        state = read_state(restart)
        assert state["config"]["revision"] == 1
        assert lease.lease_id in state["active"]
        for group in ("provider:solana_rpc", "ip:global", endpoint_group("solana_rpc", TX)):
            status = group_status(restart, group)
            assert status.requests_last_minute == status.in_flight == 1
            assert status.paused_until == 1020.0
    finally:
        lease.release()
