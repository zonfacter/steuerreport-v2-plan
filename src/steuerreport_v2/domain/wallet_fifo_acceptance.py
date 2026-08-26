from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.contracts.wallet_fifo_runs import (
    WalletFifoMethodAcceptanceCheck,
    WalletFifoMethodAcceptanceReport,
    WalletFifoMethodAcceptanceRequest,
    WalletFifoMethodAcceptanceResult,
    WalletFifoMethodDeltaExplanationReport,
    WalletFifoMethodDecisionStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget_strategy_fifo import BitgetStrategyFifoGapService
from steuerreport_v2.domain.fifo_methods import (
    WALLET_DEPOT_FIFO_SCOPE,
    active_fifo_scope,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


class WalletFifoMethodAcceptanceService:
    DECISION_TYPE = "wallet_fifo_method_acceptance"
    SCOPE_PREFIX = "wallet-fifo-method:"
    TARGET_FIFO_SCOPE = WALLET_DEPOT_FIFO_SCOPE
    APPROVAL = "approved_for_controlled_migration"

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.run_service = WalletFifoParallelRunService(store)

    def readiness(
        self,
        *,
        run_id: str | None = None,
    ) -> WalletFifoMethodAcceptanceReport:
        generated_at = datetime.now(timezone.utc)
        run = self.run_service.get(run_id) if run_id else self.run_service.latest()
        methodology = (
            "Die Abnahmeakte bindet die Methodenentscheidung an den versionierten "
            "Wallet-/Depot-FIFO-Lauf, dessen semantischen Input-Fingerprint und den "
            "Methodendifferenz-Report. Eine Entscheidung schreibt keine Tax-Lots, "
            "Tax-Lines, Ledger-, Preis- oder Importdaten und aktiviert keine andere "
            "produktive FIFO-Methode."
        )
        active_scope = active_fifo_scope(self.store)
        if run is None:
            return WalletFifoMethodAcceptanceReport(
                generated_at=generated_at,
                active_fifo_scope=active_scope,
                target_fifo_scope=self.TARGET_FIFO_SCOPE,
                blockers=["Ein versionierter Wallet-/Depot-FIFO-Lauf fehlt."],
                findings=["Vor einer Methodenentscheidung muss ein aktueller Prueflauf vorliegen."],
                methodology=methodology,
            )

        provider_classification_current = (
            run.report_schema_version == self.run_service.RUN_REPORT_VERSION
        )
        provider_basis_gap_count = (
            run.provider_basis_gap_count if provider_classification_current else 0
        )
        unexplained_unmatched_count = (
            run.unexplained_unmatched_count
            if provider_classification_current
            else run.unmatched_count
        )

        method_delta = self.run_service.method_delta_explanation(
            run_id=run.run_id,
            event_limit=self.run_service.METHOD_DELTA_TOP_EVENTS_PER_GROUP,
        )
        provider_gap = BitgetStrategyFifoGapService(self.store).report(
            run_id=run.run_id
        )
        provider_gap_event_ids = {
            disposal.source_event_id
            for group in (provider_gap.groups if provider_gap is not None else [])
            if group.quantity_reconciled
            and group.basis_gap_responsibility == "provider_export_field_gap"
            for disposal in group.linked_disposals
            if disposal.quantity_fully_allocated
        }
        (
            provider_event_set_gap_groups,
            provider_quantity_gap_groups,
            unexplained_method_gap_groups,
        ) = self.classify_method_gap_groups(
            method_delta,
            provider_gap_event_ids=provider_gap_event_ids,
        )
        current_fingerprint = self.run_service.input_fingerprint(run.as_of)
        fingerprint_current = current_fingerprint.digest == run.input_fingerprint.digest
        activation_applied = active_scope == self.TARGET_FIFO_SCOPE
        activation_output_binding = False
        if activation_applied:
            summary = TaxService(self.store).latest_summary()
            source_components_current = all(
                current_fingerprint.component_sha256.get(key) == value
                for key, value in run.input_fingerprint.component_sha256.items()
                if key != "tax_lines"
            )
            activation_output_binding = bool(
                summary
                and summary.fifo_method == self.TARGET_FIFO_SCOPE
                and summary.input_fingerprint_digest == run.input_fingerprint.digest
                and source_components_current
            )
            fingerprint_current = fingerprint_current or activation_output_binding
        checks = [
            self._check(
                "input_fingerprint_current",
                "Prueflauf entspricht dem aktuellen Datenstand",
                fingerprint_current,
                (
                    "Run und aktive Wallet-FIFO-Ausgabe sind an denselben Quelldatenstand gebunden."
                    if activation_output_binding
                    else "Run- und aktueller semantischer Input-Fingerprint stimmen ueberein."
                    if fingerprint_current
                    else "Canonical Events, Rohbelege, Preise, Einstellungen oder fachliche Reviews haben sich seit dem Lauf geaendert."
                ),
            ),
            self._check(
                "method_delta_bound",
                "Methodendifferenz ist an denselben Lauf gebunden",
                bool(
                    method_delta
                    and method_delta.input_fingerprint_digest
                    == run.input_fingerprint.digest
                    and method_delta.semantic_sha256
                    == run.method_delta_explanation_semantic_sha256
                ),
                "Input- und Report-Hashes muessen in beiden Artefakten identisch gebunden sein.",
            ),
            self._check(
                "no_blocked_years",
                "Kein Steuerjahr ist im Prueflauf blockiert",
                not run.blocked_years,
                f"Blockierte Jahre: {', '.join(str(year) for year in run.blocked_years) or 'keine'}.",
            ),
            self._check(
                "no_unexplained_unmatched_disposals",
                "Keine wirklich ungeklaerten Wallet-FIFO-Abgaenge",
                unexplained_unmatched_count == 0,
                (
                    "Wirklich ungeklaerte Abgaenge: "
                    f"{unexplained_unmatched_count}; belegte Provider-Basisluecken: "
                    f"{provider_basis_gap_count}."
                ),
            ),
            self._check(
                "provider_basis_complete",
                "Kostenbasis fuer Provider-Settlements ist vollstaendig",
                provider_basis_gap_count == 0,
                (
                    "Belegte, mengenreconciliierte Provider-Basisluecken: "
                    f"{provider_basis_gap_count}. Die fehlenden originalen Bot-Fills "
                    "benoetigen eine ausdrueckliche fachliche Behandlung; sie sind keine "
                    "unbekannten Wallet-Transaktionen."
                ),
            ),
            self._check(
                "no_unresolved_provenance",
                "Keine offene Zuflussherkunft",
                run.unresolved_inbound_provenance_count == 0,
                f"Offene Herkuenfte: {run.unresolved_inbound_provenance_count}.",
            ),
            self._check(
                "no_transfer_evidence_review",
                "Keine offenen Transferbeleg-Reviews",
                run.transfer_evidence_review_count == 0,
                f"Transferbeleg-Reviews: {run.transfer_evidence_review_count}.",
            ),
            self._check(
                "no_acquisition_cost_review",
                "Keine offenen Anschaffungskosten-Reviews",
                run.acquisition_cost_evidence_review_count == 0,
                f"Anschaffungskosten-Reviews: {run.acquisition_cost_evidence_review_count}.",
            ),
            self._check(
                "event_set_complete",
                "Veraeusserungsereignisse sind vollstaendig",
                run.method_delta_event_set_gap_groups_count == 0,
                (
                    f"Ereignis-Gap-Gruppen: {run.method_delta_event_set_gap_groups_count}; "
                    f"davon Provider-Basis: {provider_event_set_gap_groups}; "
                    f"methodisch unerklaert: {unexplained_method_gap_groups}."
                ),
            ),
            self._check(
                "quantity_complete",
                "Veraeusserungsmengen sind vollstaendig",
                run.method_delta_quantity_gap_groups_count == 0,
                (
                    f"Mengen-Gap-Gruppen: {run.method_delta_quantity_gap_groups_count}; "
                    f"davon Provider-Basis: {provider_quantity_gap_groups}; "
                    f"methodisch unerklaert: {unexplained_method_gap_groups}."
                ),
            ),
            self._check(
                "proceeds_reconciled",
                "Erlosdifferenzen sind erklaert",
                run.method_delta_unexplained_proceeds_groups_count == 0,
                (
                    "Unerklaerte Erlos-Gruppen: "
                    f"{run.method_delta_unexplained_proceeds_groups_count}."
                ),
            ),
        ]
        decision_ready = all(item.passed for item in checks if item.blocking)
        decision = self._latest_decision(run.run_id, run.semantic_sha256)
        decision_status = self._decision_status(decision)
        activation_ready = (
            decision_ready
            and decision_status == self.APPROVAL
            and activation_applied
        )
        blockers = [item.detail for item in checks if item.blocking and not item.passed]
        if not activation_applied:
            blockers.append(
                "Die produktive Steuerberechnung verwendet weiterhin "
                f"{active_scope}; eine kontrollierte Migration ist nicht aktiviert."
            )
        findings = [
            (
                "Die rechnerische Methodenakte ist entscheidungsreif."
                if decision_ready
                else "Die Methodenakte ist wegen mindestens eines Daten- oder Belegchecks nicht entscheidungsreif."
            ),
            (
                "Eine explizite Methodenentscheidung ist noch nicht gespeichert."
                if decision_status == "pending"
                else f"Gespeicherte Methodenentscheidung: {decision_status}."
            ),
            (
                f"{provider_basis_gap_count} Abgaenge sind mengenmaessig belegt und "
                "ausschliesslich wegen nicht exportierter Provider-Bot-Fills ohne originale "
                f"Kostenbasis; wirklich ungeklaert: {unexplained_unmatched_count}."
                if provider_basis_gap_count
                else "Es bestehen keine klassifizierten Provider-Basisluecken."
            ),
            (
                "Die Entscheidung ersetzt keine steuerliche oder rechtliche Einzelfallpruefung."
            ),
        ]
        return WalletFifoMethodAcceptanceReport(
            generated_at=generated_at,
            run_id=run.run_id,
            run_generated_at=run.generated_at,
            run_as_of=run.as_of,
            method_version=run.method_version,
            run_status=run.status,
            method_delta_status=(
                method_delta.status if method_delta is not None else "missing"
            ),
            run_input_fingerprint_digest=run.input_fingerprint.digest,
            current_input_fingerprint_digest=current_fingerprint.digest,
            run_semantic_sha256=run.semantic_sha256,
            method_delta_semantic_sha256=(
                method_delta.semantic_sha256 if method_delta is not None else None
            ),
            input_fingerprint_current=fingerprint_current,
            provider_basis_gap_count=provider_basis_gap_count,
            unexplained_unmatched_count=unexplained_unmatched_count,
            provider_basis_event_set_gap_groups_count=(
                provider_event_set_gap_groups
            ),
            provider_basis_quantity_gap_groups_count=(
                provider_quantity_gap_groups
            ),
            unexplained_method_gap_groups_count=unexplained_method_gap_groups,
            provider_basis_resolution_required=provider_basis_gap_count > 0,
            decision_ready=decision_ready,
            decision_status=decision_status,
            decision_id=decision.decision_id if decision is not None else None,
            decision_at=decision.created_at if decision is not None else None,
            decision_actor=decision.actor if decision is not None else None,
            decision_rationale=decision.rationale if decision is not None else None,
            method_acceptance_required=decision_status != self.APPROVAL,
            active_fifo_scope=active_scope,
            target_fifo_scope=self.TARGET_FIFO_SCOPE,
            activation_applied=activation_applied,
            activation_ready=activation_ready,
            strict_ready=activation_ready,
            checks=checks,
            blockers=blockers,
            findings=findings,
            evidence_refs=[
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}",
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-delta-explanation",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-gaps?run_id={run.run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction?run_id={run.run_id}",
                "/api/v1/tax/wallet-fifo-migrations/apply-readiness",
                run.artifact_path,
            ],
            methodology=methodology,
        )

    @staticmethod
    def classify_method_gap_groups(
        method_delta: WalletFifoMethodDeltaExplanationReport | None,
        *,
        provider_gap_event_ids: set[str],
    ) -> tuple[int, int, int]:
        if method_delta is None:
            return 0, 0, 0

        provider_event_groups = 0
        provider_quantity_groups = 0
        unexplained_groups = 0
        for group in method_delta.groups:
            event_gap_events = [
                event for event in group.top_events if "event_set_gap" in event.drivers
            ]
            quantity_gap_events = [
                event for event in group.top_events if "quantity_gap" in event.drivers
            ]
            event_gap_is_provider = bool(group.event_set_gap_events_count) and bool(
                len(event_gap_events) == group.event_set_gap_events_count
                and all(
                    event.source_event_id in provider_gap_event_ids
                    for event in event_gap_events
                )
            )
            quantity_gap_is_provider = bool(group.quantity_gap_events_count) and bool(
                len(quantity_gap_events) == group.quantity_gap_events_count
                and all(
                    event.source_event_id in provider_gap_event_ids
                    for event in quantity_gap_events
                )
            )
            if event_gap_is_provider:
                provider_event_groups += 1
            if quantity_gap_is_provider:
                provider_quantity_groups += 1
            if (
                group.event_set_gap_events_count or group.quantity_gap_events_count
            ) and not (
                (not group.event_set_gap_events_count or event_gap_is_provider)
                and (not group.quantity_gap_events_count or quantity_gap_is_provider)
            ):
                unexplained_groups += 1
        return provider_event_groups, provider_quantity_groups, unexplained_groups

    def accept(
        self,
        run_id: str,
        request: WalletFifoMethodAcceptanceRequest,
    ) -> WalletFifoMethodAcceptanceResult:
        report = self.readiness(run_id=run_id)
        if report.run_id is None:
            raise ValueError("Wallet-FIFO-Lauf nicht gefunden.")
        if not report.input_fingerprint_current:
            raise ValueError("Der Wallet-FIFO-Lauf ist nicht mehr an den aktuellen Datenstand gebunden.")
        if request.decision == self.APPROVAL and not report.decision_ready:
            raise ValueError(
                "Die Wallet-/Depot-FIFO-Methode kann wegen offener Abnahmechecks nicht freigegeben werden."
            )

        current = self._latest_decision(run_id, report.run_semantic_sha256)
        if current is not None and self._decision_status(current) == request.decision:
            return WalletFifoMethodAcceptanceResult(
                decision_id=current.decision_id,
                created=False,
                report=report,
            )

        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type=self.DECISION_TYPE,
                scope=f"{self.SCOPE_PREFIX}{run_id}",
                title="Wallet-/Depot-FIFO Methodenentscheidung",
                rationale=request.rationale,
                evidence_ref=report.evidence_refs[0],
                actor=request.actor,
                source="wallet_fifo_method_acceptance_api",
                affected_ids=[run_id],
                payload={
                    "run_id": run_id,
                    "decision_status": request.decision,
                    "run_input_fingerprint_digest": report.run_input_fingerprint_digest,
                    "run_semantic_sha256": report.run_semantic_sha256,
                    "method_delta_semantic_sha256": report.method_delta_semantic_sha256,
                    "active_fifo_scope_at_decision": report.active_fifo_scope,
                    "target_fifo_scope": report.target_fifo_scope,
                    "acknowledge_material_tax_delta": request.acknowledge_material_tax_delta,
                    "acknowledge_consistent_application": request.acknowledge_consistent_application,
                    "acknowledge_no_automatic_activation": request.acknowledge_no_automatic_activation,
                    "activation_applied": False,
                },
            )
        )
        return WalletFifoMethodAcceptanceResult(
            decision_id=decision.decision_id,
            created=True,
            report=self.readiness(run_id=run_id),
        )

    def _latest_decision(
        self,
        run_id: str,
        run_semantic_sha256: str | None,
    ) -> ReviewDecision | None:
        scope = f"{self.SCOPE_PREFIX}{run_id}"
        for decision in self.store.list_review_decisions():
            if decision.decision_type != self.DECISION_TYPE or decision.scope != scope:
                continue
            if str(decision.payload.get("run_semantic_sha256") or "") != str(
                run_semantic_sha256 or ""
            ):
                continue
            return decision
        return None

    @staticmethod
    def _decision_status(
        decision: ReviewDecision | None,
    ) -> WalletFifoMethodDecisionStatus:
        if decision is None:
            return "pending"
        value = str(decision.payload.get("decision_status") or "")
        if value in {
            "approved_for_controlled_migration",
            "retain_global_fifo_pending_professional_review",
            "rejected_requires_rework",
        }:
            return cast(WalletFifoMethodDecisionStatus, value)
        return "pending"

    @staticmethod
    def _check(
        key: str,
        label: str,
        passed: bool,
        detail: str,
    ) -> WalletFifoMethodAcceptanceCheck:
        return WalletFifoMethodAcceptanceCheck(
            key=key,
            label=label,
            passed=passed,
            blocking=True,
            detail=detail,
        )
