"""Idempotenter Import freigegebener, kontogebundener API-Belege."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.history_types import HistoryRecord, HistoryTarget
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.solana_history_identity import SolanaHistoryConflict, new_transaction_rows


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def record_digest(record: HistoryRecord) -> str:
    # Discovery/budget/window metadata is evidence, not a new financial event.
    # The full record is archived separately; the transaction payload stays bound.
    raw = record.raw.get("transaction") if record.source == "solana_rpc" else record.raw.get("payload", record.raw)
    value = {**asdict(record), "raw": raw}
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def scope_identity(target: HistoryTarget, record: HistoryRecord) -> str:
    return hashlib.sha256(canonical_json([target.provider, target.account, record.identity]).encode()).hexdigest()


def prepare_records(store: DuckDbStore, target: HistoryTarget, records: list[HistoryRecord]):
    """Returns only new complete records; conflicting originals never get replaced."""
    identities = {scope_identity(target, record): record for record in records}
    existing: dict[str, set[str]] = {}
    with store.connect() as con:
        for offset in range(0, len(identities), 1000):
            rows = con.execute(
                """
                select distinct json_extract_string(r.payload_json, '$.history_scope_identity'),
                                json_extract_string(r.payload_json, '$.history_payload_sha256'), b.status
                from raw_objects r join raw_import_batches b on b.batch_id=r.batch_id
                where json_extract_string(r.payload_json, '$.history_scope_identity') in (select unnest(?))
                """, [list(identities)[offset:offset + 1000]],
            ).fetchall()
            for identity, payload_hash, status in rows:
                if status != "normalized":
                    raise SolanaHistoryConflict("history_previous_import_incomplete")
                existing.setdefault(identity, set()).add(payload_hash)
    accepted: list[HistoryRecord] = []
    duplicates = 0
    for identity, record in identities.items():
        digest = record_digest(record)
        if identity in existing:
            if existing[identity] != {digest}:
                raise SolanaHistoryConflict("history_existing_evidence_conflict")
            duplicates += 1
            continue
        if target.provider == "solana" and record.rows:
            # Also guard imports performed by the pre-existing rc20 API path.
            new_rows, count, _batch = new_transaction_rows(store, target.account, record.rows)
            if count:
                duplicates += 1
                continue
            if new_rows != record.rows:
                raise SolanaHistoryConflict("history_existing_evidence_conflict")
        accepted.append(record)
    return accepted, duplicates


def import_records(store: DuckDbStore, target: HistoryTarget, records: list[HistoryRecord], job_id: str):
    batches = []
    for source in sorted({record.source for record in records}):
        rows: list[dict[str, object]] = []
        for record in records:
            if record.source != source:
                continue
            metadata = {
                "history_scope_identity": scope_identity(target, record),
                "history_payload_sha256": record_digest(record),
                "history_record_id": record.identity,
                "history_source_ref": target.source_ref,
                "raw_history_record": canonical_json(record.raw),
            }
            for row in record.rows:
                # No caller-controlled account may redirect a selected connection.
                expected = row.get("wallet_address") if target.provider == "solana" else row.get("account")
                if expected != target.account:
                    raise ValueError("history_record_account_mismatch")
                rows.append({**row, **metadata})
            if not record.rows:
                rows.append({**metadata, "history_evidence_only": "1", "quantity": "0", "account": target.account})
        content_hash = "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest()
        batches.append(CsvRawImporter(store).import_rows(
            source=source, filename=f"automatic-history-{job_id}-{source}.json",
            file_hash=content_hash, rows=rows, connection_id=target.connection_id,
        ))
    return batches
