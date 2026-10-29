from datetime import datetime, timedelta, timezone
from decimal import Decimal
import csv
import hashlib
from io import StringIO
import json

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.review import ReviewTask
from steuerreport_v2.contracts.workspace import WorkspaceReviewQuery
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.workspace import ActivityService, WorkspaceService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


@pytest.fixture(autouse=True)
def no_configured_wallets(monkeypatch):
    # These scenarios model accounts without the legacy suite's fixture wallets.
    from steuerreport_v2.domain.portfolio import PortfolioService
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")


@pytest.fixture
def workspace(tmp_path):
    store = DuckDbStore(tmp_path / "workspace.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="synthetic", filename="synthetic.csv", file_hash=hashlib.sha256(b"synthetic").hexdigest()))
    events = []
    for index in range(45):
        raw = store.add_raw_object(batch.batch_id, RawObjectCreate(row_number=index + 2, payload_json=json.dumps({"synthetic": index})))
        events.append(store.add_canonical_event(CanonicalEventCreate(
            source="synthetic", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
            event_type="trade" if index % 2 else "reward", asset="BTC" if index % 2 else "SOL",
            quantity=Decimal("0.123456789012345678"), account="synthetic-account", raw_object_id=raw.raw_object_id,
            quote_asset="EUR" if index % 2 else None, quote_quantity=Decimal("-10") if index % 2 else None,
            fee_asset="EUR", fee_quantity=Decimal("0.01"), tx_id=f"synthetic-tx-{index:03}",
        )))
    BalanceLedgerBuilder(store).rebuild()
    return store, TestClient(create_app(store)), events


def fingerprint(store):
    with store.connect() as con:
        names = con.execute("select table_name from information_schema.tables where table_schema='main' order by table_name").fetchall()
        values = [(name, con.execute('select * from "' + name + '" order by all').fetchall()) for (name,) in names]
    return hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()


def test_pagination_sort_filters_exact_decimals_and_readonly(workspace):
    store, client, events = workspace
    before = fingerprint(store)
    first = client.post("/api/v1/activity/query", json={"page_size": 10}).json()["data"]
    assert first["total"] == 45 and len(first["rows"]) == 10 and first["pages"] == 5
    assert first["rows"][0]["event"]["event_id"] == events[-1].event_id
    assert first["rows"][0]["event"]["quantity"] == "0.123456789012345678"
    second = client.post("/api/v1/activity/query", json={"page": 2, "page_size": 10}).json()["data"]
    assert not {row["row_id"] for row in first["rows"]} & {row["row_id"] for row in second["rows"]}
    oldest = client.post("/api/v1/activity/query", json={"sort": "oldest", "asset": "BTC", "event_type": "trade", "year": 2025}).json()["data"]
    assert oldest["total"] == 22 and oldest["rows"][0]["event"]["event_id"] == events[1].event_id
    last = client.post("/api/v1/activity/query", json={"page": 999, "page_size": 10}).json()["data"]
    assert last["page"] == 5 and len(last["rows"]) == 5
    assert fingerprint(store) == before


def test_private_search_is_body_only_and_does_not_interpret_sql(workspace):
    store, client, events = workspace
    found = client.post("/api/v1/activity/query", json={"search": "synthetic-tx-021"}).json()["data"]
    assert found["total"] == 1 and found["rows"][0]["event"]["event_id"] == events[21].event_id
    empty = client.post("/api/v1/activity/query", json={"search": "' OR 1=1 --"}).json()["data"]
    assert empty["total"] == 0
    assert len(store.list_canonical_events()) == 45
    assert client.post("/api/v1/activity/query", json={"sort": "event_time;drop table canonical_events"}).status_code == 422
    assert client.post("/api/v1/activity/query", json={"search": "x" * 201}).status_code == 422


def test_detail_original_raw_hash_row_and_ledger_semantics(workspace):
    store, client, events = workspace
    before = fingerprint(store)
    detail = client.get("/api/v1/activity/events/" + events[1].event_id).json()["data"]
    assert detail["raw"]["row_number"] == 3
    assert detail["raw"]["file_hash"] == hashlib.sha256(b"synthetic").hexdigest()
    assert json.loads(detail["raw"]["payload_json"]) == {"synthetic": 1}
    assert detail["ledger_count"] > 1
    ledger = client.post("/api/v1/activity/query", json={"mode": "ledger"}).json()["data"]
    assert ledger["total"] > 45 and ledger["mode"] == "ledger"
    assert client.get("/api/v1/activity/events/not-existing").status_code == 404
    assert fingerprint(store) == before


def test_export_scopes_match_exact_filter_and_selection(workspace):
    store, client, events = workspace
    before = fingerprint(store)
    def export(payload):
        response = client.post("/api/v1/activity/export.csv", json=payload)
        assert response.status_code == 200
        rows = list(csv.DictReader(StringIO(response.text.lstrip("\ufeff"))))
        assert len(rows) == int(response.headers["X-Export-Row-Count"])
        return rows
    filtered = export({"scope": "filtered", "query": {"asset": "BTC", "page": 2, "page_size": 10}})
    assert len(filtered) == 22 and {row["asset"] for row in filtered} == {"BTC"}
    selected = export({"scope": "selected", "selected_ids": [events[1].event_id, events[3].event_id], "query": {"asset": "BTC"}})
    assert len(selected) == 2
    complete = export({"scope": "all", "query": {"asset": "BTC"}})
    assert len(complete) == 45
    assert complete[0]["quantity"] == "0.123456789012345678"
    assert client.post("/api/v1/activity/export.csv", json={"scope": "selected"}).status_code == 400
    assert fingerprint(store) == before


def test_export_limit_fail_closed(workspace, monkeypatch):
    _store, client, _events = workspace
    monkeypatch.setattr(ActivityService, "EXPORT_LIMIT", 10)
    assert client.post("/api/v1/activity/export.csv", json={"scope": "all"}).status_code == 413


def test_fresh_account_has_no_catalog_placeholder_sources_and_no_filing_permission(tmp_path):
    store = DuckDbStore(tmp_path / "fresh.duckdb")
    client = TestClient(create_app(store))
    assert client.get("/api/v1/workspace/sources").json()["data"]["sources"] == []
    before = fingerprint(store)
    status = client.get("/api/v1/workspace/status?year=2025").json()["data"]
    assert status["owned_sources_count"] == status["events_count"] == 0
    assert not status["preview_available"] and not status["final_available"]
    assert status["next_section"] == "sources"
    assert status["dimensions"]["review"] == "Noch nicht prüfbar"
    assert fingerprint(store) == before


def test_sources_are_imported_not_catalog_and_source_query_is_opaque(workspace):
    store, client, _events = workspace
    before = fingerprint(store)
    sources = client.get("/api/v1/workspace/sources").json()["data"]["sources"]
    assert len(sources) == 1 and sources[0]["label"] == "synthetic-account"
    assert sources[0]["ref"].startswith("s_") and "synthetic" not in sources[0]["ref"]
    assert sources[0]["value_eur"] is None
    assert sources[0]["imports_count"] == 1
    ref = sources[0]["ref"]
    page = client.post("/api/v1/activity/query", json={"source_ref": ref}).json()["data"]
    assert page["total"] == 45
    detail = client.get("/api/v1/workspace/sources/" + ref).json()["data"]
    assert detail["source"]["ref"] == ref
    assert client.post("/api/v1/workspace/sources/" + ref + "/sync").status_code == 409
    assert fingerprint(store) == before


def test_explicit_readonly_metadata_for_post_queries(workspace):
    _store, client, _events = workspace
    schema = client.get("/openapi.json").json()
    for path in ("/api/v1/activity/query", "/api/v1/activity/export.csv"):
        assert schema["paths"][path]["post"]["x-data-effect"] == "read-only"
    assert schema["paths"]["/api/v1/workspace/sources/{ref}/sync"]["post"]["x-data-effect"] == "write"


def test_date_and_year_follow_existing_berlin_and_helium_period_policy(workspace):
    store, client, _events = workspace
    event = store.add_canonical_event(CanonicalEventCreate(source="boundary-test", event_time=datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc), event_type="reward", asset="TEST", quantity=Decimal("1")))
    assert client.post("/api/v1/activity/query", json={"year": 2025, "asset": "TEST"}).json()["data"]["total"] == 1
    assert client.post("/api/v1/activity/query", json={"year": 2024, "asset": "TEST"}).json()["data"]["total"] == 0
    row = client.post("/api/v1/activity/query", json={"start": "2025-01-01", "end": "2025-01-01", "asset": "TEST"}).json()["data"]["rows"][0]
    assert row["event"]["event_id"] == event.event_id and row["event"]["event_time"].endswith("Z")
    assert client.post("/api/v1/activity/query", json={"start": "2025-02-01", "end": "2025-01-01"}).status_code == 422
    assert WorkspaceService(store).sources().events_count == 46
    batch = store.create_import_batch(ImportBatchCreate(source="helium", filename="period.csv", file_hash="b" * 64))
    raw = store.add_raw_object(batch.batch_id, RawObjectCreate(row_number=2, payload_json=json.dumps({"Period Start (UTC)": "01.12.2024"})))
    store.add_canonical_event(CanonicalEventCreate(source="helium", event_time=datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc), event_type="mining", asset="IOT", quantity=Decimal("1"), raw_object_id=raw.raw_object_id))
    assert client.post("/api/v1/activity/query", json={"year": 2024, "asset": "IOT"}).json()["data"]["total"] == 1
    assert client.post("/api/v1/activity/query", json={"year": 2025, "asset": "IOT"}).json()["data"]["total"] == 0


