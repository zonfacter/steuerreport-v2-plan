"""G08/G09: echte Preisconsumer mit synthetischen HTTP-Originalantworten."""

from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import unquote

import httpx
import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceFetch, HistoricalPriceQuery, PriceMapping
from steuerreport_v2.contracts.prices import AsOfPriceGateBackfillRequest
from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as module
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.external_http import managed_client, outbound_scope
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.bmf_event_price_remediation import BmfEventPriceRemediationService
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.domain.request_limits import RequestLimiter
from steuerreport_v2.domain.v1_fx_cache_importer import V1FxCacheImporter
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


TOLERANCE = Decimal("0.00000000000000001")


def quote(day="2024-05-31", base="USD", target="EUR", rate="0.9"):
    return {"date": day, "base": base, "quote": target, "rate": rate}


def reference_metadata(source):
    return json.loads(unquote(source.split(":fxref:", 1)[1]))


@pytest.fixture
def consumer(tmp_path, monkeypatch):
    env = SimpleNamespace(calls=[], payload=[], day=date(2024, 6, 2), mode="single", retry=False)
    env.store = DuckDbStore(tmp_path / "fx-consumer.duckdb")
    env.service = HistoricalPriceService(env.store)
    env.service.save_mapping(PriceMapping(asset="BTC", defillama_id="coingecko:bitcoin"))
    clock = [1_000_000.0]
    limiter = RequestLimiter(state_root=tmp_path / "limits", clock=lambda: clock[0],
        monotonic=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0] + delay))
    limiter.write_config(RequestLimitsConfig(default_profile=RequestLimitProfile(
        requests_per_second=1000, requests_per_minute=60000, burst=1000, max_retries=1)), expected_revision=0)

    def handle(request):
        env.calls.append(request)
        if request.url.host == "api.frankfurter.dev":
            if env.retry:
                return httpx.Response(429, json={"error": "synthetic retry"})
            return httpx.Response(200, json=env.payload)
        assert request.url.host == "coins.llama.fi"
        if request.url.path == "/batchHistorical":
            coins = json.loads(request.url.params["coins"])
            return httpx.Response(200, json={"coins": {key: {"prices": [
                {"timestamp": instant, "price": "100", "confidence": "0.99"}
                for instant in instants]} for key, instants in coins.items()}})
        instant = int(request.url.path.split("/")[3])
        return httpx.Response(200, json={"coins": {"coingecko:bitcoin": {"timestamp": instant, "price": "100"}}})

    monkeypatch.setattr(module, "managed_client", lambda **kwargs: managed_client(
        transport=httpx.MockTransport(handle), limiter=limiter, clock=limiter._clock,
        monotonic=limiter._monotonic, **kwargs))
    monkeypatch.setattr(module, "outbound_scope", lambda **kwargs: outbound_scope(
        clock=limiter._clock, monotonic=limiter._monotonic, **kwargs))

    def fetch(*, days=None, budget=4):
        for day in days or [env.day]:
            env.store.add_canonical_event(CanonicalEventCreate(
                source="synthetic-fx", source_ref="fx-" + day.isoformat(), event_type="income",
                event_time=datetime.combine(day, time(12), timezone.utc), asset="BTC", quantity=Decimal("1")))
        query = HistoricalPriceQuery(scope="all_observed" if env.mode == "batch" else "tax_required",
                                     assets=["BTC"], max_requests=budget)
        plan = env.service.plan(query)
        before = env.service._revision()
        request = HistoricalPriceFetch(**query.model_dump(), request_id=uuid4(),
                                      plan_sha256=plan["plan_sha256"], confirm_external_request=True)
        result = env.service.fetch(request)
        assert env.service._revision() == before
        assert env.store.list_price_points() == []
        return result

    env.fetch = fetch
    return env


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("base,target,rate", [("USD", "EUR", "0.9"), ("EUR", "USD", "1.111111111111111111")])
def test_G08_real_consumer_both_quotation_directions(consumer, mode, base, target, rate):
    consumer.mode = mode
    consumer.payload = [quote(base=base, target=target, rate=rate)]
    result = consumer.fetch()
    assert result["prices_count"] == 1
    row = result["rows"][0]
    assert row["status"] == "fetched"
    assert abs(Decimal(row["price_eur"]) - Decimal("90")) <= TOLERANCE
    assert row["fx_date"] == "2024-05-31"
    assert result["requests_started"] == len(consumer.calls) == 2
    fx = next(item for item in result["evidence"] if item["provider"] == "fx")
    body = consumer.service._path("evidence", fx["sha256"] + ".body").read_bytes()
    assert hashlib.sha256(body).hexdigest() == fx["sha256"]
    assert json.loads(body) == consumer.payload  # Original pair and exact rate string retained.
    assert fx["sha256"] in row["evidence_sha256"]
    assert fx["url"].endswith("/providers/ecb/rates")
    assert "evidence:" in row["source"]


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("day,reference", [
    ("2024-06-01", "2024-05-31"),  # Saturday.
    ("2024-06-02", "2024-05-31"),  # Sunday.
    ("2024-04-01", "2024-03-28"),  # Easter Monday after Good Friday, supplied evidence.
    ("2024-06-07", "2024-05-31"),  # Inclusive technical seven-calendar-day boundary.
])
def test_G09_bounded_reference_day_through_real_consumer(consumer, mode, day, reference):
    consumer.mode, consumer.day = mode, date.fromisoformat(day)
    consumer.payload = [quote(day=reference)]
    result = consumer.fetch()
    assert result["prices_count"] == 1
    assert result["rows"][0]["fx_date"] == reference
    assert Decimal(result["rows"][0]["price_eur"]) == Decimal("90")


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("payload", [
    [], [quote(day="2024-06-03")], [quote(day="2024-05-25")],
    [quote(rate="0")], [quote(rate="-0.9")], [quote(rate="NaN")], [quote(rate="Infinity")],
    [quote(base="GBP")], [quote(target="JPY")],
    [{"base": "USD", "quote": "EUR", "rate": "0.9"}],
    [quote(), quote(rate="0.8")],
])
def test_G09_missing_future_stale_or_conflicting_fx_never_becomes_one(consumer, mode, payload):
    consumer.mode, consumer.payload = mode, payload
    result = consumer.fetch()
    assert result["prices_count"] == 0
    assert result["rows"][0]["status"] == "open"
    assert result["rows"][0].get("price_eur") is None
    assert result["rows"][0]["reason"].startswith("historical_price_")
    assert result["requests_started"] == len(consumer.calls)


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_G09_mixed_series_selects_latest_admissible_never_future(consumer, mode):
    consumer.mode = mode
    consumer.payload = [quote(day="2024-06-03", rate="99"), quote(), quote(day="2024-05-30", rate="0.8")]
    result = consumer.fetch()
    assert result["rows"][0]["fx_date"] == "2024-05-31"
    assert Decimal(result["rows"][0]["price_eur"]) == Decimal("90")


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_G09_fx_and_retries_obey_existing_transport_budget(consumer, mode):
    consumer.mode, consumer.payload, consumer.retry = mode, [quote()], True
    result = consumer.fetch(budget=2)
    assert result["requests_started"] == len(consumer.calls) == 2
    assert result["prices_count"] == 0


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_G09_inverse_cache_reuse_adds_no_fx_request(consumer, mode):
    consumer.mode = mode
    consumer.payload = [quote(base="EUR", target="USD", rate="1.111111111111111111")]
    result = consumer.fetch(days=[date(2024, 6, 1), date(2024, 6, 2)])
    assert result["prices_count"] == 2
    assert all(abs(Decimal(row["price_eur"]) - Decimal("90")) <= TOLERANCE for row in result["rows"])
    # Single path caches by requested day, batch path reuses its one yearly raw series.
    expected_fx = 1 if mode == "batch" else 2
    assert sum(call.url.host == "api.frankfurter.dev" for call in consumer.calls) == expected_fx
    assert result["requests_started"] == len(consumer.calls)


