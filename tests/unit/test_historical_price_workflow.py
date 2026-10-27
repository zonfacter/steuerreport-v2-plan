"""Isolierte API-Regressionen fuer die historische EUR-Preiskampagne."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
from steuerreport_v2.db import ai_corrections
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as module
from steuerreport_v2.domain.external_http import managed_client, outbound_scope
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestLimiter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


BASE = "/api/v1/prices/historical"
AT = datetime(2024, 6, 2, 12, tzinfo=timezone.utc)
MINT = "Ab" + "1" * 30
SOURCE_TABLES = (
    "raw_import_batches", "raw_objects", "canonical_events", "ai_correction_overrides",
)


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    with store.connect():
        pass
    service = HistoricalPriceService(store)
    mappings = {}
    original_mappings = HistoricalPriceService.mappings
    monkeypatch.setattr(HistoricalPriceService, "mappings", lambda self: mappings)
    clock = [1_000_000.0]
    limiter = RequestLimiter(
        state_root=tmp_path / "limits", clock=lambda: clock[0], monotonic=lambda: clock[0],
        sleep=lambda value: clock.__setitem__(0, clock[0] + value),
    )
    limiter.write_config(RequestLimitsConfig(default_profile=RequestLimitProfile(
        requests_per_second=1000, requests_per_minute=60000, burst=1000, max_retries=1,
    )), expected_revision=0)
    monkeypatch.setattr(module, "outbound_scope", lambda **kwargs: outbound_scope(
        clock=limiter._clock, monotonic=limiter._monotonic, **kwargs,
    ))
    env = SimpleNamespace(
        store=store, service=service, mappings=mappings, calls=[], missing=set(),
        before_response=None, applied_callbacks=[], original_mappings=original_mappings,
    )

    def handle(request):
        env.calls.append(request)
        if env.before_response is not None:
            env.before_response(request)
        assert request.method == "GET"
        assert not request.content
        if request.url.host == "api.frankfurter.dev":
            assert request.url.path == "/v2/providers/ecb/rates"
            assert request.url.params["base"] == "USD"
            assert request.url.params["quotes"] == "EUR"
            start = date.fromisoformat(request.url.params["from"])
            end = date.fromisoformat(request.url.params["to"])
            return httpx.Response(200, json=[
                {"base": "USD", "quote": "EUR", "date": (start + timedelta(days=index)).isoformat(),
                 "rate": "0.92"}
                for index in range((end - start).days + 1)
            ])
        if request.url.host == "coins.llama.fi":
            if request.url.path == "/batchHistorical":
                requested = json.loads(request.url.params["coins"])
                assert request.url.params["searchWidth"] == "1h"
                return httpx.Response(200, json={"coins": {
                    identifier: {"prices": [
                        {"timestamp": instant, "price": "150", "confidence": 0.99}
                        for instant in instants
                    ]}
                    for identifier, instants in requested.items() if identifier not in env.missing
                }})
            parts = request.url.path.split("/")
            assert parts[1:3] == ["prices", "historical"]
            return httpx.Response(200, json={"coins": {
                parts[4]: {"timestamp": int(parts[3]), "price": "150", "confidence": 0.99},
            }})
        pytest.fail(f"Unerwarteter externer Mock-Aufruf: {request.url.host}{request.url.path}")

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(module, "managed_client", lambda **kwargs: managed_client(
        transport=transport, limiter=limiter, clock=limiter._clock,
        monotonic=limiter._monotonic, **kwargs,
    ))
    app = FastAPI()
    app.include_router(build_historical_prices_router(
        store, lambda: env.applied_callbacks.append(True),
    ))
    with TestClient(app) as client:
        env.client = client
        yield env


def seed(env, count=1, *, kind="transfer", at=AT):
    payloads = []
    for index in range(count):
        asset = f"TOKEN{index:03d}"
        env.mappings[asset] = {"asset": asset, "coingecko_id": f"workflow-token{index:03d}",
                               "defillama_id": None}
        payloads.append(CanonicalEventCreate(
            source="synthetic", source_ref=f"observation-{index}", asset=asset,
            quantity=Decimal("1") if index % 2 == 0 else Decimal("-1"),
            event_time=at, event_type=kind, account="synthetic-account",
        ))
    return env.store.add_canonical_events(payloads)


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


def error(response, code):
    assert response.status_code == 409, response.text
    assert response.json()["errors"][0]["code"] == code


def plan(env, **kwargs):
    query = {"scope": "all_observed", "max_requests": 2, **kwargs}
    return query, data(env.client.post(BASE + "/plan", json=query))


def fetch(env, **kwargs):
    query, planned = plan(env, **kwargs)
    request = {**query, "request_id": str(uuid4()), "plan_sha256": planned["plan_sha256"],
               "confirm_external_request": True}
    return request, data(env.client.post(BASE + "/previews", json=request))


def continuation(preview, **kwargs):
    return {"request_id": str(uuid4()), "preview_sha256": preview["preview_sha256"],
            "confirm_external_request": True, "retry_open": False, **kwargs}


def follow(env, preview, **kwargs):
    request = continuation(preview, **kwargs)
    result = data(env.client.post(BASE + f"/previews/{preview['id']}/continue", json=request))
    return request, result


def approval(preview, **kwargs):
    return {"preview_sha256": preview["preview_sha256"], "actor": "Synthetische Testperson",
            "confirm_prices": True, "confirm_recalculation": True, **kwargs}


def source_snapshot(env):
    with env.store.connect() as con:
        return {table: con.execute(f"select * from {table} order by all").fetchall()
                for table in SOURCE_TABLES}


def batches(env):
    return [request for request in env.calls if request.url.path == "/batchHistorical"]


def requested_points(requests):
    return [(identifier, instant) for request in requests
            for identifier, instants in json.loads(request.url.params["coins"]).items()
            for instant in instants]


def test_api_plan_paginates_full_inventory_in_25_rows_without_writes(workflow):
    seed(workflow, 61)
    before = source_snapshot(workflow)
    revision = workflow.service._revision()
    _, first = plan(workflow)
    _, second = plan(workflow, page=2)
    _, third = plan(workflow, page=3)
    assert [len(item["rows"]) for item in (first, second, third)] == [25, 25, 11]
    assert {item["rows_total"] for item in (first, second, third)} == {61}
    assert {item["plan_sha256"] for item in (first, second, third)} == {first["plan_sha256"]}
    assert [item["row_offset"] for item in (first, second, third)] == [0, 25, 50]
    assert [item["next_offset"] for item in (first, second, third)] == [25, 50, None]
    assert len({row["asset"] for item in (first, second, third) for row in item["rows"]}) == 61
    assert first["source_event_types"] == {"transfer": 61}
    assert first["year_summary"][0]["tokens_count"] == 61
    assert first["writes_financial_data"] is False
    assert not workflow.calls and not workflow.service.root.exists()
    assert source_snapshot(workflow) == before
    assert workflow.service._revision() == revision


def test_tax_required_remains_default_and_excludes_transfer_only_observations(workflow):
    seed(workflow, 3)
    assert HistoricalPriceQuery().scope == "tax_required"
    result = data(workflow.client.post(BASE + "/plan", json={}))
    assert result["scope"] == "tax_required"
    assert result["requirements_count"] == 0 and result["rows"] == []
    _, observed = plan(workflow)
    assert observed["requirements_count"] == 3
    assert not workflow.calls


def test_fetch_uses_entire_plan_not_visible_page_or_200_row_prefix(workflow):
    seed(workflow, 205)
    before = source_snapshot(workflow)
    request, preview = fetch(workflow, max_requests=50, page=3, page_size=25)
    assert preview["total_rows"] == len(preview["rows"]) == 205
    assert preview["prices_count"] == 205 and preview["pending_count"] == 0
    assert preview["collection_complete"] is True
    assert len(requested_points(batches(workflow))) == 205
    assert len(set(requested_points(batches(workflow)))) == 205
    assert len(batches(workflow)) == 9
    assert preview["requests_started"] == len(workflow.calls) == 10
    assert all(Decimal(row["price_eur"]) == Decimal("138") for row in preview["rows"])
    assert all(row["priced_at"] == "2024-06-02T11:30:00+00:00" for row in preview["rows"])
    assert source_snapshot(workflow) == before and not workflow.store.list_price_points()
    assert data(workflow.client.get(BASE + f"/previews/{request['request_id']}")) == preview


def test_batch_historical_covers_all_observed_years_with_one_fx_range_per_year(workflow):
    instants = [AT.replace(year=2023, day=1), AT.replace(year=2023, day=3),
                AT.replace(day=1), AT.replace(day=3)]
    for instant in instants:
        seed(workflow, kind="unknown" if instant.day == 1 else "transfer", at=instant)
    _, planned = plan(workflow)
    assert [item["year"] for item in planned["year_summary"]] == [2023, 2024]
    assert planned["source_event_types"] == {"transfer": 2, "unknown": 2}
    _, preview = fetch(workflow, max_requests=10)
    assert preview["prices_count"] == 4 and preview["pending_count"] == 0
    assert {row["price_date"] for row in preview["rows"]} == {instant.date().isoformat() for instant in instants}
    assert set(preview["fx_series"]) == {"2023", "2024"}
    assert len(batches(workflow)) == 1
    assert len(set(requested_points(batches(workflow)))) == 4
    fx_calls = [call for call in workflow.calls if call.url.host == "api.frankfurter.dev"]
    assert len(fx_calls) == 2
    for call in fx_calls:
        start = date.fromisoformat(call.url.params["from"])
        end = date.fromisoformat(call.url.params["to"])
        assert start == date(end.year, 6, 1) - timedelta(days=7)
        assert end == date(end.year, 6, 3)
    assert all(Decimal(row["price_eur"]) == Decimal("138") for row in preview["rows"])
    assert preview["requests_started"] == len(workflow.calls) == 3
    assert not workflow.store.list_price_points()


@pytest.mark.parametrize("confirmation", [None, False, 0, 1, "true"])
def test_fetch_requires_literal_external_confirmation_before_any_http(workflow, confirmation):
    seed(workflow)
    query, planned = plan(workflow)
    request = {**query, "request_id": str(uuid4()), "plan_sha256": planned["plan_sha256"]}
    if confirmation is not None:
        request["confirm_external_request"] = confirmation
    response = workflow.client.post(BASE + "/previews", json=request)
    assert response.status_code == 422
    assert not workflow.calls and not workflow.service.root.exists()


def test_minimum_budget_keeps_every_row_pending_and_continuation_reuses_fx(workflow):
    seed(workflow, 32)
    request, first = fetch(workflow, max_requests=1)
    assert first["prices_count"] == 0 and first["pending_count"] == 32
    assert first["open_count"] == 0 and len(first["rows"]) == 32
    assert all(row["status"] == "pending" for row in first["rows"])
    assert first["section_requests_started"] == first["requests_started"] == 1
    assert len(workflow.calls) == 1 and workflow.calls[0].url.host == "api.frankfurter.dev"
    assert data(workflow.client.post(BASE + "/previews", json=request)) == first
    assert len(workflow.calls) == 1
    next_request, second = follow(workflow, first)
    assert second["parent_preview_id"] == first["id"]
    assert second["prices_count"] == 25 and second["pending_count"] == 7
    assert second["section_requests_started"] == 1 and second["requests_started"] == 2
    stored = json.loads((workflow.service._directory(second["id"]) / "request.json").read_bytes())
    assert stored["parent_preview_sha256"] == first["preview_sha256"]
    assert stored["retry_open"] is False
    assert data(workflow.client.post(
        BASE + f"/previews/{first['id']}/continue", json=next_request,
    )) == second
    assert len(workflow.calls) == 2
    _, last = follow(workflow, second)
    assert last["prices_count"] == 32 and last["pending_count"] == 0
    assert last["collection_complete"] is True
    assert last["requests_started"] == len(workflow.calls) == 3
    assert len([call for call in workflow.calls if call.url.host == "api.frankfurter.dev"]) == 1
    assert len(set(requested_points(batches(workflow)))) == 32
    assert len(requested_points(batches(workflow))) == 32
    assert last["prices"][:25] == second["prices"]
    assert not workflow.store.list_price_points()


@pytest.mark.parametrize("confirmation", [None, False, 0, 1, "true"])
def test_continue_requires_literal_external_confirmation(workflow, confirmation):
    seed(workflow, 2)
    _, first = fetch(workflow, max_requests=1)
    request = continuation(first)
    if confirmation is None:
        request.pop("confirm_external_request")
    else:
        request["confirm_external_request"] = confirmation
    response = workflow.client.post(BASE + f"/previews/{first['id']}/continue", json=request)
    assert response.status_code == 422
    assert len(workflow.calls) == 1
    assert not (workflow.service._directory(request["request_id"]) / "request.json").exists()


def test_multiple_sections_apply_all_cumulative_prices_once_without_more_http(workflow):
    seed(workflow, 80)
    before = source_snapshot(workflow)
    _, first = fetch(workflow)
    _, second = follow(workflow, first)
    _, third = follow(workflow, second)
    assert [item["prices_count"] for item in (first, second, third)] == [25, 75, 80]
    assert [item["pending_count"] for item in (first, second, third)] == [55, 5, 0]
    assert source_snapshot(workflow) == before
    assert not workflow.store.list_price_points() and not workflow.store.list_review_decisions()
    requests_before = len(workflow.calls)
    path = BASE + f"/previews/{third['id']}/apply"
    result = data(workflow.client.post(path, json=approval(third)))
    assert result["applied"] is True and result["prices_count"] == 80
    prices = workflow.store.list_price_points(limit=1000)
    assert len(prices) == len({point.asset for point in prices}) == 80
    assert all(point.price_eur == Decimal("138") for point in prices)
    assert data(workflow.client.post(path, json=approval(third))) == result
    (workflow.service._directory(third["id"]) / "applied.json").unlink()
    assert data(workflow.client.post(path, json=approval(third))) == result
    assert workflow.store.list_price_points(limit=1000) == prices
    assert len(workflow.store.list_review_decisions()) == 1
    assert source_snapshot(workflow) == before
    assert len(workflow.calls) == requests_before
    assert data(workflow.client.get(BASE + f"/previews/{first['id']}"))["applied"] is False
    assert data(workflow.client.get(BASE + f"/previews/{second['id']}"))["applied"] is False


def test_apply_rejects_pending_collection_without_import_or_more_http(workflow):
    seed(workflow, 30)
    _, preview = fetch(workflow)
    assert preview["prices_count"] == 25 and preview["pending_count"] == 5
    before = source_snapshot(workflow)
    count = len(workflow.calls)
    error(workflow.client.post(BASE + f"/previews/{preview['id']}/apply", json=approval(preview)),
          "historical_price_collection_incomplete")
    assert source_snapshot(workflow) == before
    assert len(workflow.calls) == count and not workflow.store.list_price_points()
    assert not workflow.store.list_review_decisions() and not workflow.applied_callbacks


def test_complete_collection_with_open_and_blocked_rows_needs_both_consents_but_no_tax_approval(workflow):
    seed(workflow, 31)
    workflow.mappings.pop("TOKEN030")
    workflow.missing.add("coingecko:workflow-token000")
    _, preview = fetch(workflow, max_requests=3)
    assert preview["pending_count"] == 0 and preview["collection_complete"] is True
    assert preview["prices_count"] == 29 and preview["open_count"] == 1
    assert sum(row["status"] == "blocked" for row in preview["rows"]) == 1
    before = source_snapshot(workflow)
    count = len(workflow.calls)
    path = BASE + f"/previews/{preview['id']}/apply"
    for field in ("confirm_prices", "confirm_recalculation"):
        for value in (False, 0, 1, "true", None):
            request = approval(preview)
            if value is None:
                request.pop(field)
            else:
                request[field] = value
            assert workflow.client.post(path, json=request).status_code == 422
    assert not workflow.store.list_price_points() and not workflow.store.list_review_decisions()
    result = data(workflow.client.post(path, json=approval(preview)))
    assert result["applied"] is True and result["prices_count"] == 29
    assert len(workflow.store.list_price_points(limit=1000)) == 29
    decisions = workflow.store.list_review_decisions()
    assert len(decisions) == 1 and decisions[0].decision_type == "historical_price_import"
    assert source_snapshot(workflow) == before
    assert len(workflow.calls) == count


def test_early_known_failure_does_not_starve_later_tokens_or_retry_implicitly(workflow):
    seed(workflow, 40)
    missing = "coingecko:workflow-token000"
    workflow.missing.add(missing)
    _, first = fetch(workflow)
    assert first["open_count"] == 1 and first["pending_count"] == 15
    assert first["rows"][0]["status"] == "open"
    assert first["prices_count"] == 24
    calls_before = len(batches(workflow))
    _, last = follow(workflow, first, retry_open=False)
    assert last["open_count"] == 1 and last["pending_count"] == 0
    assert last["prices_count"] == 39 and last["collection_complete"] is True
    later_points = requested_points(batches(workflow)[calls_before:])
    assert len(later_points) == 15 and all(identifier != missing for identifier, _ in later_points)
    assert last["prices"][:24] == first["prices"]
    workflow.missing.clear()
    calls_before = len(batches(workflow))
    _, retried = follow(workflow, last, retry_open=True)
    assert retried["prices_count"] == 40 and retried["open_count"] == 0
    assert [identifier for identifier, _ in requested_points(batches(workflow)[calls_before:])] == [missing]
    assert len([call for call in workflow.calls if call.url.host == "api.frankfurter.dev"]) == 1


def test_status_reports_not_found_running_checkpoints_and_ready(workflow):
    seed(workflow, 30)
    query, planned = plan(workflow)
    identifier = str(uuid4())
    status_path = BASE + f"/previews/{identifier}/status"
    assert data(workflow.client.get(status_path))["status"] == "not_found"
    assert not workflow.service.root.exists()
    checkpoints = []
    workflow.before_response = lambda request: checkpoints.append(workflow.service.status(identifier))
    request = {**query, "request_id": identifier, "plan_sha256": planned["plan_sha256"],
               "confirm_external_request": True}
    preview = data(workflow.client.post(BASE + "/previews", json=request))
    assert len(checkpoints) == 2
    assert all(item["status"] == "running" and item["total_rows"] == 30 for item in checkpoints)
    assert checkpoints[0]["rows_processed"] == 0
    status = data(workflow.client.get(status_path))
    assert status["status"] == "ready" and status["preview_id"] == identifier
    assert status["rows_processed"] == 25 and status["requests_started"] == 2
    assert preview["pending_count"] == 5


def test_interrupted_request_retains_evidence_and_is_not_refetched_with_same_uuid(workflow, monkeypatch):
    seed(workflow)
    query, planned = plan(workflow)
    request = {**query, "request_id": str(uuid4()), "plan_sha256": planned["plan_sha256"],
               "confirm_external_request": True}

    def interrupted(*args):
        raise RuntimeError("synthetic-interruption-before-preview")

    monkeypatch.setattr(HistoricalPriceService, "_prepare", interrupted)
    response = workflow.client.post(BASE + "/previews", json=request)
    assert response.status_code == 503
    directory = workflow.service._directory(request["request_id"])
    assert (directory / "request.json").is_file() and (directory / "plan.json").is_file()
    assert not (directory / "preview.json").exists()
    assert list((directory / "progress").glob("*.json"))
    assert len(list((workflow.service.root / "evidence").glob("*.body"))) == 2
    status = data(workflow.client.get(BASE + f"/previews/{request['request_id']}/status"))
    assert status["status"] == "interrupted" and status["total_rows"] == 1
    count = len(workflow.calls)
    error(workflow.client.post(BASE + "/previews", json=request), "historical_price_incomplete_request")
    assert len(workflow.calls) == count and not workflow.store.list_price_points()


def test_database_change_rejects_continuation_and_apply_before_more_http(workflow):
    seed(workflow, 30)
    _, first = fetch(workflow, max_requests=3)
    workflow.store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", asset="LATER", quantity=Decimal("1"),
        event_time=AT, event_type="unknown", source_ref="later-observation",
    ))
    count = len(workflow.calls)
    error(workflow.client.post(BASE + f"/previews/{first['id']}/continue", json=continuation(first)),
          "historical_price_preview_stale")
    error(workflow.client.post(BASE + f"/previews/{first['id']}/apply", json=approval(first)),
          "historical_price_preview_stale")
    assert len(workflow.calls) == count and not workflow.store.list_price_points()
    assert not workflow.store.list_review_decisions()


@pytest.mark.parametrize("target", ["evidence", "plan", "preview", "prepared"])
def test_tampered_artifacts_block_apply_without_productive_writes(workflow, target):
    seed(workflow, 30)
    _, preview = fetch(workflow, max_requests=3)
    before = source_snapshot(workflow)
    directory = workflow.service._directory(preview["id"])
    paths = {
        "evidence": workflow.service.root / "evidence" / (preview["evidence"][0]["sha256"] + ".body"),
        "plan": directory / "plan.json", "preview": directory / "preview.json",
        "prepared": directory / "calculation.prepared",
    }
    path = paths[target]
    path.chmod(0o600)
    if target == "evidence":
        path.write_bytes(b"[]")
    elif target == "prepared":
        path.write_bytes(path.read_bytes() + b"synthetic-tamper")
    else:
        payload = json.loads(path.read_bytes())
        payload["synthetic_tamper"] = True
        path.write_text(json.dumps(payload), encoding="ascii")
    count = len(workflow.calls)
    error(workflow.client.post(BASE + f"/previews/{preview['id']}/apply", json=approval(preview)),
          "historical_price_evidence_changed")
    if target != "prepared":
        error(workflow.client.get(BASE + f"/previews/{preview['id']}"), "historical_price_evidence_changed")
        error(workflow.client.post(BASE + f"/previews/{preview['id']}/continue", json=continuation(preview)),
              "historical_price_evidence_changed")
    assert source_snapshot(workflow) == before
    assert len(workflow.calls) == count and not workflow.store.list_price_points()


def test_raw_payload_tamper_rejects_continuation_and_apply(workflow):
    events = seed(workflow, 30)
    batch = workflow.store.create_import_batch(ImportBatchCreate(source="synthetic"))
    raw = workflow.store.add_raw_object(batch.batch_id, RawObjectCreate(payload_json='{"synthetic":"original"}'))
    with workflow.store.connect() as con:
        con.execute("update canonical_events set raw_object_id=? where event_id=?",
                    [raw.raw_object_id, events[0].event_id])
    _, preview = fetch(workflow, max_requests=3)
    with workflow.store.connect() as con:
        con.execute("update raw_objects set payload_json=? where raw_object_id=?",
                    ['{"synthetic":"tampered"}', raw.raw_object_id])
    count = len(workflow.calls)
    error(workflow.client.post(BASE + f"/previews/{preview['id']}/continue", json=continuation(preview)),
          "historical_price_preview_stale")
    error(workflow.client.post(BASE + f"/previews/{preview['id']}/apply", json=approval(preview)),
          "historical_price_preview_stale")
    assert len(workflow.calls) == count and not workflow.store.list_price_points()


def test_changed_database_rejects_original_plan_before_external_requests(workflow):
    events = seed(workflow)
    query, planned = plan(workflow)
    with workflow.store.connect() as con:
        con.execute("update canonical_events set quantity=2 where event_id=?", [events[0].event_id])
    response = workflow.client.post(BASE + "/previews", json={
        **query, "request_id": str(uuid4()), "plan_sha256": planned["plan_sha256"],
        "confirm_external_request": True,
    })
    error(response, "historical_price_plan_stale")
    assert not workflow.calls and not workflow.store.list_price_points()


def test_same_uuid_changed_request_and_continuation_parent_hash_are_rejected(workflow):
    seed(workflow, 30)
    request, first = fetch(workflow)
    count = len(workflow.calls)
    error(workflow.client.post(BASE + "/previews", json={**request, "max_requests": 3}),
          "historical_price_request_conflict")
    error(workflow.client.post(BASE + f"/previews/{first['id']}/continue",
                              json=continuation(first, request_id=first["id"])),
          "historical_price_request_conflict")
    error(workflow.client.post(BASE + f"/previews/{first['id']}/continue",
                              json=continuation(first, preview_sha256="0" * 64)),
          "historical_price_preview_mismatch")
    next_request, second = follow(workflow, first)
    count += second["section_requests_started"]
    error(workflow.client.post(BASE + f"/previews/{first['id']}/continue",
                              json={**next_request, "retry_open": True}),
          "historical_price_request_conflict")
    assert len(workflow.calls) == count and not workflow.store.list_price_points()


def test_old_software_preview_is_rejected_for_continue_and_apply(workflow, monkeypatch):
    seed(workflow, 30)
    _, preview = fetch(workflow)
    monkeypatch.setattr(module, "__version__", "synthetic-new-version")
    count = len(workflow.calls)
    error(workflow.client.post(BASE + f"/previews/{preview['id']}/continue", json=continuation(preview)),
          "historical_price_preview_stale")
    error(workflow.client.post(BASE + f"/previews/{preview['id']}/apply", json=approval(preview)),
          "historical_price_preview_stale")
    assert len(workflow.calls) == count and not workflow.store.list_price_points()


@pytest.mark.parametrize("scope", ["tax_required", "all_observed"])
def test_price_preview_never_normalizes_or_replays_event_classification(workflow, monkeypatch, scope):
    seed(workflow, 0)
    workflow.mappings["TOKEN000"] = {"asset": "TOKEN000", "coingecko_id": "workflow-token000",
                                      "defillama_id": None}
    payload = {"timestamp_utc": AT.isoformat(), "event_type": "token_transfer", "asset": "TOKEN000",
               "quantity": "1", "side": "in", "wallet_address": "synthetic-wallet",
               "mint": MINT, "history_mapper_version": "2"}
    batch = workflow.store.create_import_batch(ImportBatchCreate(source="solana_rpc"))
    raw = workflow.store.add_raw_object(batch.batch_id, RawObjectCreate(payload_json=json.dumps(payload)))
    event = workflow.store.add_canonical_event(CanonicalEventCreate(
        source="solana_rpc", source_ref="synthetic-reviewed-income", asset="TOKEN000",
        quantity=Decimal("1"), event_time=AT, event_type="income", raw_object_id=raw.raw_object_id,
        account="synthetic-wallet", wallet="synthetic-wallet",
    ))
    normalized = RawNormalizer(workflow.store)._row_to_event("solana_rpc", raw.raw_object_id, payload)
    assert normalized.event_type == "transfer" and event.event_type == "income"
    with workflow.store.connect() as con:
        original = ai_corrections.record(con, "event", event.event_id)
        corrected = {**original, "event_type": "trade"}
        con.execute("insert into ai_correction_overrides values (?, ?, ?, ?, ?)", [
            "event", event.event_id, ai_corrections.json_text(original),
            ai_corrections.json_text(corrected), "synthetic-pending-correction",
        ])
    before = source_snapshot(workflow)
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError("Preisworkflow darf weder normalisieren noch Event-Korrekturen einspielen")

    monkeypatch.setattr(PipelineService, "rebuild_all", forbidden)
    monkeypatch.setattr(RawNormalizer, "normalize_batch", forbidden)
    monkeypatch.setattr(ai_corrections, "replay", forbidden)
    _, preview = fetch(workflow, scope=scope)
    assert preview["prices_count"] == 1 and preview["canonical_events_unchanged"] is True
    assert len(preview["frozen_source_sha256"]) == 64
    with workflow.store.connect() as con:
        assert workflow.service._source_digest(con) == preview["frozen_source_sha256"]
    assert source_snapshot(workflow) == before
    result = data(workflow.client.post(BASE + f"/previews/{preview['id']}/apply", json=approval(preview)))
    assert result["applied"] is True
    assert source_snapshot(workflow) == before
    assert workflow.store.list_canonical_events()[0].event_type == "income"
    assert not forbidden_calls


def test_frozen_source_guard_rejects_a_mutating_ledger_rebuild(workflow, monkeypatch):
    seed(workflow)
    before = source_snapshot(workflow)
    rebuild = PipelineService.rebuild_ledgers

    def mutating_rebuild(self, *args, **kwargs):
        result = rebuild(self, *args, **kwargs)
        with self.store.connect() as con:
            con.execute("update canonical_events set event_type='income'")
        return result

    monkeypatch.setattr(PipelineService, "rebuild_ledgers", mutating_rebuild)
    query, planned = plan(workflow)
    response = workflow.client.post(BASE + "/previews", json={
        **query, "request_id": str(uuid4()), "plan_sha256": planned["plan_sha256"],
        "confirm_external_request": True,
    })
    error(response, "historical_price_source_changed")
    assert source_snapshot(workflow) == before
    assert not workflow.store.list_price_points() and not workflow.store.list_review_decisions()


def test_downloaded_evidence_matches_recorded_sha_and_rejects_unbound_hash(workflow):
    seed(workflow)
    _, preview = fetch(workflow)
    for entry in preview["evidence"]:
        response = workflow.client.get(BASE + f"/previews/{preview['id']}/evidence/{entry['sha256']}")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == entry["sha256"]
    response = workflow.client.get(BASE + f"/previews/{preview['id']}/evidence/{'0' * 64}")
    assert response.status_code == 404


@pytest.mark.parametrize("explicit_mint", [False, True], ids=["original-mint-asset", "explicit-mint"])
def test_api_coingecko_mapping_roundtrip_preserves_exact_mint_without_defillama(workflow, monkeypatch, explicit_mint):
    monkeypatch.setattr(HistoricalPriceService, "mappings", workflow.original_mappings)
    asset = "WORKFLOW_ROUNDTRIP" if explicit_mint else MINT
    batch = workflow.store.create_import_batch(ImportBatchCreate(source="solana_rpc"))
    raw = workflow.store.add_raw_object(batch.batch_id, RawObjectCreate(
        payload_json=json.dumps({"mint": MINT, "history_mapper_version": "2"}),
    ))
    workflow.store.add_canonical_event(CanonicalEventCreate(
        source="solana_rpc", asset=asset.upper(), quantity=Decimal("1"), event_time=AT,
        event_type="transfer", raw_object_id=raw.raw_object_id, source_ref="synthetic-roundtrip",
    ))
    before = source_snapshot(workflow)
    request = {"asset": asset, "coingecko_id": "workflow-mint-roundtrip"}
    if explicit_mint:
        request["solana_mint"] = MINT
    saved = data(workflow.client.put(BASE + "/mappings", json=request))
    assert saved["asset"] == asset.upper()
    assert saved["solana_mint"] == MINT and saved["solana_mint"] != MINT.upper()
    assert saved["coingecko_id"] == "workflow-mint-roundtrip"
    assert saved.get("defillama_id") is None
    stored = data(workflow.client.get(BASE + "/mappings"))[asset.upper()]
    assert stored == {**saved, "origin": "operator"}
    writable = {key: value for key, value in stored.items() if key != "origin"}
    assert data(workflow.client.put(BASE + "/mappings", json=writable)) == saved
    reloaded = HistoricalPriceService(DuckDbStore(workflow.store.path)).mappings()[asset.upper()]
    assert reloaded == stored
    _, planned = plan(workflow, provider="coingecko", assets=[asset])
    row, = planned["rows"]
    assert row["status"] == "planned" and row["reason"] is None
    assert row["mint"] == MINT and row["provider_id"] == "workflow-mint-roundtrip"
    assert source_snapshot(workflow) == before
    assert not workflow.calls and not workflow.store.list_price_points()
    assert not workflow.service.root.exists()


@pytest.mark.parametrize("exact_operator_override", [False, True], ids=["symbol-beats-bundled", "operator-mint-wins"])
def test_api_hnt_operator_mapping_beats_bundled_mint_alias_but_not_operator_mint(workflow, monkeypatch, exact_operator_override):
    monkeypatch.setattr(HistoricalPriceService, "mappings", workflow.original_mappings)
    bundled = data(workflow.client.get(BASE + "/mappings"))
    assert bundled["HNT"]["origin"] == "bundled"
    mint = bundled["HNT"]["defillama_id"].removeprefix("solana:")
    assert mint != mint.upper() and bundled[mint.upper()]["origin"] == "bundled"
    batch = workflow.store.create_import_batch(ImportBatchCreate(source="solana_rpc"))
    raw = workflow.store.add_raw_object(batch.batch_id, RawObjectCreate(
        payload_json=json.dumps({"mint": mint, "history_mapper_version": "2"}),
    ))
    workflow.store.add_canonical_event(CanonicalEventCreate(
        source="solana_rpc", asset="HNT", quantity=Decimal("1"), event_time=AT,
        event_type="transfer", raw_object_id=raw.raw_object_id, source_ref="synthetic-hnt-observation",
    ))
    before = source_snapshot(workflow)
    symbol_request = {"asset": "hnt", "coingecko_id": "workflow-hnt-symbol-operator", "solana_mint": mint}
    saved = data(workflow.client.put(BASE + "/mappings", json=symbol_request))
    assert saved["asset"] == "HNT" and saved["solana_mint"] == mint
    assert saved.get("defillama_id") is None
    persisted = data(workflow.client.get(BASE + "/mappings"))
    assert persisted["HNT"] == {**saved, "origin": "operator"}
    assert persisted[mint.upper()]["origin"] == "bundled"
    assert persisted[mint.upper()]["coingecko_id"] != saved["coingecko_id"]
    _, planned = plan(workflow, provider="coingecko", assets=["HNT"])
    row, = planned["rows"]
    assert row["mint"] == mint and row["status"] == "planned"
    assert row["provider_id"] == symbol_request["coingecko_id"]
    if exact_operator_override:
        mint_request = {"asset": mint, "coingecko_id": "workflow-hnt-mint-operator"}
        mint_saved = data(workflow.client.put(BASE + "/mappings", json=mint_request))
        assert mint_saved["solana_mint"] == mint and mint_saved.get("defillama_id") is None
        persisted = data(workflow.client.get(BASE + "/mappings"))
        assert persisted[mint.upper()]["origin"] == "operator"
        _, planned = plan(workflow, provider="coingecko", assets=["HNT"])
        row, = planned["rows"]
        assert row["status"] == "planned" and row["provider_id"] == mint_request["coingecko_id"]
    reloaded = HistoricalPriceService(DuckDbStore(workflow.store.path)).mappings()
    assert reloaded["HNT"] == persisted["HNT"]
    assert reloaded[mint.upper()] == persisted[mint.upper()]
    assert source_snapshot(workflow) == before
    assert not workflow.calls and not workflow.store.list_price_points()
    assert not workflow.service.root.exists()


@pytest.mark.parametrize("source,kind,period,expected_year", [
    ("synthetic", "income", None, 2024),
    ("helium", "mining", "31.12.23", 2023),
], ids=["berlin-new-year", "helium-source-period"])
def test_tax_required_reporting_year_csv_uses_source_policy_not_utc_price_day(workflow, source, kind, period, expected_year):
    instant = datetime(2023, 12, 31, 23, 30, tzinfo=timezone.utc)
    workflow.mappings["TOKEN000"] = {
        "asset": "TOKEN000", "coingecko_id": "workflow-token000", "defillama_id": None,
    }
    batch = workflow.store.create_import_batch(ImportBatchCreate(source=source))
    payload = {"synthetic": "year-boundary"}
    if period is not None:
        payload["Period Start (UTC)"] = period
    raw = workflow.store.add_raw_object(batch.batch_id, RawObjectCreate(payload_json=json.dumps(payload)))
    workflow.store.add_canonical_event(CanonicalEventCreate(
        source=source, asset="TOKEN000", quantity=Decimal("1"), event_time=instant,
        event_type=kind, raw_object_id=raw.raw_object_id, source_ref="synthetic-year-boundary",
        account="synthetic-account",
    ))
    before = source_snapshot(workflow)
    _, selected = plan(workflow, scope="tax_required", year=expected_year)
    assert selected["requirements_count"] == 1
    row, = selected["rows"]
    assert row["years"] == [expected_year]
    assert row["event_year_counts"] == {str(expected_year): 1}
    _, excluded = plan(workflow, scope="tax_required", year=2023 if expected_year == 2024 else 2024)
    assert excluded["rows"] == [] and excluded["requirements_count"] == 0
    _, preview = fetch(workflow, scope="tax_required")
    row, = preview["rows"]
    assert row["price_date"] == "2023-12-31" and row["years"] == [expected_year]
    assert row["event_count"] == 1 and row["event_year_counts"] == {str(expected_year): 1}
    assert preview["prices_count"] == 1 and preview["canonical_events_unchanged"] is True
    calls_before = len(workflow.calls)
    response = workflow.client.get(BASE + f"/previews/{preview['id']}/report.zip")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        csv_paths = [path for path in archive.namelist() if path.endswith("/preise.csv")]
        assert csv_paths == [f"{expected_year}/preise.csv"]
        rows = list(csv.DictReader(io.StringIO(archive.read(csv_paths[0]).decode("utf-8"), newline="")))
    exported, = rows
    assert exported["asset"] == "TOKEN000" and exported["price_date"] == "2023-12-31"
    assert json.loads(exported["years"]) == [expected_year]
    assert json.loads(exported["event_year_counts"]) == {str(expected_year): 1}
    assert source_snapshot(workflow) == before
    assert len(workflow.calls) == calls_before and not workflow.store.list_price_points()
