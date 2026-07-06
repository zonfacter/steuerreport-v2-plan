from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.product_readiness import (
    ProductReadinessCheck,
    ProductReadinessReport,
    ProductReadinessSeverity,
    ProductReadinessSource,
    ProductReadinessStatus,
)
from steuerreport_v2.contracts.sources import SourceConnectorDiagnostic, SourceStatus
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService


class ProductReadinessService:
    CREDENTIAL_BLOCKERS = {"missing", "decrypt_failed", "error"}
    LIVE_WARNING_STATUSES = {"missing_snapshot", "stale_snapshot", "warning"}

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def report(self) -> ProductReadinessReport:
        generated_at = datetime.now(timezone.utc)
        source_service = SourceService(self.store)
        sources_overview = source_service.overview()
        diagnostics = source_service.connector_diagnostics()
        review_gate = ReviewService(self.store).gate()
        bmf_snapshot = TaxMethodologyService(self.store).bmf_filing_readiness_snapshot()
        bmf_report = bmf_snapshot.report if bmf_snapshot.status == "available" else None

        source_rows = self._source_rows(sources_overview.sources, diagnostics.diagnostics)
        checks = [
            self._sources_check(source_rows, diagnostics.missing_credentials),
            self._review_gate_check(review_gate.allow_export, review_gate.issues_open),
            self._tax_years_check(bmf_snapshot.status, bmf_report),
            self._evidence_package_check(bmf_snapshot.status, bmf_report),
            self._portfolio_live_check(source_rows, sources_overview.health.status if sources_overview.health else "missing"),
        ]
        overall = self._overall_status(checks, source_rows)
        first_action = next((check for check in checks if check.status in {"blocker", "warning"}), checks[0])
        blocking_items = sum(check.count for check in checks if check.status == "blocker")
        review_items = sum(check.count for check in checks if check.status == "warning")

        return ProductReadinessReport(
            generated_at=generated_at,
            overall_status=overall,
            can_prepare_tax_report=overall in {"ready", "review"},
            can_file_without_review=overall == "ready" and review_gate.allow_export,
            headline=self._headline(overall),
            next_action=first_action.next_action,
            next_action_path=first_action.action_path or "/api/v1/cockpit/summary",
            checks=checks,
            sources=source_rows,
            ready_years=list(bmf_report.ready_years) if bmf_report is not None else [],
            conservative_ready_years=list(bmf_report.conservative_appendix_years) if bmf_report is not None else [],
            review_years=list(bmf_report.review_years) if bmf_report is not None else [],
            blocked_years=list(bmf_report.blocked_years) if bmf_report is not None else [],
            setup_required_sources=sum(1 for source in source_rows if source.status == "blocker"),
            review_items_count=review_items,
            blocking_items_count=blocking_items,
            methodology=(
                "Read-only Produkt-Readiness fuer vorhandene V2-Quellen. Der Bericht aggregiert "
                "Quellenuebersicht, Connector-Diagnose, Review-Gate und den vorhandenen "
                "BMF-Filing-Readiness-Snapshot. Es werden keine Connectoren abgefragt, keine "
                "Importe gestartet und keine Steuer-/FIFO-Daten veraendert."
            ),
        )

    def _source_rows(
        self,
        sources: list[SourceStatus],
        diagnostics: list[SourceConnectorDiagnostic],
    ) -> list[ProductReadinessSource]:
        sources_by_id = {source.source_id: source for source in sources}
        diagnostics_by_id = {diagnostic.source_id: diagnostic for diagnostic in diagnostics}
        source_ids = sorted(set(sources_by_id) | set(diagnostics_by_id))
        rows: list[ProductReadinessSource] = []
        for source_id in source_ids:
            source = sources_by_id.get(source_id)
            diagnostic = diagnostics_by_id.get(source_id)
            status = self._source_status(source, diagnostic)
            rows.append(
                ProductReadinessSource(
                    source_id=source_id,
                    label=source.label if source is not None else diagnostic.label if diagnostic is not None else source_id,
                    connector_id=diagnostic.connector_id if diagnostic is not None else source_id,
                    source_type=source.source_type if source is not None else diagnostic.connector_type if diagnostic is not None else "unknown",
                    status=status,
                    credential_status=diagnostic.credential_status if diagnostic is not None else "not_required",
                    live_status=self._live_status(source, diagnostic),
                    ledger_value_eur=source.ledger_value_eur if source is not None else Decimal("0"),
                    live_value_eur=source.live_value_eur if source is not None else None,
                    delta_value_eur=source.delta_value_eur if source is not None else None,
                    open_issues=(
                        (source.open_reconciliation_issues + source.open_price_issues)
                        if source is not None
                        else 0
                    ),
                    next_action=self._source_next_action(status, source, diagnostic),
                    action_path=self._source_action_path(status, diagnostic),
                )
            )
        return rows

    def _source_status(
        self,
        source: SourceStatus | None,
        diagnostic: SourceConnectorDiagnostic | None,
    ) -> ProductReadinessSeverity:
        if diagnostic is not None and diagnostic.credential_status in self.CREDENTIAL_BLOCKERS:
            return "blocker"
        if source is not None and source.current_status == "blocked":
            return "blocker"
        if source is not None and (source.open_reconciliation_issues > 0 or source.open_price_issues > 0):
            return "warning"
        if source is not None and source.current_status == "complete_export_strategy_reference_live_zero":
            return "ok"
        if source is not None and source.display_warning:
            return "warning"
        if diagnostic is not None and diagnostic.status in self.LIVE_WARNING_STATUSES:
            return "warning"
        if source is None:
            return "info"
        return "ok"

    def _live_status(
        self,
        source: SourceStatus | None,
        diagnostic: SourceConnectorDiagnostic | None,
    ) -> str:
        if source is not None:
            return source.live_freshness
        if diagnostic is not None:
            return diagnostic.status
        return "missing"

    def _source_next_action(
        self,
        status: ProductReadinessSeverity,
        source: SourceStatus | None,
        diagnostic: SourceConnectorDiagnostic | None,
    ) -> str:
        if diagnostic is not None and diagnostic.credential_status in self.CREDENTIAL_BLOCKERS:
            return "Credentials in Administration hinterlegen."
        if status == "warning" and source is not None and source.open_reconciliation_issues > 0:
            return "Ledger-vs-Live-Abgleich der Quelle pruefen."
        if status == "warning" and source is not None and source.display_warning:
            return "Live-Delta im Quellen-Drilldown pruefen; keine automatische FIFO-Korrektur buchen."
        if status == "warning":
            return "Live-Snapshot oder Quellenwarnung pruefen."
        if status == "info":
            return "Quelle aktuell ohne Portfolio-Wert; Konfiguration bei Bedarf pruefen."
        return "Keine Aktion erforderlich."

    def _source_action_path(
        self,
        status: ProductReadinessSeverity,
        diagnostic: SourceConnectorDiagnostic | None,
    ) -> str:
        if diagnostic is not None and diagnostic.credential_status in self.CREDENTIAL_BLOCKERS:
            return "/api/v1/admin/settings"
        if status in {"warning", "blocker"}:
            return "/api/v1/sources/overview"
        return "/api/v1/portfolio/snapshot"

    def _sources_check(
        self,
        sources: list[ProductReadinessSource],
        missing_credentials: int,
    ) -> ProductReadinessCheck:
        if not sources:
            return ProductReadinessCheck(
                key="sources_connected",
                label="Quellen verbunden",
                status="blocker",
                detail="Es sind keine vorhandenen Quellen in der V2-Uebersicht sichtbar.",
                next_action="Quellen und Wallets konfigurieren.",
                action_path="/api/v1/sources/overview",
                count=1,
            )
        if missing_credentials > 0:
            return ProductReadinessCheck(
                key="sources_connected",
                label="Quellen verbunden",
                status="blocker",
                detail=f"{missing_credentials} CEX-Connector(en) haben fehlende oder unlesbare Credentials.",
                next_action="Credentials fuer vorhandene Connectoren hinterlegen.",
                action_path="/api/v1/admin/settings",
                count=missing_credentials,
            )
        warnings = sum(1 for source in sources if source.status == "warning")
        if warnings > 0:
            return ProductReadinessCheck(
                key="sources_connected",
                label="Quellen verbunden",
                status="warning",
                detail=(
                    f"{warnings} vorhandene Quelle(n) haben frische Daten, aber ein "
                    "erklaerungsbeduerftiges Live-/Ledger-Delta."
                ),
                next_action="Quellen-Drilldown und Live-Abgleich pruefen.",
                action_path="/api/v1/sources/overview",
                count=warnings,
            )
        return ProductReadinessCheck(
            key="sources_connected",
            label="Quellen verbunden",
            status="ok",
            detail=f"{len(sources)} vorhandene Quelle(n) sind ohne blockierende Connector-Probleme sichtbar.",
            next_action="Keine Aktion erforderlich.",
            action_path="/api/v1/sources/overview",
            count=0,
        )

    def _review_gate_check(self, allow_export: bool, issues_open: int) -> ProductReadinessCheck:
        if not allow_export or issues_open > 0:
            return ProductReadinessCheck(
                key="review_gate",
                label="Review-Gate",
                status="blocker",
                detail=f"{issues_open} offene Review-Issue(s) blockieren oder gefaehrden die Abgabe.",
                next_action="Review-Aufgaben oeffnen und entscheiden.",
                action_path="/api/v1/review/tasks",
                count=issues_open,
            )
        return ProductReadinessCheck(
            key="review_gate",
            label="Review-Gate",
            status="ok",
            detail="Review-Gate ist frei.",
            next_action="Keine Aktion erforderlich.",
            action_path="/api/v1/review/gates",
            count=0,
        )

    def _tax_years_check(self, snapshot_status: str, bmf_report: object | None) -> ProductReadinessCheck:
        if bmf_report is None:
            return ProductReadinessCheck(
                key="tax_years",
                label="Steuerjahre",
                status="warning",
                detail=f"BMF-Filing-Readiness-Snapshot ist {snapshot_status}.",
                next_action="BMF-Filing-Readiness-Snapshot erzeugen.",
                action_path="/api/v1/tax-methodology/bmf-filing-readiness-snapshot",
                count=1,
            )
        blocked = len(bmf_report.blocked_years)
        review = len(bmf_report.review_years)
        conservative = len(bmf_report.conservative_appendix_years)
        if blocked > 0:
            return ProductReadinessCheck(
                key="tax_years",
                label="Steuerjahre",
                status="blocker",
                detail=f"{blocked} Steuerjahr(e) sind im BMF-Snapshot blockiert.",
                next_action="BMF-Finalisierung und Jahreschecks pruefen.",
                action_path="/api/v1/tax-methodology/bmf-finalization-matrix",
                count=blocked,
            )
        if review + conservative > 0:
            return ProductReadinessCheck(
                key="tax_years",
                label="Steuerjahre",
                status="warning",
                detail=f"{review} Review-Jahr(e), {conservative} konservativ abgabefaehige Jahr(e).",
                next_action="Jahrespakete und konservative Anlagen pruefen.",
                action_path="/api/v1/tax-methodology/bmf-filing-readiness",
                count=review + conservative,
            )
        return ProductReadinessCheck(
            key="tax_years",
            label="Steuerjahre",
            status="ok",
            detail=f"{len(bmf_report.ready_years)} Steuerjahr(e) sind BMF-ready.",
            next_action="Keine Aktion erforderlich.",
            action_path="/api/v1/tax-methodology/bmf-filing-readiness",
            count=0,
        )

    def _evidence_package_check(self, snapshot_status: str, bmf_report: object | None) -> ProductReadinessCheck:
        if bmf_report is None:
            return ProductReadinessCheck(
                key="evidence_package",
                label="Belegpakete",
                status="warning",
                detail=f"Belegpaket-Status haengt am BMF-Snapshot ({snapshot_status}).",
                next_action="Report-Center nach Snapshot-Erzeugung pruefen.",
                action_path="/api/v1/reports/center",
                count=1,
            )
        years = len(bmf_report.ready_years) + len(bmf_report.conservative_appendix_years)
        return ProductReadinessCheck(
            key="evidence_package",
            label="Belegpakete",
            status="ok" if years > 0 else "info",
            detail=f"{years} Jahr(e) haben einen abgabefaehigen Status fuer Belegpakete.",
            next_action="Belegpaket-Index im Exportbereich pruefen.",
            action_path="/api/v1/export/evidence-package-index.json",
            count=0,
        )

    def _portfolio_live_check(
        self,
        sources: list[ProductReadinessSource],
        overview_health_status: str,
    ) -> ProductReadinessCheck:
        warnings = sum(1 for source in sources if source.live_status in {"missing", "stale", "missing_snapshot"})
        delta_warnings = sum(1 for source in sources if source.status == "warning")
        if overview_health_status == "blocked":
            return ProductReadinessCheck(
                key="portfolio_live",
                label="Live-Abgleich",
                status="blocker",
                detail="Die Quellenuebersicht meldet einen blockierenden Live-/Portfolio-Zustand.",
                next_action="Quellenabgleich pruefen.",
                action_path="/api/v1/sources/overview",
                count=max(warnings, 1),
            )
        if warnings > 0 or delta_warnings > 0:
            return ProductReadinessCheck(
                key="portfolio_live",
                label="Live-Abgleich",
                status="warning",
                detail=(
                    f"{warnings} Quelle(n) haben keinen frischen Live-Status; "
                    f"{delta_warnings} Quelle(n) haben ein erklaerungsbeduerftiges Live-/Ledger-Delta."
                ),
                next_action="Quellen-Drilldown und Reconciliation-Report pruefen.",
                action_path="/api/v1/portfolio/reconciliation",
                count=max(warnings, delta_warnings),
            )
        return ProductReadinessCheck(
            key="portfolio_live",
            label="Live-Abgleich",
            status="ok",
            detail="Live-/Ledger-Abgleich meldet keinen offenen Quellenstatus.",
            next_action="Keine Aktion erforderlich.",
            action_path="/api/v1/portfolio/reconciliation",
            count=0,
        )

    def _overall_status(
        self,
        checks: list[ProductReadinessCheck],
        sources: list[ProductReadinessSource],
    ) -> ProductReadinessStatus:
        if not sources:
            return "setup_required"
        if any(source.status == "blocker" and source.credential_status in self.CREDENTIAL_BLOCKERS for source in sources):
            return "setup_required"
        if any(check.status == "blocker" for check in checks):
            return "blocked"
        if any(check.status == "warning" for check in checks):
            return "review"
        return "ready"

    def _headline(self, overall: ProductReadinessStatus) -> str:
        return {
            "ready": "Abgabe-Workflow ist bereit",
            "review": "Abgabe-Workflow ist nutzbar, aber Review bleibt offen",
            "blocked": "Abgabe-Workflow ist blockiert",
            "setup_required": "Quellen-Setup ist noch nicht vollstaendig",
        }[overall]