def test_status_requires_selected_year_and_all_existing_filing_gates(workspace, monkeypatch):
    from steuerreport_v2.domain.product_readiness import ProductReadinessService
    from steuerreport_v2.domain.review import ReviewService
    store, client, _events = workspace
    with store.connect() as con:
        con.execute("insert into tax_run_summaries(run_id,tax_lines_count,unmatched_disposals,created_at) values ('synthetic-run',0,0,?)", [datetime.now(timezone.utc)])
    report = ProductReadinessService(store).report()
    gate = ReviewService(store).gate().model_copy(update={"allow_export": True, "issues_open": 0})
    monkeypatch.setattr(ReviewService, "gate", lambda self: gate)
    monkeypatch.setattr(ProductReadinessService, "report", lambda self: report.model_copy(update={"can_file_without_review": False, "ready_years": [2025]}))
    before = fingerprint(store)
    status = client.get("/api/v1/workspace/status?year=2025").json()["data"]
    assert status["preview_available"] and not status["final_available"]
    assert status["next_section"] == "tax"
    monkeypatch.setattr(ProductReadinessService, "report", lambda self: report.model_copy(update={"can_file_without_review": True, "ready_years": [2025]}))
    assert client.get("/api/v1/workspace/status?year=2025").json()["data"]["final_available"]
    other = client.get("/api/v1/workspace/status?year=2024").json()["data"]
    assert other["year_events_count"] == 0 and not other["preview_available"] and not other["final_available"]
    assert fingerprint(store) == before


