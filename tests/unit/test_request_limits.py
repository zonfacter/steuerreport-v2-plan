"""Isolierte Limiter-Tests: keine HTTP-Aufrufe, keine produktiven Zustandsdaten."""
from dataclasses import dataclass
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
from threading import Event
import time

import httpx
from pydantic import ValidationError
import pytest

from steuerreport_v2.contracts.request_limits import ProviderCeiling, RequestLimitProfile, RequestLimitsConfig
from steuerreport_v2.domain.request_limits import (
    LimiterUnavailable, RequestCancelled, RequestCostExceeded, RequestDeadlineExceeded,
    RequestLimitError, RequestLimiter, RetryNotAllowed, RevisionConflict,
)
from steuerreport_v2.paths import PROJECT_ROOT


@dataclass
class Clock:
    elapsed: float = 0.0
    rollback: float = 0.0

    def wall(self):
        return 1_700_000_000.0 + self.elapsed - self.rollback

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        assert seconds > 0
        self.elapsed += seconds


@pytest.fixture
def clock():
    return Clock()


def limiter_at(root, clock, **kwargs):
    return RequestLimiter(state_root=root, clock=clock.wall, monotonic=clock.monotonic,
                          sleep=kwargs.pop("sleep", clock.sleep), random=lambda: 0.5, **kwargs)


@pytest.fixture
def limiter(tmp_path, clock):
    return limiter_at(tmp_path, clock)


def configure(limiter, **changes):
    config = limiter.read_config()
    profile = RequestLimitProfile(**changes)
    return limiter.write_config(config.model_copy(update={"default_profile": profile}), expected_revision=config.revision)


def state_file(limiter):
    return limiter.directory / "coordinator.json"


def state(limiter):
    return json.loads(state_file(limiter).read_text())


def groups(limiter):
    return {item.group: item for item in limiter.status().groups}


def test_defaults_private_persistent_and_no_manufacturer_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path))
    limiter = RequestLimiter()
    config = limiter.read_config()
    assert config.revision == 0 and config.scheduler_enabled is False
    assert config.default_profile == RequestLimitProfile()
    assert config.default_profile.requests_per_second == 1
    assert config.default_profile.requests_per_minute == 30
    assert config.default_profile.burst == config.default_profile.max_concurrency == 1
    assert config.default_profile.manufacturer_limit_verified is False
    assert not limiter.status().manufacturer_telemetry_available
    assert limiter.directory.stat().st_mode & 0o777 == 0o700
    assert state_file(limiter).stat().st_mode & 0o777 == 0o600
    assert RequestLimiter().read_config() == config


@pytest.mark.parametrize("change", [
    {"requests_per_second": 0}, {"requests_per_minute": -1}, {"burst": 0},
    {"max_concurrency": 0}, {"weighted_cost_per_minute": 0}, {"requests_per_second": True},
    {"requests_per_second": 1.5}, {"timeout_seconds": float("nan")},
    {"job_deadline_seconds": float("inf")}, {"timeout_seconds": 301.0},
    {"max_retries": -1}, {"max_retries": 11}, {"burst": 2},
    {"backoff_base_seconds": 31.0}, {"jitter_ratio": -0.1}, {"unknown": 1},
])
def test_invalid_profiles_are_rejected(change):
    with pytest.raises(ValidationError):
        RequestLimitProfile(**change)


def test_config_revision_restart_endpoint_costs_and_bindings(limiter, tmp_path, clock):
    original = limiter.read_config()
    config = RequestLimitsConfig(provider_groups={"binance": ["project:shared"]}, endpoint_costs={
        "binance": {"account": 20}, "solscan": {"default": 100}, "rpc": {"rpc:getTransaction": 10},
    })
    saved = limiter.write_config(config, expected_revision=0)
    restored = limiter_at(tmp_path, clock).read_config()
    assert restored == saved and restored.revision == 1
    assert restored.endpoint_costs["rpc"]["rpc:getTransaction"] == 10
    assert restored.endpoint_costs.get("unknown", {}).get("other", 1) == 1
    with pytest.raises(RevisionConflict):
        limiter.write_config(original, expected_revision=0)
    assert limiter.read_config() == saved
    with limiter.acquire("binance") as lease:
        assert lease.groups == ("ip:global", "project:shared", "provider:binance")


@pytest.mark.parametrize("costs", [
    {"rpc": {"https://example.test?api_key=x": 1}}, {"rpc": {"getTransaction": 0}},
    {"rpc": {"getTransaction": -1}}, {"rpc": {"getTransaction": True}},
    {"rpc": {"getTransaction": 1.5}}, {"rpc": {"x": "secret"}},
    {"rpc": {f"e{i}": 1 for i in range(1001)}},
])
def test_endpoint_costs_are_bounded_local_integer_units(costs):
    with pytest.raises(ValidationError):
        RequestLimitsConfig(endpoint_costs=costs)


