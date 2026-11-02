from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import external_price_backfill as module
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def synthetic_store(tmp_path, *, event_type="income"):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", source_ref="event", asset="TEST", quantity=Decimal("2"),
        event_time=datetime(2024, 6, 2, 12, tzinfo=timezone.utc), event_type=event_type, account="test",
    ))
    if event_type == "transfer":
        BalanceLedgerBuilder(store).rebuild()
    config = tmp_path / "synthetic.json"
    config.write_text(json.dumps({"assets": [{"symbol": "TEST", "coingecko_id": "synthetic-test", "defillama_id": "synthetic:token", "aliases": ["TEST"], "store_keys": ["TEST"]}]}))
    return store, config


def cache(path, *, source="synthetic", with_source_date=True):
    with sqlite3.connect(path) as con:
        column = ", source_rate_date text" if with_source_date else ""
        con.execute("create table fx_cache (rate_date text, base_ccy text, quote_ccy text, rate text, source text" + column + ")")
        values = ("2024-06-02", "USD", "EUR", "0.9", source) + (("2024-05-31",) if with_source_date else ())
        con.execute("insert into fx_cache values (" + ",".join("?" for _ in values) + ")", values)
    return path


def mock_client(monkeypatch):
    monkeypatch.setattr(module, "managed_client", lambda **kwargs: httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("unexpected provider request"))))


@pytest.mark.parametrize("price", ["1e100", "1e1000000", "1e-50"])
def test_historical_extreme_price_is_rejected_without_write(tmp_path, monkeypatch, price):
    store, config = synthetic_store(tmp_path)
    path = cache(tmp_path / "legacy.sqlite")
    mock_client(monkeypatch)
    monkeypatch.setattr(
        ExternalPriceBackfillService, "_fetch_price_usd",
        lambda *args, **kwargs: (Decimal(price), "synthetic"),
    )
    result = ExternalPriceBackfillService(store).run(
        config_path=str(config), v1_fx_db_path=str(path), provider="defillama",
        assets_filter=["TEST"], max_requests=5, timeout_seconds=5,
        confidence=Decimal("1"), dry_run=False,
    )
    assert result.imported_prices == 0 and result.pipeline is None
    assert result.jobs[0].reason == "price_out_of_range"
    assert not store.list_price_points()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "0", "1e20", "1e-50"])
def test_price_ledger_rejects_unrepresentable_eur_values(value):
    assert module.checked_eur_price(Decimal(value), Decimal("1")) is None


def test_price_ledger_accepts_decimal_boundary_without_losing_precision():
    value = Decimal("99999999999999999999.999999999999999999")
    assert module.checked_eur_price(value, Decimal("1")) == value


def test_price_ledger_rounds_once_after_exact_decimal_multiplication():
    value = Decimal("1.0000000000000000005" + "0" * 55 + "1")
    assert module.checked_eur_price(value, Decimal("1")) == Decimal("1.000000000000000001")
    assert module.checked_eur_price(Decimal("1." + "2" * 256), Decimal("1")) is None


def test_exact_current_prices_keep_existing_decimal_scale():
    assert str(module.checked_eur_price(Decimal("3.21"), Decimal("1"), preserve_exact_scale=True)) == "3.21"
    assert str(module.checked_eur_price(Decimal("75"), Decimal("0.90"), preserve_exact_scale=True)) == "67.50"
    value = Decimal("1.0000000000000000005" + "0" * 55 + "1")
    assert module.checked_eur_price(value, Decimal("1"), preserve_exact_scale=True) == Decimal("1.000000000000000001")


@pytest.mark.parametrize("source", ["usd", "eur"])
def test_current_backfill_rejects_unrepresentable_price_without_write(tmp_path, monkeypatch, source):
    store, config = synthetic_store(tmp_path, event_type="transfer")
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd",
                        lambda *args: {"synthetic:token": Decimal("1e-50")} if source == "usd" else {})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur",
                        lambda *args: {"synthetic-test": Decimal("1e-50")} if source == "eur" else {})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur",
                        lambda *args: (Decimal("0.9"), (date.today() - timedelta(days=1)).isoformat()))
    result = ExternalPriceBackfillService(store).run_current_portfolio(
        config_path=str(config), provider="coingecko", assets_filter=["TEST"],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False,
    )
    assert result.imported_prices == 0 and result.pipeline is None
    assert result.jobs[0].reason == "price_out_of_range"
    if source == "eur":
        assert result.jobs[0].provider_id == "synthetic-test"
        assert result.jobs[0].source == "coingecko:simple-price:eur"
    assert not store.list_price_points()


