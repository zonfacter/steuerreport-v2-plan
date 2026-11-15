import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


@pytest.fixture
def current(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2025, 6, 2, 12, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.datetime", Clock)
    store = DuckDbStore(tmp_path / "isolated.duckdb")
    config = tmp_path / "assets.json"
    config.write_text('{"assets":[{"symbol":"AAA","coingecko_id":"a"},{"symbol":"BBB","defillama_id":"synthetic:b"}]}')
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.BalanceLedgerBuilder", lambda store: SimpleNamespace(
        positions=lambda: [SimpleNamespace(asset=a, quantity=Decimal("1")) for a in ("AAA", "BBB")]
    ))
    monkeypatch.setattr(ExternalPriceBackfillService, "_token_risk_statuses", lambda self: {})
    calls = []
    def coin(self, client, ids):
        calls.append("coin")
        return {"a": Decimal("2")}
    def defi(self, client, ids):
        calls.append("defi")
        return {"synthetic:b": Decimal("3")}
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", coin)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", defi)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", lambda *args: (Decimal("0.9"), "2025-06-01"))
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: PipelineResult(
        normalized_events=0, balance_entries=0, flow_entries=0, tax_lines=0, review_issues_open=0, allow_export=False,
    ))
    payload = {"config_path": str(config), "dry_run": False, "request_id": str(uuid4())}
    return store, payload, calls


def test_success_ids_and_replay_blocked_after_restart(current):
    store, payload, calls = current
    client = TestClient(create_app(store))
    first = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert first.status_code == 200
    data = first.json()["data"]
    assert data["imported_prices"] == 2 and data["pipeline_status"] == "completed"
    assert set(data["stored_price_ids"]) == {p.price_id for p in store.list_price_points()}
    second = TestClient(create_app(DuckDbStore(store.path))).post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert second.status_code == 409 and second.json()["errors"][0]["code"] == "current_backfill_replay_blocked"
    assert calls == ["coin", "defi"] and len(store.list_price_points()) == 2
    changed = {**payload, "assets": ["AAA"]}
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=changed).status_code == 409


def test_legacy_payload_repeat_blocked_and_new_explicit_request(current):
    store, payload, calls = current
    payload.pop("request_id")
    client = TestClient(create_app(store))
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert len(calls) == 2
    payload["request_id"] = str(uuid4())
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200
    assert len(store.list_price_points()) == 4


@pytest.mark.parametrize("failed_provider", ["coin", "defi", "fx"])
def test_provider_failure_is_sanitized_and_other_prices_survive(current, monkeypatch, caplog, failed_provider):
    store, payload, _ = current
    canary = "SYNTHETIC_PROVIDER_SECRET_49"
    method = {"coin": "_fetch_coingecko_simple_prices_eur", "defi": "_fetch_defillama_current_prices_usd", "fx": "_fetch_frankfurter_usd_eur"}[failed_provider]
    def fail(*args, **kwargs):
        raise RuntimeError(f"/private/path?token={canary}")
    monkeypatch.setattr(ExternalPriceBackfillService, method, fail)
    caplog.set_level(logging.ERROR)
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    body = response.json()
    assert body["data"]["failed"] == 1 and body["data"]["imported_prices"] == 1
    assert "price_provider_error" in {w["code"] for w in body["warnings"]}
    assert canary not in response.text + caplog.text and "/private/path" not in response.text + caplog.text
    assert set(body["data"]["stored_price_ids"]) == {p.price_id for p in store.list_price_points()}


@pytest.mark.parametrize("signal", [RequestCancelled, RequestDeadlineExceeded])
def test_cancel_or_deadline_stops_before_price_write_and_pipeline(current, monkeypatch, caplog, signal):
    store, payload, calls = current
    def fail(*args):
        raise signal("SYNTHETIC_CANCELLATION_SECRET")
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", fail)
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: pytest.fail("pipeline must not run"))
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    result = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert result.status_code == 503 and result.json()["data"]["storage_status"] == "not_started"
    assert not store.list_price_points() and "SYNTHETIC_CANCELLATION_SECRET" not in result.text + caplog.text
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert calls == ["coin"]