def ceiling(**changes):
    # Nur kuenstliche Operatorvorgaben, keinerlei reale Herstellerzahlen.
    return ProviderCeiling(**{
        "requests_per_second": 2, "requests_per_minute": 3, "weighted_cost_per_minute": 6,
        "source_url": "https://docs.example.invalid/operator-plan", "checked_date": "2026-10-26",
        "scope": "ip", "plan": "synthetic-test-plan", **changes,
    })


def test_provider_ceiling_is_compulsory_and_effective_minimum(limiter, clock, tmp_path):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10, max_concurrency=4)
    config = limiter.read_config()
    config = limiter.write_config(config.model_copy(update={"provider_ceilings": {"mock": ceiling()}}),
                                  expected_revision=config.revision)
    assert limiter_at(tmp_path, clock).read_config().provider_ceilings == config.provider_ceilings
    profile = limiter.profile("mock")
    assert (profile.requests_per_second, profile.requests_per_minute, profile.burst) == (2, 3, 2)
    assert profile.weighted_cost_per_minute == 6
    with limiter.acquire("mock", cost=3) as lease:
        assert "budget:ceiling:mock" in lease.groups
    with limiter.acquire("mock", cost=3):
        pass
    # Hoeherer Betreiberwunsch kann die deklarierte Obergrenze nicht aushebeln.
    configure(limiter, requests_per_second=20, requests_per_minute=200, burst=20, max_concurrency=8)
    assert limiter.profile("mock").requests_per_second == 2
    with limiter.acquire("mock", cost=1):
        assert clock.wall() >= 1_700_000_060.0
    status = groups(limiter)["budget:ceiling:mock"]
    assert status.provider_ceiling == ceiling()
    assert status.provider_ceiling.independently_verified is False
    assert status.profile.manufacturer_limit_verified is False


def test_stricter_operator_limits_still_win(limiter):
    config = limiter.read_config()
    limiter.write_config(config.model_copy(update={"provider_ceilings": {"mock": ceiling()}}), expected_revision=0)
    profile = limiter.profile("mock")
    assert profile.requests_per_second == 1
    assert profile.requests_per_minute == 3
    assert profile.burst == 1


def test_partial_ceiling_keeps_unknown_dimensions_unknown(limiter):
    config = limiter.read_config()
    cap = ceiling(requests_per_second=None, requests_per_minute=None, weighted_cost_per_minute=5)
    limiter.write_config(config.model_copy(update={"provider_ceilings": {"ai_cloud": cap}}), expected_revision=0)
    profile = limiter.profile("ai_cloud")
    assert profile.weighted_cost_per_minute == 5
    assert profile.requests_per_second == 1 and profile.requests_per_minute == 30
    status = groups(limiter)["budget:ceiling:ai_cloud"]
    assert status.provider_ceiling.requests_per_second is None
    assert not limiter.status().manufacturer_telemetry_available


def test_adding_ceiling_inherits_existing_starts_not_empty_budget(limiter, clock):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10, max_concurrency=4)
    for _ in range(4):
        with limiter.acquire("mock", cost=2):
            pass
    config = limiter.read_config()
    limiter.write_config(config.model_copy(update={"provider_ceilings": {"mock": ceiling()}}),
                         expected_revision=config.revision)
    status = groups(limiter)["budget:ceiling:mock"]
    assert status.requests_last_minute == 4 and status.cost_last_minute == 8
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("mock", deadline=1.0)
    with limiter.acquire("mock"):
        assert clock.wall() >= 1_700_000_060.0


def test_readding_ceiling_accounts_for_intermediate_requests(limiter):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10, max_concurrency=4)
    config = limiter.read_config()
    configured = limiter.write_config(config.model_copy(update={"provider_ceilings": {"mock": ceiling()}}),
                                      expected_revision=config.revision)
    with limiter.acquire("mock"):
        pass
    removed = limiter.write_config(configured.model_copy(update={"provider_ceilings": {}}),
                                   expected_revision=configured.revision)
    for _ in range(3):
        with limiter.acquire("mock"):
            pass
    limiter.write_config(removed.model_copy(update={"provider_ceilings": {"mock": ceiling()}}),
                         expected_revision=removed.revision)
    assert groups(limiter)["budget:ceiling:mock"].requests_last_minute == 4
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("mock", deadline=1.0)


@pytest.mark.parametrize("changes", [
    {"source_url": "http://docs.example.invalid/"},
    {"source_url": "https://docs.example.invalid/?secret=not-allowed"},
    {"source_url": "https://user:password@docs.example.invalid/"},
    {"source_url": "https://docs.example.invalid/#fragment"},
    {"source_url": "https://127.0.0.1/"}, {"source_url": "https://docs.local/path"},
    {"source_url": "https://docs.example.invalid:443/path"},
    {"checked_date": "2026-02-30"}, {"checked_date": "unbekannt"},
    {"scope": ""}, {"plan": ""}, {"requests_per_second": 0},
    {"requests_per_second": None, "requests_per_minute": None, "weighted_cost_per_minute": None},
])
def test_ceiling_requires_bounded_known_dimensions_and_reference_metadata(changes):
    with pytest.raises(ValidationError):
        ceiling(**changes)


