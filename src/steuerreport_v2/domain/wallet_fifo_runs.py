from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import csv
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from pydantic import BaseModel

from steuerreport_v2.contracts.bitget_strategy_fifo import (
    BitgetStrategyLinkedDisposal,
)
from steuerreport_v2.contracts.tax_wallet_fifo import (
    WalletFifoPreviewLine,
    WalletFifoPreviewLot,
    WalletFifoPreviewUnmatched,
    WalletFifoTransferTrace,
    WalletFifoYearDelta,
)
from steuerreport_v2.contracts.wallet_fifo_runs import (
    WalletFifoAssetReconciliation,
    WalletFifoEvidenceFile,
    WalletFifoMethodDeltaEvent,
    WalletFifoMethodDeltaExplanationReport,
    WalletFifoMethodDeltaGroup,
    WalletFifoParallelRunReport,
    WalletFifoParallelRunRequest,
    WalletFifoRunInputFingerprint,
    WalletFifoRunYearResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget_strategy_fifo import BitgetStrategyFifoGapService
from steuerreport_v2.domain.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionService,
)
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService, WalletFifoReplayState
from steuerreport_v2.domain.tax_time import reporting_tax_year


class WalletFifoParallelRunService:
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/wallet_fifo_runs"
    ACQUISITION_COST_EVIDENCE_REVIEW_STATUSES = {
        "resolved_by_documented_moonpay_apple_pay_onramp_cost_basis_pending",
        "known_staking_return_with_reward_component_review",
    }
    METHOD_DELTA_TOP_EVENTS_PER_GROUP = 50
    QUANTITY_TOLERANCE = Decimal("0.000000000001")
    PROCEEDS_TOLERANCE_EUR = Decimal("0.01")
    PROCEEDS_RECONCILIATION_TOLERANCE_EUR = Decimal("0.000001")
    INPUT_FINGERPRINT_VERSION = "wallet_fifo_input_v3_nonfinancial_updates_excluded"
    RUN_REPORT_VERSION = "wallet_fifo_run_v2_provider_basis_classification"

    def __init__(self, store: DuckDbStore, *, artifact_root: Path | None = None) -> None:
        self.store = store
        self.preview_service = WalletFifoPreviewService(store)
        self.artifact_root = artifact_root or self._default_artifact_root()

    def find_reusable_run(
        self,
        request: WalletFifoParallelRunRequest,
    ) -> WalletFifoParallelRunReport | None:
        now = datetime.now(timezone.utc)
        years = self._validated_years(request.years, now.year)
        as_of = self._resolve_as_of(request.as_of, years, now)
        try:
            candidates = sorted(
                self.artifact_root.glob(
                    "wallet-fifo-*/wallet_fifo_parallel_run.json"
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        matching_reports: list[tuple[Path, WalletFifoParallelRunReport]] = []
        for path in candidates:
            try:
                report = WalletFifoParallelRunReport.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            report_as_of = (
                report.as_of.replace(tzinfo=timezone.utc)
                if report.as_of.tzinfo is None
                else report.as_of.astimezone(timezone.utc)
            )
            if (
                report.years != years
                or report_as_of != as_of
                or report.material_delta_threshold_eur
                != request.material_delta_threshold_eur
                or report.report_schema_version != self.RUN_REPORT_VERSION
                or report.method_version != self.preview_service.METHOD_VERSION
            ):
                continue
            matching_reports.append((path, report))
        if not matching_reports:
            return None
        fingerprint = self._input_fingerprint(as_of)
        for path, report in matching_reports:
            if (
                report.input_fingerprint.fingerprint_version
                != fingerprint.fingerprint_version
                or report.input_fingerprint.digest != fingerprint.digest
                or not self._reusable_evidence_is_intact(path.parent, report)
            ):
                continue
            return report
        return None

    def run(
        self,
        request: WalletFifoParallelRunRequest,
        *,
        publish_latest: bool = True,
    ) -> WalletFifoParallelRunReport:
        generated_at = datetime.now(timezone.utc)
        years = self._validated_years(request.years, generated_at.year)
        as_of = self._resolve_as_of(request.as_of, years, generated_at)
        threshold = request.material_delta_threshold_eur
        fingerprint = self._input_fingerprint(as_of)
        state = self.preview_service.replay(as_of=as_of)
        latest_event_at = fingerprint.last_event_at
        if latest_event_at is not None and latest_event_at.tzinfo is None:
            latest_event_at = latest_event_at.replace(tzinfo=timezone.utc)
        cache_latest = latest_event_at is None or latest_event_at.astimezone(timezone.utc) <= as_of
        self.preview_service.seed_preview_cache_from_state(
            state,
            years=years,
            as_of=as_of,
            cache_latest=cache_latest,
        )
        year_results = [self._year_result(state, year, threshold) for year in years]
        asset_reconciliations = [
            item
            for year_result in year_results
            for item in year_result.asset_reconciliations
        ]

        run_id = (
            f"wallet-fifo-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{fingerprint.digest[:12]}-{uuid4().hex[:8]}"
        )
        run_dir = self.artifact_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        method_delta_report, method_delta_events = self._build_method_delta_explanation(
            state=state,
            run_id=run_id,
            generated_at=generated_at,
            as_of=as_of,
            years=years,
            fingerprint=fingerprint,
            material_threshold=threshold,
        )
        evidence_files = self._write_evidence_files(
            run_dir,
            state,
            asset_reconciliations,
            method_delta_report,
            method_delta_events,
        )
        bitget_strategy_gap = BitgetStrategyFifoGapService(
            self.store,
            artifact_root=self.artifact_root,
        ).build_from_evidence(
            run_id=run_id,
            generated_at=generated_at,
            as_of=as_of,
            input_digest=fingerprint.digest,
            unmatched_path=run_dir / "wallet_fifo_unmatched.csv.gz",
            transfer_traces_path=run_dir / "wallet_fifo_transfer_traces.csv.gz",
        )
        bitget_reconstruction_service = BitgetStrategyBasisReconstructionService(
            self.store,
            artifact_root=self.artifact_root,
        )
        bitget_strategy_reconstruction = bitget_reconstruction_service.build(
            bitget_strategy_gap
        )
        evidence_files.extend(
            [
                self._write_json_evidence(
                    run_dir / "bitget_strategy_fifo_gap_report.json",
                    "bitget_strategy_fifo_gap_report",
                    bitget_strategy_gap,
                    records_count=bitget_strategy_gap.groups_count,
                    semantic_sha256=bitget_strategy_gap.semantic_sha256,
                ),
                self._write_csv_gzip(
                    run_dir / "bitget_strategy_fifo_gap_disposals.csv.gz",
                    "bitget_strategy_fifo_gap_disposals",
                    [
                        disposal
                        for group in bitget_strategy_gap.groups
                        for disposal in group.linked_disposals
                    ]
                    + bitget_strategy_gap.unallocated_disposals,
                    list(BitgetStrategyLinkedDisposal.model_fields),
                    set(),
                ),
                self._write_json_evidence(
                    run_dir / "bitget_strategy_basis_reconstruction.json",
                    "bitget_strategy_basis_reconstruction",
                    bitget_strategy_reconstruction,
                    records_count=bitget_strategy_reconstruction.groups_count,
                    semantic_sha256=bitget_strategy_reconstruction.semantic_sha256,
                ),
                self._write_csv_bytes_gzip(
                    run_dir / "bitget_strategy_basis_reconstruction.csv.gz",
                    "bitget_strategy_basis_reconstruction_csv",
                    bitget_reconstruction_service.csv_bytes(
                        bitget_strategy_reconstruction
                    ),
                    records_count=(
                        bitget_strategy_reconstruction.linked_disposals_count
                    ),
                    semantic_sha256=bitget_strategy_reconstruction.semantic_sha256,
                ),
            ]
        )
        evidence_files = [
            item.model_copy(
                update={
                    "download_url": (
                        f"/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/"
                        f"{Path(item.path).name}"
                    )
                }
            )
            for item in evidence_files
        ]

        blocked_years = [item.year for item in year_results if item.status == "blocked"]
        review_years = [item.year for item in year_results if item.status == "review"]
        ready_years = [item.year for item in year_results if item.status == "ready_for_method_review"]
        material_years = [item.year for item in year_results if item.material_delta]
        event_set_mismatch_years = [item.year for item in year_results if not item.event_set_parity]
        event_set_parity_years = [item.year for item in year_results if item.event_set_parity]
        valuation_review_years = [item.year for item in year_results if not item.proceeds_parity]
        proceeds_parity_years = [item.year for item in year_results if item.proceeds_parity]
        status = "blocked" if blocked_years else "review" if review_years else "ready_for_method_review"
        selected_lines = [
            line
            for line in state.tax_lines
            if reporting_tax_year(line.disposed_at) in years
        ]
        selected_unmatched = [
            item
            for item in state.unmatched
            if reporting_tax_year(item.event_time) in years
        ]
        selected_transfers = [
            item
            for item in state.transfer_traces
            if reporting_tax_year(item.event_time) in years
        ]
        provider_basis_gap_event_ids = {
            disposal.source_event_id
            for group in bitget_strategy_gap.groups
            if group.quantity_reconciled
            and group.basis_gap_responsibility == "provider_export_field_gap"
            for disposal in group.linked_disposals
            if disposal.quantity_fully_allocated
        }
        provider_basis_gaps = [
            item
            for item in selected_unmatched
            if item.source_event_id in provider_basis_gap_event_ids
        ]
        unexplained_unmatched = [
            item
            for item in selected_unmatched
            if item.source_event_id not in provider_basis_gap_event_ids
        ]
        provider_basis_gap_count_by_year: dict[int, int] = defaultdict(int)
        unexplained_unmatched_count_by_year: dict[int, int] = defaultdict(int)
        for item in provider_basis_gaps:
            provider_basis_gap_count_by_year[reporting_tax_year(item.event_time)] += 1
        for item in unexplained_unmatched:
            unexplained_unmatched_count_by_year[
                reporting_tax_year(item.event_time)
            ] += 1
        year_results = [
            item.model_copy(
                update={
                    "provider_basis_gap_count": provider_basis_gap_count_by_year[
                        item.year
                    ],
                    "unexplained_unmatched_count": (
                        unexplained_unmatched_count_by_year[item.year]
                    ),
                }
            )
            for item in year_results
        ]
        global_gain = sum((item.global_gain_loss_eur for item in year_results), Decimal("0"))
        wallet_gain = sum((item.wallet_gain_loss_eur for item in year_results), Decimal("0"))
        findings = self._findings(
            blocked_years=blocked_years,
            material_years=material_years,
            event_set_mismatch_years=event_set_mismatch_years,
            unmatched_count=len(selected_unmatched),
            provider_basis_gap_count=len(provider_basis_gaps),
            unexplained_unmatched_count=len(unexplained_unmatched),
            unresolved_count=sum(
                1 for trace in selected_transfers if trace.status == "unresolved_inbound_provenance"
            ),
            transfer_evidence_review_count=sum(
                1 for trace in selected_transfers if trace.status == "cross_cex_transfer_evidence_partial"
            ),
            acquisition_cost_evidence_review_count=sum(
                1
                for trace in selected_transfers
                if trace.status in self.ACQUISITION_COST_EVIDENCE_REVIEW_STATUSES
            ),
            valuation_review_years=valuation_review_years,
        )
        semantic_sha256 = self._semantic_digest(
            as_of=as_of,
            years=years,
            threshold=threshold,
            fingerprint=fingerprint,
            year_results=year_results,
            evidence_files=evidence_files,
        )
        artifact_path = run_dir / "wallet_fifo_parallel_run.json"
        latest_path = self.artifact_root / "latest_wallet_fifo_run.json"
        report = WalletFifoParallelRunReport(
            run_id=run_id,
            generated_at=generated_at,
            as_of=as_of,
            report_schema_version=self.RUN_REPORT_VERSION,
            years=years,
            method_version=self.preview_service.METHOD_VERSION,
            status=status,
            strict_ready=False,
            method_acceptance_required=True,
            material_delta_threshold_eur=threshold,
            input_fingerprint=fingerprint,
            semantic_sha256=semantic_sha256,
            input_events_count=state.input_events_count,
            pools_count=state.pools_count,
            all_lots_count=len(state.all_lots),
            open_lots_count=len(state.open_lots),
            wallet_tax_lines_count=len(selected_lines),
            unmatched_count=len(selected_unmatched),
            provider_basis_gap_count=len(provider_basis_gaps),
            unexplained_unmatched_count=len(unexplained_unmatched),
            transfer_traces_count=len(selected_transfers),
            unresolved_inbound_provenance_count=sum(
                1 for trace in selected_transfers if trace.status == "unresolved_inbound_provenance"
            ),
            transfer_evidence_review_count=sum(
                1 for trace in selected_transfers if trace.status == "cross_cex_transfer_evidence_partial"
            ),
            acquisition_cost_evidence_review_count=sum(
                1
                for trace in selected_transfers
                if trace.status in self.ACQUISITION_COST_EVIDENCE_REVIEW_STATUSES
            ),
            global_gain_loss_eur=global_gain,
            wallet_gain_loss_eur=wallet_gain,
            delta_gain_loss_eur=wallet_gain - global_gain,
            material_delta_years=material_years,
            event_set_parity_years=event_set_parity_years,
            event_set_mismatch_years=event_set_mismatch_years,
            proceeds_parity_years=proceeds_parity_years,
            valuation_review_years=valuation_review_years,
            blocked_years=blocked_years,
            review_years=review_years,
            ready_for_method_review_years=ready_years,
            year_results=year_results,
            evidence_files=evidence_files,
            method_delta_explanation_url=(
                f"/api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation"
            ),
            method_delta_explanation_status=method_delta_report.status,
            method_delta_explanation_semantic_sha256=(
                method_delta_report.semantic_sha256
            ),
            method_delta_event_set_gap_groups_count=(
                method_delta_report.event_set_gap_groups_count
            ),
            method_delta_quantity_gap_groups_count=(
                method_delta_report.quantity_gap_groups_count
            ),
            method_delta_pool_reordering_groups_count=(
                method_delta_report.pool_reordering_groups_count
            ),
            method_delta_unexplained_proceeds_groups_count=(
                method_delta_report.unexplained_proceeds_delta_groups_count
            ),
            method_delta_quote_asset_fee_groups_count=(
                method_delta_report.quote_asset_fee_netting_groups_count
            ),
            bitget_strategy_gap_report_url=(
                f"/api/v1/tax/wallet-fifo/bitget-strategy-gaps?run_id={run_id}"
            ),
            bitget_strategy_gap_status=bitget_strategy_gap.status,
            bitget_strategy_gap_semantic_sha256=bitget_strategy_gap.semantic_sha256,
            bitget_strategy_gap_groups_count=bitget_strategy_gap.groups_count,
            bitget_strategy_gap_linked_disposals_count=(
                bitget_strategy_gap.linked_unmatched_disposals_count
            ),
            bitget_strategy_gap_unallocated_disposals_count=(
                bitget_strategy_gap.unallocated_unmatched_disposals_count
            ),
            bitget_strategy_gap_quantity_reconciled=(
                bitget_strategy_gap.quantity_reconciled
            ),
            bitget_strategy_reconstruction_report_url=(
                "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction"
                f"?run_id={run_id}"
            ),
            bitget_strategy_reconstruction_csv_url=(
                "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv"
                f"?run_id={run_id}"
            ),
            bitget_strategy_reconstruction_status=(
                bitget_strategy_reconstruction.status
            ),
            bitget_strategy_reconstruction_semantic_sha256=(
                bitget_strategy_reconstruction.semantic_sha256
            ),
            bitget_strategy_reconstruction_groups_count=(
                bitget_strategy_reconstruction.groups_count
            ),
            bitget_strategy_reconstruction_disposals_count=(
                bitget_strategy_reconstruction.linked_disposals_count
            ),
            published_as_latest=publish_latest,
            artifact_path=self._display_path(artifact_path),
            latest_artifact_path=(
                self._display_path(latest_path) if publish_latest else None
            ),
            findings=findings,
            next_actions=self._next_actions(
                blocked_years,
                material_years,
                provider_basis_gap_count=len(provider_basis_gaps),
                unexplained_unmatched_count=len(unexplained_unmatched),
                acquisition_cost_evidence_review_count=sum(
                    1
                    for trace in selected_transfers
                    if trace.status in self.ACQUISITION_COST_EVIDENCE_REVIEW_STATUSES
                ),
                valuation_review_years=valuation_review_years,
            ),
            methodology=(
                "Versionierter, read-only Wallet-/Depot-FIFO-Parallel-Run. Canonical Events und "
                "globale Vergleichszeilen werden exakt bis as_of in UTC begrenzt. Eigene Transfers "
                "fuehren Anschaffungszeitpunkt und Cost Basis in den Ziel-Pool fort. Der Lauf schreibt "
                "keine tax_lots, tax_lines, Ledger- oder Importdaten. strict_ready bleibt bis zur "
                "fachlichen Delta-Erklaerung und expliziten Methodenabnahme false. Mengen- und "
                "Mengenparitaet, Bewertungserloese, Cost-Basis-Deltas und explizite "
                "Netzwerkgebuehr-Veraeusserungen werden je Jahr/Asset getrennt nachgewiesen. "
                "Mengenreconciliierte Provider-Settlements ohne exportierte Bot-Fill-Kostenbasis "
                "werden separat von tatsaechlich unerklaerten Abgaengen ausgewiesen; beide "
                "bleiben bis zur belastbaren Kostenbasis beziehungsweise Herkunft blockierend."
            ),
        )
        content = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")
        self._atomic_write(artifact_path, content)
        if publish_latest:
            self._atomic_write(latest_path, content)
        return report

    @staticmethod
    def _reusable_evidence_is_intact(
        run_dir: Path,
        report: WalletFifoParallelRunReport,
    ) -> bool:
        for evidence in report.evidence_files:
            path = run_dir / Path(evidence.path).name
            try:
                if not path.is_file() or path.stat().st_size != evidence.size_bytes:
                    return False
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != evidence.sha256:
                    return False
            except OSError:
                return False
        return True

    def latest(self) -> WalletFifoParallelRunReport | None:
        path = self.artifact_root / "latest_wallet_fifo_run.json"
        try:
            return WalletFifoParallelRunReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def get(self, run_id: str) -> WalletFifoParallelRunReport | None:
        if not run_id.startswith("wallet-fifo-"):
            return None
        path = self.artifact_root / run_id / "wallet_fifo_parallel_run.json"
        try:
            return WalletFifoParallelRunReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def method_delta_explanation(
        self,
        *,
        run_id: str | None = None,
        year: int | None = None,
        asset: str | None = None,
        event_limit: int = 20,
    ) -> WalletFifoMethodDeltaExplanationReport | None:
        if event_limit < 1 or event_limit > self.METHOD_DELTA_TOP_EVENTS_PER_GROUP:
            raise ValueError(
                f"event_limit muss zwischen 1 und {self.METHOD_DELTA_TOP_EVENTS_PER_GROUP} liegen."
            )
        selected_run_id = run_id
        if selected_run_id is None:
            latest = self.latest()
            selected_run_id = latest.run_id if latest is not None else None
        if selected_run_id is None or not selected_run_id.startswith("wallet-fifo-"):
            return None
        path = (
            self.artifact_root
            / selected_run_id
            / "wallet_fifo_method_delta_explanation.json"
        )
        try:
            report = WalletFifoMethodDeltaExplanationReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        return self._filter_method_delta_report(
            report,
            year=year,
            asset=asset,
            event_limit=event_limit,
        )

    def evidence_path(self, run_id: str, filename: str) -> Path | None:
        allowed = {
            "wallet_fifo_tax_lines.csv.gz",
            "wallet_fifo_all_lots.csv.gz",
            "wallet_fifo_open_lots.csv.gz",
            "wallet_fifo_transfer_traces.csv.gz",
            "wallet_fifo_unmatched.csv.gz",
            "wallet_fifo_year_asset_deltas.csv.gz",
            "wallet_fifo_asset_reconciliation.csv.gz",
            "wallet_fifo_method_delta_events.csv.gz",
            "wallet_fifo_method_delta_explanation.json",
            "bitget_strategy_fifo_gap_report.json",
            "bitget_strategy_fifo_gap_disposals.csv.gz",
            "bitget_strategy_basis_reconstruction.json",
            "bitget_strategy_basis_reconstruction.csv.gz",
        }
        if filename not in allowed or not run_id.startswith("wallet-fifo-"):
            return None
        root = self.artifact_root.resolve()
        path = (root / run_id / filename).resolve()
        if path.parent != (root / run_id).resolve() or not path.is_file():
            return None
        return path

    def input_fingerprint(self, as_of: datetime) -> WalletFifoRunInputFingerprint:
        normalized = (
            as_of.replace(tzinfo=timezone.utc)
            if as_of.tzinfo is None
            else as_of.astimezone(timezone.utc)
        )
        return self._input_fingerprint(normalized)

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/wallet_fifo_runs"

    @staticmethod
    def _validated_years(years: list[int], current_year: int) -> list[int]:
        result = sorted(set(years))
        if not result:
            raise ValueError("Mindestens ein Steuerjahr ist erforderlich.")
        invalid = [year for year in result if year < 2009 or year > current_year]
        if invalid:
            raise ValueError(f"Ungueltige Steuerjahre: {', '.join(str(year) for year in invalid)}")
        return result

    @staticmethod
    def _resolve_as_of(
        requested: datetime | None,
        years: list[int],
        now: datetime,
    ) -> datetime:
        if requested is None:
            max_year = max(years)
            if max_year == now.year:
                return now
            return datetime(max_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
        as_of = requested.replace(tzinfo=timezone.utc) if requested.tzinfo is None else requested.astimezone(timezone.utc)
        if as_of.year < max(years):
            raise ValueError("Der Stichtag liegt vor einem angeforderten Steuerjahr.")
        if as_of > now:
            raise ValueError("Der Stichtag darf nicht in der Zukunft liegen.")
        return as_of

    def _input_fingerprint(self, as_of: datetime) -> WalletFifoRunInputFingerprint:
        cutoff = as_of.replace(tzinfo=None)
        with self.store.connect() as con:
            schema_version = str(
                con.execute("select value from schema_meta where key = 'schema_version'").fetchone()[0]
            )
            canonical = con.execute(
                """
                select count(*)::integer, min(event_time), max(event_time)
                from canonical_events where event_time <= ?
                """,
                [cutoff],
            ).fetchone()
            tax_lines = con.execute(
                """
                select count(*)::integer, max(disposed_at)
                from tax_lines where disposed_at <= ?
                """,
                [cutoff],
            ).fetchone()
            raw_objects = con.execute(
                """
                select count(*)::integer
                from raw_objects
                """
            ).fetchone()
            decisions = con.execute(
                """
                select count(*)::integer
                from review_decisions
                where coalesce(
                    json_extract_string(payload_json, '$.decision_type'), ''
                ) not in (
                    'wallet_fifo_method_acceptance',
                    'bitget_strategy_basis_method_decision'
                )
                """
            ).fetchone()
            prices = con.execute(
                """
                select count(*)::integer, max(priced_at)
                from price_ledger where priced_at <= ?
                """,
                [cutoff],
            ).fetchone()
            component_sha256 = {
                "canonical_events": self._rows_sha256(
                    con,
                    """
                    select event_id, source, source_ref, event_time, event_type,
                           asset, quantity, quote_asset, quote_quantity,
                           fee_asset, fee_quantity, tx_id, wallet, account,
                           confidence
                    from canonical_events
                    where event_time <= ?
                    order by all
                    """,
                    [cutoff],
                ),
                "tax_lines": self._rows_sha256(
                    con,
                    """
                    select line.asset, lot.acquired_at, line.disposed_at,
                           line.quantity, line.acquisition_cost_eur,
                           line.disposal_proceeds_eur, line.gain_loss_eur,
                           line.holding_days, line.source_event_id,
                           lot.source_event_id
                    from tax_lines line
                    join tax_lots lot on lot.lot_id = line.lot_id
                    where line.disposed_at <= ?
                    order by all
                    """,
                    [cutoff],
                ),
                "raw_objects": self._rows_sha256(
                    con,
                    """
                    select batch.source, batch.filename, batch.file_hash,
                           raw.row_number, raw.payload_json
                    from raw_objects raw
                    join raw_import_batches batch on batch.batch_id = raw.batch_id
                    order by all
                    """,
                ),
                "review_decisions": self._rows_sha256(
                    con,
                    """
                    select payload_json
                    from review_decisions
                    where coalesce(
                        json_extract_string(payload_json, '$.decision_type'), ''
                    ) not in (
                        'wallet_fifo_method_acceptance',
                        'bitget_strategy_basis_method_decision'
                    )
                    order by payload_json
                    """,
                ),
                "price_ledger": self._rows_sha256(
                    con,
                    """
                    select asset, price_eur, priced_at, source, confidence
                    from price_ledger
                    where priced_at <= ?
                    order by all
                    """,
                    [cutoff],
                ),
                "admin_settings": self._rows_sha256(
                    con,
                    """
                    select key, value_json
                    from admin_settings
                    where key not in ('tax.fee_accounting_binding', 'updates.settings.v1', 'updates.cache.v1')
                    order by key
                    """,
                ),
            }
        from steuerreport_v2.domain.token_conversion import config_binding
        component_sha256["token_conversion_config"] = config_binding()
        payload = {
            "as_of": as_of.isoformat(),
            "schema_version": schema_version,
            "fingerprint_version": self.INPUT_FINGERPRINT_VERSION,
            "component_sha256": component_sha256,
            "counts": {
                "canonical_events": int(canonical[0] or 0),
                "tax_lines": int(tax_lines[0] or 0),
                "raw_objects": int(raw_objects[0] or 0),
                "review_decisions": int(decisions[0] or 0),
                "price_ledger": int(prices[0] or 0),
            },
            "moonpay_evidence": MoonpayReceiptService(
                self.store
            ).evidence_fingerprint(),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        return WalletFifoRunInputFingerprint(
            digest=digest,
            schema_version=schema_version,
            fingerprint_version=self.INPUT_FINGERPRINT_VERSION,
            component_sha256=component_sha256,
            canonical_events_count=int(canonical[0] or 0),
            first_event_at=self._utc_datetime(canonical[1]),
            last_event_at=self._utc_datetime(canonical[2]),
            tax_lines_count=int(tax_lines[0] or 0),
            raw_objects_count=int(raw_objects[0] or 0),
            review_decisions_count=int(decisions[0] or 0),
            price_points_count=int(prices[0] or 0),
        )

    @classmethod
    def _rows_sha256(
        cls,
        con: object,
        query: str,
        params: list[object] | None = None,
    ) -> str:
        cursor = con.execute(query, params or [])
        digest = hashlib.sha256()
        while rows := cursor.fetchmany(1000):
            for row in rows:
                values = [cls._fingerprint_value(value) for value in row]
                digest.update(
                    json.dumps(
                        values,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("utf-8")
                )
                digest.update(b"\n")
        return digest.hexdigest()

    @staticmethod
    def _fingerprint_value(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        return value

    @staticmethod
    def _year_result(
        state: WalletFifoReplayState,
        year: int,
        threshold: Decimal,
    ) -> WalletFifoRunYearResult:
        global_lines = [
            line
            for line in state.global_tax_lines
            if reporting_tax_year(line.disposed_at) == year
        ]
        wallet_lines = [
            line
            for line in state.tax_lines
            if reporting_tax_year(line.disposed_at) == year
        ]
        unmatched = [
            item
            for item in state.unmatched
            if reporting_tax_year(item.event_time) == year
        ]
        transfers = [
            item
            for item in state.transfer_traces
            if reporting_tax_year(item.event_time) == year
        ]
        asset_deltas = [item for item in state.year_deltas if item.year == year]
        global_gain = sum((line.gain_loss_eur for line in global_lines), Decimal("0"))
        wallet_gain = sum((line.gain_loss_eur for line in wallet_lines), Decimal("0"))
        delta = wallet_gain - global_gain
        unresolved = sum(1 for trace in transfers if trace.status == "unresolved_inbound_provenance")
        transfer_evidence_review_count = sum(
            1 for trace in transfers if trace.status == "cross_cex_transfer_evidence_partial"
        )
        acquisition_cost_evidence_review_count = sum(
            1
            for trace in transfers
            if trace.status in WalletFifoParallelRunService.ACQUISITION_COST_EVIDENCE_REVIEW_STATUSES
        )
        reconciliations = WalletFifoParallelRunService._asset_reconciliations(
            global_lines=global_lines,
            wallet_lines=wallet_lines,
            year=year,
            material_threshold=threshold,
        )
        event_set_mismatch_assets = [
            item.asset for item in reconciliations if not item.quantity_parity
        ]
        valuation_review_assets = [
            item.asset for item in reconciliations if not item.proceeds_parity
        ]
        explicit_fee_assets = [
            item.asset for item in reconciliations if item.explicit_fee_quantity > 0
        ]
        basis_method_delta_assets = [
            item.asset for item in reconciliations if item.material_basis_delta
        ]
        material = abs(delta) > threshold
        status = (
            "blocked"
            if unmatched or unresolved or acquisition_cost_evidence_review_count or event_set_mismatch_assets
            else "review"
            if material or transfer_evidence_review_count or valuation_review_assets
            else "ready_for_method_review"
        )
        affected_assets = sorted({item.asset for item in asset_deltas if abs(item.delta_eur) > threshold})
        return WalletFifoRunYearResult(
            year=year,
            status=status,
            global_gain_loss_eur=global_gain,
            wallet_gain_loss_eur=wallet_gain,
            delta_gain_loss_eur=delta,
            material_delta=material,
            global_tax_lines_count=len(global_lines),
            wallet_tax_lines_count=len(wallet_lines),
            unmatched_count=len(unmatched),
            transfer_traces_count=len(transfers),
            unresolved_inbound_provenance_count=unresolved,
            transfer_evidence_review_count=transfer_evidence_review_count,
            acquisition_cost_evidence_review_count=acquisition_cost_evidence_review_count,
            affected_assets=affected_assets,
            event_set_parity=not event_set_mismatch_assets,
            proceeds_parity=not valuation_review_assets,
            event_set_mismatch_assets=event_set_mismatch_assets,
            valuation_review_assets=valuation_review_assets,
            explicit_fee_assets=explicit_fee_assets,
            basis_method_delta_assets=basis_method_delta_assets,
            asset_deltas=asset_deltas,
            asset_reconciliations=reconciliations,
        )

    @staticmethod
    def _asset_reconciliations(
        *,
        global_lines: list[object],
        wallet_lines: list[WalletFifoPreviewLine],
        year: int,
        material_threshold: Decimal,
    ) -> list[WalletFifoAssetReconciliation]:
        quantity_tolerance = Decimal("0.000000000001")
        proceeds_tolerance = Decimal("0.01")
        totals: dict[str, dict[str, Decimal]] = {}

        def values(asset: str) -> dict[str, Decimal]:
            return totals.setdefault(
                asset.upper(),
                {
                    "global_quantity": Decimal("0"),
                    "wallet_quantity": Decimal("0"),
                    "explicit_fee_quantity": Decimal("0"),
                    "global_proceeds": Decimal("0"),
                    "wallet_proceeds": Decimal("0"),
                    "global_basis": Decimal("0"),
                    "wallet_basis": Decimal("0"),
                    "global_gain": Decimal("0"),
                    "wallet_gain": Decimal("0"),
                },
            )

        for line in global_lines:
            item = values(str(getattr(line, "asset")))
            item["global_quantity"] += getattr(line, "quantity")
            item["global_proceeds"] += getattr(line, "disposal_proceeds_eur")
            item["global_basis"] += getattr(line, "acquisition_cost_eur")
            item["global_gain"] += getattr(line, "gain_loss_eur")
        for line in wallet_lines:
            item = values(line.asset)
            item["wallet_quantity"] += line.quantity
            item["wallet_proceeds"] += line.disposal_proceeds_eur
            item["wallet_basis"] += line.acquisition_cost_eur
            item["wallet_gain"] += line.gain_loss_eur
            if line.source_event_id.startswith(("external:", "solana-program-escrow:", "cross-cex:")) and line.source_event_id.endswith(":fee"):
                item["explicit_fee_quantity"] += line.quantity

        reconciliations: list[WalletFifoAssetReconciliation] = []
        for asset, item in sorted(totals.items()):
            reconciled_wallet_quantity = item["wallet_quantity"] - item["explicit_fee_quantity"]
            quantity_delta = reconciled_wallet_quantity - item["global_quantity"]
            proceeds_delta = item["wallet_proceeds"] - item["global_proceeds"]
            cost_basis_delta = item["wallet_basis"] - item["global_basis"]
            gain_delta = item["wallet_gain"] - item["global_gain"]
            quantity_parity = abs(quantity_delta) <= quantity_tolerance
            proceeds_parity = abs(proceeds_delta) <= proceeds_tolerance
            event_set_parity = quantity_parity
            material_basis_delta = abs(cost_basis_delta) > material_threshold
            has_fee = item["explicit_fee_quantity"] > 0
            if not quantity_parity:
                classification = "event_set_mismatch"
            elif not proceeds_parity:
                classification = "valuation_delta"
            elif material_basis_delta and has_fee:
                classification = "method_basis_delta_with_explicit_fee"
            elif material_basis_delta:
                classification = "method_basis_delta"
            elif has_fee:
                classification = "explicit_fee_disposal"
            else:
                classification = "exact_match"
            reconciliations.append(
                WalletFifoAssetReconciliation(
                    year=year,
                    asset=asset,
                    global_quantity=item["global_quantity"],
                    wallet_quantity=item["wallet_quantity"],
                    explicit_fee_quantity=item["explicit_fee_quantity"],
                    reconciled_wallet_quantity=reconciled_wallet_quantity,
                    quantity_delta=quantity_delta,
                    global_proceeds_eur=item["global_proceeds"],
                    wallet_proceeds_eur=item["wallet_proceeds"],
                    proceeds_delta_eur=proceeds_delta,
                    global_cost_basis_eur=item["global_basis"],
                    wallet_cost_basis_eur=item["wallet_basis"],
                    cost_basis_delta_eur=cost_basis_delta,
                    gain_loss_delta_eur=gain_delta,
                    quantity_parity=quantity_parity,
                    proceeds_parity=proceeds_parity,
                    event_set_parity=event_set_parity,
                    material_basis_delta=material_basis_delta,
                    classification=classification,
                )
            )
        return reconciliations

    def _build_method_delta_explanation(
        self,
        *,
        state: WalletFifoReplayState,
        run_id: str,
        generated_at: datetime,
        as_of: datetime,
        years: list[int],
        fingerprint: WalletFifoRunInputFingerprint,
        material_threshold: Decimal,
    ) -> tuple[
        WalletFifoMethodDeltaExplanationReport,
        list[WalletFifoMethodDeltaEvent],
    ]:
        global_lot_sources = {
            lot.lot_id: lot.source_event_id
            for lot in self.preview_service.tax_service.list_tax_lots()
        }
        event_metadata = {event.event_id: event for event in state.canonical_events}
        totals: defaultdict[tuple[int, str, str], dict[str, object]] = defaultdict(
            self._empty_method_delta_event_totals
        )

        for line in state.global_tax_lines:
            year = reporting_tax_year(line.disposed_at)
            if year not in years:
                continue
            item = totals[(year, line.asset.upper(), line.source_event_id)]
            self._add_method_delta_line(
                item,
                method="global",
                quantity=line.quantity,
                proceeds=line.disposal_proceeds_eur,
                cost_basis=line.acquisition_cost_eur,
                gain_loss=line.gain_loss_eur,
                acquired_at=line.acquired_at,
                disposed_at=line.disposed_at,
                acquisition_source_event_id=global_lot_sources.get(line.lot_id),
            )

        for line in state.tax_lines:
            year = reporting_tax_year(line.disposed_at)
            if year not in years:
                continue
            item = totals[(year, line.asset.upper(), line.source_event_id)]
            self._add_method_delta_line(
                item,
                method="wallet",
                quantity=line.quantity,
                proceeds=line.disposal_proceeds_eur,
                cost_basis=line.acquisition_cost_eur,
                gain_loss=line.gain_loss_eur,
                acquired_at=line.acquired_at,
                disposed_at=line.disposed_at,
                acquisition_source_event_id=line.acquisition_source_event_id,
                pool_id=line.pool_id,
                explicit_fee=self._is_explicit_fee_line(line),
            )

        event_rows: list[WalletFifoMethodDeltaEvent] = []
        grouped_events: defaultdict[tuple[int, str], list[WalletFifoMethodDeltaEvent]] = (
            defaultdict(list)
        )
        for (year, asset, source_event_id), item in sorted(totals.items()):
            metadata = event_metadata.get(source_event_id)
            event = self._method_delta_event(
                year=year,
                asset=asset,
                source_event_id=source_event_id,
                item=item,
                metadata=metadata,
                material_threshold=material_threshold,
            )
            event_rows.append(event)
            grouped_events[(year, asset)].append(event)

        groups = [
            self._method_delta_group(
                year=year,
                asset=asset,
                events=events,
                material_threshold=material_threshold,
            )
            for (year, asset), events in sorted(grouped_events.items())
        ]
        report = self._method_delta_report_from_groups(
            run_id=run_id,
            generated_at=generated_at,
            as_of=as_of,
            method_version=self.preview_service.METHOD_VERSION,
            input_fingerprint_digest=fingerprint.digest,
            material_threshold=material_threshold,
            groups=groups,
            source_run_report_url=f"/api/v1/tax/wallet-fifo-runs/{run_id}",
            full_event_csv_download_url=(
                f"/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/"
                "wallet_fifo_method_delta_events.csv.gz"
            ),
        )
        return report, event_rows

    @staticmethod
    def _empty_method_delta_event_totals() -> dict[str, object]:
        return {
            "global_quantity": Decimal("0"),
            "wallet_quantity": Decimal("0"),
            "global_proceeds": Decimal("0"),
            "wallet_proceeds": Decimal("0"),
            "global_basis": Decimal("0"),
            "wallet_basis": Decimal("0"),
            "global_gain": Decimal("0"),
            "wallet_gain": Decimal("0"),
            "global_lines": 0,
            "wallet_lines": 0,
            "global_acquired_at": [],
            "wallet_acquired_at": [],
            "global_acquisition_sources": set(),
            "wallet_acquisition_sources": set(),
            "wallet_pools": set(),
            "disposed_at": [],
            "explicit_fee": False,
        }

    @staticmethod
    def _add_method_delta_line(
        item: dict[str, object],
        *,
        method: str,
        quantity: Decimal,
        proceeds: Decimal,
        cost_basis: Decimal,
        gain_loss: Decimal,
        acquired_at: datetime,
        disposed_at: datetime,
        acquisition_source_event_id: str | None,
        pool_id: str | None = None,
        explicit_fee: bool = False,
    ) -> None:
        item[f"{method}_quantity"] = Decimal(str(item[f"{method}_quantity"])) + quantity
        item[f"{method}_proceeds"] = Decimal(str(item[f"{method}_proceeds"])) + proceeds
        item[f"{method}_basis"] = Decimal(str(item[f"{method}_basis"])) + cost_basis
        item[f"{method}_gain"] = Decimal(str(item[f"{method}_gain"])) + gain_loss
        item[f"{method}_lines"] = int(item[f"{method}_lines"]) + 1
        acquired_values = item[f"{method}_acquired_at"]
        assert isinstance(acquired_values, list)
        acquired_values.append(
            acquired_at.replace(tzinfo=timezone.utc)
            if acquired_at.tzinfo is None
            else acquired_at.astimezone(timezone.utc)
        )
        disposed_values = item["disposed_at"]
        assert isinstance(disposed_values, list)
        disposed_values.append(
            disposed_at.replace(tzinfo=timezone.utc)
            if disposed_at.tzinfo is None
            else disposed_at.astimezone(timezone.utc)
        )
        if acquisition_source_event_id:
            sources = item[f"{method}_acquisition_sources"]
            assert isinstance(sources, set)
            sources.add(acquisition_source_event_id)
        if pool_id:
            pools = item["wallet_pools"]
            assert isinstance(pools, set)
            pools.add(pool_id)
        item["explicit_fee"] = bool(item["explicit_fee"]) or explicit_fee

    def _method_delta_event(
        self,
        *,
        year: int,
        asset: str,
        source_event_id: str,
        item: dict[str, object],
        metadata: object | None,
        material_threshold: Decimal,
    ) -> WalletFifoMethodDeltaEvent:
        global_quantity = Decimal(str(item["global_quantity"]))
        wallet_quantity = Decimal(str(item["wallet_quantity"]))
        global_proceeds = Decimal(str(item["global_proceeds"]))
        wallet_proceeds = Decimal(str(item["wallet_proceeds"]))
        global_basis = Decimal(str(item["global_basis"]))
        wallet_basis = Decimal(str(item["wallet_basis"]))
        global_gain = Decimal(str(item["global_gain"]))
        wallet_gain = Decimal(str(item["wallet_gain"]))
        explicit_fee = bool(item["explicit_fee"])
        quantity_delta = wallet_quantity - global_quantity
        proceeds_delta = wallet_proceeds - global_proceeds
        basis_delta = wallet_basis - global_basis
        gain_delta = wallet_gain - global_gain
        global_lines = int(item["global_lines"])
        wallet_lines = int(item["wallet_lines"])
        event_quantity = abs(
            Decimal(str(getattr(metadata, "quantity", Decimal("0")) or "0"))
        )
        quote_asset = str(getattr(metadata, "quote_asset", "") or "").upper()
        fee_asset = str(getattr(metadata, "fee_asset", "") or "").upper()
        fee_quantity = abs(
            Decimal(str(getattr(metadata, "fee_quantity", Decimal("0")) or "0"))
        )
        is_quote_asset_fee = bool(
            metadata is not None
            and getattr(metadata, "event_type", "") == "trade"
            and Decimal(str(getattr(metadata, "quantity", Decimal("0")))) < 0
            and quote_asset
            and fee_asset == quote_asset
            and fee_quantity > 0
        )
        gross_event_value = (
            self.preview_service.tax_service._eur_value(metadata)
            if metadata is not None and event_quantity > 0
            else Decimal("0")
        )
        fee_value = (
            self.preview_service.tax_service._asset_value_eur(
                fee_asset,
                fee_quantity,
                getattr(metadata, "event_time"),
            )
            if is_quote_asset_fee
            else Decimal("0")
        ) or Decimal("0")
        global_gross_expected = (
            gross_event_value * global_quantity / event_quantity
            if event_quantity
            else global_proceeds
        )
        wallet_gross_expected = (
            gross_event_value * wallet_quantity / event_quantity
            if event_quantity
            else wallet_proceeds
        )
        global_net_expected = (
            (gross_event_value - fee_value) * global_quantity / event_quantity
            if event_quantity
            else global_proceeds
        )
        wallet_net_expected = (
            (gross_event_value - fee_value) * wallet_quantity / event_quantity
            if event_quantity
            else wallet_proceeds
        )
        global_quote_fee_netting_applied = bool(
            is_quote_asset_fee
            and abs(global_proceeds - global_net_expected)
            <= self.PROCEEDS_RECONCILIATION_TOLERANCE_EUR
        )
        wallet_quote_fee_netting_applied = bool(
            is_quote_asset_fee
            and abs(wallet_proceeds - wallet_net_expected)
            <= self.PROCEEDS_RECONCILIATION_TOLERANCE_EUR
        )
        expected_global_proceeds = (
            global_net_expected
            if global_quote_fee_netting_applied
            else global_gross_expected
        )
        expected_wallet_proceeds = (
            wallet_net_expected
            if wallet_quote_fee_netting_applied
            else wallet_gross_expected
        )
        expected_proceeds_delta = expected_wallet_proceeds - expected_global_proceeds
        unexplained_proceeds_delta = proceeds_delta - expected_proceeds_delta
        proceeds_delta_reconciled = bool(
            abs(unexplained_proceeds_delta)
            <= self.PROCEEDS_RECONCILIATION_TOLERANCE_EUR
        )
        drivers: list[str] = []
        if explicit_fee:
            drivers.append("explicit_fee_treatment")
        else:
            if not global_lines or not wallet_lines:
                drivers.append("event_set_gap")
            if abs(quantity_delta) > self.QUANTITY_TOLERANCE:
                drivers.append("quantity_gap")
                if proceeds_delta_reconciled:
                    drivers.append("quantity_proceeds_allocation")
            if (
                is_quote_asset_fee
                and global_quote_fee_netting_applied
                != wallet_quote_fee_netting_applied
            ):
                drivers.append("quote_asset_fee_netting")
            if (
                abs(unexplained_proceeds_delta) > self.PROCEEDS_TOLERANCE_EUR
            ):
                drivers.append("proceeds_valuation_delta")
            if (
                global_lines
                and wallet_lines
                and abs(quantity_delta) <= self.QUANTITY_TOLERANCE
                and abs(basis_delta) > material_threshold
            ):
                drivers.append("pool_fifo_cost_basis_reordering")
        if not drivers:
            has_nonzero_delta = any(
                value != 0
                for value in (quantity_delta, proceeds_delta, basis_delta, gain_delta)
            )
            drivers.append("rounding_only" if has_nonzero_delta else "exact_match")

        global_acquired = item["global_acquired_at"]
        wallet_acquired = item["wallet_acquired_at"]
        disposed_values = item["disposed_at"]
        global_sources = sorted(str(value) for value in item["global_acquisition_sources"])
        wallet_sources = sorted(str(value) for value in item["wallet_acquisition_sources"])
        wallet_pools = sorted(str(value) for value in item["wallet_pools"])
        assert isinstance(global_acquired, list)
        assert isinstance(wallet_acquired, list)
        assert isinstance(disposed_values, list)
        return WalletFifoMethodDeltaEvent(
            year=year,
            asset=asset,
            source_event_id=source_event_id,
            disposed_at=min(disposed_values),
            source=str(getattr(metadata, "source", "") or "") or None,
            account=str(getattr(metadata, "account", "") or "") or None,
            tx_id=str(getattr(metadata, "tx_id", "") or "") or None,
            global_quantity=global_quantity,
            wallet_quantity=wallet_quantity,
            quantity_delta=quantity_delta,
            global_proceeds_eur=global_proceeds,
            wallet_proceeds_eur=wallet_proceeds,
            proceeds_delta_eur=proceeds_delta,
            expected_proceeds_delta_eur=expected_proceeds_delta,
            unexplained_proceeds_delta_eur=unexplained_proceeds_delta,
            proceeds_delta_reconciled=proceeds_delta_reconciled,
            quote_asset_fee_netting=is_quote_asset_fee,
            global_quote_fee_netting_applied=global_quote_fee_netting_applied,
            wallet_quote_fee_netting_applied=wallet_quote_fee_netting_applied,
            fee_asset=fee_asset or None,
            fee_quantity=fee_quantity,
            fee_value_eur=fee_value,
            global_cost_basis_eur=global_basis,
            wallet_cost_basis_eur=wallet_basis,
            cost_basis_delta_eur=basis_delta,
            global_gain_loss_eur=global_gain,
            wallet_gain_loss_eur=wallet_gain,
            gain_loss_delta_eur=gain_delta,
            global_tax_lines_count=global_lines,
            wallet_tax_lines_count=wallet_lines,
            explicit_fee_event=explicit_fee,
            global_acquired_at_min=min(global_acquired) if global_acquired else None,
            global_acquired_at_max=max(global_acquired) if global_acquired else None,
            wallet_acquired_at_min=min(wallet_acquired) if wallet_acquired else None,
            wallet_acquired_at_max=max(wallet_acquired) if wallet_acquired else None,
            wallet_pool_ids=wallet_pools,
            global_acquisition_sources_count=len(global_sources),
            wallet_acquisition_sources_count=len(wallet_sources),
            global_acquisition_source_event_ids=global_sources[:25],
            wallet_acquisition_source_event_ids=wallet_sources[:25],
            drivers=drivers,
            explanation=self._method_delta_explanation_text(drivers),
        )

    def _method_delta_group(
        self,
        *,
        year: int,
        asset: str,
        events: list[WalletFifoMethodDeltaEvent],
        material_threshold: Decimal,
    ) -> WalletFifoMethodDeltaGroup:
        global_event_ids = {
            event.source_event_id
            for event in events
            if event.global_tax_lines_count and not event.explicit_fee_event
        }
        wallet_event_ids = {
            event.source_event_id
            for event in events
            if event.wallet_tax_lines_count and not event.explicit_fee_event
        }
        global_quantity = sum((event.global_quantity for event in events), Decimal("0"))
        wallet_quantity = sum((event.wallet_quantity for event in events), Decimal("0"))
        explicit_fee_quantity = sum(
            (event.wallet_quantity for event in events if event.explicit_fee_event),
            Decimal("0"),
        )
        reconciled_wallet_quantity = wallet_quantity - explicit_fee_quantity
        quantity_delta = reconciled_wallet_quantity - global_quantity
        global_proceeds = sum((event.global_proceeds_eur for event in events), Decimal("0"))
        wallet_proceeds = sum((event.wallet_proceeds_eur for event in events), Decimal("0"))
        global_basis = sum((event.global_cost_basis_eur for event in events), Decimal("0"))
        wallet_basis = sum((event.wallet_cost_basis_eur for event in events), Decimal("0"))
        global_gain = sum((event.global_gain_loss_eur for event in events), Decimal("0"))
        wallet_gain = sum((event.wallet_gain_loss_eur for event in events), Decimal("0"))
        event_set_parity = global_event_ids == wallet_event_ids
        quantity_parity = abs(quantity_delta) <= self.QUANTITY_TOLERANCE
        proceeds_delta = wallet_proceeds - global_proceeds
        proceeds_parity = abs(proceeds_delta) <= self.PROCEEDS_TOLERANCE_EUR
        expected_proceeds_delta = sum(
            (event.expected_proceeds_delta_eur for event in events), Decimal("0")
        )
        unexplained_proceeds_delta = proceeds_delta - expected_proceeds_delta
        proceeds_reconciliation_ready = bool(
            abs(unexplained_proceeds_delta) <= self.PROCEEDS_TOLERANCE_EUR
        )
        basis_delta = wallet_basis - global_basis
        drivers: list[str] = []
        if not event_set_parity:
            drivers.append("event_set_gap")
        if not quantity_parity:
            drivers.append("quantity_gap")
            if proceeds_reconciliation_ready:
                drivers.append("quantity_proceeds_allocation")
        if any("quote_asset_fee_netting" in event.drivers for event in events):
            drivers.append("quote_asset_fee_netting")
        if not proceeds_reconciliation_ready:
            drivers.append("proceeds_valuation_delta")
        has_pool_reordering_events = any(
            "pool_fifo_cost_basis_reordering" in event.drivers for event in events
        )
        if (
            event_set_parity
            and abs(basis_delta) > material_threshold
            and (quantity_parity or has_pool_reordering_events)
        ):
            drivers.append("pool_fifo_cost_basis_reordering")
        if any(event.explicit_fee_event for event in events):
            drivers.append("explicit_fee_treatment")
        if not drivers:
            gain_delta = wallet_gain - global_gain
            has_nonzero_delta = any(
                value != 0 for value in (quantity_delta, proceeds_delta, basis_delta, gain_delta)
            )
            drivers.append("rounding_only" if has_nonzero_delta else "exact_match")
        material_events = [
            event
            for event in events
            if abs(event.gain_loss_delta_eur) > material_threshold
            or any(
                driver in {"event_set_gap", "quantity_gap", "proceeds_valuation_delta"}
                for driver in event.drivers
            )
        ]
        ranked_events = sorted(
            events,
            key=lambda event: (
                -abs(event.gain_loss_delta_eur),
                event.disposed_at,
                event.source_event_id,
            ),
        )
        return WalletFifoMethodDeltaGroup(
            year=year,
            asset=asset,
            global_event_ids_count=len(global_event_ids),
            wallet_event_ids_count=len(wallet_event_ids),
            compared_events_count=len(events),
            material_events_count=len(material_events),
            explicit_fee_events_count=sum(event.explicit_fee_event for event in events),
            event_set_gap_events_count=sum(
                "event_set_gap" in event.drivers for event in events
            ),
            quantity_gap_events_count=sum(
                "quantity_gap" in event.drivers for event in events
            ),
            proceeds_delta_events_count=sum(
                abs(event.proceeds_delta_eur) > self.PROCEEDS_TOLERANCE_EUR
                for event in events
            ),
            quote_asset_fee_events_count=sum(
                event.quote_asset_fee_netting for event in events
            ),
            reconciled_proceeds_delta_events_count=sum(
                abs(event.proceeds_delta_eur) > self.PROCEEDS_TOLERANCE_EUR
                and event.proceeds_delta_reconciled
                for event in events
            ),
            pool_reordering_events_count=sum(
                "pool_fifo_cost_basis_reordering" in event.drivers for event in events
            ),
            global_quantity=global_quantity,
            wallet_quantity=wallet_quantity,
            explicit_fee_quantity=explicit_fee_quantity,
            reconciled_wallet_quantity=reconciled_wallet_quantity,
            quantity_delta=quantity_delta,
            global_proceeds_eur=global_proceeds,
            wallet_proceeds_eur=wallet_proceeds,
            proceeds_delta_eur=proceeds_delta,
            expected_proceeds_delta_eur=expected_proceeds_delta,
            unexplained_proceeds_delta_eur=unexplained_proceeds_delta,
            proceeds_reconciliation_ready=proceeds_reconciliation_ready,
            global_cost_basis_eur=global_basis,
            wallet_cost_basis_eur=wallet_basis,
            cost_basis_delta_eur=basis_delta,
            global_gain_loss_eur=global_gain,
            wallet_gain_loss_eur=wallet_gain,
            gain_loss_delta_eur=wallet_gain - global_gain,
            event_set_parity=event_set_parity,
            quantity_parity=quantity_parity,
            proceeds_parity=proceeds_parity,
            drivers=drivers,
            top_events=ranked_events[: self.METHOD_DELTA_TOP_EVENTS_PER_GROUP],
            explanation=self._method_delta_explanation_text(drivers),
        )

    def _method_delta_report_from_groups(
        self,
        *,
        run_id: str,
        generated_at: datetime,
        as_of: datetime,
        method_version: str,
        input_fingerprint_digest: str,
        material_threshold: Decimal,
        groups: list[WalletFifoMethodDeltaGroup],
        source_run_report_url: str,
        full_event_csv_download_url: str,
    ) -> WalletFifoMethodDeltaExplanationReport:
        event_gap_count = self._groups_with_driver(groups, "event_set_gap")
        quantity_gap_count = self._groups_with_driver(groups, "quantity_gap")
        raw_proceeds_count = sum(not group.proceeds_parity for group in groups)
        unexplained_proceeds_count = self._groups_with_driver(
            groups, "proceeds_valuation_delta"
        )
        reconciled_proceeds_count = sum(
            not group.proceeds_parity and group.proceeds_reconciliation_ready
            for group in groups
        )
        quote_fee_group_count = sum(
            group.quote_asset_fee_events_count > 0 for group in groups
        )
        pool_count = self._groups_with_driver(groups, "pool_fifo_cost_basis_reordering")
        exact_count = self._groups_with_driver(groups, "exact_match")
        material_count = sum(
            abs(group.gain_loss_delta_eur) > material_threshold
            or any(
                driver in {"event_set_gap", "quantity_gap", "proceeds_valuation_delta"}
                for driver in group.drivers
            )
            for group in groups
        )
        global_gain = sum((group.global_gain_loss_eur for group in groups), Decimal("0"))
        wallet_gain = sum((group.wallet_gain_loss_eur for group in groups), Decimal("0"))
        global_proceeds = sum((group.global_proceeds_eur for group in groups), Decimal("0"))
        wallet_proceeds = sum((group.wallet_proceeds_eur for group in groups), Decimal("0"))
        global_basis = sum((group.global_cost_basis_eur for group in groups), Decimal("0"))
        wallet_basis = sum((group.wallet_cost_basis_eur for group in groups), Decimal("0"))
        status = (
            "blocked"
            if event_gap_count or quantity_gap_count
            else "review"
            if material_count or unexplained_proceeds_count
            else "ready_for_method_review"
        )
        findings = self._method_delta_findings(
            groups=groups,
            event_gap_count=event_gap_count,
            quantity_gap_count=quantity_gap_count,
            raw_proceeds_count=raw_proceeds_count,
            reconciled_proceeds_count=reconciled_proceeds_count,
            unexplained_proceeds_count=unexplained_proceeds_count,
            quote_fee_group_count=quote_fee_group_count,
            pool_count=pool_count,
            global_proceeds=global_proceeds,
            wallet_proceeds=wallet_proceeds,
            global_basis=global_basis,
            wallet_basis=wallet_basis,
        )
        report = WalletFifoMethodDeltaExplanationReport(
            run_id=run_id,
            generated_at=generated_at,
            as_of=as_of,
            method_version=method_version,
            status=status,
            method_acceptance_required=True,
            input_fingerprint_digest=input_fingerprint_digest,
            semantic_sha256="",
            years=sorted({group.year for group in groups}),
            assets=sorted({group.asset for group in groups}),
            material_delta_threshold_eur=material_threshold,
            groups_count=len(groups),
            material_groups_count=material_count,
            event_set_gap_groups_count=event_gap_count,
            quantity_gap_groups_count=quantity_gap_count,
            proceeds_delta_groups_count=raw_proceeds_count,
            reconciled_proceeds_delta_groups_count=reconciled_proceeds_count,
            unexplained_proceeds_delta_groups_count=unexplained_proceeds_count,
            quote_asset_fee_netting_groups_count=quote_fee_group_count,
            quote_asset_fee_netting_events_count=sum(
                group.quote_asset_fee_events_count for group in groups
            ),
            pool_reordering_groups_count=pool_count,
            exact_groups_count=exact_count,
            compared_events_count=sum(group.compared_events_count for group in groups),
            global_gain_loss_eur=global_gain,
            wallet_gain_loss_eur=wallet_gain,
            gain_loss_delta_eur=wallet_gain - global_gain,
            global_proceeds_eur=global_proceeds,
            wallet_proceeds_eur=wallet_proceeds,
            turnover_delta_eur=wallet_proceeds - global_proceeds,
            proceeds_contribution_to_gain_delta_eur=(
                wallet_proceeds - global_proceeds
            ),
            unexplained_proceeds_delta_eur=sum(
                (group.unexplained_proceeds_delta_eur for group in groups),
                Decimal("0"),
            ),
            global_cost_basis_eur=global_basis,
            wallet_cost_basis_eur=wallet_basis,
            cost_basis_delta_eur=wallet_basis - global_basis,
            cost_basis_contribution_to_gain_delta_eur=(
                global_basis - wallet_basis
            ),
            extra_turnover_detected=(
                wallet_proceeds - global_proceeds > self.PROCEEDS_TOLERANCE_EUR
            ),
            material_turnover_delta_detected=(
                abs(wallet_proceeds - global_proceeds)
                > self.PROCEEDS_TOLERANCE_EUR
            ),
            groups=groups,
            source_run_report_url=source_run_report_url,
            full_event_csv_download_url=full_event_csv_download_url,
            findings=findings,
            methodology=(
                "Read-only Erklaerung der Differenz zwischen produktiver globaler Asset-FIFO und "
                "Wallet-/Depot-FIFO desselben versionierten Laufs. Veraeusserungen werden ueber "
                "source_event_id verglichen; Menge, Erlos, Cost Basis, Anschaffungszeitraum, "
                "Anschaffungs-Event und Wallet-Pool bleiben getrennt sichtbar. "
                "Quote-Asset-Gebuehren und mengenproportionale Erloszuordnungen werden "
                "gegen den Canonical Event rechnerisch reconciled; nur der danach "
                "verbleibende unerklaerte Erlosrest ist ein Bewertungsreview. "
                "pool_fifo_cost_basis_reordering bedeutet bei Ereignis-, Mengen- und Erlosparitaet "
                "keinen zusaetzlichen Umsatz, sondern den Verbrauch anderer historischer Lots. "
                "Der Report schreibt keine Steuer-, Ledger-, Import- oder Preisdaten und nimmt "
                "keine steuerliche Methodenwahl vor."
            ),
        )
        semantic_payload = report.model_dump(
            mode="json",
            exclude={
                "semantic_sha256",
                "generated_at",
                "run_id",
                "source_run_report_url",
                "full_event_csv_download_url",
            },
        )
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return report.model_copy(update={"semantic_sha256": semantic_sha256})

    def _filter_method_delta_report(
        self,
        report: WalletFifoMethodDeltaExplanationReport,
        *,
        year: int | None,
        asset: str | None,
        event_limit: int,
    ) -> WalletFifoMethodDeltaExplanationReport:
        normalized_asset = asset.strip().upper() if asset else None
        groups = [
            group.model_copy(update={"top_events": group.top_events[:event_limit]})
            for group in report.groups
            if (year is None or group.year == year)
            and (normalized_asset is None or group.asset == normalized_asset)
        ]
        return self._method_delta_report_from_groups(
            run_id=report.run_id,
            generated_at=report.generated_at,
            as_of=report.as_of,
            method_version=report.method_version,
            input_fingerprint_digest=report.input_fingerprint_digest,
            material_threshold=report.material_delta_threshold_eur,
            groups=groups,
            source_run_report_url=report.source_run_report_url,
            full_event_csv_download_url=report.full_event_csv_download_url,
        )

    @staticmethod
    def _groups_with_driver(
        groups: list[WalletFifoMethodDeltaGroup], driver: str
    ) -> int:
        return sum(driver in group.drivers for group in groups)

    @staticmethod
    def _method_delta_explanation_text(drivers: list[str]) -> str:
        if "quantity_gap" in drivers and "quantity_proceeds_allocation" in drivers:
            return (
                "Eine Teilmenge fehlt in einer Methode. Das zugehoerige Erlosdelta ist "
                "mengenproportional vollstaendig erklaert; die Mengenherkunft bleibt zu schliessen."
            )
        if "event_set_gap" in drivers or "quantity_gap" in drivers:
            return (
                "Mindestens eine Veraeusserung oder Teilmenge fehlt in einer Methode; "
                "dieser Anteil ist vor einer Methodenentscheidung fachlich zu schliessen."
            )
        if "proceeds_valuation_delta" in drivers:
            return (
                "Die Veraeusserungserloese unterscheiden sich materiell; UTC-Zeitpunkt, "
                "Preisquelle und Gebuehrenbehandlung sind zu pruefen."
            )
        if "quote_asset_fee_netting" in drivers:
            return (
                "Das Erlosdelta entspricht exakt der im erhaltenen Quote-Asset "
                "einbehaltenen Handelsgebuehr; Preis und UTC-Zeitpunkt erzeugen keinen Rest."
            )
        if "pool_fifo_cost_basis_reordering" in drivers:
            return (
                "Veraeusserungsereignis, Menge und Erlos stimmen ueberein. Die Abweichung "
                "entsteht durch andere historische Anschaffungslots im getrennten Wallet-/Depot-Pool."
            )
        if "explicit_fee_treatment" in drivers:
            return (
                "Die Wallet-FIFO weist den Verbrauch des Gebuehren-Assets als eigene, "
                "explizit erkennbare Veraeusserungszeile aus."
            )
        if "rounding_only" in drivers:
            return "Die verbleibende Differenz liegt innerhalb der definierten Mengen-/Erlostoleranzen."
        return "Beide Methoden stimmen fuer diese Gruppe exakt ueberein."

    @staticmethod
    def _method_delta_findings(
        *,
        groups: list[WalletFifoMethodDeltaGroup],
        event_gap_count: int,
        quantity_gap_count: int,
        raw_proceeds_count: int,
        reconciled_proceeds_count: int,
        unexplained_proceeds_count: int,
        quote_fee_group_count: int,
        pool_count: int,
        global_proceeds: Decimal,
        wallet_proceeds: Decimal,
        global_basis: Decimal,
        wallet_basis: Decimal,
    ) -> list[str]:
        findings: list[str] = []
        if pool_count:
            findings.append(
                f"{pool_count} Jahr-/Asset-Gruppen unterscheiden sich bei gleichen "
                "Veraeusserungen primaer durch die FIFO-Lot-Reihenfolge je Wallet/Depot."
            )
        proceeds_delta = wallet_proceeds - global_proceeds
        basis_contribution = global_basis - wallet_basis
        if proceeds_delta <= Decimal("0.01"):
            findings.append(
                "Ueber die Auswahl entsteht kein zusaetzlicher Veraeusserungsumsatz; "
                f"das Erlosdelta betraegt {proceeds_delta} EUR."
            )
        findings.append(
            "Das Ergebnisdelta zerfaellt rechnerisch in "
            f"{proceeds_delta} EUR Erlosbeitrag und {basis_contribution} EUR "
            "Cost-Basis-Beitrag."
        )
        if event_gap_count or quantity_gap_count:
            findings.append(
                f"{event_gap_count} Ereignismengen- und {quantity_gap_count} Mengengruppen "
                "benoetigen vor einer Methodenabnahme eine Primaerdatenklaerung."
            )
        if raw_proceeds_count and reconciled_proceeds_count:
            findings.append(
                f"{reconciled_proceeds_count} von {raw_proceeds_count} materiellen "
                "Erlosdelta-Gruppen sind durch Quote-Asset-Gebuehr oder Mengenallokation reconciled."
            )
        if quote_fee_group_count:
            findings.append(
                f"{quote_fee_group_count} Gruppen enthalten belegte Quote-Asset-Gebuehren."
            )
        if unexplained_proceeds_count:
            findings.append(
                f"{unexplained_proceeds_count} Gruppen besitzen nach der Reconciliation "
                "weiter ein unerklaertes Erlosdelta ueber 0,01 EUR."
            )
        if groups:
            findings.append(
                "Die produktiven tax_lots und tax_lines verwenden weiterhin unveraendert die globale Asset-FIFO."
            )
        return findings

    @staticmethod
    def _is_explicit_fee_line(line: WalletFifoPreviewLine) -> bool:
        return line.source_event_id.startswith(
            ("external:", "solana-program-escrow:", "cross-cex:")
        ) and line.source_event_id.endswith(":fee")

    def _write_evidence_files(
        self,
        run_dir: Path,
        state: WalletFifoReplayState,
        asset_reconciliations: list[WalletFifoAssetReconciliation],
        method_delta_report: WalletFifoMethodDeltaExplanationReport,
        method_delta_events: list[WalletFifoMethodDeltaEvent],
    ) -> list[WalletFifoEvidenceFile]:
        return [
            self._write_csv_gzip(
                run_dir / "wallet_fifo_tax_lines.csv.gz",
                "wallet_fifo_tax_lines",
                state.tax_lines,
                list(WalletFifoPreviewLine.model_fields),
                {"tax_line_id", "lot_id", "origin_lot_id"},
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_all_lots.csv.gz",
                "wallet_fifo_all_lots",
                state.all_lots,
                list(WalletFifoPreviewLot.model_fields),
                {"lot_id", "origin_lot_id"},
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_open_lots.csv.gz",
                "wallet_fifo_open_lots",
                state.open_lots,
                list(WalletFifoPreviewLot.model_fields),
                {"lot_id", "origin_lot_id"},
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_transfer_traces.csv.gz",
                "wallet_fifo_transfer_traces",
                state.transfer_traces,
                list(WalletFifoTransferTrace.model_fields),
                set(),
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_unmatched.csv.gz",
                "wallet_fifo_unmatched",
                state.unmatched,
                list(WalletFifoPreviewUnmatched.model_fields),
                set(),
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_year_asset_deltas.csv.gz",
                "wallet_fifo_year_asset_deltas",
                state.year_deltas,
                list(WalletFifoYearDelta.model_fields),
                set(),
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_asset_reconciliation.csv.gz",
                "wallet_fifo_asset_reconciliation",
                asset_reconciliations,
                list(WalletFifoAssetReconciliation.model_fields),
                set(),
            ),
            self._write_csv_gzip(
                run_dir / "wallet_fifo_method_delta_events.csv.gz",
                "wallet_fifo_method_delta_events",
                method_delta_events,
                list(WalletFifoMethodDeltaEvent.model_fields),
                set(),
            ),
            self._write_json_evidence(
                run_dir / "wallet_fifo_method_delta_explanation.json",
                "wallet_fifo_method_delta_explanation",
                method_delta_report,
                records_count=method_delta_report.groups_count,
                semantic_sha256=method_delta_report.semantic_sha256,
            ),
        ]

    def _write_json_evidence(
        self,
        path: Path,
        kind: str,
        report: BaseModel,
        *,
        records_count: int,
        semantic_sha256: str,
    ) -> WalletFifoEvidenceFile:
        content = json.dumps(
            report.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")
        self._atomic_write(path, content)
        return WalletFifoEvidenceFile(
            kind=kind,
            path=self._display_path(path),
            media_type="application/json",
            records_count=records_count,
            size_bytes=path.stat().st_size,
            sha256=self._file_sha256(path),
            semantic_sha256=semantic_sha256,
        )

    def _write_csv_gzip(
        self,
        path: Path,
        kind: str,
        records: Iterable[BaseModel],
        fieldnames: list[str],
        semantic_excluded_fields: set[str],
    ) -> WalletFifoEvidenceFile:
        tmp_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        semantic_hasher = hashlib.sha256()
        count = 0
        with tmp_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n")
                    writer.writeheader()
                    for record in records:
                        row = record.model_dump(mode="json")
                        writer.writerow({key: self._csv_value(row.get(key)) for key in fieldnames})
                        semantic_row = {
                            key: row.get(key)
                            for key in fieldnames
                            if key not in semantic_excluded_fields
                        }
                        semantic_hasher.update(
                            json.dumps(
                                semantic_row,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=True,
                            ).encode("utf-8")
                        )
                        semantic_hasher.update(b"\n")
                        count += 1
        tmp_path.replace(path)
        return WalletFifoEvidenceFile(
            kind=kind,
            path=self._display_path(path),
            media_type="text/csv+gzip",
            records_count=count,
            size_bytes=path.stat().st_size,
            sha256=self._file_sha256(path),
            semantic_sha256=semantic_hasher.hexdigest(),
        )

    def _write_csv_bytes_gzip(
        self,
        path: Path,
        kind: str,
        content: bytes,
        *,
        records_count: int,
        semantic_sha256: str,
    ) -> WalletFifoEvidenceFile:
        tmp_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        with tmp_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                compressed.write(content)
        tmp_path.replace(path)
        return WalletFifoEvidenceFile(
            kind=kind,
            path=self._display_path(path),
            media_type="text/csv+gzip",
            records_count=records_count,
            size_bytes=path.stat().st_size,
            sha256=self._file_sha256(path),
            semantic_sha256=semantic_sha256,
        )

    @staticmethod
    def _semantic_digest(
        *,
        as_of: datetime,
        years: list[int],
        threshold: Decimal,
        fingerprint: WalletFifoRunInputFingerprint,
        year_results: list[WalletFifoRunYearResult],
        evidence_files: list[WalletFifoEvidenceFile],
    ) -> str:
        payload = {
            "method_version": WalletFifoPreviewService.METHOD_VERSION,
            "as_of": as_of.isoformat(),
            "years": years,
            "threshold": str(threshold),
            "input_fingerprint": fingerprint.digest,
            "year_results": [item.model_dump(mode="json") for item in year_results],
            "evidence_semantic_hashes": {
                item.kind: item.semantic_sha256 for item in evidence_files
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _findings(
        *,
        blocked_years: list[int],
        material_years: list[int],
        event_set_mismatch_years: list[int],
        unmatched_count: int,
        provider_basis_gap_count: int,
        unexplained_unmatched_count: int,
        unresolved_count: int,
        transfer_evidence_review_count: int,
        acquisition_cost_evidence_review_count: int,
        valuation_review_years: list[int],
    ) -> list[str]:
        findings: list[str] = []
        if provider_basis_gap_count:
            findings.append(
                f"{provider_basis_gap_count} Bitget-Strategy-Abgaenge sind mengenmaessig "
                "vollstaendig belegten Settlements zugeordnet; offen ist ausschliesslich "
                "die vom Provider nicht exportierte Bot-Fill-Kostenbasis."
            )
        if unexplained_unmatched_count:
            findings.append(
                f"{unexplained_unmatched_count} Wallet-Pool-Abgaenge besitzen weder ein "
                "vollstaendig passendes Lot noch eine belegte Provider-Basisluecke."
            )
        if unmatched_count != provider_basis_gap_count + unexplained_unmatched_count:
            findings.append(
                "Die Klassifikation der offenen Wallet-Pool-Abgaenge ist rechnerisch inkonsistent."
            )
        if unresolved_count:
            findings.append(f"{unresolved_count} eingehende Transfers haben noch keine belastbare Herkunft.")
        if transfer_evidence_review_count:
            findings.append(
                f"{transfer_evidence_review_count} Cross-CEX-Transfers sind rechnerisch verknuepft; "
                "Withdrawal-TXID/Adresse bleibt als Belegreview offen."
            )
        if acquisition_cost_evidence_review_count:
            findings.append(
                f"{acquisition_cost_evidence_review_count} Anschaffungs- oder Reward-Komponenten "
                "verwenden eine vorlaeufige Kostenbasis; der zugehoerige Primaerbeleg ist noch zuzuordnen."
            )
        if material_years:
            findings.append(
                "Materielle Abweichung zur globalen FIFO in: "
                + ", ".join(str(year) for year in material_years)
                + "."
            )
        if event_set_mismatch_years:
            findings.append(
                "Mengenparitaet fehlt in: "
                + ", ".join(str(year) for year in event_set_mismatch_years)
                + "."
            )
        else:
            findings.append("Die Veraeusserungsmengen sind nach Abzug expliziter Netzwerkgebuehren je Jahr/Asset paritaetisch.")
        if valuation_review_years:
            findings.append(
                "Bewertungserloese unterscheiden sich trotz gleicher Mengen in: "
                + ", ".join(str(year) for year in valuation_review_years)
                + "; Preisquelle und korrigierter UTC-Zeitpunkt sind separat zu pruefen."
            )
        if not blocked_years and not material_years:
            findings.append("Der Parallel-Run ist rechnerisch bereit fuer die fachliche Methodenpruefung.")
        findings.append("Die produktiven tax_lots und tax_lines verwenden weiterhin die globale Asset-FIFO.")
        return findings

    @staticmethod
    def _next_actions(
        blocked_years: list[int],
        material_years: list[int],
        *,
        provider_basis_gap_count: int,
        unexplained_unmatched_count: int,
        acquisition_cost_evidence_review_count: int,
        valuation_review_years: list[int],
    ) -> list[str]:
        actions: list[str] = []
        if unexplained_unmatched_count:
            actions.append("Pool-Luecken und offene Transfer-Herkunft der blockierten Jahre schliessen.")
        if provider_basis_gap_count:
            actions.append(
                "Bitget-Strategy-Kostenbasis anhand der vorhandenen Rekonstruktionsakte "
                "fachlich entscheiden; keine weiteren Nutzerexporte anfordern und keine "
                "automatische Null- oder Marktwertbasis buchen."
            )
        elif blocked_years:
            actions.append(
                "Verbleibende technische Blocker der Wallet-FIFO-Jahre schliessen."
            )
        if material_years:
            actions.append("Delta je Jahr und Asset gegen Originalbelege und globale Lots erklaeren.")
        if acquisition_cost_evidence_review_count:
            actions.append(
                "Offene Fiat-Onramp- oder Staking-Reward-Belege der vorlaeufigen Kostenbasis zuordnen."
            )
        if valuation_review_years:
            actions.append("Bewertungsdeltas gegen UTC-Quellzeit, Preisquelle und USD/EUR-FX belegen.")
        actions.append("Wallet-/Depot-Methode fachlich abnehmen, bevor sie produktive Steuerwerte ersetzt.")
        return actions

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(path)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _csv_value(value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return value

    @staticmethod
    def _json_values(row: tuple[object, ...] | None) -> list[object]:
        if row is None:
            return []
        return [value.isoformat() if isinstance(value, datetime) else value for value in row]

    @staticmethod
    def _utc_datetime(value: object) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
