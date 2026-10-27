"""Private Abrufbelege und dauerhafte, geheimnisfreie Job-Zustaende."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryRecord
from steuerreport_v2.importers.source_history_importer import canonical_json

PREFIX = "history.job."


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise HistoryFetchError("history_job_id_invalid", resumable=False) from None


class HistoryStorage:
    def __init__(self, store: DuckDbStore):
        self.store = store

    def jobs(self) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                "select value_json from admin_settings where starts_with(key, ?) order by updated_at desc",
                [PREFIX],
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def load(self, job_id: str) -> dict:
        with self.store.connect() as con:
            row = con.execute("select value_json from admin_settings where key=?", [PREFIX + identifier(job_id)]).fetchone()
        if row is None:
            raise HistoryFetchError("history_job_not_found", resumable=False)
        return json.loads(row[0])

    def save(self, job: dict) -> None:
        job["updated_at"] = now()
        self.store.write_admin_settings_batch([
            AdminSettingWrite(key=PREFIX + identifier(job["id"]), value_json=canonical_json(job)),
        ], [])

    def directory(self, job_id: str, *, create=False) -> Path:
        root = self.store.path.parent / "source_history_previews"
        path = root / identifier(job_id)
        if root.is_symlink() or path.is_symlink():
            raise HistoryFetchError("history_storage_invalid", resumable=False)
        if create:
            root.mkdir(mode=0o700, exist_ok=True)
            path.mkdir(mode=0o700, exist_ok=True)
        return path

    def write_record(self, job_id: str, record: HistoryRecord) -> str:
        encoded = canonical_json(asdict(record)).encode()
        if len(encoded) > 8 * 1024 * 1024:
            raise HistoryFetchError("history_record_too_large", resumable=False)
        digest = hashlib.sha256(encoded).hexdigest()
        directory = self.directory(job_id, create=True) / "records"
        if directory.is_symlink():
            raise HistoryFetchError("history_storage_invalid", resumable=False)
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / (digest + ".json")
        if not target.exists():
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, prefix="pending-", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    pass
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise HistoryFetchError("history_evidence_changed", resumable=False)
        return digest

    def records(self, job: dict) -> list[HistoryRecord]:
        records = []
        directory = self.directory(job["id"]) / "records"
        if directory.is_symlink():
            raise HistoryFetchError("history_storage_invalid", resumable=False)
        for expected in job.get("_records", {}).values():
            if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
                raise HistoryFetchError("history_evidence_changed", resumable=False)
            path = directory / (expected + ".json")
            try:
                if path.is_symlink():
                    raise OSError("symlink")
                content = path.read_bytes()
            except OSError:
                raise HistoryFetchError("history_evidence_missing", resumable=False) from None
            if hashlib.sha256(content).hexdigest() != expected:
                raise HistoryFetchError("history_evidence_changed", resumable=False)
            records.append(HistoryRecord(**json.loads(content)))
        return records
