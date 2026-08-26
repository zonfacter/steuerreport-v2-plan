from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from steuerreport_v2.contracts.bitget_strategy_basis_decisions import (
    BitgetStrategyBasisDecisionCheck,
    BitgetStrategyBasisDecisionReport,
    BitgetStrategyBasisDecisionRequest,
    BitgetStrategyBasisDecisionResult,
    BitgetStrategyBasisDecisionStatus,
    BitgetStrategyBasisSelectedMethod,
)
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget_strategy_fifo import BitgetStrategyFifoGapService
from steuerreport_v2.domain.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


class BitgetStrategyBasisDecisionService:
    DECISION_TYPE = "bitget_strategy_basis_method_decision"
    SCOPE_PREFIX = "bitget-strategy-basis:"
    ESTIMATE_DECISIONS = {
        "approve_zero_basis_estimate_for_staging",
        "approve_settlement_value_proxy_estimate_for_staging",
    }

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.run_service = WalletFifoParallelRunService(
            store,
            artifact_root=artifact_root,
        )
        self.gap_service = BitgetStrategyFifoGapService(
            store,
            artifact_root=artifact_root,
        )
        self.reconstruction_service = BitgetStrategyBasisReconstructionService(
            store,
            artifact_root=artifact_root,
        )

    def readiness(
        self,
        *,
        run_id: str | None = None,
    ) -> BitgetStrategyBasisDecisionReport:
        generated_at = datetime.now(timezone.utc)
        methodology = (
            "Die Entscheidung bindet eine ausdruecklich als Schaetzung bezeichnete "
            "Behandlung der im vollstaendigen Bitget-Anbieterexport fehlenden Bot-"
            "Einzelfills an Wallet-FIFO-Run, Input-Fingerprint, Mengenabgleich und "
            "Rekonstruktionshash. Nullbasis und anteiliger Settlement-Zeitwert sind "
            "ausschliesslich Staging-Varianten. Die Entscheidung schreibt keine "
            "Canonical Events, Lots, Tax-Lines, Ledger- oder Preisdaten und aktiviert "
            "keine produktive FIFO-Methode."
        )
        run = self.run_service.get(run_id) if run_id else self.run_service.latest()
        if run is None:
            return BitgetStrategyBasisDecisionReport(
                generated_at=generated_at,
                blockers=["Ein versionierter Wallet-FIFO-Lauf fehlt."],
                findings=[
                    "Vor einer Bitget-Basisentscheidung muss ein aktueller Prueflauf vorliegen."
                ],
                methodology=methodology,
            )

        gap = self.gap_service.report(run_id=run.run_id)
        reconstruction = self.reconstruction_service.report(run_id=run.run_id)
        current_fingerprint = self.run_service.input_fingerprint(run.as_of)
        fingerprint_current = current_fingerprint.digest == run.input_fingerprint.digest
        run_bound = bool(
            gap is not None
            and reconstruction is not None
            and gap.run_id == run.run_id
            and reconstruction.run_id == run.run_id
            and gap.source_run_input_fingerprint_digest == run.input_fingerprint.digest
            and reconstruction.source_run_input_fingerprint_digest
            == run.input_fingerprint.digest
        )
        gap_bound = bool(
            gap is not None
            and reconstruction is not None
            and reconstruction.source_gap_semantic_sha256 == gap.semantic_sha256
        )
        support_complete = bool(
            gap is not None
            and reconstruction is not None
            and gap.support_package.package_complete
            and reconstruction.support_package_complete
        )
        provider_gap = bool(
            gap is not None
            and reconstruction is not None
            and gap.support_package.provider_export_field_gap
            and reconstruction.provider_export_field_gap
        )
        quantity_reconciled = bool(
            gap is not None
            and gap.quantity_reconciled
            and gap.unallocated_unmatched_disposals_count == 0
            and gap.linked_unmatched_disposals_count == gap.unmatched_disposals_count
        )
        price_complete = bool(
            reconstruction is not None
            and reconstruction.groups_count
            == reconstruction.price_evidence_complete_groups_count
        )
        holding_complete = bool(
            reconstruction is not None
            and reconstruction.uncertain_holding_period_disposals_count == 0
            and (
                reconstruction.definitely_within_one_year_disposals_count
                + reconstruction.definitely_over_one_year_disposals_count
                == reconstruction.linked_disposals_count
            )
        )
        proceeds_complete = bool(
            reconstruction is not None
            and all(
                row.attributable_disposal_proceeds_eur is not None
                for group in reconstruction.groups
                for row in group.linked_disposals
            )
        )
        reconstruction_ready = bool(
            reconstruction is not None
            and reconstruction.status == "ready_for_professional_review"
            and reconstruction.groups_count > 0
            and reconstruction.linked_disposals_count > 0
        )
        checks = [
            self._check(
                "input_fingerprint_current",
                "Prueflauf entspricht dem aktuellen Datenstand",
                fingerprint_current,
                (
                    "Run- und aktueller semantischer Input-Fingerprint stimmen ueberein."
                    if fingerprint_current
                    else "Quellen, Preise oder steuerwirksame Reviews haben sich seit dem Lauf geaendert."
                ),
            ),
            self._check(
                "run_artifacts_bound",
                "Gap- und Rekonstruktionsakte sind an denselben Lauf gebunden",
                run_bound and gap_bound,
                "Run-ID, Input-Fingerprint und Gap-Hash muessen durchgaengig identisch sein.",
            ),
            self._check(
                "support_package_complete",
                "Vollstaendiges Bitget-Supportpaket ist hashgebunden",
                support_complete,
                "Alle sechs vom Bitget-Support bereitgestellten Dateien muessen vorhanden sein.",
            ),
            self._check(
                "provider_field_gap_confirmed",
                "Fehlende Bot-Fills sind als Provider-Feldluecke belegt",
                provider_gap,
                "Die Schaetzentscheidung ist nur fuer eine dokumentierte Anbietergrenze zulaessig.",
            ),
            self._check(
                "quantity_reconciled",
                "Alle Strategy-Mengen sind reconciliert",
                quantity_reconciled,
                "Kein Abgang und keine materielle Restmenge darf unzugeordnet bleiben.",
            ),
            self._check(
                "reference_prices_complete",
                "EUR-Referenzpreise sind vollstaendig",
                price_complete,
                "Alle Strategy-Gruppen benoetigen gebundene EUR-Referenzpreise.",
            ),
            self._check(
                "holding_period_classified",
                "Haltedauerband ist fuer alle Abgaenge eindeutig",
                holding_complete,
                "Ein Erwerbsfenster darf die Einjahresgrenze nicht ungeklaert schneiden.",
            ),
            self._check(
                "disposal_proceeds_complete",
                "Anteilige Verkaufserloese sind vollstaendig",
                proceeds_complete,
                "Jeder zugeordnete Abgang benoetigt einen beleggebundenen EUR-Erloes.",
            ),
            self._check(
                "reconstruction_ready",
                "Sensitivitaetsakte ist fachlich pruefbar",
                reconstruction_ready,
                "Die Rekonstruktionsakte muss ready_for_professional_review sein.",
            ),
        ]
        decision_ready = all(check.passed for check in checks if check.blocking)
        decision = self._latest_decision(
            run_id=run.run_id,
            run_input_fingerprint_digest=run.input_fingerprint.digest,
            gap_semantic_sha256=gap.semantic_sha256 if gap is not None else None,
            reconstruction_semantic_sha256=(
                reconstruction.semantic_sha256 if reconstruction is not None else None
            ),
        )
        decision_status = self._decision_status(decision)
        selected_method = self._selected_method(decision_status)
        selected_basis = None
        selected_gain = None
        if reconstruction is not None and selected_method == "zero_basis_estimate":
            selected_basis = reconstruction.documented_cost_basis_floor_total_eur
            selected_gain = reconstruction.zero_basis_gain_sensitivity_total_eur
        elif (
            reconstruction is not None
            and selected_method == "settlement_value_proxy_estimate"
        ):
            selected_basis = reconstruction.settlement_value_proxy_basis_total_eur
            selected_gain = (
                reconstruction.settlement_value_proxy_gain_sensitivity_total_eur
            )
        decision_recorded = decision_status != "pending"
        estimate_selected = decision_ready and decision_status in self.ESTIMATE_DECISIONS
        status = (
            "decision_recorded"
            if decision_recorded
            else "ready_for_professional_decision"
            if decision_ready
            else "blocked"
        )
        blockers = [
            check.detail for check in checks if check.blocking and not check.passed
        ]
        findings = [
            (
                "Die technische Akte ist fuer eine ausdrueckliche fachliche Entscheidung vorbereitet."
                if decision_ready
                else "Mindestens ein Beleg- oder Bindungscheck verhindert derzeit eine Schaetzentscheidung."
            ),
            (
                "Noch keine Bitget-Basismethode ausgewaehlt."
                if decision_status == "pending"
                else f"Gespeicherte Entscheidung: {decision_status}."
            ),
            (
                "Auch eine dokumentierte Schaetzentscheidung ist keine exakte Bot-Fill-Historie "
                "und setzt strict_ready deshalb nicht auf true."
            ),
        ]
        return BitgetStrategyBasisDecisionReport(
            generated_at=generated_at,
            run_id=run.run_id,
            run_as_of=run.as_of,
            run_input_fingerprint_digest=run.input_fingerprint.digest,
            current_input_fingerprint_digest=current_fingerprint.digest,
            input_fingerprint_current=fingerprint_current,
            gap_semantic_sha256=gap.semantic_sha256 if gap is not None else None,
            reconstruction_semantic_sha256=(
                reconstruction.semantic_sha256 if reconstruction is not None else None
            ),
            status=status,
            decision_ready=decision_ready,
            decision_status=decision_status,
            selected_method=selected_method,
            decision_id=decision.decision_id if decision is not None else None,
            decision_at=decision.created_at if decision is not None else None,
            decision_actor=decision.actor if decision is not None else None,
            decision_rationale=decision.rationale if decision is not None else None,
            support_package_complete=support_complete,
            provider_export_field_gap=provider_gap,
            quantity_reconciled=quantity_reconciled,
            price_evidence_complete=price_complete,
            holding_period_classification_complete=holding_complete,
            linked_disposals_count=(
                reconstruction.linked_disposals_count
                if reconstruction is not None
                else 0
            ),
            attributable_disposal_proceeds_total_eur=(
                reconstruction.attributable_disposal_proceeds_total_eur
                if reconstruction is not None
                else 0
            ),
            selected_estimated_cost_basis_total_eur=selected_basis,
            selected_estimated_gain_loss_total_eur=selected_gain,
            estimate_selected_for_staging=estimate_selected,
            checks=checks,
            blockers=blockers,
            findings=findings,
            evidence_refs=[
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-gaps?run_id={run.run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction?run_id={run.run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-review.html?run_id={run.run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip?run_id={run.run_id}",
            ],
            methodology=methodology,
        )

    def decide(
        self,
        *,
        run_id: str,
        request: BitgetStrategyBasisDecisionRequest,
    ) -> BitgetStrategyBasisDecisionResult:
        report = self.readiness(run_id=run_id)
        if report.run_id is None:
            raise ValueError("Wallet-FIFO-Lauf nicht gefunden.")
        if not report.input_fingerprint_current:
            raise ValueError(
                "Der Wallet-FIFO-Lauf ist nicht mehr an den aktuellen Datenstand gebunden."
            )
        if request.decision in self.ESTIMATE_DECISIONS and not report.decision_ready:
            raise ValueError(
                "Eine Schaetzmethode kann wegen offener Beleg- oder Bindungschecks nicht fuer das Staging ausgewaehlt werden."
            )
        current = self._latest_decision(
            run_id=run_id,
            run_input_fingerprint_digest=report.run_input_fingerprint_digest,
            gap_semantic_sha256=report.gap_semantic_sha256,
            reconstruction_semantic_sha256=report.reconstruction_semantic_sha256,
        )
        if current is not None and self._decision_status(current) == request.decision:
            return BitgetStrategyBasisDecisionResult(
                decision_id=current.decision_id,
                created=False,
                report=report,
            )

        selected_method = self._selected_method(request.decision)
        selected_basis = None
        selected_gain = None
        reconstruction = self.reconstruction_service.report(run_id=run_id)
        affected_years = (
            sorted({group.year for group in reconstruction.groups})
            if reconstruction is not None
            else []
        )
        if reconstruction is not None and selected_method == "zero_basis_estimate":
            selected_basis = reconstruction.documented_cost_basis_floor_total_eur
            selected_gain = reconstruction.zero_basis_gain_sensitivity_total_eur
        elif (
            reconstruction is not None
            and selected_method == "settlement_value_proxy_estimate"
        ):
            selected_basis = reconstruction.settlement_value_proxy_basis_total_eur
            selected_gain = (
                reconstruction.settlement_value_proxy_gain_sensitivity_total_eur
            )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type=self.DECISION_TYPE,
                scope=f"{self.SCOPE_PREFIX}{run_id}",
                title="Bitget Strategy-Bot Kostenbasisentscheidung",
                rationale=request.rationale,
                evidence_ref=(
                    f"/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip?run_id={run_id}"
                ),
                actor=request.actor,
                source="bitget_strategy_basis_decision_api",
                affected_ids=[run_id],
                payload={
                    "run_id": run_id,
                    "decision_status": request.decision,
                    "selected_method": selected_method,
                    "run_input_fingerprint_digest": report.run_input_fingerprint_digest,
                    "gap_semantic_sha256": report.gap_semantic_sha256,
                    "reconstruction_semantic_sha256": (
                        report.reconstruction_semantic_sha256
                    ),
                    "selected_estimated_cost_basis_total_eur": (
                        str(selected_basis) if selected_basis is not None else None
                    ),
                    "selected_estimated_gain_loss_total_eur": (
                        str(selected_gain) if selected_gain is not None else None
                    ),
                    "years": affected_years,
                    "staging_only": True,
                    "productive_tax_effect": "none",
                    "import_effect": "none",
                    "ledger_effect": "none",
                    "fifo_effect": "staging_only_no_productive_change",
                    "tax_line_effect": "none",
                    "acknowledge_provider_fill_data_missing": (
                        request.acknowledge_provider_fill_data_missing
                    ),
                    "acknowledge_estimate_not_observed_transaction": (
                        request.acknowledge_estimate_not_observed_transaction
                    ),
                    "acknowledge_consistent_application": (
                        request.acknowledge_consistent_application
                    ),
                    "acknowledge_no_automatic_tax_effect": (
                        request.acknowledge_no_automatic_tax_effect
                    ),
                    "acknowledge_professional_review_before_filing": (
                        request.acknowledge_professional_review_before_filing
                    ),
                },
            )
        )
        return BitgetStrategyBasisDecisionResult(
            decision_id=decision.decision_id,
            created=True,
            report=self.readiness(run_id=run_id),
        )

    def _latest_decision(
        self,
        *,
        run_id: str,
        run_input_fingerprint_digest: str | None,
        gap_semantic_sha256: str | None,
        reconstruction_semantic_sha256: str | None,
    ) -> ReviewDecision | None:
        scope = f"{self.SCOPE_PREFIX}{run_id}"
        for decision in self.store.list_review_decisions():
            if decision.decision_type != self.DECISION_TYPE or decision.scope != scope:
                continue
            payload = decision.payload
            if (
                str(payload.get("run_input_fingerprint_digest") or "")
                != str(run_input_fingerprint_digest or "")
                or str(payload.get("gap_semantic_sha256") or "")
                != str(gap_semantic_sha256 or "")
                or str(payload.get("reconstruction_semantic_sha256") or "")
                != str(reconstruction_semantic_sha256 or "")
            ):
                continue
            return decision
        return None

    @staticmethod
    def _decision_status(
        decision: ReviewDecision | None,
    ) -> BitgetStrategyBasisDecisionStatus:
        if decision is None:
            return "pending"
        value = str(decision.payload.get("decision_status") or "")
        if value in {
            "retain_provider_gap_pending_professional_review",
            "approve_zero_basis_estimate_for_staging",
            "approve_settlement_value_proxy_estimate_for_staging",
            "rejected_requires_rework",
        }:
            return cast(BitgetStrategyBasisDecisionStatus, value)
        return "pending"

    @staticmethod
    def _selected_method(
        decision_status: BitgetStrategyBasisDecisionStatus,
    ) -> BitgetStrategyBasisSelectedMethod:
        if decision_status == "approve_zero_basis_estimate_for_staging":
            return "zero_basis_estimate"
        if decision_status == "approve_settlement_value_proxy_estimate_for_staging":
            return "settlement_value_proxy_estimate"
        return "none"

    @staticmethod
    def _check(
        key: str,
        label: str,
        passed: bool,
        detail: str,
    ) -> BitgetStrategyBasisDecisionCheck:
        return BitgetStrategyBasisDecisionCheck(
            key=key,
            label=label,
            passed=passed,
            detail=detail,
        )