def test_review_pagination_keeps_rules_and_only_links_existing_events(workspace):
    store, client, _events = workspace
    before = fingerprint(store)
    page = client.post("/api/v1/workspace/review/query", json={"page_size": 10}).json()["data"]
    assert page["total"] >= len(page["items"]) and len(page["items"]) <= 10
    if page["items"]:
        task = page["items"][0]
        exact = client.post("/api/v1/workspace/review/query", json={"task_id": task["task"]["task_id"]}).json()["data"]
        assert exact["total"] == 1
        known = {row.event_id for row in store.list_canonical_events()}
        assert set(task["event_ids"]) <= known
    assert client.post("/api/v1/workspace/review/query", json={"task_id": "non-existing"}).json()["data"]["total"] == 0
    assert fingerprint(store) == before


def test_review_context_binds_raw_evidence_to_the_exact_event(workspace):
    store, _client, events = workspace
    event = events[0]
    task = ReviewTask(task_id="synthetic-raw-link", priority="high", category="evidence", title="Beleg pruefen",
                      detail="Synthetische Pruefung", source="synthetic", scope=event.raw_object_id,
                      action_label="Pruefen", evidence_refs=[event.raw_object_id])
    service = WorkspaceService(store)
    items = service._review_items([task], service.source_scopes())
    assert len(items) == 1
    assert items[0].event_ids == [event.event_id]
    assert items[0].raw_evidence_by_event == {event.event_id: event.raw_object_id}