@pytest.mark.parametrize("insert_before_failure", [False, True])
def test_storage_failure_unknown_before_and_after_write_blocks_repeat(current, monkeypatch, caplog, insert_before_failure):
    store, payload, calls = current
    original = store.add_price_points
    def fail(prices):
        if insert_before_failure:
            original(prices)
        raise RuntimeError("SYNTHETIC_STORAGE_SECRET")
    monkeypatch.setattr(store, "add_price_points", fail)
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: pytest.fail("pipeline must not run"))
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 500
    assert response.json()["data"] == {"storage_status": "unknown", "pipeline_status": "not_started"}
    assert "SYNTHETIC_STORAGE_SECRET" not in response.text + caplog.text
    assert len(store.list_price_points()) == (2 if insert_before_failure else 0)
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert calls == ["coin", "defi"]


def test_pipeline_failure_has_ids_unknown_effects_no_secret_and_no_retry(current, monkeypatch, caplog):
    store, payload, calls = current
    def fail(self):
        raise RuntimeError("SYNTHETIC_PIPELINE_SECRET")
    monkeypatch.setattr(PipelineService, "rebuild_all", fail)
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    data = response.json()["data"]
    assert data["pipeline_status"] == "failed" and data["pipeline_effects"] == "unknown_or_partial"
    assert set(data["stored_price_ids"]) == {p.price_id for p in store.list_price_points()}
    assert "SYNTHETIC_PIPELINE_SECRET" not in response.text + caplog.text
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert calls == ["coin", "defi"]


def test_dry_run_does_not_reserve_apply_key(current):
    store, payload, calls = current
    client = TestClient(create_app(store))
    assert client.post("/api/v1/prices/backfill/current-portfolio", json={**payload, "dry_run": True}).status_code == 200
    assert calls == [] and not store.list_price_points()
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200


def test_provider_context_exception_does_not_leak_and_blocks_replay(current, monkeypatch, caplog):
    store, payload, calls = current
    def fail(**kwargs):
        raise RuntimeError("SYNTHETIC_CONTEXT_SECRET")
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", fail)
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 503 and response.json()["data"]["storage_status"] == "not_started"
    assert "SYNTHETIC_CONTEXT_SECRET" not in response.text + caplog.text
    assert not store.list_price_points() and calls == []
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409


def test_provider_and_pipeline_warnings_coexist(current, monkeypatch):
    store, payload, _ = current
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic")))
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: (_ for _ in ()).throw(RuntimeError("synthetic")))
    body = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload).json()
    assert {w["code"] for w in body["warnings"]} >= {"price_provider_error", "price_backfill_partial_failure", "price_backfill_pipeline_failed", "usd_eur_daily_reference_unverified"}
    assert len(body["data"]["stored_price_ids"]) == 1


def test_concurrent_duplicate_request_has_only_one_price_write(current):
    store, payload, calls = current
    client = TestClient(create_app(store))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/api/v1/prices/backfill/current-portfolio", json=payload), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert calls == ["coin", "defi"] and len(store.list_price_points()) == 2


def test_schema_open_adds_reservation_table_without_price_operation(current):
    store, payload, calls = current
    response = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and len(store.list_price_points()) == 2
    calls.clear()
    # Model the previous schema-3 database without the additive table.
    with store.connect() as con:
        con.execute("drop table current_price_backfill_requests")
        before = con.execute("select * from price_ledger").fetchall()
    upgraded = DuckDbStore(store.path)
    with upgraded.connect() as con:
        assert con.execute("select * from current_price_backfill_requests").fetchall() == []
        assert con.execute("select * from price_ledger").fetchall() == before
    assert calls == []


def test_schema_open_preserves_existing_reservation_bytes(current):
    store, _, _ = current
    assert store.reserve_current_price_backfill("synthetic-existing-request")
    with store.connect() as con:
        before = con.execute("select * from current_price_backfill_requests").fetchall()
    reopened = DuckDbStore(store.path)
    assert not reopened.reserve_current_price_backfill("synthetic-existing-request")
    with reopened.connect() as con:
        assert con.execute("select * from current_price_backfill_requests").fetchall() == before


def test_malformed_reservation_table_stops_before_provider(current, caplog):
    store, payload, calls = current
    with store.connect() as con:
        con.execute("drop table current_price_backfill_requests")
        con.execute("create table current_price_backfill_requests (broken varchar)")
    response = TestClient(create_app(DuckDbStore(store.path))).post(
        "/api/v1/prices/backfill/current-portfolio", json=payload,
    )
    assert response.status_code == 503 and not calls
    assert not store.list_price_points()