def test_ceiling_metadata_is_required_and_reserved_group_cannot_be_overridden():
    with pytest.raises(ValidationError):
        ProviderCeiling(requests_per_second=2)
    with pytest.raises(ValidationError):
        RequestLimitsConfig(group_profiles={"budget:ceiling:mock": RequestLimitProfile()})
    with pytest.raises(ValidationError):
        RequestLimitsConfig(provider_groups={"mock": ["budget:ceiling:other"]})


def test_default_minute_window_survives_restart(limiter, clock, tmp_path):
    times = []
    for _ in range(31):
        with limiter.acquire("binance"):
            times.append(clock.wall())
        limiter = limiter_at(tmp_path, clock)
    assert times[29] - times[0] == pytest.approx(29.0, abs=0.001)
    assert times[30] - times[0] >= 60.0
    assert times[30] - times[0] < 60.01


def test_two_per_second_and_sixty_per_minute_rolling_boundaries(limiter, clock):
    configure(limiter, requests_per_second=2, requests_per_minute=60, burst=2, max_concurrency=3)
    times = []
    for _ in range(63):
        with limiter.acquire("mock"):
            times.append(clock.wall())
    for now in times:
        assert sum(now - 1.0 < start <= now for start in times) <= 2
        assert sum(now - 60.0 < start <= now for start in times) <= 60
    assert times[60] - times[0] >= 60.0
    # Kein Doppelburst an einer starren Sekundengrenze.
    assert times[2] - times[0] >= 1.0


def test_burst_is_additional_token_bucket_not_extra_rolling_quota(limiter, clock):
    configure(limiter, requests_per_second=4, requests_per_minute=100, burst=1)
    starts = []
    for _ in range(5):
        with limiter.acquire("mock"):
            starts.append(clock.wall())
    assert starts[1] - starts[0] >= 0.25
    assert starts[4] - starts[0] >= 1.0


def test_weighted_cost_waits_for_enough_individual_old_requests(limiter, clock):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10,
              weighted_cost_per_minute=7)
    with limiter.acquire("mock", cost=5):
        pass
    clock.sleep(10.0)
    with limiter.acquire("mock", cost=2):
        pass
    with limiter.acquire("mock", cost=3):
        assert clock.elapsed == pytest.approx(60.0, abs=0.001)
        assert groups(limiter)["ip:global"].cost_last_minute == 5
    before = state(limiter)
    with pytest.raises(RequestCostExceeded):
        limiter.acquire("mock", cost=8)
    assert state(limiter) == before


def test_shared_groups_cannot_be_bypassed_and_no_partial_debit(limiter, clock):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10)
    held = limiter.acquire("first", groups=["account:first"])
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("second", groups=["account:second"], deadline=clock.monotonic() + 0.2)
    current = groups(limiter)
    assert current["provider:second"].requests_last_minute == 0
    assert current["account:second"].requests_last_minute == 0
    assert current["provider:first"].requests_last_minute == 1
    assert current["ip:global"].in_flight == 1
    assert current["ip:global"].queued == 0
    held.release()
    with limiter.acquire("second", groups=["account:second"]):
        assert groups(limiter)["ip:global"].requests_last_minute == 2


def test_two_accounts_share_project_budget_and_separate_identity(limiter, clock):
    config = limiter.read_config()
    generous = RequestLimitProfile(requests_per_second=10, requests_per_minute=100, burst=10, max_concurrency=3)
    project = RequestLimitProfile(requests_per_second=1, requests_per_minute=30)
    limiter.write_config(config.model_copy(update={"default_profile": generous,
        "group_profiles": {"project:shared": project}}), expected_revision=0)
    first = limiter.acquire("bitget", groups=["account:a", "project:shared"])
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("bitget", groups=["account:b", "project:shared"], deadline=0.2)
    assert groups(limiter)["account:b"].requests_last_minute == 0
    first.release()
    with limiter.acquire("bitget", groups=["account:b", "project:shared"]):
        pass
    assert clock.wall() >= 1_700_000_001.0


def test_ai_budget_is_isolated_from_cex_without_user_bypass(limiter):
    cex = limiter.acquire("binance")
    ai = limiter.acquire("ai_openrouter")
    assert "ip:ai" in ai.groups and "ip:global" not in ai.groups
    assert "ip:global" in cex.groups and "ip:ai" not in cex.groups
    assert groups(limiter)["ip:global"].in_flight == 1
    assert groups(limiter)["ip:ai"].in_flight == 1
    ai.release()
    cex.release()


def test_pause_survives_restart_and_does_not_shorten(limiter, clock, tmp_path):
    limiter.pause("binance", 4.0)
    limiter.pause("binance", 1.0)
    with limiter_at(tmp_path, clock).acquire("bitget"):
        assert clock.wall() >= 1_700_000_004.0  # IP-topf ist bewusst gemeinsam.
    assert groups(limiter)["provider:binance"].paused_until is None