def test_sync_duplicate_guard_releases_after_provider_failure(workspace, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from steuerreport_v2.contracts.workspace import WorkspaceSource
    from steuerreport_v2.domain.portfolio import PortfolioService
    from steuerreport_v2.domain.workspace import SourceScope
    _store, client, _events = workspace
    entered, release = Event(), Event()
    source = WorkspaceSource(ref="s_" + "a" * 20, label="Synthetic", source_type="exchange", connection_status="configured", connector_id="binance", can_sync=True)
    monkeypatch.setattr(WorkspaceService, "scope", lambda self, ref: SourceScope(source, "false", []))
    def refresh(self, connectors=None):
        assert connectors == ["binance"]
        entered.set()
        assert release.wait(10)
        raise RuntimeError("synthetic-provider-failure")
    monkeypatch.setattr(PortfolioService, "refresh_reconciliation_snapshots", refresh)
    def first_request():
        with pytest.raises(RuntimeError, match="synthetic-provider-failure"):
            client.post("/api/v1/workspace/sources/" + source.ref + "/sync")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first_request)
        assert entered.wait(10)
        try:
            assert client.post("/api/v1/workspace/sources/" + source.ref + "/sync").status_code == 409
            assert client.post("/api/v1/pipeline/rebuild").status_code == 409
        finally:
            release.set()
        future.result()
    # A failed provider cannot leave the operation lock held.
    with pytest.raises(RuntimeError, match="synthetic-provider-failure"):
        client.post("/api/v1/workspace/sources/" + source.ref + "/sync")


def test_csv_escapes_formulas_without_corrupting_negative_decimals(workspace):
    store, client, _events = workspace
    event = store.add_canonical_event(CanonicalEventCreate(source="=synthetic-formula", event_time=datetime(2025, 6, 1, tzinfo=timezone.utc), event_type="trade", asset="TEST", quantity=Decimal("-0.123456789012345678")))
    response = client.post("/api/v1/activity/export.csv", json={"scope": "selected", "selected_ids": [event.event_id]})
    row = next(csv.DictReader(StringIO(response.text.lstrip("\ufeff"))))
    assert row["source"] == "'=synthetic-formula"
    assert row["quantity"] == "-0.123456789012345678"


def test_expected_zero_policy_is_not_a_confirmed_zero_and_failed_retry_keeps_success(tmp_path):
    from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
    from steuerreport_v2.contracts.prices import PricePointCreate
    from steuerreport_v2.domain.portfolio import PortfolioService
    store = DuckDbStore(tmp_path / "zero-status.duckdb")
    store.add_canonical_event(CanonicalEventCreate(source="pionex", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc), event_type="transfer", asset="USDT", quantity=Decimal("4"), account="pionex"))
    BalanceLedgerBuilder(store).rebuild()
    now = datetime.now(timezone.utc)
    store.add_price_point(PricePointCreate(asset="USDT", price_eur=Decimal("1"), priced_at=now, source="synthetic"))
    PortfolioService(store)._replace_live_balance_snapshots([
        PortfolioLiveBalanceSnapshot(
            snapshot_id="synthetic-old-snapshot", connector_id="pionex",
            asset="USDT", quantity=Decimal("2"), source="pionex_api_v2",
            fetched_at=now - timedelta(days=365),
        )
    ])
    service = WorkspaceService(store)
    row = next(row for row in service.sources().sources if row.connector_id == "pionex")
    assert row.value_eur is None and row.ledger_value_eur == Decimal("4")
    with store.connect() as con:
        con.execute("insert into portfolio_live_connector_runs values (?,?,?,?,?,?,?)", ["synthetic-empty", "pionex", now, "empty_response", 0, "pionex_api_v2", "Synthetic empty response"])
    row = next(row for row in service.sources().sources if row.connector_id == "pionex")
    assert row.value_eur == 0 and row.last_success_at == now
    with store.connect() as con:
        con.execute("insert into portfolio_live_connector_runs values (?,?,?,?,?,?,?)", ["synthetic-failure", "pionex", now + timedelta(seconds=1), "fetch_failed", 0, "pionex_api_v2", "Synthetic failure"])
    row = next(row for row in service.sources().sources if row.connector_id == "pionex")
    assert row.value_eur == 0 and row.last_success_at == now
    assert row.last_attempt.status == "fetch_failed"