def test_status_reads_persisted_result_after_restart_without_provider_or_pipeline(current, monkeypatch):
    store, payload, calls = current
    first = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload).json()["data"]
    before_prices = [p.model_dump() for p in store.list_price_points()]
    assert first["result_journal_status"] == "recorded"
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: pytest.fail("status must not rebuild"))
    response = TestClient(create_app(DuckDbStore(store.path))).post(
        "/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]},
    )
    assert response.status_code == 200 and response.json()["data"]["status"] == "recorded"
    assert response.json()["data"]["result"] == first
    assert [p.model_dump() for p in store.list_price_points()] == before_prices
    assert calls == ["coin", "defi"]


def test_status_does_not_turn_missing_or_incomplete_request_into_success(current, monkeypatch):
    store, payload, calls = current
    client = TestClient(create_app(store))
    query = {"request_id": payload["request_id"]}
    assert client.post("/api/v1/prices/backfill/current-portfolio/status", json=query).json()["data"]["status"] == "not_found"
    def fail(prices):
        raise RuntimeError("synthetic storage failure")
    monkeypatch.setattr(store, "add_price_points", fail)
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 500
    status = client.post("/api/v1/prices/backfill/current-portfolio/status", json=query).json()["data"]
    assert status["status"] == "unknown_or_running" and status["result"] is None
    assert calls == ["coin", "defi"]


