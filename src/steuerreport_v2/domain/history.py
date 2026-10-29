"""Ausdruecklich gestartete, wiederaufnehmbare Historienjobs pro eigener Quelle."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, time as day_time, timedelta, timezone
import hashlib
import os
import threading
import time
from uuid import uuid4

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.history import (
    HistoryApprove, HistoryCapability, HistoryJob, HistoryResume, HistoryStart, HistoryView,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.external_http import outbound_scope
from steuerreport_v2.domain.history_preview import HistoryPreview, fingerprint
from steuerreport_v2.domain.history_storage import HistoryStorage, now
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryOptions, HistoryTarget
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded
from steuerreport_v2.domain.workspace import WorkspaceService
from steuerreport_v2.importers.solana_history_identity import SolanaHistoryConflict, exclusive_history_import
from steuerreport_v2.importers.source_history_importer import canonical_json, record_digest

RUN_SECONDS = 240
MAX_ACTIVE = 2
MAX_JOBS = 100
MAX_PROVIDER_REQUESTS = 10000
ACTIVE = {"queued", "running", "importing"}


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


class _Signal(threading.Event):
    def __init__(self, service, job_id, run_id, deadline):
        super().__init__()
        self.service, self.job_id, self.run_id, self.deadline = service, job_id, run_id, deadline
        self.reason = None
        self.checked_at = 0.0

    def refresh(self):
        if self.is_set():
            return True
        if time.monotonic() >= self.deadline:
            self.reason = "history_run_deadline"
        elif time.monotonic() - self.checked_at < 0.2:
            return False
        else:
            self.checked_at = time.monotonic()
            try:
                job = self.service.storage.load(self.job_id)
                self.reason = ("history_worker_superseded" if job.get("_run_id") != self.run_id
                               else "history_cancelled" if job.get("_cancel_requested")
                               else "history_paused" if job.get("_pause_requested") else None)
            except Exception:
                self.reason = "history_coordination_unavailable"
        if self.reason:
            self.set()
        return self.is_set()

    def check(self):
        if self.refresh():
            raise HistoryFetchError(self.reason or "history_paused")

    def wait(self, timeout=None):
        end = min(self.deadline, time.monotonic() + timeout) if timeout is not None else self.deadline
        while not self.refresh():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            super().wait(min(remaining, 0.1))
        return True


class HistoryService:
    def __init__(self, store: DuckDbStore):
        self.store = store
        self.storage = HistoryStorage(store)
        self.connections = ConnectionService(store)

    def _target(self, ref: str) -> HistoryTarget:
        try:
            source = WorkspaceService(self.store).scope(ref).item
        except LookupError:
            raise HistoryFetchError("history_source_not_found", resumable=False) from None
        if source.wallet_address:
            return HistoryTarget(ref, source.label, "solana", source.wallet_address, source.wallet_address)
        if source.connection_id:
            connection = next((c for c in self.connections.list().connections if str(c.id) == source.connection_id), None)
            if connection is None:
                raise HistoryFetchError("history_connection_required", resumable=False)
            return HistoryTarget(ref, source.label, connection.provider, "connection:" + str(connection.id),
                                 connection_id=str(connection.id), budget_groups=(connection.budget_group,))
        provider = source.connector_id
        if provider in {"binance", "bitget", "coinbase", "pionex"}:
            configured = [c for c in self.connections.list().connections if c.provider == provider]
            if configured:
                raise HistoryFetchError("history_select_individual_connection", resumable=False)
            return HistoryTarget(ref, source.label, provider, provider, legacy_credentials=True)
        raise HistoryFetchError("history_provider_not_supported", resumable=False)

    def _binding(self, target: HistoryTarget, *, software_version=None, include_binance_earn=False):
        keys = []
        if target.provider != "solana":
            if target.connection_id:
                self.connections.credentials(target.connection_id, target.provider)
                prefix = f"secret.cex.connection.{target.connection_id}."
            else:
                from steuerreport_v2.domain.cex_balances import CexBalanceService
                CexBalanceService(self.store)._credentials(target.provider)
                prefix = f"secret.cex.{target.provider}."
            keys = [(row.key, row.value_json) for row in self.store.list_admin_settings() if row.key.startswith(prefix)]
        # Ciphertexts, not plaintext secrets, participate in the private binding.
        binding = {key: value for key, value in asdict(target).items() if key != "label"}
        if target.connection_id:
            connection = next(c for c in self.connections.list().connections if str(c.id) == target.connection_id)
            binding["account_name"] = connection.account
            binding["subaccount"] = connection.subaccount
        if include_binance_earn:
            if target.provider != "binance" or not target.connection_id:
                raise HistoryFetchError("history_binance_earn_connection_required", resumable=False)
            from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService
            products = BinanceEarnHistoryService(
                self.store, connection_id=target.connection_id,
            ).history_products_for_connection()
            binding["binance_earn_product_basis_sha256"] = hashlib.sha256(
                canonical_json(products).encode(),
            ).hexdigest()
            snapshot = self.connections.snapshots(target.connection_id).model_dump(mode="json")
            binding["binance_earn_snapshot_sha256"] = hashlib.sha256(
                canonical_json(snapshot).encode(),
            ).hexdigest()
        return hashlib.sha256(canonical_json([software_version or __version__, binding, sorted(keys)]).encode()).hexdigest()

    def capability(self, ref):
        try:
            source = WorkspaceService(self.store).scope(ref).item
        except LookupError:
            raise HistoryFetchError("history_source_not_found", resumable=False) from None
        capability = HistoryCapability(source_ref=ref, label=source.label)
        try:
            target = self._target(ref)
            capability.provider = target.provider
            capability.supported = True
            capability.supports_binance_earn = target.provider == "binance" and target.connection_id is not None
            if target.provider != "solana":
                from steuerreport_v2.domain.history_cex import requires_symbols
                capability.requires_symbols = requires_symbols(target.provider)
            self._binding(target)
            capability.ready = True
        except HistoryFetchError as exc:
            capability.blocked_reason = exc.code
        except Exception:
            capability.blocked_reason = "history_connection_required"
        capability.coverage_notes = [
            "Anbietergrenzen und fehlende historische Daten bleiben pruefpflichtig.",
            "Der Abruf speichert Originalbelege. Erst eine gesonderte Freigabe importiert und berechnet.",
        ]
        if capability.provider == "solana":
            from steuerreport_v2.domain.history_solana import SolanaHistoryCollector
            capability.coverage_notes.extend(SolanaHistoryCollector.NOTES)
            from steuerreport_v2.contracts.history import HistoryRateState, HistoryRpcOption
            from steuerreport_v2.domain.history_rpc import rpc_options, rpc_status
            for values in rpc_options(self.store):
                option = HistoryRpcOption.model_validate(values)
                option.limits = HistoryRateState.model_validate(rpc_status(self.store, provider_id=option.provider_id))
                capability.rpc_options.append(option)
        elif capability.provider:
            from steuerreport_v2.domain.history_cex import coverage_notes
            capability.coverage_notes.extend(coverage_notes(capability.provider))
            if capability.supports_binance_earn:
                capability.coverage_notes.extend((
                    "Simple Earn kann ausdruecklich in denselben Historienauftrag aufgenommen werden.",
                    "Earn-Produktanker stammen nur aus dem gespeicherten Snapshot dieser Verbindung und ihren kontogebundenen Earn-Belegen; API-Retention und Vollstaendigkeit bleiben unbewiesen.",
                ))
        if capability.provider != "solana":
            from datetime import date
            capability.default_start = date(2009, 1, 1)
        return capability

    def _effective(self, job):
        if job["status"] in ACTIVE and (not _alive(job.get("_pid")) or datetime.fromisoformat(job["_until"]) < datetime.now(timezone.utc)):
            return {**job, "status": "paused", "phase": "Abruf unterbrochen; Fortsetzen moeglich", "error_code": "history_worker_stopped"}
        return job

    def _public(self, job):
        effective = self._effective(job)
        transport = None
        if job.get('transport'):
            from steuerreport_v2.contracts.history import HistoryRateState, HistoryRpcOption
            from steuerreport_v2.domain.history_rpc import rpc_status
            transport = HistoryRpcOption.model_validate(job['transport'])
            transport.limits = HistoryRateState.model_validate(rpc_status(self.store, provider_id=transport.provider_id))
        from steuerreport_v2.domain.history_progress import public_progress
        return HistoryJob.model_validate({**effective, "requires_repreview": bool(job.get("_preview") and job["_preview"].get("software_version") != __version__), "can_resume": (
            effective["status"] in {"paused", "failed"} and job.get("_resumable") is not False
        ), 'transport': transport, 'progress': public_progress(effective, transport)})

    def _check_rpc_binding(self, job):
        if job.get('_rpc_binding') is not None:
            from steuerreport_v2.domain.history_rpc import resolve_rpc
            endpoint = resolve_rpc(self.store, job['_options']['rpc_provider'])
            if endpoint.binding_hash != job['_rpc_binding']:
                raise HistoryFetchError('history_rpc_configuration_changed', resumable=False)

    def view(self, ref):
        capability = self.capability(ref)
        jobs = [self._public(job) for job in self.storage.jobs() if job["source_ref"] == ref]
        return HistoryView(capability=capability, jobs=jobs[:20])

    def get(self, ref, job_id):
        job = self.storage.load(job_id)
        if job["source_ref"] != ref:
            raise HistoryFetchError("history_job_not_found", resumable=False)
        return self._public(job)

    @contextmanager
    def _worker_guard(self, job_id):
        import fcntl
        directory = self.storage.directory(job_id, create=True)
        fd = os.open(directory / "worker.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HistoryFetchError("history_worker_running") from None
            yield
        finally:
            os.close(fd)

    def start(self, ref, request: HistoryStart):
        capability = self.capability(ref)
        if not capability.ready:
            raise HistoryFetchError(capability.blocked_reason or "history_provider_not_supported", resumable=False)
        if capability.requires_symbols and not request.symbols:
            raise HistoryFetchError("history_symbols_required", resumable=False)
        if request.include_binance_earn and not capability.supports_binance_earn:
            raise HistoryFetchError("history_binance_earn_connection_required", resumable=False)
        if capability.provider == "solana" and request.symbols:
            raise HistoryFetchError("solana_asset_filter_not_supported", resumable=False)
        target = self._target(ref)
        if target.provider != 'solana' and request.rpc_provider is not None:
            raise HistoryFetchError('history_rpc_provider_not_supported', resumable=False)
        job_id = str(request.request_id)
        transport = endpoint = None
        if request.rpc_provider is not None:
            from steuerreport_v2.domain.history_rpc import resolve_rpc
            endpoint = resolve_rpc(self.store, request.rpc_provider)
            transport = next((option for option in capability.rpc_options if option.id == request.rpc_provider), None)
            if transport is None or not transport.ready:
                raise HistoryFetchError('history_rpc_not_configured', resumable=False)
            transport = transport.model_copy(update={
                'provider_id': endpoint.provider_id, 'label': endpoint.label, 'kind': endpoint.kind,
            })
        end = request.end or datetime.now(timezone.utc).date()
        if end < request.start or request.start > datetime.now(timezone.utc).date():
            raise HistoryFetchError("history_date_range_invalid", resumable=False)
        options = HistoryOptions(
            start=datetime.combine(request.start, day_time.min, timezone.utc),
            end=min(datetime.combine(end, day_time.max, timezone.utc), datetime.now(timezone.utc)),
            symbols=tuple(request.symbols), public_rpc_only=request.public_rpc_only,
            rpc_provider=request.rpc_provider,
            inventory_job_id=job_id if request.rpc_provider is not None else None,
            include_binance_earn=request.include_binance_earn,
            max_records=request.max_records,
        )
        if target.provider != "solana":
            options = HistoryOptions(
                start=options.start, end=options.end.replace(microsecond=options.end.microsecond // 1000 * 1000),
                symbols=options.symbols, public_rpc_only=options.public_rpc_only,
                include_binance_earn=options.include_binance_earn,
                max_records=options.max_records,
            )
        values = request.model_dump(mode="json")
        with self.connections._mutation():
            jobs = self.storage.jobs()
            prior = next((job for job in jobs if job["id"] == job_id), None)
            if prior:
                prior_request = HistoryStart.model_validate(prior["_request"]).model_dump(mode="json")
                if prior["source_ref"] != ref or prior_request != values:
                    raise HistoryFetchError("history_request_id_conflict", resumable=False)
                return self._public(prior)
            if len(jobs) >= MAX_JOBS:
                raise HistoryFetchError("history_job_storage_limit", resumable=False)
            if any(job["source_ref"] == ref and self._effective(job)["status"] in {*ACTIVE, "paused", "ready"} for job in jobs):
                raise HistoryFetchError("history_source_job_exists")
            if sum(self._effective(job)["status"] in ACTIVE for job in jobs) >= MAX_ACTIVE:
                raise HistoryFetchError("history_job_capacity")
            self.storage.directory(job_id, create=True)
            job = {
                "id": job_id, "source_ref": ref, "label": target.label, "provider": target.provider,
                "status": "queued", "phase": "Abruf wartet", "created_at": now(), "updated_at": now(),
                "start": request.start.isoformat(), "end": end.isoformat(), "max_records": request.max_records,
                "records_fetched": 0, "pages_fetched": 0, "requests": 0,
                "includes_binance_earn": request.include_binance_earn,
                "provider_requests_reserved": 0,
                "provider_request_limit": MAX_PROVIDER_REQUESTS,
                "coverage_notes": capability.coverage_notes, "complete_history_proven": False,
                "_target": asdict(target), "_options": {**asdict(options), "start": options.start.isoformat(), "end": options.end.isoformat()},
                "_binding": self._binding(target, include_binance_earn=request.include_binance_earn),
                "_request": values, "_cursor": {}, "_records": {},
                "_pid": os.getpid(), "_run_id": str(uuid4()),
                "_until": (datetime.now(timezone.utc) + timedelta(seconds=RUN_SECONDS)).isoformat(),
            }
            if endpoint is not None:
                job['_rpc_binding'] = endpoint.binding_hash
                job['transport'] = transport.model_dump(mode='json')
            self.storage.save(job)
        self._launch(job_id)
        return self._public(job)

    def _launch(self, job_id):
        threading.Thread(target=self._run, args=(job_id,), daemon=True, name="source-history-" + job_id).start()

    def control(self, ref, job_id, action, request: HistoryResume | None = None):
        with self.connections._mutation():
            job = self.storage.load(job_id)
            if job["source_ref"] != ref:
                raise HistoryFetchError("history_job_not_found", resumable=False)
            status = self._effective(job)["status"]
            if action in {"pause", "cancel"}:
                if status in {"succeeded", "cancelled"}:
                    return self._public(job)
                # A timed-out lease can still have a live worker. Persist intent
                # even when the read-only effective view already reports paused.
                job["_pause_requested" if action == "pause" else "_cancel_requested"] = True
                if status in ACTIVE:
                    job["phase"] = "Pause angefordert" if action == "pause" else "Abbruch angefordert"
                else:
                    job.update(status="paused" if action == "pause" else "cancelled", phase="Abruf pausiert" if action == "pause" else "Abruf abgebrochen")
                self.storage.save(job)
                return self._public(job)
            if action != "resume" or request is None or status not in {"paused", "failed"} or job.get("_resumable") is False:
                raise HistoryFetchError("history_job_state_conflict")
            target = self._target(ref)
            if self._binding(target, include_binance_earn=bool(job.get("includes_binance_earn"))) != job["_binding"]:
                raise HistoryFetchError("history_source_changed", resumable=False)
            self._check_rpc_binding(job)
            if sum(self._effective(other)["status"] in ACTIVE for other in self.storage.jobs() if other["id"] != job["id"]) >= MAX_ACTIVE:
                raise HistoryFetchError("history_job_capacity")
            with self._worker_guard(job["id"]):
                job.update(status="queued", phase="Abruf wird fortgesetzt", error_code=None,
                           _pause_requested=False, _cancel_requested=False, _pid=os.getpid(),
                           _run_id=str(uuid4()), _until=(datetime.now(timezone.utc) + timedelta(seconds=RUN_SECONDS)).isoformat())
                if request.max_records is not None:
                    job["max_records"] = max(job["records_fetched"], request.max_records)
                job.pop('_detail_rate_ema', None)
                job['_detail_samples'] = 0
                job.pop('_detail_measured_at', None)
                self.storage.save(job)
        self._launch(job["id"])
        return self._public(job)

    def _collector(self, target, options):
        if target.provider == "solana":
            from steuerreport_v2.domain.history_solana import SolanaHistoryCollector
            return SolanaHistoryCollector(self.store, target, options)
        if options.include_binance_earn:
            from steuerreport_v2.domain.history_binance import BinanceHistoryCollector
            return BinanceHistoryCollector(self.store, target, options)
        from steuerreport_v2.domain.history_cex import CexHistoryCollector
        return CexHistoryCollector(self.store, target, options)

    def _reserve_provider_request(self, job_id, run_id):
        with self.connections._mutation():
            job = self.storage.load(job_id)
            if job.get("_run_id") != run_id:
                raise HistoryFetchError("history_worker_superseded", resumable=False)
            if job.get("_cancel_requested"):
                raise HistoryFetchError("history_cancelled", resumable=False)
            if job.get("_pause_requested"):
                raise HistoryFetchError("history_paused", resumable=True)
            target = self._target(job["source_ref"])
            if self._binding(target, include_binance_earn=bool(job.get("includes_binance_earn"))) != job["_binding"]:
                raise HistoryFetchError("history_source_changed", resumable=False)
            used = int(job.get("provider_requests_reserved", 0))
            limit = int(job.get("provider_request_limit", MAX_PROVIDER_REQUESTS))
            if used >= limit:
                raise HistoryFetchError("history_provider_request_budget_exhausted", resumable=False)
            job["provider_requests_reserved"] = used + 1
            self.storage.save(job)

    def _run(self, job_id):
        run_id = None
        try:
            with self._worker_guard(job_id):
                with self.connections._mutation():
                    job = self.storage.load(job_id)
                    if job["status"] != "queued":
                        return
                    run_id = job["_run_id"]
                    job.update(status="running", phase="Anbieter und Kontingent abfragen")
                    self.storage.save(job)
                target = HistoryTarget(**{**job["_target"], "budget_groups": tuple(job["_target"]["budget_groups"])})
                options = HistoryOptions(**{
                    **job["_options"],
                    "start": datetime.fromisoformat(job["_options"]["start"]),
                    "end": datetime.fromisoformat(job["_options"]["end"]),
                    "symbols": tuple(job["_options"]["symbols"]),
                    "max_records": max(1, int(job["max_records"]) - len(job["_records"])),
                })
                if self._binding(self._target(job["source_ref"]), include_binance_earn=bool(job.get("includes_binance_earn"))) != job["_binding"]:
                    raise HistoryFetchError("history_source_changed", resumable=False)
                self._check_rpc_binding(job)
                signal = _Signal(self, job_id, run_id, time.monotonic() + RUN_SECONDS)
                collector = self._collector(target, options)
                provider_request_used = int(job.get("provider_requests_reserved", 0))
                provider_request_limit = int(job.get("provider_request_limit", MAX_PROVIDER_REQUESTS))
                if options.include_binance_earn and provider_request_used >= provider_request_limit:
                    raise HistoryFetchError("history_provider_request_budget_exhausted", resumable=False)
                with outbound_scope(provider=None if target.provider == "solana" else target.provider,
                                    connection_id=target.connection_id, groups=tuple(sorted({"ip:global", *target.budget_groups})),
                                    cancel=signal, deadline=time.time() + RUN_SECONDS,
                                    max_requests=(provider_request_limit - provider_request_used)
                                    if options.include_binance_earn else None,
                                    reserve_request=(lambda: self._reserve_provider_request(job_id, run_id))
                                    if options.include_binance_earn else None):
                    while not job.get("_done"):
                        signal.check()
                        if len(job["_records"]) >= job["max_records"]:
                            raise HistoryFetchError("history_record_limit")
                        self._check_rpc_binding(job)
                        page_started = time.monotonic()
                        page = collector.fetch_page(job["_cursor"], signal.check)
                        signal.check()
                        self._check_rpc_binding(job)
                        if canonical_json(page.cursor) == canonical_json(job["_cursor"]) and not page.done:
                            raise HistoryFetchError("history_cursor_stalled", resumable=False)
                        pending = dict(job["_records"])
                        for record in page.records:
                            if not record.identity or len(record.identity) > 512:
                                raise HistoryFetchError("history_record_identity_invalid", resumable=False)
                            digest = self.storage.write_record(job_id, record)
                            previous = pending.get(record.identity)
                            if previous is not None and previous != digest:
                                # Different discovery metadata can accompany the
                                # same financial payload; the first original stays.
                                old = next(r for r in self.storage.records({**job, "_records": {record.identity: previous}}))
                                if record_digest(old) != record_digest(record):
                                    raise HistoryFetchError("history_evidence_conflict", resumable=False)
                            pending.setdefault(record.identity, digest)
                        if len(pending) > job["max_records"]:
                            raise HistoryFetchError("history_record_limit")
                        with self.connections._mutation():
                            signal.checked_at = 0
                            signal.check()
                            current = self.storage.load(job_id)
                            from steuerreport_v2.domain.history_progress import record_progress
                            record_progress(job, page, time.monotonic() - page_started)
                            job.update(_records=pending, _cursor=page.cursor, _done=page.done,
                                       records_fetched=len(pending), pages_fetched=job["pages_fetched"] + 1,
                                       requests=job["requests"] + page.requests, phase=page.phase,
                                       coverage_notes=list(dict.fromkeys([*job["coverage_notes"], *page.notes])),
                                       _pause_requested=current.get("_pause_requested", False), _cancel_requested=current.get("_cancel_requested", False))
                            job["provider_requests_reserved"] = current.get(
                                "provider_requests_reserved", job.get("provider_requests_reserved", 0),
                            )
                            if not job.get("sample_rows"):
                                job["sample_rows"] = [{key: row.get(key) for key in ("timestamp_utc", "event_type", "asset", "quantity", "side", "quote_asset", "quote_quantity")} for record in page.records for row in record.rows][:10]
                            self.storage.save(job)
                signal.checked_at = 0
                signal.check()
                with self.connections._mutation():
                    job.update(phase="Importvorschau wird berechnet")
                    job["_until"] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                    self.storage.save(job)
                signal.deadline = time.monotonic() + 1800
                preview = HistoryPreview(self.store).prepare(job, target)
                with self.connections._mutation(), self.store.connect() as con:
                    signal.checked_at = 0
                    signal.check()
                    if fingerprint(con) != preview["database_revision"]:
                        raise HistoryFetchError("history_preview_stale")
                    job.update(status="ready", phase="Vorschau bereit; Freigabe erforderlich", _preview=preview,
                               preview_sha256=preview["preview_sha256"], new_records=preview["new_records"],
                               duplicate_records=preview["duplicate_records"], before_summary=preview["before_summary"],
                               after_summary=preview["after_summary"], review_issues_open=preview["review_issues_open"], error_code=None)
                    job["sample_rows"] = preview["sample_rows"]
                    self.storage.save(job)
        except Exception as exc:
            try:
                with self.connections._mutation():
                    current = self.storage.load(job_id)
                    if current.get("_run_id") != run_id:
                        return
                    if current["status"] in {"cancelled", "succeeded"}:
                        return
                    if isinstance(exc, HistoryFetchError):
                        code, resumable = exc.code, exc.resumable
                    elif isinstance(exc, (RequestCancelled, RequestDeadlineExceeded)):
                        code, resumable = "history_run_deadline", True
                    elif isinstance(exc, SolanaHistoryConflict):
                        code, resumable = "history_existing_evidence_conflict", False
                    else:
                        code, resumable = self.connections._safe_error(exc), True
                    continue_automatically = (code == "history_run_deadline" and current["status"] in ACTIVE and not current.get("_pause_requested") and not current.get("_cancel_requested") and not current.get("_done"))
                    status = "queued" if continue_automatically else "cancelled" if current.get("_cancel_requested") else "paused" if resumable else "failed"
                    current.update(status=status, phase="Abruf abgebrochen" if status == "cancelled" else "Abruf angehalten; Hinweise pruefen",
                                   error_code=code, _resumable=resumable)
                    if continue_automatically:
                        current.update(phase="Naechster Abrufabschnitt startet", error_code=None, _run_id=str(uuid4()),
                                       _until=(datetime.now(timezone.utc) + timedelta(seconds=RUN_SECONDS)).isoformat())
                    self.storage.save(current)
                if continue_automatically:
                    self._launch(job_id)
            except Exception:
                return

    def approve(self, ref, job_id, request: HistoryApprove):
        with self.connections._mutation(), exclusive_history_import(self.store):
            job = self.storage.load(job_id)
            if job["source_ref"] != ref:
                raise HistoryFetchError("history_job_not_found", resumable=False)
            if job.get("status") != "succeeded" and self._binding(
                    self._target(ref), include_binance_earn=bool(job.get("includes_binance_earn"))) != job["_binding"]:
                raise HistoryFetchError("history_source_changed", resumable=False)
            self._check_rpc_binding(job)
            return self._public(HistoryPreview(self.store).apply(job, request))

    def repreview(self, ref, job_id):
        with self.connections._mutation():
            job = self.storage.load(job_id)
            if job["source_ref"] != ref or job["status"] not in {"ready", "paused", "failed"} or not job.get("_done") or not job.get("_preview") or job.get("approval"):
                raise HistoryFetchError("history_preview_required", resumable=False)
            old = job["_preview"]
            version = old.get("software_version")
            if not version or self._binding(
                    self._target(ref), software_version=version,
                    include_binance_earn=bool(job.get("includes_binance_earn"))) != job["_binding"]:
                raise HistoryFetchError("history_source_changed", resumable=False)
            self._check_rpc_binding(job)
            self.storage.records(job)
            content = canonical_json(old).encode()
            digest = hashlib.sha256(content).hexdigest()
            path = self.storage.directory(job_id) / ("previous-preview-" + digest + ".json")
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(content)
                path.chmod(0o400)
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise HistoryFetchError("history_preview_changed", resumable=False)
            previous = job.get("_previous_previews", [])
            if len(previous) >= 20:
                raise HistoryFetchError("history_job_storage_limit", resumable=False)
            job.update(_previous_previews=[*previous, {"sha256": digest, "software_version": version, "preview_sha256": job["preview_sha256"]}],
                       _binding=self._binding(
                           self._target(ref), include_binance_earn=bool(job.get("includes_binance_earn")),
                       ), status="queued", phase="Gespeicherte Originalbelege lokal neu pruefen",
                       _run_id=str(uuid4()), _until=(datetime.now(timezone.utc) + timedelta(seconds=RUN_SECONDS)).isoformat(),
                       _pid=os.getpid(), _pause_requested=False, _cancel_requested=False, error_code=None)
            self.storage.save(job)
        self._launch(job_id)
        return self._public(job)

    def audit(self, ref, job_id):
        job = self.storage.load(job_id)
        if job["source_ref"] != ref:
            raise HistoryFetchError("history_job_not_found", resumable=False)
        return {"job": self._public(job).model_dump(mode="json"), "evidence_sha256": sorted(job.get("_records", {}).values()),
                "preview": {k: v for k, v in job.get("_preview", {}).items() if k != "prepared_file"},
                "options": job["_options"], "source_binding": job["_target"],
                "software_version": __version__, "previous_previews": job.get("_previous_previews", []), "tax_source_activated": False}