def legacy_cache(tmp_path, *, pair=("USD", "EUR"), rate="0.9", recorded="2024-06-02", reference="2024-05-31"):
    path = tmp_path / "legacy-fx.sqlite"
    with sqlite3.connect(path) as con:
        con.execute("create table fx_cache (rate_date text, base_ccy text, quote_ccy text, rate text, source text, source_rate_date text)")
        con.execute("insert into fx_cache values (?, 'BTC', 'USD', '100', 'fixture:crypto-usd', ?)", (recorded, recorded))
        con.execute("insert into fx_cache values (?, ?, ?, ?, 'fixture:ecb', ?)", (recorded, *pair, rate, reference))
    return path


def legacy_store(tmp_path):
    store = DuckDbStore(tmp_path / "legacy-consumer.duckdb")
    store.add_canonical_event(CanonicalEventCreate(source="synthetic-fx", asset="BTC", quantity=Decimal("1"),
        event_type="income", event_time=datetime(2024, 6, 2, 12, tzinfo=timezone.utc)))
    return store


@pytest.mark.parametrize("pair,rate", [(("USD", "EUR"), "0.9"), (("EUR", "USD"), "1.111111111111111111")])
def test_G08_legacy_importer_consumes_both_directions_with_original_reference(tmp_path, pair, rate):
    store = legacy_store(tmp_path)
    cache = legacy_cache(tmp_path, pair=pair, rate=rate)
    before = hashlib.sha256(cache.read_bytes()).hexdigest()
    service = ExternalPriceBackfillService(store)
    fx = service._usd_eur_reference(str(cache), "2024-06-02")
    assert fx.original_base == pair[0] and fx.original_quote == pair[1]
    assert fx.original_rate == Decimal(rate)
    assert fx.reference_date == date(2024, 5, 31)
    assert fx.source == "fixture:ecb"
    assert service._usd_eur_rate(str(cache), "2024-06-02") == fx.rate_eur_per_usd
    preview, points = V1FxCacheImporter(store).to_price_points(str(cache), Decimal("1"))
    assert preview.importable_count == len(points) == 1
    assert abs(points[0].price_eur - Decimal("90")) <= TOLERANCE
    assert preview.importable[0].source_rate_date == "2024-05-31"
    assert reference_metadata(points[0].source) == {
        "base": pair[0], "quote": pair[1], "rate": rate, "source": "fixture:ecb",
        "reference_date": "2024-05-31", "policy_id": "fx_reference_on_or_before_max_7_calendar_days_v1"}
    assert hashlib.sha256(cache.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("reference,rate", [
    ("2024-06-03", "0.9"), ("2024-05-25", "0.9"), ("2021-01-01", "0.9"),
    ("not-a-date", "0.9"), (None, "0.9"), ("2024-05-31", "0"), ("2024-05-31", "NaN"),
])
def test_G09_cached_row_date_never_hides_future_or_stale_original_reference(tmp_path, reference, rate):
    store = legacy_store(tmp_path)
    cache = legacy_cache(tmp_path, reference=reference, rate=rate)
    service = ExternalPriceBackfillService(store)
    assert service._usd_eur_reference(str(cache), "2024-06-02") is None
    assert service._usd_eur_rate(str(cache), "2024-06-02") == 0
    preview, points = V1FxCacheImporter(store).to_price_points(str(cache), Decimal("1"))
    assert preview.missing_usd_eur_count == 1 and not points
    assert preview.missing[0]["reason"] == "usd_eur_missing"


@pytest.mark.parametrize("pair,rate", [(("USD", "EUR"), "0.9"), (("EUR", "USD"), "1.111111111111111111")])
def test_G08_external_same_day_crypto_import_remains_positive(tmp_path, monkeypatch, pair, rate):
    from steuerreport_v2.domain import external_price_backfill as external
    store = legacy_store(tmp_path)
    cache = legacy_cache(tmp_path, pair=pair, rate=rate)
    config = tmp_path / "prices.json"
    config.write_text(json.dumps({"assets": [{"symbol": "BTC", "coingecko_id": "bitcoin", "aliases": []}]}))
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "api.coingecko.com"
        assert request.url.path == "/api/v3/coins/bitcoin/history"
        return httpx.Response(200, json={"market_data": {"current_price": {"usd": "100"}}})

    monkeypatch.setattr(external, "managed_client", lambda **kw: httpx.Client(transport=httpx.MockTransport(handle), **kw))
    result = ExternalPriceBackfillService(store).run(config_path=str(config), v1_fx_db_path=str(cache),
        provider="coingecko", assets_filter=["BTC"], max_requests=1, timeout_seconds=3, confidence=Decimal("1"), dry_run=False)
    assert result.imported_prices == 1 and len(calls) == 1
    point = store.list_price_points()[0]
    assert abs(point.price_eur - Decimal("90")) <= TOLERANCE
    assert point.priced_at.date() == date(2024, 6, 2)
    assert reference_metadata(point.source) == {
        "base": pair[0], "quote": pair[1], "rate": rate, "source": "fixture:ecb",
        "reference_date": "2024-05-31", "policy_id": "fx_reference_on_or_before_max_7_calendar_days_v1"}


@pytest.mark.parametrize("payload,accepted", [
    ([quote()], True), ([quote(base="EUR", target="USD", rate="1.111111111111111111")], True),
    ([quote(day="2024-06-03")], False), ([quote(day="2024-05-25")], False),
    ([quote(base="GBP")], False), ([], False), ([quote(), quote(rate="0.8")], False),
    ([quote(day="2024-06-03", rate="999"), quote()], True),
])
def test_G09_bmf_fx_consumer_preserves_raw_body_and_rejects_invalid_reference(tmp_path, payload, accepted):
    store = legacy_store(tmp_path)
    body = json.dumps(payload).encode()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
        result = BmfEventPriceRemediationService(store)._fetch_fx(client, date(2024, 6, 2))
    assert (result is not None) is accepted
    if accepted:
        assert result.rate_date == date(2024, 5, 31)
        assert result.response_sha256 == hashlib.sha256(body).hexdigest()
        assert result.response_body_utf8.encode() == body
        assert result.payload == payload
        assert abs(Decimal("100") * result.rate - Decimal("90")) <= TOLERANCE


def test_G09_unrepresentable_inverse_is_missing_not_an_uncaught_decimal_error(tmp_path):
    cache = legacy_cache(tmp_path, pair=("EUR", "USD"), rate="1e-1000000")
    service = ExternalPriceBackfillService(legacy_store(tmp_path))
    assert service._usd_eur_reference(str(cache), "2024-06-02") is None
    assert service._usd_eur_rate(str(cache), "2024-06-02") == 0


@pytest.mark.parametrize("body", [b"not json", json.dumps([quote()]).encode("utf-16")])
def test_G09_malformed_original_body_yields_no_bmf_fx(tmp_path, body):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
        result = BmfEventPriceRemediationService(legacy_store(tmp_path))._fetch_fx(client, date(2024, 6, 2))
    assert result is None


@pytest.mark.parametrize("pair,rate", [(("USD", "EUR"), "0.9"), (("EUR", "USD"), "1.111111111111111111")])
@pytest.mark.parametrize("dry_run", [True, False])
def test_G08_G09_asof_caller_binds_actual_fx_reference_in_job_and_price(tmp_path, monkeypatch, pair, rate, dry_run):
    from steuerreport_v2.domain import as_of_price_gate as asof
    store = legacy_store(tmp_path)
    BalanceLedgerBuilder(store).rebuild()
    cache = legacy_cache(tmp_path, pair=pair, rate=rate)
    config = tmp_path / "asof-prices.json"
    config.write_text(json.dumps({"assets": [{"symbol": "BTC", "coingecko_id": "bitcoin"}]}))
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "coins.llama.fi"
        assert request.url.path.endswith("/coingecko:bitcoin")
        instant = int(request.url.path.split("/")[3])
        return httpx.Response(200, json={"coins": {"coingecko:bitcoin": {"price": "100", "timestamp": instant}}})

    monkeypatch.setattr(asof, "managed_client", lambda **kw: httpx.Client(transport=httpx.MockTransport(handle), **kw))
    result = AsOfPriceGateService(store, artifact_root=tmp_path / "asof-artifacts").backfill(
        AsOfPriceGateBackfillRequest(as_of=datetime(2024, 6, 2, 12, tzinfo=timezone.utc),
            config_path=str(config), v1_fx_db_path=str(cache), provider="coingecko", assets=["BTC"], dry_run=dry_run))
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.price_date == date(2024, 6, 2)
    assert reference_metadata(job.source) == {"base": pair[0], "quote": pair[1], "rate": rate,
        "source": "fixture:ecb", "reference_date": "2024-05-31",
        "policy_id": "fx_reference_on_or_before_max_7_calendar_days_v1"}
    if dry_run:
        assert result.imported_prices == 0 and not calls
        assert store.list_price_points() == []
    else:
        assert result.imported_prices == len(calls) == 1
        assert abs(job.price_eur - Decimal("90")) <= TOLERANCE
        point = store.list_price_points()[0]
        assert point.source == job.source
        assert abs(point.price_eur - Decimal("90")) <= TOLERANCE
        assert point.priced_at.date() == date(2024, 6, 2)


@pytest.mark.parametrize("reference", ["2024-05-25", "2024-06-03"])
def test_G09_asof_caller_rejects_invalid_reference_before_provider_request(tmp_path, monkeypatch, reference):
    from steuerreport_v2.domain import as_of_price_gate as asof
    store = legacy_store(tmp_path)
    BalanceLedgerBuilder(store).rebuild()
    cache = legacy_cache(tmp_path, reference=reference)
    calls = []
    monkeypatch.setattr(asof, "managed_client", lambda **kw: calls.append(kw))
    with pytest.raises(ValueError, match="Kein belegter USD/EUR-Kurs"):
        AsOfPriceGateService(store).backfill(AsOfPriceGateBackfillRequest(
            as_of=datetime(2024, 6, 2, 12, tzinfo=timezone.utc), v1_fx_db_path=str(cache), assets=["BTC"], dry_run=False))
    assert calls == [] and store.list_price_points() == []