def test_current_backfill_warns_when_valid_fallback_replaces_out_of_range_usd(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path, event_type="transfer")
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd",
                        lambda *args: {"synthetic:token": Decimal("1e-50")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur",
                        lambda *args: {"synthetic-test": Decimal("42")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur",
                        lambda *args: (Decimal("0.9"), (date.today() - timedelta(days=1)).isoformat()))
    result = ExternalPriceBackfillService(store).run_current_portfolio(
        config_path=str(config), provider="coingecko", assets_filter=["TEST"],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False,
    )
    assert result.imported_prices == 1 and result.jobs[0].price_eur == Decimal("42")
    assert result.jobs[0].provider_id == "synthetic-test"
    assert result.jobs[0].reason == module.PRICE_CANDIDATE_OUT_OF_RANGE
    assert module.fx_reference_warnings(result.jobs)[0].code == module.PRICE_CANDIDATE_OUT_OF_RANGE


def test_current_api_reports_invalid_fx_and_unrepresentable_eur_fallback(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path, event_type="transfer")
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd",
                        lambda *args: {"synthetic:token": Decimal("100")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur",
                        lambda *args: {"synthetic-test": Decimal("1e-50")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur",
                        lambda *args: (Decimal("0.9"), "2024-01-01"))
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json={
        "config_path": str(config), "assets": ["TEST"], "dry_run": False,
    })
    body = response.json()
    assert response.status_code == 200 and body["status"] == "warning"
    assert {w["code"] for w in body["warnings"]} >= {module.FX_REFERENCE_INVALID, module.PRICE_OUT_OF_RANGE}
    job = body["data"]["jobs"][0]
    assert job["reason"] == module.FX_REFERENCE_INVALID
    assert job["additional_reasons"] == [module.PRICE_OUT_OF_RANGE]
    assert job["provider_id"] == "synthetic-test" and job["source"] == "coingecko:simple-price:eur"
    assert not store.list_price_points()


def test_current_api_partial_failure_is_warning_even_when_another_asset_imports(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path, event_type="transfer")
    config.write_text(json.dumps({"assets": [
        {"symbol": "TEST", "coingecko_id": "synthetic-test"},
        {"symbol": "GOOD", "coingecko_id": "synthetic-good"},
    ]}))
    monkeypatch.setattr(module.BalanceLedgerBuilder, "positions", lambda self: [
        SimpleNamespace(asset="TEST", quantity=Decimal("1")),
        SimpleNamespace(asset="GOOD", quantity=Decimal("1")),
    ])
    monkeypatch.setattr(module.PipelineService, "rebuild_all", lambda self: None)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", lambda *args: {})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur",
                        lambda *args: {"synthetic-test": Decimal("1e-50"), "synthetic-good": Decimal("42")})
    mock_client(monkeypatch)
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json={
        "config_path": str(config), "assets": ["TEST", "GOOD"], "dry_run": False,
    })
    body = response.json()
    assert response.status_code == 200 and body["status"] == "warning"
    assert body["data"]["imported_prices"] == 1 and body["data"]["failed"] == 1
    assert any(w["code"] == "price_backfill_partial_failure" for w in body["warnings"])
    assert any(w["code"] == module.PRICE_OUT_OF_RANGE for w in body["warnings"])
    assert [point.asset for point in store.list_price_points()] == ["GOOD"]


def test_historical_api_warns_when_daily_fx_is_only_technically_accepted(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path)
    path = cache(tmp_path / "legacy.sqlite")
    mock_client(monkeypatch)
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/external", json={
        "config_path": str(config), "v1_fx_db_path": str(path), "assets": ["TEST"], "dry_run": True,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["warnings"][0]["code"] == module.FX_REFERENCE_UNVERIFIED
    assert "Originalbeleg" in body["warnings"][0]["message"]
    assert body["data"]["jobs"][0]["status"] == "planned"
    assert not store.list_price_points()


