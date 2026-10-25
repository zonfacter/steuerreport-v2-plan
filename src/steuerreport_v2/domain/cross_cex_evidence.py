from __future__ import annotations

from steuerreport_v2.private_settings import private_config_path

import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from uuid import UUID

from steuerreport_v2.contracts.cross_cex_evidence import (
    CrossCexTransferDecisionLayer,
    CrossCexTransferEvidenceRecord,
    CrossCexTransferEvidenceReport,
)
from steuerreport_v2.contracts.source_registry import SourceRegistryConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_time import reporting_tax_year


class CrossCexTransferEvidenceService:
    DEFAULT_CONFIG_PATH = private_config_path('source_registry.json')
    DEFAULT_LATEST_RUN_PATH = Path(
        "/workspace/steuerreport-v2-plan/var/wallet_fifo_runs/latest_wallet_fifo_run.json"
    )
    EVIDENCE_ENDPOINT = "/api/v1/tax/cross-cex-transfer-evidence"

    def __init__(
        self,
        store: DuckDbStore,
        *,
        config_path: Path | None = None,
        latest_run_path: Path | None = None,
    ) -> None:
        self.store = store
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.latest_run_path = latest_run_path or self.DEFAULT_LATEST_RUN_PATH

    def report(self) -> CrossCexTransferEvidenceReport:
        methodology = (
            "SHA- und Event-gebundener Nachweis eigener Cross-CEX-Transfers. "
            "Der Service verknuepft CEX-Withdrawal-Originalzeile, Ziel-TXID, "
            "Menge, Same-Asset-Gebuehr, Zeitfenster und den aktuellen "
            "Wallet-FIFO-Lot-Carry. Es wird weder ein Verkauf noch Einkommen "
            "erzeugt; produktive Imports, Lots, Tax-Lines und Ledger bleiben "
            "unveraendert."
        )
        errors: list[str] = []
        try:
            config = SourceRegistryConfig.model_validate_json(
                self.config_path.read_text(encoding="utf-8")
            )
            run_payload = json.loads(
                self.latest_run_path.read_text(encoding="utf-8")
            )
            trace_meta = next(
                item
                for item in run_payload.get("evidence_files", [])
                if item.get("kind") == "wallet_fifo_transfer_traces"
            )
            trace_path = self._resolve_path(str(trace_meta["path"]))
            trace_sha = self._sha256(trace_path)
            if trace_sha != str(trace_meta.get("sha256") or ""):
                errors.append("transfer_trace_sha256_mismatch")
            with gzip.open(trace_path, "rt", encoding="utf-8", newline="") as handle:
                traces = list(csv.DictReader(handle))
        except (OSError, ValueError, StopIteration, TypeError, json.JSONDecodeError) as exc:
            return self._error_report(methodology, f"evidence_load_failed:{exc}")

        entries_by_id = {entry.source_id: entry for entry in config.entries}
        traces_by_tx_id: dict[str, list[dict[str, str]]] = {}
        for row in traces:
            traces_by_tx_id.setdefault(str(row.get("tx_id") or ""), []).append(row)
        approvals = [
            evidence
            for evidence in config.transfer_evidence
            if self.EVIDENCE_ENDPOINT in evidence.evidence_refs
            or any(
                "662_DETERMINISTIC_EVENT_IDS_AND_CROSS_CEX_TRANSFER_CLOSURE"
                in reference
                for reference in evidence.evidence_refs
            )
        ]
        records: list[CrossCexTransferEvidenceRecord] = []
        for evidence in approvals:
            trace = self._select_trace(traces_by_tx_id.get(evidence.tx_id, []), evidence)
            if trace is None:
                errors.append(f"trace_missing:{evidence.evidence_id}")
                continue
            source = self._event_evidence(str(trace.get("source_event_id") or ""))
            target = self._event_evidence(str(trace.get("target_event_id") or ""))
            if source is None or target is None:
                errors.append(f"event_binding_missing:{evidence.evidence_id}")
                continue
            source_entry = entries_by_id.get(evidence.source_id)
            target_entry = entries_by_id.get(evidence.target_source_id)
            explicit_fee = (
                abs(source["fee_quantity"])
                if str(source["fee_asset"] or "").upper()
                == str(source["asset"]).upper()
                else Decimal("0")
            )
            calculated_fee = abs(source["quantity"]) + explicit_fee - target["quantity"]
            source_operation = str(
                source["payload"].get("Operation")
                or source["payload"].get("Action")
                or source["payload"].get("Type")
                or ""
            ).strip().lower()
            source_time = self._as_utc(source["event_time"])
            target_time = self._as_utc(target["event_time"])
            time_delta = abs(
                Decimal(str((target_time - source_time).total_seconds()))
            )
            decision = CrossCexTransferDecisionLayer(
                registry_approval_present=evidence.evidence_status
                == "approved_complete",
                source_and_target_owned=bool(
                    source_entry
                    and target_entry
                    and source_entry.ownership
                    in {"owned", "owned_historical_route"}
                    and target_entry.ownership
                    in {"owned", "owned_historical_route"}
                ),
                source_withdrawal_log_bound=source_operation
                in {"withdraw", "withdrawal"},
                target_transaction_id_bound=str(target["tx_id"] or "")
                == evidence.tx_id,
                source_and_target_raw_hashes_bound=bool(
                    source["file_hash"] and target["file_hash"]
                ),
                deterministic_event_ids_bound=self._is_uuid5(source["event_id"])
                and self._is_uuid5(target["event_id"]),
                time_window_reconciles=time_delta <= Decimal("600"),
                quantity_and_fee_reconcile=bool(
                    str(source["asset"]).upper() == evidence.asset.upper()
                    and str(target["asset"]).upper() == evidence.asset.upper()
                    and target["quantity"] == evidence.quantity
                    and calculated_fee == evidence.fee_quantity
                    and Decimal(str(trace.get("quantity") or "0"))
                    == evidence.quantity
                    and Decimal(str(trace.get("fee_quantity") or "0"))
                    == evidence.fee_quantity
                ),
                wallet_fifo_lot_carry_complete=bool(
                    str(trace.get("status") or "")
                    == "cross_cex_transfer_evidence_complete"
                    and int(trace.get("lots_moved") or 0) > 0
                ),
            )
            ready = all(decision.model_dump().values())
            records.append(
                CrossCexTransferEvidenceRecord(
                    evidence_id=evidence.evidence_id,
                    year=reporting_tax_year(target_time),
                    tx_id=evidence.tx_id,
                    asset=evidence.asset,
                    quantity=evidence.quantity,
                    fee_quantity=evidence.fee_quantity,
                    source_id=evidence.source_id,
                    target_source_id=evidence.target_source_id,
                    source_pool_id=str(trace.get("source_pool_id") or ""),
                    target_pool_id=str(trace.get("target_pool_id") or ""),
                    source_event_id=source["event_id"],
                    target_event_id=target["event_id"],
                    source_event_time=source_time,
                    target_event_time=target_time,
                    time_delta_seconds=time_delta,
                    source_filename=source["filename"],
                    source_file_hash=source["file_hash"],
                    source_row_number=source["row_number"],
                    target_filename=target["filename"],
                    target_file_hash=target["file_hash"],
                    target_row_number=target["row_number"],
                    lots_moved=int(trace.get("lots_moved") or 0),
                    carried_cost_basis_eur=Decimal(
                        str(trace.get("carried_cost_basis_eur") or "0")
                    ),
                    status=("ready" if ready else "review_required"),
                    ready=ready,
                    decision_layer=decision,
                    evidence_refs=evidence.evidence_refs,
                )
            )
        ready_count = sum(record.ready for record in records)
        strict_ready = bool(
            approvals
            and len(records) == len(approvals)
            and ready_count == len(records)
            and not errors
        )
        semantic_sha = self._semantic_sha(records)
        return CrossCexTransferEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            status="ready" if strict_ready else "review_required",
            strict_ready=strict_ready,
            config_path=str(self.config_path),
            latest_wallet_fifo_run_path=str(self.latest_run_path),
            source_run_id=str(run_payload.get("run_id") or "") or None,
            source_run_semantic_sha256=str(
                run_payload.get("semantic_sha256") or ""
            )
            or None,
            transfer_trace_sha256=trace_sha,
            records_count=len(approvals),
            ready_count=ready_count,
            review_count=len(approvals) - ready_count,
            years=sorted({record.year for record in records}),
            records=records,
            errors=errors,
            semantic_sha256=semantic_sha,
            methodology=methodology,
        )

    @staticmethod
    def _select_trace(
        traces: list[dict[str, str]],
        evidence: object,
    ) -> dict[str, str] | None:
        asset = str(getattr(evidence, "asset", "")).upper()
        quantity = Decimal(str(getattr(evidence, "quantity", "0")))
        fee_quantity = Decimal(str(getattr(evidence, "fee_quantity", "0")))
        exact = [
            trace
            for trace in traces
            if str(trace.get("asset") or "").upper() == asset
            and Decimal(str(trace.get("quantity") or "0")) == quantity
            and Decimal(str(trace.get("fee_quantity") or "0")) == fee_quantity
        ]
        complete = [
            trace
            for trace in exact
            if trace.get("status") == "cross_cex_transfer_evidence_complete"
        ]
        if len(complete) == 1:
            return complete[0]
        if len(exact) == 1:
            return exact[0]
        if len(traces) == 1:
            return traces[0]
        return None

    def _event_evidence(self, event_id: str) -> dict[str, object] | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select e.event_id, e.event_time, e.asset, e.quantity,
                       e.fee_asset, e.fee_quantity, e.tx_id,
                       r.row_number, r.payload_json, b.filename, b.file_hash
                from canonical_events e
                join raw_objects r using(raw_object_id)
                join raw_import_batches b using(batch_id)
                where e.event_id = ?
                """,
                [event_id],
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[8]))
        return {
            "event_id": str(row[0]),
            "event_time": row[1],
            "asset": str(row[2]),
            "quantity": Decimal(str(row[3])),
            "fee_asset": row[4],
            "fee_quantity": Decimal(str(row[5] or 0)),
            "tx_id": row[6],
            "row_number": int(row[7]) if row[7] is not None else None,
            "payload": payload if isinstance(payload, dict) else {},
            "filename": str(row[9]),
            "file_hash": str(row[10]),
        }

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.latest_run_path.parents[2] / path

    @staticmethod
    def _is_uuid5(value: object) -> bool:
        try:
            return UUID(str(value)).version == 5
        except ValueError:
            return False

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _semantic_sha(records: list[CrossCexTransferEvidenceRecord]) -> str:
        payload = [record.model_dump(mode="json") for record in records]
        for record in payload:
            record.pop("status", None)
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()

    def _error_report(
        self, methodology: str, error: str
    ) -> CrossCexTransferEvidenceReport:
        return CrossCexTransferEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            status="not_available",
            config_path=str(self.config_path),
            latest_wallet_fifo_run_path=str(self.latest_run_path),
            errors=[error],
            semantic_sha256=hashlib.sha256(b"[]").hexdigest(),
            methodology=methodology,
        )
