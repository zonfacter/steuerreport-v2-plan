"""Automatische Tagespreisaufloesung ausschliesslich mit synthetischen Belegen."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as module
from steuerreport_v2.domain.external_http import managed_client, outbound_scope
from steuerreport_v2.domain.historical_price_collection import fallback_candidates
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.domain.request_limits import RequestLimiter
from steuerreport_v2.importers.source_history_importer import canonical_json

from test_historical_price_workflow import (
    AT, BASE, MINT, approval, batches, continuation, data, error, requested_points,
    seed, source_snapshot,
)


UTC = timezone.utc
WSOL = "So11111111111111111111111111111111111111112"
SOL_PROVIDER = "solana:" + WSOL


def quote(instant, price="150", confidence="0.99"):
    return {"timestamp": instant, "price": price, "confidence": confidence}


def echoed(coins):
    return {"coins": {identifier: {"prices": [quote(instant) for instant in instants]}
                      for identifier, instants in coins.items()}}


@pytest.fixture
def automatic_workflow(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "automatic-synthetic.duckdb")
    with store.connect():
        pass
    env = SimpleNamespace(
        store=store, service=HistoricalPriceService(store), mappings={}, calls=[],
        batch_payload=lambda coins, number: echoed(coins), batch_count=0,
        legacy_missing=False, applied_callbacks=[], scope_budgets=[],
        fx_payload=None,
    )
    monkeypatch.setattr(HistoricalPriceService, "mappings", lambda self: env.mappings)
    clock = [1_000_000.0]
    limiter = RequestLimiter(
        state_root=tmp_path / "limits", clock=lambda: clock[0], monotonic=lambda: clock[0],
        sleep=lambda value: clock.__setitem__(0, clock[0] + value),
    )
    limiter.write_config(RequestLimitsConfig(default_profile=RequestLimitProfile(
        requests_per_second=1000, requests_per_minute=60000, burst=1000, max_retries=1,
    )), expected_revision=0)

    def scope_factory(**kwargs):
        env.scope_budgets.append(kwargs["max_requests"])
        return outbound_scope(clock=limiter._clock, monotonic=limiter._monotonic, **kwargs)

    def handle(request):
        env.calls.append(request)
        assert request.method == "GET" and not request.content
        if request.url.host == "api.frankfurter.dev":
            assert request.url.path == "/v2/providers/ecb/rates"
            assert request.url.params["base"] == "USD"
            assert request.url.params["quotes"] == "EUR"
            if env.fx_payload is not None:
                return httpx.Response(200, json=env.fx_payload)
            start = date.fromisoformat(request.url.params["from"])
            end = date.fromisoformat(request.url.params["to"])
            return httpx.Response(200, json=[
                {"base": "USD", "quote": "EUR", "date": (start + timedelta(days=i)).isoformat(),
                 "rate": "0.92"}
                for i in range((end - start).days + 1)
            ])
        if request.url.host == "coins.llama.fi":
            if request.url.path == "/batchHistorical":
                assert request.url.params["searchWidth"] == "1h"
                env.batch_count += 1
                coins = json.loads(request.url.params["coins"])
                return httpx.Response(200, json=env.batch_payload(coins, env.batch_count))
            parts = request.url.path.split("/")
            assert parts[1:3] == ["prices", "historical"]
            return httpx.Response(200, json={"coins": {} if env.legacy_missing else {
                parts[4]: quote(int(parts[3])),
            }})
        pytest.fail(f"Nicht gemockter Provider: {request.url.host}{request.url.path}")

    transport = httpx.MockTransport(handle)
    env.client_factory = lambda **kwargs: managed_client(
        transport=transport, limiter=limiter, clock=limiter._clock,
        monotonic=limiter._monotonic, **kwargs,
    )
    env.scope_factory = scope_factory
    monkeypatch.setattr(module, "outbound_scope", scope_factory)
    monkeypatch.setattr(module, "managed_client", env.client_factory)
    app = FastAPI()
    app.include_router(build_historical_prices_router(
        store, lambda: env.applied_callbacks.append(True),
    ))
    with TestClient(app) as client:
        env.client = client
        yield env


def automatic_fetch(env, **kwargs):
    query = {"scope": "all_observed", "strategy": "automatic", **kwargs}
    planned = data(env.client.post(BASE + "/plan", json=query))
    request = {**query, "request_id": str(uuid4()), "plan_sha256": planned["plan_sha256"],
               "confirm_external_request": True}
    return request, data(env.client.post(BASE + "/previews", json=request))


def continue_automatic(env, preview):
    return data(env.client.post(
        BASE + f"/previews/{preview['id']}/continue", json=continuation(preview),
    ))


def add_observation(env, *, asset="SOL", at=AT, kind="reward", mint=None, source="synthetic"):
    raw_id = None
    if mint is not None:
        batch = env.store.create_import_batch(ImportBatchCreate(source="solana_rpc"))
        raw = env.store.add_raw_object(batch.batch_id, RawObjectCreate(
            payload_json=json.dumps({"mint": mint, "history_mapper_version": "2"}),
        ))
        raw_id = raw.raw_object_id
    return env.store.add_canonical_event(CanonicalEventCreate(
        source="solana_rpc" if mint is not None else source,
        source_ref=f"automatic-{uuid4()}", asset=asset, quantity=Decimal("1"),
        event_time=at, event_type=kind, raw_object_id=raw_id,
    ))


def native_mapping(env):
    env.mappings["SOL"] = {"asset": "SOL", "defillama_id": SOL_PROVIDER,
                           "coingecko_id": "wrapped-solana"}


def points(request):
    return json.loads(request.url.params["coins"])


def target_for(row):
    midnight = datetime.combine(date.fromisoformat(row["price_date"]), time(), UTC)
    return int(max(midnight, datetime.fromisoformat(row["first_event_at"]) - timedelta(minutes=30)).timestamp())


def nearby_for(row):
    target = target_for(row)
    midnight = int(datetime.combine(date.fromisoformat(row["price_date"]), time(), UTC).timestamp())
    latest = int(datetime.fromisoformat(row["first_event_at"]).timestamp()) - 1
    return sorted({max(midnight, min(latest, target + delta)) for delta in (-1800, 900, 1800)})


def assert_provenance(env, preview, row, resolved):
    assert row["resolved_provider_id"] == resolved
    attempts = row["lookup_attempts"]
    assert attempts
    known = {entry["sha256"] for entry in preview["evidence"]}
    attempted_hashes = set()
    for attempt in attempts:
        assert {"provider_id", "search", "status", "reason", "evidence_sha256"} <= attempt.keys()
        assert attempt["search"] in {"primary", "nearby", "native_sol"}
        hashes = attempt["evidence_sha256"]
        assert isinstance(hashes, list) and hashes
        assert set(hashes) <= known
        attempted_hashes.update(hashes)
    fx_hash = preview["fx_series"][row["price_date"][:4]]["sha256"]
    assert set(row["evidence_sha256"]) == attempted_hashes | {fx_hash}
    assert f":{resolved}:day:{row['price_date']}:evidence:" in row["source"]
    identity = hashlib.sha256(canonical_json(row["evidence_sha256"]).encode()).hexdigest()
    assert row["source"].endswith(identity)
    assert any(item["source"] == row["source"] for item in preview["prices"])
    for sha in row["evidence_sha256"]:
        body = env.service._path("evidence", sha + ".body").read_bytes()
        assert hashlib.sha256(body).hexdigest() == sha


def test_strategy_is_additive_and_total_budget_is_optional():
    default = HistoricalPriceQuery()
    assert default.strategy == "standard"
    assert default.max_total_requests is None
    for budget in (1, 1000):
        query = HistoricalPriceQuery(strategy="automatic", max_total_requests=budget)
        assert query.strategy == "automatic" and query.max_total_requests == budget


@pytest.mark.parametrize("query", [
    {"strategy": "invented"}, {"max_total_requests": 0}, {"max_total_requests": 1001},
])
def test_invalid_strategy_or_total_budget_is_rejected_without_http(automatic_workflow, query):
    env = automatic_workflow
    with pytest.raises(ValidationError):
        HistoricalPriceQuery(**query)
    assert env.client.post(BASE + "/plan", json=query).status_code == 422
    assert not env.calls


@pytest.mark.parametrize("scope", ["all_observed", "tax_required"])
def test_automatic_primary_is_one_anchor_and_both_scopes_use_collector(automatic_workflow, monkeypatch, scope):
    env = automatic_workflow
    seed(env, kind="reward")

    def legacy_quote(*args, **kwargs):
        pytest.fail("automatic darf den alten Einzelquote-Pfad nicht benutzen")

    monkeypatch.setattr(HistoricalPriceService, "_quote", legacy_quote)
    before = source_snapshot(env)
    _, preview = automatic_fetch(env, scope=scope)
    row, = preview["rows"]
    assert preview["prices_count"] == 1 and preview["pending_count"] == 0
    assert preview["requests_started"] == len(env.calls) == 2
    request, = batches(env)
    assert points(request) == {row["provider_id"]: [target_for(row)]}
    assert [item["search"] for item in row["lookup_attempts"]] == ["primary"]
    assert Decimal(row["price_eur"]) == Decimal("138")
    assert row["provider_id"] == "coingecko:workflow-token000"
    assert_provenance(env, preview, row, row["provider_id"])
    assert source_snapshot(env) == before and not env.store.list_price_points()


def test_tax_standard_retains_legacy_single_quote_and_no_automatic_retry(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env)
    env.legacy_missing = True
    _, preview = automatic_fetch(env, scope="tax_required", strategy="standard")
    assert preview["prices_count"] == 0
    assert preview["rows"][0]["status"] == "open"
    assert not batches(env)
    assert len(env.calls) == 1
    assert env.calls[0].url.path.endswith("/" + SOL_PROVIDER)
    assert not env.store.list_price_points()


def test_tax_standard_honors_optional_total_budget_without_changing_single_quote_path(automatic_workflow):
    env = automatic_workflow
    seed(env, kind="reward")
    _, preview = automatic_fetch(
        env, scope="tax_required", strategy="standard", max_requests=50, max_total_requests=1,
    )
    assert preview["requests_started"] == len(env.calls) == 1
    assert env.scope_budgets == [1]
    assert preview["prices_count"] == 0
    assert preview["rows"][0]["status"] == "open"
    assert env.calls[0].url.host == "coins.llama.fi"
    assert "/prices/historical/" in env.calls[0].url.path
    assert not batches(env) and not env.store.list_price_points()


def test_all_observed_standard_missing_primary_does_not_escalate_to_fallback(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env)
    env.batch_payload = lambda coins, number: {"coins": {}}
    _, preview = automatic_fetch(env, strategy="standard", max_requests=50)
    row, = preview["rows"]
    assert preview["prices_count"] == preview["pending_count"] == 0
    assert preview["open_count"] == 1 and preview["collection_complete"] is True
    assert row["status"] == "open" and row["reason"] == "historical_price_quote_missing"
    assert preview["requests_started"] == len(env.calls) == 2
    request, = batches(env)
    assert points(request) == {SOL_PROVIDER: [target_for(row)]}
    assert [attempt["search"] for attempt in row["lookup_attempts"]] == ["primary"]
    assert row.get("resolved_provider_id") is None
    assert not env.store.list_price_points()


@pytest.mark.parametrize("scope", ["all_observed", "tax_required"])
def test_missing_wrapped_sol_primary_resolves_all_twenty_days_in_second_batch(automatic_workflow, scope):
    env = automatic_workflow
    native_mapping(env)
    native_targets = {
        int((AT + timedelta(days=offset, minutes=-30)).timestamp()) for offset in range(20)
    }
    for offset in range(20):
        add_observation(env, at=AT + timedelta(days=offset), kind="fee", source="solana_rpc")

    def payload(coins, number):
        if number == 1:
            return {"coins": {}}
        return echoed({
            key: [instant for instant in values if instant in native_targets]
            for key, values in coins.items() if key == "coingecko:solana"
        })

    env.batch_payload = payload
    before = source_snapshot(env)
    _, preview = automatic_fetch(env, scope=scope)
    assert preview["total_rows"] == preview["prices_count"] == 20
    assert preview["pending_count"] == preview["open_count"] == 0
    assert preview["collection_complete"] is True
    primary, fallback = batches(env)
    assert preview["requests_started"] == len(env.calls) == 3
    assert set(points(primary)) == {SOL_PROVIDER}
    assert len(points(primary)[SOL_PROVIDER]) == 20
    assert set(points(fallback)) == {SOL_PROVIDER, "coingecko:solana"}
    assert points(fallback)[SOL_PROVIDER] == sorted({
        instant for row in preview["rows"] for instant in nearby_for(row)
    })
    assert points(fallback)["coingecko:solana"] == sorted(native_targets | {
        instant for row in preview["rows"] for instant in nearby_for(row)
    })
    for row in preview["rows"]:
        assert row["provider_id"] == SOL_PROVIDER
        assert row["status"] == "fetched" and row["reason"] is None
        assert Decimal(row["price_eur"]) == Decimal("138")
        assert row["priced_at"] == datetime.fromtimestamp(target_for(row), UTC).isoformat()
        assert row["lookup_attempts"][0]["reason"] == "historical_price_quote_missing"
        assert {item["search"] for item in row["lookup_attempts"]} == {"primary", "nearby", "native_sol"}
        assert_provenance(env, preview, row, "coingecko:solana")
    assert source_snapshot(env) == before and not env.store.list_price_points()


@pytest.mark.parametrize("primary_failure", ["missing", "timestamp_mismatch"])
def test_nearby_earlier_quote_is_used_with_original_provider_and_all_evidence(automatic_workflow, primary_failure):
    env = automatic_workflow
    seed(env)
    original = int((AT - timedelta(minutes=30)).timestamp())

    def payload(coins, number):
        if number == 1:
            return {"coins": {}} if primary_failure == "missing" else {
                "coins": {key: {"prices": [quote(original + 1801)]} for key in coins},
            }
        return {"coins": {key: {"prices": [quote(original - 1800, "151")]} for key in coins}}

    env.batch_payload = payload
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert preview["prices_count"] == 1 and preview["open_count"] == 0
    assert row["priced_at"] == datetime.fromtimestamp(original - 1800, UTC).isoformat()
    assert Decimal(row["price_eur"]) == Decimal("138.92")
    primary, fallback = batches(env)
    assert points(primary) == {row["provider_id"]: [original]}
    assert points(fallback) == {row["provider_id"]: nearby_for(row)}
    assert [item["search"] for item in row["lookup_attempts"]] == ["primary", "nearby"]
    assert row["lookup_attempts"][0]["reason"] == "historical_price_" + (
        "quote_missing" if primary_failure == "missing" else "timestamp_mismatch"
    )
    assert_provenance(env, preview, row, row["provider_id"])


@pytest.mark.parametrize("delta", [-3600, -1800, 0, 1800])
def test_fallback_accepts_original_time_boundaries_and_minimum_confidence(automatic_workflow, delta):
    env = automatic_workflow
    seed(env)
    instant = int((AT - timedelta(minutes=30)).timestamp()) + delta
    env.batch_payload = lambda coins, number: {"coins": {}} if number == 1 else {
        "coins": {key: {"prices": [quote(instant, confidence="0.95")]} for key in coins},
    }
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert row["status"] == "fetched" and preview["prices_count"] == 1
    assert row["priced_at"] == datetime.fromtimestamp(instant, UTC).isoformat()
    assert Decimal(row["price_eur"]) == Decimal("138")


def test_mixed_batch_retries_only_missing_or_mismatched_not_successful_or_conflicting_rows(automatic_workflow):
    env = automatic_workflow
    seed(env, 4)
    target = int((AT - timedelta(minutes=30)).timestamp())
    identifiers = [f"coingecko:workflow-token{i:03d}" for i in range(4)]

    def payload(coins, number):
        if number == 1:
            return {"coins": {
                identifiers[0]: {"prices": [quote(target)]},
                identifiers[2]: {"prices": [quote(int(AT.timestamp()) + 1)]},
                identifiers[3]: {"prices": [quote(target), quote(target, "151")]},
            }}
        assert set(coins) == {identifiers[1], identifiers[2]}
        return echoed(coins)

    env.batch_payload = payload
    _, preview = automatic_fetch(env)
    rows = {row["asset"]: row for row in preview["rows"]}
    assert preview["prices_count"] == 3 and preview["open_count"] == 1
    assert preview["pending_count"] == 0 and len(batches(env)) == 2
    assert preview["requests_started"] == len(env.calls) == 3
    assert rows["TOKEN003"]["reason"] == "historical_price_quote_conflict"
    for asset in ("TOKEN000", "TOKEN003"):
        assert [attempt["search"] for attempt in rows[asset]["lookup_attempts"]] == ["primary"]
    for asset in ("TOKEN001", "TOKEN002"):
        assert [attempt["search"] for attempt in rows[asset]["lookup_attempts"]] == ["primary", "nearby"]


@pytest.mark.parametrize("seconds", [1, 600, 1799, 1800])
def test_nearby_targets_are_deduplicated_and_clamped_to_same_day_before_first_event(automatic_workflow, seconds):
    env = automatic_workflow
    midnight = AT.replace(hour=0)
    at = midnight + timedelta(seconds=seconds)
    seed(env, at=at)

    def payload(coins, number):
        if number == 1:
            return {"coins": {}}
        return {"coins": {key: {"prices": [quote(int(midnight.timestamp()))]} for key in coins}}

    env.batch_payload = payload
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    primary, fallback = batches(env)
    assert points(primary) == {row["provider_id"]: [target_for(row)]}
    assert points(fallback) == {row["provider_id"]: nearby_for(row)}
    for instant in points(fallback)[row["provider_id"]]:
        assert midnight.timestamp() <= instant <= at.timestamp() - 1
    assert row["status"] == "fetched"
    assert row["priced_at"] == midnight.isoformat()


@pytest.mark.parametrize("bad_quote", [
    "too_late", "previous_utc_day", "outside_original_hour", "low_confidence",
    "nan_confidence", "nan_price", "negative_price", "zero_price", "infinite_price", "conflict",
])
def test_fallback_never_uses_invalid_quotes_even_from_native_sol(automatic_workflow, bad_quote):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env)
    target = int((AT - timedelta(minutes=30)).timestamp())
    instant = {
        "too_late": int(AT.timestamp()) + 1,
        "previous_utc_day": int(AT.replace(hour=0).timestamp()) - 1,
        "outside_original_hour": target - 3601,
    }.get(bad_quote, target)
    price = {"nan_price": "NaN", "negative_price": "-1", "zero_price": "0",
             "infinite_price": "Infinity"}.get(bad_quote, "150")
    confidence = {"low_confidence": "0.949999", "nan_confidence": "NaN"}.get(bad_quote, "0.99")

    def payload(coins, number):
        if number == 1:
            if bad_quote == "too_late":
                return {"coins": {key: {"prices": [quote(instant)]} for key in coins}}
            return {"coins": {}}
        items = [quote(instant, price, confidence)]
        if bad_quote == "conflict":
            items.append(quote(instant, "151"))
        return {"coins": {key: {"prices": items} for key in coins}}

    env.batch_payload = payload
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert len(batches(env)) == 2
    assert preview["prices_count"] == preview["pending_count"] == 0
    assert preview["open_count"] == 1 and preview["collection_complete"] is True
    assert row["status"] == "open" and row["reason"]
    assert row.get("resolved_provider_id") is None
    assert row.get("price_eur") is None and row.get("source") is None
    assert row["lookup_attempts"][0]["search"] == "primary"
    assert not env.store.list_price_points()


def test_conflicting_primary_quote_is_not_silently_replaced_by_native_alias(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env)

    def payload(coins, number):
        if number != 1:
            pytest.fail("Ein Quote-Konflikt darf keinen automatischen Aliaswechsel ausloesen")
        return {"coins": {key: {"prices": [quote(instant, "150"), quote(instant, "151")
                                           ]} for key, (instant,) in coins.items()}}

    env.batch_payload = payload
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert row["status"] == "open" and row["reason"] == "historical_price_quote_conflict"
    assert preview["prices_count"] == 0 and len(batches(env)) == 1
    assert row.get("resolved_provider_id") is None


def test_unknown_original_mint_stays_explicitly_open_without_symbol_or_native_alias(automatic_workflow):
    env = automatic_workflow
    env.mappings["RARE"] = {"asset": "RARE", "coingecko_id": "arbitrary-symbol-alias"}
    add_observation(env, asset="RARE", kind="transfer", mint=MINT)
    env.batch_payload = lambda coins, number: {"coins": {}}
    before = source_snapshot(env)
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert row["mint"] == MINT and row["provider_id"] == "solana:" + MINT
    assert row["status"] == "open" and row["reason"]
    assert preview["open_count"] == 1 and preview["pending_count"] == preview["prices_count"] == 0
    primary, fallback = batches(env)
    assert set(points(primary)) == set(points(fallback)) == {"solana:" + MINT}
    assert points(primary)["solana:" + MINT] == [target_for(row)]
    assert points(fallback)["solana:" + MINT] == nearby_for(row)
    assert {item["search"] for item in row["lookup_attempts"]} == {"primary", "nearby"}
    assert row.get("resolved_provider_id") is None
    assert source_snapshot(env) == before and not env.store.list_price_points()


def test_sol_symbol_with_foreign_raw_mint_is_blocked_before_any_request(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env, mint=MINT)
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert row["status"] == "blocked" and row["reason"] == "solana_mint_identity_mismatch"
    assert preview["prices_count"] == 0 and not env.calls


@pytest.mark.parametrize("asset,provider,mints,basis,native_fee,expected", [
    ("SOL", SOL_PROVIDER, [], "native_sol_reference", False, True),
    ("SOL", SOL_PROVIDER, [WSOL], "original_mint", False, False),
    ("SOL", "coingecko:wrapped-solana", [], "native_sol_reference", False, True),
    ("SOL", "coingecko:wrapped-solana", [WSOL], "original_mint", False, False),
    ("SOL", SOL_PROVIDER, [WSOL], "original_mint", True, True),
    ("SOL", "coingecko:wrapped-solana", [WSOL], "original_mint", True, True),
    ("SOL", SOL_PROVIDER, [], "configured_mapping", True, True),
    ("RARE", SOL_PROVIDER, [WSOL], "original_mint", False, False),
    ("SOL", "solana:" + MINT, [], "native_sol_reference", False, False),
    ("SOL", SOL_PROVIDER, [MINT], "original_mint", False, False),
    ("SOL", SOL_PROVIDER, [MINT, WSOL], "original_mint", False, False),
    ("SOL", SOL_PROVIDER, [MINT], "native_sol_reference", True, False),
    ("SOL", "coingecko:arbitrary-sol-alias", [], "native_sol_reference", False, False),
], ids=[
    "native-reference", "wsol-mint-is-not-native", "wrapped-native-reference", "no-wrapped-parity-alias",
    "verified-native-fee-wsol", "verified-native-fee-wrapped", "verified-native-fee-no-mint",
    "foreign-symbol", "foreign-provider", "foreign-mint", "conflicting-mints",
    "fee-does-not-override-foreign-mint", "no-arbitrary-alias",
])
def test_native_sol_fallback_requires_exact_asset_provider_and_raw_identity(
    asset, provider, mints, basis, native_fee, expected,
):
    row = {"asset": asset, "provider_id": provider, "mints": mints,
           "identity_basis": basis, "sources": ["solana_rpc"] if native_fee else ["synthetic"],
           "event_types": ["fee"] if native_fee else ["transfer"]}
    candidates = fallback_candidates(row)
    assert candidates == [(provider, "nearby")] + (
        [("coingecko:solana", "native_sol")] if expected else []
    )


def test_original_wsol_mint_without_native_fee_must_not_use_native_sol_parity(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env, mint=WSOL)
    env.batch_payload = lambda coins, number: {"coins": {}} if number == 1 else echoed({
        key: values for key, values in coins.items() if key == "coingecko:solana"
    })
    _, preview = automatic_fetch(env)
    row, = preview["rows"]
    assert row["mint"] == WSOL and row["mints"] == [WSOL]
    assert row["provider_id"] == SOL_PROVIDER
    assert row["status"] == "open" and preview["prices_count"] == 0
    assert row.get("resolved_provider_id") is None
    assert all(set(points(request)) == {SOL_PROVIDER} for request in batches(env))
    assert {item["search"] for item in row["lookup_attempts"]} == {"primary", "nearby"}


@pytest.mark.parametrize("provider", [SOL_PROVIDER, "coingecko:wrapped-solana"])
def test_verified_native_fee_with_original_wsol_mint_can_resolve_native_sol(automatic_workflow, provider):
    env = automatic_workflow
    native_mapping(env)
    env.mappings["SOL"]["defillama_id"] = provider if provider == SOL_PROVIDER else None
    add_observation(env, mint=WSOL, kind="fee")
    env.batch_payload = lambda coins, number: {"coins": {}} if number == 1 else echoed({
        key: values for key, values in coins.items() if key == "coingecko:solana"
    })
    _, preview = automatic_fetch(env, scope="tax_required")
    row, = preview["rows"]
    assert row["provider_id"] == provider
    assert row["status"] == "fetched" and preview["prices_count"] == 1
    assert_provenance(env, preview, row, "coingecko:solana")


def test_tax_native_fee_with_foreign_original_mint_must_not_use_native_fallback(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    add_observation(env, mint=MINT, kind="fee")
    env.batch_payload = lambda coins, number: {"coins": {}} if number == 1 else echoed({
        key: values for key, values in coins.items() if key == "coingecko:solana"
    })
    _, preview = automatic_fetch(env, scope="tax_required")
    row, = preview["rows"]
    assert preview["prices_count"] == 0
    assert row["status"] == "blocked" and row["reason"] == "solana_mint_identity_mismatch"
    assert row.get("resolved_provider_id") is None
    assert not env.calls
    assert not env.store.list_price_points()


def test_budget_after_primary_keeps_fallback_pending_and_continuation_reuses_fx(automatic_workflow):
    env = automatic_workflow
    native_mapping(env)
    for offset in range(20):
        add_observation(env, at=AT + timedelta(days=offset))
    env.batch_payload = lambda coins, number: {"coins": {}} if number == 1 else echoed({
        key: values for key, values in coins.items() if key == "coingecko:solana"
    })
    before = source_snapshot(env)
    request, first = automatic_fetch(env, max_requests=2)
    assert first["requests_started"] == first["section_requests_started"] == len(env.calls) == 2
    assert first["pending_count"] == 20 and first["open_count"] == first["prices_count"] == 0
    assert first["collection_complete"] is False
    for row in first["rows"]:
        assert row["status"] == "pending" and row["lookup_stage"] == "fallback"
        assert [item["search"] for item in row["lookup_attempts"]] == ["primary"]
    assert data(env.client.post(BASE + "/previews", json=request)) == first
    assert len(env.calls) == 2
    blocked = env.client.post(BASE + f"/previews/{first['id']}/apply", json=approval(first))
    assert blocked.status_code == 409, blocked.text
    assert len(env.calls) == 2 and not env.applied_callbacks
    second = continue_automatic(env, first)
    assert second["section_requests_started"] == 1
    assert second["requests_started"] == len(env.calls) == 3
    assert second["prices_count"] == 20 and second["pending_count"] == second["open_count"] == 0
    assert second["collection_complete"] is True
    assert second["fx_series"] == first["fx_series"]
    assert len([call for call in env.calls if call.url.host == "api.frankfurter.dev"]) == 1
    primary, fallback = batches(env)
    assert not set(requested_points([primary])) & set(
        (identifier, instant) for identifier, instant in requested_points([fallback])
        if identifier == SOL_PROVIDER
    )
    for old, row in zip(first["rows"], second["rows"], strict=True):
        assert row["lookup_attempts"][0] == old["lookup_attempts"][0]
        assert [item["search"] for item in row["lookup_attempts"]].count("primary") == 1
        assert_provenance(env, second, row, "coingecko:solana")
    assert source_snapshot(env) == before and not env.store.list_price_points()


@pytest.mark.parametrize("total", [1, 2])
def test_total_budget_caps_first_section_and_exhausted_continuation_starts_no_http(automatic_workflow, total):
    env = automatic_workflow
    seed(env, 30)
    env.batch_payload = lambda coins, number: {"coins": {}}
    _, preview = automatic_fetch(env, max_requests=50, max_total_requests=total)
    assert preview["requests_started"] == preview["section_requests_started"] == len(env.calls) == total
    assert env.scope_budgets == [total]
    assert preview["pending_count"] == 30 and preview["prices_count"] == 0
    count = len(env.calls)
    before = source_snapshot(env)
    error(env.client.post(BASE + f"/previews/{preview['id']}/continue", json=continuation(preview)),
          "historical_price_total_budget_exhausted")
    assert len(env.calls) == count and env.scope_budgets == [total]
    assert source_snapshot(env) == before and not env.store.list_price_points()


@pytest.mark.parametrize("scope", ["all_observed", "tax_required"])
def test_continuation_section_uses_remaining_total_budget_not_full_section_budget(automatic_workflow, scope):
    env = automatic_workflow
    seed(env, kind="reward")
    env.batch_payload = lambda coins, number: {"coins": {}} if number == 1 else echoed(coins)
    _, first = automatic_fetch(env, scope=scope, max_requests=2, max_total_requests=3)
    assert first["pending_count"] == 1 and first["requests_started"] == 2
    last = continue_automatic(env, first)
    assert env.scope_budgets == [2, 1]
    assert last["requests_started"] == len(env.calls) == 3
    assert last["section_requests_started"] == 1
    assert last["prices_count"] == 1 and last["pending_count"] == 0
    assert len(batches(env)) == 2
    assert len([call for call in env.calls if call.url.host == "api.frankfurter.dev"]) == 1


def test_default_automatic_section_finishes_more_than_fifty_new_requirements(automatic_workflow):
    env = automatic_workflow
    seed(env, 61)
    env.batch_payload = lambda coins, number: {"coins": {}} if number % 2 else echoed(coins)
    _, preview = automatic_fetch(env)
    assert preview["total_rows"] == preview["prices_count"] == 61
    assert preview["pending_count"] == preview["open_count"] == 0
    assert preview["collection_complete"] is True
    assert preview["requests_started"] == len(env.calls) == 7
    assert len(batches(env)) == 6
    assert not env.store.list_price_points()


def test_fx_day_failure_does_not_poison_cached_year_for_later_valid_day(automatic_workflow):
    env = automatic_workflow
    seed(env, at=AT)
    seed(env, at=AT + timedelta(days=2))
    env.fx_payload = [{"base": "USD", "quote": "EUR", "date": "2024-06-03", "rate": "0.92"}]
    _, preview = automatic_fetch(env)
    first, later = sorted(preview["rows"], key=lambda row: row["price_date"])
    assert first["price_date"] == "2024-06-02"
    assert first["status"] == "open" and first["reason"] == "historical_price_fx_date_invalid"
    assert first.get("price_eur") is None and first.get("resolved_provider_id") is None
    assert later["price_date"] == "2024-06-04" and later["status"] == "fetched"
    assert later["fx_date"] == "2024-06-03" and Decimal(later["price_eur"]) == Decimal("138")
    assert preview["prices_count"] == preview["open_count"] == 1
    assert preview["pending_count"] == 0 and preview["collection_complete"] is True
    assert preview["requests_started"] == len(env.calls) == 2
    assert len([call for call in env.calls if call.url.host == "api.frankfurter.dev"]) == 1
    request, = batches(env)
    assert points(request) == {later["provider_id"]: [target_for(later)]}
    assert_provenance(env, preview, later, later["provider_id"])
    assert not env.store.list_price_points()
