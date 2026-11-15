"""Unabhaengige Issue49-Vertragsproben mit eigener DuckDB und Fake-Providern.

Fehlende neue Schnittstellen sind explizite Vertragsluecken, kein Nachweis
falscher Altpreise. Die Crash-Proben werfen nur im Test einen BaseException-
Abbruch; es wird kein echter Prozess und kein externer Provider gestartet.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import inspect
import json
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.db.offline_snapshot import clone_offline_database
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.historical_fx import FxReference
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


KINDS = ("current_portfolio", "historical")
URLS = {"current_portfolio": "/api/v1/prices/backfill/current-portfolio",
        "historical": "/api/v1/prices/backfill/external"}
CANARY = "SYNTHETIC_PRIVATE_CHECKPOINT_49"
PRIVATE_ERROR = f"/private/checkpoint-49?token={CANARY}"
NOW = datetime(2025, 6, 2, 12, tzinfo=timezone.utc)


class SimulatedProcessCrash(BaseException):
    """Modelliert fehlendes finales Journal, nicht einen normalen Fachfehler."""


def method(store, name):
    value = getattr(store, name, None)
    assert callable(value), f"VERTRAGSLUECKE: Store-Schnittstelle {name} fehlt"
    return value


def request_hash(kind, request_id):
    identity = {"request_id": str(request_id)}
    if kind == "historical":
        identity["operation_kind"] = kind
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reserve(store, kind, key):
    name = "reserve_current_price_backfill" if kind == "current_portfolio" else "reserve_historical_price_backfill"
    assert method(store, name)(key)


def record_method(store, kind):
    return method(store, "record_current_price_backfill" if kind == "current_portfolio"
                  else "record_historical_price_backfill")


def prices(count=2, *, same_asset=False):
    return [PricePointCreate(asset="DUP49" if same_asset else f"SYNTH49_{index:04d}",
                             price_eur=Decimal(index + 1), priced_at=NOW,
                             source="synthetic-acceptance") for index in range(count)]


def snapshot(store):
    with store.connect() as con:
        return (con.execute("select * from price_ledger order by price_id").fetchall(),
                con.execute("select * from current_price_backfill_requests order by request_hash").fetchall())


def status(client, kind, request_id):
    response = client.post(URLS[kind] + "/status", json={"request_id": str(request_id)})
    assert response.status_code != 404, f"VERTRAGSLUECKE: lesender {kind}-Statuspfad fehlt"
    assert response.status_code == 200, response.text
    assert str(request_id) not in str(response.request.url)
    return response


def assert_private(response, caplog, case):
    text = response.text + caplog.text
    for secret in (CANARY, "/private/checkpoint-49", str(case.config), str(case.store.path)):
        assert secret not in text


def assert_checkpoint(store, kind, key, body, ids, phase):
    checkpoint = body.get("checkpoint")
    assert isinstance(checkpoint, dict), (
        f"VERTRAGSLUECKE: Checkpoint fehlt fuer bekannte Preis-IDs {sorted(ids)}; Status={body}"
    )
    assert checkpoint["format_version"] == 1
    assert checkpoint["operation_kind"] == kind
    assert len(checkpoint["stored_price_ids"]) == len(set(checkpoint["stored_price_ids"]))
    assert set(checkpoint["stored_price_ids"]) == set(ids)
    assert all(str(UUID(value)) == value for value in checkpoint["stored_price_ids"])
    assert checkpoint["pipeline_status"] == phase
    stored_at = datetime.fromisoformat(checkpoint["stored_at"].replace("Z", "+00:00"))
    assert stored_at.utcoffset() is not None and stored_at.utcoffset().total_seconds() == 0
    row = method(store, "price_backfill_operation_record")(key, kind)
    assert row is not None and isinstance(row[1], str)
    assert json.loads(row[1]) == checkpoint
    assert body["checkpoint_sha256"] == hashlib.sha256(row[1].encode("utf-8")).hexdigest()
    return row


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Eigenes minimales Gegenstueck zum Current-Partial-Muster, ohne Testimporte.
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2025, 6, 2, 12, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.datetime", Clock)
    store = DuckDbStore(tmp_path / "acceptance.duckdb")
    config = tmp_path / "synthetic-assets.json"
    config.write_text(json.dumps({"assets": [
        {"symbol": "AAA", "coingecko_id": "synthetic-a"},
        {"symbol": "BBB", "defillama_id": "synthetic:b"},
    ]}), encoding="ascii")
    for index, asset in enumerate(("AAA", "BBB")):
        store.add_canonical_event(CanonicalEventCreate(
            source="synthetic-checkpoint", source_ref=asset,
            event_time=datetime(2024, 1, index + 1, 12, tzinfo=timezone.utc),
            event_type="reward", asset=asset, quantity=Decimal("1"),
        ))
    calls, pipeline_calls = [], []
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client",
                        lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.BalanceLedgerBuilder",
                        lambda store: SimpleNamespace(positions=lambda: [
                            SimpleNamespace(asset=asset, quantity=Decimal("1")) for asset in ("AAA", "BBB")]))
    monkeypatch.setattr(ExternalPriceBackfillService, "_token_risk_statuses", lambda self: {})
    def coin(self, client, ids):
        calls.append("current-coin")
        return {"synthetic-a": Decimal("2")}
    def defi(self, client, ids):
        calls.append("current-defi")
        return {"synthetic:b": Decimal("3")}
    def fx(self, client):
        calls.append("current-fx")
        return Decimal("0.9"), "2025-06-01"
    def historical(self, **kwargs):
        calls.append("historical-" + kwargs["date_str"])
        return Decimal("10"), "synthetic-provider"
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_coingecko_simple_prices_eur", coin)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_defillama_current_prices_usd", defi)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_frankfurter_usd_eur", fx)
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", historical)
    monkeypatch.setattr(ExternalPriceBackfillService, "_timed_usd_eur_reference", lambda *args: FxReference(
        Decimal("0.9"), date(2023, 12, 31), "USD", "EUR", Decimal("0.9"), "synthetic"))
    def pipeline(self):
        pipeline_calls.append("pipeline")
        return PipelineResult(normalized_events=0, balance_entries=0, flow_entries=0,
                              tax_lines=0, review_issues_open=0, allow_export=False)
    monkeypatch.setattr(PipelineService, "rebuild_all", pipeline)
    def payload(kind, request_id=None):
        value = {"config_path": str(config), "dry_run": False, "request_id": str(request_id or uuid4())}
        if kind == "historical":
            value["v1_fx_db_path"] = str(tmp_path / "never-read-private-fx.sqlite")
        return value
    return SimpleNamespace(store=store, config=config, calls=calls, pipeline_calls=pipeline_calls, payload=payload)


def domain_apply(case, kind, payload):
    service = ExternalPriceBackfillService(case.store)
    kwargs = dict(config_path=payload["config_path"], provider="auto" if kind == "historical" else "coingecko",
                  assets_filter=[], max_requests=25, timeout_seconds=5,
                  confidence=Decimal("0.95"), dry_run=False, request_id=payload["request_id"])
    target = service.run_current_portfolio if kind == "current_portfolio" else service.run
    assert "request_id" in inspect.signature(target).parameters, (
        f"VERTRAGSLUECKE: Domain-{kind} nimmt noch keine Request-ID an"
    )
    if kind == "historical":
        kwargs["v1_fx_db_path"] = payload["v1_fx_db_path"]
    return target(**kwargs)


@pytest.mark.parametrize("kind", KINDS)
def test_success_checkpoint_matches_exact_bytes_and_status_is_read_only(case, kind, monkeypatch, caplog):
    client = TestClient(create_app(case.store))
    payload = case.payload(kind)
    response = client.post(URLS[kind], json=payload)
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    ids = {price.price_id for price in case.store.list_price_points()}
    assert len(ids) == 2 and set(result["stored_price_ids"]) == ids
    assert "result_journal_status" in result, "VERTRAGSLUECKE: Result-Journalstatus fehlt"
    assert result["result_journal_status"] == "recorded"
    assert result["pipeline"]["allow_export"] is False
    before, calls, pipelines = snapshot(case.store), case.calls[:], case.pipeline_calls[:]
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: pytest.fail("Status darf keine Pipeline starten"))
    reopened = DuckDbStore(case.store.path)
    read = status(TestClient(create_app(reopened)), kind, payload["request_id"])
    body = read.json()["data"]
    assert body["status"] == "recorded" and body["result"] == result
    assert_checkpoint(reopened, kind, request_hash(kind, payload["request_id"]), body, ids, "completed")
    assert read.json()["warnings"] == response.json()["warnings"]
    assert snapshot(reopened) == before and case.calls == calls and case.pipeline_calls == pipelines
    assert not reopened.list_review_decisions()
    assert_private(read, caplog, case)


@pytest.mark.parametrize("kind", KINDS)
def test_identical_replay_after_restart_never_repeats_provider_price_or_pipeline(case, kind):
    payload = case.payload(kind)
    response = TestClient(create_app(case.store)).post(URLS[kind], json=payload)
    assert response.status_code == 200
    before, calls, pipelines = snapshot(case.store), case.calls[:], case.pipeline_calls[:]
    client = TestClient(create_app(DuckDbStore(case.store.path)))
    for repeated in (payload, {**payload, "assets": ["AAA"]}):
        replay = client.post(URLS[kind], json=repeated)
        assert replay.status_code == 409, f"GEGENBELEG: identischer Auftrag wird erneut ausgefuehrt: {replay.text}"
    assert snapshot(case.store) == before and case.calls == calls and case.pipeline_calls == pipelines


@pytest.mark.parametrize("kind", KINDS)
def test_parallel_same_id_uses_persistent_reservation_between_store_instances(case, kind, monkeypatch):
    payload = case.payload(kind)
    clients = [TestClient(create_app(DuckDbStore(case.store.path))) for _ in range(2)]
    entered, release, rejected = Event(), Event(), Event()
    name = "_fetch_coingecko_simple_prices_eur" if kind == "current_portfolio" else "_fetch_price_usd"
    fetch = getattr(ExternalPriceBackfillService, name)
    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(10), "Testfreigabe des Fake-Providers fehlt"
        return fetch(*args, **kwargs)
    monkeypatch.setattr(ExternalPriceBackfillService, name, gated)
    def apply(client):
        response = client.post(URLS[kind], json=payload)
        if response.status_code in (409, 503):
            rejected.set()
        return response
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply, client) for client in clients]
        try:
            assert entered.wait(10)
            blocked_before_provider_return = rejected.wait(5)
        finally:
            release.set()
        responses = [future.result(timeout=20) for future in futures]
    assert blocked_before_provider_return, (
        "GEGENBELEG: paralleler identischer Auftrag wird nicht vor Provider-Rueckkehr blockiert; "
        f"HTTP={[response.status_code for response in responses]}, "
        f"Preise={len(case.store.list_price_points())}, Provideraufrufe={case.calls}"
    )
    assert sum(response.status_code == 200 for response in responses) == 1
    assert all(response.status_code in (200, 409, 503) for response in responses)
    for response in responses:
        if response.status_code == 503:
            assert response.json()["data"]["storage_status"] == "not_started"
    assert len(case.store.list_price_points()) == 2 and case.pipeline_calls == ["pipeline"]
    assert len(case.calls) == (3 if kind == "current_portfolio" else 2)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("signal_type", [RequestCancelled, RequestDeadlineExceeded])
@pytest.mark.parametrize("phase", ["provider", "pipeline"])
def test_api_cancellation_distinguishes_before_prepare_from_checkpointed_pipeline(
    case, kind, signal_type, phase, monkeypatch, caplog,
):
    payload = case.payload(kind)
    def interrupt(*args, **kwargs):
        raise signal_type(PRIVATE_ERROR)
    if phase == "provider":
        name = "_fetch_coingecko_simple_prices_eur" if kind == "current_portfolio" else "_fetch_price_usd"
        monkeypatch.setattr(ExternalPriceBackfillService, name, interrupt)
    else:
        monkeypatch.setattr(PipelineService, "rebuild_all", interrupt)
    client = TestClient(create_app(case.store), raise_server_exceptions=False)
    response = client.post(URLS[kind], json=payload)
    ids = {price.price_id for price in case.store.list_price_points()}
    assert_private(response, caplog, case)
    assert response.status_code == 503, (
        f"GEGENBELEG: {kind}/{phase}/{signal_type.__name__}: HTTP {response.status_code}, "
        f"dauerhafte Preis-IDs={sorted(ids)}, Antwort={response.text}"
    )
    data = response.json()["data"]
    if phase == "provider":
        assert not ids and not case.pipeline_calls
        assert data["storage_status"] == data["pipeline_status"] == "not_started"
        assert not data.get("stored_price_ids")
    else:
        assert len(ids) == 2
        assert data["storage_status"] == "checkpointed"
        assert data["pipeline_status"] == "unknown_or_partial"
        assert set(data["stored_price_ids"]) == ids
    before, calls = snapshot(case.store), case.calls[:]
    read = status(TestClient(create_app(DuckDbStore(case.store.path))), kind, payload["request_id"])
    body = read.json()["data"]
    if phase == "provider":
        assert body["status"] == "unknown_or_running" and body.get("checkpoint") is None
    else:
        assert body["status"] == "checkpointed" and body.get("result") is None
        assert_checkpoint(case.store, kind, request_hash(kind, payload["request_id"]), body, ids,
                          "running_or_interrupted")
    assert client.post(URLS[kind], json=payload).status_code == 409
    assert snapshot(case.store) == before and case.calls == calls
    assert_private(read, caplog, case)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("boundary", ["after_prepare", "pipeline_entry"])
def test_crash_after_price_commit_has_exact_ids_without_final_journal(case, kind, boundary, monkeypatch):
    payload = case.payload(kind)
    if boundary == "after_prepare":
        prepare = method(case.store, "prepare_price_backfill")
        def crash_after_commit(*args, **kwargs):
            prepare(*args, **kwargs)
            raise SimulatedProcessCrash()
        monkeypatch.setattr(case.store, "prepare_price_backfill", crash_after_commit)
    else:
        def crash_at_pipeline_entry(self):
            raise SimulatedProcessCrash()
        monkeypatch.setattr(PipelineService, "rebuild_all", crash_at_pipeline_entry)
    with pytest.raises(SimulatedProcessCrash):
        domain_apply(case, kind, payload)
    ids = {price.price_id for price in case.store.list_price_points()}
    assert len(ids) == 2, "Crashprobe muss einen tatsaechlichen dauerhaften Preis-Commit erreichen"
    before, calls = snapshot(case.store), case.calls[:]
    recovered = DuckDbStore(case.store.path)
    client = TestClient(create_app(recovered))
    body = status(client, kind, payload["request_id"]).json()["data"]
    assert body["status"] == "checkpointed", (
        f"GEGENBELEG: Preise {sorted(ids)} existieren nach Crash, lesender Status bleibt {body}"
    )
    assert body.get("result") is None
    assert_checkpoint(recovered, kind, request_hash(kind, payload["request_id"]), body, ids,
                      "not_started" if boundary == "after_prepare" else "running_or_interrupted")
    assert client.post(URLS[kind], json=payload).status_code == 409
    assert snapshot(recovered) == before and case.calls == calls and not case.pipeline_calls


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("write_first", [False, True])
def test_final_journal_failure_still_has_readable_checkpoint_without_reexecution(
    case, kind, write_first, monkeypatch, caplog,
):
    original = record_method(case.store, kind)
    def fail(key, raw):
        if write_first:
            original(key, raw)
        raise RuntimeError(PRIVATE_ERROR)
    monkeypatch.setattr(case.store, original.__name__, fail)
    client = TestClient(create_app(case.store))
    payload = case.payload(kind)
    response = client.post(URLS[kind], json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result_journal_status"] == "unknown"
    ids = {price.price_id for price in case.store.list_price_points()}
    assert len(ids) == 2
    before, calls, pipelines = snapshot(case.store), case.calls[:], case.pipeline_calls[:]
    recovered = DuckDbStore(case.store.path)
    read = status(TestClient(create_app(recovered)), kind, payload["request_id"])
    body = read.json()["data"]
    assert body["status"] == ("recorded" if write_first else "checkpointed"), (
        f"GEGENBELEG: bekannte Preis-IDs {sorted(ids)} nach Journalfehler nicht lesbar: {body}"
    )
    assert_checkpoint(recovered, kind, request_hash(kind, payload["request_id"]), body, ids,
                      "completed" if write_first else "running_or_interrupted")
    assert client.post(URLS[kind], json=payload).status_code == 409
    assert snapshot(recovered) == before and case.calls == calls and case.pipeline_calls == pipelines
    assert_private(response, caplog, case)
    assert_private(read, caplog, case)


@pytest.mark.parametrize("kind", KINDS)
def test_dry_run_does_not_reserve_store_or_call_provider_and_same_id_can_apply(case, kind):
    client = TestClient(create_app(case.store))
    payload = case.payload(kind)
    before = snapshot(case.store)
    response = client.post(URLS[kind], json={**payload, "dry_run": True})
    assert response.status_code == 200
    assert snapshot(case.store) == before and not case.calls and not case.pipeline_calls
    assert status(client, kind, payload["request_id"]).json()["data"]["status"] == "not_found"
    assert client.post(URLS[kind], json=payload).status_code == 200
    assert len(case.store.list_price_points()) == 2


@pytest.mark.parametrize("kind", KINDS)
def test_partial_pipeline_effects_are_not_claimed_atomic_or_completed(case, kind, monkeypatch, caplog):
    def partial_pipeline(self):
        case.pipeline_calls.append("partial-pipeline")
        with self.store.connect() as con:
            con.execute("create table acceptance_pipeline_effect (marker varchar)")
            con.execute("insert into acceptance_pipeline_effect values ('synthetic-partial')")
        raise RuntimeError(PRIVATE_ERROR)
    monkeypatch.setattr(PipelineService, "rebuild_all", partial_pipeline)
    payload = case.payload(kind)
    client = TestClient(create_app(case.store))
    response = client.post(URLS[kind], json=payload)
    assert response.status_code == 200 and response.json()["status"] == "warning"
    result = response.json()["data"]
    ids = {price.price_id for price in case.store.list_price_points()}
    assert len(ids) == 2 and set(result["stored_price_ids"]) == ids
    assert result["pipeline_status"] == "failed" and result["pipeline_effects"] == "unknown_or_partial"
    with case.store.connect() as con:
        assert con.execute("select marker from acceptance_pipeline_effect").fetchall() == [("synthetic-partial",)]
    before, calls = snapshot(case.store), case.calls[:]
    read = status(client, kind, payload["request_id"])
    body = read.json()["data"]
    assert body["status"] == "recorded" and body["result"] == result
    assert_checkpoint(case.store, kind, request_hash(kind, payload["request_id"]), body, ids, "failed")
    assert client.post(URLS[kind], json=payload).status_code == 409
    assert snapshot(case.store) == before and case.calls == calls and case.pipeline_calls == ["partial-pipeline"]
    assert_private(response, caplog, case)
    assert_private(read, caplog, case)


@pytest.mark.parametrize("kind", KINDS)
def test_empty_apply_has_empty_checkpoint_and_never_starts_pipeline(case, kind):
    client = TestClient(create_app(case.store))
    payload = {**case.payload(kind), "max_requests": 0}
    response = client.post(URLS[kind], json=payload)
    assert response.status_code == 200
    assert not case.calls and not case.pipeline_calls and not case.store.list_price_points()
    assert response.json()["data"]["pipeline_status"] == "not_started"
    read = status(client, kind, payload["request_id"]).json()["data"]
    assert_checkpoint(case.store, kind, request_hash(kind, payload["request_id"]), read, [], "not_started")


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_without_explicit_id_still_blocks_identical_apply(case, kind):
    payload = case.payload(kind)
    payload.pop("request_id")
    client = TestClient(create_app(case.store))
    assert client.post(URLS[kind], json=payload).status_code == 200
    before, calls, pipelines = snapshot(case.store), case.calls[:], case.pipeline_calls[:]
    assert client.post(URLS[kind], json=payload).status_code == 409
    assert snapshot(case.store) == before and case.calls == calls and case.pipeline_calls == pipelines


def test_same_uuid_has_separate_current_and_historical_namespaces(case):
    request_id = str(uuid4())
    client = TestClient(create_app(case.store))
    for kind in KINDS:
        assert client.post(URLS[kind], json=case.payload(kind, request_id)).status_code == 200
    assert len(case.store.list_price_points()) == 4
    with case.store.connect() as con:
        keys = {row[0] for row in con.execute("select request_hash from current_price_backfill_requests").fetchall()}
    assert keys == {request_hash(kind, request_id) for kind in KINDS}, (
        "GEGENBELEG: Current/Historical-Auftraege sind nicht getrennt dauerhaft reserviert"
    )
    assert len(case.pipeline_calls) == 2
    for kind in KINDS:
        read = status(client, kind, request_id).json()["data"]
        assert read["status"] == "recorded" and read["checkpoint"]["operation_kind"] == kind


@pytest.mark.parametrize("kind", KINDS)
def test_prepare_atomicity_on_real_insert_and_checkpoint_write_failures(case, kind):
    store = case.store
    prepare = method(store, "prepare_price_backfill")
    key = request_hash(kind, uuid4())
    reserve(store, kind, key)
    with store.connect() as con:
        con.execute("create unique index acceptance_unique_asset on price_ledger(asset)")
    before = snapshot(store)
    with pytest.raises(Exception):
        prepare(key, kind, prices(same_asset=True))
    assert snapshot(store) == before, "Preis-Insertfehler darf weder Teilpreise noch Checkpoint committen"
    seed = request_hash(kind, uuid4())
    reserve(store, kind, seed)
    prepare(seed, kind, [])
    # Echte DuckDB-Constraint: zweite nichtleere Checkpointzelle scheitert.
    with store.connect() as con:
        con.execute("create unique index acceptance_checkpoint_fail on current_price_backfill_requests "
                    "((case when checkpoint_json is not null then 1 else null end))")
    before = snapshot(store)
    with pytest.raises(Exception):
        prepare(key, kind, prices())
    assert snapshot(store) == before, "Checkpoint-Writefehler muss auch bereits eingefuegte Preise zurueckrollen"


class CommitFaultConnection:
    """Fehler an der Transaktionsgrenze, unabhaengig vom Preis-Insertverfahren."""
    def __init__(self, real, after_commit, events):
        self.real, self.after_commit, self.events = real, after_commit, events

    def __enter__(self):
        self.real.__enter__()
        return self

    def __exit__(self, *args):
        return self.real.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.real, name)

    def _commit(self, action):
        self.events.append("commit")
        if self.after_commit:
            action()
        raise OSError(PRIVATE_ERROR)

    def execute(self, sql, *args, **kwargs):
        if sql.strip().split()[0].upper().rstrip(";") == "COMMIT":
            return self._commit(lambda: self.real.execute(sql, *args, **kwargs))
        result = self.real.execute(sql, *args, **kwargs)
        return self if result is self.real else result

    def commit(self):
        return self._commit(self.real.commit)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("after_commit", [False, True])
def test_prepare_commit_ack_loss_is_resolved_by_reading_not_by_retry(case, kind, after_commit, monkeypatch):
    store = case.store
    prepare = method(store, "prepare_price_backfill")
    request_id = str(uuid4())
    key = request_hash(kind, request_id)
    reserve(store, kind, key)
    before, events = snapshot(store), []
    connect = store.connect
    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", lambda: CommitFaultConnection(connect(), after_commit, events))
        with pytest.raises(Exception):
            prepare(key, kind, prices())
    assert events, "Fehlereinwurf muss die echte Prepare-Commitgrenze erreichen"
    recovered = DuckDbStore(store.path)
    ids = {price.price_id for price in recovered.list_price_points()}
    body = status(TestClient(create_app(recovered)), kind, request_id).json()["data"]
    if after_commit:
        assert len(ids) == 2 and body["status"] == "checkpointed"
        assert_checkpoint(recovered, kind, key, body, ids, "not_started")
    else:
        assert snapshot(recovered) == before and not ids
        assert body["status"] == "unknown_or_running" and body.get("checkpoint") is None
    assert not case.calls and not case.pipeline_calls


@pytest.mark.parametrize("kind,count,allowed", [
    ("current_portfolio", 250, True), ("current_portfolio", 251, False),
    ("historical", 251, True), ("historical", 1001, False),
])
def test_prepare_preserves_kind_specific_batch_capacity(case, kind, count, allowed):
    store = case.store
    prepare = method(store, "prepare_price_backfill")
    key = request_hash(kind, uuid4())
    reserve(store, kind, key)
    if not allowed:
        before = snapshot(store)
        with pytest.raises(Exception):
            prepare(key, kind, prices(count))
        assert snapshot(store) == before
        return
    written = prepare(key, kind, prices(count))
    ids = {price.price_id for price in store.list_price_points(limit=None)}
    assert len(written) == len(ids) == count
    raw = method(store, "price_backfill_operation_record")(key, kind)[1]
    checkpoint = json.loads(raw)
    assert set(checkpoint["stored_price_ids"]) == ids and checkpoint["operation_kind"] == kind


@pytest.mark.parametrize("kind", KINDS)
def test_prepare_requires_matching_open_reservation_and_never_overwrites_checkpoint(case, kind):
    store = case.store
    prepare = method(store, "prepare_price_backfill")
    key = request_hash(kind, uuid4())
    before = snapshot(store)
    with pytest.raises(Exception):
        prepare(key, kind, prices())
    assert snapshot(store) == before
    reserve(store, kind, key)
    before = snapshot(store)
    other = "historical" if kind == "current_portfolio" else "current_portfolio"
    with pytest.raises(Exception):
        prepare(key, other, prices())
    assert snapshot(store) == before
    prepare(key, kind, prices())
    before = snapshot(store)
    with pytest.raises(Exception):
        prepare(key, kind, prices())
    assert snapshot(store) == before
    mark = method(store, "mark_price_backfill_pipeline_started")
    mark(key, kind)
    before = snapshot(store)
    with pytest.raises(Exception):
        mark(key, kind)
    assert snapshot(store) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("forgery", ["price_ids", "pipeline_phase", "operation_kind"])
def test_final_record_cannot_rebind_ids_phase_or_operation_kind(case, kind, forgery, monkeypatch):
    original = record_method(case.store, kind)
    captured = []
    def stop_before_final_record(key, raw):
        captured.append((key, raw))
        raise RuntimeError(PRIVATE_ERROR)
    payload = case.payload(kind)
    with monkeypatch.context() as patch:
        patch.setattr(case.store, original.__name__, stop_before_final_record)
        response = TestClient(create_app(case.store)).post(URLS[kind], json=payload)
    assert response.status_code == 200 and response.json()["data"]["result_journal_status"] == "unknown"
    assert len(captured) == 1
    key, raw = captured[0]
    forged = json.loads(raw)
    record = original
    if forgery == "price_ids":
        forged["stored_price_ids"] = [str(uuid4())]
    elif forgery == "pipeline_phase":
        forged.update(pipeline_status="not_started", pipeline_effects="not_started", pipeline=None)
    else:
        other = "historical" if kind == "current_portfolio" else "current_portfolio"
        record = record_method(case.store, other)
    before = snapshot(case.store)
    with pytest.raises(Exception):
        record(key, json.dumps(forged))
    assert snapshot(case.store) == before, "Abgewiesenes Finaljournal darf keinen Beleg umschreiben"
    original(key, raw)
    finalized = snapshot(case.store)
    body = status(TestClient(create_app(case.store)), kind, payload["request_id"]).json()["data"]
    assert body["status"] == "recorded"
    assert_checkpoint(case.store, kind, key, body, set(json.loads(raw)["stored_price_ids"]), "completed")
    assert snapshot(case.store) == finalized


@pytest.mark.parametrize("kind", KINDS)
def test_offline_restore_preserves_checkpoint_bytes_ids_and_replay_guard(case, kind, tmp_path, monkeypatch):
    record = record_method(case.store, kind)
    def fail(*args):
        raise RuntimeError(PRIVATE_ERROR)
    monkeypatch.setattr(case.store, record.__name__, fail)
    payload = case.payload(kind)
    response = TestClient(create_app(case.store)).post(URLS[kind], json=payload)
    assert response.status_code == 200
    ids = {price.price_id for price in case.store.list_price_points()}
    before, calls, pipelines = snapshot(case.store), case.calls[:], case.pipeline_calls[:]
    backup, restored = tmp_path / "offline-backup.duckdb", tmp_path / "offline-restored.duckdb"
    proof = clone_offline_database(case.store.path, backup)
    clone_offline_database(backup, restored, expected_sha256=proof.target_sha256)
    recovered = DuckDbStore(restored)
    assert snapshot(recovered) == before
    client = TestClient(create_app(recovered))
    read = status(client, kind, payload["request_id"]).json()["data"]
    assert read["status"] == "checkpointed", "Restore muss bekannte Preisbelege statt nur unknown erhalten"
    assert_checkpoint(recovered, kind, request_hash(kind, payload["request_id"]), read, ids,
                      "running_or_interrupted")
    assert client.post(URLS[kind], json=payload).status_code == 409
    assert snapshot(recovered) == before and snapshot(case.store) == before
    assert case.calls == calls and case.pipeline_calls == pipelines


def test_old_journal_bytes_and_reservations_remain_readable_without_invented_checkpoint(case):
    payload = case.payload("current_portfolio")
    first = TestClient(create_app(case.store)).post(URLS["current_portfolio"], json=payload)
    assert first.status_code == 200
    raw = json.dumps(first.json()["data"], indent=3, ensure_ascii=True)
    old_id = str(uuid4())
    entries = [(request_hash("current_portfolio", payload["request_id"]), raw),
               (request_hash("current_portfolio", old_id), None)]
    with case.store.connect() as con:
        con.execute("drop table current_price_backfill_requests")
        con.execute("create table current_price_backfill_requests (request_hash varchar primary key, "
                    "reserved_at timestamp not null, result_json varchar)")
        for key, result in entries:
            con.execute("insert into current_price_backfill_requests values (?, current_timestamp, ?)", [key, result])
        legacy = con.execute("select request_hash, reserved_at, result_json from current_price_backfill_requests "
                             "order by request_hash").fetchall()
    recovered = DuckDbStore(case.store.path)
    client = TestClient(create_app(recovered))
    for request_id, expected in ((payload["request_id"], "recorded"), (old_id, "unknown_or_running")):
        read = status(client, "current_portfolio", request_id).json()["data"]
        assert read["status"] == expected and read.get("checkpoint") is None
        assert read.get("checkpoint_sha256") is None
        assert client.post(URLS["current_portfolio"], json={**payload, "request_id": request_id}).status_code == 409
    with recovered.connect() as con:
        assert con.execute("select request_hash, reserved_at, result_json from current_price_backfill_requests "
                           "order by request_hash").fetchall() == legacy
        columns = {row[1] for row in con.execute("pragma table_info('current_price_backfill_requests')").fetchall()}
    for key, original_result in entries:
        assert recovered.current_price_backfill_record(key) == (original_result,)
    assert columns >= {"operation_kind", "checkpoint_json"}, "VERTRAGSLUECKE: additive Checkpointspalten fehlen"


@pytest.mark.parametrize("kind", KINDS)
def test_checkpoint_ids_remain_historical_proof_after_explicit_price_deletion(case, kind):
    payload = case.payload(kind)
    client = TestClient(create_app(case.store))
    first = client.post(URLS[kind], json=payload)
    assert first.status_code == 200
    ids = set(first.json()["data"]["stored_price_ids"])
    assert len(ids) == 2
    case.store.delete_price_point(next(iter(ids)))
    before = snapshot(case.store)
    read = status(client, kind, payload["request_id"]).json()["data"]
    assert_checkpoint(case.store, kind, request_hash(kind, payload["request_id"]), read, ids, "completed")
    assert set(read["result"]["stored_price_ids"]) == ids
    assert len(case.store.list_price_points()) == 1 and snapshot(case.store) == before


@pytest.mark.parametrize("kind", KINDS)
def test_status_openapi_is_read_only_and_has_no_request_id_url_parameter(case, kind):
    path = URLS[kind] + "/status"
    paths = create_app(case.store).openapi()["paths"]
    assert path in paths, f"VERTRAGSLUECKE: {kind}-Statusroute fehlt im API-Vertrag"
    operation = paths[path]["post"]
    assert operation["x-data-effect"] == "read-only"
    assert not any(parameter["in"] in {"path", "query"} and parameter["name"] == "request_id"
                   for parameter in operation.get("parameters", []))