def test_retry_policy_has_jitter_caps_attempt_bound_and_auth_no_retry(limiter):
    assert limiter.retry_delay("mock", 1, retryable=True, idempotent=True) == pytest.approx(1.1)
    assert limiter.retry_delay("mock", 2, retryable=True, idempotent=True, retry_after=4.0) == 4.0
    for kwargs in [{"attempt": 3, "retryable": True, "idempotent": True},
                   {"attempt": 1, "retryable": False, "idempotent": True},
                   {"attempt": 1, "retryable": True, "idempotent": False}]:
        with pytest.raises(RetryNotAllowed):
            limiter.retry_delay("mock", **kwargs)
    configure(limiter, backoff_base_seconds=30.0, backoff_max_seconds=30.0)
    assert limiter.retry_delay("mock", 2, retryable=True, idempotent=True) == 30.0


def test_retry_pause_is_bounded_by_job_deadline(limiter, clock):
    delay = limiter.retry_delay("mock", 1, retryable=True, idempotent=True, retry_after=600.0)
    limiter.pause("mock", delay)
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("mock", deadline=clock.monotonic() + 2.0)
    assert clock.elapsed == pytest.approx(2.0)
    assert groups(limiter)["ip:global"].requests_last_minute == 0


def test_cancel_prevents_reservation_and_clears_waiter(limiter, clock, tmp_path):
    cancel = Event()
    cancel.set()
    with pytest.raises(RequestCancelled):
        limiter.acquire("mock", cancel=cancel)
    assert not state(limiter)["active"]
    cancel.clear()
    held = limiter.acquire("first")
    seen_queue = []

    def interrupt(seconds):
        seen_queue.append(groups(limiter)["ip:global"].queued)
        clock.sleep(seconds)
        cancel.set()

    waiting = limiter_at(tmp_path, clock, sleep=interrupt)
    with pytest.raises(RequestCancelled):
        waiting.acquire("second", cancel=cancel)
    assert seen_queue == [1]
    assert groups(limiter)["ip:global"].queued == 0
    assert groups(limiter)["provider:second"].requests_last_minute == 0
    held.release()


def test_lease_releases_on_exception_but_never_reuses(limiter, clock):
    lease = limiter.acquire("mock")
    with pytest.raises(RuntimeError, match="mock HTTP failed"):
        with lease:
            raise RuntimeError("mock HTTP failed")
    assert groups(limiter)["ip:global"].in_flight == 0
    assert groups(limiter)["ip:global"].requests_last_minute == 1
    lease.release()
    with pytest.raises(RequestLimitError, match="lease_not_reusable"):
        with lease:
            pass
    late = limiter.acquire("mock", deadline=clock.monotonic() + 1.5)
    clock.sleep(2.0)
    with pytest.raises(RequestDeadlineExceeded):
        with late:
            pass
    assert groups(limiter)["ip:global"].in_flight == 0


def test_dispatch_two_clients_slow_signer_rechecks_actual_starts(tmp_path, clock):
    first, second = limiter_at(tmp_path, clock), limiter_at(tmp_path, clock)
    configure(first, requests_per_second=1, requests_per_minute=60, max_concurrency=2)
    starts, signatures = [], []

    def network(request):
        starts.append((request.url.path, clock.wall()))
        assert groups(first)["ip:global"].in_flight <= 2
        return httpx.Response(200)

    class Transport(httpx.BaseTransport):
        def __init__(self, limiter, prepare=None):
            self.limiter, self.prepare = limiter, prepare
            self.inner = httpx.MockTransport(network)

        def handle_request(self, request):
            with self.limiter.acquire("mock", cost=3) as lease:
                lease.start(prepare=self.prepare)
                return self.inner.handle_request(request)

    with httpx.Client(transport=Transport(second)) as fast:
        def slow_signer():
            signatures.append(clock.wall())
            if len(signatures) == 1:
                clock.sleep(1.1)
                # Reentrant second client proves the signer does not hold flock.
                fast.get("https://mock.invalid/fast")

        with httpx.Client(transport=Transport(first, slow_signer)) as slow:
            slow.get("https://mock.invalid/slow")
    assert [path for path, _ in starts] == ["/fast", "/slow"]
    assert starts[1][1] - starts[0][1] >= 1.0
    assert len(signatures) == 2 and signatures[-1] == starts[-1][1]
    for bucket in groups(first).values():
        assert bucket.requests_last_minute == 2 and bucket.cost_last_minute == 6
        assert bucket.in_flight == bucket.queued == 0


@pytest.mark.parametrize("cancelled", [False, True])
def test_dispatch_checks_deadline_or_cancel_after_signer_without_request(limiter, clock, cancelled):
    cancel, sent = Event(), []
    with limiter.acquire("mock", cancel=cancel, deadline=1.0) as lease:
        def prepare():
            if cancelled:
                cancel.set()
            else:
                clock.sleep(1.0)

        with pytest.raises(RequestCancelled if cancelled else RequestDeadlineExceeded):
            lease.start(prepare)
            sent.append("request")
        assert not sent
        assert state(limiter)["buckets"]["ip:global"]["starts"][0]["at"] == 1_700_000_000.0
    assert groups(limiter)["ip:global"].in_flight == 0