@pytest.mark.parametrize("with_source_date,source", [(False, "synthetic"), (True, "   ")])
def test_external_backfill_rejects_unbound_fx_date_or_source(tmp_path, monkeypatch, with_source_date, source):
    store, config = synthetic_store(tmp_path)
    path = cache(tmp_path / "legacy.sqlite", source=source, with_source_date=with_source_date)
    before = path.read_bytes()
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", lambda *args, **kwargs: (Decimal("100"), "synthetic"))
    result = ExternalPriceBackfillService(store).run(config_path=str(config), v1_fx_db_path=str(path), provider="defillama",
        assets_filter=["TEST"], max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False)
    assert result.imported_prices == 0 and result.pipeline is None
    assert result.jobs[0].reason == "usd_eur_source_date_or_source_invalid"
    assert not store.list_price_points() and path.read_bytes() == before


@pytest.mark.parametrize("fx_date", ["", "invalid", "2024-01-01", "2999-01-01"])
def test_current_backfill_rejects_missing_stale_or_future_fx(tmp_path, monkeypatch, fx_date):
    store, config = synthetic_store(tmp_path, event_type="transfer")
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", lambda *args: {"synthetic:token": Decimal("100")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", lambda *args: {})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", lambda *args: (Decimal("0.9"), fx_date))
    result = ExternalPriceBackfillService(store).run_current_portfolio(config_path=str(config), provider="coingecko", assets_filter=["TEST"],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False)
    assert result.imported_prices == 0 and result.pipeline is None
    assert result.jobs[0].reason == "usd_eur_source_date_or_source_invalid"
    assert result.jobs[0].provider_id == "synthetic:token"
    assert not store.list_price_points()


@pytest.mark.parametrize("age,accepted", [(0, False), (1, True), (7, True), (8, False), (-1, False)])
def test_current_backfill_uses_existing_fx_reference_window(tmp_path, monkeypatch, age, accepted):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 30, 12, tzinfo=tz)

    store, config = synthetic_store(tmp_path, event_type="transfer")
    mock_client(monkeypatch)
    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", lambda *args: {"synthetic:token": Decimal("100")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", lambda *args: {})
    fx_day = (date(2026, 10, 30) - timedelta(days=age)).isoformat()
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", lambda *args: (Decimal("0.9"), fx_day))
    result = ExternalPriceBackfillService(store).run_current_portfolio(config_path=str(config), provider="coingecko", assets_filter=["TEST"],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False)
    assert result.imported_prices == (1 if accepted else 0)
    assert len(store.list_price_points()) == (1 if accepted else 0)
    if accepted:
        assert result.jobs[0].price_eur == Decimal("90")
        assert result.jobs[0].reason == module.FX_REFERENCE_UNVERIFIED
        assert [warning.code for warning in module.fx_reference_warnings(result.jobs)] == [module.FX_REFERENCE_UNVERIFIED]
    else:
        assert result.jobs[0].reason == "usd_eur_source_date_or_source_invalid"


def test_current_backfill_can_use_direct_eur_if_fx_is_invalid(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path, event_type="transfer")
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", lambda *args: {"synthetic:token": Decimal("100")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", lambda *args: {"synthetic-test": Decimal("42")})
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", lambda *args: (Decimal("0.9"), "2024-01-01"))
    result = ExternalPriceBackfillService(store).run_current_portfolio(config_path=str(config), provider="coingecko", assets_filter=["TEST"],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False)
    assert result.imported_prices == 1 and result.jobs[0].price_eur == Decimal("42")
    assert result.jobs[0].source == "coingecko:simple-price:eur"
    assert result.jobs[0].provider_id == "synthetic-test"
    assert result.jobs[0].reason == module.FX_REFERENCE_INVALID
    assert module.fx_reference_warnings(result.jobs)


