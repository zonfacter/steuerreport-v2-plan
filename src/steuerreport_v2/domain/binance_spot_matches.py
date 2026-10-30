"""Explizite, append-only Zuordnung zwischen Binance-Spot-CSV und API-Fill."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timezone
from decimal import Decimal
import base64
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

from steuerreport_v2.contracts.history import (
    BinanceSpotMatchCandidate,
    BinanceSpotMatchDecisionCreate,
    BinanceSpotMatchPreview,
    BinanceSpotMatchPreviewRequest,
    BinanceSpotMatchRevocation,
)
from steuerreport_v2.contracts.imports import ImportAssistantExecuteResult, ImportAssistantRequest
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.history_storage import HistoryStorage
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryRecord, HistoryTarget
from steuerreport_v2.domain.import_assistant import ImportAssistantService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.binance_spot_lock import BINANCE_SPOT_IMPORT_LOCK
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.source_history_importer import canonical_json, record_digest, scope_identity


MATCH_TYPE = "binance_spot_csv_api_match"
REVOKE_TYPE = "binance_spot_csv_api_match_revocation"
_TRADE_ID_COLUMNS = {"trade id", "tradeid"}
_SYMBOL_COLUMNS = {"symbol", "pair"}
_METADATA_FIELDS = {
    "history evidence only", "history scope identity", "history payload sha256",
    "history record id", "history source ref", "raw history record",
}


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value:
        return "0"
    return format(value.normalize(), "f")


def _column_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip().casefold().replace("_", " "))


def _one_column(row: dict[str, object], names: set[str]) -> tuple[str | None, bool]:
    found = [str(value).strip() for key, value in row.items()
             if _column_name(key) in names and value not in (None, "")]
    if not found:
        return None, False
    distinct = set(found)
    return (found[0], False) if len(distinct) == 1 else (None, True)


def _strip_match_metadata(row: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if _column_name(key) not in _METADATA_FIELDS}


class BinanceSpotHistoryMatchService:
    """Nutzt bestehende Rohimport- und Review-Tabellen; schreibt keine Rohquelle um."""

    def __init__(self, store: DuckDbStore):
        self.store = store
        self.storage = HistoryStorage(store)
        self.normalizer = RawNormalizer(store)

    def _job(self, ref: str, job_id: str) -> tuple[dict, HistoryTarget]:
        job = self.storage.load(job_id)
        if job.get("source_ref") != ref:
            raise HistoryFetchError("history_job_not_found", resumable=False)
        target_data = job.get("_target")
        if not isinstance(target_data, dict):
            raise HistoryFetchError("history_match_scope_unavailable", resumable=False)
        target = HistoryTarget(**target_data)
        if (target.provider != "binance" or not target.connection_id
                or job.get("provider") != "binance" or job.get("includes_binance_earn")):
            raise HistoryFetchError("history_binance_spot_match_scope_required", resumable=False)
        return job, target

    def _upload_rows(self, request: BinanceSpotMatchPreviewRequest) -> tuple[list[tuple[int, dict[str, object], str]], str, str, None]:
        if not request.filename or Path(request.filename).suffix.casefold() != ".csv":
            raise HistoryFetchError("history_binance_spot_csv_required", resumable=False)
        if request.content_base64 is not None:
            try:
                content = base64.b64decode(request.content_base64, validate=True)
            except Exception:
                raise HistoryFetchError("history_match_file_invalid", resumable=False) from None
            importer = FileRawImporter(CsvRawImporter(self.store))
            rows, _columns, file_format, sheet, _sheets = importer._rows_from_bytes(
                request.filename, content, request.sheet_name, "binance",
            )
            if file_format != "csv" or sheet is not None:
                raise HistoryFetchError("history_binance_spot_csv_required", resumable=False)
            file_hash = importer._file_hash(content, None)
        elif request.content is not None:
            content = request.content.encode("utf-8")
            importer = CsvRawImporter(self.store)
            rows = [importer._stringify_row(row) for row in importer._dict_reader(request.content, "binance")]
            file_hash = importer.hash_text(request.content)
        else:
            raise HistoryFetchError("history_match_file_invalid", resumable=False)
        csv_importer = CsvRawImporter(self.store)
        normalized_rows = []
        for row_number, row in enumerate(rows, start=1):
            row = csv_importer._stringify_row(row)
            if not csv_importer._is_ignorable_row("binance", row):
                row_hash = hashlib.sha256(canonical_json(row).encode()).hexdigest()
                normalized_rows.append((row_number, row, row_hash))
        return normalized_rows, file_hash, request.filename, None

    def _batch_rows(self, target: HistoryTarget, batch_id: str) -> tuple[list[tuple[int, dict[str, object], str]], str, str, str]:
        with self.store.connect() as con:
            row = con.execute(
                """select source, filename, file_hash, connection_id from raw_import_batches
                   where batch_id=?""", [batch_id],
            ).fetchone()
            if row is None or row[0] != "binance" or str(row[3] or "") != target.connection_id:
                raise HistoryFetchError("history_match_csv_batch_scope_invalid", resumable=False)
            if Path(str(row[1] or "")).suffix.casefold() != ".csv":
                raise HistoryFetchError("history_binance_spot_csv_required", resumable=False)
            objects = con.execute(
                "select raw_object_id, row_number, payload_json from raw_objects where batch_id=? order by row_number",
                [batch_id],
            ).fetchall()
        result = []
        for raw_id, row_number, payload_json in objects:
            payload = json.loads(payload_json)
            result.append((int(row_number), payload, hashlib.sha256(payload_json.encode()).hexdigest()))
        return result, str(row[2] or ""), str(row[1] or "binance.csv"), batch_id

    def _raw_event(self, row: dict[str, object], *, account: str, filename: str):
        clean = _strip_match_metadata(row)
        return self.normalizer._row_to_event(
            "binance", "spot-match-preview",
            {str(key): None if value is None else str(value) for key, value in clean.items()},
            default_timezone=self.normalizer._timezone_from_text(filename),
            bound_account=account,
        )

    def _event(self, row: dict[str, object], *, account: str, filename: str):
        event = self._raw_event(row, account=account, filename=filename)
        if event is None or event.event_type != "trade" or not event.quantity:
            return None
        if event.quote_asset is None or event.quote_quantity is None:
            return None
        if event.fee_quantity not in (None, Decimal("0")) and event.fee_asset is None:
            return None
        return event

    @staticmethod
    def _financial_sha256(event) -> str:
        fee_quantity = event.fee_quantity if event.fee_quantity is not None else Decimal("0")
        value = {
            "event_time_utc": event.event_time.replace(tzinfo=timezone.utc).astimezone(timezone.utc).isoformat(timespec="microseconds")
            if event.event_time.tzinfo is None
            else event.event_time.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            "event_type": event.event_type,
            "asset": event.asset.upper(),
            "quantity": _decimal(event.quantity),
            "quote_asset": event.quote_asset.upper() if event.quote_asset else None,
            "quote_quantity": _decimal(event.quote_quantity),
            "fee_asset": event.fee_asset.upper() if fee_quantity not in (None, Decimal("0")) and event.fee_asset else None,
            "fee_quantity": _decimal(fee_quantity),
        }
        return hashlib.sha256(canonical_json(value).encode()).hexdigest()

    @staticmethod
    def _financial_facts(event) -> dict[str, str | None] | None:
        if event is None:
            return None
        timestamp = event.event_time
        timestamp = (
            timestamp.replace(tzinfo=timezone.utc)
            if timestamp.tzinfo is None
            else timestamp.astimezone(timezone.utc)
        )
        return {
            "event_time_utc": timestamp.isoformat(timespec="microseconds"),
            "event_type": event.event_type,
            "asset": event.asset.upper(),
            "quantity": _decimal(event.quantity),
            "quote_asset": event.quote_asset.upper() if event.quote_asset else None,
            "quote_quantity": _decimal(event.quote_quantity) if event.quote_quantity is not None else None,
            "fee_asset": event.fee_asset.upper() if event.fee_asset else None,
            "fee_quantity": _decimal(event.fee_quantity) if event.fee_quantity is not None else None,
        }

    def _api_entries(self, target: HistoryTarget, records: list[HistoryRecord]):
        entries = []
        for record in records:
            raw = record.raw if isinstance(record.raw, dict) else {}
            payload = raw.get("payload")
            if (record.source != "binance" or raw.get("endpoint") != "/api/v3/myTrades"
                    or not isinstance(payload, dict)):
                continue
            provider_id = payload.get("id")
            symbol = payload.get("symbol")
            if (isinstance(provider_id, bool) or not isinstance(provider_id, (str, int))
                    or not str(provider_id).strip() or not isinstance(symbol, str) or not symbol.strip()):
                entries.append({"record": record, "invalid": True})
                continue
            expected_identity = "cex:" + json.dumps(
                ["binance", target.account, "/api/v3/myTrades", symbol.strip().upper(), str(provider_id).strip()],
                ensure_ascii=True, separators=(",", ":"),
            )
            if record.identity != expected_identity:
                entries.append({"record": record, "invalid": True})
                continue
            event = self._event(record.rows[0], account=target.account, filename="api-history-utc.csv") if len(record.rows) == 1 else None
            entries.append({
                "record": record, "record_sha256": hashlib.sha256(canonical_json(asdict(record)).encode()).hexdigest(),
                "payload_sha256": record_digest(record), "identity": record.identity,
                "scope_identity": scope_identity(target, record), "provider_id": str(provider_id).strip(),
                "symbol": symbol.strip().upper(), "financial_sha256": self._financial_sha256(event) if event else None,
                "financial_facts": self._financial_facts(event),
                "invalid": event is None,
            })
        return entries

    def preview(
        self, ref: str, job_id: str, request: BinanceSpotMatchPreviewRequest,
    ) -> BinanceSpotMatchPreview:
        job, target = self._job(ref, job_id)
        api_records = self.storage.records(job)
        api_entries = self._api_entries(target, api_records)
        if request.batch_id:
            rows, file_hash, filename, batch_id = self._batch_rows(target, request.batch_id)
        else:
            rows, file_hash, filename, batch_id = self._upload_rows(request)
            existing = self.store.get_import_batch_by_file_hash("binance", file_hash, target.connection_id)
            if existing is not None:
                rows, existing_hash, filename, batch_id = self._batch_rows(target, existing.batch_id)
                if existing_hash != file_hash:
                    raise HistoryFetchError("history_match_csv_batch_scope_invalid", resumable=False)

        csv_keys: dict[tuple[str, str], list[int]] = {}
        row_info = []
        for number, row, row_sha in rows:
            record_id, id_conflict = _one_column(row, _TRADE_ID_COLUMNS)
            symbol, symbol_conflict = _one_column(row, _SYMBOL_COLUMNS)
            symbol = symbol.upper() if symbol else None
            event = self._event(row, account=target.account, filename=filename)
            financial_sha = self._financial_sha256(event) if event else None
            key = (symbol, record_id) if symbol and record_id else None
            if key:
                csv_keys.setdefault(key, []).append(number)
            row_info.append({
                "row_number": number, "row_sha256": row_sha, "provider_id": record_id,
                "id_conflict": id_conflict, "symbol": symbol, "symbol_conflict": symbol_conflict,
                "financial_sha256": financial_sha, "financial_facts": self._financial_facts(event), "key": key,
            })
        api_by_key: dict[tuple[str, str], list[dict]] = {}
        for entry in api_entries:
            if entry.get("symbol") and entry.get("provider_id"):
                api_by_key.setdefault((entry["symbol"], entry["provider_id"]), []).append(entry)

        decisions = self.store.list_review_decisions()
        revoked_ids = {
            decision.payload.get("revokes_decision_id")
            for decision in decisions if decision.decision_type == REVOKE_TYPE
        }
        decisions_by_api: dict[str, list] = {}
        for decision in decisions:
            if (decision.decision_type == MATCH_TYPE
                    and decision.payload.get("connection_id") == target.connection_id):
                decisions_by_api.setdefault(str(decision.payload.get("api_record_identity")), []).append(decision)

        candidates = []
        for item in row_info:
            key = item["key"]
            matches = api_by_key.get(key, []) if key else []
            entry = matches[0] if len(matches) == 1 else None
            if not item["provider_id"] or item["id_conflict"]:
                status = "missing_stable_id"
            elif not item["symbol"] or item["symbol_conflict"]:
                status = "symbol_missing"
            elif len(csv_keys.get(key, [])) > 1:
                status = "csv_id_ambiguous"
            elif len(matches) > 1:
                status = "api_id_ambiguous"
            elif entry is None:
                status = "api_record_missing"
            elif not item["financial_sha256"] or not entry.get("financial_sha256") or entry.get("invalid"):
                status = "financial_shape_unsupported"
            elif item["financial_sha256"] != entry["financial_sha256"]:
                status = "financial_digest_conflict"
            else:
                status = "matchable"
            matching_decisions = decisions_by_api.get(entry["identity"], []) if entry else []
            decision = next((value for value in matching_decisions if value.decision_id not in revoked_ids), None)
            decision_state = "active" if decision else "revoked" if matching_decisions else "none"
            decision_id = decision.decision_id if decision else matching_decisions[-1].decision_id if matching_decisions else None
            if status == "matchable" and decision_state == "active":
                status = "already_decided"
            elif status == "matchable" and decision_state == "revoked":
                status = "match_revoked"
            candidates.append(BinanceSpotMatchCandidate(
                csv_row_number=item["row_number"], csv_provider_record_id=item["provider_id"],
                symbol=item["symbol"], api_record_identity=entry["identity"] if entry else None,
                csv_financial_sha256=item["financial_sha256"],
                api_financial_sha256=entry.get("financial_sha256") if entry else None,
                csv_financial_facts=item["financial_facts"],
                api_financial_facts=entry.get("financial_facts") if entry else None,
                decision_id=decision_id, decision_state=decision_state,
                status=status,
            ))

        preview_basis = {
            "version": 1, "job_id": job_id, "connection_id": target.connection_id,
            "file_sha256": file_hash, "source_batch_id": batch_id,
            "rows": row_info,
            "api_records": sorted(({
                "identity": entry.get("identity"), "record_sha256": entry.get("record_sha256"),
                "payload_sha256": entry.get("payload_sha256"), "symbol": entry.get("symbol"),
                "provider_id": entry.get("provider_id"), "financial_sha256": entry.get("financial_sha256"),
                "invalid": entry.get("invalid"),
            } for entry in api_entries), key=lambda value: str(value.get("identity"))),
        }
        preview_sha = hashlib.sha256(canonical_json(preview_basis).encode()).hexdigest()
        return BinanceSpotMatchPreview(
            connection_id=UUID(target.connection_id), job_id=UUID(job_id), file_sha256=file_hash,
            source_batch_id=batch_id, preview_sha256=preview_sha, candidates=candidates,
        )

    def decide(self, ref: str, job_id: str, request: BinanceSpotMatchDecisionCreate) -> ReviewDecision:
        with BINANCE_SPOT_IMPORT_LOCK:
            return self._decide_locked(ref, job_id, request)

    def _decide_locked(self, ref: str, job_id: str, request: BinanceSpotMatchDecisionCreate) -> ReviewDecision:
        preview_request = BinanceSpotMatchPreviewRequest(
            batch_id=request.batch_id, filename=request.filename, content=request.content,
            content_base64=request.content_base64, sheet_name=request.sheet_name,
        )
        preview = self.preview(ref, job_id, preview_request)
        if preview.preview_sha256 != request.preview_sha256:
            raise HistoryFetchError("history_match_preview_stale", resumable=False)
        job, target = self._job(ref, job_id)
        if job.get("status") == "succeeded" and preview.source_batch_id:
            raise HistoryFetchError("history_match_both_sources_already_imported", resumable=False)
        candidates = [candidate for candidate in preview.candidates
                      if candidate.csv_row_number == request.csv_row_number
                      and candidate.api_record_identity == request.api_record_identity]
        if len(candidates) == 1 and candidates[0].decision_state != "none":
            raise HistoryFetchError("history_match_already_decided", resumable=False)
        if len(candidates) != 1 or candidates[0].status != "matchable":
            raise HistoryFetchError("history_match_not_exact", resumable=False)
        candidate = candidates[0]
        api_record = next((row for row in self._api_entries(target, self.storage.records(job))
                           if row.get("identity") == request.api_record_identity), None)
        if api_record is None or api_record.get("invalid"):
            raise HistoryFetchError("history_match_api_record_ambiguous", resumable=False)
        source_batch_id = preview.source_batch_id
        source_raw_id = None
        if source_batch_id:
            with self.store.connect() as con:
                row = con.execute(
                    "select raw_object_id from raw_objects where batch_id=? and row_number=?",
                    [source_batch_id, request.csv_row_number],
                ).fetchone()
            if row is None:
                raise HistoryFetchError("history_match_csv_row_not_found", resumable=False)
            source_raw_id = str(row[0])
        else:
            persisted = next((item for item in self._stored_api_rows(target.connection_id)
                              if item.get("identity") == request.api_record_identity
                              and item.get("payload_sha256") == api_record.get("payload_sha256")), None)
            if persisted is None:
                raise HistoryFetchError("history_match_api_evidence_not_persisted", resumable=False)
        for decision in self.store.list_review_decisions():
            if decision.decision_type not in {MATCH_TYPE, REVOKE_TYPE}:
                continue
            payload = decision.payload
            if (payload.get("connection_id") == target.connection_id
                    and payload.get("api_record_identity") == request.api_record_identity):
                raise HistoryFetchError("history_match_already_decided", resumable=False)
            if (payload.get("connection_id") == target.connection_id
                    and payload.get("file_sha256") == preview.file_sha256
                    and payload.get("csv_row_number") == request.csv_row_number):
                raise HistoryFetchError("history_match_already_decided", resumable=False)
        payload = {
            "action": "match", "api_job_id": job_id, "api_record_identity": api_record["identity"],
            "api_record_sha256": api_record["record_sha256"],
            "api_payload_sha256": api_record["payload_sha256"],
            "history_scope_identity": api_record["scope_identity"],
            "connection_id": target.connection_id, "provider_record_id": candidate.csv_provider_record_id,
            "symbol": candidate.symbol, "financial_sha256": candidate.csv_financial_sha256,
            "file_sha256": preview.file_sha256, "csv_row_number": request.csv_row_number,
            "source_batch_id": source_batch_id, "csv_raw_object_id": source_raw_id,
            "preview_sha256": preview.preview_sha256, "source_ref": ref,
        }
        decision = self.store.add_review_decision(ReviewDecisionCreate(
            decision_type=MATCH_TYPE,
            scope=f"binance_spot:{target.connection_id}:{candidate.symbol}:{candidate.csv_provider_record_id}",
            title="Binance-Spot-CSV-Zeile und API-Fill explizit abgeglichen",
            rationale=request.rationale,
            evidence_ref=(f"file:{preview.file_sha256}#row={request.csv_row_number};"
                          f"/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/audit.json"),
            actor=request.actor, source="binance", affected_ids=[
                source_raw_id or f"csv:{preview.file_sha256}:{request.csv_row_number}",
                api_record["identity"],
            ], payload=payload,
        ))
        return decision

    def revoke(self, ref: str, decision_id: str, request: BinanceSpotMatchRevocation) -> ReviewDecision:
        with BINANCE_SPOT_IMPORT_LOCK:
            return self._revoke_locked(ref, decision_id, request)

    def _revoke_locked(self, ref: str, decision_id: str, request: BinanceSpotMatchRevocation) -> ReviewDecision:
        decisions = self.store.list_review_decisions()
        original = next((row for row in decisions if row.decision_id == decision_id
                         and row.decision_type == MATCH_TYPE
                         and row.payload.get("source_ref") == ref), None)
        if original is None:
            raise HistoryFetchError("history_match_decision_not_found", resumable=False)
        if any(row.decision_type == REVOKE_TYPE and row.payload.get("revokes_decision_id") == decision_id
               for row in decisions):
            raise HistoryFetchError("history_match_already_revoked", resumable=False)
        payload = original.payload
        source_batch_id = payload.get("source_batch_id")
        if not source_batch_id and payload.get("file_sha256") and payload.get("connection_id"):
            imported_batch = self.store.get_import_batch_by_file_hash(
                "binance", str(payload["file_sha256"]), str(payload["connection_id"]),
            )
            source_batch_id = imported_batch.batch_id if imported_batch else None
        job = self.storage.load(str(payload.get("api_job_id", "")))
        if source_batch_id and job.get("status") == "succeeded":
            raise HistoryFetchError("history_match_revoke_after_import", resumable=False)
        payload = {**payload, "action": "revoke", "revokes_decision_id": decision_id}
        return self.store.add_review_decision(ReviewDecisionCreate(
            decision_type=REVOKE_TYPE, scope=original.scope,
            title="Binance-Spot-Abgleich widerrufen",
            rationale=request.rationale, evidence_ref=original.evidence_ref,
            actor=request.actor, source="binance", affected_ids=[decision_id], payload=payload,
        ))

    def history_records_for_import(self, job: dict, target: HistoryTarget, records: list[HistoryRecord]):
        with BINANCE_SPOT_IMPORT_LOCK:
            return self._history_records_for_import_locked(job, target, records)

    def _history_records_for_import_locked(self, job: dict, target: HistoryTarget, records: list[HistoryRecord]):
        matches = {}
        revoked = {}
        for decision in self.store.list_review_decisions():
            if decision.decision_type == REVOKE_TYPE:
                revoked[decision.payload.get("revokes_decision_id")] = decision
            elif decision.decision_type == MATCH_TYPE and decision.payload.get("api_job_id") == job["id"]:
                matches[decision.decision_id] = decision
        api_by_identity = {entry.get("identity"): entry for entry in self._api_entries(target, records)}
        skip_identities, csv_raw_ids = set(), set()
        for decision_id, decision in matches.items():
            payload = decision.payload
            identity = payload.get("api_record_identity")
            if decision_id in revoked:
                raise HistoryFetchError("history_match_revoked_review_required", resumable=False)
            entry = api_by_identity.get(identity)
            if entry is None or entry.get("invalid") or entry.get("record_sha256") != payload.get("api_record_sha256"):
                raise HistoryFetchError("history_match_preview_stale", resumable=False)
            if payload.get("source_batch_id") is None or payload.get("csv_raw_object_id") is None:
                raise HistoryFetchError("history_match_csv_not_imported", resumable=False)
            source_preview = self.preview(
                str(payload.get("source_ref", "")), job["id"],
                BinanceSpotMatchPreviewRequest(batch_id=str(payload["source_batch_id"])),
            )
            if source_preview.preview_sha256 != payload.get("preview_sha256"):
                raise HistoryFetchError("history_match_preview_stale", resumable=False)
            raw_id = str(payload["csv_raw_object_id"])
            with self.store.connect() as con:
                row = con.execute(
                    """select r.payload_json,b.file_hash,b.connection_id,b.source,b.filename
                       from raw_objects r join raw_import_batches b using(batch_id)
                       where r.raw_object_id=? and r.batch_id=? and r.row_number=?""",
                    [raw_id, payload["source_batch_id"], payload["csv_row_number"]],
                ).fetchone()
            if row is None or row[2] != target.connection_id or row[3] != "binance" or row[1] != payload.get("file_sha256"):
                raise HistoryFetchError("history_match_preview_stale", resumable=False)
            raw = json.loads(row[0])
            record_id, conflict = _one_column(raw, _TRADE_ID_COLUMNS)
            symbol, symbol_conflict = _one_column(raw, _SYMBOL_COLUMNS)
            event = self._event(raw, account=target.account, filename=str(row[4] or "binance.csv"))
            if (conflict or symbol_conflict or record_id != payload.get("provider_record_id")
                    or (symbol or "").upper() != payload.get("symbol")
                    or event is None or self._financial_sha256(event) != payload.get("financial_sha256")):
                raise HistoryFetchError("history_match_preview_stale", resumable=False)
            skip_identities.add(str(identity))
            csv_raw_ids.add(raw_id)
        return [record for record in records if record.identity not in skip_identities], len(skip_identities), sorted(csv_raw_ids)

    def import_csv_if_needed(self, payload: ImportAssistantRequest) -> ImportAssistantExecuteResult | None:
        with BINANCE_SPOT_IMPORT_LOCK:
            return self._import_csv_if_needed_locked(payload)

    def _import_csv_if_needed_locked(self, payload: ImportAssistantRequest) -> ImportAssistantExecuteResult | None:
        if payload.source.strip().lower() != "binance" or payload.import_mode != "file":
            return None
        assistant = ImportAssistantService(self.store)
        preview = assistant.preview(payload)
        if not preview.can_execute or preview.preview is None or preview.preview.duplicate_batch_id:
            return None
        connection_id = str(payload.connection_id) if payload.connection_id else None
        api_rows = self._stored_api_rows(connection_id)
        if not api_rows:
            return None
        if any(item.get("invalid") for item in api_rows):
            raise ValueError("Gespeicherter Binance-API-Spotbeleg ist nicht eindeutig kontogebunden; Dateiimport bleibt gesperrt.")
        rows, file_hash, filename, file_format = self._import_rows(payload)
        if file_format != "csv":
            raise ValueError("Binance-Dateiimport mit vorhandener API-Historie ist fuer diesen Abgleich nur als CSV freigegeben.")
        if connection_id is None:
            raise ValueError("Binance-API-Historie vorhanden: Datei vor dem Import an eine konkrete Verbindung binden.")
        if preview.preview.file_sha256 != file_hash:
            raise ValueError("Binance-CSV-Vorschau ist veraltet; bitte die Datei erneut vorpruefen.")
        api_by_key: dict[tuple[str, str], list[dict]] = {}
        for item in api_rows:
            api_by_key.setdefault((item["symbol"], item["provider_id"]), []).append(item)
        decisions = self.store.list_review_decisions()
        match_decisions = [row for row in decisions if row.decision_type == MATCH_TYPE]
        revoked = {row.payload.get("revokes_decision_id") for row in decisions if row.decision_type == REVOKE_TYPE}
        used_api = set()
        csv_importer = CsvRawImporter(self.store)
        for number, row in enumerate(rows, start=1):
            if csv_importer._is_ignorable_row("binance", row):
                continue
            provider_id, id_conflict = _one_column(row, _TRADE_ID_COLUMNS)
            symbol, symbol_conflict = _one_column(row, _SYMBOL_COLUMNS)
            key = (symbol.upper(), provider_id) if symbol and provider_id and not symbol_conflict and not id_conflict else None
            api_matches = api_by_key.get(key, []) if key else []
            raw_event = self._raw_event(row, account="connection:" + connection_id, filename=filename)
            is_trade = raw_event is not None and raw_event.event_type == "trade"
            if not provider_id or id_conflict or not symbol or symbol_conflict:
                if is_trade:
                    raise ValueError("Binance-API-Spot-Historie ueberschneidet eine Tradezeile ohne eindeutige Trade-ID/Symbol; Import bleibt gesperrt.")
                continue
            if not api_matches:
                continue
            if raw_event is None or raw_event.event_type != "trade":
                raise ValueError("Binance-CSV/API-Trade-ID und Symbol stimmen, aber die CSV-Finanzform ist nicht eindeutig als Spot-Trade belegbar. Import bleibt gesperrt.")
            event = self._event(row, account="connection:" + connection_id, filename=filename)
            if event is None:
                raise ValueError("Binance-CSV/API-Trade ist wegen fehlender Gegenmenge oder Gebuehrenwaehrung nicht exakt abgleichbar. Import bleibt gesperrt.")
            if len(api_matches) != 1:
                raise ValueError("Binance-API-Spot-Trade-ID ist innerhalb der Verbindung mehrdeutig; Import bleibt gesperrt.")
            api = api_matches[0]
            csv_digest = self._financial_sha256(event)
            if api["financial_sha256"] is None or api["financial_sha256"] != csv_digest:
                raise ValueError("Binance-CSV/API-Trade-ID stimmt, Finanzdigest aber nicht. Kein Match; Originalbelege pruefen.")
            if api["identity"] in used_api:
                raise ValueError("Binance-CSV enthaelt dieselbe API-Trade-ID mehrfach; Import bleibt gesperrt.")
            used_api.add(api["identity"])
            decisions_for_pair = [decision for decision in match_decisions
                                  if decision.payload.get("connection_id") == connection_id
                                  and decision.payload.get("file_sha256") == file_hash
                                  and decision.payload.get("csv_row_number") == number
                                  and decision.payload.get("api_record_identity") == api["identity"]]
            if not decisions_for_pair:
                raise ValueError("Exakter Binance-Spot-Overlap erkannt. Vor dem Import ist eine ausdrueckliche CSV/API-Abgleichentscheidung erforderlich.")
            decision = decisions_for_pair[0]
            if decision.decision_id in revoked:
                raise ValueError("Binance-Spot-Match wurde widerrufen; der Import bleibt bis zur Pruefung gesperrt.")
            details = decision.payload
            if (details.get("api_payload_sha256") != api["payload_sha256"]
                    or details.get("financial_sha256") != csv_digest
                    or details.get("provider_record_id") != provider_id
                    or details.get("symbol") != symbol.upper()):
                raise ValueError("Binance-Spot-Match ist veraltet; bitte erneut vorpruefen und pruefen.")
            row.update({
                "history_evidence_only": "1",
                "history_scope_identity": api["scope_identity"],
                "history_payload_sha256": api["payload_sha256"],
                "history_record_id": api["identity"],
                "history_source_ref": details.get("source_ref", ""),
            })
        imported = CsvRawImporter(self.store).import_rows(
            source="binance", filename=filename, file_hash=file_hash, rows=rows,
            connection_id=connection_id,
            allow_binance_history_overlap=True,
        )
        run = PipelineService(self.store).rebuild_after_import(imported.batch_id)
        return ImportAssistantExecuteResult(preview=preview, batch=imported, run=run)

    def _import_rows(self, payload: ImportAssistantRequest):
        importer = CsvRawImporter(self.store)
        if payload.content_base64 is not None:
            content = base64.b64decode(payload.content_base64, validate=True)
            file = FileRawImporter(importer)
            rows, _columns, file_format, sheet, _sheet_names = file._rows_from_bytes(
                payload.filename or "binance.csv", content, payload.sheet_name, "binance",
            )
            if sheet is not None:
                raise ValueError("Binance-Spot-Abgleich unterstuetzt nur ein einzelnes CSV, keine Tabellenblaetter.")
            file_hash = file._file_hash(content, None)
            filename = payload.filename or "binance.csv"
        elif payload.content is not None:
            rows = [importer._stringify_row(row) for row in importer._dict_reader(payload.content, "binance")]
            file_hash = importer.hash_text(payload.content)
            file_format = "csv"
            filename = payload.filename or "binance.csv"
        else:
            raise ValueError("Binance-CSV-Inhalt fehlt.")
        rows = [importer._stringify_row(row) for row in rows]
        return rows, file_hash, filename, file_format

    def _stored_api_rows(self, connection_id: str | None):
        params: list[object] = []
        where = "lower(b.source)='binance' and coalesce(json_extract_string(r.payload_json, '$.history_scope_identity'),'')<>''"
        if connection_id is not None:
            where += " and b.connection_id=?"
            params.append(connection_id)
        with self.store.connect() as con:
            rows = con.execute(
                f"""select r.payload_json,b.connection_id from raw_objects r
                    join raw_import_batches b using(batch_id) where {where}""", params,
            ).fetchall()
        result = []
        for payload_json, batch_connection in rows:
            raw = json.loads(payload_json)
            try:
                api_raw = json.loads(raw.get("raw_history_record") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            api_payload = api_raw.get("payload") if isinstance(api_raw, dict) else None
            if api_raw.get("endpoint") != "/api/v3/myTrades":
                continue
            if (not isinstance(api_payload, dict) or not raw.get("history_record_id")
                    or not raw.get("history_payload_sha256")):
                result.append({"invalid": True, "connection_id": str(batch_connection)})
                continue
            provider_id, symbol = api_payload.get("id"), api_payload.get("symbol")
            if isinstance(provider_id, bool) or not isinstance(provider_id, (int, str)) or not isinstance(symbol, str):
                result.append({"invalid": True, "connection_id": str(batch_connection)})
                continue
            expected_identity = "cex:" + json.dumps(
                ["binance", "connection:" + str(batch_connection), "/api/v3/myTrades",
                 symbol.strip().upper(), str(provider_id).strip()],
                ensure_ascii=True, separators=(",", ":"),
            )
            event = self._event(raw, account="connection:" + str(batch_connection), filename="api-history-utc.csv")
            if raw["history_record_id"] != expected_identity or event is None:
                result.append({"invalid": True, "connection_id": str(batch_connection)})
                continue
            result.append({
                "identity": raw["history_record_id"], "scope_identity": raw["history_scope_identity"],
                "payload_sha256": raw["history_payload_sha256"],
                "provider_id": str(provider_id).strip(), "symbol": symbol.strip().upper(),
                "financial_sha256": self._financial_sha256(event) if event else None,
                "connection_id": str(batch_connection),
            })
        return result

    def has_stored_spot_history(self, connection_id: str) -> bool:
        with BINANCE_SPOT_IMPORT_LOCK:
            return bool(self._stored_api_rows(connection_id))