@pytest.fixture
def negative_context(tmp_path):
    from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
    from steuerreport_v2.importers.raw_normalizer import RawNormalizer
    store = DuckDbStore(tmp_path / "context.duckdb")
    batch = CsvRawImporter(store).import_text(source="manual-csv", filename="synthetic-original.csv", content=(
        "time,asset,amount,type,account\n"
        "2025-01-02T10:00:00Z,EUR,-10,withdrawal,alpha-account\n"
        "2025-01-02T10:00:00Z,EUR,50,deposit,beta-account\n"
    ))
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    return store, TestClient(create_app(store)), batch


def test_negative_account_is_linked_consistently_in_source_review_and_filtered_ledger(negative_context):
    store, client, _batch = negative_context
    before = fingerprint(store)
    page = client.post("/api/v1/workspace/review/query", json={}).json()["data"]
    task = next(item for item in page["items"] if item["task"]["decision_status"] == "negative_balance")
    assert task["account"] == "alpha-account" and task["task"]["asset"] == "EUR"
    assert task["context_status"] == "matched" and task["source_ref"]
    assert task["account_ref"].startswith("a_") and "alpha" not in task["account_ref"]
    sources = client.get("/api/v1/workspace/sources").json()["data"]["sources"]
    source = next(row for row in sources if row["ref"] == task["source_ref"])
    assert source["issues_count"] == 0  # Native valuation hints stay a separate set.
    assert source["review_tasks_count"] == source["blocking_review_tasks_count"] == 1
    assert source["review_reconciliation_tasks_count"] == 1
    other = next(row for row in sources if row["ref"] != source["ref"])
    assert other["review_tasks_count"] == 0
    detail = client.get("/api/v1/workspace/sources/" + source["ref"]).json()["data"]
    assert detail["source"] == source
    assert [item["task"]["task_id"] for item in detail["review_tasks"]] == [task["task"]["task_id"]]
    filtered = client.post("/api/v1/workspace/review/query", json={"source_ref": source["ref"]}).json()["data"]
    assert filtered["total"] == 1
    ledger = client.post("/api/v1/activity/query", json={"mode": "ledger", "source_ref": source["ref"], "account_ref": task["account_ref"], "asset": "EUR"}).json()["data"]
    assert ledger["total"] == 1 and ledger["account_label"] == "alpha-account"
    assert ledger["rows"][0]["ledger_account"] == "alpha-account"
    assert ledger["rows"][0]["ledger_asset"] == "EUR"
    assert Decimal(ledger["rows"][0]["ledger_quantity"]) == -10
    assert fingerprint(store) == before


