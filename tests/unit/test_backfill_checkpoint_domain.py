"""Domain-Phasen mit synthetischem Vertragsstore; keine Provider-/Produktionszugriffe."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.contracts.prices import (
    CurrentPortfolioPriceBackfillResult, ExternalPriceBackfillRequest,
    ExternalPriceBackfillResult, ExternalPriceBackfillStatusRequest,
    PriceBackfillCheckpoint, PricePoint,
)
from steuerreport_v2.domain import external_price_backfill as domain
from steuerreport_v2.domain.historical_fx import FxReference
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


CANARY = "SYNTHETIC_PRIVATE_ERROR /private/receipt?token=checkpoint-test"
NOW = datetime(2025, 6, 2, 12, tzinfo=UTC)
PIPELINE = PipelineResult(normalized_events=0, balance_entries=0, flow_entries=0,
                          tax_lines=0, review_issues_open=0, allow_export=False)


class ContractStore:
    """Nur Phasenverhalten emulieren; kein Ersatz fuer Store-Transaktionstests."""

    def __init__(self):
        self.rows = {}
        self.calls = []
        self.prices = []
        self.faults = {}
        self.lock = threading.RLock()
        self.snapshots = 0
        self.gate_active = False
        self.gate_thread = None

    @contextmanager
    def exclusive_access(self):
        with self.lock:
            assert not self.gate_active
            self.gate_active = True
            self.gate_thread = threading.get_ident()
            try:
                yield
            finally:
                self.gate_active = False
                self.gate_thread = None

    def fault(self, phase, point):
        planned = self.faults.get(phase)
        if planned and planned[0] == point:
            raise planned[1]

    def reserve(self, key, kind):
        with self.lock:
            self.calls.append(("reserve", kind))
            self.fault("reserve", "before")
            if (kind, key) in self.rows:
                return False
            self.rows[kind, key] = (None, None)
            self.fault("reserve", "after")
            return True

    def reserve_current_price_backfill(self, key):
        return self.reserve(key, "current_portfolio")

    def reserve_historical_price_backfill(self, key):
        return self.reserve(key, "historical")

    def prepare_price_backfill(self, key, kind, payloads):
        with self.lock:
            assert not self.gate_active
            self.calls.append(("prepare", kind))
            assert self.rows[kind, key] == (None, None)
            self.fault("prepare", "before")
            created = [PricePoint(price_id=str(uuid4()), **payload.model_dump()) for payload in payloads]
            checkpoint = PriceBackfillCheckpoint(
                operation_kind=kind, stored_at=NOW,
                stored_price_ids=[price.price_id for price in created], pipeline_status="not_started",
            )
            self.rows[kind, key] = (None, checkpoint.model_dump_json())
            self.prices.extend(created)
            self.fault("prepare", "after")
            return created

    def mark_price_backfill_pipeline_started(self, key, kind):
        assert self.gate_active
        self.calls.append(("marker", kind))
        self.fault("marker", "before")
        old_result, raw = self.rows[kind, key]
        checkpoint = PriceBackfillCheckpoint.model_validate_json(raw)
        assert old_result is None and checkpoint.pipeline_status == "not_started"
        assert checkpoint.stored_price_ids
        self.rows[kind, key] = (None, checkpoint.model_copy(
            update={"pipeline_status": "running_or_interrupted"},
        ).model_dump_json())
        self.fault("marker", "after")

    def record(self, key, kind, raw_result):
        self.calls.append(("record", kind))
        self.fault("record", "before")
        model = CurrentPortfolioPriceBackfillResult if kind == "current_portfolio" else ExternalPriceBackfillResult
        result = model.model_validate_json(raw_result)
        _, raw_checkpoint = self.rows[kind, key]
        checkpoint = PriceBackfillCheckpoint.model_validate_json(raw_checkpoint)
        assert checkpoint.stored_price_ids == result.stored_price_ids
        assert len(checkpoint.stored_price_ids) == result.imported_prices
        assert not result.stored_price_ids or checkpoint.pipeline_status == "running_or_interrupted"
        self.rows[kind, key] = (raw_result, checkpoint.model_copy(
            update={"pipeline_status": result.pipeline_status},
        ).model_dump_json())
        self.fault("record", "after")

    def record_current_price_backfill(self, key, raw):
        self.record(key, "current_portfolio", raw)

    def record_historical_price_backfill(self, key, raw):
        self.record(key, "historical", raw)

    @contextmanager
    def read_snapshot(self):
        with self.lock:
            self.snapshots += 1
            rows = dict(self.rows)
            yield SimpleNamespace(price_backfill_operation_record=lambda key, kind: rows.get((kind, key)))


@pytest.fixture
def setup(monkeypatch):
    store = ContractStore()
    service = domain.ExternalPriceBackfillService(store)
    identifier = str(uuid4())
    monkeypatch.setattr(service, "_load_assets", lambda _: [domain._PriceAsset("AAA", "synthetic-a", ("AAA",))])
    monkeypatch.setattr(service, "_token_risk_statuses", lambda: {})
    monkeypatch.setattr(domain, "managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(domain, "BalanceLedgerBuilder", lambda store: SimpleNamespace(
        positions=lambda: [SimpleNamespace(asset="AAA", quantity=Decimal("1"))],
    ))
    monkeypatch.setattr(domain, "PriceCoverageService", lambda store: SimpleNamespace(requirements=lambda: SimpleNamespace(
        requirements=[SimpleNamespace(asset="AAA", price_date=date(2025, 6, 1))],
    )))
    provider_calls = []
    def quote(*args, **kwargs):
        assert store.gate_thread != threading.get_ident()
        provider_calls.append("quote")
        return {"synthetic-a": Decimal("2")}
    monkeypatch.setattr(service, "_fetch_coingecko_simple_prices_eur", quote)
    def historical(**kwargs):
        assert store.gate_thread != threading.get_ident()
        provider_calls.append("quote")
        return Decimal("2"), "coingecko_history"
    monkeypatch.setattr(service, "_fetch_price_usd", historical)
    monkeypatch.setattr(service, "_timed_usd_eur_reference", lambda *args: FxReference(
        Decimal("0.9"), date(2025, 5, 31), "USD", "EUR", Decimal("0.9"), "synthetic",
    ))
    def pipeline(self):
        assert store.gate_active
        store.calls.append(("pipeline", "running"))
        active = [PriceBackfillCheckpoint.model_validate_json(row[1]) for row in store.rows.values() if row[1]]
        assert any(cp.pipeline_status == "running_or_interrupted" for cp in active)
        return PIPELINE
    monkeypatch.setattr(domain.PipelineService, "rebuild_all", pipeline)
    return service, store, identifier, provider_calls


def apply(setup, kind, **overrides):
    service, _, identifier, _ = setup
    arguments = dict(config_path="synthetic-config.json", provider="auto", assets_filter=[],
                     max_requests=25, timeout_seconds=20, confidence=Decimal("1"), dry_run=False,
                     request_id=identifier)
    arguments.update(overrides)
    if kind == "current_portfolio":
        return service.run_current_portfolio(**arguments)
    return service.run(v1_fx_db_path="synthetic-fx.db", **arguments)


def status(setup, kind):
    service, _, identifier, _ = setup
    method = service.current_portfolio_request_status if kind == "current_portfolio" else service.historical_request_status
    return method(identifier)


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_positive_apply_uses_prepare_marker_pipeline_and_final_journal(setup, kind):
    _, store, _, calls = setup
    result = apply(setup, kind)
    assert [call[0] for call in store.calls] == ["reserve", "prepare", "marker", "pipeline", "record"]
    assert calls == ["quote"]
    assert result.result_journal_status == "recorded"
    assert result.pipeline_status == "completed" and result.pipeline_effects == "completed"
    assert result.stored_price_ids == [price.price_id for price in store.prices]
    before = dict(store.rows)
    read = status(setup, kind)
    assert read.status == "recorded" and read.result == result
    assert read.checkpoint.pipeline_status == "completed"
    raw = next(iter(store.rows.values()))[1]
    assert read.checkpoint_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert store.snapshots == 1 and store.rows == before and calls == ["quote"]


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_empty_apply_still_has_checkpoint_without_pipeline(setup, kind):
    _, store, _, calls = setup
    result = apply(setup, kind, max_requests=0)
    assert [call[0] for call in store.calls] == ["reserve", "prepare", "record"]
    assert not calls and not store.prices
    assert result.stored_price_ids == [] and result.pipeline_status == "not_started"
    read = status(setup, kind)
    assert read.status == "recorded" and read.checkpoint.stored_price_ids == []


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_dry_run_never_reserves_prepares_marks_or_records(setup, kind):
    _, store, _, calls = setup
    result = apply(setup, kind, dry_run=True)
    assert not store.calls and not store.rows and not calls
    assert result.result_journal_status == "not_started"
    assert result.pipeline_status == "not_started" and result.pipeline is None
    apply(setup, kind)


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_duplicate_reservation_stops_before_provider_even_with_changed_parameters(setup, kind):
    error = domain.CurrentBackfillReplayBlocked if kind == "current_portfolio" else domain.HistoricalBackfillReplayBlocked
    apply(setup, kind)
    with pytest.raises(error):
        apply(setup, kind, assets_filter=["DIFFERENT"])
    assert setup[3] == ["quote"]


def test_two_concurrent_historical_reservations_only_fetch_once(setup):
    def call(_):
        try:
            apply(setup, "historical")
            return "done"
        except domain.HistoricalBackfillReplayBlocked:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(call, range(2))) == ["blocked", "done"]
    assert setup[3] == ["quote"]


def test_same_store_current_and_historical_pipelines_do_not_interleave(setup, monkeypatch):
    _, store, _, calls = setup
    active = []
    events = []
    def pipeline(self):
        assert store.gate_active and not active
        active.append(True)
        events.append("start")
        time.sleep(0.02)
        events.append("end")
        active.pop()
        return PIPELINE
    monkeypatch.setattr(domain.PipelineService, "rebuild_all", pipeline)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda kind: apply(setup, kind), ["current_portfolio", "historical"]))
    assert all(result.pipeline_status == "completed" for result in results)
    assert events == ["start", "end", "start", "end"] and len(calls) == 2


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("after", [False, True])
def test_prepare_error_has_no_safe_ids_and_checkpoint_survives_lost_ack(setup, kind, after, caplog):
    _, store, _, _ = setup
    store.faults["prepare"] = ("after" if after else "before", RuntimeError(CANARY))
    error = domain.CurrentBackfillStorageUnknown if kind == "current_portfolio" else domain.HistoricalBackfillStorageUnknown
    with pytest.raises(error) as caught:
        apply(setup, kind)
    assert CANARY not in str(caught.value) + caplog.text
    assert not hasattr(caught.value, "stored_price_ids")
    assert [call[0] for call in store.calls] == ["reserve", "prepare"]
    read = status(setup, kind)
    assert read.status == ("checkpointed" if after else "unknown_or_running")
    assert read.result is None
    if after:
        assert read.checkpoint.stored_price_ids == [price.price_id for price in store.prices]
        assert read.checkpoint.pipeline_status == "not_started"


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("after", [False, True])
def test_marker_failure_is_checkpointed_not_pre_storage(setup, kind, after, caplog):
    _, store, _, _ = setup
    store.faults["marker"] = ("after" if after else "before", RuntimeError(CANARY))
    error = domain.CurrentBackfillPipelineStartUnknown if kind == "current_portfolio" else domain.HistoricalBackfillPipelineStartUnknown
    with pytest.raises(error) as caught:
        apply(setup, kind)
    assert caught.value.stored_price_ids == [price.price_id for price in store.prices]
    assert CANARY not in str(caught.value) + caplog.text
    assert [call[0] for call in store.calls] == ["reserve", "prepare", "marker"]
    read = status(setup, kind)
    assert read.status == "checkpointed"
    assert read.checkpoint.pipeline_status == ("running_or_interrupted" if after else "not_started")


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("phase", ["marker", "pipeline", "record"])
@pytest.mark.parametrize("interrupt", [RequestCancelled, RequestDeadlineExceeded])
def test_request_interrupt_after_prepare_is_phase_specific(setup, monkeypatch, kind, phase, interrupt):
    _, store, _, _ = setup
    if phase == "pipeline":
        def fail(self):
            raise interrupt(CANARY)
        monkeypatch.setattr(domain.PipelineService, "rebuild_all", fail)
    else:
        store.faults[phase] = ("before", interrupt(CANARY))
    error = domain.CurrentBackfillPipelineInterrupted if kind == "current_portfolio" else domain.HistoricalBackfillPipelineInterrupted
    with pytest.raises(error) as caught:
        apply(setup, kind)
    assert caught.value.stored_price_ids == [price.price_id for price in store.prices]
    assert CANARY not in str(caught.value)
    assert status(setup, kind).status == "checkpointed"
    if kind == "historical":
        assert isinstance(caught.value, domain.HistoricalBackfillIncompleteError)


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("phase", ["prepare", "marker", "pipeline", "record"])
def test_base_exception_propagates_without_final_result(setup, monkeypatch, kind, interrupt, phase):
    if phase == "pipeline":
        def fail(self):
            raise interrupt()
        monkeypatch.setattr(domain.PipelineService, "rebuild_all", fail)
    else:
        setup[1].faults[phase] = ("before", interrupt())
    with pytest.raises(interrupt):
        apply(setup, kind)
    read = status(setup, kind)
    assert read.result is None
    assert read.status == ("unknown_or_running" if phase == "prepare" else "checkpointed")
    if read.checkpoint:
        assert read.checkpoint.pipeline_status == ("not_started" if phase == "marker" else "running_or_interrupted")


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("fault", [RuntimeError, RequestCancelled, RequestDeadlineExceeded])
def test_gate_entry_failure_after_prepare_is_never_pre_storage(setup, monkeypatch, kind, fault):
    _, store, _, _ = setup
    @contextmanager
    def failed_gate():
        raise fault(CANARY)
        yield
    monkeypatch.setattr(store, "exclusive_access", failed_gate)
    interrupted = domain.CurrentBackfillPipelineInterrupted if kind == "current_portfolio" else domain.HistoricalBackfillPipelineInterrupted
    unknown = domain.CurrentBackfillPipelineStartUnknown if kind == "current_portfolio" else domain.HistoricalBackfillPipelineStartUnknown
    with pytest.raises(unknown if fault is RuntimeError else interrupted) as caught:
        apply(setup, kind)
    assert caught.value.stored_price_ids == [price.price_id for price in store.prices]
    assert CANARY not in str(caught.value)
    assert status(setup, kind).checkpoint.pipeline_status == "not_started"


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_pipeline_failure_is_recorded_with_unknown_effects(setup, monkeypatch, kind, caplog):
    def fail(self):
        raise RuntimeError(CANARY)
    monkeypatch.setattr(domain.PipelineService, "rebuild_all", fail)
    result = apply(setup, kind)
    assert result.pipeline_status == "failed" and result.pipeline_effects == "unknown_or_partial"
    assert result.pipeline is None and result.result_journal_status == "recorded"
    assert status(setup, kind).checkpoint.pipeline_status == "failed"
    assert CANARY not in caplog.text


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("after", [False, True])
def test_final_journal_error_keeps_local_result_unknown_and_never_repeats(setup, kind, after, caplog):
    _, store, _, _ = setup
    store.faults["record"] = ("after" if after else "before", RuntimeError(CANARY))
    result = apply(setup, kind)
    assert result.result_journal_status == "unknown" and result.imported_prices == 1
    read = status(setup, kind)
    assert read.status == ("recorded" if after else "checkpointed")
    assert CANARY not in result.model_dump_json() + read.model_dump_json() + caplog.text
    error = domain.CurrentBackfillReplayBlocked if kind == "current_portfolio" else domain.HistoricalBackfillReplayBlocked
    with pytest.raises(error):
        apply(setup, kind)


def test_current_hash_bytes_unchanged_and_historical_namespace_is_separate(setup):
    service, store, identifier, _ = setup
    expected = hashlib.sha256(json.dumps({"request_id": identifier}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert service._explicit_current_request_hash(identifier) == expected
    historical = hashlib.sha256(json.dumps({"operation_kind": "historical", "request_id": identifier},
                                           sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert service._explicit_historical_request_hash(identifier) == historical != expected
    apply(setup, "current_portfolio")
    apply(setup, "historical")
    assert set(store.rows) == {("current_portfolio", expected), ("historical", historical)}


def test_historical_implicit_hash_uses_effective_normalized_parameters(setup):
    apply(setup, "historical", request_id=None, assets_filter=[" aaa ", "AAA"],
          provider="invalid-provider", timeout_seconds=1, max_requests=1001, confidence=Decimal("1.00"))
    with pytest.raises(domain.HistoricalBackfillReplayBlocked):
        apply(setup, "historical", request_id=None, assets_filter=["AAA"], provider="auto",
              timeout_seconds=3, max_requests=1000, confidence=Decimal("1"))


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_legacy_result_without_checkpoint_preserves_fields_and_warnings(setup, kind):
    apply(setup, kind)
    _, store, _, calls = setup
    key, = store.rows
    original, _ = store.rows[key]
    payload = json.loads(original)
    payload.pop("operation_kind")
    payload.pop("result_journal_status")
    legacy = json.dumps(payload)
    store.rows[key] = (legacy, None)
    before_warnings = domain.backfill_result_warnings(status(setup, kind).result)
    read = status(setup, kind)
    assert read.status == "recorded" and read.checkpoint is None and read.checkpoint_sha256 is None
    assert read.result.stored_price_ids == payload["stored_price_ids"]
    assert read.result.result_journal_status == "not_started"
    assert domain.backfill_result_warnings(read.result) == before_warnings
    assert store.rows[key] == (legacy, None) and calls == ["quote"]


@pytest.mark.parametrize("field,value", [
    ("stored_price_ids", [str(uuid4())]), ("imported_prices", 2),
    ("imported_prices", True), ("operation_kind", "other"),
    ("pipeline_status", "not_started"), ("pipeline_effects", "not_started"),
    ("dry_run", True), ("result_journal_status", "unknown"),
])
@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
def test_result_checkpoint_mismatch_is_sanitized_error(setup, kind, field, value, caplog):
    apply(setup, kind)
    _, store, _, _ = setup
    key, = store.rows
    raw, checkpoint = store.rows[key]
    payload = json.loads(raw)
    payload[field] = value
    payload["private_extra"] = CANARY
    store.rows[key] = (json.dumps(payload), checkpoint)
    error = domain.CurrentBackfillStatusUnknown if kind == "current_portfolio" else domain.HistoricalBackfillStatusUnknown
    with pytest.raises(error) as caught:
        status(setup, kind)
    assert CANARY not in str(caught.value) + caplog.text


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("raw", [CANARY, "[]", '{"format_version":1,"format_version":1}', '{"number":NaN}'])
def test_corrupt_checkpoint_never_becomes_positive_or_leaks_input(setup, kind, raw, caplog):
    apply(setup, kind)
    _, store, _, _ = setup
    key, = store.rows
    result, _ = store.rows[key]
    store.rows[key] = (result, raw)
    error = domain.CurrentBackfillStatusUnknown if kind == "current_portfolio" else domain.HistoricalBackfillStatusUnknown
    with pytest.raises(error) as caught:
        status(setup, kind)
    assert CANARY not in str(caught.value) + caplog.text


def test_status_drops_result_extras_but_checkpoint_extras_are_forbidden(setup):
    apply(setup, "historical")
    _, store, _, _ = setup
    key, = store.rows
    raw, checkpoint = store.rows[key]
    payload = json.loads(raw)
    payload["private_extra"] = CANARY
    store.rows[key] = (json.dumps(payload), checkpoint)
    assert CANARY not in status(setup, "historical").model_dump_json()
    payload = json.loads(checkpoint)
    payload["private_extra"] = CANARY
    store.rows[key] = (raw, json.dumps(payload))
    with pytest.raises(domain.HistoricalBackfillStatusUnknown):
        status(setup, "historical")


@pytest.mark.parametrize("patch", [
    {"format_version": True}, {"format_version": "1"},
    {"stored_at": "2025-06-02T12:00:00"}, {"stored_at": "2025-06-02T13:00:00+01:00"},
    {"stored_at": 1}, {"stored_price_ids": ["not-a-uuid"]},
    {"stored_price_ids": ["AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"]},
    {"stored_price_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"] * 2},
    {"extra": CANARY},
])
def test_checkpoint_rejects_noncanonical_or_untrusted_fields(patch):
    payload = dict(operation_kind="historical", stored_at=NOW, stored_price_ids=[], pipeline_status="not_started")
    payload.update(patch)
    with pytest.raises(ValidationError):
        PriceBackfillCheckpoint(**payload)


@pytest.mark.parametrize("kind,limit", [("current_portfolio", 250), ("historical", 1000)])
def test_checkpoint_limits_preserve_historical_extent(kind, limit):
    identifiers = [str(uuid4()) for _ in range(limit)]
    model = PriceBackfillCheckpoint(operation_kind=kind, stored_at=NOW,
                                    stored_price_ids=identifiers, pipeline_status="not_started")
    assert model.stored_price_ids == identifiers
    with pytest.raises(ValidationError):
        PriceBackfillCheckpoint(operation_kind=kind, stored_at=NOW,
                                stored_price_ids=[*identifiers, str(uuid4())], pipeline_status="not_started")


@pytest.mark.parametrize("journal", ["not_started", "recorded", "unknown"])
def test_legacy_caller_guard_blocks_only_unknown_journal(setup, journal):
    result = apply(setup, "historical")
    result.result_journal_status = journal
    if journal == "unknown":
        with pytest.raises(domain.HistoricalBackfillJournalUnknown) as caught:
            domain.require_backfill_pipeline_success(result)
        assert isinstance(caught.value, domain.HistoricalBackfillIncompleteError)
        assert caught.value.stored_price_ids == result.stored_price_ids
    else:
        domain.require_backfill_pipeline_success(result)


def test_existing_pipeline_and_job_guards_still_win(setup):
    result = apply(setup, "historical")
    result.result_journal_status = "unknown"
    result.pipeline_status = "failed"
    with pytest.raises(domain.HistoricalBackfillPipelineFailed):
        domain.require_backfill_pipeline_success(result)
    result.pipeline_status = "completed"
    result.failed = 1
    with pytest.raises(domain.HistoricalBackfillJobsFailed):
        domain.require_backfill_pipeline_success(result)


def test_historical_request_and_status_accept_uuid_model():
    identifier = uuid4()
    assert ExternalPriceBackfillRequest(request_id=identifier).request_id == identifier
    assert ExternalPriceBackfillStatusRequest(request_id=identifier).request_id == identifier
