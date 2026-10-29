"""Isolierte Regressionen aus der unabhaengigen Historienimport-Pruefung."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from steuerreport_v2.db.duckdb_store import DuckDbStore
import steuerreport_v2.domain.history as history_module
from steuerreport_v2.domain.history import HistoryService, _Signal
from steuerreport_v2.domain.history_preview import HistoryPreview
from steuerreport_v2.domain.history_storage import HistoryStorage
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryRecord, HistoryTarget
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestLimiter
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.workspace import source_ref
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


@pytest.fixture
def history_store(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "registry_version": "test", "entries": [],
        "ledger_adjustments": [], "transfer_evidence": [],
    }))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")
    monkeypatch.setattr(PortfolioService, "SOURCE_REGISTRY_CONFIG_PATH", registry)
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_CONFIG_PATH", registry)
    return DuckDbStore(tmp_path / "synthetic.duckdb")


@pytest.mark.parametrize("prior_scope,blocked", [
    ("selected_connection", True),
    ("ambiguous_legacy", True),
    ("unassigned_legacy", True),
    ("inclusive_start", True),
    ("inclusive_end", True),
    ("different_connection", False),
    ("outside_window", False),
    ("after_end", False),
])
def test_csv_overlap_requires_review_for_selected_account_only(history_store, prior_scope, blocked):
    store = history_store
    connection_id = str(uuid4())
    account = "connection:" + connection_id
    target = HistoryTarget(
        source_ref(account), "Synthetic Binance", "binance", account,
        connection_id=connection_id,
    )
    row = {
        "utc time": "2025-01-01T12:00:00Z", "coin": "BTC", "change": "1",
        "operation": "buy", "quote_asset": "EUR", "quote_quantity": "100",
        "account": account, "id": "synthetic-fill-42",
    }
    prior = dict(row)
    if prior_scope == "ambiguous_legacy":
        prior["account"] = "binance"
    elif prior_scope == "unassigned_legacy":
        prior.pop("account")
    elif prior_scope == "inclusive_start":
        prior["utc time"] = "2025-01-01T00:00:00Z"
    elif prior_scope == "inclusive_end":
        prior["utc time"] = "2025-01-02T23:59:59.999000Z"
    elif prior_scope == "different_connection":
        prior["account"] = "connection:" + str(uuid4())
    elif prior_scope == "outside_window":
        prior["utc time"] = "2024-12-31T12:00:00Z"
    elif prior_scope == "after_end":
        prior["utc time"] = "2025-01-03T00:00:00Z"
    batch = CsvRawImporter(store).import_rows(
        "binance", "synthetic-existing.csv", "sha256:synthetic-existing-csv", [prior],
    )
    assert len(RawNormalizer(store).normalize_batch(batch.batch_id)) == 1
    before = store.list_canonical_events()
    record = HistoryRecord(
        "cex:synthetic-fill-42", "binance", [row],
        {"payload": {"id": "synthetic-fill-42", "qty": "1"}},
    )
    storage = HistoryStorage(store)
    job_id = str(uuid4())
    job = {
        "id": job_id,
        "_options": {"start": "2025-01-01T00:00:00+00:00", "end": "2025-01-02T23:59:59.999000+00:00"},
        "_records": {record.identity: storage.write_record(job_id, record)},
    }
    if blocked:
        with pytest.raises(HistoryFetchError, match="history_legacy_account_assignment_required"):
            HistoryPreview(store).prepare(job, target)
    else:
        preview = HistoryPreview(store).prepare(job, target)
        assert preview["new_records"] == 1
    assert store.list_canonical_events() == before


def test_connection_bound_accountless_binance_csv_still_hits_legacy_api_overlap_guard(history_store):
    store = history_store
    connection_id = str(uuid4())
    account = "connection:" + connection_id
    content = (
        "utc time,coin,change,operation,quote_asset,quote_quantity,id\n"
        "2025-01-01T12:00:00Z,BTC,1,buy,EUR,100,synthetic-fill-42\n"
    )
    batch = CsvRawImporter(store).import_text(
        "binance", "synthetic-spot.csv", content, connection_id=connection_id,
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    assert len(events) == 1
    assert events[0].account == account
    assert str(batch.connection_id) == connection_id

    target = HistoryTarget(
        source_ref(account), "Synthetic Binance", "binance", account,
        connection_id=connection_id,
    )
    record = HistoryRecord(
        "cex:synthetic-fill-42", "binance", [{
            "utc time": "2025-01-01T12:00:00Z", "coin": "BTC", "change": "1",
            "operation": "buy", "quote_asset": "EUR", "quote_quantity": "100",
            "account": account, "id": "synthetic-fill-42",
        }],
        {"payload": {"id": "synthetic-fill-42", "qty": "1"}},
    )
    storage = HistoryStorage(store)
    job_id = str(uuid4())
    job = {
        "id": job_id,
        "_options": {
            "start": "2025-01-01T00:00:00+00:00",
            "end": "2025-01-02T23:59:59.999000+00:00",
        },
        "_records": {record.identity: storage.write_record(job_id, record)},
    }
    with pytest.raises(HistoryFetchError, match="history_legacy_account_assignment_required"):
        HistoryPreview(store).prepare(job, target)


@pytest.mark.parametrize("cancellation", ["control_expired_worker", "terminal_checkpoint"])
def test_expired_worker_cannot_restart_after_cancellation(history_store, monkeypatch, cancellation):
    service = HistoryService(history_store)
    job_id, run_id = str(uuid4()), str(uuid4())
    target = HistoryTarget("synthetic-source", "Synthetic wallet", "solana", "synthetic-wallet")
    timestamp = datetime.now(timezone.utc).isoformat()
    job = {
        "id": job_id, "source_ref": target.source_ref, "label": target.label,
        "provider": target.provider, "status": "queued", "phase": "Synthetic worker",
        "created_at": timestamp, "updated_at": timestamp,
        "start": "2025-01-01", "end": "2025-01-02", "max_records": 100,
        "records_fetched": 0, "pages_fetched": 1, "requests": 1, "coverage_notes": [],
        "_target": asdict(target), "_binding": "synthetic-binding",
        "_options": {
            "start": "2025-01-01T00:00:00+00:00", "end": "2025-01-03T00:00:00+00:00",
            "symbols": [], "public_rpc_only": True,
        },
        "_records": {}, "_cursor": {"page": 1}, "_pid": os.getpid(),
        "_run_id": run_id, "_until": "2000-01-01T00:00:00+00:00",
    }
    service.storage.save(job)
    launches, controls = [], []
    monkeypatch.setattr(service, "_launch", launches.append)
    monkeypatch.setattr(service, "_target", lambda _ref: target)
    monkeypatch.setattr(service, "_binding", lambda _target: "synthetic-binding")

    class Collector:
        def fetch_page(self, cursor, check):
            assert cursor == {"page": 1}
            if cancellation == "control_expired_worker":
                controls.append(service.control(target.source_ref, job_id, "cancel"))
            else:
                # A terminal durable checkpoint must also survive an old worker.
                current = service.storage.load(job_id)
                current["status"] = "cancelled"
                service.storage.save(current)
            raise HistoryFetchError("history_run_deadline")

    monkeypatch.setattr(service, "_collector", lambda *_args: Collector())
    service._run(job_id)
    stopped = service.storage.load(job_id)
    assert launches == [], "A cancelled job must not launch another provider chunk"
    assert stopped["status"] == "cancelled"
    assert stopped["_run_id"] == run_id
    assert stopped["_cursor"] == {"page": 1}
    if cancellation == "control_expired_worker":
        assert len(controls) == 1
        assert stopped.get("_cancel_requested") is True
        assert HistoryService(history_store).get(target.source_ref, job_id).status == "cancelled"
    assert not history_store.list_canonical_events()


@dataclass
class Clock:
    elapsed: float = 100.0

    def wall(self):
        return 1_700_000_000.0 + self.elapsed

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


def limiter_signal(limiter, clock, monkeypatch):
    monkeypatch.setattr(history_module, "time", SimpleNamespace(monotonic=clock.monotonic))
    state = {"_run_id": "synthetic-run", "_cancel_requested": False}
    polls, locked_reads = [], []

    def load(_job_id):
        polls.append(clock.elapsed)
        # Probe the real flock without blocking or acquiring any database lock.
        with (limiter.directory / "coordinator.lock").open("rb") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                locked_reads.append(clock.elapsed)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return deepcopy(state)

    signal = _Signal(
        SimpleNamespace(storage=SimpleNamespace(load=load)),
        "synthetic-job", "synthetic-run", clock.monotonic() + 240,
    )
    signal.check()
    return signal, state, polls, locked_reads


def test_limiter_slot_wait_observes_durable_history_cancellation(tmp_path, monkeypatch):
    clock = Clock()
    limiter = RequestLimiter(
        state_root=tmp_path / "limiter", clock=clock.wall, monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    signal, state, polls, locked_reads = limiter_signal(limiter, clock, monkeypatch)

    def cancel_during_wait(_seconds):
        state["_cancel_requested"] = True
        # Advance only synthetic time: bound the unfixed reproduction to eight polls.
        clock.elapsed += 30

    monkeypatch.setattr(limiter, "_sleep", cancel_during_wait)
    with limiter.acquire("binance"):
        with pytest.raises(RequestCancelled):
            lease = limiter.acquire("binance", cancel=signal, deadline=signal.deadline)
            lease.release()
    assert clock.elapsed == 130.0
    assert len(polls) >= 2
    assert signal.reason == "history_cancelled"
    assert locked_reads == [], "Durable cancellation polling must never read DB state under coordinator flock"
    assert all(group.queued == 0 for group in limiter.status().groups)


def test_limiter_acquire_and_dispatch_refresh_only_outside_coordinator_lock(tmp_path, monkeypatch):
    clock = Clock()
    limiter = RequestLimiter(
        state_root=tmp_path / "limiter", clock=clock.wall, monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    signal, _state, polls, locked_reads = limiter_signal(limiter, clock, monkeypatch)
    original_load = limiter._load

    def slow_load(directory_fd, lock_fd):
        document = original_load(directory_fd, lock_fd)
        # Cross the signal refresh interval while the coordinator lock is held.
        clock.elapsed += 0.25
        return document

    monkeypatch.setattr(limiter, "_load", slow_load)
    with limiter.acquire("binance", cancel=signal, deadline=signal.deadline) as lease:
        lease.start()
    assert locked_reads == [], "Event checks under flock must not refresh durable state"
    assert len(polls) >= 2, "Acquire/dispatch must refresh cancellation outside flock"


@pytest.mark.parametrize("phase", ["acquire", "dispatch"])
def test_limiter_flock_wait_observes_history_cancellation(tmp_path, monkeypatch, phase):
    clock = Clock()
    limiter = RequestLimiter(
        state_root=tmp_path / "limiter", clock=clock.wall, monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    monkeypatch.setattr(history_module, "time", SimpleNamespace(monotonic=clock.monotonic))
    state = {"_run_id": "synthetic-run", "_cancel_requested": False}
    polls = []

    def load(_job_id):
        polls.append(clock.elapsed)
        return deepcopy(state)

    signal = _Signal(
        SimpleNamespace(storage=SimpleNamespace(load=load)),
        "synthetic-job", "synthetic-run", clock.monotonic() + 240,
    )
    signal.check()
    lease = limiter.acquire("binance", cancel=signal) if phase == "dispatch" else None

    def cancel_during_lock_wait(_seconds):
        state["_cancel_requested"] = True
        clock.elapsed += 0.25

    monkeypatch.setattr(limiter, "_sleep", cancel_during_lock_wait)
    try:
        with (limiter.directory / "coordinator.lock").open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with pytest.raises(RequestCancelled):
                    if lease is not None:
                        lease.start()
                    else:
                        unexpected = limiter.acquire("binance", cancel=signal)
                        unexpected.release()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        # Release only after the competing flock: cleanup itself needs that lock.
        if lease is not None:
            lease.release()
    assert clock.elapsed == 100.25
    assert len(polls) >= 2
    assert signal.reason == "history_cancelled"