def test_real_synthetic_funding_import_clears_context_everywhere_without_accepting_decision(negative_context):
    from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
    from steuerreport_v2.importers.raw_normalizer import RawNormalizer
    store, client, original = negative_context
    task = client.post("/api/v1/workspace/review/query", json={}).json()["data"]["items"][0]
    ref = task["source_ref"]
    # Actual disposable data correction through the existing import/ledger path,
    # not a mocked empty task list or a documentary review acceptance.
    funding = CsvRawImporter(store).import_text(source="manual-csv", filename="synthetic-funding.csv", content=(
        "time,asset,amount,type,account\n"
        "2025-01-01T10:00:00Z,EUR,20,deposit,alpha-account\n"
    ))
    RawNormalizer(store).normalize_batch(funding.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    sources = client.get("/api/v1/workspace/sources").json()["data"]["sources"]
    source = next(row for row in sources if row["ref"] == ref)
    assert source["review_tasks_count"] == source["review_reconciliation_tasks_count"] == source["blocking_review_tasks_count"] == 0
    detail = client.get("/api/v1/workspace/sources/" + ref).json()["data"]
    assert detail["review_tasks"] == []
    assert client.post("/api/v1/workspace/review/query", json={"task_id": task["task"]["task_id"]}).json()["data"]["total"] == 0
    assert store.list_review_decisions() == []
    assert store.get_import_batch(original.batch_id).file_hash == original.file_hash


def test_review_resolution_preserves_ambiguity_and_ignores_translated_labels(negative_context):
    from steuerreport_v2.domain.review import ReviewService
    from steuerreport_v2.domain.workspace import SourceScope
    store, _client, _batch = negative_context
    service = WorkspaceService(store)
    scopes = service.source_scopes()
    task = next(task for task in ReviewService(store).tasks(limit=None).tasks if task.decision_status == "negative_balance")
    matched = service._review_items([task], scopes)[0]
    scope = next(scope for scope in scopes if scope.item.ref == matched.source_ref)
    scope.item.label = "A renamed display label"
    assert service._review_items([task], scopes)[0].source_ref == matched.source_ref
    duplicate = SourceScope(scope.item.model_copy(update={"ref": "s_" + "f" * 20}), scope.predicate, scope.parameters)
    ambiguous = service._review_items([task], [*scopes, duplicate])[0]
    assert ambiguous.context_status == "ambiguous" and ambiguous.source_ref is None
    assert len(ambiguous.candidate_source_refs) == 2
    service._attach_review([*scopes, duplicate])
    assert scope.item.ambiguous_review_tasks_count == scope.item.blocking_review_tasks_count == 1
    missing = task.model_copy(update={"scope": "account:missing-account:asset:EUR", "evidence_refs": []})
    unresolved = service._review_items([missing], scopes)[0]
    assert unresolved.context_status == "unresolved" and unresolved.source_ref is None
    combined = task.model_copy(update={"evidence_refs": ["account:beta-account:asset:EUR"]})
    multiple = service._review_items([combined], scopes)[0]
    assert multiple.context_status == "ambiguous" and multiple.account_ref is None
    assert len(multiple.candidate_source_refs) == 2
    partial = task.model_copy(update={"evidence_refs": ["account:missing-account:asset:EUR"]})
    assert service._review_items([partial], scopes)[0].context_status == "ambiguous"


def test_source_task_preview_is_bounded_with_complete_counts(negative_context, monkeypatch):
    from steuerreport_v2.domain.review import ReviewService
    store, _client, _batch = negative_context
    summary = ReviewService(store).tasks(limit=None)
    task = next(task for task in summary.tasks if task.decision_status == "negative_balance")
    tasks = [task.model_copy(update={"task_id": f"synthetic-task-{index:03d}"}) for index in range(51)]
    monkeypatch.setattr(ReviewService, "tasks", lambda *_args, **_kwargs: summary.model_copy(update={"tasks": tasks, "open_tasks": 51, "blocking_tasks": 51}))
    service = WorkspaceService(store)
    source = next(row for row in service.sources().sources if row.review_tasks_count)
    detail = service.source(source.ref)
    assert source.review_tasks_count == source.blocking_review_tasks_count == 51
    assert len(detail.review_tasks) == detail.review_tasks_limit == 50
    page = service.review_page(WorkspaceReviewQuery(source_ref=source.ref, page=3, page_size=25))
    assert page.total == 51 and len(page.items) == 1


def test_workspace_environment_is_explicit_and_readonly(workspace):
    store, client, _events = workspace
    before = fingerprint(store)
    assert client.get("/api/v1/workspace/environment").json()["data"] == {"synthetic_preview": False, "read_only": False}
    assert fingerprint(store) == before