def test_dispatch_expired_before_prepare_never_calls_signer(limiter, clock):
    called = []
    with limiter.acquire("mock", deadline=1.0) as lease:
        clock.sleep(1.0)
        with pytest.raises(RequestDeadlineExceeded):
            lease.start(lambda: called.append(True))
    assert not called


def test_dispatch_checks_deadline_again_immediately_before_commit(limiter, clock, monkeypatch):
    real_wait = limiter._wait
    calls = 0

    def delayed_wait(*args):
        nonlocal calls
        result = real_wait(*args)
        calls += 1
        if calls == 4:  # Two groups, second pass after prepare.
            clock.sleep(1.0)
        return result

    with limiter.acquire("mock", deadline=1.0) as lease:
        monkeypatch.setattr(limiter, "_wait", delayed_wait)
        with pytest.raises(RequestDeadlineExceeded):
            lease.start()
    assert groups(limiter)["ip:global"].in_flight == 0


def test_dispatch_updates_all_groups_and_weighted_reservations_once(limiter, clock):
    configure(limiter, requests_per_second=2, requests_per_minute=60, burst=2,
              max_concurrency=2, weighted_cost_per_minute=7)
    with limiter.acquire("mock", cost=3, groups=["account:one", "project:shared"]) as lease:
        clock.sleep(0.25)
        lease.start()
        for bucket in groups(limiter).values():
            assert bucket.requests_last_minute == 1 and bucket.cost_last_minute == 3
            assert bucket.in_flight == 1
        bookings = state(limiter)["buckets"]
        assert all(len(bucket["starts"]) == 1 for bucket in bookings.values())
        assert {bucket["starts"][0]["at"] for bucket in bookings.values()} == {clock.wall()}
        assert {bucket["starts"][0]["reservation_id"] for bucket in bookings.values()} == {lease.lease_id}
        with pytest.raises(RequestLimitError, match="lease_not_reusable"):
            lease.start()
    with pytest.raises(RequestLimitError, match="lease_not_reusable"):
        lease.start()


def test_dispatch_new_mandatory_group_and_ceiling_during_prepare(limiter, clock):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10, max_concurrency=2)
    calls = []
    with limiter.acquire("mock", groups=["account:original"]) as lease:
        def prepare():
            calls.append(clock.wall())
            if len(calls) == 1:
                config = limiter.read_config()
                limiter.write_config(config.model_copy(update={
                    "provider_groups": {"mock": ["project:new"]},
                    "provider_ceilings": {"mock": ceiling()},
                }), expected_revision=config.revision)
                limiter.pause("mock", 1.5)

        lease.start(prepare)
        assert len(calls) == 2 and clock.wall() >= 1_700_000_001.5
        assert set(lease.groups) == {"account:original", "project:new", "budget:ceiling:mock",
                                    "ip:global", "provider:mock"}
        for group in lease.groups:
            assert groups(limiter)[group].requests_last_minute == 1
            assert groups(limiter)[group].in_flight == 1


def test_dispatch_old_start_records_without_reservation_id_are_conservative(limiter, clock, tmp_path):
    with limiter.acquire("mock"):
        pass
    original = state(limiter)
    for bucket in original["buckets"].values():
        for start in bucket["starts"]:
            del start["reservation_id"]
    state_file(limiter).write_text(json.dumps(original))
    restored = limiter_at(tmp_path, clock)
    assert groups(restored)["ip:global"].requests_last_minute == 1
    with restored.acquire("mock") as lease:
        lease.start()
    assert clock.wall() >= 1_700_000_001.0
    assert groups(restored)["ip:global"].requests_last_minute == 2


def test_dispatch_profile_change_cannot_ignore_new_cost_capacity(limiter):
    with limiter.acquire("mock", cost=3) as lease:
        def prepare():
            config = limiter.read_config()
            limiter.write_config(config.model_copy(update={
                "group_profiles": {"project:new": RequestLimitProfile(weighted_cost_per_minute=2)},
                "provider_groups": {"mock": ["project:new"]},
            }), expected_revision=config.revision)

        with pytest.raises(RequestCostExceeded):
            lease.start(prepare)
    assert "project:new" not in state(limiter)["buckets"]


def test_dispatch_wait_cancel_cleans_waiter_and_retains_other_bookings(tmp_path, clock):
    cancel = Event()
    limiter = limiter_at(tmp_path, clock)
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10, max_concurrency=2)
    with limiter.acquire("mock", cancel=cancel) as lease:
        limiter.pause("mock", 4.0)

        def interrupt(seconds):
            assert groups(limiter)["ip:global"].queued == 1
            clock.sleep(seconds)
            cancel.set()

        limiter._sleep = interrupt
        with pytest.raises(RequestCancelled):
            lease.start()
        assert groups(limiter)["ip:global"].queued == 0
        assert groups(limiter)["ip:global"].requests_last_minute == 1


