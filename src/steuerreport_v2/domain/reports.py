from __future__ import annotations

from steuerreport_v2.private_settings import private_value

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.reports import (
    EvidenceManifest,
    EvidenceManifestFile,
    EvidencePackageIndex,
    EvidencePackageIndexFile,
    EvidencePackageIndexGroup,
    ReportEvidenceHealth,
    ReportAction,
    ReportArtifact,
    ReportCenterStatus,
    ReportQualityWarning,
    ReportYearCard,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax_time import (
    event_reporting_year_sql,
    reporting_year_sql,
    tax_line_within_year_sql,
)
from steuerreport_v2.domain.valuation import PriceCoverageService


class ReportCenterService:
    FAIRSPOT_STAKING_WALLET = private_value('staking_route_wallet', '')
    EVIDENCE_GROUP_PATHS = {
        "structure": "01_Struktur_Audit",
        "tax": "02_Steuerliche_CSVs",
        "review": "03_Review_Entscheidungen",
        "prices_parity": "04_Preise_Paritaet",
        "hnt": "05_HNT_Fairspot",
        "solana_fifo": "06_Solana_FIFO_Belege",
        "other": "99_Sonstige_Belege",
    }
    EVIDENCE_FILENAMES = {
        "audit-json": "audit.json",
        "elster-prep": "elster-prep.json",
        "review-decisions": "review-decisions.csv",
        "token-risk-documentation": "token-risk-documentation.csv",
        "price-gaps": "price-gaps.csv",
        "price-requirements": "price-requirements.csv",
        "parity-diagnostics": "parity-diagnostics.csv",
        "hnt-provenance-timeline": "hnt-provenance-timeline.csv",
        "hnt-provenance-events": "hnt-provenance-events.csv",
        "hnt-fairspot-timeline": "hnt-fairspot-timeline.csv",
        "hnt-fairspot-events": "hnt-fairspot-events.csv",
        "binance-fiat-deposits": "binance-fiat-deposits.csv",
        "tax-lines": "tax-lines.csv",
        "derivative-lines": "derivative-lines.csv",
        "tax-income-guide": "tax-income-guide.csv",
        "tax-external-inflows": "tax-external-inflows.csv",
        "tax-solana-stablecoin-swap-evidence": "tax-solana-stablecoin-swap-evidence.csv",
        "tax-solana-stablecoin-swap-fifo-lines": "tax-solana-stablecoin-swap-fifo-lines.csv",
        "tax-helium-swap-context": "tax-helium-swap-context.csv",
        "tax-helium-swap-evidence-review": "tax-helium-swap-evidence-review.csv",
        "tax-helium-swap-alchemy-audit": "tax-helium-swap-alchemy-audit.json",
        "tax-payment-overview": "tax-payment-overview.json",
        "solscan-evidence-trace": "solscan-evidence-trace.json",
        "helium-solana-reward-rpc-evidence": "helium-solana-reward-rpc-evidence.json",
        "solana-tx-alchemy-audit": "solana-tx-alchemy-audit.json",
        "solana-failed-tx-tax-impact": "solana-failed-tx-tax-impact.json",
        "all-transaction-evidence-matrix": "all-transaction-evidence-matrix.json",
        "all-transaction-evidence-closure": "all-transaction-evidence-closure.json",
        "all-transaction-open-detail-review": "all-transaction-open-detail-review.json",
        "all-transaction-decision-candidates": "all-transaction-decision-candidates.json",
    }
    EVIDENCE_GROUPS = {
        "audit-json": ("structure", "Struktur und Audit"),
        "elster-prep": ("structure", "Struktur und Audit"),
        "review-decisions": ("review", "Review-Entscheidungen"),
        "token-risk-documentation": ("review", "Review-Entscheidungen"),
        "price-gaps": ("prices_parity", "Preise und Paritaet"),
        "price-requirements": ("prices_parity", "Preise und Paritaet"),
        "parity-diagnostics": ("prices_parity", "Preise und Paritaet"),
        "hnt-provenance-timeline": ("hnt", "HNT und Fairspot"),
        "hnt-provenance-events": ("hnt", "HNT und Fairspot"),
        "hnt-fairspot-timeline": ("hnt", "HNT und Fairspot"),
        "hnt-fairspot-events": ("hnt", "HNT und Fairspot"),
        "binance-fiat-deposits": ("tax", "Steuerliche CSVs"),
        "tax-lines": ("tax", "Steuerliche CSVs"),
        "derivative-lines": ("tax", "Steuerliche CSVs"),
        "tax-income-guide": ("tax", "Steuerliche CSVs"),
        "tax-external-inflows": ("tax", "Steuerliche CSVs"),
        "tax-solana-stablecoin-swap-evidence": ("solana_fifo", "Solana FIFO-Belege"),
        "tax-solana-stablecoin-swap-fifo-lines": ("solana_fifo", "Solana FIFO-Belege"),
        "tax-helium-swap-context": ("solana_fifo", "Solana FIFO-Belege"),
        "tax-helium-swap-evidence-review": ("solana_fifo", "Solana FIFO-Belege"),
        "tax-helium-swap-alchemy-audit": ("solana_fifo", "Solana FIFO-Belege"),
        "tax-payment-overview": ("tax", "Steuerliche CSVs"),
        "solscan-evidence-trace": ("solana_fifo", "Solana FIFO-Belege"),
        "helium-solana-reward-rpc-evidence": ("solana_fifo", "Solana FIFO-Belege"),
        "solana-tx-alchemy-audit": ("solana_fifo", "Solana FIFO-Belege"),
        "solana-failed-tx-tax-impact": ("solana_fifo", "Solana FIFO-Belege"),
        "all-transaction-evidence-matrix": ("solana_fifo", "Solana FIFO-Belege"),
        "all-transaction-evidence-closure": ("solana_fifo", "Solana FIFO-Belege"),
        "all-transaction-open-detail-review": ("solana_fifo", "Solana FIFO-Belege"),
        "all-transaction-decision-candidates": ("solana_fifo", "Solana FIFO-Belege"),
    }
    CSV_EXPORTS = [
        ("review-decisions", "Review-Decisions CSV", "/api/v1/export/review-decisions.csv"),
        ("token-risk-documentation", "Token-Risiko Dokumentation CSV", "/api/v1/export/token-risk-documentation.csv"),
        ("price-gaps", "Preis-Gaps CSV", "/api/v1/export/price-gaps.csv"),
        ("price-requirements", "Preis-Anforderungen CSV", "/api/v1/export/price-requirements.csv"),
        ("parity-diagnostics", "Paritaetsdiagnostik CSV", "/api/v1/export/parity-diagnostics.csv"),
        ("hnt-provenance-timeline", "HNT-Herkunft Timeline CSV", "/api/v1/export/hnt-provenance-timeline.csv"),
        ("hnt-provenance-events", "HNT-Herkunft Events CSV", "/api/v1/export/hnt-provenance-events.csv"),
        (
            "hnt-fairspot-timeline",
            "HNT-Fairspot Timeline CSV",
            f"/api/v1/export/hnt-provenance-timeline.csv?account={FAIRSPOT_STAKING_WALLET}",
        ),
        (
            "hnt-fairspot-events",
            "HNT-Fairspot Events CSV",
            f"/api/v1/export/hnt-provenance-events.csv?account={FAIRSPOT_STAKING_WALLET}",
        ),
        ("binance-fiat-deposits", "Binance-Fiat-Einzahlungen CSV", "/api/v1/export/binance-fiat-deposits.csv"),
        ("tax-lines", "Tax-Lines CSV", "/api/v1/export/tax-lines.csv"),
        ("derivative-lines", "Derivate-Lines CSV", "/api/v1/export/derivative-lines.csv"),
        ("tax-income-guide", "Mining/Reward/Income Guide CSV", "/api/v1/export/tax-income-guide.csv"),
        ("tax-external-inflows", "Externe Solana-Zufluesse CSV", "/api/v1/export/tax-external-inflows.csv"),
        (
            "tax-solana-stablecoin-swap-evidence",
            "Solana Stablecoin Swap Evidence CSV",
            "/api/v1/export/tax-solana-stablecoin-swap-evidence.csv",
        ),
        (
            "tax-solana-stablecoin-swap-fifo-lines",
            "Solana Stablecoin Swap FIFO-Splits CSV",
            "/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv",
        ),
        (
            "tax-helium-swap-context",
            "Helium Swap-/Trading-Kontext CSV",
            "/api/v1/export/tax-helium-swap-context.csv",
        ),
        (
            "tax-helium-swap-evidence-review",
            "Helium Swap-TxID Belegmatrix CSV",
            "/api/v1/export/tax-helium-swap-evidence-review.csv",
        ),
        (
            "tax-helium-swap-alchemy-audit",
            "Helium Swap Alchemy Onchain-Audit JSON",
            "/api/v1/export/tax-helium-swap-alchemy-audit.json",
        ),
        (
            "solana-tx-alchemy-audit",
            "Solana RPC TxID Alchemy-Audit JSON",
            "/api/v1/export/solana-tx-alchemy-audit.json",
        ),
        (
            "solana-failed-tx-tax-impact",
            "Solana Failed-Tx Steuerwirkungspruefung JSON",
            "/api/v1/export/solana-failed-tx-tax-impact.json",
        ),
        (
            "all-transaction-evidence-matrix",
            "Gesamt-Transaktions-Belegmatrix JSON",
            "/api/v1/export/all-transaction-evidence-matrix.json",
        ),
        (
            "all-transaction-evidence-closure",
            "Gesamt-Transaktions-Abschlussreport JSON",
            "/api/v1/export/all-transaction-evidence-closure.json",
        ),
        (
            "all-transaction-open-detail-review",
            "Offene Transaktionen Detailreview JSON",
            "/api/v1/export/all-transaction-open-detail-review.json",
        ),
        (
            "all-transaction-decision-candidates",
            "Offene Transaktionen Entscheidungskandidaten JSON",
            "/api/v1/export/all-transaction-decision-candidates.json",
        ),
    ]

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def center(self) -> ReportCenterStatus:
        from steuerreport_v2.domain.product_readiness import ProductReadinessService

        export_service = ExportService(self.store)
        filing = ProductReadinessService(self.store).report()
        price_coverage = PriceCoverageService(self.store).report()
        readiness = export_service.readiness(price_coverage=price_coverage)
        packages = export_service.list_packages()
        created_packages = [package for package in packages if package.status == "created"]
        blocked_packages = [package for package in packages if package.status == "blocked"]
        latest_package = packages[0] if packages else None
        latest_created_package = created_packages[0] if created_packages else None
        low_confidence_prices = self._low_confidence_price_count()
        proxy_prices = self._proxy_price_count()
        decisions_without_evidence = self._manual_review_decisions_without_evidence()
        external_inflow_risk = self._external_inflow_risk()
        evidence_health = self._evidence_health()

        quality_warnings = self._quality_warnings(
            readiness=readiness,
            missing_price_count=price_coverage.missing_count,
            missing_price_assets=price_coverage.missing_assets,
            low_confidence_prices=low_confidence_prices,
            proxy_prices=proxy_prices,
            decisions_without_evidence=decisions_without_evidence,
            external_inflow_risk=external_inflow_risk,
        )

        return ReportCenterStatus(
            generated_at=datetime.now(timezone.utc),
            export_allowed=readiness.allow_export,
            export_status="Vorschau technisch erzeugbar" if readiness.allow_export else "blockiert",
            max_pdf_pages_per_file=readiness.max_pdf_pages_per_file,
            packages_count=len(packages),
            created_pdf_packages_count=len(created_packages),
            blocked_pdf_packages_count=len(blocked_packages),
            latest_package_created_at=latest_package.created_at if latest_package else None,
            years=self._year_cards(
                allow_export=readiness.allow_export,
                has_created_package=bool(created_packages),
                latest_created_at=getattr(latest_created_package, "created_at", None),
                final_years=set(filing.ready_years) if filing.can_file_without_review else set(),
            ),
            artifacts=self._artifacts(readiness.allow_export, created_packages, latest_created_package),
            csv_exports=self._csv_exports(),
            actions=self._actions(readiness.allow_export),
            quality_warnings=quality_warnings,
            evidence_health=evidence_health,
            packages=packages[:20],
            methodology=(
                "Fuehrt vorhandene Exportfunktionen zusammen: PDF-Pakete, "
                "Audit JSON, ELSTER-Prep und CSV-Downloads. Der Quality-Check "
                "liest Export-Gate, Preisdeckung, Preisvertrauen und Review-"
                "Entscheidungen, schreibt aber keine Steuerdaten."
            ),
        )

    def _evidence_health(self) -> ReportEvidenceHealth:
        report = ReviewService(self.store).evidence_traces()
        if report.missing_decision_count:
            status = "missing_decision"
        elif report.legacy_ref_count:
            status = "legacy_ref"
        elif report.traces_count and report.canonical_count == report.traces_count:
            status = "complete"
        else:
            status = "partial"
        return ReportEvidenceHealth(
            status=status,
            traces_count=report.traces_count,
            canonical_count=report.canonical_count,
            legacy_ref_count=report.legacy_ref_count,
            missing_decision_count=report.missing_decision_count,
            detail=(
                "Solana/FIFO-Belegspuren sind kanonisch verlinkt."
                if status == "complete"
                else "Mindestens eine Review-Belegspur ist noch nicht kanonisch."
            ),
        )

    def _year_cards(
        self,
        *,
        allow_export: bool,
        has_created_package: bool,
        latest_created_at: datetime | None,
        final_years: set[int] | None = None,
    ) -> list[ReportYearCard]:
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                with years as (
                    select year from range(2020, 2027) as t(year)
                    union
                    select distinct {reporting_year_sql('disposed_at')} as year from tax_lines
                    union
                    select distinct {event_reporting_year_sql('event', 'raw')} as year
                    from canonical_events event
                    left join raw_objects raw on raw.raw_object_id = event.raw_object_id
                    where event.event_type in ('reward', 'staking', 'mining', 'income')
                    union
                    select distinct {reporting_year_sql('event_time')} as year from derivative_lines
                ),
                taxable as (
                    select
                        {reporting_year_sql('disposed_at')} as year,
                        count(*)::integer as tax_lines_count,
                        coalesce(sum(gain_loss_eur), 0) as realized_gain_loss_eur
                    from tax_lines
                    where {tax_line_within_year_sql()}
                    group by year
                ),
                tax_free as (
                    select
                        {reporting_year_sql('disposed_at')} as year,
                        count(*)::integer as tax_free_lines_count,
                        coalesce(sum(gain_loss_eur), 0) as tax_free_gain_loss_eur
                    from tax_lines
                    where not {tax_line_within_year_sql()}
                    group by year
                ),
                income as (
                    select
                        {event_reporting_year_sql('e', 'raw')} as year,
                        count(*)::integer as income_events_count,
                        coalesce(sum(l.cost_basis_eur_total), 0) as rewards_income_eur
                    from canonical_events e
                    left join raw_objects raw on raw.raw_object_id = e.raw_object_id
                    left join tax_lots l on l.source_event_id = e.event_id
                    where e.event_type in ('reward', 'mining')
                      and upper(e.asset) in ('HNT', 'IOT', 'MOBILE')
                    group by year
                ),
                derivatives as (
                    select
                        {reporting_year_sql('event_time')} as year,
                        count(*)::integer as derivative_lines_count,
                        coalesce(sum(value_eur), 0) as derivative_pnl_eur
                    from derivative_lines
                    group by year
                ),
                activity as (
                    select {reporting_year_sql('disposed_at')} as year, count(*)::integer as events
                    from tax_lines
                    group by year
                    union all
                    select {event_reporting_year_sql('event', 'raw')} as year, count(*)::integer as events
                    from canonical_events event
                    left join raw_objects raw on raw.raw_object_id = event.raw_object_id
                    where event.event_type in ('reward', 'staking', 'mining', 'income')
                    group by year
                    union all
                    select {reporting_year_sql('event_time')} as year, count(*)::integer as events
                    from derivative_lines
                    group by year
                ),
                activity_by_year as (
                    select year, sum(events)::integer as events
                    from activity
                    group by year
                )
                select
                    y.year,
                    coalesce(t.tax_lines_count, 0) as tax_lines_count,
                    coalesce(t.realized_gain_loss_eur, 0) as realized_gain_loss_eur,
                    coalesce(i.rewards_income_eur, 0) as rewards_income_eur,
                    coalesce(d.derivative_pnl_eur, 0) as derivative_pnl_eur,
                    coalesce(f.tax_free_gain_loss_eur, 0) as tax_free_gain_loss_eur,
                    coalesce(f.tax_free_lines_count, 0) as tax_free_lines_count,
                    coalesce(a.events, 0) as activity_events
                from years y
                left join taxable t on t.year = y.year
                left join tax_free f on f.year = y.year
                left join income i on i.year = y.year
                left join derivatives d on d.year = y.year
                left join activity_by_year a on a.year = y.year
                order by y.year
                """
            ).fetchall()
        cex_anchor_counts = self._cex_fifo_anchor_counts_by_year()
        cards: list[ReportYearCard] = []
        for (
            year,
            tax_lines_count,
            gain_loss,
            rewards_income,
            derivative_pnl,
            tax_free_gain_loss,
            tax_free_lines_count,
            activity_events,
        ) in rows:
            has_activity = int(activity_events or 0) > 0
            state = "finished" if has_activity else "empty"
            label = "fertig" if has_activity else "leer"
            filing_status = ("ready" if year in (final_years or set()) else "preview") if has_activity and allow_export else "blocked" if has_activity else "empty"
            cex_anchor_count = cex_anchor_counts.get(int(year), 0)
            cex_anchor_endpoint = (
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility"
                "?source_exchange=bitget&target_cex=binance&network=SOL"
                if cex_anchor_count
                else None
            )
            required_evidence_refs = self._required_year_evidence_refs(
                year=int(year),
                gain_loss=Decimal(str(gain_loss or 0)),
                rewards_income=Decimal(str(rewards_income or 0)),
                derivative_pnl=Decimal(str(derivative_pnl or 0)),
                tax_free_lines_count=int(tax_free_lines_count or 0),
                cex_anchor_endpoint=cex_anchor_endpoint,
            )
            evidence_status = self._year_evidence_status(
                has_activity=has_activity,
                allow_export=allow_export,
                required_evidence_refs=required_evidence_refs,
            )
            cards.append(
                ReportYearCard(
                    year=year,
                    label=label,
                    tax_state=state,
                    export_blocked=not allow_export,
                    pdf_status=self._pdf_status(allow_export, False, has_created_package),
                    audit_status="ready" if allow_export else "available",
                    elster_prep_status="ready" if allow_export else "available",
                    csv_status="available",
                    tax_lines_count=tax_lines_count,
                    review_issues_count=0,
                    realized_gain_loss_eur=str(gain_loss),
                    rewards_mining_staking_income_eur=str(rewards_income),
                    derivative_pnl_eur=str(derivative_pnl),
                    tax_free_private_disposals_eur=str(tax_free_gain_loss),
                    tax_free_lines_count=int(tax_free_lines_count or 0),
                    filing_summary=self._year_filing_summary_text(
                        year=year,
                        gain_loss=Decimal(str(gain_loss or 0)),
                        rewards_income=Decimal(str(rewards_income or 0)),
                        derivative_pnl=Decimal(str(derivative_pnl or 0)),
                        tax_free_gain_loss=Decimal(str(tax_free_gain_loss or 0)),
                        tax_free_lines_count=int(tax_free_lines_count or 0),
                    ),
                    filing_status=filing_status,
                    filing_status_label=self._filing_status_label(filing_status),
                    evidence_status=evidence_status,
                    evidence_status_label=self._evidence_status_label(evidence_status),
                    evidence_summary=self._year_evidence_summary(
                        has_activity=has_activity,
                        allow_export=allow_export,
                        required_evidence_refs=required_evidence_refs,
                    ),
                    package_status="available" if allow_export else "review",
                    package_status_label=(
                        "Schnelles Jahrespaket abrufbar"
                        if allow_export
                        else "Jahrespaket abrufbar, Review beachten"
                    ),
                    next_action_label=self._year_next_action_label(
                        has_activity=has_activity,
                        allow_export=allow_export,
                    ),
                    required_evidence_labels=[
                        self._evidence_ref_label(ref) for ref in required_evidence_refs
                    ],
                    filing_endpoint=f"/api/v1/tax-years/{year}/filing-summary",
                    evidence_endpoint=f"/api/v1/tax-years/{year}/evidence",
                    evidence_package_endpoint=f"/api/v1/export/tax-years/{year}/evidence-package.zip",
                    wallet_fifo_endpoint=f"/api/v1/tax-years/{year}/wallet-fifo-delta",
                    wallet_fifo_gaps_endpoint=f"/api/v1/tax-years/{year}/wallet-fifo-gaps?limit=80",
                    required_evidence_refs=required_evidence_refs,
                    required_evidence_count=len(required_evidence_refs),
                    expected_package_files_count=self._expected_year_package_files_count(required_evidence_refs),
                    cex_fifo_anchor_status="documented" if cex_anchor_count else "none",
                    cex_fifo_anchor_status_label=(
                        f"{cex_anchor_count} CEX-FIFO-Anker dokumentiert"
                        if cex_anchor_count
                        else "Keine CEX-FIFO-Anker"
                    ),
                    cex_fifo_anchor_decisions_count=cex_anchor_count,
                    cex_fifo_anchor_endpoint=cex_anchor_endpoint,
                    primary_action=(
                        "Jahreserklaerung und Pflichtbelege pruefen"
                        if has_activity
                        else "Keine V2-Eingabewerte; Belegpaket archivieren"
                    ),
                    latest_pdf_created_at=latest_created_at,
                )
            )
        return cards

    def _cex_fifo_anchor_counts_by_year(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "cex_exchange_outflow":
                continue
            if decision.payload.get("decision_status") != "transfer_neutral_fifo_carry_forward_reviewed":
                continue
            year_raw = decision.payload.get("year")
            if year_raw is None and ":year:" in decision.scope:
                parts = decision.scope.split(":")
                try:
                    year_raw = parts[parts.index("year") + 1]
                except (ValueError, IndexError):
                    year_raw = None
            try:
                year = int(str(year_raw))
            except (TypeError, ValueError):
                continue
            counts[year] = counts.get(year, 0) + 1
        return counts

    @staticmethod
    def _filing_status_label(status: str) -> str:
        if status == "preview":
            return "Vorschau - Jahresfreigabe offen"
        if status == "ready":
            return "Eingabehilfe bereit"
        if status == "blocked":
            return "Vor Einreichung pruefen"
        return "Keine V2-Eingabewerte"

    @staticmethod
    def _year_evidence_status(
        *,
        has_activity: bool,
        allow_export: bool,
        required_evidence_refs: list[str],
    ) -> str:
        if not allow_export:
            return "review"
        if has_activity:
            return "complete"
        if required_evidence_refs:
            return "archive_only"
        return "empty"

    @staticmethod
    def _evidence_status_label(status: str) -> str:
        if status == "complete":
            return "Nachweise vollstaendig"
        if status == "review":
            return "Nachweise pruefen"
        if status == "archive_only":
            return "Nur archivieren"
        return "Keine Belege noetig"

    def _year_evidence_summary(
        self,
        *,
        has_activity: bool,
        allow_export: bool,
        required_evidence_refs: list[str],
    ) -> str:
        if not allow_export:
            return (
                "Review-Gate ist blockiert. Jahrespaket kann gelesen werden, "
                "aber Einreichung erst nach Klaerung."
            )
        if has_activity:
            return (
                f"{len(required_evidence_refs)} Pflichtbeleg(e) plus Wallet-FIFO-Artefakte "
                "im Jahrespaket. Belege vor Einreichung gegen die Eingabehilfe pruefen."
            )
        return (
            "Keine V2-Eingabewerte. Jahrespaket dient als Archiv- und Nullaktivitaetsnachweis."
        )

    @staticmethod
    def _year_next_action_label(*, has_activity: bool, allow_export: bool) -> str:
        if not allow_export:
            return "Erst Review-Gate klaeren"
        if has_activity:
            return "Eingabehilfe pruefen und Jahrespaket speichern"
        return "Archivpaket speichern"

    @staticmethod
    def _evidence_ref_label(ref: str) -> str:
        if "cex-exchange-outflow-anchor-feasibility" in ref:
            return "CEX-FIFO-Anker"
        labels = {
            "/api/v1/export/tax-payment-overview.json": "Zahlungsuebersicht",
            "/api/v1/export/evidence-package.zip": "Gesamt-Belegpaket",
            "/api/v1/export/tax-lines.csv": "FIFO Tax-Lines",
            "/api/v1/export/tax-income-guide.csv": "Einzutragende Rewards/Mining/Staking",
            "/api/v1/export/derivative-lines.csv": "Derivate",
            "/api/v1/export/tax-external-inflows.csv": "Externe Zufluesse",
            "/api/v1/export/hnt-provenance-events.csv": "HNT Events",
            "/api/v1/export/hnt-provenance-timeline.csv": "HNT Timeline",
        }
        return labels.get(ref, ref.rsplit("/", 1)[-1])

    def _expected_year_package_files_count(self, required_evidence_refs: list[str]) -> int:
        base_files = 4  # README, Manifest, Filing Summary, Evidence Map.
        always_included = {"/api/v1/export/tax-payment-overview.json"}
        wallet_fifo_files = 3
        csv_refs = {
            "/api/v1/export/tax-lines.csv",
            "/api/v1/export/tax-income-guide.csv",
            "/api/v1/export/derivative-lines.csv",
            "/api/v1/export/tax-external-inflows.csv",
            "/api/v1/export/hnt-provenance-events.csv",
            "/api/v1/export/hnt-provenance-timeline.csv",
        }
        return (
            base_files
            + len(always_included)
            + wallet_fifo_files
            + sum(1 for ref in required_evidence_refs if ref in csv_refs)
        )

    def _required_year_evidence_refs(
        self,
        *,
        year: int,
        gain_loss: Decimal,
        rewards_income: Decimal,
        derivative_pnl: Decimal,
        tax_free_lines_count: int,
        cex_anchor_endpoint: str | None = None,
    ) -> list[str]:
        refs = ["/api/v1/export/tax-payment-overview.json", "/api/v1/export/evidence-package.zip"]
        if gain_loss or tax_free_lines_count:
            refs.append("/api/v1/export/tax-lines.csv")
        if rewards_income:
            refs.append("/api/v1/export/tax-income-guide.csv")
        if derivative_pnl:
            refs.append("/api/v1/export/derivative-lines.csv")
        if cex_anchor_endpoint:
            refs.append(cex_anchor_endpoint)
        return refs

    def _year_filing_summary_text(
        self,
        *,
        year: int,
        gain_loss: Decimal,
        rewards_income: Decimal,
        derivative_pnl: Decimal,
        tax_free_gain_loss: Decimal,
        tax_free_lines_count: int,
    ) -> str:
        parts = []
        if gain_loss < 0:
            parts.append(f"privater Verlust {self._fmt_eur(gain_loss)}")
        elif gain_loss > 0:
            parts.append(f"privater Gewinn {self._fmt_eur(gain_loss)}")
        if rewards_income:
            parts.append(f"einzutragende Rewards/Mining/Staking {self._fmt_eur(rewards_income)}")
        if derivative_pnl:
            parts.append(f"Derivate {self._fmt_eur(derivative_pnl)}")
        if tax_free_lines_count:
            parts.append(f"steuerfrei nach Haltefrist {self._fmt_eur(tax_free_gain_loss)}")
        if not parts:
            parts.append("keine V2-Eingabebetraege")
        return f"{year}: " + "; ".join(parts) + "."

    @staticmethod
    def _fmt_eur(value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01'))} EUR"

    def _artifacts(
        self,
        allow_export: bool,
        created_packages: list[object],
        latest_created_package: object | None,
    ) -> list[ReportArtifact]:
        pdf_note = "PDF-Paket erzeugbar." if allow_export else "PDF-Erzeugung durch Export-Gate blockiert."
        artifacts = [
            ReportArtifact(
                artifact_id="pdf-package",
                label="PDF-Paket",
                kind="pdf",
                status=self._pdf_status(allow_export, False, bool(created_packages)),
                endpoint="/api/v1/export/pdf",
                package_id=getattr(latest_created_package, "package_id", None),
                file_index=getattr(latest_created_package, "file_index", None),
                page_count=getattr(latest_created_package, "page_count", None),
                created_at=getattr(latest_created_package, "created_at", None),
                note=pdf_note,
            ),
            ReportArtifact(
                artifact_id="audit-json",
                label="Audit JSON",
                kind="audit_json",
                status="ready" if allow_export else "available",
                endpoint="/api/v1/export/audit.json",
                note=(
                    "Audit-Daten sind lesend erzeugbar und enthalten Review-/Preis-/"
                    "Parity- sowie Token-Risiko-Dokumentationskontext."
                ),
            ),
            ReportArtifact(
                artifact_id="elster-prep",
                label="ELSTER-Prep",
                kind="elster_prep",
                status="ready" if allow_export else "available",
                endpoint="/api/v1/export/elster-prep",
                note="Direkte ERiC-Uebertragung bleibt deaktiviert.",
            ),
            ReportArtifact(
                artifact_id="tax-payment-overview",
                label="Steuer-Eingabezettel JSON",
                kind="json",
                status="available",
                endpoint="/api/v1/export/tax-payment-overview.json",
                note="Read-only Jahresuebersicht: eintragen, nur Beleg, pruefen.",
            ),
            ReportArtifact(
                artifact_id="evidence-package",
                label="Belegpaket",
                kind="evidence_package",
                status="available",
                endpoint="/api/v1/export/evidence-package.zip",
                note="Read-only ZIP mit Manifest, Audit JSON und pruefungsrelevanten CSV-Belegen.",
            ),
        ]
        return artifacts

    def evidence_manifest(self) -> EvidenceManifest:
        files = [
            EvidenceManifestFile(
                file_id="audit-json",
                label="Audit JSON",
                kind="audit_json",
                endpoint="/api/v1/export/audit.json",
                group="structure",
                group_label="Struktur und Audit",
                note=(
                    "Audit-Snapshot inklusive Review-, Preis-, Paritaets-, "
                    "Token-Risiko- und HNT-Provenance-Kontext."
                ),
            ),
            EvidenceManifestFile(
                file_id="elster-prep",
                label="ELSTER-Prep JSON",
                kind="elster_prep",
                endpoint="/api/v1/export/elster-prep",
                group="structure",
                group_label="Struktur und Audit",
                required=False,
                note="Strukturierte Vorbereitung; direkte ERiC-Uebertragung bleibt deaktiviert.",
            ),
        ]
        files.append(
            EvidenceManifestFile(
                file_id="tax-payment-overview",
                label="Steuer-Eingabezettel JSON",
                kind="json",
                endpoint="/api/v1/export/tax-payment-overview.json",
                group="tax",
                group_label="Steuerliche CSVs",
                required=True,
                note=(
                    "Lesbare Jahresuebersicht mit ASCII-Tabelle und gefuehrten "
                    "Aufgaben je Jahr: eintragen, nur Beleg, pruefen."
                ),
            )
        )
        for artifact in self._csv_exports():
            if artifact.endpoint is None:
                continue
            group, group_label = self.EVIDENCE_GROUPS.get(
                artifact.artifact_id,
                ("other", "Sonstige Belege"),
            )
            files.append(
                EvidenceManifestFile(
                    file_id=artifact.artifact_id,
                    label=artifact.label,
                    kind=artifact.kind,
                    endpoint=artifact.endpoint,
                    group=group,
                    group_label=group_label,
                    required=artifact.artifact_id in {
                        "review-decisions",
                        "parity-diagnostics",
                        "hnt-fairspot-timeline",
                        "hnt-fairspot-events",
                        "tax-lines",
                    },
                    note=artifact.note,
                )
            )
        files.append(
            EvidenceManifestFile(
                file_id="solscan-evidence-trace",
                label="Solscan/RPC Evidence Trace",
                kind="audit_json",
                endpoint="/api/v1/import/solscan/evidence-trace",
                group="solana_fifo",
                group_label="Solana FIFO-Belege",
                required=True,
                note=(
                    "Read-only Belegspur fuer fehlende Solscan-IOT-Signaturen: "
                    "Solscan-CSV, Blockpit-Referenzexport, RPC-Artefakt und "
                    "Review-Kontext ohne Importeffekt."
                ),
            )
        )
        files.append(
            EvidenceManifestFile(
                file_id="helium-solana-reward-rpc-evidence",
                label="Helium/Solana Reward RPC Evidence",
                kind="audit_json",
                endpoint="/api/v1/import/solscan/helium-reward-evidence",
                group="solana_fifo",
                group_label="Solana FIFO-Belege",
                required=True,
                note=(
                    "Read-only Reward-Beleg fuer Solana-Helium-Rewards: "
                    "RPC-Signaturen, Reward-Instructions und positive "
                    "HNT/IOT/MOBILE-Wallet-Deltas ohne Importeffekt."
                ),
            )
        )
        for year, decisions_count in sorted(self._cex_fifo_anchor_counts_by_year().items()):
            files.append(
                EvidenceManifestFile(
                    file_id=f"tax-year-{year}-cex-exchange-outflow-evidence",
                    label=f"CEX Exchange Outflow Evidence {year}",
                    kind="json",
                    endpoint=(
                        f"/api/v1/tax-years/{year}/cex-exchange-outflow-evidence"
                        "?source_exchange=bitget&target_cex=binance&network=SOL"
                    ),
                    group="solana_fifo",
                    group_label="Solana FIFO-Belege",
                    required=True,
                    note=(
                        f"{decisions_count} dokumentierte Bitget -> Binance Exchange-Outflow-"
                        "Entscheidung(en); Beleg fuer steuerneutralen Depotwechsel."
                    ),
                )
            )
            files.append(
                EvidenceManifestFile(
                    file_id=f"tax-year-{year}-cex-exchange-outflow-anchor-feasibility",
                    label=f"CEX-FIFO-Anker Bitget -> Binance {year}",
                    kind="json",
                    endpoint=(
                        f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility"
                        "?source_exchange=bitget&target_cex=binance&network=SOL"
                    ),
                    group="solana_fifo",
                    group_label="Solana FIFO-Belege",
                    required=True,
                    note=(
                        "Read-only Ankerstatus fuer vorhandene Exchange-Outflow-"
                        "Entscheidungen; schreibt keine FIFO-Lots oder Tax-Lines."
                    ),
                )
            )
        return EvidenceManifest(
            generated_at=datetime.now(timezone.utc),
            files=files,
            methodology=(
                "Read-only Belegmanifest. Es listet vorhandene Downloadpfade fuer "
                "Audit JSON, HNT/Fairspot-Provenance, Solana/FIFO-Belegspuren, "
                "Review-Entscheidungen, Parity und steuerliche CSVs. Das Manifest "
                "erzeugt keine Exporte, Imports, FIFO-Rebuilds oder "
                "Review-Entscheidungen."
            ),
        )

    def evidence_package_index(self) -> EvidencePackageIndex:
        manifest = self.evidence_manifest()
        files = [
            EvidencePackageIndexFile(
                path="00_Manifest/evidence-manifest.json",
                file_id="evidence-manifest",
                label="Evidence Manifest",
                group="structure",
                group_label="Struktur und Audit",
                required=True,
                source_endpoint="/api/v1/export/evidence-manifest.json",
            )
        ]
        for file in manifest.files:
            filename = self._evidence_package_filename(file.file_id)
            if filename is None:
                continue
            folder = self.EVIDENCE_GROUP_PATHS.get(file.group, self.EVIDENCE_GROUP_PATHS["other"])
            files.append(
                EvidencePackageIndexFile(
                    path=f"{folder}/{filename}",
                    file_id=file.file_id,
                    label=file.label,
                    group=file.group,
                    group_label=file.group_label,
                    required=file.required,
                    source_endpoint=file.endpoint,
                )
            )
        groups = [
            EvidencePackageIndexGroup(
                group=group,
                folder=folder,
                files_count=sum(1 for file in files if file.path.startswith(f"{folder}/")),
                required_count=sum(
                    1
                    for file in files
                    if file.path.startswith(f"{folder}/") and file.required
                ),
            )
            for group, folder in self.EVIDENCE_GROUP_PATHS.items()
            if any(file.path.startswith(f"{folder}/") for file in files)
        ]
        return EvidencePackageIndex(
            generated_at=datetime.now(timezone.utc),
            manifest_label=manifest.label,
            files_count=len(files),
            groups=groups,
            files=files,
            methodology=(
                "Maschinenlesbarer Index des on-demand Belegpakets. "
                "Er beschreibt ZIP-Pfade und Quellendpunkte, schreibt aber keine Steuerdaten."
            ),
        )

    def _evidence_package_filename(self, file_id: str) -> str | None:
        filename = self.EVIDENCE_FILENAMES.get(file_id)
        if filename is not None:
            return filename
        if file_id.startswith("tax-year-") and (
            file_id.endswith("-cex-exchange-outflow-evidence")
            or file_id.endswith("-cex-exchange-outflow-anchor-feasibility")
        ):
            return f"{file_id}.json"
        return None

    def _csv_exports(self) -> list[ReportArtifact]:
        return [
            ReportArtifact(
                artifact_id=artifact_id,
                label=label,
                kind="csv",
                status="available",
                endpoint=endpoint,
            )
            for artifact_id, label, endpoint in self.CSV_EXPORTS
        ]

    def _actions(self, allow_export: bool) -> list[ReportAction]:
        blocked_reason = None if allow_export else "Export-Gate ist blockiert."
        return [
            ReportAction(
                action_id="create-pdf",
                label="PDF-Paket erzeugen",
                kind="pdf",
                method="POST",
                path="/api/v1/export/pdf",
                enabled=allow_export,
                blocked_reason=blocked_reason,
                description="Erzeugt PDF-Pakete unter Beachtung des 100-Seiten-Limits je Datei.",
            ),
            ReportAction(
                action_id="create-audit-json",
                label="Audit JSON erzeugen",
                kind="audit_json",
                method="POST",
                path="/api/v1/export/audit",
                description="Erzeugt den Audit-Snapshot ueber vorhandene Audit-Logik.",
            ),
            ReportAction(
                action_id="create-elster-prep",
                label="ELSTER-Prep erzeugen",
                kind="elster_prep",
                method="POST",
                path="/api/v1/export/elster-prep",
                description="Erzeugt strukturierte Vorbereitungsdaten ohne direkte ERiC-Uebertragung.",
            ),
        ]

    def _quality_warnings(
        self,
        *,
        readiness: object,
        missing_price_count: int,
        missing_price_assets: list[str],
        low_confidence_prices: int,
        proxy_prices: int,
        decisions_without_evidence: int,
        external_inflow_risk: dict[str, Decimal | int],
    ) -> list[ReportQualityWarning]:
        warnings: list[ReportQualityWarning] = []
        if not getattr(readiness, "allow_export"):
            warnings.append(
                ReportQualityWarning(
                    code="export_gate_blocked",
                    severity="high",
                    message="Export-Gate ist blockiert. PDF-Pakete duerfen nicht erzeugt werden.",
                    count=1,
                    blocks_export=True,
                    action_path="/api/v1/export/readiness",
                )
            )
        current_open = int(getattr(readiness, "review_issues_current_open", 0) or 0)
        historical_open = int(getattr(readiness, "review_issues_historical_open", 0) or 0)
        if current_open:
            warnings.append(
                ReportQualityWarning(
                    code="review_current_open",
                    severity="high",
                    message=f"{current_open} aktuelle Review-Issue(s) sind offen.",
                    count=current_open,
                    blocks_export=True,
                    action_path="/api/v1/review/gates",
                )
            )
        if historical_open:
            warnings.append(
                ReportQualityWarning(
                    code="review_historical_open",
                    severity="medium",
                    message=f"{historical_open} historische Review-Issue(s) bleiben sichtbar.",
                    count=historical_open,
                    blocks_export=False,
                    action_path="/api/v1/review/gates",
                )
            )
        if missing_price_count:
            warnings.append(
                ReportQualityWarning(
                    code="missing_prices",
                    severity="high",
                    message=(
                        f"{missing_price_count} Preisgruppe(n) ohne EUR-Bewertung: "
                        f"{', '.join(missing_price_assets[:8])}"
                    ),
                    count=missing_price_count,
                    blocks_export=True,
                    action_path="/api/v1/prices/coverage",
                )
            )
        if low_confidence_prices:
            warnings.append(
                ReportQualityWarning(
                    code="low_confidence_prices",
                    severity="medium",
                    message=f"{low_confidence_prices} Preis(e) haben Confidence unter 1.0.",
                    count=low_confidence_prices,
                    blocks_export=False,
                    action_path="/api/v1/prices",
                )
            )
        if proxy_prices:
            warnings.append(
                ReportQualityWarning(
                    code="proxy_prices",
                    severity="medium",
                    message=f"{proxy_prices} Preis(e) stammen aus Proxy-Quellen.",
                    count=proxy_prices,
                    blocks_export=False,
                    action_path="/api/v1/prices",
                )
            )
        if decisions_without_evidence:
            warnings.append(
                ReportQualityWarning(
                    code="manual_decisions_without_evidence",
                    severity="medium",
                    message=f"{decisions_without_evidence} manuelle Review-Entscheidung(en) haben keinen Beleglink.",
                    count=decisions_without_evidence,
                    blocks_export=False,
                    action_path="/api/v1/review/decisions",
                )
            )
        external_review = int(external_inflow_risk.get("review_count", 0) or 0)
        external_unmatched = int(external_inflow_risk.get("unmatched_count", 0) or 0)
        external_value = external_inflow_risk.get("review_unmatched_value_eur", Decimal("0"))
        if external_review or external_unmatched:
            value_note = (
                f", Pruefwert {external_value} EUR"
                if external_value
                else "; Wertdetails im Tax-Year-Report/CSV"
            )
            warnings.append(
                ReportQualityWarning(
                    code="external_solana_inflows_need_evidence",
                    severity="medium",
                    message=(
                        "Externe Solana-Zufluesse brauchen Belegpruefung: "
                        f"{external_review} Review-Kandidat(en), {external_unmatched} unmatched"
                        f"{value_note}."
                    ),
                    count=external_review + external_unmatched,
                    blocks_export=False,
                    action_path="/api/v1/export/tax-external-inflows.csv",
                )
            )
        return warnings

    def _external_inflow_risk(self) -> dict[str, Decimal | int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                with tx_context as (
                    select
                        tx_id,
                        count(*) filter (where quantity < 0)::integer as negative_count
                    from canonical_events
                    where tx_id is not null
                    group by tx_id
                )
                select count(*)::integer
                from canonical_events e
                left join tx_context t on t.tx_id = e.tx_id
                where e.source = 'solana_rpc'
                  and e.event_type = 'income'
                  and e.quantity > 0
                  and e.quote_asset is null
                  and coalesce(t.negative_count, 0) = 0
                """
            ).fetchone()
        unmatched_count = int(row[0] or 0)
        return {
            "review_count": 0,
            "unmatched_count": unmatched_count,
            "review_unmatched_value_eur": Decimal("0"),
        }

    def _low_confidence_price_count(self) -> int:
        with self.store.connect() as con:
            row = con.execute(
                "select count(*) from price_ledger where confidence < ?",
                [Decimal("1.0")],
            ).fetchone()
        return int(row[0] or 0)

    def _proxy_price_count(self) -> int:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(*)
                from price_ledger
                where lower(source) like '%proxy%'
                   or lower(source) like '%derived%'
                """
            ).fetchone()
        return int(row[0] or 0)

    def _manual_review_decisions_without_evidence(self) -> int:
        return sum(
            1
            for decision in self.store.list_review_decisions()
            if decision.actor == "user" and not (decision.evidence_ref or "").strip()
        )

    @staticmethod
    def _pdf_status(allow_export: bool, year_export_blocked: bool, has_created_package: bool) -> str:
        if not allow_export or year_export_blocked:
            return "blocked"
        if has_created_package:
            return "ready"
        return "not_created"
