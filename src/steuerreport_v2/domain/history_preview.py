"""Bestehende Berechnung in privater Kopie; Uebernahme nur atomar und freigegeben."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import shutil
from uuid import uuid4

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.history import HistoryApprove
from steuerreport_v2.contracts.review import ReviewDecision
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.ai_changes import DERIVED_TABLES, _fingerprint, _summary, _tax_delta, _tax_groups
from steuerreport_v2.domain.history_storage import PREFIX, HistoryStorage
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryTarget
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.source_history_importer import canonical_json, import_records, prepare_records


def fingerprint(con):
    return _fingerprint(con, excluded_admin_prefixes=(PREFIX,))


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class HistoryPreview:
    def __init__(self, store: DuckDbStore):
        self.store = store
        self.storage = HistoryStorage(store)

    def prepare(self, job: dict, target: HistoryTarget) -> dict:
        records = self.storage.records(job)
        directory = self.storage.directory(job["id"], create=True)
        # A non-main extension keeps diagnostic tools from mistaking a private
        # calculation copy for another productive database.
        working = directory / (str(uuid4()) + ".prepared")
        with self.store.exclusive_access(), self.store.connect() as con:
            revision = fingerprint(con)
            before, before_tax = _summary(con), _tax_groups(con)
            if target.provider != "solana":
                ambiguous = con.execute(
                    """
                    select count(*) from canonical_events e
                    left join raw_objects r on r.raw_object_id=e.raw_object_id
                    where lower(e.source)=? and e.event_time>=? and e.event_time<=?
                      and (e.account=? or not starts_with(coalesce(e.account, ''), 'connection:'))
                      and coalesce(json_extract_string(r.payload_json, '$.history_scope_identity'), '')=''
                    """, [target.provider, job["_options"]["start"], job["_options"]["end"], target.account],
                ).fetchone()[0]
                if ambiguous:
                    raise HistoryFetchError("history_legacy_account_assignment_required", resumable=False)
            con.execute("checkpoint")
            if shutil.disk_usage(directory).free < self.store.path.stat().st_size * 2 + 128 * 1024 * 1024:
                raise HistoryFetchError("history_storage_insufficient")
            shutil.copyfile(self.store.path, working)
            working.chmod(0o600)
        try:
            clone = DuckDbStore(working)
            accepted, duplicates = prepare_records(clone, target, records)
            batches = import_records(clone, target, accepted, job["id"])
            pipeline = None
            for batch in batches:
                pipeline = PipelineService(clone).rebuild_after_import(batch.batch_id).pipeline
                with clone.connect() as con:
                    con.execute("update raw_import_batches set status='normalized' where batch_id=?", [batch.batch_id])
            with clone.connect() as con:
                after = _summary(con)
                deltas = _tax_delta(before_tax, _tax_groups(con))
                imported_events = con.execute(
                    "select count(*) from canonical_events where raw_object_id in "
                    "(select raw_object_id from raw_objects where batch_id in (select unnest(?)))",
                    [[batch.batch_id for batch in batches]],
                ).fetchone()[0] if batches else 0
                con.execute("checkpoint")
            prepared = {
                "database_revision": revision, "prepared_file": working.name,
                "prepared_sha256": file_hash(working), "before_summary": before,
                "after_summary": after, "tax_line_deltas": deltas,
                "software_version": __version__, "new_records": len(accepted),
                "duplicate_records": duplicates, "imported_events": imported_events,
                "batch_ids": [batch.batch_id for batch in batches],
                "evidence_hashes": sorted(job["_records"].values()),
                "source_ref": target.source_ref,
                "review_issues_open": pipeline.review_issues_open if pipeline else None,
            }
            prepared["preview_sha256"] = hashlib.sha256(canonical_json(prepared).encode()).hexdigest()
            return prepared
        except Exception:
            working.unlink(missing_ok=True)
            raise

    def apply(self, job: dict, request: HistoryApprove) -> dict:
        preview = job.get("_preview")
        if not isinstance(preview, dict) or preview.get("preview_sha256") != request.preview_sha256:
            raise HistoryFetchError("history_preview_required", resumable=False)
        expected = hashlib.sha256(canonical_json({k: v for k, v in preview.items() if k != "preview_sha256"}).encode()).hexdigest()
        if expected != request.preview_sha256 or preview["software_version"] != __version__:
            raise HistoryFetchError("history_preview_changed", resumable=False)
        if job["status"] == "succeeded":
            return job
        if job["status"] != "ready":
            raise HistoryFetchError("history_preview_required", resumable=False)
        # Raw evidence is rechecked independently of the prepared database.
        self.storage.records(job)
        working = self.storage.directory(job["id"]) / preview["prepared_file"]
        if working.is_symlink() or not working.is_file() or file_hash(working) != preview["prepared_sha256"]:
            raise HistoryFetchError("history_preview_changed", resumable=False)
        with self.store.exclusive_access(), self.store.connect() as con:
            if fingerprint(con) != preview["database_revision"]:
                raise HistoryFetchError("history_preview_stale")
            escaped = str(working).replace("'", "''")
            con.execute(f"attach '{escaped}' as history_prepared (read_only)")
            try:
                con.execute("begin transaction")
                for table, key in (("raw_import_batches", "batch_id"), ("raw_objects", "raw_object_id")):
                    con.execute(
                        f"insert into {table} select p.* from history_prepared.{table} p "
                        f"where not exists(select 1 from {table} live where live.{key}=p.{key})",
                    )
                if preview["batch_ids"]:
                    for table in ("canonical_events", *DERIVED_TABLES):
                        con.execute(f"delete from {table}")
                        con.execute(f"insert into {table} select * from history_prepared.{table}")
                if _summary(con) != preview["after_summary"]:
                    raise HistoryFetchError("reconciliation_failed", resumable=False)
                approval = {**request.model_dump(mode="json"), "approved_at_utc": datetime.now(timezone.utc).isoformat(), "identity_verified": False}
                decision = ReviewDecision(
                    decision_id=str(uuid4()), decision_type="source_history_import",
                    scope="source_history:" + job["id"], title="API-Historie nach Vorschau importiert",
                    rationale="Ausdrueckliche Uebernahme der ausgewiesenen Originalbelege und Berechnung; keine steuerliche Quellen- oder Jahresfreigabe.",
                    actor=request.actor, evidence_ref=f"api:/api/v1/workspace/sources/{job['source_ref']}/history/jobs/{job['id']}/audit.json",
                    source=job["provider"], affected_ids=preview["batch_ids"],
                    payload={"preview_sha256": expected, "new_records": preview["new_records"], "approval": approval},
                    created_at=datetime.now(timezone.utc),
                )
                con.execute("insert into review_decisions values (?, ?, ?, ?)", [decision.decision_id, decision.model_dump_json(), decision.created_at, None])
                job.update(status="succeeded", phase="Import abgeschlossen", approval=approval,
                           imported_events=preview["imported_events"], error_code=None,
                           updated_at=datetime.now(timezone.utc).isoformat())
                con.execute(
                    "update admin_settings set value_json=?, updated_at=? where key=?",
                    [canonical_json(job), datetime.now(timezone.utc), PREFIX + job["id"]],
                )
                con.execute("commit")
            except Exception:
                con.execute("rollback")
                raise
            finally:
                con.execute("detach history_prepared")
        # Originals stay immutable; the calculation copy is not a source document.
        working.unlink(missing_ok=True)
        return job
