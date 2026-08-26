from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from steuerreport_v2.contracts.valuation_runs import (
    DivorceValuationEvidenceFile,
    DivorceValuationFifoCheckpoint,
    DivorceValuationRunReport,
    DivorceValuationRunRequest,
)
from steuerreport_v2.contracts.source_registry import SourceRegistryRunReport
from steuerreport_v2.contracts.wallet_fifo_runs import (
    WalletFifoParallelRunReport,
    WalletFifoParallelRunRequest,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget_strategy_fifo import BitgetStrategyFifoGapService
from steuerreport_v2.domain.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionService,
)
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.divorce_inheritance import (
    DivorceInheritanceOriginService,
)
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.solana_staking_position import (
    SolanaStakingPositionReconciliationService,
)
from steuerreport_v2.domain.tax_time import event_reporting_year_sql
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)


class DivorceValuationRunService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/valuation_runs"

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
        wallet_fifo_artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()
        self.wallet_fifo_service = WalletFifoParallelRunService(
            store,
            artifact_root=wallet_fifo_artifact_root,
        )

    def run(self, request: DivorceValuationRunRequest) -> DivorceValuationRunReport:
        generated_at = datetime.now(timezone.utc)
        divorce_service = DivorceEqualizationService(self.store)
        summary = divorce_service.summary(
            separation_date=request.separation_date,
            end_asset_date=request.end_asset_date,
            court_evidence_reference=request.court_evidence_reference,
            cutoff_at=request.cutoff_at,
            valuation_at=request.valuation_at,
            materiality_threshold_eur=request.materiality_threshold_eur,
        )
        source_registry = SourceRegistryService(self.store).run()
        cutoff_years = self._years_through(summary.cutoff_at)
        valuation_years = self._years_through(summary.valuation_at)
        cutoff_request = WalletFifoParallelRunRequest(
            years=cutoff_years,
            as_of=summary.cutoff_at,
            material_delta_threshold_eur=request.material_delta_threshold_eur,
        )
        cutoff_fifo = self.wallet_fifo_service.find_reusable_run(cutoff_request)
        cutoff_reused = cutoff_fifo is not None
        if cutoff_fifo is None:
            cutoff_fifo = self.wallet_fifo_service.run(cutoff_request)
        valuation_request = WalletFifoParallelRunRequest(
            years=valuation_years,
            as_of=summary.valuation_at,
            material_delta_threshold_eur=request.material_delta_threshold_eur,
        )
        valuation_fifo = self.wallet_fifo_service.find_reusable_run(
            valuation_request
        )
        valuation_reused = valuation_fifo is not None
        if valuation_fifo is None:
            valuation_fifo = self.wallet_fifo_service.run(valuation_request)
        bitget_strategy_service = BitgetStrategyFifoGapService(
            self.store,
            artifact_root=self.wallet_fifo_service.artifact_root,
        )
        bitget_strategy_reports = {
            "cutoff": bitget_strategy_service.report(run_id=cutoff_fifo.run_id),
            "valuation": bitget_strategy_service.report(run_id=valuation_fifo.run_id),
        }
        checkpoints = [
            self._fifo_checkpoint(
                "cutoff",
                cutoff_fifo,
                cutoff_reused,
                self._method_gap_classification(
                    cutoff_fifo, bitget_strategy_reports["cutoff"]
                ),
            ),
            self._fifo_checkpoint(
                "valuation",
                valuation_fifo,
                valuation_reused,
                self._method_gap_classification(
                    valuation_fifo, bitget_strategy_reports["valuation"]
                ),
            ),
        ]
        bitget_reconstruction_service = BitgetStrategyBasisReconstructionService(
            self.store,
            artifact_root=self.wallet_fifo_service.artifact_root,
        )
        bitget_reconstruction_reports = {
            checkpoint.label: bitget_reconstruction_service.report(
                run_id=checkpoint.run_id
            )
            for checkpoint in checkpoints
        }
        bitget_support_package = next(
            (
                report.support_package
                for report in bitget_strategy_reports.values()
                if report is not None
            ),
            None,
        )
        bitget_support_package_zip = (
            bitget_strategy_service.support_package_zip_bytes(bitget_support_package)
            if bitget_support_package is not None
            else None
        )
        latest_fifo_path = Path(valuation_fifo.latest_artifact_path)
        if not latest_fifo_path.is_absolute():
            latest_fifo_path = self.PROJECT_ROOT / latest_fifo_path
        solana_staking_position = SolanaStakingPositionReconciliationService(
            self.store,
            latest_wallet_fifo_path=latest_fifo_path,
        ).report()
        moonpay_service = MoonpayReceiptService(self.store)
        moonpay_report = moonpay_service.report(as_of=summary.valuation_at)
        moonpay_evidence_active = bool(
            moonpay_report.candidates_count
            or summary.confirmed_onramp_invest_since_cutoff_eur
            or summary.provisional_onramp_invest_since_cutoff_eur
        )
        moonpay_trade_history_content = self._moonpay_trade_history_content(
            moonpay_service,
            moonpay_report if moonpay_evidence_active else None,
        )
        strict_ready = (
            summary.cutoff_price_gate.strict_ready
            and summary.valuation_price_gate.strict_ready
            and summary.capital_flow_gate.strict_ready
            and summary.inheritance_origin_gate.strict_ready
            and summary.stichtage.court_evidence_status == "documented"
            and source_registry.strict_ready
            and all(item.strict_ready for item in checkpoints)
        )
        has_blocker = (
            not summary.cutoff_price_gate.strict_ready
            or not summary.valuation_price_gate.strict_ready
            or not summary.capital_flow_gate.strict_ready
            or not summary.inheritance_origin_gate.strict_ready
            or summary.stichtage.court_evidence_status != "documented"
            or not source_registry.strict_ready
            or any(item.status == "blocked" for item in checkpoints)
        )
        status = (
            "strict_ready" if strict_ready else "blocked" if has_blocker else "review"
        )
        source_accounts = sorted(
            {
                source_account
                for account in summary.accounts
                for source_account in account.source_accounts
            }
        )
        semantic_sha256 = self._semantic_digest(
            summary=summary.model_dump(mode="json"),
            checkpoints=checkpoints,
            bitget_strategy_reports=bitget_strategy_reports,
            bitget_reconstruction_reports=bitget_reconstruction_reports,
            source_registry_semantic_sha256=source_registry.semantic_sha256,
            solana_staking_semantic_sha256=solana_staking_position.semantic_sha256,
            moonpay_semantic_sha256=(
                moonpay_report.semantic_sha256 if moonpay_evidence_active else None
            ),
            material_delta_threshold_eur=request.material_delta_threshold_eur,
        )
        run_id = (
            f"valuation-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{semantic_sha256[:12]}-{uuid4().hex[:8]}"
        )
        run_dir = self.artifact_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        evidence_files = self._write_evidence_files(
            run_id=run_id,
            run_dir=run_dir,
            summary=summary,
            checkpoints=checkpoints,
            bitget_strategy_reports=bitget_strategy_reports,
            bitget_reconstruction_reports=bitget_reconstruction_reports,
            bitget_support_package=bitget_support_package,
            bitget_support_package_zip=bitget_support_package_zip,
            divorce_service=divorce_service,
            source_accounts=source_accounts,
            source_registry=source_registry,
            solana_staking_position=solana_staking_position,
            moonpay_report=moonpay_report if moonpay_evidence_active else None,
            moonpay_trade_history_content=moonpay_trade_history_content,
        )
        artifact_path = run_dir / "valuation_run.json"
        latest_path = self.artifact_root / "latest_valuation_gate.json"
        findings = self._findings(summary, checkpoints)
        if not solana_staking_position.strict_ready:
            findings.append(
                "Solana-Staking-Principal-/Reward-Nachweis ist noch nicht vollstaendig freigegeben."
            )
        report = DivorceValuationRunReport(
            run_id=run_id,
            generated_at=generated_at,
            status=status,
            strict_ready=strict_ready,
            cutoff_at=summary.cutoff_at,
            valuation_at=summary.valuation_at,
            materiality_threshold_eur=request.materiality_threshold_eur,
            material_delta_threshold_eur=request.material_delta_threshold_eur,
            cutoff_value_eur=summary.cutoff_portfolio_value_eur,
            valuation_value_eur=summary.valuation_portfolio_value_eur,
            gross_change_eur=summary.gross_portfolio_change_eur,
            external_invest_eur=summary.net_external_invest_since_cutoff_eur,
            adjusted_gain_loss_eur=summary.adjusted_gain_loss_excluding_new_invest_eur,
            cutoff_price_gate=summary.cutoff_price_gate,
            valuation_price_gate=summary.valuation_price_gate,
            fifo_checkpoints=checkpoints,
            source_registry_status=source_registry.status,
            source_registry_strict_ready=source_registry.strict_ready,
            source_provider_coverage_gap_count=(
                source_registry.provider_coverage_gap_entries_count
            ),
            source_user_evidence_gap_count=(
                source_registry.user_evidence_gap_entries_count
            ),
            source_quantity_blocker_count=(
                source_registry.quantity_blocker_entries_count
            ),
            source_registry_semantic_sha256=source_registry.semantic_sha256,
            source_accounts=source_accounts,
            semantic_sha256=semantic_sha256,
            evidence_files=evidence_files,
            artifact_path=self._display_path(artifact_path),
            latest_artifact_path=self._display_path(latest_path),
            findings=[
                *findings,
                *[f"Quellenregistry: {item}" for item in source_registry.findings],
            ],
            next_actions=self._next_actions(
                summary, checkpoints, source_registry
            ),
            methodology=(
                "Versionierter read-only Stichtagslauf. Mengen und Marktwerte werden fuer den "
                "Trennungs- und Endvermoegensstichtag aus Canonical Events, Balance-Ledger und dem letzten "
                "Preis am oder vor dem jeweiligen Stichtag rekonstruiert. Preisalter und Tokenrisiken "
                "werden durch ein Materialitaets-Gate geprueft. Ein separates Vermoegensfluss-Gate "
                "trennt externe Einzahlungen und Auszahlungen von internen Transfers, "
                "Produktumbuchungen und technischen Gebuehren. Zwei separate Wallet-/Depot-FIFO-"
                "Replays belegen offene Lots, Verbrauchsfolgen und Transferfortfuehrung genau bis zu "
                "den nach Europe/Berlin bestimmten und in UTC gespeicherten Tagesenden. Ein bereits "
                "vorhandener Lauf darf nur bei identischem Stichtag, Methodencode, Schwellwert und "
                "semantischem Eingabefingerprint sowie intakten SHA-256-geprueften Belegdateien "
                "wiederverwendet werden. Der Lauf veraendert keine Import-, Ledger-, Preis- oder "
                "Steuerdaten."
            ),
            summary=summary,
        )
        content = json.dumps(
            report.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")
        self._atomic_write(artifact_path, content)
        self._atomic_write(latest_path, content)
        return report

    def latest(self) -> DivorceValuationRunReport | None:
        path = self.artifact_root / "latest_valuation_gate.json"
        try:
            return DivorceValuationRunReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def get(self, run_id: str) -> DivorceValuationRunReport | None:
        if not run_id.startswith("valuation-"):
            return None
        path = self.artifact_root / run_id / "valuation_run.json"
        try:
            return DivorceValuationRunReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def evidence_path(self, run_id: str, filename: str) -> Path | None:
        report = self.get(run_id)
        if report is None:
            return None
        allowed = {Path(item.path).name for item in report.evidence_files}
        if filename not in allowed:
            return None
        root = self.artifact_root.resolve()
        path = (root / run_id / filename).resolve()
        if path.parent != (root / run_id).resolve() or not path.is_file():
            return None
        return path

    def _write_evidence_files(
        self,
        *,
        run_id: str,
        run_dir: Path,
        summary: object,
        checkpoints: list[DivorceValuationFifoCheckpoint],
        bitget_strategy_reports: dict[str, object | None],
        bitget_reconstruction_reports: dict[str, object | None],
        bitget_support_package: object | None,
        bitget_support_package_zip: bytes | None,
        divorce_service: DivorceEqualizationService,
        source_accounts: list[str],
        source_registry: object,
        solana_staking_position: object,
        moonpay_report: object | None,
        moonpay_trade_history_content: bytes | None,
    ) -> list[DivorceValuationEvidenceFile]:
        payloads: dict[str, tuple[str, str, bytes]] = {
            "equalization_summary.json": (
                "summary",
                "application/json",
                json.dumps(
                    summary.model_dump(mode="json"), indent=2, ensure_ascii=False
                ).encode("utf-8"),
            ),
            "accounts.csv": (
                "accounts",
                "text/csv",
                divorce_service._accounts_csv_for_report(summary).encode("utf-8"),
            ),
            "valuation_tokens.csv": (
                "valuation_tokens",
                "text/csv",
                divorce_service._valuation_tokens_csv_for_report(summary).encode(
                    "utf-8"
                ),
            ),
            "price_gates.json": (
                "price_gates",
                "application/json",
                json.dumps(
                    {
                        "cutoff": summary.cutoff_price_gate.model_dump(mode="json"),
                        "valuation": summary.valuation_price_gate.model_dump(
                            mode="json"
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "stichtag_token_valuation_decisions.csv": (
                "stichtag_token_valuation_decisions",
                "text/csv",
                divorce_service.token_valuation_service.decisions_csv(
                    {
                        summary.stichtage.separation_date,
                        summary.stichtage.end_asset_date,
                    }
                ).encode("utf-8"),
            ),
            "capital_flow_reconciliation.json": (
                "capital_flow_reconciliation",
                "application/json",
                json.dumps(
                    summary.capital_flow_gate.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "capital_flow_reconciliation.csv": (
                "capital_flow_reconciliation",
                "text/csv",
                divorce_service._capital_flows_csv_for_report(summary).encode("utf-8"),
            ),
            "service_route_evidence.json": (
                "service_route_evidence",
                "application/json",
                divorce_service._service_route_evidence_json_for_report(summary),
            ),
            "inheritance_origin.json": (
                "inheritance_origin",
                "application/json",
                json.dumps(
                    summary.inheritance_origin_gate.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "inheritance_origin.csv": (
                "inheritance_origin",
                "text/csv",
                DivorceInheritanceOriginService.csv_for_report(
                    summary.inheritance_origin_gate
                ).encode("utf-8"),
            ),
            "inheritance_credit_evidence.csv": (
                "inheritance_credit_evidence",
                "text/csv",
                DivorceInheritanceOriginService.inheritance_credits_csv_for_report(
                    summary.inheritance_origin_gate
                ).encode("utf-8"),
            ),
            "trade_republic_document_evidence.csv": (
                "trade_republic_document_evidence",
                "text/csv",
                DivorceInheritanceOriginService.trade_republic_documents_csv_for_connector(
                    summary.inheritance_origin_gate.trade_republic_connector
                ).encode("utf-8"),
            ),
            "formal_inheritance_document_evidence.csv": (
                "formal_inheritance_document_evidence",
                "text/csv",
                DivorceInheritanceOriginService.inheritance_documents_csv_for_connector(
                    summary.inheritance_origin_gate.formal_inheritance_connector
                ).encode("utf-8"),
            ),
            "coinbase_history_valuation_evidence.csv": (
                "coinbase_history_valuation_evidence",
                "text/csv",
                DivorceInheritanceOriginService.coinbase_connector_csv_for_connector(
                    summary.inheritance_origin_gate.coinbase_connector
                ).encode("utf-8"),
            ),
            "fifo_checkpoints.json": (
                "fifo_checkpoints",
                "application/json",
                json.dumps(
                    [item.model_dump(mode="json") for item in checkpoints],
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "source_manifest.json": (
                "source_manifest",
                "application/json",
                json.dumps(
                    {
                        "stichtage": summary.stichtage.model_dump(mode="json"),
                        "cutoff_at": summary.cutoff_at.isoformat(),
                        "valuation_at": summary.valuation_at.isoformat(),
                        "source_accounts": source_accounts,
                        "accounts": [
                            {
                                "account": account.account,
                                "source_accounts": account.source_accounts,
                                "classification": account.classification,
                                "cutoff_assets": account.asset_labels_cutoff,
                                "valuation_assets": account.asset_labels_valuation,
                            }
                            for account in summary.accounts
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "source_registry.json": (
                "source_registry",
                "application/json",
                json.dumps(
                    source_registry.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "solana_staking_position_reconciliation.json": (
                "solana_staking_position_reconciliation",
                "application/json",
                json.dumps(
                    solana_staking_position.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
        }
        if moonpay_report is not None:
            payloads["moonpay_receipt_reconciliation.json"] = (
                "moonpay_receipt_reconciliation",
                "application/json",
                json.dumps(
                    moonpay_report.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        for label, bitget_report in bitget_strategy_reports.items():
            if bitget_report is None:
                continue
            payloads[f"bitget_strategy_fifo_gaps_{label}.json"] = (
                "bitget_strategy_fifo_gaps",
                "application/json",
                json.dumps(
                    bitget_report.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        for label, reconstruction in bitget_reconstruction_reports.items():
            if reconstruction is None:
                continue
            payloads[f"bitget_strategy_basis_reconstruction_{label}.json"] = (
                "bitget_strategy_basis_reconstruction",
                "application/json",
                json.dumps(
                    reconstruction.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            payloads[f"bitget_strategy_basis_reconstruction_{label}.csv"] = (
                "bitget_strategy_basis_reconstruction",
                "text/csv",
                BitgetStrategyBasisReconstructionService.csv_bytes(reconstruction),
            )
        if bitget_support_package is not None:
            payloads["bitget_support_package_manifest.json"] = (
                "bitget_support_package_manifest",
                "application/json",
                json.dumps(
                    bitget_support_package.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        if bitget_support_package_zip is not None:
            payloads["bitget_support_package.zip"] = (
                "bitget_support_package",
                "application/zip",
                bitget_support_package_zip,
            )
        if moonpay_trade_history_content is not None:
            payloads["moonpay_trade_history.csv"] = (
                "moonpay_trade_history",
                "text/csv",
                moonpay_trade_history_content,
            )
        manifest = {
            "run_id": run_id,
            "read_only": True,
            "files": [
                {
                    "filename": filename,
                    "kind": kind,
                    "media_type": media_type,
                    "sha256": self._sha256(content),
                }
                for filename, (kind, media_type, content) in payloads.items()
            ],
            "wallet_fifo_runs": [item.model_dump(mode="json") for item in checkpoints],
        }
        payloads["manifest.json"] = (
            "manifest",
            "application/json",
            json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        )
        for filename, (_kind, _media_type, content) in payloads.items():
            self._atomic_write(run_dir / filename, content)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(
            zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as package:
            for filename, (_kind, _media_type, content) in payloads.items():
                package.writestr(filename, content)
        payloads["stichtag-zugewinn-dossier.zip"] = (
            "evidence_package",
            "application/zip",
            zip_buffer.getvalue(),
        )
        self._atomic_write(
            run_dir / "stichtag-zugewinn-dossier.zip", zip_buffer.getvalue()
        )
        return [
            DivorceValuationEvidenceFile(
                kind=kind,
                path=self._display_path(run_dir / filename),
                media_type=media_type,
                size_bytes=len(content),
                sha256=self._sha256(content),
                download_url=f"/api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}",
            )
            for filename, (kind, media_type, content) in payloads.items()
        ]

    def _years_through(self, as_of: datetime) -> list[int]:
        cutoff = self._naive(as_of)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select distinct {event_reporting_year_sql("event", "raw")}
                from canonical_events event
                left join raw_objects raw on raw.raw_object_id = event.raw_object_id
                where event.event_time <= ?
                order by 1
                """,
                [cutoff],
            ).fetchall()
        years = [int(row[0]) for row in rows if 2009 <= int(row[0]) <= as_of.year]
        return years or [as_of.year]

    @staticmethod
    def _fifo_checkpoint(
        label: str,
        report: WalletFifoParallelRunReport,
        reused_existing_run: bool = False,
        method_gap_classification: tuple[int, int, int, bool] = (0, 0, 0, False),
    ) -> DivorceValuationFifoCheckpoint:
        (
            provider_event_set_groups,
            provider_quantity_groups,
            unexplained_method_groups,
            method_gap_classification_complete,
        ) = method_gap_classification
        return DivorceValuationFifoCheckpoint(
            label=label,
            run_id=report.run_id,
            as_of=report.as_of,
            reused_existing_run=reused_existing_run,
            status=report.status,
            strict_ready=report.strict_ready,
            years=report.years,
            unmatched_count=report.unmatched_count,
            unmatched_classification_complete=(
                report.report_schema_version
                == WalletFifoParallelRunService.RUN_REPORT_VERSION
            ),
            provider_basis_gap_count=report.provider_basis_gap_count,
            unexplained_unmatched_count=report.unexplained_unmatched_count,
            unresolved_inbound_provenance_count=report.unresolved_inbound_provenance_count,
            transfer_evidence_review_count=report.transfer_evidence_review_count,
            acquisition_cost_evidence_review_count=report.acquisition_cost_evidence_review_count,
            event_set_mismatch_years=report.event_set_mismatch_years,
            valuation_review_years=report.valuation_review_years,
            method_gap_classification_complete=method_gap_classification_complete,
            provider_basis_event_set_gap_groups_count=provider_event_set_groups,
            provider_basis_quantity_gap_groups_count=provider_quantity_groups,
            unexplained_method_gap_groups_count=unexplained_method_groups,
            bitget_strategy_gap_status=report.bitget_strategy_gap_status,
            bitget_strategy_gap_quantity_reconciled=(
                report.bitget_strategy_gap_quantity_reconciled
            ),
            bitget_strategy_gap_groups_count=report.bitget_strategy_gap_groups_count,
            bitget_strategy_gap_linked_disposals_count=(
                report.bitget_strategy_gap_linked_disposals_count
            ),
            bitget_strategy_gap_unallocated_disposals_count=(
                report.bitget_strategy_gap_unallocated_disposals_count
            ),
            bitget_strategy_gap_semantic_sha256=(
                report.bitget_strategy_gap_semantic_sha256
            ),
            bitget_strategy_gap_report_url=report.bitget_strategy_gap_report_url,
            semantic_sha256=report.semantic_sha256,
            report_url=f"/api/v1/tax/wallet-fifo-runs/{report.run_id}",
            evidence_urls=[
                item.download_url for item in report.evidence_files if item.download_url
            ],
        )

    def _method_gap_classification(
        self,
        report: WalletFifoParallelRunReport,
        provider_gap: object | None,
    ) -> tuple[int, int, int, bool]:
        method_delta = self.wallet_fifo_service.method_delta_explanation(
            run_id=report.run_id,
            event_limit=self.wallet_fifo_service.METHOD_DELTA_TOP_EVENTS_PER_GROUP,
        )
        if method_delta is None:
            return 0, 0, 0, False
        provider_gap_event_ids = {
            disposal.source_event_id
            for group in (provider_gap.groups if provider_gap is not None else [])
            if group.quantity_reconciled
            and group.basis_gap_responsibility == "provider_export_field_gap"
            for disposal in group.linked_disposals
            if disposal.quantity_fully_allocated
        }
        classified = WalletFifoMethodAcceptanceService.classify_method_gap_groups(
            method_delta,
            provider_gap_event_ids=provider_gap_event_ids,
        )
        return *classified, True

    @staticmethod
    def _findings(
        summary: object, checkpoints: list[DivorceValuationFifoCheckpoint]
    ) -> list[str]:
        findings = [
            *[
                f"Trennungsstichtag: {item}"
                for item in summary.cutoff_price_gate.findings
            ],
            *[
                f"Endvermoegensstichtag: {item}"
                for item in summary.valuation_price_gate.findings
            ],
            *[
                f"Vermoegensfluss: {item}"
                for item in summary.capital_flow_gate.findings
            ],
            *[
                f"Erbgeld-Nachweis: {item}"
                for item in summary.inheritance_origin_gate.findings
            ],
        ]
        if summary.stichtage.court_evidence_status != "documented":
            findings.append(
                "Der Endvermoegensstichtag ist als Nutzerangabe erfasst; der Gerichts-/"
                "Zustellungsbeleg zur Rechtshaengigkeit ist noch nicht referenziert."
            )
        for checkpoint in checkpoints:
            if checkpoint.status == "blocked":
                blockers = []
                if checkpoint.provider_basis_gap_count:
                    blockers.append(
                        f"{checkpoint.provider_basis_gap_count} mengenbelegte "
                        "Provider-Kostenbasisluecken"
                    )
                if checkpoint.unexplained_unmatched_count:
                    blockers.append(
                        f"{checkpoint.unexplained_unmatched_count} wirklich "
                        "ungeklaerte Abgaenge"
                    )
                if checkpoint.unresolved_inbound_provenance_count:
                    blockers.append(
                        f"{checkpoint.unresolved_inbound_provenance_count} "
                        "ungeklaerte Zufluesse"
                    )
                if checkpoint.acquisition_cost_evidence_review_count:
                    blockers.append(
                        f"{checkpoint.acquisition_cost_evidence_review_count} "
                        "fehlende Anschaffungskostenbelege"
                    )
                if checkpoint.event_set_mismatch_years:
                    if (
                        checkpoint.method_gap_classification_complete
                        and checkpoint.unexplained_method_gap_groups_count == 0
                        and checkpoint.provider_basis_event_set_gap_groups_count
                    ):
                        blockers.append(
                            "providergebundene Ereignismengenabweichungen in "
                            + ", ".join(
                                str(year)
                                for year in checkpoint.event_set_mismatch_years
                            )
                        )
                    else:
                        blockers.append(
                            "nicht abschliessend klassifizierte "
                            "Ereignismengenabweichungen in "
                            + ", ".join(
                                str(year)
                                for year in checkpoint.event_set_mismatch_years
                            )
                        )
                findings.append(
                    f"FIFO {checkpoint.label} blockiert: {', '.join(blockers)}."
                )
            elif not checkpoint.strict_ready:
                findings.append(
                    f"FIFO {checkpoint.label} ist versioniert, aber noch nicht fachlich freigegeben."
                )
        return findings

    @staticmethod
    def _next_actions(
        summary: object,
        checkpoints: list[DivorceValuationFifoCheckpoint],
        source_registry: SourceRegistryRunReport,
    ) -> list[str]:
        actions: list[str] = []
        if not summary.cutoff_price_gate.strict_ready:
            actions.append(
                "Fehlende oder veraltete materielle Preise am Trennungsstichtag belegen."
            )
        if not summary.valuation_price_gate.strict_ready:
            actions.append(
                "Fehlende oder veraltete materielle Preise am Endvermoegensstichtag belegen."
            )
        if summary.capital_flow_gate.provisional_contributions_eur:
            actions.append(
                "Vorlaeufige MoonPay-/Apple-Pay-Zufluesse mit Zahlungsbetrag und Gebuehr belegen."
            )
        if summary.capital_flow_gate.capital_origin_pending_count:
            actions.append(
                "Kapitalherkunft der Zuflussgruppen als Erbe, eheliches oder sonstiges "
                "Vermoegen mit Beleg referenzieren."
            )
        if summary.capital_flow_gate.material_review_outflows_count:
            actions.append(
                "Materielle Abfluss-/Service-Ereignisse im Vermoegensfluss-Beleg als "
                "internen Verbleib oder externe Auszahlung klaeren."
            )
        actions.extend(summary.inheritance_origin_gate.next_actions)
        if summary.stichtage.court_evidence_status != "documented":
            actions.append(
                "Gerichts-/Zustellungsbeleg fuer den Endvermoegensstichtag referenzieren."
            )
        if source_registry.provider_coverage_gap_entries_count:
            actions.append(
                f"{source_registry.provider_coverage_gap_entries_count} dokumentierte "
                "Provider-Abdeckungsgrenze(n) fachlich behandeln; bereits gelieferte "
                "identische Nutzerexporte nicht erneut anfordern."
            )
        if source_registry.user_evidence_gap_entries_count:
            actions.append(
                f"Fuer {source_registry.user_evidence_gap_entries_count} Quelle(n) fehlt "
                "noch ein eigener Primaerbeleg oder eine vollstaendige Account-History."
            )
        if source_registry.quantity_blocker_entries_count:
            actions.append(
                f"{source_registry.quantity_blocker_entries_count} materielle "
                "Live-vs-Ledger-Mengendifferenz(en) mit Connector- oder Primaerbeleg klaeren."
            )
        actions.extend(
            f"Quellenregistry: {action}"
            for action in source_registry.next_actions
            if "API-Key/Secret" in action
            or "Connector-Live-Snapshot" in action
        )
        if any(item.provider_basis_gap_count for item in checkpoints):
            actions.append(
                "Providergebundene FIFO-Kostenbasisluecken mit dem vorhandenen Support-"
                "Dossier fachlich entscheiden; keine Anschaffungskosten erfinden."
            )
        if any(
            item.unexplained_unmatched_count
            or item.unresolved_inbound_provenance_count
            or item.unexplained_method_gap_groups_count
            or (
                item.event_set_mismatch_years
                and not item.method_gap_classification_complete
            )
            for item in checkpoints
        ):
            actions.append(
                "Wirklich ungeklaerte FIFO-Herkunfts- oder Ereignismengendifferenzen "
                "anhand der referenzierten Run-Belege schliessen."
            )
        if any(item.acquisition_cost_evidence_review_count for item in checkpoints):
            actions.append(
                "Fehlende Fiat-Onramp-/MoonPay-Zahlungsbelege den dokumentierten "
                "Anschaffungen zuordnen."
            )
        if not any(item.strict_ready for item in checkpoints):
            actions.append(
                "Wallet-/Depot-FIFO nach Delta-Erklaerung fachlich abnehmen; globale Steuer-FIFO bleibt unveraendert."
            )
        return actions

    @staticmethod
    def _semantic_digest(
        *,
        summary: dict[str, object],
        checkpoints: list[DivorceValuationFifoCheckpoint],
        bitget_strategy_reports: dict[str, object | None],
        bitget_reconstruction_reports: dict[str, object | None],
        source_registry_semantic_sha256: str,
        solana_staking_semantic_sha256: str,
        moonpay_semantic_sha256: str | None,
        material_delta_threshold_eur: Decimal,
    ) -> str:
        summary = dict(summary)
        summary.pop("generated_at", None)
        payload = {
            "summary": summary,
            "fifo": [
                {
                    "label": item.label,
                    "semantic_sha256": item.semantic_sha256,
                    "as_of": item.as_of.isoformat(),
                }
                for item in checkpoints
            ],
            "bitget_strategy_fifo": {
                label: (
                    report.semantic_sha256 if report is not None else None
                )
                for label, report in sorted(bitget_strategy_reports.items())
            },
            "bitget_strategy_basis_reconstruction": {
                label: (
                    report.semantic_sha256 if report is not None else None
                )
                for label, report in sorted(bitget_reconstruction_reports.items())
            },
            "source_registry_semantic_sha256": source_registry_semantic_sha256,
            "solana_staking_semantic_sha256": solana_staking_semantic_sha256,
            "moonpay_semantic_sha256": moonpay_semantic_sha256,
            "material_delta_threshold_eur": str(material_delta_threshold_eur),
        }
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _moonpay_trade_history_content(
        service: MoonpayReceiptService,
        report: object | None,
    ) -> bytes | None:
        if report is None or not report.trade_history_exists:
            return None
        content = service.trade_history_path.read_bytes()
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != report.trade_history_sha256:
            raise RuntimeError(
                "MoonPay Trade History changed while valuation evidence was created."
            )
        return content

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/valuation_runs"

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
