from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any
import zipfile

from steuerreport_v2.contracts.bitget_strategy_fifo import (
    BitgetStrategyApiHistoryBoundary,
    BitgetStrategyAssetTotals,
    BitgetStrategyFifoGapReport,
    BitgetStrategyLinkedDisposal,
    BitgetStrategyReferenceEvidence,
    BitgetStrategySettlementGap,
    BitgetSupportFileEvidence,
    BitgetSupportPackageAudit,
    BitgetSupportStrategyMatch,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.paths import configured_import_path


class BitgetStrategyFifoGapService:
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/wallet_fifo_runs"
    DEFAULT_BLOCKPIT_REFERENCE_PATH = configured_import_path("blockpit_reference_file", "blockpit/transactions.csv")
    DEFAULT_SUPPORT_PACKAGE_ROOT = configured_import_path("bitget_support_root", "bitget/support")
    SUPPORT_FILES = {
        "Deposit-Withdrawal History.csv": ("transfer_evidence", False, False),
        "Spot Financial Record.csv": ("spot_balance_ledger", True, False),
        "Spot Trading History.csv": ("spot_execution_evidence", False, True),
        "Futures Financial Record.csv": (
            "derivative_cashflow_ledger",
            True,
            False,
        ),
        "Futures Trading History.csv": (
            "derivative_execution_evidence",
            False,
            True,
        ),
        "Strategy.csv": ("strategy_summary_evidence", False, False),
    }
    CLASSIC_SPOT_HISTORY_ENDPOINT = "/api/v2/spot/trade/history-orders"
    UTA_HISTORY_ENDPOINT = "/api/v3/trade/history-orders"
    CLASSIC_SPOT_HISTORY_DOC = (
        "https://www.bitget.com/api-doc/classic/spot/trade/Get-History-Orders"
    )
    UTA_HISTORY_DOC = "https://www.bitget.com/api-doc/uta/trade/Get-Order-History"
    DUST_TOLERANCES = {
        "BTC": Decimal("0.000001"),
        "HNT": Decimal("0.01"),
        "SOL": Decimal("0.001"),
    }
    DEFAULT_DUST_TOLERANCE = Decimal("0.00000001")

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
        blockpit_reference_path: Path | None = None,
        support_package_root: Path | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or (
            self.DEFAULT_ARTIFACT_ROOT
            if self.store.path.resolve() == self.DEFAULT_DB.resolve()
            else self.store.path.parent / "var/wallet_fifo_runs"
        )
        self.blockpit_reference_path = (
            blockpit_reference_path or self.DEFAULT_BLOCKPIT_REFERENCE_PATH
        )
        self.support_package_root = support_package_root or (
            self.DEFAULT_SUPPORT_PACKAGE_ROOT
            if self.store.path.resolve() == self.DEFAULT_DB.resolve()
            else self.store.path.parent / "bitget-support"
        )

    def report(self, *, run_id: str | None = None) -> BitgetStrategyFifoGapReport | None:
        run_payload = self._run_payload(run_id)
        if run_payload is None:
            return None
        evidence_by_kind = {
            str(item.get("kind") or ""): item
            for item in run_payload.get("evidence_files", [])
            if isinstance(item, dict)
        }
        stored = evidence_by_kind.get("bitget_strategy_fifo_gap_report")
        if stored is not None:
            path = self._resolve_path(str(stored.get("path") or ""))
            try:
                if self._sha256(path) == str(stored.get("sha256") or ""):
                    return BitgetStrategyFifoGapReport.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
            except (OSError, ValueError):
                pass
        unmatched = evidence_by_kind.get("wallet_fifo_unmatched")
        traces = evidence_by_kind.get("wallet_fifo_transfer_traces")
        if unmatched is None or traces is None:
            return self._error_report(
                run_id=str(run_payload.get("run_id") or "unknown"),
                generated_at=datetime.now(timezone.utc),
                as_of=self._datetime(run_payload.get("as_of")),
                input_digest=str(
                    (run_payload.get("input_fingerprint") or {}).get("digest") or ""
                ),
                errors=["wallet_fifo_evidence_files_missing"],
            )
        return self.build_from_evidence(
            run_id=str(run_payload.get("run_id") or "unknown"),
            generated_at=self._datetime(run_payload.get("generated_at")),
            as_of=self._datetime(run_payload.get("as_of")),
            input_digest=str(
                (run_payload.get("input_fingerprint") or {}).get("digest") or ""
            ),
            unmatched_path=self._resolve_path(str(unmatched.get("path") or "")),
            transfer_traces_path=self._resolve_path(str(traces.get("path") or "")),
            expected_unmatched_sha256=str(unmatched.get("sha256") or ""),
            expected_transfer_traces_sha256=str(traces.get("sha256") or ""),
        )

    def build_from_evidence(
        self,
        *,
        run_id: str,
        generated_at: datetime,
        as_of: datetime,
        input_digest: str,
        unmatched_path: Path,
        transfer_traces_path: Path,
        expected_unmatched_sha256: str | None = None,
        expected_transfer_traces_sha256: str | None = None,
    ) -> BitgetStrategyFifoGapReport:
        errors: list[str] = []
        if expected_unmatched_sha256 and self._sha256(unmatched_path) != expected_unmatched_sha256:
            errors.append("wallet_fifo_unmatched_sha256_mismatch")
        if (
            expected_transfer_traces_sha256
            and self._sha256(transfer_traces_path) != expected_transfer_traces_sha256
        ):
            errors.append("wallet_fifo_transfer_traces_sha256_mismatch")
        try:
            unmatched_rows = self._gzip_csv_rows(unmatched_path)
            trace_rows = self._gzip_csv_rows(transfer_traces_path)
        except OSError as exc:
            errors.append(f"wallet_fifo_evidence_read_failed:{exc}")
            return self._error_report(
                run_id=run_id,
                generated_at=generated_at,
                as_of=as_of,
                input_digest=input_digest,
                errors=errors,
            )

        all_bitget_unmatched = [
            row
            for row in unmatched_rows
            if str(row.get("pool_id") or "").lower().startswith("bitget:")
            and self._decimal(row.get("missing_quantity")) > 0
        ]
        inbound_traces = [
            row
            for row in trace_rows
            if str(row.get("source_pool_id") or "").lower().startswith("bitget:")
            and str(row.get("direction") or "").lower() == "inbound"
            and str(row.get("evidence_operation") or "").upper()
            == "STRATEGY_TRANSFER_IN"
        ]
        outbound_traces = [
            row
            for row in trace_rows
            if str(row.get("source_pool_id") or "").lower().startswith("bitget:")
            and str(row.get("direction") or "").lower() == "outbound"
            and str(row.get("evidence_operation") or "").upper()
            == "STRATEGY_TRANSFER_OUT"
        ]
        bitget_unmatched = [
            row
            for row in all_bitget_unmatched
            if any(
                str(trace.get("asset") or "").upper()
                == str(row.get("asset") or "").upper()
                and self._datetime(trace.get("event_time"))
                <= self._datetime(row.get("event_time"))
                for trace in inbound_traces
            )
        ]
        out_of_scope_unmatched_count = len(all_bitget_unmatched) - len(bitget_unmatched)
        raw_ids = {
            str(row.get("evidence_raw_object_id") or "")
            for row in inbound_traces + outbound_traces
            if row.get("evidence_raw_object_id")
        }
        unmatched_event_ids = {
            str(row.get("source_event_id") or "") for row in bitget_unmatched
        }
        raw_evidence = self._raw_evidence(raw_ids)
        disposal_evidence = self._event_evidence(unmatched_event_ids)
        blockpit_rows, blockpit_sha = self._blockpit_rows()

        candidates: list[dict[str, Any]] = []
        for row in sorted(inbound_traces, key=lambda item: self._datetime(item.get("event_time"))):
            asset = str(row.get("asset") or "").upper()
            event_at = self._datetime(row.get("event_time"))
            quantity = self._decimal(row.get("quantity"))
            previous_out = self._previous_outbound(
                outbound_traces,
                asset=asset,
                before=event_at,
            )
            supported_principal = Decimal("0")
            if previous_out is not None:
                supported_principal = min(
                    quantity,
                    self._decimal(previous_out.get("basis_covered_quantity")),
                )
            strategy_gap = max(quantity - supported_principal, Decimal("0"))
            candidates.append(
                {
                    "row": row,
                    "asset": asset,
                    "at": event_at,
                    "quantity": quantity,
                    "previous_out": previous_out,
                    "supported_principal": supported_principal,
                    "strategy_gap": strategy_gap,
                    "remaining": strategy_gap,
                    "allocations": [],
                }
            )

        unallocated: list[BitgetStrategyLinkedDisposal] = []
        for unmatched in sorted(
            bitget_unmatched,
            key=lambda item: self._datetime(item.get("event_time")),
        ):
            missing = self._decimal(unmatched.get("missing_quantity"))
            remaining = missing
            event_at = self._datetime(unmatched.get("event_time"))
            asset = str(unmatched.get("asset") or "").upper()
            eligible = [
                item
                for item in candidates
                if item["asset"] == asset
                and item["at"] <= event_at
                and item["remaining"] > 0
            ]
            for candidate in reversed(eligible):
                if remaining <= 0:
                    break
                allocated = min(remaining, candidate["remaining"])
                candidate["allocations"].append((unmatched, allocated))
                candidate["remaining"] -= allocated
                remaining -= allocated
            if remaining > 0:
                unallocated.append(
                    self._linked_disposal(
                        unmatched,
                        settlement_group_id="unallocated",
                        allocated=missing - remaining,
                        evidence=disposal_evidence.get(
                            str(unmatched.get("source_event_id") or "")
                        ),
                    )
                )

        groups: list[BitgetStrategySettlementGap] = []
        for candidate in candidates:
            if not candidate["allocations"]:
                continue
            row = candidate["row"]
            event_id = str(row.get("source_event_id") or "")
            group_id = f"bitget-strategy:{event_id}"
            evidence = raw_evidence.get(
                str(row.get("evidence_raw_object_id") or "")
            )
            linked = [
                self._linked_disposal(
                    unmatched,
                    settlement_group_id=group_id,
                    allocated=allocated,
                    evidence=disposal_evidence.get(
                        str(unmatched.get("source_event_id") or "")
                    ),
                )
                for unmatched, allocated in candidate["allocations"]
            ]
            allocated_total = sum(
                (item.allocated_strategy_gap_quantity for item in linked),
                Decimal("0"),
            )
            residual = candidate["strategy_gap"] - allocated_total
            dust_tolerance = self.DUST_TOLERANCES.get(
                candidate["asset"], self.DEFAULT_DUST_TOLERANCE
            )
            quantity_reconciled = Decimal("0") <= residual <= dust_tolerance
            transaction_id = self._transaction_id(row)
            blockpit_reference = self._blockpit_reference(
                transaction_id,
                blockpit_rows=blockpit_rows,
                blockpit_sha=blockpit_sha,
                source_operation=str(row.get("evidence_operation") or ""),
            )
            previous_out = candidate["previous_out"]
            payload = evidence.get("payload", {}) if evidence else {}
            settlement_ref = self._optional_decimal(payload.get("Amount (USDT)"))
            evidence_refs = [
                (
                    f"{evidence.get('filename')}:{evidence.get('row_number')}"
                    if evidence
                    else f"wallet_fifo_transfer_trace:{event_id}"
                ),
                *(
                    [
                        f"{self.blockpit_reference_path}:{blockpit_reference.row_number}"
                    ]
                    if blockpit_reference.available
                    else []
                ),
            ]
            groups.append(
                BitgetStrategySettlementGap(
                    settlement_group_id=group_id,
                    year=reporting_tax_year(candidate["at"]),
                    asset=candidate["asset"],
                    pool_id=str(row.get("source_pool_id") or ""),
                    settlement_event_id=event_id,
                    settlement_transaction_id=transaction_id,
                    settlement_at=candidate["at"],
                    settlement_quantity=candidate["quantity"],
                    settlement_reference_value_usdt=settlement_ref,
                    preview_basis_covered_at_settlement=self._decimal(
                        row.get("basis_covered_quantity")
                    ),
                    preview_basis_missing_at_settlement=self._decimal(
                        row.get("basis_missing_quantity")
                    ),
                    predecessor_strategy_out_event_id=(
                        str(previous_out.get("source_event_id") or "")
                        if previous_out
                        else None
                    ),
                    predecessor_strategy_out_transaction_id=(
                        self._transaction_id(previous_out) if previous_out else None
                    ),
                    predecessor_strategy_out_at=(
                        self._datetime(previous_out.get("event_time"))
                        if previous_out
                        else None
                    ),
                    predecessor_strategy_out_quantity=(
                        self._decimal(previous_out.get("quantity"))
                        if previous_out
                        else Decimal("0")
                    ),
                    supported_principal_carried_quantity=candidate[
                        "supported_principal"
                    ],
                    strategy_quantity_without_cost_basis=candidate["strategy_gap"],
                    linked_disposals_count=len(linked),
                    linked_disposal_quantity=sum(
                        (item.disposal_quantity for item in linked), Decimal("0")
                    ),
                    linked_matched_wallet_lot_quantity=sum(
                        (item.matched_wallet_lot_quantity for item in linked),
                        Decimal("0"),
                    ),
                    allocated_missing_quantity=allocated_total,
                    residual_quantity=residual,
                    dust_tolerance_quantity=dust_tolerance,
                    quantity_reconciled=quantity_reconciled,
                    quantity_equation=(
                        f"{candidate['strategy_gap']} = {allocated_total} + {residual} "
                        f"{candidate['asset']}"
                    ),
                    settlement_raw_object_id=(
                        str(evidence.get("raw_object_id")) if evidence else None
                    ),
                    settlement_batch_id=(
                        str(evidence.get("batch_id")) if evidence else None
                    ),
                    settlement_filename=(
                        str(evidence.get("filename")) if evidence else None
                    ),
                    settlement_file_hash=(
                        str(evidence.get("file_hash")) if evidence else None
                    ),
                    settlement_row_number=(
                        int(evidence["row_number"])
                        if evidence and evidence.get("row_number") is not None
                        else None
                    ),
                    settlement_raw_payload_sha256=(
                        str(evidence.get("payload_sha256")) if evidence else None
                    ),
                    blockpit_reference=blockpit_reference,
                    linked_disposals=linked,
                    evidence_refs=evidence_refs,
                )
            )

        support_package = self._support_package(groups)
        support_matches = {
            item.settlement_group_id: item
            for item in support_package.relevant_strategy_matches
        }
        strategy_file = next(
            (
                item
                for item in support_package.files
                if item.filename == "Strategy.csv"
            ),
            None,
        )
        groups = [
            group.model_copy(
                update={
                    "basis_gap_responsibility": (
                        "provider_export_field_gap"
                        if support_package.provider_export_field_gap
                        else "support_package_incomplete"
                    ),
                    "support_strategy_match": support_matches.get(
                        group.settlement_group_id
                    ),
                    "evidence_refs": [
                        *group.evidence_refs,
                        *(
                            [
                                f"{strategy_file.path}:"
                                f"{support_matches[group.settlement_group_id].strategy_row_number}"
                            ]
                            if strategy_file
                            and group.settlement_group_id in support_matches
                            else []
                        ),
                    ],
                }
            )
            for group in groups
        ]
        linked_count = sum(item.linked_disposals_count for item in groups)
        quantity_reconciled = bool(groups) and not unallocated and all(
            item.quantity_reconciled for item in groups
        )
        if errors:
            status = "evidence_error"
        elif not bitget_unmatched:
            status = "no_gap"
        elif quantity_reconciled:
            status = "quantity_reconciled_basis_pending"
        else:
            status = "blocked_unallocated_quantity"
        findings = self._findings(
            groups=groups,
            unmatched_count=len(bitget_unmatched),
            linked_count=linked_count,
            unallocated_count=len(unallocated),
            out_of_scope_unmatched_count=out_of_scope_unmatched_count,
            errors=errors,
            support_package=support_package,
        )
        next_actions = []
        if groups:
            if support_package.package_complete:
                next_actions.append(
                    "Keine weiteren Bitget-Dateien vom Nutzer anfordern: Das vollstaendige "
                    "Supportpaket ist hashgebunden abgelegt."
                )
                next_actions.append(
                    "Die anbieterbedingte Fill-Feldluecke in einer konservativen "
                    "Rekonstruktionsakte dokumentieren; keine exakten Bot-Fills erfinden."
                )
            else:
                next_actions.append(
                    "Die im Supportpaket-Audit als fehlend ausgewiesenen Bitget-Dateien "
                    "beifuegen."
                )
            next_actions.append(
                "Eine rekonstruierte Anschaffungszeit- und Kostenbasis erst nach "
                "fachlicher Methodenfreigabe in die Steuer-FIFO uebernehmen."
            )
        if unallocated:
            next_actions.insert(
                0,
                "Nicht zugeordnete Bitget-Abgangsmengen gegen weitere Originalexports pruefen.",
            )
        api_boundary = self._api_boundary(support_package)
        semantic_payload = {
            "as_of": self._utc(as_of).isoformat(),
            "input_digest": input_digest,
            "status": status,
            "quantity_reconciled": quantity_reconciled,
            "groups": [self._semantic_group(item) for item in groups],
            "support_package": self._semantic_support_package(support_package),
            "unallocated": [
                item.model_dump(mode="json") for item in unallocated
            ],
            "api_history_boundary": api_boundary.model_dump(mode="json"),
            "errors": errors,
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return BitgetStrategyFifoGapReport(
            run_id=run_id,
            generated_at=self._utc(generated_at),
            as_of=self._utc(as_of),
            source_run_input_fingerprint_digest=input_digest,
            status=status,
            strict_ready=status == "no_gap",
            quantity_reconciled=quantity_reconciled,
            original_acquisition_basis_complete=not groups and not bitget_unmatched,
            groups_count=len(groups),
            assets=sorted({item.asset for item in groups}),
            years=sorted({item.year for item in groups}),
            unmatched_disposals_count=len(bitget_unmatched),
            out_of_scope_bitget_unmatched_disposals_count=(
                out_of_scope_unmatched_count
            ),
            linked_unmatched_disposals_count=linked_count,
            unallocated_unmatched_disposals_count=len(unallocated),
            asset_totals=[
                BitgetStrategyAssetTotals(
                    asset=asset,
                    groups_count=sum(1 for item in groups if item.asset == asset),
                    strategy_quantity_without_cost_basis=sum(
                        (
                            item.strategy_quantity_without_cost_basis
                            for item in groups
                            if item.asset == asset
                        ),
                        Decimal("0"),
                    ),
                    allocated_missing_quantity=sum(
                        (
                            item.allocated_missing_quantity
                            for item in groups
                            if item.asset == asset
                        ),
                        Decimal("0"),
                    ),
                    residual_quantity=sum(
                        (
                            item.residual_quantity
                            for item in groups
                            if item.asset == asset
                        ),
                        Decimal("0"),
                    ),
                )
                for asset in sorted({item.asset for item in groups})
            ],
            blockpit_reference_count=sum(
                1 for item in groups if item.blockpit_reference.available
            ),
            blockpit_classification_conflict_count=sum(
                1
                for item in groups
                if item.blockpit_reference.classification_conflict
            ),
            support_package=support_package,
            api_history_boundary=api_boundary,
            groups=groups,
            unallocated_disposals=unallocated,
            findings=findings,
            next_actions=next_actions,
            evidence_refs=[
                f"/api/v1/tax/wallet-fifo-runs/{run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-gaps?run_id={run_id}",
                "/api/v1/tax/wallet-fifo/bitget-support-package.zip",
                *[
                    f"{item.path}#sha256={item.file_sha256}"
                    for item in support_package.files
                ],
                self.CLASSIC_SPOT_HISTORY_DOC,
                self.UTA_HISTORY_DOC,
            ],
            semantic_sha256=semantic_sha256,
            methodology=(
                "Read-only Mengen- und Belegabgleich fuer Bitget-Strategy-Settlements. "
                "Jeder nicht gedeckte Wallet-FIFO-Abgang wird chronologisch einer zuvor "
                "belegten STRATEGY_TRANSFER_IN-Originalzeile desselben Assets zugeordnet. "
                "Ein zuvor mit Lots gedeckter STRATEGY_TRANSFER_OUT-Principaleinsatz wird "
                "von der offenen Strategy-Menge abgezogen. Verbleibende Rundungsreste "
                "werden nur innerhalb assetbezogener Dust-Toleranzen als mengenmaessig "
                "geschlossen bewertet. Der in Bitget ausgewiesene USDT-Wert und Blockpit "
                "dienen ausschliesslich der Plausibilisierung; sie setzen weder historische "
                "Anschaffungskosten noch Anschaffungszeitpunkte. Das vollstaendige "
                "Bitget-Supportpaket wird datei- und zeilenscharf ausgewertet; Strategy.csv "
                "bindet jede Settlement-Gruppe an die konkrete Strategie, waehrend der "
                "Anbieterexport keine strategiegebundenen Einzel-Fills enthaelt. Eine Blockpit-Bezeichnung "
                "als Mining erzeugt hier ausdruecklich keinen Reward. Canonical Events, "
                "FIFO-Lots, Tax-Lines, Ledger und Preise bleiben unveraendert."
            ),
        )

    @staticmethod
    def csv_bytes(report: BitgetStrategyFifoGapReport) -> bytes:
        fieldnames = list(BitgetStrategyLinkedDisposal.model_fields)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for group in report.groups:
            for disposal in group.linked_disposals:
                writer.writerow(disposal.model_dump(mode="json"))
        for disposal in report.unallocated_disposals:
            writer.writerow(disposal.model_dump(mode="json"))
        return buffer.getvalue().encode("utf-8")

    def support_package_zip_bytes(
        self,
        package: BitgetSupportPackageAudit,
    ) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            manifest = json.dumps(
                package.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            self._zip_write(archive, "bitget_support_manifest.json", manifest)
            for item in sorted(package.files, key=lambda value: value.filename):
                path = Path(item.path)
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != item.file_sha256:
                    raise ValueError(
                        f"Bitget-Supportdatei hat sich geaendert: {item.filename}"
                    )
                self._zip_write(
                    archive,
                    f"bitget_support/{item.filename}",
                    content,
                )
        return buffer.getvalue()

    def _run_payload(self, run_id: str | None) -> dict[str, Any] | None:
        if run_id is not None:
            if not run_id.startswith("wallet-fifo-") or Path(run_id).name != run_id:
                return None
        path = (
            self.artifact_root / run_id / "wallet_fifo_parallel_run.json"
            if run_id
            else self.artifact_root / "latest_wallet_fifo_run.json"
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _raw_evidence(self, raw_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not raw_ids:
            return {}
        placeholders = ",".join("?" for _ in raw_ids)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select raw.raw_object_id, raw.batch_id, batch.source,
                       batch.filename, batch.file_hash, raw.row_number,
                       raw.payload_json
                from raw_objects raw
                join raw_import_batches batch on batch.batch_id = raw.batch_id
                where raw.raw_object_id in ({placeholders})
                """,
                sorted(raw_ids),
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload_text = str(row[6] or "{}")
            try:
                payload = json.loads(payload_text)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            result[str(row[0])] = {
                "raw_object_id": str(row[0]),
                "batch_id": str(row[1]),
                "source": str(row[2]),
                "filename": str(row[3] or ""),
                "file_hash": str(row[4] or ""),
                "row_number": row[5],
                "payload": payload,
                "payload_sha256": hashlib.sha256(
                    payload_text.encode("utf-8")
                ).hexdigest(),
            }
        return result

    def _event_evidence(self, event_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not event_ids:
            return {}
        placeholders = ",".join("?" for _ in event_ids)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select event.event_id, event.tx_id, event.source_ref,
                       event.quote_asset, event.quote_quantity,
                       raw.raw_object_id, raw.batch_id, raw.row_number,
                       raw.payload_json, batch.filename, batch.file_hash
                from canonical_events event
                left join raw_objects raw on raw.raw_object_id = event.raw_object_id
                left join raw_import_batches batch on batch.batch_id = raw.batch_id
                where event.event_id in ({placeholders})
                """,
                sorted(event_ids),
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload_text = str(row[8] or "{}")
            try:
                payload = json.loads(payload_text)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            result[str(row[0])] = {
                "tx_id": row[1],
                "source_ref": row[2],
                "quote_asset": row[3],
                "quote_quantity": row[4],
                "raw_object_id": row[5],
                "batch_id": row[6],
                "row_number": row[7],
                "payload": payload,
                "payload_sha256": hashlib.sha256(
                    payload_text.encode("utf-8")
                ).hexdigest(),
                "filename": row[9],
                "file_hash": row[10],
            }
        return result

    def _support_package(
        self,
        groups: list[BitgetStrategySettlementGap],
    ) -> BitgetSupportPackageAudit:
        files: list[BitgetSupportFileEvidence] = []
        rows_by_filename: dict[str, list[dict[str, str]]] = {}
        missing: list[str] = []
        for filename, (role, ledger_imported, contains_executions) in sorted(
            self.SUPPORT_FILES.items()
        ):
            path = self.support_package_root / filename
            if not path.is_file():
                missing.append(filename)
                continue
            content = path.read_bytes()
            columns, rows = self._support_csv(content)
            rows_by_filename[filename] = rows
            strategy_link_columns = [
                column
                for column in columns
                if "strategy" in column.lower()
                and ("id" in column.lower() or "identifier" in column.lower())
            ]
            files.append(
                BitgetSupportFileEvidence(
                    filename=filename,
                    path=str(path),
                    file_sha256=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                    records_count=len(rows),
                    columns=columns,
                    evidence_role=role,
                    ledger_imported=ledger_imported,
                    contains_individual_executions=contains_executions,
                    contains_strategy_link_field=bool(strategy_link_columns),
                    note=self._support_file_note(filename),
                )
            )

        strategy_rows = rows_by_filename.get("Strategy.csv", [])
        spot_rows = rows_by_filename.get("Spot Trading History.csv", [])
        strategy_file = next(
            (item for item in files if item.filename == "Strategy.csv"),
            None,
        )
        matches: list[BitgetSupportStrategyMatch] = []
        for group in groups:
            candidates: list[tuple[Decimal, dict[str, str], datetime, datetime]] = []
            for row in strategy_rows:
                if str(row.get("Futures/Spot") or "").strip().lower() != "spot":
                    continue
                pair = self._normalized_pair(row.get("Trading pair"))
                if not pair.startswith(group.asset.upper()):
                    continue
                created_at = self._support_datetime(row.get("Timestamp(creation) - (UTC+8)"))
                terminated_at = self._support_datetime(
                    row.get("Timestamp(termination) - (UTC+8)")
                )
                if created_at is None or terminated_at is None:
                    continue
                delta = Decimal(str(abs((group.settlement_at - terminated_at).total_seconds())))
                if delta <= Decimal("300"):
                    candidates.append((delta, row, created_at, terminated_at))
            if not candidates or strategy_file is None:
                continue
            delta, row, created_at, terminated_at = min(
                candidates,
                key=lambda item: item[0],
            )
            pair = self._normalized_pair(row.get("Trading pair"))
            same_pair_window_rows = [
                spot_row
                for spot_row in spot_rows
                if self._normalized_pair(spot_row.get("Trading pair")) == pair
                and (
                    created_at
                    <= (
                        self._support_datetime(
                            spot_row.get("Timestamp UTC+8 (Created)")
                        )
                        or datetime.min.replace(tzinfo=timezone.utc)
                    )
                    <= terminated_at
                )
            ]
            matches.append(
                BitgetSupportStrategyMatch(
                    settlement_group_id=group.settlement_group_id,
                    strategy_id=str(row.get("Strategy ID") or "").strip().lstrip("'"),
                    strategy_row_number=int(row.get("__row_number") or 0),
                    strategy_file_sha256=strategy_file.file_sha256,
                    asset=group.asset,
                    trading_pair=str(row.get("Trading pair") or ""),
                    strategy_type=str(row.get("Strategy type") or ""),
                    created_at=created_at,
                    terminated_at=terminated_at,
                    settlement_delta_seconds=delta,
                    investment_amount=self._decimal(row.get("Investment amount")),
                    total_gains=self._decimal(row.get("Total gains")),
                    fee_base_asset=self._decimal(row.get("Fee(base asset)")),
                    fee_quote_asset=self._decimal(row.get("Fee(quote asset)")),
                    status_upon_termination=(
                        str(row.get("Status upon termination") or "") or None
                    ),
                    reason_of_termination=(
                        str(row.get("Reason of termination") or "") or None
                    ),
                    same_pair_window_execution_rows_count=len(same_pair_window_rows),
                    strategy_linked_fill_rows_count=0,
                    exact_settlement_match=delta <= Decimal("10"),
                )
            )

        package_complete = not missing
        linked_fill_rows = sum(
            item.strategy_linked_fill_rows_count for item in matches
        )
        spot_execution_file = next(
            (
                item
                for item in files
                if item.filename == "Spot Trading History.csv"
            ),
            None,
        )
        provider_gap = (
            package_complete
            and spot_execution_file is not None
            and not spot_execution_file.contains_strategy_link_field
            and linked_fill_rows == 0
        )
        if not files:
            status = "support_package_unavailable"
        elif not package_complete:
            status = "incomplete_support_package"
        elif provider_gap:
            status = "complete_provider_package_fill_fields_absent"
        else:
            status = "complete_provider_package_exact_fills_available"
        semantic_payload = {
            "status": status,
            "missing_files": missing,
            "files": [
                {
                    key: value
                    for key, value in item.model_dump(mode="json").items()
                    if key != "path"
                }
                for item in files
            ],
            "matches": [item.model_dump(mode="json") for item in matches],
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        findings = []
        if package_complete:
            findings.append(
                f"Alle {len(self.SUPPORT_FILES)} vom Bitget-Support gelieferten "
                "Dateien sind vorhanden und SHA-256-gebunden."
            )
        else:
            findings.append(
                f"{len(files)} von {len(self.SUPPORT_FILES)} erwarteten "
                "Bitget-Supportdateien sind vorhanden."
            )
        if matches:
            findings.append(
                f"{len(matches)} Strategy.csv-Zeilen stimmen innerhalb von zehn "
                "Sekunden mit den relevanten Settlements ueberein."
            )
        if provider_gap:
            findings.append(
                "Spot Trading History.csv enthaelt Einzel-Ausfuehrungen, aber kein "
                "Strategy-ID-Feld; die internen Bot-Fills sind im vollstaendigen "
                "Supportexport deshalb nicht transaktionsscharf enthalten."
            )
        return BitgetSupportPackageAudit(
            status=status,
            root_path=str(self.support_package_root),
            available_files_count=len(files),
            missing_files=missing,
            package_complete=package_complete,
            additional_user_export_required=not package_complete,
            provider_export_field_gap=provider_gap,
            files=files,
            strategy_rows_count=len(strategy_rows),
            spot_execution_rows_count=len(spot_rows),
            relevant_strategy_matches_count=len(matches),
            strategy_linked_fill_rows_count=linked_fill_rows,
            same_pair_window_execution_rows_count=sum(
                item.same_pair_window_execution_rows_count for item in matches
            ),
            relevant_strategy_matches=matches,
            findings=findings,
            semantic_sha256=semantic_sha256,
        )

    def _blockpit_rows(self) -> tuple[dict[str, tuple[int, dict[str, str]]], str | None]:
        try:
            content = self.blockpit_reference_path.read_bytes()
            text = content.decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return {}, None
        rows: dict[str, tuple[int, dict[str, str]]] = {}
        for row_number, row in enumerate(
            csv.DictReader(io.StringIO(text), delimiter=";"), start=2
        ):
            tx_id = str(row.get("Trx. ID (optional)") or "").strip().lstrip("'")
            if tx_id:
                rows[tx_id] = (row_number, row)
        return rows, hashlib.sha256(content).hexdigest()

    def _blockpit_reference(
        self,
        transaction_id: str,
        *,
        blockpit_rows: dict[str, tuple[int, dict[str, str]]],
        blockpit_sha: str | None,
        source_operation: str,
    ) -> BitgetStrategyReferenceEvidence:
        found = blockpit_rows.get(transaction_id)
        if found is None:
            return BitgetStrategyReferenceEvidence(
                note=(
                    "Keine Blockpit-Referenzzeile gefunden; die Bitget-Originalzeile "
                    "bleibt die primaere Mengenquelle."
                )
            )
        row_number, row = found
        label = str(row.get("Label") or "").strip()
        incoming_asset = str(row.get("Incoming Asset") or "").strip() or None
        incoming_amount = self._optional_decimal(row.get("Incoming Amount"))
        conflict = (
            source_operation.upper() == "STRATEGY_TRANSFER_IN"
            and label.lower() in {"mining", "reward", "interest", "staking"}
        )
        return BitgetStrategyReferenceEvidence(
            available=True,
            path=str(self.blockpit_reference_path),
            file_sha256=blockpit_sha,
            row_number=row_number,
            transaction_id=transaction_id,
            integration_name=str(row.get("Integration Name") or "") or None,
            label=label or None,
            incoming_asset=incoming_asset,
            incoming_amount=incoming_amount,
            comment=str(row.get("Comment (optional)") or "") or None,
            source_type=str(row.get("Source Type") or "") or None,
            source_name=str(row.get("Source Name") or "") or None,
            classification_conflict=conflict,
            note=(
                "Referenz nur fuer Menge und Fremdsystemvergleich. Die Bezeichnung "
                "Mining wird durch die Bitget-Originaloperation STRATEGY_TRANSFER_IN "
                "widerlegt und hat keine Reward- oder Steuerwirkung."
                if conflict
                else "Referenz nur fuer Menge und Fremdsystemvergleich; keine Kostenbasis."
            ),
        )

    def _linked_disposal(
        self,
        row: dict[str, str],
        *,
        settlement_group_id: str,
        allocated: Decimal,
        evidence: dict[str, Any] | None,
    ) -> BitgetStrategyLinkedDisposal:
        missing = self._decimal(row.get("missing_quantity"))
        payload = evidence.get("payload", {}) if evidence else {}
        return BitgetStrategyLinkedDisposal(
            settlement_group_id=settlement_group_id,
            source_event_id=str(row.get("source_event_id") or ""),
            event_time=self._datetime(row.get("event_time")),
            asset=str(row.get("asset") or "").upper(),
            pool_id=str(row.get("pool_id") or ""),
            disposal_quantity=self._decimal(row.get("quantity")),
            matched_wallet_lot_quantity=self._decimal(row.get("matched_quantity")),
            missing_wallet_lot_quantity=missing,
            allocated_strategy_gap_quantity=allocated,
            quantity_fully_allocated=allocated == missing,
            reason=str(row.get("reason") or ""),
            order_number=(
                str(payload.get("Order no.") or "").strip().lstrip("'") or None
            ),
            quote_asset=(
                str(evidence.get("quote_asset") or "") or None if evidence else None
            ),
            quote_quantity=(
                self._optional_decimal(evidence.get("quote_quantity"))
                if evidence
                else None
            ),
            raw_object_id=(
                str(evidence.get("raw_object_id") or "") or None
                if evidence
                else None
            ),
            source_batch_id=(
                str(evidence.get("batch_id") or "") or None if evidence else None
            ),
            source_filename=(
                str(evidence.get("filename") or "") or None if evidence else None
            ),
            source_file_hash=(
                str(evidence.get("file_hash") or "") or None if evidence else None
            ),
            source_row_number=(
                int(evidence["row_number"])
                if evidence and evidence.get("row_number") is not None
                else None
            ),
            raw_payload_sha256=(
                str(evidence.get("payload_sha256") or "") or None
                if evidence
                else None
            ),
        )

    @classmethod
    def _previous_outbound(
        cls,
        rows: list[dict[str, str]],
        *,
        asset: str,
        before: datetime,
    ) -> dict[str, str] | None:
        eligible = [
            row
            for row in rows
            if str(row.get("asset") or "").upper() == asset
            and cls._datetime(row.get("event_time")) < before
        ]
        return max(
            eligible,
            key=lambda row: cls._datetime(row.get("event_time")),
            default=None,
        )

    @classmethod
    def _semantic_group(cls, group: BitgetStrategySettlementGap) -> dict[str, Any]:
        payload = group.model_dump(mode="json")
        reference = payload.get("blockpit_reference")
        if isinstance(reference, dict):
            reference.pop("path", None)
        payload["evidence_refs"] = [
            reference
            for reference in payload.get("evidence_refs", [])
            if not str(reference).startswith("/")
        ]
        return payload

    @staticmethod
    def _semantic_support_package(
        package: BitgetSupportPackageAudit,
    ) -> dict[str, Any]:
        payload = package.model_dump(mode="json")
        payload.pop("root_path", None)
        for item in payload.get("files", []):
            if isinstance(item, dict):
                item.pop("path", None)
        return payload

    @classmethod
    def _findings(
        cls,
        *,
        groups: list[BitgetStrategySettlementGap],
        unmatched_count: int,
        linked_count: int,
        unallocated_count: int,
        out_of_scope_unmatched_count: int,
        errors: list[str],
        support_package: BitgetSupportPackageAudit,
    ) -> list[str]:
        findings = []
        if errors:
            findings.extend(f"Belegfehler: {error}" for error in errors)
        if unmatched_count:
            findings.append(
                f"{linked_count} von {unmatched_count} Bitget-Abgaengen sind einer "
                "belegten Strategy-Settlement-Menge zugeordnet."
            )
        if groups and all(item.quantity_reconciled for item in groups):
            findings.append(
                f"{len(groups)} Settlement-Gruppen sind mengenmaessig bis auf "
                "belegten Rundungs-Dust geschlossen."
            )
        if unallocated_count:
            findings.append(
                f"{unallocated_count} Bitget-Abgaenge besitzen weiterhin keine "
                "ausreichende Settlement-Menge."
            )
        if out_of_scope_unmatched_count:
            findings.append(
                f"{out_of_scope_unmatched_count} weitere Bitget-Luecke(n) liegen "
                "ausserhalb belegter STRATEGY_TRANSFER_IN-Ketten und werden von "
                "diesem Spezialbericht nicht umklassifiziert."
            )
        if groups:
            if support_package.provider_export_field_gap:
                findings.append(
                    "Das vollstaendige Bitget-Supportpaket ist vorhanden. Der "
                    "Anbieterexport enthaelt jedoch keine strategiegebundenen Bot-Fills "
                    "mit Anschaffungszeitpunkt und Kostenbasis; deshalb bleibt die "
                    "strikte Wallet-FIFO gesperrt."
                )
            else:
                findings.append(
                    "Die Original-Bot-Fills mit Anschaffungszeitpunkt und Kostenbasis "
                    "sind nicht belegt; deshalb bleibt die strikte Wallet-FIFO gesperrt."
                )
        conflicts = sum(
            1 for item in groups if item.blockpit_reference.classification_conflict
        )
        if conflicts:
            findings.append(
                f"{conflicts} Blockpit-Fremdklassifizierung(en) als Mining/Reward "
                "werden nicht in die Steuerlogik uebernommen."
            )
        findings.append(
            "Der Bericht schreibt keine Canonical Events, FIFO-Lots, Tax-Lines, "
            "Ledger- oder Preisdaten."
        )
        return findings

    @classmethod
    def _api_boundary(
        cls,
        support_package: BitgetSupportPackageAudit,
    ) -> BitgetStrategyApiHistoryBoundary:
        package_note = (
            "Das vollstaendige Supportpaket liegt bereits vor; weitere Dateien werden "
            "nicht vom Nutzer angefordert. Der Export selbst enthaelt keine "
            "strategiegebundenen Einzel-Fills."
            if support_package.package_complete
            else "Das lokale Supportpaket ist noch nicht vollstaendig."
        )
        return BitgetStrategyApiHistoryBoundary(
            status="historical_api_unavailable",
            requested_year=2024,
            classic_spot_history_endpoint=cls.CLASSIC_SPOT_HISTORY_ENDPOINT,
            uta_history_endpoint=cls.UTA_HISTORY_ENDPOINT,
            official_documentation_urls=[
                cls.CLASSIC_SPOT_HISTORY_DOC,
                cls.UTA_HISTORY_DOC,
            ],
            older_data_retrieval=(
                "support_package_already_supplied_provider_fill_fields_absent"
                if support_package.package_complete
                else "complete_local_support_package"
            ),
            finding=(
                "Die offiziellen Spot-History-Endpunkte liefern nur die letzten "
                f"90 Tage. Bot-Fills aus 2024 koennen heute nicht per API nachgeladen werden. {package_note}"
            ),
        )

    def _error_report(
        self,
        *,
        run_id: str,
        generated_at: datetime,
        as_of: datetime,
        input_digest: str,
        errors: list[str],
    ) -> BitgetStrategyFifoGapReport:
        support_package = self._support_package([])
        semantic = hashlib.sha256(
            json.dumps(
                {"input_digest": input_digest, "errors": errors},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return BitgetStrategyFifoGapReport(
            run_id=run_id,
            generated_at=self._utc(generated_at),
            as_of=self._utc(as_of),
            source_run_input_fingerprint_digest=input_digest,
            status="evidence_error",
            support_package=support_package,
            api_history_boundary=self._api_boundary(support_package),
            findings=[f"Belegfehler: {item}" for item in errors],
            next_actions=["Wallet-FIFO-Artefakte und SHA-Bindung erneut erzeugen."],
            semantic_sha256=semantic,
            methodology=(
                "Read-only Bitget-Strategy-FIFO-Nachweis; wegen fehlender oder "
                "abweichender Quellartefakte konnte kein Mengenabgleich erstellt werden."
            ),
        )

    @staticmethod
    def _gzip_csv_rows(path: Path) -> list[dict[str, str]]:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _support_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
        text = content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        next(reader, None)
        columns = [str(value or "").strip() for value in (next(reader, []) or [])]
        rows: list[dict[str, str]] = []
        for row_number, values in enumerate(reader, start=3):
            if not any(str(value or "").strip() for value in values):
                continue
            padded = [*values, *([""] * max(0, len(columns) - len(values)))]
            item = {
                column: str(padded[index] or "").strip()
                for index, column in enumerate(columns)
                if column
            }
            item["__row_number"] = str(row_number)
            rows.append(item)
        return columns, rows

    @staticmethod
    def _support_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            local = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=8))
            )
        except ValueError:
            return None
        return local.astimezone(timezone.utc)

    @staticmethod
    def _normalized_pair(value: Any) -> str:
        return "".join(
            character
            for character in str(value or "").upper()
            if character.isalnum()
        )

    @staticmethod
    def _support_file_note(filename: str) -> str:
        notes = {
            "Deposit-Withdrawal History.csv": (
                "On-chain und Fiat Deposit-/Withdrawal-Beleg; keine Bot-Ausfuehrungen."
            ),
            "Spot Financial Record.csv": (
                "Primaerer Spot-Bestandsledger mit Strategy-Ein-/Ausbuchungen."
            ),
            "Spot Trading History.csv": (
                "Spot-Einzelausfuehrungen ohne Strategy-ID oder Bot-Zuordnung."
            ),
            "Futures Financial Record.csv": (
                "Primaerer Derivate-Cashflowledger."
            ),
            "Futures Trading History.csv": (
                "Derivate-Ausfuehrungsbeleg; nicht fuer die vier Spot-Settlements."
            ),
            "Strategy.csv": (
                "Strategie-ID, Typ, Laufzeit, Investment, Gesamtgewinn und Gebuehren; "
                "keine Einzel-Fills."
            ),
        }
        return notes[filename]

    @staticmethod
    def _zip_write(archive: zipfile.ZipFile, filename: str, content: bytes) -> None:
        info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        archive.writestr(info, content)

    @classmethod
    def _transaction_id(cls, row: dict[str, Any]) -> str:
        return str(row.get("tx_id") or row.get("source_event_id") or "").strip().lstrip("'")

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value or "0"))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @classmethod
    def _optional_decimal(cls, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            result = value
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return BitgetStrategyFifoGapService._utc(result)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.PROJECT_ROOT / path

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        except OSError:
            return ""
        return digest.hexdigest()