@pytest.mark.parametrize("base,amount", [("GBP", 1), (None, 1), ("USD", 100), ("USD", None)])
def test_frankfurter_latest_requires_usd_base_and_unit_amount(tmp_path, base, amount):
    service = ExternalPriceBackfillService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    payload = {"base": base, "amount": amount, "date": date.today().isoformat(), "rates": {"EUR": "0.9"}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        rate, _ = service._fetch_frankfurter_usd_eur(client)
    assert rate == 0


@pytest.mark.parametrize("kind", ["historical", "current", "current_fallback"])
def test_api_reports_fx_rejection_without_financial_write(tmp_path, monkeypatch, kind):
    store, config = synthetic_store(tmp_path, event_type="income" if kind == "historical" else "transfer")
    mock_client(monkeypatch)
    if kind == "historical":
        legacy = cache(tmp_path / "legacy.sqlite", with_source_date=False)
        path = "/api/v1/prices/backfill/external"
        payload = {"config_path": str(config), "v1_fx_db_path": str(legacy), "assets": ["TEST"], "dry_run": False}
        monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", lambda *args, **kwargs: pytest.fail("unexpected price request"))
    else:
        path = "/api/v1/prices/backfill/current-portfolio"
        payload = {"config_path": str(config), "assets": ["TEST"], "dry_run": False}
        monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", lambda *args: {"synthetic:token": Decimal("100")})
        monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", lambda *args: {"synthetic-test": Decimal("42")} if kind == "current_fallback" else {})
        monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", lambda *args: (Decimal("0.9"), "2024-01-01"))
    response = TestClient(create_app(store)).post(path, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning" and body["data"]["imported_prices"] == (1 if kind == "current_fallback" else 0)
    assert body["warnings"][0]["code"] == "usd_eur_source_date_or_source_invalid"
    assert "Quelltag" in body["warnings"][0]["message"]
    assert "Originalbeleg" in body["warnings"][0]["message"]
    if kind == "current_fallback":
        assert body["data"]["jobs"][0]["provider_id"] == "synthetic-test"
        assert len(store.list_price_points()) == 1
    else:
        assert not store.list_price_points()


@pytest.mark.parametrize("dry_run", [True, False])
def test_historical_backfill_rejects_same_day_fx_without_publication_time(tmp_path, monkeypatch, dry_run):
    store, config = synthetic_store(tmp_path)
    path = cache(tmp_path / "legacy.sqlite")
    with sqlite3.connect(path) as con:
        con.execute("update fx_cache set source_rate_date = rate_date")
    mock_client(monkeypatch)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", lambda *a, **k: pytest.fail("unexpected request"))
    result = ExternalPriceBackfillService(store).run(config_path=str(config), v1_fx_db_path=str(path), provider="auto",
        assets_filter=["TEST"], max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=dry_run)
    assert result.jobs[0].reason == module.FX_REFERENCE_INVALID
    assert result.imported_prices == 0 and result.pipeline is None and not store.list_price_points()


@pytest.mark.parametrize("source", ["   ", "", None])
def test_blank_source_does_not_shadow_valid_same_day_reference(tmp_path, source):
    path = cache(tmp_path / "legacy.sqlite", source=source)
    with sqlite3.connect(path) as con:
        con.execute("insert into fx_cache values ('2024-06-02', 'USD', 'EUR', '0.9', 'valid', '2024-05-31')")
    ref = ExternalPriceBackfillService(None)._timed_usd_eur_reference(str(path), "2024-06-02")
    assert ref is not None and ref.source == "valid"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_coingecko_uses_defillama_fallback_and_defillama_rejects_nonfinite(tmp_path, bad):
    service = ExternalPriceBackfillService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    def handle(request):
        if request.url.host == "api.coingecko.com":
            return httpx.Response(200, json={"market_data": {"current_price": {"usd": bad}}})
        return httpx.Response(200, json={"coins": {"synthetic:token": {"price": "2"}}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        price, source = service._fetch_price_usd(client=client, coingecko_id="synthetic", defillama_id="synthetic:token", date_str="2024-06-02", provider="auto")
    assert (price, source) == (Decimal("2"), "defillama_token_history")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"coins": {"synthetic:token": {"price": bad}}}))) as client:
        assert service._fetch_defillama_history_price(client, "synthetic:token", "2024-06-02") == 0
        assert service._fetch_defillama_current_prices_usd(client, ["synthetic:token"]) == {}


