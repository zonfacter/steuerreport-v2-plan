from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.audit import (
    AuditExport,
    ElsterPrepExport,
    HntProvenanceAuditSummary,
    ReviewDecisionAuditItem,
    TokenRiskDocumentationAuditItem,
    TokenRiskDocumentationAuditSummary,
)
from steuerreport_v2.contracts.review import ReviewDecision
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.valuation import PriceCoverageService


class AuditService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def export(self) -> AuditExport:
        counts = self.store.table_counts(
            [
                "raw_import_batches",
                "raw_objects",
                "canonical_events",
                "balance_ledger",
                "flow_ledger",
                "export_packages",
            ]
        )
        gate = ReviewService(self.store).gate()
        parity = V1ParityService(self.store).release_readiness()
        hnt_provenance = V1ParityService(self.store).hnt_fifo_provenance(limit=1)
        decisions = self.store.list_review_decisions()
        token_risk_documentation = self._token_risk_documentation(decisions)
        price_coverage = PriceCoverageService(self.store).report()
        return AuditExport(
            generated_at=datetime.now(timezone.utc),
            import_batches=counts["raw_import_batches"],
            raw_objects=counts["raw_objects"],
            canonical_events=counts["canonical_events"],
            balance_entries=counts["balance_ledger"],
            flow_entries=counts["flow_ledger"],
            export_packages=counts["export_packages"],
            review_allow_export=gate.allow_export,
            export_ready=gate.allow_export and parity.release_ready,
            review_issues_open=gate.issues_open,
            review_issues_current_open=(
                gate.issues_current_open
                if gate.issues_current_open is not None
                else gate.issues_open
            ),
            review_issues_historical_open=gate.issues_historical_open,
            review_issues_open_total=(
                gate.issues_open_total
                if gate.issues_open_total is not None
                else gate.issues_open
            ),
            review_blocking_issues_open=gate.blocking_issues_open,
            parity_release_ready=parity.release_ready,
            parity_unresolved_groups=parity.unresolved_groups,
            parity_blocking_groups=parity.blocking_groups,
            parity_blocking_difference_eur=str(parity.blocking_difference_eur),
            parity_accepted_groups=parity.accepted_groups,
            parity_groups_total=parity.groups_total,
            review_decisions_count=len(decisions),
            review_decisions=[
                ReviewDecisionAuditItem(
                    decision_id=decision.decision_id,
                    decision_type=decision.decision_type,
                    scope=decision.scope,
                    title=decision.title,
                    rationale=decision.rationale,
                    evidence_ref=decision.evidence_ref,
                    actor=decision.actor,
                    source=decision.source,
                    affected_ids=decision.affected_ids,
                    payload=decision.payload,
                    created_at=decision.created_at,
                    updated_at=decision.updated_at,
                )
                for decision in decisions
            ],
            price_gaps_count=price_coverage.missing_count,
            price_gap_assets=price_coverage.missing_assets,
            price_gaps=price_coverage.missing,
            hnt_provenance=HntProvenanceAuditSummary(
                current_portfolio_events=hnt_provenance.current_portfolio_events,
                transfer_counterparty_events=hnt_provenance.transfer_counterparty_events,
                fifo_relevant_events=hnt_provenance.fifo_relevant_events,
                open_lots=hnt_provenance.open_lots,
                disposals=hnt_provenance.disposals,
                current_portfolio_accounts=hnt_provenance.current_portfolio_accounts,
                transfer_counterparty_accounts=hnt_provenance.transfer_counterparty_accounts,
                methodology=(
                    "HNT-Provenance ist read-only. Legacy-, Fairspot- und CEX-"
                    "Gegenparteien werden als Transfer-/Bridge-Nachweise gefuehrt, "
                    "nicht als aktuelle Portfolio-Orte. FIFO-relevant bleiben nur "
                    "Erwerb, Income/Mining/Staking und Veraeusserungen."
                ),
            ),
            token_risk_documentation=token_risk_documentation,
            transfer_context_note=(
                "Transfers und Bridge-Kontexte werden fuer Audit und stichtagsgenaue "
                "Historie sichtbar gehalten. Sie erzeugen ohne belegten Trade/Income-"
                "Kontext keine steuerliche Veraeusserung und keine aktuelle Portfolio-Wallet."
            ),
        )

    def elster_prep(self) -> ElsterPrepExport:
        gate = ReviewService(self.store).gate()
        parity = V1ParityService(self.store).release_readiness()
        counts = self.store.table_counts(["tax_lines"])
        token_risk_documentation = self._token_risk_documentation(
            self.store.list_review_decisions()
        )
        return ElsterPrepExport(
            generated_at=datetime.now(timezone.utc),
            direct_eric_submission=False,
            tax_lines_count=counts["tax_lines"],
            export_ready=gate.allow_export and parity.release_ready,
            parity_release_ready=parity.release_ready,
            parity_blocking_groups=parity.blocking_groups,
            token_risk_documentation_count=token_risk_documentation.documented_count,
            notes=[
                "ELSTER-Prep erzeugt strukturierte Vorbereitungsdaten.",
                "Direkte ERiC-Uebertragung ist in V2-MVP bewusst deaktiviert.",
                (
                    "Token-Risiko-Dokumentationen sind reine Belegentscheidungen "
                    "ohne Import-, Ledger-, FIFO- oder Steuerzeilenwirkung."
                ),
            ],
        )

    def _token_risk_documentation(
        self,
        decisions: list[ReviewDecision],
    ) -> TokenRiskDocumentationAuditSummary:
        items: list[TokenRiskDocumentationAuditItem] = []
        total_value = Decimal("0")
        for decision in decisions:
            if decision.decision_type != "token_risk_documentation":
                continue
            payload = decision.payload
            value_eur = self._payload_str(payload, "value_eur")
            if value_eur is not None:
                try:
                    total_value += Decimal(value_eur)
                except Exception:
                    pass
            accounts_raw = payload.get("accounts")
            accounts = [
                str(account)
                for account in accounts_raw
                if str(account).strip()
            ] if isinstance(accounts_raw, list) else []
            items.append(
                TokenRiskDocumentationAuditItem(
                    decision_id=decision.decision_id,
                    scope=decision.scope,
                    asset=self._payload_str(payload, "asset"),
                    token_symbol=self._payload_str(payload, "token_symbol"),
                    token_name=self._payload_str(payload, "token_name"),
                    token_mint=self._payload_str(payload, "token_mint"),
                    token_risk_status=self._payload_str(payload, "token_risk_status"),
                    quantity=self._payload_str(payload, "quantity"),
                    value_eur=value_eur,
                    accounts=accounts,
                    evidence_ref=decision.evidence_ref,
                    import_effect=self._payload_str(payload, "import_effect"),
                    ledger_effect=self._payload_str(payload, "ledger_effect"),
                    fifo_effect=self._payload_str(payload, "fifo_effect"),
                    tax_line_effect=self._payload_str(payload, "tax_line_effect"),
                    created_at=decision.created_at,
                )
            )
        return TokenRiskDocumentationAuditSummary(
            documented_count=len(items),
            total_value_eur=str(total_value),
            items=items,
        )

    @staticmethod
    def _payload_str(payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        return str(value)