def test_restart_keeps_active_lease_even_after_timeout(limiter, clock, tmp_path):
    orphan = limiter.acquire("mock")
    clock.sleep(1000.0)
    restarted = limiter_at(tmp_path, clock)
    with pytest.raises(RequestDeadlineExceeded):
        restarted.acquire("other", deadline=clock.monotonic() + 0.2)
    assert groups(restarted)["ip:global"].in_flight == 1
    assert restarted.status().concurrency_recovery == "explicit_release_only"
    assert "nachweislich" in restarted.status().recovery_hint
    assert groups(restarted)["ip:global"].next_start_at is None
    orphan.release()
    with restarted.acquire("other"):
        pass


def test_config_changes_preserve_usage_pauses_active_and_old_refill(limiter, clock):
    first = limiter.acquire("mock")
    limiter.pause("mock", 2.0)
    configure(limiter, requests_per_second=4, requests_per_minute=5, burst=4, max_concurrency=2)
    current = groups(limiter)["ip:global"]
    assert current.requests_last_minute == current.in_flight == 1
    assert "provider_pause" in current.blocking_reasons
    assert state(limiter)["buckets"]["ip:global"]["tokens"] == 0.0
    first.release()
    with limiter.acquire("mock"):
        assert clock.wall() >= 1_700_000_002.0


def test_reduced_limit_waits_for_existing_window_without_reset(limiter, clock):
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10)
    for _ in range(4):
        with limiter.acquire("mock"):
            pass
    configure(limiter, requests_per_minute=2)
    assert groups(limiter)["ip:global"].requests_last_minute == 4
    with limiter.acquire("mock"):
        assert clock.wall() >= 1_700_000_060.0


def test_profile_returns_effective_timeout_retry_and_deadline_from_all_groups(limiter):
    config = limiter.read_config()
    tight = RequestLimitProfile(timeout_seconds=2.0, max_retries=0, job_deadline_seconds=3.0)
    limiter.write_config(config.model_copy(update={"group_profiles": {"project:tight": tight},
        "provider_groups": {"mock": ["project:tight"]}}), expected_revision=0)
    profile = limiter.profile("mock")
    assert profile.timeout_seconds == 2.0
    assert profile.max_retries == 0
    assert profile.job_deadline_seconds == 3.0
    with limiter.acquire("mock", deadline=1.5) as lease:
        assert lease.timeout_seconds == pytest.approx(1.5)
        assert lease.deadline == 1.5


def test_request_classes_all_reserve_and_cannot_use_retry_as_free_request(limiter, clock):
    # Der HTTP-Adapter waehlt die Klasse; fuer alle ist der gleiche acquire Pflicht.
    for purpose in ("connection-test", "pagination", "metadata", "retry"):
        with limiter.acquire("mock"):
            pass
    assert groups(limiter)["ip:global"].requests_last_minute == 4
    assert clock.wall() >= 1_700_000_003.0


def test_clock_rollback_never_resets_windows(limiter, clock):
    with limiter.acquire("mock"):
        pass
    clock.rollback = 10.0
    assert limiter.status().clock_rollback
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("mock", deadline=1.0)
    assert groups(limiter)["ip:global"].requests_last_minute == 1
    assert clock.elapsed == pytest.approx(1.0)


def test_observations_are_real_optional_not_synthesized_and_persist(limiter, clock, tmp_path):
    assert not limiter.status().provider_observations
    limiter.observe("binance", used_weight_1m=123, reset_at=clock.wall() + 50.0, rate_limited=True)
    status = limiter_at(tmp_path, clock).status()
    observation = status.provider_observations["binance"]
    assert status.manufacturer_telemetry_available
    assert observation.used_weight_1m == 123 and observation.remaining_requests is None
    assert observation.last_rate_limit_at == clock.wall()
    assert not status.groups  # Beobachtung aendert keine lokalen Budgets/Pausen.
    clock.sleep(1.0)
    limiter.observe("binance", remaining_requests=0)
    updated = limiter.status().provider_observations["binance"]
    assert updated.last_observed_at == clock.wall()
    assert updated.last_rate_limit_at == observation.last_rate_limit_at
    assert updated.used_weight_1m is None and updated.reset_at is None
    assert updated.remaining_requests == 0
    with pytest.raises(ValidationError):
        limiter.observe("binance", used_weight_1m=-1)


@pytest.mark.parametrize("remaining", [-100, -1, 0, 5])
def test_signed_provider_remaining_after_429_is_preserved_without_clamping(limiter, clock, tmp_path, remaining):
    # Jupiter: https://developers.jup.ag/docs/portal/rate-limits
    reset_at = clock.wall() + 2.0
    limiter.observe("jupiter", remaining_requests=remaining, reset_at=reset_at, rate_limited=True)
    observation = limiter_at(tmp_path, clock).status().provider_observations["jupiter"]
    assert observation.remaining_requests == remaining
    assert observation.reset_at == reset_at
    assert observation.last_rate_limit_at == clock.wall()
    assert observation.used_weight_1m is None