def test_historical_fx_warning_survives_job_limit(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path)
    requirements = [SimpleNamespace(asset=f"UNKNOWN{i}", price_date=date(2024, 6, 2)) for i in range(200)]
    requirements.append(SimpleNamespace(asset="TEST", price_date=date(2024, 6, 2)))
    monkeypatch.setattr(module, "PriceCoverageService", lambda _: SimpleNamespace(requirements=lambda: SimpleNamespace(requirements=requirements)))
    mock_client(monkeypatch)
    result = ExternalPriceBackfillService(store).run(config_path=str(config), v1_fx_db_path=str(tmp_path / "missing"),
        provider="auto", assets_filter=[], max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False)
    assert len(result.jobs) == 200 and result.skipped == 201
    assert module.fx_reference_warnings(result.jobs)
    assert result.imported_prices == 0 and result.pipeline is None
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/external", json={
        "config_path": str(config), "v1_fx_db_path": str(tmp_path / "missing"), "dry_run": False,
    })
    assert response.status_code == 200 and response.json()["status"] == "warning"
    assert response.json()["warnings"][0]["code"] == module.FX_REFERENCE_INVALID


def test_historical_job_limit_keeps_both_unverified_and_invalid_fx_warnings(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path)
    requirements = [SimpleNamespace(asset="TEST", price_date=date(2024, 1, 1) + timedelta(days=i))
                    for i in range(201)]
    monkeypatch.setattr(module, "PriceCoverageService", lambda _: SimpleNamespace(
        requirements=lambda: SimpleNamespace(requirements=requirements)))
    reference = module.FxReference(Decimal("0.9"), date(2024, 1, 1), "USD", "EUR", Decimal("0.9"), "synthetic")
    last_date = requirements[-1].price_date.isoformat()
    monkeypatch.setattr(ExternalPriceBackfillService, "_timed_usd_eur_reference",
                        lambda self, path, day: reference if day == last_date else None)
    mock_client(monkeypatch)
    result = ExternalPriceBackfillService(store).run(
        config_path=str(config), v1_fx_db_path="unused", provider="auto", assets_filter=[],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=True,
    )
    assert len(result.jobs) == 200
    assert {warning.code for warning in module.fx_reference_warnings(result.jobs)} == {
        module.FX_REFERENCE_INVALID, module.FX_REFERENCE_UNVERIFIED,
    }
    assert result.imported_prices == 0 and not store.list_price_points()


def test_historical_job_limit_keeps_three_distinct_warnings(tmp_path, monkeypatch):
    store, config = synthetic_store(tmp_path)
    requirements = [SimpleNamespace(asset="TEST", price_date=date(2024, 1, 1) + timedelta(days=i))
                    for i in range(202)]
    monkeypatch.setattr(module, "PriceCoverageService", lambda _: SimpleNamespace(
        requirements=lambda: SimpleNamespace(requirements=requirements)))
    reference = module.FxReference(Decimal("0.9"), date(2024, 1, 1), "USD", "EUR", Decimal("0.9"), "synthetic")
    accepted_days = {item.price_date.isoformat() for item in requirements[-2:]}
    monkeypatch.setattr(ExternalPriceBackfillService, "_timed_usd_eur_reference",
                        lambda self, path, day: reference if day in accepted_days else None)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd",
                        lambda self, **kwargs: (Decimal("1e100") if kwargs["date_str"] == requirements[-1].price_date.isoformat() else Decimal("100"), "synthetic"))
    monkeypatch.setattr(module.PipelineService, "rebuild_all", lambda self: None)
    mock_client(monkeypatch)
    result = ExternalPriceBackfillService(store).run(
        config_path=str(config), v1_fx_db_path="unused", provider="auto", assets_filter=[],
        max_requests=5, timeout_seconds=5, confidence=Decimal("1"), dry_run=False,
    )
    assert len(result.jobs) == 200
    assert {warning.code for warning in module.fx_reference_warnings(result.jobs)} == {
        module.FX_REFERENCE_INVALID, module.FX_REFERENCE_UNVERIFIED, module.PRICE_OUT_OF_RANGE,
    }
    assert result.imported_prices == result.failed == 1
