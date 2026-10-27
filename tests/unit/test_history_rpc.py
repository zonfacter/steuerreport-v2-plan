"""RPC-Auswahl ohne Live-HTTP, Tarifannahmen oder produktive Geheimnisse."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import fcntl
import json
from types import SimpleNamespace

import httpx
import pytest

from steuerreport_v2.contracts.history import HistoryRateState, HistoryRpcOption
from steuerreport_v2.contracts.request_limits import ProviderCeiling, RequestLimitProfile
from steuerreport_v2.domain import history_rpc as rpc
from steuerreport_v2.domain.history_types import HistoryFetchError
from steuerreport_v2.domain.request_limits import RequestLimiter, endpoint_group
from steuerreport_v2.domain.secret_vault import encrypt_secret_setting


class Store:
    def __init__(self, values=None):
        self.values = values or {}
        self.reads = []

    @contextmanager
    def connect(self):
        yield self

    def execute(self, sql, parameters):
        assert sql == "select value_json from admin_settings where key = ?"
        assert len(parameters) == 1
        key = parameters[0]
        assert key in {"secret.helius.api_key", "secret.alchemy.api_key"}
        self.reads.append(key)
        row = (self.values[key],) if key in self.values else None
        return SimpleNamespace(fetchone=lambda: row)

    def list_admin_settings(self):
        pytest.fail("RPC darf admin_settings niemals vollstaendig laden")


def forbidden(*args, **kwargs):
    pytest.fail("Unerlaubter Key-, Profil- oder Netzwerkzugriff")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("ALCHEMY_API_KEY", "ALCHEMY_SOLANA_API_KEY", "HELIUS_API_KEY",
                 "SOLANA_RPC_URL", "SOLANA_RPC_URLS", "STEUERREPORT_SOLANA_RPC_URL",
                 "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def fast(**changes):
    return RequestLimitProfile(**{
        "requests_per_second": 100, "requests_per_minute": 6000,
        "max_concurrency": 10, **changes,
    })


def configured_limiter(tmp_path, monkeypatch, **changes):
    def clock():
        return 1000.0
    monkeypatch.setattr(rpc.time, "time", clock)
    limiter = RequestLimiter(state_root=tmp_path / "runtime", clock=clock, monotonic=clock)
    config = limiter.read_config()
    limiter.write_config(config.model_copy(update={"default_profile": fast(), **changes}),
                         expected_revision=config.revision)
    return limiter


def test_public_reads_neither_secrets_profile_nor_environment_key(monkeypatch):
    monkeypatch.setattr(rpc, "_secret_json", forbidden)
    monkeypatch.setattr(rpc, "decode_secret_setting", forbidden)
    monkeypatch.setattr(rpc, "_profile_rpc_url", forbidden)
    monkeypatch.setattr(rpc, "load_vault_key", forbidden)
    monkeypatch.setattr(rpc, "_alchemy_env_key", forbidden)
    endpoint = rpc.resolve_rpc(None, "public")
    assert endpoint.url == "https://api.mainnet.solana.com"
    assert endpoint.provider_id == "solana_rpc"
    assert endpoint.kind == "public"
    with pytest.raises(FrozenInstanceError):
        endpoint.url = "https://other.invalid"


def test_endpoint_repr_hides_url_key_and_binding():
    endpoint = rpc.resolve_rpc(Store({"secret.helius.api_key": '"synthetic-secret"'}), "helius")
    assert "synthetic-secret" not in repr(endpoint)
    assert endpoint.url not in repr(endpoint)
    assert endpoint.binding_hash not in repr(endpoint)
    assert len(endpoint.binding_hash) == 64


def test_helius_uses_only_current_saved_key(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", "ignored-secret")
    monkeypatch.setenv("SOLANA_RPC_URL", "https://ignored.invalid")
    with pytest.raises(HistoryFetchError, match="^history_rpc_key_missing$"):
        rpc.resolve_rpc(Store(), "helius")
    store = Store({"secret.helius.api_key": '"synthetic-current"'})
    first = rpc.resolve_rpc(store, "helius")
    assert first.url == "https://mainnet.helius-rpc.com/?api-key=synthetic-current"
    store.values["secret.helius.api_key"] = '"synthetic-new"'
    second = rpc.resolve_rpc(store, "helius")
    assert second.binding_hash != first.binding_hash
    assert first.url.endswith("synthetic-current")


@pytest.mark.parametrize("choice", ["helius", "alchemy"])
def test_binding_reads_only_selected_secret_row(choice):
    key = f"secret.{choice}.api_key"
    store = Store({key: '"selected-secret"', "history.job.unrelated": "unread-history-payload"})
    rpc.resolve_rpc(store, choice)
    rpc.resolve_rpc(store, choice)
    assert store.reads == [key, key]


def test_options_read_only_two_secret_rows_without_decoding(monkeypatch):
    store = Store({"secret.helius.api_key": '"helius-secret"', "secret.alchemy.api_key": '"alchemy-secret"',
                   "history.job.unrelated": "unread-history-payload"})
    monkeypatch.setattr(rpc, "decode_secret_setting", forbidden)
    options = rpc.rpc_options(store)
    assert store.reads == ["secret.helius.api_key", "secret.alchemy.api_key"]
    assert all(option["ready"] for option in options[:3])
    assert "helius-secret" not in json.dumps(options)
    assert "alchemy-secret" not in json.dumps(options)
    assert "unread-history-payload" not in json.dumps(options)


def test_real_store_uses_single_row_queries_despite_many_history_jobs(tmp_path, monkeypatch, caplog):
    from steuerreport_v2.db.duckdb_store import DuckDbStore

    key_file = tmp_path / "vault-key"
    key_file.write_bytes(b"a" * 32)
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key_file))
    store = DuckDbStore(tmp_path / "history-rpc.duckdb")
    original_connect = store.connect
    with original_connect() as con:
        con.execute("insert into admin_settings "
                    "select 'history.job.' || cast(i as varchar), repeat('unread-sensitive-history', 32), current_timestamp "
                    "from range(2048) jobs(i)")
        for choice in ("helius", "alchemy"):
            key = f"secret.{choice}.api_key"
            con.execute("insert into admin_settings values (?, ?, current_timestamp)",
                        [key, encrypt_secret_setting(key, f"{choice}-private-key", b"a" * 32)])
    reads = []

    @contextmanager
    def targeted_connection():
        with original_connect() as con:
            def execute(sql, parameters):
                assert sql == "select value_json from admin_settings where key = ?"
                assert parameters in (["secret.helius.api_key"], ["secret.alchemy.api_key"])
                reads.append(parameters[0])
                result = con.execute(sql, parameters)
                return SimpleNamespace(fetchone=result.fetchone)
            yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(store, "connect", targeted_connection)
    monkeypatch.setattr(store, "list_admin_settings", forbidden)
    with monkeypatch.context() as metadata:
        metadata.setattr(rpc, "decode_secret_setting", forbidden)
        options = rpc.rpc_options(store)
    assert options[1]["ready"] and options[2]["ready"]
    assert reads == ["secret.helius.api_key", "secret.alchemy.api_key"]
    reads.clear()
    first = rpc.resolve_rpc(store, "helius")
    assert first.url.endswith("helius-private-key")
    assert rpc.resolve_rpc(store, "alchemy").url.endswith("alchemy-private-key")
    with original_connect() as con:
        key = "secret.helius.api_key"
        con.execute("update admin_settings set value_json = ? where key = ?",
                    [encrypt_secret_setting(key, "changed-private-key", b"a" * 32), key])
    assert rpc.resolve_rpc(store, "helius").binding_hash != first.binding_hash
    assert reads == ["secret.helius.api_key", "secret.alchemy.api_key", "secret.helius.api_key"]
    public_metadata = json.dumps(options) + repr(first) + caplog.text
    for secret in ("helius-private-key", "alchemy-private-key", "changed-private-key", "unread-sensitive-history"):
        assert secret not in public_metadata


def test_single_row_read_error_is_sanitized_without_scan_fallback(monkeypatch, caplog):
    store = Store()

    @contextmanager
    def failed_connection():
        raise RuntimeError("private-key https://private-host.invalid/private-path")
        yield

    monkeypatch.setattr(store, "connect", failed_connection)
    monkeypatch.setenv("ALCHEMY_API_KEY", "must-not-fallback")
    with pytest.raises(HistoryFetchError, match="^history_rpc_key_unavailable$") as caught:
        rpc.resolve_rpc(store, "alchemy")
    options = rpc.rpc_options(store)
    assert not options[1]["ready"] and not options[2]["ready"]
    assert options[1]["blocked_reason"] == options[2]["blocked_reason"] == "history_rpc_key_unavailable"
    public_metadata = json.dumps(options) + str(caught.value) + caplog.text
    for secret in ("private-key", "private-host.invalid", "private-path", "must-not-fallback"):
        assert secret not in public_metadata
    assert not store.reads


@pytest.mark.parametrize("env", ["ALCHEMY_API_KEY", "ALCHEMY_SOLANA_API_KEY"])
def test_alchemy_retains_existing_key_and_env_precedence(monkeypatch, env):
    monkeypatch.setenv(env, "env-key")
    store = Store({"secret.alchemy.api_key": '"saved/key"'})
    assert rpc.resolve_rpc(store, "alchemy").url.endswith("/saved%2Fkey")
    store.values.clear()
    assert rpc.resolve_rpc(store, "alchemy").url.endswith("/env-key")


def test_unreadable_saved_key_does_not_fall_back_to_environment(monkeypatch):
    monkeypatch.setenv("ALCHEMY_API_KEY", "env-key")
    store = Store({"secret.alchemy.api_key": encrypt_secret_setting("secret.alchemy.api_key", "hidden", b"a" * 32)})
    with pytest.raises(HistoryFetchError, match="^history_rpc_key_unavailable$"):
        rpc.resolve_rpc(store, "alchemy")


@pytest.mark.parametrize("choice", [None, "legacy", "premium", "https://secret.invalid"])
def test_resolver_requires_explicit_known_choice(choice):
    with pytest.raises(HistoryFetchError, match="^history_rpc_choice_invalid$"):
        rpc.resolve_rpc(None, choice)


def test_custom_profile_precedes_single_env_and_never_uses_url_chain(monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_URL", "https://env.invalid/private-key")
    monkeypatch.setenv("SOLANA_RPC_URLS", "https://ignored.invalid")
    monkeypatch.setattr(rpc, "_profile_rpc_url", lambda: "https://profile.invalid/private-key")
    endpoint = rpc.resolve_rpc(None, "custom")
    assert endpoint.url == "https://profile.invalid/private-key"
    assert endpoint.provider_id == "solana_custom_rpc"
    monkeypatch.setattr(rpc, "_profile_rpc_url", lambda: "")
    assert rpc.resolve_rpc(None, "custom").url == "https://env.invalid/private-key"


@pytest.mark.parametrize("value", [
    "https://first.invalid,https://second.invalid", '["https://first.invalid"]',
    "https://first.invalid https://second.invalid", "ftp://host.invalid", "https://",
    "https://host.invalid:bad", "https://user:secret@host.invalid", "https://host.invalid/#secret",
])
def test_custom_invalid_url_never_silently_falls_back(monkeypatch, value):
    monkeypatch.setattr(rpc, "_profile_rpc_url", lambda: value)
    monkeypatch.setenv("SOLANA_RPC_URL", "https://otherwise-valid.invalid")
    with pytest.raises(HistoryFetchError, match="^history_rpc_url_invalid$"):
        rpc.resolve_rpc(None, "custom")


def test_custom_missing_does_not_use_manufacturer_chain(monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_URLS", "https://ignored.invalid")
    with pytest.raises(HistoryFetchError, match="^history_rpc_url_missing$"):
        rpc.resolve_rpc(None, "custom")


@pytest.mark.parametrize("url, provider, kind", [
    ("https://mainnet.helius-rpc.com/?api-key=synthetic", "helius", "configured"),
    ("https://solana-mainnet.g.alchemy.com/v2/synthetic", "alchemy", "configured"),
    ("https://api.mainnet.solana.com", "solana_rpc", "public"),
    ("https://api.mainnet-beta.solana.com", "solana_rpc", "public"),
    ("https://solana-rpc.publicnode.com", "solana_rpc", "public"),
    ("https://solana.publicnode.dev", "solana_rpc", "public"),
    ("https://alchemy.com.attacker.invalid/key", "solana_custom_rpc", "configured"),
    ("https://rpc.invalid/helius.xyz", "solana_custom_rpc", "configured"),
])
def test_custom_classification_is_honest_and_host_bound(monkeypatch, url, provider, kind):
    monkeypatch.setattr(rpc, "_profile_rpc_url", lambda: url)
    endpoint = rpc.resolve_rpc(None, "custom")
    assert (endpoint.provider_id, endpoint.kind) == (provider, kind)
    option = next(row for row in rpc.rpc_options(Store()) if row["id"] == "custom")
    assert option["provider_id"] == provider
    assert option["kind"] == kind
    assert option["tariff_verified"] is False
    assert url not in json.dumps(option)


def test_options_are_contract_exact_and_do_not_decrypt_or_create_state(tmp_path, monkeypatch):
    from steuerreport_v2.domain import secret_vault

    key = b"k" * 32
    store = Store({"secret.helius.api_key": encrypt_secret_setting("secret.helius.api_key", "hidden-secret", key)})
    monkeypatch.setattr(rpc, "load_vault_key", lambda: key)
    monkeypatch.setattr(rpc, "decode_secret_setting", forbidden)
    monkeypatch.setattr(secret_vault, "decode_secret_setting", forbidden)
    monkeypatch.setenv("ALCHEMY_API_KEY", "env-secret")
    monkeypatch.setenv("SOLANA_RPC_URL", "https://custom.invalid/private-secret")
    options = rpc.rpc_options(store)
    assert [row["id"] for row in options] == ["public", "helius", "alchemy", "custom"]
    assert all(row["configured"] and row["ready"] for row in options)
    assert all(set(row) == set(HistoryRpcOption.model_fields) for row in options)
    assert all(HistoryRpcOption.model_validate(row) for row in options)
    assert "secret" not in json.dumps(options)
    assert not (tmp_path / "runtime").exists()


def test_encrypted_current_key_is_resolved_only_for_explicit_choice(tmp_path, monkeypatch):
    path = tmp_path / "vault-key"
    path.write_bytes(b"a" * 32)
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(path))
    store = Store({"secret.helius.api_key": encrypt_secret_setting("secret.helius.api_key", "current-secret", b"a" * 32)})
    options = rpc.rpc_options(store)
    assert options[1]["configured"] and options[1]["ready"]
    assert "current-secret" not in json.dumps(options)
    assert rpc.resolve_rpc(store, "helius").url.endswith("current-secret")
    path.write_bytes(b"b" * 32)
    assert not rpc.rpc_options(store)[1]["ready"]
    with pytest.raises(HistoryFetchError, match="^history_rpc_key_unavailable$"):
        rpc.resolve_rpc(store, "helius")


@pytest.mark.parametrize("value", ['""', "null", "malformed"])
def test_alchemy_metadata_matches_existing_empty_key_env_fallback(monkeypatch, value):
    monkeypatch.setenv("ALCHEMY_API_KEY", "env-secret")
    store = Store({"secret.alchemy.api_key": value})
    option = rpc.rpc_options(store)[2]
    assert option["ready"] and option["configured"]
    assert rpc.resolve_rpc(store, "alchemy").url.endswith("env-secret")


def test_broken_vault_does_not_block_public_option_or_status(monkeypatch):
    monkeypatch.setattr(rpc, "load_vault_key", lambda: None)
    store = Store({"secret.helius.api_key": encrypt_secret_setting("secret.helius.api_key", "hidden", b"a" * 32)})
    options = rpc.rpc_options(store)
    assert options[0]["ready"]
    assert options[1]["configured"] and not options[1]["ready"]
    assert rpc.resolve_rpc(None, "public").provider_id == "solana_rpc"
    assert not rpc.rpc_status(None, "public")["available"]


def test_status_missing_state_returns_unknown_not_zero_and_does_not_create(tmp_path):
    status = rpc.rpc_status(None, "public")
    assert set(status) == set(HistoryRateState.model_fields)
    assert not status["available"]
    for field in ("requests_per_second", "requests_per_10_seconds", "requests_per_minute",
                  "max_concurrency", "effective_max_requests_per_second", "in_flight", "waiting_requests", "wait_seconds"):
        assert status[field] is None
    assert not (tmp_path / "runtime").exists()


def test_pinned_provider_status_never_reads_changed_keys_or_urls(tmp_path, monkeypatch):
    configured_limiter(tmp_path, monkeypatch)
    monkeypatch.setattr(rpc, "_profile_rpc_url", forbidden)
    monkeypatch.setattr(rpc, "_secret_json", forbidden)
    monkeypatch.setattr(rpc, "decode_secret_setting", forbidden)
    monkeypatch.setattr(rpc, "_option", forbidden)
    status = rpc.rpc_status(None, "custom", provider_id="helius")
    assert status["available"]
    assert "provider:helius" in status["budget_groups"]
    assert "provider:solana_custom_rpc" not in status["budget_groups"]


def test_status_merges_global_provider_endpoint_and_shared_budgets(tmp_path, monkeypatch):
    endpoint = endpoint_group("helius", rpc.TRANSACTION_ENDPOINT)
    limiter = configured_limiter(tmp_path, monkeypatch,
        group_profiles={"ip:global": fast(requests_per_second=3), "provider:helius": fast(requests_per_second=50),
                        "project:shared": fast(requests_per_minute=120)},
        provider_groups={"helius": ["project:shared"]},
        endpoint_profiles={"helius": {rpc.TRANSACTION_ENDPOINT: fast(requests_per_10_seconds=10)}},
    )
    before = (limiter.directory / "coordinator.json").read_bytes()
    status = rpc.rpc_status(None, "helius")
    assert status["requests_per_second"] == 3
    assert status["requests_per_10_seconds"] == 10
    assert status["requests_per_minute"] == 120
    assert status["effective_max_requests_per_second"] == 1
    assert set(status["budget_groups"]) == {"ip:global", "provider:helius", "project:shared", endpoint}
    assert status["bottlenecks"] == [endpoint]
    assert status["config_revision"] == limiter.read_config().revision
    assert (limiter.directory / "coordinator.json").read_bytes() == before


def test_global_three_is_visible_bottleneck_without_raising_quotas(tmp_path, monkeypatch):
    limiter = configured_limiter(tmp_path, monkeypatch, group_profiles={"ip:global": fast(requests_per_second=3)})
    config = limiter.read_config()
    for provider in ("helius", "alchemy", "solana_custom_rpc"):
        status = rpc.rpc_status(None, provider_id=provider)
        assert status["requests_per_second"] == status["effective_max_requests_per_second"] == 3
        assert status["bottlenecks"] == ["ip:global"]
    assert limiter.read_config() == config


def test_custom_does_not_inherit_public_free_provider_profile(tmp_path, monkeypatch):
    configured_limiter(tmp_path, monkeypatch,
        group_profiles={"provider:solana_rpc": fast(requests_per_second=3)})
    custom = rpc.rpc_status(None, provider_id="solana_custom_rpc")
    assert custom["requests_per_second"] == 100
    assert "provider:solana_rpc" not in custom["budget_groups"]


def test_weighted_provider_ceiling_is_included_and_no_plan_claim_is_returned(tmp_path, monkeypatch):
    ceiling = ProviderCeiling(weighted_cost_per_minute=120,
        source_url="https://example.invalid/documentation", checked_date="2026-10-27", scope="provider", plan="Operator")
    configured_limiter(tmp_path, monkeypatch, provider_ceilings={"helius": ceiling},
        endpoint_costs={"helius": {rpc.TRANSACTION_ENDPOINT: 4}})
    status = rpc.rpc_status(None, "helius")
    assert status["effective_max_requests_per_second"] == 0.5
    assert status["bottlenecks"] == ["budget:ceiling:helius"]
    assert "Operator" not in json.dumps(status)


def test_impossible_request_cost_is_not_advertised_as_executable_rate(tmp_path, monkeypatch):
    configured_limiter(tmp_path, monkeypatch,
        group_profiles={"provider:helius": fast(weighted_cost_per_minute=5)},
        endpoint_costs={"helius": {rpc.TRANSACTION_ENDPOINT: 6}})
    status = rpc.rpc_status(None, "helius")
    assert status["effective_max_requests_per_second"] is None
    assert status["wait_seconds"] is None and status["retry_at"] is None
    assert "request_cost_exceeds_group_capacity" in status["blocking_reasons"]


def test_custom_binding_reads_changed_profile_without_cached_values(tmp_path, monkeypatch):
    from steuerreport_v2.private_settings import private_value

    path = tmp_path / "custom-profile.json"
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(path))
    path.write_text(json.dumps({"solana_rpc_url": "https://first.invalid/private-key"}))
    assert private_value("solana_rpc_url") == "https://first.invalid/private-key"
    first = rpc.resolve_rpc(None, "custom")
    path.write_text(json.dumps({"solana_rpc_url": "https://second.invalid/private-key"}))
    second = rpc.resolve_rpc(None, "custom")
    assert first.binding_hash != second.binding_hash
    assert second.url == "https://second.invalid/private-key"
    assert private_value("solana_rpc_url") == "https://first.invalid/private-key"


@pytest.mark.parametrize("value", ["broken", "[]", '{"solana_rpc_url": 123}'])
def test_bad_custom_profile_is_sanitized_and_never_falls_back(tmp_path, monkeypatch, value):
    path = tmp_path / "broken-profile.json"
    path.write_text(value)
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(path))
    monkeypatch.setenv("SOLANA_RPC_URL", "https://fallback.invalid")
    with pytest.raises(HistoryFetchError, match="^history_rpc_profile_unavailable$"):
        rpc.resolve_rpc(None, "custom")
    assert rpc.rpc_options(Store())[-1]["blocked_reason"] == "history_rpc_profile_unavailable"


def test_unclassifiable_custom_status_is_unknown_even_when_limiter_exists(tmp_path, monkeypatch):
    configured_limiter(tmp_path, monkeypatch)
    monkeypatch.setenv("SOLANA_RPC_URL", "invalid")
    status = rpc.rpc_status(None, "custom")
    assert not status["available"] and status["requests_per_second"] is None
    assert status["blocking_reasons"] == ["history_rpc_url_invalid"]


def test_busy_limiter_snapshot_does_not_wait_write_or_create(tmp_path, monkeypatch):
    limiter = configured_limiter(tmp_path, monkeypatch)
    before = (limiter.directory / "coordinator.json").read_bytes()
    with (limiter.directory / "coordinator.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = rpc.rpc_status(None, "public")
    assert not status["available"] and status["requests_per_second"] is None
    assert (limiter.directory / "coordinator.json").read_bytes() == before


def test_status_uses_real_endpoint_cost_for_weighted_wait(tmp_path, monkeypatch):
    limiter = configured_limiter(tmp_path, monkeypatch,
        group_profiles={"provider:helius": fast(weighted_cost_per_minute=5)},
        endpoint_costs={"helius": {rpc.TRANSACTION_ENDPOINT: 4}})
    with limiter.acquire("helius", endpoint=rpc.TRANSACTION_ENDPOINT, cost=4) as lease:
        lease.start()
    status = rpc.rpc_status(None, "helius")
    assert "weighted_minute" in status["blocking_reasons"]
    assert status["wait_seconds"] == 60.0
    assert status["retry_at"].timestamp() == 1060.0


def test_concurrency_pause_and_queue_are_read_only_and_not_double_counted(tmp_path, monkeypatch):
    limiter = configured_limiter(tmp_path, monkeypatch, default_profile=fast(max_concurrency=1))
    lease = limiter.acquire("helius", endpoint=rpc.TRANSACTION_ENDPOINT)
    try:
        lease.start()
        limiter.pause("helius", 20.0)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in limiter.directory.iterdir()}
        status = rpc.rpc_status(None, "helius")
        assert status["in_flight"] == 1
        assert status["waiting_requests"] == 0
        assert "concurrency" in status["blocking_reasons"]
        assert "provider_pause" in status["blocking_reasons"]
        assert status["wait_seconds"] is None and status["retry_at"] is None
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in limiter.directory.iterdir()}
        assert after == before
    finally:
        lease.release()


@pytest.mark.parametrize("damage", ["missing", "invalid", "empty_lock", "symlink"])
def test_bad_existing_state_stays_untouched_and_is_not_reset(tmp_path, monkeypatch, damage):
    limiter = configured_limiter(tmp_path, monkeypatch)
    state = limiter.directory / "coordinator.json"
    if damage == "missing":
        state.unlink()
    elif damage == "invalid":
        state.write_text("synthetic-secret corrupt data")
    elif damage == "empty_lock":
        (limiter.directory / "coordinator.lock").write_text("")
    else:
        target = tmp_path / "external.json"
        target.write_bytes(state.read_bytes())
        state.unlink()
        state.symlink_to(target)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in limiter.directory.iterdir()}
    status = rpc.rpc_status(None, "public")
    assert not status["available"] and status["requests_per_second"] is None
    assert "synthetic-secret" not in json.dumps(status)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in limiter.directory.iterdir()} == before


def test_legacy_and_unknown_provider_have_no_fabricated_limits():
    assert rpc.rpc_status(None) == HistoryRateState().model_dump()
    assert rpc.rpc_status(None, provider_id="secret-provider")["requests_per_second"] is None


def test_portfolio_hook_pins_limiter_provider_with_mock_http(tmp_path, monkeypatch):
    from steuerreport_v2.domain import portfolio
    from steuerreport_v2.domain.external_http import managed_client

    limiter = configured_limiter(tmp_path, monkeypatch)
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"result": {"ok": True}})
    monkeypatch.setattr(portfolio, "managed_client", lambda **kwargs: managed_client(
        transport=httpx.MockTransport(handler), limiter=limiter, **kwargs))
    class Pinned(portfolio.PortfolioService):
        def _solana_rpc_provider(self):
            return "solana_custom_rpc"

        def _solana_rpc_urls(self):
            return ["https://rpc.invalid/private-secret"]

    service = Pinned(None)
    assert service._solana_rpc("getTransaction", [], 5) == {"ok": True}
    assert len(seen) == 1
    groups = {row.group for row in limiter.status().groups}
    assert "provider:solana_custom_rpc" in groups
    assert "provider:solana_rpc" not in groups
    assert portfolio.PortfolioService(None)._solana_rpc_provider() is None