def test_config_state_atomic_replace_and_fsync_failure_is_closed(limiter, monkeypatch):
    original = state_file(limiter).read_bytes()
    real_replace = os.replace

    def fail_replace(*args, **kwargs):
        raise OSError("simulated secret must not escape")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(LimiterUnavailable, match="^limiter_state_unavailable$"):
        limiter.acquire("mock")
    assert state_file(limiter).read_bytes() == original
    assert not list(limiter.directory.glob(".state-*"))
    monkeypatch.setattr(os, "replace", real_replace)
    with limiter.acquire("mock"):
        pass


def test_fsync_failure_does_not_admit_or_reset(limiter, monkeypatch):
    def fail_sync(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(LimiterUnavailable):
        limiter.acquire("mock")
    assert not state(limiter)["active"]


def test_failure_after_replace_retains_blocking_reservation(limiter, monkeypatch, clock):
    real_sync = os.fsync
    calls = 0

    def fail_directory_sync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated post-rename failure")
        return real_sync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_sync)
    with pytest.raises(LimiterUnavailable):
        limiter.acquire("mock")
    monkeypatch.setattr(os, "fsync", real_sync)
    assert groups(limiter)["ip:global"].in_flight == 1
    with pytest.raises(RequestDeadlineExceeded):
        limiter.acquire("other", deadline=clock.monotonic() + 0.1)


def test_private_root_must_not_allow_other_users_to_replace_state(tmp_path, clock):
    tmp_path.chmod(0o777)
    with pytest.raises(LimiterUnavailable, match="private_root"):
        limiter_at(tmp_path, clock)


@pytest.mark.parametrize("damage", ["missing", "truncated", "empty-object", "missing-buckets", "duplicate-keys"])
def test_missing_or_corrupt_state_is_fail_closed_not_reset(limiter, clock, tmp_path, damage):
    with limiter.acquire("mock"):
        pass
    filename = state_file(limiter)
    if damage == "missing":
        filename.unlink()
    elif damage == "truncated":
        filename.write_text('{"broken"')
    elif damage == "empty-object":
        filename.write_text("{}")
    elif damage == "duplicate-keys":
        filename.write_text(filename.read_text().replace('"active":{}', '"active":{},"active":{}'))
    else:
        value = state(limiter)
        del value["buckets"]
        filename.write_text(json.dumps(value))
    with pytest.raises(LimiterUnavailable):
        limiter_at(tmp_path, clock)


def test_unsafe_paths_permissions_symlinks_and_secret_input_not_exposed(tmp_path, clock):
    with pytest.raises(LimiterUnavailable, match="outside_software"):
        limiter_at(PROJECT_ROOT / "do-not-create-limiter", clock)
    unsafe = tmp_path / "request_limits"
    unsafe.mkdir(mode=0o755)
    with pytest.raises(LimiterUnavailable, match="permissions"):
        limiter_at(tmp_path, clock)
    unsafe.rmdir()
    destination = tmp_path / "elsewhere"
    destination.mkdir(mode=0o700)
    unsafe.symlink_to(destination, target_is_directory=True)
    with pytest.raises(LimiterUnavailable):
        limiter_at(tmp_path, clock)
    with pytest.raises(ValidationError) as error:
        RequestLimitsConfig(endpoint_costs={"rpc": {"SECRET?RAW_HEADER": 1}})
    assert "input_value" not in str(error.value)