@pytest.mark.parametrize("write_first", [False, True])
def test_journal_failure_is_unknown_and_never_retries_price_operation(current, monkeypatch, caplog, write_first):
    store, payload, calls = current
    original = store.record_current_price_backfill
    def fail(key, result):
        if write_first:
            original(key, result)
        raise RuntimeError("SYNTHETIC_JOURNAL_SECRET")
    monkeypatch.setattr(store, "record_current_price_backfill", fail)
    caplog.set_level(logging.ERROR)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    assert response.json()["data"]["result_journal_status"] == "unknown"
    assert any(w["code"] == "current_backfill_journal_unknown" for w in response.json()["warnings"])
    assert "SYNTHETIC_JOURNAL_SECRET" not in response.text + caplog.text
    status = client.post("/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]}).json()["data"]
    assert status["status"] == ("recorded" if write_first else "unknown_or_running")
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert len(store.list_price_points()) == 2 and calls == ["coin", "defi"]


def test_status_with_corrupt_result_is_unknown_without_disclosure(current, caplog):
    store, payload, calls = current
    client = TestClient(create_app(store))
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 200
    with store.connect() as con:
        con.execute("update current_price_backfill_requests set result_json='SYNTHETIC_CORRUPT_SECRET'")
    response = client.post("/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]})
    assert response.status_code == 500
    assert response.json()["data"]["status"] == "unknown"
    assert "SYNTHETIC_CORRUPT_SECRET" not in response.text + caplog.text
    assert calls == ["coin", "defi"]


def test_legacy_reservation_without_journal_stays_unknown_and_blocked(current):
    store, payload, calls = current
    service = ExternalPriceBackfillService(store)
    key = service._explicit_current_request_hash(payload["request_id"])
    assert store.reserve_current_price_backfill(key)
    with store.connect() as con:
        con.execute("alter table current_price_backfill_requests drop column result_json")
        before = con.execute("select request_hash, reserved_at from current_price_backfill_requests").fetchall()
    client = TestClient(create_app(DuckDbStore(store.path)))
    response = client.post("/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]})
    assert response.json()["data"]["status"] == "unknown_or_running"
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    with store.connect() as con:
        assert con.execute("select request_hash, reserved_at from current_price_backfill_requests").fetchall() == before
    assert calls == []


def test_status_preserves_original_partial_price_warnings(current, monkeypatch):
    store, payload, calls = current
    def fail(*args):
        raise RuntimeError("synthetic provider failure")
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", fail)
    client = TestClient(create_app(store))
    original = client.post("/api/v1/prices/backfill/current-portfolio", json=payload).json()
    restored = client.post("/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]}).json()
    assert restored["status"] == "warning" and restored["data"]["result"]["failed"] == 1
    assert {w["code"] for w in restored["warnings"]} == {w["code"] for w in original["warnings"]}
    assert {w["code"] for w in restored["warnings"]} >= {"price_provider_error", "price_backfill_partial_failure"}
    assert calls == ["defi"]


def test_status_contract_is_read_only(current):
    store, _, _ = current
    operation = create_app(store).openapi()["paths"]["/api/v1/prices/backfill/current-portfolio/status"]["post"]
    assert operation["x-data-effect"] == "read-only"


def test_offline_clone_preserves_result_journal_prices_and_replay_guard(current, tmp_path):
    from steuerreport_v2.db.offline_snapshot import clone_offline_database

    store, payload, calls = current
    original = TestClient(create_app(store)).post("/api/v1/prices/backfill/current-portfolio", json=payload).json()
    assert original["data"]["imported_prices"] == 2
    assert original["data"]["pipeline_status"] == "completed"
    assert original["data"]["result_journal_status"] == "recorded"
    with store.connect() as con:
        journal = con.execute("select * from current_price_backfill_requests").fetchall()
    before = store.path.read_bytes()
    backup, restored = tmp_path / "backup.duckdb", tmp_path / "restored.duckdb"
    proof = clone_offline_database(store.path, backup)
    restored_proof = clone_offline_database(backup, restored, expected_sha256=proof.target_sha256)
    assert proof.source_sha256 == restored_proof.target_sha256
    assert store.path.read_bytes() == before == restored.read_bytes()
    recovered = DuckDbStore(restored)
    client = TestClient(create_app(recovered))
    response = client.post("/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]})
    assert response.status_code == 200 and response.json()["data"]["result"] == original["data"]
    assert response.json()["warnings"] == original["warnings"]
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    assert {p.price_id for p in recovered.list_price_points()} == set(original["data"]["stored_price_ids"])
    with recovered.connect() as con:
        assert con.execute("select * from current_price_backfill_requests").fetchall() == journal
    assert calls == ["coin", "defi"] and store.path.read_bytes() == before


def test_partial_price_job_and_filing_comparison_share_state_without_reexecution(current, monkeypatch):
    import hashlib
    import io
    import json
    import zipfile
    from steuerreport_v2.contracts.tax_filing_snapshots import TaxFilingSnapshotCaptureRequest
    from steuerreport_v2.domain.tax_filing_snapshots import TaxFilingSnapshotService

    store, payload, calls = current
    summary = {"year": 2025, "generated_at": "2026-01-01T00:00:00Z", "export_ready": False,
               "tax_free_lines_count": 0, **{field: "0" for field in (
                   "taxable_private_disposals_eur", "taxable_disposal_proceeds_eur", "acquisition_cost_eur",
                   "rewards_mining_staking_income_eur", "derivative_pnl_eur", "tax_free_private_disposals_eur")}}
    content = json.dumps(summary).encode()
    path = "02_Steuerliche_CSVs/tax-year-2025-filing-summary.json"
    manifest = {"year": 2025, "generated_at": summary["generated_at"], "files": [
        {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}]}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("00_Manifest/year-evidence-manifest.json", json.dumps(manifest))
        package.writestr(path, content)
    service = TaxFilingSnapshotService(store)
    reference = service.capture_package(year=2025, package_bytes=archive.getvalue(),
        request=TaxFilingSnapshotCaptureRequest(), source_kind="synthetic-integration").snapshot
    pipeline_calls = []
    def partial_pipeline(self):
        pipeline_calls.append("pipeline")
        with store.connect() as con:
            con.execute("""insert into derivative_lines
                (derivative_line_id, event_id, source, event_time, asset, quantity,
                 price_eur, value_eur, price_source, created_at)
                values ('synthetic-partial', 'synthetic-event', 'synthetic', '2025-06-02',
                        'EUR', 10, 1, 10, 'synthetic', '2025-06-02')""")
        raise RuntimeError("synthetic partial pipeline")
    monkeypatch.setattr(PipelineService, "rebuild_all", partial_pipeline)
    client = TestClient(create_app(store))
    response = client.post("/api/v1/prices/backfill/current-portfolio", json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    original_result = response.json()["data"]
    assert original_result["pipeline_status"] == "failed"
    assert len(original_result["stored_price_ids"]) == 2
    with store.connect() as con:
        original_journal = con.execute("select * from current_price_backfill_requests").fetchall()
    comparison = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison").json()["data"]
    assert comparison["comparison_scope"]["aggregate_status"] == "different"
    assert comparison["comparison_scope"]["detail_reconciliation"] == "not_compared"
    assert comparison["submission_confirmation_required"] is True
    assert Decimal(comparison["current_values"]["derivative_pnl_eur"]) == Decimal("10")
    restored = client.post("/api/v1/prices/backfill/current-portfolio/status", json={"request_id": payload["request_id"]})
    assert restored.json()["status"] == "warning"
    assert restored.json()["data"]["result"] == original_result
    assert client.post("/api/v1/prices/backfill/current-portfolio", json=payload).status_code == 409
    with store.connect() as con:
        assert con.execute("select * from current_price_backfill_requests").fetchall() == original_journal
    assert service.read_package(reference.snapshot_id) == archive.getvalue()
    assert calls == ["coin", "defi"] and pipeline_calls == ["pipeline"]
