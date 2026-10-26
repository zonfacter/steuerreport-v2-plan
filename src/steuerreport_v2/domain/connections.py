"""Isolierte CEX-Verbindungen ohne Aktivierung steuerlicher Quellen.

Persistenz nutzt die vorhandenen atomaren admin_settings-Batches, ohne
Schemaaenderung oder Legacy-Migration. Mutationen sind pro Datenbank ueber
Prozess- und Dateisperre hostlokal koordiniert, kein Mehrhostbetrieb.
GETs starten keine Jobs oder Migrationen.
Ein Sync speichert ausschliesslich den letzten verbindungseigenen Bestand;
globale Anbieter-Snapshots, Raw-Objekte und Ledger bleiben unveraendert.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import weakref
from typing import Literal
from uuid import UUID, uuid4

from pydantic import SecretStr

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.connections import (
    Connection, ConnectionAction, ConnectionCreate, ConnectionJob, ConnectionJobs,
    ConnectionList, ConnectionSnapshots, ConnectionUpdate, CredentialMetadata,
    LegacyConnection,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secret_vault import (
    decode_secret_setting, encrypt_secret_setting, is_encrypted_envelope, load_vault_key,
)

RECORD_PREFIX = "connection.record."
JOB_PREFIX = "connection.job."
SNAPSHOT_PREFIX = "connection.snapshot."
SECRET_PREFIX = "secret.cex.connection."
FIELDS = ("api_key", "api_secret", "passphrase")
PROVIDERS = ("binance", "bitget", "coinbase", "pionex")
ACTIVE = {"queued", "running"}
MAX_ACTIVE = 4
MAX_RETAINED = 100
MAX_CONNECTIONS = 100
_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_cancel_signals: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


class ConnectionError(RuntimeError):
    """Ausschliesslich kontrollierte Codes, keine Providertexte oder URLs."""

    def __init__(self, code: str, http_status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(value: str | UUID) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ConnectionError("connection_id_invalid", 400) from None


def _secret_key(connection_id: str, field: str) -> str:
    return f"{SECRET_PREFIX}{connection_id}.{field}"


def _value(value: SecretStr | None) -> str:
    result = value.get_secret_value().strip() if value is not None else ""
    if len(result) > 16384:
        raise ConnectionError("connection_secret_too_long", 400)
    return result


def _setting(key: str, value: object) -> AdminSettingWrite:
    return AdminSettingWrite(key=key, value_json=json.dumps(value, separators=(",", ":")))


class _JobCancellation(threading.Event):
    """Auch Cancel-Anfragen eines anderen Workers vor Folge-Requests sehen."""

    def __init__(self, service: ConnectionService, job_id: str, deadline: float) -> None:
        super().__init__()
        self.service = service
        self.job_id = job_id
        self.deadline = deadline
        with _locks_guard:
            _cancel_signals[job_id] = self
        self.refresh()

    def refresh(self) -> bool:
        """DB nur ausserhalb des Limiters und vor der Signierung lesen."""
        if super().is_set():
            return True
        if time.time() >= self.deadline:
            self.set()
            return True
        try:
            record = self.service._read().get(f"{JOB_PREFIX}{self.job_id}")
            if not isinstance(record, dict) or bool(record.get("cancel_requested")):
                self.set()
        except Exception:
            # Koordinationsausfall darf keine weiteren Requests zulassen.
            self.set()
        return super().is_set()

    def wait(self, timeout: float | None = None) -> bool:
        end = min(self.deadline, time.time() + timeout) if timeout is not None else self.deadline
        while not self.is_set():
            if self.refresh():
                return True
            remaining = end - time.time()
            if remaining <= 0:
                return False
            super().wait(min(remaining, 0.1))
        return True


class ConnectionService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    @contextmanager
    def _mutation(self):
        path = str(self.store.path.resolve())
        with _locks_guard:
            lock = _locks.setdefault(path, threading.RLock())
        with lock, self.store.exclusive_access():
            try:
                import fcntl
            except ImportError:
                raise ConnectionError("connection_coordination_unavailable", 503) from None
            lock_path = Path(f"{path}.connections.lock")
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for setting in self.store.list_admin_settings():
            if setting.key.startswith((RECORD_PREFIX, JOB_PREFIX, SNAPSHOT_PREFIX)):
                try:
                    result[setting.key] = json.loads(setting.value_json)
                except (ValueError, TypeError):
                    raise ConnectionError("connection_store_invalid", 503) from None
        return result

    def _record(self, records: dict[str, object], connection_id: str) -> dict:
        record = records.get(f"{RECORD_PREFIX}{connection_id}")
        if not isinstance(record, dict):
            raise ConnectionError("connection_not_found", 404)
        return dict(record)

    def _metadata(self, prefix: str, provider: str, *, legacy: bool = False) -> CredentialMetadata:
        rows = {row.key: row for row in self.store.list_admin_settings() if row.key.startswith(prefix)}
        present = {field: bool(rows.get(f"{prefix}{field}")) for field in FIELDS}
        encrypted = bool(rows) and all(is_encrypted_envelope(row.value_json) for row in rows.values())
        readable: dict[str, bool] = {}
        invalid = False
        unavailable = False
        for field in FIELDS:
            row = rows.get(f"{prefix}{field}")
            if row is None:
                readable[field] = False
                continue
            if not legacy and not is_encrypted_envelope(row.value_json):
                invalid = True
                readable[field] = False
                continue
            try:
                readable[field] = bool(decode_secret_setting(row.key, row.value_json))
            except RuntimeError:
                unavailable = True
            except (ValueError, UnicodeError):
                invalid = True
        required = ["api_key", "api_secret"] + (["passphrase"] if provider == "bitget" else [])
        status = (
            "unavailable" if unavailable else "invalid" if invalid
            else "configured" if all(readable.get(field) for field in required)
            else "incomplete" if any(readable.values()) else "missing"
        )
        return CredentialMetadata(
            status=status, has_api_key=present["api_key"],
            has_api_secret=present["api_secret"], has_passphrase=present["passphrase"],
            encrypted=encrypted,
            updated_at=max((row.updated_at.replace(tzinfo=timezone.utc)
                            if row.updated_at.tzinfo is None else row.updated_at
                            for row in rows.values()), default=None),
        )

    def _public(self, record: dict) -> Connection:
        return Connection.model_validate({
            **record, "credentials": self._metadata(
                f"{SECRET_PREFIX}{record['id']}.", record["provider"],
            ),
        })

    def list(self) -> ConnectionList:
        records = self._read()
        connections = [self._public(value) for key, value in records.items()
                       if key.startswith(RECORD_PREFIX) and isinstance(value, dict)]
        keys = {row.key for row in self.store.list_admin_settings()}
        legacy = []
        for provider in PROVIDERS:
            prefix = f"secret.cex.{provider}."
            if any(key.startswith(prefix) for key in keys):
                legacy.append(LegacyConnection(
                    id=f"legacy:{provider}", provider=provider, label=f"{provider} (Legacy)",
                    credentials=self._metadata(prefix, provider, legacy=True),
                ))
        return ConnectionList(
            connections=sorted(connections, key=lambda item: (item.created_at, str(item.id))),
            legacy_connections=legacy, vault_ready=load_vault_key() is not None,
        )

    def _prepare_secrets(self, connection_id: str, payload) -> list[AdminSettingWrite]:
        vault_key = load_vault_key()
        if vault_key is None:
            raise ConnectionError("secret_vault_key_required", 503)
        writes = []
        for field in FIELDS:
            value = _value(getattr(payload, field))
            if not value:
                continue
            key = _secret_key(connection_id, field)
            writes.append(AdminSettingWrite(
                key=key, value_json=encrypt_secret_setting(key, value, vault_key),
            ))
        return writes

    def create(self, payload: ConnectionCreate) -> Connection:
        connection_id = str(uuid4())
        writes = self._prepare_secrets(connection_id, payload)
        now = _now().isoformat()
        record = {
            "id": connection_id, "provider": payload.provider, "label": payload.label,
            "account": payload.account, "subaccount": payload.subaccount,
            "origin": payload.origin, "budget_group": payload.budget_group,
            "created_at": now, "updated_at": now,
            "last_test_at": None, "last_sync_at": None, "last_error_code": None,
        }
        with self._mutation():
            records = self._read()
            if sum(key.startswith(RECORD_PREFIX) for key in records) >= MAX_CONNECTIONS:
                raise ConnectionError("connection_limit_reached")
            self.store.write_admin_settings_batch(
                [_setting(f"{RECORD_PREFIX}{connection_id}", record), *writes], [],
            )
        return self._public(record)

    def update(self, connection_id: str | UUID, payload: ConnectionUpdate) -> Connection:
        connection_id = _id(connection_id)
        with self._mutation():
            records = self._read()
            record = self._record(records, connection_id)
            self._reject_active(records, connection_id)
            writes = self._prepare_secrets(connection_id, payload)
            for field in ("label", "account", "subaccount", "budget_group"):
                if (value := getattr(payload, field)) is not None:
                    record[field] = value
            record["updated_at"] = _now().isoformat()
            if writes:
                # Ein alter Zugangstest bestaetigt keine geaenderten Credentials.
                record["last_test_at"] = None
                record["last_error_code"] = None
            self.store.write_admin_settings_batch(
                [_setting(f"{RECORD_PREFIX}{connection_id}", record), *writes], [],
            )
        return self._public(record)

    def delete_credentials(self, connection_id: str | UUID) -> Connection:
        connection_id = _id(connection_id)
        with self._mutation():
            records = self._read()
            record = self._record(records, connection_id)
            self._reject_active(records, connection_id)
            record.update(updated_at=_now().isoformat(), last_test_at=None, last_error_code=None)
            self.store.write_admin_settings_batch(
                [_setting(f"{RECORD_PREFIX}{connection_id}", record)],
                [_secret_key(connection_id, field) for field in FIELDS],
            )
        return self._public(record)

    def credentials(self, connection_id: str | UUID, provider: str) -> tuple[str, str, str]:
        connection_id = _id(connection_id)
        record = self._record(self._read(), connection_id)
        if record["provider"] != provider:
            raise ConnectionError("connection_provider_mismatch", 400)
        if load_vault_key() is None:
            raise ConnectionError("secret_vault_key_required", 503)
        settings = {row.key: row.value_json for row in self.store.list_admin_settings()}
        values = []
        for field in FIELDS:
            key = _secret_key(connection_id, field)
            if key not in settings:
                values.append("")
                continue
            if not is_encrypted_envelope(settings[key]):
                raise ConnectionError("connection_credentials_invalid", 503)
            try:
                values.append(decode_secret_setting(key, settings[key]))
            except (RuntimeError, ValueError, UnicodeError):
                raise ConnectionError("connection_credentials_unavailable", 503) from None
        if not values[0] or not values[1] or (provider == "bitget" and not values[2]):
            raise ConnectionError("connection_credentials_incomplete", 400)
        return values[0], values[1], values[2]

    def _effective_job(self, record: dict) -> dict:
        result = dict(record)
        result["slot_reserved"] = self._holds_slot(record)
        if result.get("status") in ACTIVE:
            expired = datetime.fromisoformat(result["deadline_at"]).timestamp() <= time.time()
            stopped = not self._owner_alive(result)
            if expired or stopped:
                result.update(status="failed", error_code="connection_job_deadline_exceeded" if expired else "connection_job_interrupted")
        return result

    @staticmethod
    def _owner_alive(record: dict) -> bool:
        try:
            pid = int(record["_pid"])
            if pid <= 0:
                return True
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except (PermissionError, KeyError, ValueError, TypeError, OverflowError):
            return True

    def _holds_slot(self, record: dict) -> bool:
        # Eine abgelaufene Deadline beendet keinen laufenden Python-/HTTP-Aufruf.
        # Erst Worker-Abschluss oder nachweisliches Prozessende gibt den Platz frei.
        return record.get("status") in ACTIVE and self._owner_alive(record)

    def _reject_active(self, records: dict[str, object], connection_id: str) -> None:
        if any(key.startswith(JOB_PREFIX) and isinstance(job, dict)
               and job.get("connection_id") == connection_id
               and self._holds_slot(job)
               for key, job in records.items()):
            raise ConnectionError("connection_job_already_active")

    def jobs(self) -> ConnectionJobs:
        records = self._read()
        jobs = [ConnectionJob.model_validate(self._effective_job(job))
                for key, job in records.items() if key.startswith(JOB_PREFIX) and isinstance(job, dict)]
        return ConnectionJobs(jobs=sorted(jobs, key=lambda job: job.created_at, reverse=True)[:MAX_RETAINED])

    def snapshots(self, connection_id: str | UUID) -> ConnectionSnapshots:
        connection_id = _id(connection_id)
        records = self._read()
        self._record(records, connection_id)
        return ConnectionSnapshots.model_validate(records.get(
            f"{SNAPSHOT_PREFIX}{connection_id}", {"connection_id": connection_id},
        ))

    def start(self, connection_id: str | UUID, action: Literal["test", "sync"],
              payload: ConnectionAction) -> ConnectionJob:
        connection_id = _id(connection_id)
        if action not in {"test", "sync"}:
            raise ConnectionError("connection_action_invalid", 400)
        if not payload.confirm_external_request or (action == "sync" and not payload.confirm_balance_snapshot):
            raise ConnectionError("connection_effect_confirmation_required", 400)
        try:
            from steuerreport_v2.domain.external_http import outbound_scope
        except ImportError:
            raise ConnectionError("external_http_unavailable", 503) from None
        if not callable(outbound_scope):
            raise ConnectionError("external_http_unavailable", 503)
        with self._mutation():
            records = self._read()
            record = self._record(records, connection_id)
            self._reject_active(records, connection_id)
            jobs = [(key, job) for key, job in records.items()
                    if key.startswith(JOB_PREFIX) and isinstance(job, dict)]
            if sum(self._holds_slot(job) for _, job in jobs) >= MAX_ACTIVE:
                raise ConnectionError("connection_job_queue_full", 429)
            # Vor dem Job nur entschluesseln/validieren, kein externer Zugriff.
            self.credentials(connection_id, record["provider"])
            now = _now()
            job = ConnectionJob(
                id=uuid4(), connection_id=UUID(connection_id), provider=record["provider"],
                action=action, status="queued", created_at=now, updated_at=now,
                slot_reserved=True,
                deadline_at=datetime.fromtimestamp(time.time() + payload.deadline_seconds, timezone.utc),
                effect="read_only_connection_test" if action == "test" else "connection_balance_snapshot",
            )
            stored = {**job.model_dump(mode="json", exclude={"slot_reserved"}), "_pid": os.getpid()}
            finished = sorted([(key, item) for key, item in jobs if not self._holds_slot(item)],
                              key=lambda item: item[1]["created_at"])
            prune = [key for key, _ in finished[:max(0, len(jobs) + 1 - MAX_RETAINED)]]
            self.store.write_admin_settings_batch([_setting(f"{JOB_PREFIX}{job.id}", stored)], prune)
        try:
            self._launch(str(job.id))
        except Exception:
            self._finish(str(job.id), "failed", error_code="connection_worker_unavailable")
            raise ConnectionError("connection_worker_unavailable", 503) from None
        return job

    def _launch(self, job_id: str) -> None:
        thread = threading.Thread(target=self._run, args=(job_id,), daemon=True,
                                  name=f"cex-connection-{job_id}")
        thread.start()

    def cancel(self, job_id: str | UUID) -> ConnectionJob:
        job_id = _id(job_id)
        with self._mutation():
            records = self._read()
            job = records.get(f"{JOB_PREFIX}{job_id}")
            if not isinstance(job, dict):
                raise ConnectionError("connection_job_not_found", 404)
            if job["status"] in ACTIVE:
                job.update(cancel_requested=True, updated_at=_now().isoformat())
                self.store.write_admin_settings_batch([_setting(f"{JOB_PREFIX}{job_id}", job)], [])
                with _locks_guard:
                    signal = _cancel_signals.get(job_id)
                    if signal is not None:
                        signal.set()
        return ConnectionJob.model_validate(self._effective_job(job))

    def _run(self, job_id: str) -> None:
        try:
            with self._mutation():
                records = self._read()
                job = dict(records[f"{JOB_PREFIX}{job_id}"])
                if job.get("status") != "queued":
                    return
                if job.get("cancel_requested"):
                    job.update(status="cancelled", updated_at=_now().isoformat())
                    self.store.write_admin_settings_batch([_setting(f"{JOB_PREFIX}{job_id}", job)], [])
                    return
                job.update(status="running", updated_at=_now().isoformat())
                self.store.write_admin_settings_batch([_setting(f"{JOB_PREFIX}{job_id}", job)], [])
                connection = self._record(records, job["connection_id"])
            from steuerreport_v2.domain.cex_balances import CexBalanceService
            from steuerreport_v2.domain.external_http import outbound_scope

            deadline = datetime.fromisoformat(job["deadline_at"]).timestamp()
            cancel = _JobCancellation(self, job_id, deadline)
            if cancel.is_set():
                self._finish(job_id, "cancelled")
                return
            groups = sorted({"ip:global", connection["budget_group"]})
            with outbound_scope(provider=connection["provider"], connection_id=job["connection_id"],
                                groups=groups, cancel=cancel, deadline=deadline):
                service = CexBalanceService(self.store, connection_id=job["connection_id"])
                if job["action"] == "test":
                    service.test_connection(connection["provider"])
                    snapshots = None
                else:
                    snapshots = service.fetch(connection["provider"], _now())
            self._finish(job_id, "succeeded", snapshots=snapshots)
        except Exception as exc:
            try:
                self._finish(job_id, "failed", error_code=self._safe_error(exc))
            except Exception:
                # Keine Tracebacks mit moeglichem HTTP-Kontext. Dauerhafte Jobs
                # werden nach ihrer Deadline lesend als fehlgeschlagen gezeigt.
                return

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ConnectionError):
            return exc.code
        from steuerreport_v2.domain.request_limits import (
            LimiterUnavailable, RequestCancelled, RequestCostExceeded,
            RequestDeadlineExceeded, RetryNotAllowed,
        )

        for error_type, safe_code in (
            (LimiterUnavailable, "connection_limiter_unavailable"),
            (RequestCancelled, "connection_request_cancelled"),
            (RequestCostExceeded, "connection_budget_capacity_exceeded"),
            (RequestDeadlineExceeded, "connection_job_deadline_exceeded"),
            (RetryNotAllowed, "connection_retry_not_allowed"),
        ):
            if isinstance(exc, error_type):
                return safe_code
        code = exc.args[0] if exc.args else None
        allowed = {
            "cex_authentication_failed", "cex_request_timeout", "external_http_unavailable",
            "coinbase_api_secret_invalid_ecdsa_private_key", "coinbase_api_secret_requires_es256_key",
            "cex_connection_response_invalid", "cex_provider_request_failed",
        }
        return code if isinstance(code, str) and code in allowed else "connection_provider_request_failed"

    def _finish(self, job_id: str, status: str, *, error_code: str | None = None,
                snapshots: list | None = None) -> None:
        with self._mutation():
            records = self._read()
            job = records.get(f"{JOB_PREFIX}{job_id}")
            if not isinstance(job, dict):
                return
            if job.get("status") not in ACTIVE:
                return
            now = _now()
            expired = now.timestamp() >= datetime.fromisoformat(job["deadline_at"]).timestamp()
            if expired:
                status, error_code = "failed", "connection_job_deadline_exceeded"
            elif job.get("cancel_requested"):
                status, error_code = "cancelled", None
            job.update(status=status, error_code=error_code, updated_at=now.isoformat())
            connection = self._record(records, job["connection_id"])
            created_at = datetime.fromisoformat(job["created_at"])
            superseded = datetime.fromisoformat(connection["updated_at"]) > created_at or any(
                key.startswith(JOB_PREFIX) and isinstance(other, dict)
                and other.get("connection_id") == job["connection_id"]
                and datetime.fromisoformat(other["created_at"]) > created_at
                for key, other in records.items()
            )
            if superseded:
                # Ein abgelaufener alter Worker darf weder neuere Metadaten
                # noch ein inzwischen erfolgreiches Ergebnis ueberschreiben.
                self.store.write_admin_settings_batch([_setting(f"{JOB_PREFIX}{job_id}", job)], [])
                return
            connection["last_error_code"] = error_code
            connection["updated_at"] = now.isoformat()
            writes = []
            if status == "succeeded":
                connection["last_test_at" if job["action"] == "test" else "last_sync_at"] = now.isoformat()
                if snapshots is not None:
                    result = ConnectionSnapshots(
                        connection_id=UUID(job["connection_id"]), fetched_at=now, snapshots=snapshots,
                    )
                    job["snapshot_count"] = len(snapshots)
                    writes.append(_setting(f"{SNAPSHOT_PREFIX}{job['connection_id']}", result.model_dump(mode="json")))
            writes.extend([
                _setting(f"{JOB_PREFIX}{job_id}", job),
                _setting(f"{RECORD_PREFIX}{job['connection_id']}", connection),
            ])
            self.store.write_admin_settings_batch(writes, [])