def test_lock_contention_honors_deadline_and_does_not_admit(limiter, clock):
    with (limiter.directory / "coordinator.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RequestDeadlineExceeded):
            limiter.acquire("mock", deadline=clock.monotonic() + 0.2)
    assert not state(limiter)["active"]


def test_corrupt_secret_content_is_never_in_exception_or_logs(limiter, caplog):
    state_file(limiter).write_text('BROKEN_PRIVATE_FIXTURE_CONTENT')
    with pytest.raises(LimiterUnavailable) as error:
        limiter.status()
    assert "BROKEN_PRIVATE_FIXTURE_CONTENT" not in str(error.value)
    assert "BROKEN_PRIVATE_FIXTURE_CONTENT" not in caplog.text


def _process_obtain_then_crash(root, output):
    limiter = RequestLimiter(state_root=Path(root))
    limiter.acquire("mock")
    output.send("reserved")
    output.close()
    os._exit(0)  # Echter Prozessabbruch, kein Lease.__exit__.


def _process_config_revision(root, start, output):
    limiter = RequestLimiter(state_root=Path(root))
    config = RequestLimitsConfig()
    start.wait(10)
    try:
        limiter.write_config(config, expected_revision=0)
    except RevisionConflict:
        output.put("conflict")
    else:
        output.put("saved")


def _process_fixed_clock_requests(root, timestamp, start, output):
    limiter = RequestLimiter(state_root=Path(root), clock=lambda: timestamp.value)
    start.wait(10)
    for _ in range(2):
        with limiter.acquire("mock", cost=3, deadline=time.monotonic() + 10.0):
            output.put(timestamp.value)


def test_real_worker_crash_never_expires_concurrency(tmp_path):
    limiter = RequestLimiter(state_root=tmp_path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(target=_process_obtain_then_crash, args=(str(tmp_path), child))
    worker.start()
    try:
        assert parent.poll(8) and parent.recv() == "reserved"
        worker.join(timeout=5)
        assert worker.exitcode == 0
        assert groups(RequestLimiter(state_root=tmp_path))["ip:global"].in_flight == 1
        with pytest.raises(RequestDeadlineExceeded):
            limiter.acquire("other", deadline=time.monotonic() + 0.2)
        assert groups(limiter)["ip:global"].in_flight == 1
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=3)
        parent.close()
        child.close()


def test_real_workers_config_revision_compare_and_swap(tmp_path):
    limiter = RequestLimiter(state_root=tmp_path)
    context = multiprocessing.get_context("spawn")
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_process_config_revision, args=(str(tmp_path), start, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        start.set()
        assert sorted(output.get(timeout=8) for _ in range(2)) == ["conflict", "saved"]
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert limiter.read_config().revision == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=3)


def test_real_workers_share_weighted_rolling_minute_with_controlled_clock(tmp_path):
    context = multiprocessing.get_context("spawn")
    timestamp = context.Value("d", 1_700_000_000.0)
    limiter = RequestLimiter(state_root=tmp_path, clock=lambda: timestamp.value)
    configure(limiter, requests_per_second=10, requests_per_minute=60, burst=10,
              max_concurrency=4, weighted_cost_per_minute=6)
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_process_fixed_clock_requests, args=(str(tmp_path), timestamp, start, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        start.set()
        assert [output.get(timeout=8) for _ in range(2)] == [1_700_000_000.0] * 2
        assert groups(limiter)["ip:global"].cost_last_minute == 6
        timestamp.value += 59.999
        assert groups(limiter)["ip:global"].cost_last_minute == 6
        assert "weighted_minute" in groups(limiter)["ip:global"].blocking_reasons
        timestamp.value = 1_700_000_060.0
        assert [output.get(timeout=8) for _ in range(2)] == [1_700_000_060.0] * 2
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert groups(limiter)["ip:global"].cost_last_minute == 6
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=3)


def _process_hold(root, start, ready, release):
    limiter = RequestLimiter(state_root=Path(root))
    start.wait(10)
    with limiter.acquire("mock", deadline=time.monotonic() + 8.0):
        ready.put(("entered", time.time(), groups(limiter)["ip:global"].in_flight))
        release.wait(8)
    ready.put(("released", time.time(), 0))


def _process_admit_many(root, start, output):
    limiter = RequestLimiter(state_root=Path(root))
    start.wait(10)
    for _ in range(3):
        with limiter.acquire("mock", deadline=time.monotonic() + 8.0):
            output.put(time.time())


def test_real_processes_share_concurrency_and_restart_state(tmp_path):
    limiter = RequestLimiter(state_root=tmp_path)
    configure(limiter, requests_per_second=10, requests_per_minute=100, burst=10)
    context = multiprocessing.get_context("spawn")
    start, release = context.Event(), context.Event()
    output = context.Queue()
    workers = [context.Process(target=_process_hold, args=(str(tmp_path), start, output, release)) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        start.set()
        first = output.get(timeout=8)
        assert first[0] == "entered" and first[2] == 1
        # Zweiter Prozess muss nachweisbar als wartend registriert sein.
        until = time.monotonic() + 5.0
        while groups(limiter)["ip:global"].queued == 0 and time.monotonic() < until:
            time.sleep(0.01)
        assert groups(limiter)["ip:global"].queued == 1
        assert groups(limiter)["ip:global"].in_flight == 1
        release.set()
        events = [output.get(timeout=8) for _ in range(3)]
        assert sum(event[0] == "entered" for event in events) == 1
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert groups(limiter)["ip:global"].in_flight == 0
    finally:
        release.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=3)


def test_real_processes_share_rolling_request_windows(tmp_path):
    limiter = RequestLimiter(state_root=tmp_path)
    configure(limiter, requests_per_second=2, requests_per_minute=60, burst=2, max_concurrency=4)
    context = multiprocessing.get_context("spawn")
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_process_admit_many, args=(str(tmp_path), start, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        start.set()
        starts = sorted(output.get(timeout=10) for _ in range(6))
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        # Messung nach Dateisystem-Commit; kleine Messlatenz ist nicht das Fenster selbst.
        persisted = state(limiter)["buckets"]["ip:global"]["starts"]
        admitted = [item["at"] for item in persisted]
        for now in admitted:
            assert sum(now - 1 < value <= now for value in admitted) <= 2
        assert starts[-1] - starts[0] >= 1.9
        assert len(admitted) == 6
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=3)
