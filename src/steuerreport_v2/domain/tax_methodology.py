from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from steuerreport_v2.contracts.tax_methodology import (
    TaxBmfActionItem,
    TaxBmfActionPlan,
    TaxBmfAmendmentWorklist,
    TaxBmfAmendmentWorklistYear,
    TaxBmfClosureBacklogItem,
    TaxBmfClosureBacklogReport,
    TaxBmfClosureBacklogSnapshot,
    TaxBmfClosureBacklogYear,
    TaxBmfFinalizationMatrix,
    TaxBmfFinalizationRequirement,
    TaxBmfFinalizationYear,
    TaxBmfFilingReadinessReport,
    TaxBmfFilingReadinessSnapshot,
    TaxBmfFilingReadinessYear,
    TaxBmfPriorFilingComparison,
    TaxBmfPriorFilingComparisonYear,
    TaxBmfPriorFilingDeclaredAmounts,
    TaxBmfPriorFilingDeclaredAmountsWrite,
    TaxBmfPriorFilingDeclaredAmountsWriteResult,
    TaxBmfPriorFilingDeclaredYear,
    TaxBmfSubmissionGuide,
    TaxBmfSubmissionGuideYear,
    TaxRewardBmfRecheckReport,
    TaxRewardBmfRecheckYear,
    TaxMethodologyGap,
    TaxMethodologyPolicy,
    TaxMethodologyReport,
    TaxMethodologyStatus,
    TaxMethodologySummary,
    TaxTraceabilityMetric,
    TaxYearComplianceStatus,
)
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.domain.valuation import PriceQualityService


class TaxMethodologyService:
    METHOD_VERSION = "bmf_readiness_v2"
    FIFO_SCOPE = "global_asset_with_wallet_fifo_evidence_overlay_v1"
    ASSET_FIFO_CORRECTION_MIN_ABS_EUR = Decimal("100")
    EXCHANGE_SEQUENCING_GAP_MAX_QUANTITY = Decimal("1")
    EXCHANGE_SEQUENCING_GAP_WINDOW = timedelta(minutes=5)
    EXCHANGE_SEQUENCING_POOLS = {"binance", "bitget", "pionex"}
    DEFAULT_BMF_FILING_READINESS_DIR = Path("/workspace/steuerreport-v2-plan/var/bmf_filing_readiness")
    DEFAULT_BMF_CLOSURE_BACKLOG_DIR = Path("/workspace/steuerreport-v2-plan/var/bmf_closure_backlog")
    PRIOR_FILING_DECLARED_AMOUNTS_SETTING = "tax.prior_filing.declared_amounts"
    PRIOR_FILING_DELTA_TOLERANCE_EUR = Decimal("0.01")
    CONSERVATIVE_REVIEW_ONLY_CODES = {
        "asset_fifo_quote_attribution_documented",
        "gain_evidence_event_level_reconciled",
        "income_only_year",
        "wallet_fifo_delta_present",
        "wallet_fifo_evidence_overlay_ok",
    }

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.tax_years = TaxYearService(store)

    def policy(self) -> TaxMethodologyPolicy:
        return TaxMethodologyPolicy(
            method_version=self.METHOD_VERSION,
            fifo_scope=self.FIFO_SCOPE,
            valuation_policy=(
                "Historische EUR-Werte werden aus Canonical Events, quote-Werten "
                "und Price Ledger abgeleitet; UI-Rundung erfolgt erst in der Anzeige."
            ),
            timezone_policy=(
                "Zeitpunkte werden UTC gespeichert und in Jahresreports nach dem "
                "gespeicherten Event-/Disposal-Jahr aggregiert."
            ),
            rounding_policy=(
                "Backend und Datenbank behalten Decimal-Genauigkeit; EUR-Anzeigen "
                "werden auf zwei Nachkommastellen formatiert."
            ),
            transfer_policy=(
                "Eigene Transfers muessen als Transfer-/Provenance-Kontext belegbar "
                "sein und duerfen nicht als neue Anschaffung ohne Herkunft wirken; "
                "Wallet-/Depot-FIFO wird als BMF-Evidence-Overlay gegen die "
                "bestehende globale FIFO gerechnet."
            ),
            source_policy=(
                "API-, CSV-, Ledger-, Review- und Belegquellen werden read-only "
                "ausgewertet; fehlende Quellen blockieren BMF-Readiness."
            ),
            bmf_reference=(
                "BMF-Schreiben 2025-03-06 zu Kryptowerten, insbesondere "
                "Dokumentation, Verbrauchsfolge, Wallet-/Depotbezug und "
                "Nachvollziehbarkeit."
            ),
        )

    def summary(self, year: int | None = None) -> TaxMethodologySummary:
        generated_at = self._now()
        available_years = [year] if year is not None else self._available_years()
        statuses = [self.status(year) for year in available_years]
        return TaxMethodologySummary(
            generated_at=generated_at,
            years=statuses,
            available_years=available_years,
            policy=self.policy(),
            ok_years=sum(1 for item in statuses if item.status == "ok"),
            review_years=sum(1 for item in statuses if item.status == "review"),
            blocked_years=sum(1 for item in statuses if item.status == "blocked"),
            empty_years=sum(1 for item in statuses if item.status == "empty"),
            methodology=(
                "Read-only BMF-Readiness aus Tax-Year-Status, FIFO-Tabellen, "
                "Wallet-/Depot-FIFO-Evidence, Asset-FIFO-Korrekturreview, "
                "externen Zufluessen, Preisen, Review-Gate und vorhandenen "
                "Belegen. Es werden keine Imports, FIFO-Lots, Tax-Lines, Preise "
                "oder Review-Entscheidungen geschrieben."
            ),
        )

    def bmf_action_plan(
        self,
        year: int | None = None,
        *,
        include_gain_evidence: bool = False,
        prefer_snapshot: bool = False,
    ) -> TaxBmfActionPlan:
        generated_at = self._now()
        available_years = [year] if year is not None else self._available_years()
        if prefer_snapshot and not include_gain_evidence and self._can_use_default_bmf_snapshot():
            snapshot = self.bmf_filing_readiness_snapshot()
            if snapshot.status == "available" and snapshot.report is not None:
                return self._bmf_action_plan_from_readiness_snapshot(
                    snapshot.report,
                    generated_at=generated_at,
                    year=year,
                )
        reports = [
            self.report(item_year, include_gain_evidence=include_gain_evidence)
            for item_year in available_years
        ]
        items = [
            self._action_item_from_gap(report.year, gap)
            for report in reports
            for gap in report.gaps
            if report.status != "empty" or gap.severity != "info"
        ]
        return TaxBmfActionPlan(
            generated_at=generated_at,
            available_years=available_years,
            ready_years=[report.year for report in reports if report.status == "ok"],
            review_years=[report.year for report in reports if report.status == "review"],
            blocked_years=[report.year for report in reports if report.status == "blocked"],
            empty_years=[report.year for report in reports if report.status == "empty"],
            blocking_items_count=sum(1 for item in items if item.blocks_bmf_ready or item.severity == "blocker"),
            review_items_count=sum(1 for item in items if item.severity == "warning"),
            info_items_count=sum(1 for item in items if item.severity == "info"),
            items=sorted(
                items,
                key=lambda item: (
                    0 if item.severity == "blocker" else 1 if item.severity == "warning" else 2,
                    item.year,
                    item.category,
                    item.code,
                ),
            ),
            methodology=(
                "Read-only BMF-Aktionsliste aus den Methodikreports aller Jahre. "
                "Blocker muessen vor einer belastbaren Einreichung fachlich "
                "geschlossen werden; Warnungen markieren dokumentationspflichtige "
                "Deltas. Die Liste schreibt keine Steuerdaten. Schwere "
                "Gain-Evidence-Detailnachweise werden nur mit "
                "include_gain_evidence=true in die Aktionsliste geladen."
            ),
        )

    def _bmf_action_plan_from_readiness_snapshot(
        self,
        report: TaxBmfFilingReadinessReport,
        *,
        generated_at: str,
        year: int | None,
    ) -> TaxBmfActionPlan:
        rows = [row for row in report.years if year is None or row.year == year]
        items: list[TaxBmfActionItem] = []
        for row in rows:
            for code in row.blocking_gap_codes:
                items.append(self._snapshot_action_item(row.year, code, severity="blocker"))
            for code in row.review_gap_codes:
                items.append(self._snapshot_action_item(row.year, code, severity=self._snapshot_review_severity(code)))
        return TaxBmfActionPlan(
            generated_at=generated_at,
            available_years=[row.year for row in rows],
            ready_years=[row.year for row in rows if row.filing_status == "bmf_ready"],
            review_years=[row.year for row in rows if row.filing_status == "review_required"],
            blocked_years=[row.year for row in rows if row.filing_status == "blocked"],
            empty_years=[row.year for row in rows if row.filing_status == "empty"],
            blocking_items_count=sum(1 for item in items if item.severity == "blocker"),
            review_items_count=sum(1 for item in items if item.severity == "warning"),
            info_items_count=sum(1 for item in items if item.severity == "info"),
            items=sorted(
                items,
                key=lambda item: (
                    0 if item.severity == "blocker" else 1 if item.severity == "warning" else 2,
                    item.year,
                    item.category,
                    item.code,
                ),
            ),
            methodology=(
                "Schnelle BMF-Aktionsliste aus dem letzten Filing-Readiness-Snapshot. "
                "Fuer vollstaendige Live-Details den Jahres-Methodikreport oder "
                "include_gain_evidence=true verwenden. Die Liste schreibt keine Steuerdaten."
            ),
        )

    def _snapshot_action_item(
        self,
        year: int,
        code: str,
        *,
        severity: str,
    ) -> TaxBmfActionItem:
        is_blocker = severity == "blocker"
        return TaxBmfActionItem(
            year=year,
            category=self._gap_category(code),
            severity=severity,
            code=code,
            title=self._gap_title(code),
            detail=self._gap_title(code),
            count=1,
            blocks_bmf_ready=is_blocker,
            evidence_ref=f"/api/v1/tax-years/{year}/methodology",
            action=(
                "Blockierenden Punkt im Jahres-Methodikreport oeffnen und Beleg/Review nachziehen."
                if is_blocker
                else "Als konservativen Beleg-/Review-Hinweis im Jahrespaket pruefen und archivieren."
            ),
        )

    def _snapshot_review_severity(self, code: str) -> str:
        if code in {"wallet_fifo_delta_present", "wallet_fifo_exchange_sequencing_documented"}:
            return "warning"
        return "info"

    def bmf_filing_readiness(self, year: int | None = None) -> TaxBmfFilingReadinessReport:
        generated_at = self._now()
        available_years = [year] if year is not None else [
            item_year for item_year in self._available_years() if 2021 <= item_year <= 2025
        ]
        payment_rows = {
            row.year: row
            for row in self.tax_years.payment_overview(years=available_years).rows
        }
        rows = [
            self._bmf_filing_readiness_year(item_year, payment_row=payment_rows.get(item_year))
            for item_year in available_years
        ]
        return TaxBmfFilingReadinessReport(
            generated_at=generated_at,
            years=rows,
            available_years=available_years,
            ready_years=[row.year for row in rows if row.filing_status == "bmf_ready"],
            conservative_appendix_years=[
                row.year for row in rows if row.filing_status == "conservative_appendix"
            ],
            review_years=[row.year for row in rows if row.filing_status == "review_required"],
            blocked_years=[row.year for row in rows if row.filing_status == "blocked"],
            empty_years=[row.year for row in rows if row.filing_status == "empty"],
            ascii_table=self._bmf_filing_readiness_ascii(rows),
            methodology=(
                "Read-only Abschlussmatrix fuer die Steuerjahre. Kombiniert "
                "BMF-Methodology, Filing Summary und die konservative "
                "BMF-Closure-Appendix-Beilage. 'BMF-ready' bleibt streng; "
                "'conservative_appendix' bedeutet nur, dass offene Herkunft "
                "konservativ offengelegt werden kann, ohne eigene Transfers "
                "ungeprueft steuerneutral zu behaupten."
            ),
        )

    def bmf_filing_readiness_snapshot(
        self,
        *,
        artifact_path: Path | None = None,
    ) -> TaxBmfFilingReadinessSnapshot:
        path = artifact_path or self._bmf_filing_readiness_snapshot_path()
        if not path.exists():
            return TaxBmfFilingReadinessSnapshot(
                generated_at=self._now(),
                snapshot_exists=False,
                artifact_path=str(path),
                report=None,
                status="missing",
                note=(
                    "Noch kein BMF-Filing-Readiness-Snapshot vorhanden. "
                    "Erzeuge ihn mit scripts/run_bmf_filing_readiness_snapshot_20260621.py."
                ),
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            report = TaxBmfFilingReadinessReport.model_validate(payload)
        except Exception as exc:
            return TaxBmfFilingReadinessSnapshot(
                generated_at=self._now(),
                snapshot_exists=True,
                artifact_path=str(path),
                report=None,
                status="invalid",
                note=f"Snapshot konnte nicht validiert werden: {exc}",
            )
        return TaxBmfFilingReadinessSnapshot(
            generated_at=self._now(),
            snapshot_exists=True,
            artifact_path=str(path),
            report=report,
            years_count=len(report.years),
            available_years=list(report.available_years),
            ready_years=list(report.ready_years),
            conservative_appendix_years=list(report.conservative_appendix_years),
            review_years=list(report.review_years),
            blocked_years=list(report.blocked_years),
            empty_years=list(report.empty_years),
            status="available",
            note="Read-only Snapshot aus var/bmf_filing_readiness; API berechnet dabei keine Methodology neu.",
        )

    def bmf_finalization_matrix(
        self,
        *,
        years: list[int] | None = None,
        include_reward_recheck: bool = False,
    ) -> TaxBmfFinalizationMatrix:
        generated_at = self._now()
        selected_years = sorted(years if years is not None else [2021, 2022, 2023, 2024, 2025])
        snapshot = self.bmf_filing_readiness_snapshot()
        if snapshot.status == "available" and snapshot.report is not None:
            readiness = snapshot.report
        else:
            readiness = self.bmf_filing_readiness()
        readiness_by_year = {row.year: row for row in readiness.years}
        filing = self.tax_years.filing_matrix()
        if not all(year in {row.year for row in filing.rows} for year in selected_years):
            filing = self.tax_years.filing_matrix(years=selected_years)
        filing_by_year = {row.year: row for row in filing.rows}
        correction = self.tax_years.correction_map()
        if not all(year in {row.year for row in correction.years} for year in selected_years):
            correction = self.tax_years.correction_map(years=selected_years)
        correction_by_year = {row.year: row for row in correction.years}
        reward_by_year: dict[int, object] = {}
        if include_reward_recheck:
            reward = self.reward_bmf_recheck()
            reward_by_year = {row.year: row for row in reward.years}
        stablecoin_anchor = PriceQualityService(self.store).stablecoin_fx_anchor_preview_latest()
        stablecoin_groups_by_year: dict[int, list[object]] = {}
        for group in stablecoin_anchor.groups:
            stablecoin_groups_by_year.setdefault(group.year, []).append(group)

        rows = [
            self._bmf_finalization_year(
                year,
                readiness=readiness_by_year.get(year),
                filing=filing_by_year.get(year),
                correction=correction_by_year.get(year),
                reward=reward_by_year.get(year),
                stablecoin_groups=stablecoin_groups_by_year.get(year, []),
            )
            for year in selected_years
        ]
        return TaxBmfFinalizationMatrix(
            generated_at=generated_at,
            years=rows,
            available_years=selected_years,
            ready_years=[row.year for row in rows if row.finalization_status == "bmf_ready"],
            conservative_ready_years=[
                row.year for row in rows if row.finalization_status == "conservative_ready"
            ],
            review_years=[row.year for row in rows if row.finalization_status == "review_required"],
            blocked_years=[row.year for row in rows if row.finalization_status == "blocked"],
            empty_years=[row.year for row in rows if row.finalization_status == "empty"],
            total_taxable_private_disposals_eur=sum(
                (row.taxable_private_disposals_eur for row in rows),
                Decimal("0"),
            ),
            total_rewards_mining_staking_income_eur=sum(
                (row.rewards_mining_staking_income_eur for row in rows),
                Decimal("0"),
            ),
            total_derivative_pnl_eur=sum((row.derivative_pnl_eur for row in rows), Decimal("0")),
            ascii_table=self._bmf_finalization_ascii(rows),
            methodology=(
                "Read-only BMF-Finalisierungsmatrix fuer 2021-2025. Kombiniert "
                "BMF-Filing-Readiness, Filing-Matrix, Korrekturkarte, Evidence-Status "
                "und Stablecoin-FX-Ankerstatus. Der teure Reward-Recheck wird nur mit "
                "include_reward_recheck=true live geladen; die schnelle Dashboard-"
                "Ansicht nutzt die im Readiness-Snapshot enthaltenen Reward-Summen. "
                "Die Matrix ist eine Arbeits-/Abschlussampel und schreibt keine Imports, "
                "Preise, FIFO-Lots, Tax-Lines oder Review-Entscheidungen."
            ),
        )

    def bmf_submission_guide(self, *, years: list[int] | None = None) -> TaxBmfSubmissionGuide:
        generated_at = self._now()
        selected_years = sorted(years if years is not None else [2021, 2022, 2023, 2024, 2025])
        finalization = self.bmf_finalization_matrix(years=selected_years)
        closure = self.tax_years.filing_closure_overview(years=selected_years)
        finalization_by_year = {row.year: row for row in finalization.years}
        closure_by_year = {row.year: row for row in closure.rows}
        rows = [
            self._bmf_submission_guide_year(
                year,
                finalization=finalization_by_year.get(year),
                closure=closure_by_year.get(year),
            )
            for year in selected_years
        ]
        return TaxBmfSubmissionGuide(
            generated_at=generated_at,
            years=rows,
            available_years=selected_years,
            ready_years=[row.year for row in rows if row.status == "ready"],
            conservative_ready_years=[row.year for row in rows if row.status == "conservative_ready"],
            review_years=[row.year for row in rows if row.status == "review_required"],
            blocked_years=[row.year for row in rows if row.status == "blocked"],
            empty_years=[row.year for row in rows if row.status == "empty"],
            amendment_review_years=[row.year for row in rows if row.correction_review_recommended],
            total_taxable_private_disposals_eur=sum(
                (row.taxable_private_disposals_eur for row in rows),
                Decimal("0"),
            ),
            total_rewards_mining_staking_income_eur=sum(
                (row.rewards_mining_staking_income_eur for row in rows),
                Decimal("0"),
            ),
            total_derivative_pnl_eur=sum((row.derivative_pnl_eur for row in rows), Decimal("0")),
            total_tax_free_private_disposals_eur=sum(
                (row.tax_free_private_disposals_eur for row in rows),
                Decimal("0"),
            ),
            ascii_table=self._bmf_submission_ascii(rows),
            methodology=(
                "Read-only BMF-Abgabehilfe aus Finalisierungsmatrix, Filing-Closure-"
                "Overview und Korrekturkarte. Sie zeigt pro Jahr die eintragungs-"
                "relevanten Betraege, Beleg-/Archivierungspflichten und Korrektur-"
                "hinweise, schreibt aber keine Imports, Preise, FIFO-Lots, Tax-Lines "
                "oder Review-Entscheidungen."
            ),
        )

    def _bmf_submission_guide_year(
        self,
        year: int,
        *,
        finalization: TaxBmfFinalizationYear | None,
        closure,
    ) -> TaxBmfSubmissionGuideYear:
        status = self._bmf_submission_status(finalization)
        status_label = (
            finalization.status_label
            if finalization is not None
            else "Keine Aktivitaet"
            if status == "empty"
            else "Pruefen"
        )
        taxable_private = self._decimal_attr(
            closure,
            "private_disposals_gain_loss_eur",
            getattr(finalization, "taxable_private_disposals_eur", Decimal("0")),
        )
        rewards = self._decimal_attr(
            closure,
            "rewards_mining_staking_income_eur",
            getattr(finalization, "rewards_mining_staking_income_eur", Decimal("0")),
        )
        derivatives = self._decimal_attr(
            closure,
            "derivative_pnl_eur",
            getattr(finalization, "derivative_pnl_eur", Decimal("0")),
        )
        tax_free = self._decimal_attr(
            closure,
            "tax_free_private_disposals_eur",
            getattr(finalization, "tax_free_private_disposals_eur", Decimal("0")),
        )
        enter_count = int(getattr(closure, "eintragen_count", 0) or 0)
        attach_count = int(getattr(closure, "beilegen_count", 0) or 0)
        review_count = int(getattr(closure, "pruefen_count", 0) or 0)
        archive_count = int(getattr(closure, "archivieren_count", 0) or 0)
        blocking_count = int(getattr(finalization, "blocking_count", 0) or 0)
        review_requirements_count = int(getattr(finalization, "review_count", 0) or 0)
        technical_review_requirements_count = self._bmf_submission_technical_review_count(finalization)
        correction_review = bool(
            getattr(closure, "amendment_review_recommended", False)
            or getattr(finalization, "correction_review_recommended", False)
        )
        amendment_reason = str(getattr(closure, "amendment_reason", "") or "").strip() or None
        declaration_bucket = str(getattr(closure, "declaration_bucket", "") or self._bmf_submission_bucket(
            taxable_private=taxable_private,
            rewards=rewards,
            derivatives=derivatives,
        ))
        where_to_enter = str(getattr(closure, "where_to_enter", "") or self._bmf_submission_where_to_enter(
            taxable_private=taxable_private,
            rewards=rewards,
            derivatives=derivatives,
        ))
        filing_summary_endpoint = str(
            getattr(closure, "filing_summary_endpoint", "")
            or getattr(finalization, "filing_summary_endpoint", "")
            or f"/api/v1/tax-years/{year}/filing-summary"
        )
        correction_map_endpoint = str(
            getattr(closure, "correction_map_endpoint", "")
            or getattr(finalization, "correction_map_endpoint", "")
            or f"/api/v1/tax-years/{year}/correction-map"
        )
        evidence_package_endpoint = str(
            getattr(closure, "evidence_package_endpoint", "")
            or getattr(finalization, "evidence_package_endpoint", "")
            or f"/api/v1/export/tax-years/{year}/evidence-package.zip"
        )
        next_action = str(
            getattr(closure, "next_action", "")
            or getattr(finalization, "next_action", "")
            or "Jahresdaten und Belege pruefen."
        )
        row = TaxBmfSubmissionGuideYear(
            year=year,
            status=status,  # type: ignore[arg-type]
            status_label=status_label,
            can_submit=status == "ready",
            can_submit_conservative=status in {"ready", "conservative_ready"},
            correction_review_recommended=correction_review,
            declaration_bucket=declaration_bucket,
            where_to_enter=where_to_enter,
            taxable_private_disposals_eur=taxable_private,
            rewards_mining_staking_income_eur=rewards,
            derivative_pnl_eur=derivatives,
            tax_free_private_disposals_eur=tax_free,
            enter_count=enter_count,
            attach_count=attach_count,
            review_count=review_count,
            archive_count=archive_count,
            blocking_count=blocking_count,
            review_requirements_count=review_requirements_count,
            technical_review_requirements_count=technical_review_requirements_count,
            declaration_compare_required=correction_review,
            amendment_reason=amendment_reason,
            filing_sentence=self._bmf_submission_filing_sentence(
                taxable_private=taxable_private,
                rewards=rewards,
                derivatives=derivatives,
                declaration_bucket=declaration_bucket,
                where_to_enter=where_to_enter,
            ),
            attachment_sentence=self._bmf_submission_attachment_sentence(
                attach_count=attach_count,
                correction_review=correction_review,
                evidence_package_endpoint=evidence_package_endpoint,
            ),
            archive_sentence=self._bmf_submission_archive_sentence(
                tax_free=tax_free,
                archive_count=archive_count,
            ),
            review_sentence=self._bmf_submission_review_sentence(
                status=status,
                blocking_count=blocking_count,
                review_requirements_count=review_requirements_count,
                technical_review_requirements_count=technical_review_requirements_count,
                correction_review=correction_review,
                amendment_reason=amendment_reason,
            ),
            next_action=next_action,
            filing_summary_endpoint=filing_summary_endpoint,
            filing_checklist_csv_endpoint=str(
                getattr(closure, "filing_checklist_csv_endpoint", "")
                or f"/api/v1/export/tax-years/{year}/filing-checklist.csv"
            ),
            correction_map_endpoint=correction_map_endpoint,
            correction_map_csv_endpoint=str(
                getattr(closure, "correction_map_csv_endpoint", "")
                or f"/api/v1/export/tax-years/{year}/correction-map.csv"
            ),
            evidence_package_endpoint=evidence_package_endpoint,
            display_line="",
        )
        row.display_line = self._bmf_submission_line(row)
        return row

    def _bmf_submission_status(self, finalization: TaxBmfFinalizationYear | None) -> str:
        if finalization is None:
            return "empty"
        if finalization.finalization_status == "bmf_ready":
            return "ready"
        if finalization.finalization_status == "conservative_ready":
            return "conservative_ready"
        if finalization.finalization_status == "blocked":
            return "blocked"
        if finalization.finalization_status == "empty":
            return "empty"
        return "review_required"

    def _bmf_submission_technical_review_count(self, finalization: TaxBmfFinalizationYear | None) -> int:
        if finalization is None:
            return 0
        return sum(
            1
            for requirement in getattr(finalization, "requirements", [])
            if requirement.status == "review"
            and requirement.key
            in {
                "fifo_traceability",
                "income_rewards_mining",
                "transfers_provenance",
                "prices_fx",
            }
        )

    def _decimal_attr(self, obj, attr: str, fallback: Decimal) -> Decimal:
        value = getattr(obj, attr, None) if obj is not None else None
        if value is None:
            return fallback
        return Decimal(str(value))

    def _bmf_submission_bucket(
        self,
        *,
        taxable_private: Decimal,
        rewards: Decimal,
        derivatives: Decimal,
    ) -> str:
        parts = []
        if taxable_private:
            parts.append("Anlage SO")
        if rewards:
            parts.append("Rewards/Mining")
        if derivatives:
            parts.append("Derivate pruefen")
        return " + ".join(parts) if parts else "keine Eingabe aus V2-Werten"

    def _bmf_submission_where_to_enter(
        self,
        *,
        taxable_private: Decimal,
        rewards: Decimal,
        derivatives: Decimal,
    ) -> str:
        targets = []
        if taxable_private:
            targets.append("Private Veraeusserungsgeschaefte / Anlage SO")
        if rewards:
            targets.append("Mining-/Reward-Einnahmen laut Steuerberaterzuordnung")
        if derivatives:
            targets.append("Derivate/Termingeschaefte separat pruefen")
        return "; ".join(targets) if targets else "Keine Eintragung, Belege archivieren"

    def _bmf_submission_filing_sentence(
        self,
        *,
        taxable_private: Decimal,
        rewards: Decimal,
        derivatives: Decimal,
        declaration_bucket: str,
        where_to_enter: str,
    ) -> str:
        return (
            f"Eintragen: {declaration_bucket}. Ziel: {where_to_enter}. "
            f"Anlage SO {self._eur(taxable_private)}, Rewards/Mining {self._eur(rewards)}, "
            f"Derivate {self._eur(derivatives)}."
        )

    def _bmf_submission_attachment_sentence(
        self,
        *,
        attach_count: int,
        correction_review: bool,
        evidence_package_endpoint: str,
    ) -> str:
        prefix = f"Beilegen: {attach_count} Position(en) aus Filing-/BMF-Checkliste."
        if correction_review:
            prefix += " Vorjahres-/Nachreichungspruefung ist markiert."
        return f"{prefix} Belegpaket: {evidence_package_endpoint}."

    def _bmf_submission_archive_sentence(self, *, tax_free: Decimal, archive_count: int) -> str:
        return (
            f"Archivieren: {archive_count} Position(en), insbesondere steuerfreie "
            f"private Veraeusserungen nach Haltefrist {self._eur(tax_free)}."
        )

    def _bmf_submission_review_sentence(
        self,
        *,
        status: str,
        blocking_count: int,
        review_requirements_count: int,
        technical_review_requirements_count: int,
        correction_review: bool,
        amendment_reason: str | None,
    ) -> str:
        if status == "blocked":
            return f"Nicht einreichen: {blocking_count} Blocker zuerst schliessen."
        if technical_review_requirements_count and correction_review:
            return (
                f"Konservativ einreichbar: {technical_review_requirements_count} fachliche "
                "Nachweis-Hinweis(e) beilegen und die V2-Betraege gegen die urspruengliche "
                f"Erklaerung vergleichen. Grund: {amendment_reason or 'eintragungsrelevante V2-Betraege vorhanden'}"
            )
        if technical_review_requirements_count:
            return (
                f"Konservativ einreichbar mit {technical_review_requirements_count} fachlichen "
                "Nachweis-Hinweis(en); diese im Jahrespaket beilegen."
            )
        if correction_review:
            return (
                "Keine technischen BMF-Blocker; V2-Betraege gegen die urspruengliche "
                f"Erklaerung vergleichen. Grund: {amendment_reason or 'eintragungsrelevante V2-Betraege vorhanden'}"
            )
        if status == "empty":
            return "Keine V2-Aktivitaet; nur archivieren, falls externe Belege vorhanden sind."
        return "Keine offenen BMF-Blocker in der Abschlussmatrix."

    def _bmf_submission_ascii(self, rows: list[TaxBmfSubmissionGuideYear]) -> str:
        if not rows:
            return "Jahr | Status | Eintragen | Beilegen | Pruefen | Naechster Schritt"
        header = "Jahr | Status | Eintragen | Beilegen | Pruefen | Naechster Schritt"
        separator = "-----|--------|-----------|----------|---------|-----------------"
        return "\n".join([header, separator, *(row.display_line for row in rows)])

    def _bmf_submission_line(self, row: TaxBmfSubmissionGuideYear) -> str:
        return (
            f"{row.year} | {row.status_label} | "
            f"{self._eur(row.taxable_private_disposals_eur)} / "
            f"{self._eur(row.rewards_mining_staking_income_eur)} | "
            f"{row.attach_count} | {row.review_requirements_count} | {row.next_action}"
        )

    def bmf_prior_filing_comparison(self, *, years: list[int] | None = None) -> TaxBmfPriorFilingComparison:
        generated_at = self._now()
        selected_years = sorted(years if years is not None else [2021, 2022, 2023, 2024, 2025])
        submission = self.bmf_submission_guide(years=selected_years)
        declared_by_year, setting_exists = self._prior_filing_declared_amounts()
        rows = [
            self._bmf_prior_filing_comparison_year(row, declared_by_year.get(row.year))
            for row in submission.years
        ]
        return TaxBmfPriorFilingComparison(
            generated_at=generated_at,
            setting_key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
            setting_exists=setting_exists,
            years=rows,
            available_years=selected_years,
            match_years=[row.year for row in rows if row.status == "match"],
            delta_review_years=[row.year for row in rows if row.status == "delta_review"],
            missing_declared_years=[row.year for row in rows if row.status == "missing_declared_values"],
            untrusted_declared_years=[row.year for row in rows if row.status == "declared_values_untrusted"],
            empty_years=[row.year for row in rows if row.status == "empty"],
            total_delta_taxable_private_disposals_eur=sum(
                (row.delta_taxable_private_disposals_eur or Decimal("0") for row in rows),
                Decimal("0"),
            ),
            total_delta_rewards_mining_staking_income_eur=sum(
                (row.delta_rewards_mining_staking_income_eur or Decimal("0") for row in rows),
                Decimal("0"),
            ),
            total_delta_derivative_pnl_eur=sum(
                (row.delta_derivative_pnl_eur or Decimal("0") for row in rows),
                Decimal("0"),
            ),
            total_absolute_delta_eur=sum((row.absolute_delta_eur for row in rows), Decimal("0")),
            example_setting_json=self._prior_filing_example_json(),
            ascii_table=self._bmf_prior_filing_ascii(rows),
            methodology=(
                "Read-only Vergleich zwischen V2-Abgabehilfe und optional hinterlegten "
                f"Alt-Erklaerungswerten aus Admin-Setting {self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING}. "
                "Positive Deltas bedeuten: V2 liegt ueber dem erklaerten Wert; negative Deltas "
                "bedeuten: V2 liegt darunter. Der Vergleich schreibt keine Steuerdaten und "
                "entscheidet nicht automatisch ueber Nachreichung oder Einspruch."
            ),
        )

    def bmf_prior_filing_declared_amounts(self) -> TaxBmfPriorFilingDeclaredAmounts:
        declared_by_year, _setting_exists = self._prior_filing_declared_amounts()
        rows = [
            TaxBmfPriorFilingDeclaredYear(
                year=year,
                declared_values_status=values["declared_values_status"],  # type: ignore[arg-type]
                note=str(values.get("note") or "") or None,
                taxable_private_disposals_eur=Decimal(str(values["taxable_private_disposals_eur"])),
                rewards_mining_staking_income_eur=Decimal(str(values["rewards_mining_staking_income_eur"])),
                derivative_pnl_eur=Decimal(str(values["derivative_pnl_eur"])),
                tax_free_private_disposals_eur=Decimal(str(values["tax_free_private_disposals_eur"])),
            )
            for year, values in sorted(declared_by_year.items())
        ]
        return TaxBmfPriorFilingDeclaredAmounts(
            setting_key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
            years=rows,
            example_setting_json=self._prior_filing_example_json(),
            methodology=(
                "Read-only Ansicht der hinterlegten Alt-Erklaerungswerte aus dem "
                f"Admin-Setting {self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING}. Diese "
                "Werte dienen nur dem Vergleich gegen V2 und veraendern keine "
                "Tax-Lines, FIFO-Lots, Preise oder Review-Entscheidungen."
            ),
        )

    def write_bmf_prior_filing_declared_amounts(
        self,
        payload: TaxBmfPriorFilingDeclaredAmountsWrite,
    ) -> TaxBmfPriorFilingDeclaredAmountsWriteResult:
        years = sorted(payload.years, key=lambda row: row.year)
        serialized = {
            "years": {
                str(row.year): {
                    "taxable_private_disposals_eur": str(row.taxable_private_disposals_eur),
                    "declared_values_status": row.declared_values_status,
                    "note": row.note,
                    "rewards_mining_staking_income_eur": str(row.rewards_mining_staking_income_eur),
                    "derivative_pnl_eur": str(row.derivative_pnl_eur),
                    "tax_free_private_disposals_eur": str(row.tax_free_private_disposals_eur),
                }
                for row in years
            }
        }
        self.store.upsert_admin_setting(
            AdminSettingWrite(
                key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
                value_json=json.dumps(serialized, sort_keys=True),
            )
        )
        return TaxBmfPriorFilingDeclaredAmountsWriteResult(
            setting_key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
            written_years=[row.year for row in years],
            comparison=self.bmf_prior_filing_comparison(years=[row.year for row in years] or None),
        )

    def _prior_filing_declared_amounts(self) -> tuple[dict[int, dict[str, object]], bool]:
        raw = None
        for setting in self.store.list_admin_settings():
            if setting.key == self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING:
                raw = setting.value_json
                break
        if raw is None:
            return {}, False
        try:
            payload = json.loads(raw)
        except Exception:
            return {}, True
        years_payload = payload.get("years") if isinstance(payload, dict) else payload
        if not isinstance(years_payload, dict):
            return {}, True
        parsed: dict[int, dict[str, object]] = {}
        for year_key, item in years_payload.items():
            if not isinstance(item, dict):
                continue
            try:
                year = int(year_key)
            except Exception:
                continue
            parsed[year] = {
                "taxable_private_disposals_eur": self._optional_decimal(item.get("taxable_private_disposals_eur")),
                "declared_values_status": self._prior_filing_status(item.get("declared_values_status")),
                "note": str(item.get("note") or ""),
                "rewards_mining_staking_income_eur": self._optional_decimal(
                    item.get("rewards_mining_staking_income_eur")
                ),
                "derivative_pnl_eur": self._optional_decimal(item.get("derivative_pnl_eur")),
                "tax_free_private_disposals_eur": self._optional_decimal(item.get("tax_free_private_disposals_eur")),
            }
        return parsed, True

    def _bmf_prior_filing_comparison_year(
        self,
        row: TaxBmfSubmissionGuideYear,
        declared: dict[str, object] | None,
    ) -> TaxBmfPriorFilingComparisonYear:
        if declared is None:
            status = "empty" if row.status == "empty" else "missing_declared_values"
            result = TaxBmfPriorFilingComparisonYear(
                year=row.year,
                status=status,  # type: ignore[arg-type]
                status_label="Keine Altwerte hinterlegt" if status == "missing_declared_values" else "Keine Aktivitaet",
                declared_values_configured=False,
                declared_values_status="unknown",
                v2_taxable_private_disposals_eur=row.taxable_private_disposals_eur,
                v2_rewards_mining_staking_income_eur=row.rewards_mining_staking_income_eur,
                v2_derivative_pnl_eur=row.derivative_pnl_eur,
                v2_tax_free_private_disposals_eur=row.tax_free_private_disposals_eur,
                amendment_review_recommended=status == "missing_declared_values",
                next_action=(
                    f"Altwerte im Admin-Setting {self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING} hinterlegen."
                    if status == "missing_declared_values"
                    else "Keine Aktion."
                ),
                setting_key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
                filing_summary_endpoint=row.filing_summary_endpoint,
                correction_map_endpoint=row.correction_map_endpoint,
                evidence_package_endpoint=row.evidence_package_endpoint,
                display_line="",
            )
            result.display_line = self._bmf_prior_filing_line(result)
            return result

        declared_status = str(declared.get("declared_values_status") or "declared_values")
        declared_note = str(declared.get("note") or "") or None
        if declared_status != "declared_values":
            status_label = {
                "unknown": "Altwerte unbekannt",
                "probably_wrong": "Altwerte vermutlich falsch",
                "not_filed": "Nicht erklaert",
            }.get(declared_status, "Altwerte nicht belastbar")
            result = TaxBmfPriorFilingComparisonYear(
                year=row.year,
                status="declared_values_untrusted",
                status_label=status_label,
                declared_values_configured=True,
                declared_values_status=declared_status,  # type: ignore[arg-type]
                declared_values_note=declared_note,
                v2_taxable_private_disposals_eur=row.taxable_private_disposals_eur,
                v2_rewards_mining_staking_income_eur=row.rewards_mining_staking_income_eur,
                v2_derivative_pnl_eur=row.derivative_pnl_eur,
                v2_tax_free_private_disposals_eur=row.tax_free_private_disposals_eur,
                amendment_review_recommended=row.status != "empty",
                next_action=(
                    "Keine rechnerische Delta-Aussage: urspruengliche Erklaerung ist als nicht belastbar markiert. "
                    "Originalbescheid/Steuererklaerung beschaffen oder Jahr konservativ als Korrekturpruefung behandeln."
                ),
                setting_key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
                filing_summary_endpoint=row.filing_summary_endpoint,
                correction_map_endpoint=row.correction_map_endpoint,
                evidence_package_endpoint=row.evidence_package_endpoint,
                display_line="",
            )
            result.display_line = self._bmf_prior_filing_line(result)
            return result

        declared_taxable = Decimal(str(declared["taxable_private_disposals_eur"]))
        declared_rewards = Decimal(str(declared["rewards_mining_staking_income_eur"]))
        declared_derivatives = Decimal(str(declared["derivative_pnl_eur"]))
        declared_tax_free = Decimal(str(declared["tax_free_private_disposals_eur"]))
        delta_taxable = row.taxable_private_disposals_eur - declared_taxable
        delta_rewards = row.rewards_mining_staking_income_eur - declared_rewards
        delta_derivatives = row.derivative_pnl_eur - declared_derivatives
        delta_tax_free = row.tax_free_private_disposals_eur - declared_tax_free
        absolute_delta = sum(
            (abs(value) for value in [delta_taxable, delta_rewards, delta_derivatives, delta_tax_free]),
            Decimal("0"),
        )
        has_delta = absolute_delta > self.PRIOR_FILING_DELTA_TOLERANCE_EUR
        result = TaxBmfPriorFilingComparisonYear(
            year=row.year,
            status="delta_review" if has_delta else "match",
            status_label="Abweichung pruefen" if has_delta else "Altwerte passen",
            declared_values_configured=True,
            declared_values_status="declared_values",
            declared_values_note=declared_note,
            v2_taxable_private_disposals_eur=row.taxable_private_disposals_eur,
            declared_taxable_private_disposals_eur=declared_taxable,
            delta_taxable_private_disposals_eur=delta_taxable,
            v2_rewards_mining_staking_income_eur=row.rewards_mining_staking_income_eur,
            declared_rewards_mining_staking_income_eur=declared_rewards,
            delta_rewards_mining_staking_income_eur=delta_rewards,
            v2_derivative_pnl_eur=row.derivative_pnl_eur,
            declared_derivative_pnl_eur=declared_derivatives,
            delta_derivative_pnl_eur=delta_derivatives,
            v2_tax_free_private_disposals_eur=row.tax_free_private_disposals_eur,
            declared_tax_free_private_disposals_eur=declared_tax_free,
            delta_tax_free_private_disposals_eur=delta_tax_free,
            absolute_delta_eur=absolute_delta,
            amendment_review_recommended=has_delta,
            next_action=(
                "Differenz mit der urspruenglichen Steuererklaerung und Belegen pruefen."
                if has_delta
                else "Altwerte archivieren; keine rechnerische Abweichung oberhalb 0,01 EUR."
            ),
            setting_key=self.PRIOR_FILING_DECLARED_AMOUNTS_SETTING,
            filing_summary_endpoint=row.filing_summary_endpoint,
            correction_map_endpoint=row.correction_map_endpoint,
            evidence_package_endpoint=row.evidence_package_endpoint,
            display_line="",
        )
        result.display_line = self._bmf_prior_filing_line(result)
        return result

    def _optional_decimal(self, value) -> Decimal:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(str(value))

    def _prior_filing_status(self, value) -> str:
        status = str(value or "declared_values")
        if status in {"declared_values", "unknown", "probably_wrong", "not_filed"}:
            return status
        return "declared_values"

    def _prior_filing_example_json(self) -> str:
        return json.dumps(
            {
                "years": {
                    "2021": {
                        "declared_values_status": "probably_wrong",
                        "note": "Ich vermute, dass die damalige Eintragung nicht korrekt war.",
                        "taxable_private_disposals_eur": "0.00",
                        "rewards_mining_staking_income_eur": "11000.00",
                        "derivative_pnl_eur": "0.00",
                        "tax_free_private_disposals_eur": "0.00",
                    }
                }
            },
            indent=2,
        )

    def _bmf_prior_filing_ascii(self, rows: list[TaxBmfPriorFilingComparisonYear]) -> str:
        if not rows:
            return "Jahr | Status | Delta SO | Delta Rewards | Delta Derivate | Aktion"
        header = "Jahr | Status | Delta SO | Delta Rewards | Delta Derivate | Aktion"
        separator = "-----|--------|----------|---------------|----------------|-------"
        return "\n".join([header, separator, *(row.display_line for row in rows)])

    def _bmf_prior_filing_line(self, row: TaxBmfPriorFilingComparisonYear) -> str:
        return (
            f"{row.year} | {row.status_label} | "
            f"{self._eur(row.delta_taxable_private_disposals_eur or Decimal('0'))} | "
            f"{self._eur(row.delta_rewards_mining_staking_income_eur or Decimal('0'))} | "
            f"{self._eur(row.delta_derivative_pnl_eur or Decimal('0'))} | "
            f"{row.next_action}"
        )

    def bmf_amendment_worklist(self, *, years: list[int] | None = None) -> TaxBmfAmendmentWorklist:
        generated_at = self._now()
        selected_years = sorted(years if years is not None else [2021, 2022, 2023, 2024, 2025])
        submission = self.bmf_submission_guide(years=selected_years)
        comparison = self.bmf_prior_filing_comparison(years=selected_years)
        submission_by_year = {row.year: row for row in submission.years}
        comparison_by_year = {row.year: row for row in comparison.years}
        rows = [
            self._bmf_amendment_worklist_year(
                year,
                submission=submission_by_year.get(year),
                comparison=comparison_by_year.get(year),
            )
            for year in selected_years
        ]
        rows.sort(key=lambda row: (row.priority, row.year))
        return TaxBmfAmendmentWorklist(
            generated_at=generated_at,
            years=rows,
            available_years=selected_years,
            correction_review_years=[row.year for row in rows if row.status == "prepare_correction_review"],
            compare_declared_years=[row.year for row in rows if row.status == "compare_declared_values"],
            archive_only_years=[row.year for row in rows if row.status == "archive_only"],
            blocked_years=[row.year for row in rows if row.status == "blocked"],
            total_v2_taxable_private_disposals_eur=sum(
                (row.v2_taxable_private_disposals_eur for row in rows),
                Decimal("0"),
            ),
            total_v2_rewards_mining_staking_income_eur=sum(
                (row.v2_rewards_mining_staking_income_eur for row in rows),
                Decimal("0"),
            ),
            total_v2_derivative_pnl_eur=sum((row.v2_derivative_pnl_eur for row in rows), Decimal("0")),
            ascii_table=self._bmf_amendment_worklist_ascii(rows),
            methodology=(
                "Read-only Korrekturpruefungs-Worklist fuer 2021-2025. Kombiniert "
                "BMF-Abgabehilfe und Alt-Erklaerungsvergleich. Jahre mit unbekannten "
                "oder vermutlich falschen Altwerten werden als Korrekturpruefung "
                "gefuehrt, ohne scheinexakte Delta-Betraege zu erzeugen. Die Worklist "
                "schreibt keine Steuerdaten, Preise, FIFO-Lots oder Review-Entscheidungen."
            ),
        )

    def _bmf_amendment_worklist_year(
        self,
        year: int,
        *,
        submission: TaxBmfSubmissionGuideYear | None,
        comparison: TaxBmfPriorFilingComparisonYear | None,
    ) -> TaxBmfAmendmentWorklistYear:
        prior_status = str(getattr(comparison, "declared_values_status", "unknown"))
        technical_review = int(getattr(submission, "technical_review_requirements_count", 0) or 0)
        amendment_review = bool(
            getattr(submission, "correction_review_recommended", False)
            or getattr(comparison, "amendment_review_recommended", False)
        )
        if getattr(submission, "blocking_count", 0):
            status = "blocked"
            label = "Blocker zuerst klaeren"
            priority = 0
        elif prior_status in {"unknown", "probably_wrong", "not_filed"}:
            status = "prepare_correction_review"
            label = "Korrekturpruefung vorbereiten"
            priority = 1
        elif comparison is not None and comparison.status == "delta_review":
            status = "compare_declared_values"
            label = "Delta gegen Altwerte pruefen"
            priority = 2
        elif amendment_review or technical_review:
            status = "prepare_correction_review"
            label = "Belege/Korrektur pruefen"
            priority = 3
        else:
            status = "archive_only"
            label = "Archivieren"
            priority = 9
        correction_reason = self._bmf_amendment_reason(submission, comparison, prior_status)
        result = TaxBmfAmendmentWorklistYear(
            year=year,
            priority=priority,
            status=status,  # type: ignore[arg-type]
            status_label=label,
            prior_filing_status=prior_status,
            v2_taxable_private_disposals_eur=getattr(
                submission,
                "taxable_private_disposals_eur",
                getattr(comparison, "v2_taxable_private_disposals_eur", Decimal("0")),
            ),
            v2_rewards_mining_staking_income_eur=getattr(
                submission,
                "rewards_mining_staking_income_eur",
                getattr(comparison, "v2_rewards_mining_staking_income_eur", Decimal("0")),
            ),
            v2_derivative_pnl_eur=getattr(
                submission,
                "derivative_pnl_eur",
                getattr(comparison, "v2_derivative_pnl_eur", Decimal("0")),
            ),
            v2_tax_free_private_disposals_eur=getattr(
                submission,
                "tax_free_private_disposals_eur",
                getattr(comparison, "v2_tax_free_private_disposals_eur", Decimal("0")),
            ),
            technical_review_requirements_count=technical_review,
            amendment_review_recommended=amendment_review,
            correction_reason=correction_reason,
            next_action=self._bmf_amendment_next_action(status, prior_status),
            filing_summary_endpoint=getattr(
                submission,
                "filing_summary_endpoint",
                f"/api/v1/tax-years/{year}/filing-summary",
            ),
            correction_map_endpoint=getattr(
                submission,
                "correction_map_endpoint",
                f"/api/v1/tax-years/{year}/correction-map",
            ),
            correction_map_csv_endpoint=getattr(
                submission,
                "correction_map_csv_endpoint",
                f"/api/v1/export/tax-years/{year}/correction-map.csv",
            ),
            evidence_package_endpoint=getattr(
                submission,
                "evidence_package_endpoint",
                f"/api/v1/export/tax-years/{year}/evidence-package.zip",
            ),
            display_line="",
        )
        result.display_line = self._bmf_amendment_worklist_line(result)
        return result

    def _bmf_amendment_reason(
        self,
        submission: TaxBmfSubmissionGuideYear | None,
        comparison: TaxBmfPriorFilingComparisonYear | None,
        prior_status: str,
    ) -> str:
        if prior_status == "probably_wrong":
            return "Alt-Erklaerung wurde als vermutlich falsch/nicht belastbar markiert."
        if prior_status == "unknown":
            return "Alt-Erklaerungswerte sind unbekannt oder noch nicht aus Bescheid/Erklaerung uebertragen."
        if prior_status == "not_filed":
            return "Jahr ist als nicht erklaert markiert; V2-Werte gegen Abgabepflicht/Nachreichung pruefen."
        if comparison is not None and comparison.status == "delta_review":
            return "Belegte Altwerte weichen rechnerisch von V2 ab."
        if submission is not None and submission.amendment_reason:
            return submission.amendment_reason
        return "Keine priorisierte Korrekturpruefung aus V2-Sicht."

    def _bmf_amendment_next_action(self, status: str, prior_status: str) -> str:
        if status == "blocked":
            return "BMF-/FIFO-Blocker zuerst schliessen, dann Korrekturpruefung wiederholen."
        if prior_status in {"probably_wrong", "unknown"}:
            return "Original-Steuererklaerung und Bescheid beschaffen; V2-Filing-Summary und Belegpaket je Jahr gegenueberstellen."
        if prior_status == "not_filed":
            return "Pruefen, ob Nachreichung/Erstangabe fuer das Jahr erforderlich ist; Belegpaket vorbereiten."
        if status == "compare_declared_values":
            return "Delta-Zeilen fachlich mit Bescheid/Erklaerung vergleichen und Korrekturkarte verwenden."
        if status == "archive_only":
            return "Jahrespaket archivieren."
        return "Korrekturkarte, Filing Summary und Belegpaket fuer Steuerberater/Finanzamt vorbereiten."

    def _bmf_amendment_worklist_ascii(self, rows: list[TaxBmfAmendmentWorklistYear]) -> str:
        if not rows:
            return "Jahr | Status | Anlage SO | Rewards | Derivate | Grund | Aktion"
        header = "Jahr | Status | Anlage SO | Rewards | Derivate | Grund | Aktion"
        separator = "-----|--------|-----------|---------|----------|-------|-------"
        return "\n".join([header, separator, *(row.display_line for row in rows)])

    def _bmf_amendment_worklist_line(self, row: TaxBmfAmendmentWorklistYear) -> str:
        return (
            f"{row.year} | {row.status_label} | "
            f"{self._eur(row.v2_taxable_private_disposals_eur)} | "
            f"{self._eur(row.v2_rewards_mining_staking_income_eur)} | "
            f"{self._eur(row.v2_derivative_pnl_eur)} | "
            f"{row.correction_reason} | {row.next_action}"
        )

    def write_bmf_filing_readiness_snapshot(
        self,
        *,
        output_dir: Path | None = None,
    ) -> Path:
        out = output_dir or self.DEFAULT_BMF_FILING_READINESS_DIR
        out.mkdir(parents=True, exist_ok=True)
        report = self.bmf_filing_readiness()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact = out / f"{timestamp}_bmf_filing_readiness_2021_2025.json"
        latest = out / "latest_bmf_filing_readiness_2021_2025.json"
        content = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")
        artifact.write_bytes(content)
        latest.write_bytes(content)
        return latest

    def _bmf_finalization_year(
        self,
        year: int,
        *,
        readiness: TaxBmfFilingReadinessYear | None,
        filing,
        correction,
        reward,
        stablecoin_groups: list[object],
    ) -> TaxBmfFinalizationYear:
        if readiness is None:
            readiness = self._bmf_filing_readiness_year(year, payment_row=None)
        requirements = self._bmf_finalization_requirements(
            year,
            readiness=readiness,
            filing=filing,
            correction=correction,
            reward=reward,
            stablecoin_groups=stablecoin_groups,
        )
        blocking_count = sum(1 for item in requirements if item.status == "blocked")
        review_count = sum(1 for item in requirements if item.status == "review")
        finalization_status = self._bmf_finalization_status(readiness, blocking_count, review_count)
        status_label = self._bmf_finalization_label(finalization_status)
        evidence_refs = [
            ref
            for ref in [
                readiness.methodology_endpoint,
                readiness.filing_summary_endpoint,
                readiness.bmf_closure_appendix_endpoint,
                readiness.evidence_package_endpoint,
                f"/api/v1/tax-years/{year}/evidence",
                f"/api/v1/tax-years/{year}/correction-map",
            ]
            if ref
        ]
        tax_free = (
            filing.tax_free_private_disposals_eur
            if filing is not None
            else Decimal("0")
        )
        correction_review = bool(
            correction.amendment_review_recommended
            if correction is not None
            else finalization_status in {"review_required", "blocked"}
        )
        return TaxBmfFinalizationYear(
            year=year,
            finalization_status=finalization_status,
            status_label=status_label,
            can_submit=finalization_status == "bmf_ready",
            can_submit_conservative=finalization_status in {"bmf_ready", "conservative_ready"},
            correction_review_recommended=correction_review,
            taxable_private_disposals_eur=readiness.taxable_private_disposals_eur,
            rewards_mining_staking_income_eur=readiness.rewards_mining_staking_income_eur,
            derivative_pnl_eur=readiness.derivative_pnl_eur,
            tax_free_private_disposals_eur=tax_free,
            blocking_count=blocking_count,
            review_count=review_count,
            evidence_refs=evidence_refs,
            requirements=requirements,
            next_action=self._bmf_finalization_next_action(finalization_status, readiness, requirements),
            filing_summary_endpoint=readiness.filing_summary_endpoint,
            correction_map_endpoint=f"/api/v1/tax-years/{year}/correction-map",
            evidence_package_endpoint=readiness.evidence_package_endpoint,
            display_line=self._bmf_finalization_line(
                year=year,
                label=status_label,
                taxable_private_disposals_eur=readiness.taxable_private_disposals_eur,
                rewards_mining_staking_income_eur=readiness.rewards_mining_staking_income_eur,
                derivative_pnl_eur=readiness.derivative_pnl_eur,
                blocking_count=blocking_count,
                review_count=review_count,
            ),
        )

    def _bmf_finalization_requirements(
        self,
        year: int,
        *,
        readiness: TaxBmfFilingReadinessYear,
        filing,
        correction,
        reward,
        stablecoin_groups: list[object],
    ) -> list[TaxBmfFinalizationRequirement]:
        requirement_rows: list[TaxBmfFinalizationRequirement] = []
        blocking_codes = set(readiness.blocking_gap_codes)
        review_codes = set(readiness.review_gap_codes)
        status = "blocked" if blocking_codes else "review" if review_codes else "ok"
        if readiness.filing_status == "empty":
            status = "empty"
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="fifo_traceability",
                label="FIFO / Haltefrist / Tax-Lines",
                status=status,  # type: ignore[arg-type]
                detail=(
                    "BMF-Methodik meldet keine offenen FIFO-Blocker."
                    if status == "ok"
                    else f"Offene Codes: {', '.join(sorted(blocking_codes | review_codes))}"
                ),
                evidence_ref=readiness.methodology_endpoint,
            )
        )

        reward_status = "ok"
        reward_detail = "Keine offenen Reward-/Mining-Abweichungen."
        if reward is not None and getattr(reward, "consistency_status", "ok") == "review":
            reward_status = "review"
            flags = getattr(reward, "flags", [])
            reward_detail = "Reward-Recheck pruefen: " + (", ".join(flags) if flags else "Review-Signal vorhanden")
        elif readiness.rewards_mining_staking_income_eur == 0:
            reward_status = "empty"
            reward_detail = "Keine Reward-/Mining-/Staking-Einnahmen in diesem Jahr."
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="income_rewards_mining",
                label="Rewards / Mining / Staking",
                status=reward_status,  # type: ignore[arg-type]
                detail=reward_detail,
                evidence_ref=f"/api/v1/tax-years/{year}/income-guide",
            )
        )

        private_status = "ok" if readiness.taxable_private_disposals_eur or readiness.filing_status != "empty" else "empty"
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="private_disposals",
                label="Private Veraeusserungen",
                status=private_status,  # type: ignore[arg-type]
                detail=(
                    f"Steuerpflichtiger privater G/V: {self._eur(readiness.taxable_private_disposals_eur)}."
                    if private_status != "empty"
                    else "Keine steuerpflichtigen privaten Veraeusserungen aus V2-Werten."
                ),
                evidence_ref=readiness.filing_summary_endpoint,
            )
        )

        transfer_status = "blocked" if any(code.startswith("wallet_fifo") for code in blocking_codes) else (
            "review" if readiness.appendix_items_count or any(code.startswith("wallet_fifo") for code in review_codes) else "ok"
        )
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="transfers_provenance",
                label="Transfers / Depotwechsel / Herkunft",
                status=transfer_status,  # type: ignore[arg-type]
                detail=(
                    f"Appendix-Positionen: {readiness.appendix_items_count}, manuell: {readiness.appendix_manual_evidence_required_count}."
                    if transfer_status != "ok"
                    else "Keine offene Transfer-/Herkunftsbeilage fuer dieses Jahr."
                ),
                evidence_ref=readiness.bmf_closure_appendix_endpoint,
            )
        )

        stablecoin_review = [
            group for group in stablecoin_groups if getattr(group, "status", "") in {"ready_for_review", "incomplete"}
        ]
        price_blocked = "missing_price_groups" in blocking_codes or any(
            getattr(group, "status", "") == "incomplete" for group in stablecoin_groups
        )
        price_review = bool(stablecoin_review) or any(
            code in review_codes
            for code in {"asset_fifo_possible_recalculation"}
        )
        price_status = "blocked" if price_blocked else "review" if price_review else "ok"
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="prices_fx",
                label="Preise / FX / Stablecoins",
                status=price_status,  # type: ignore[arg-type]
                detail=(
                    f"Stablecoin-FX-Gruppen offen: {len(stablecoin_review)}."
                    if stablecoin_review
                    else "Keine offenen Preis-/FX-Blocker in der Finalisierungsmatrix."
                ),
                evidence_ref="/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest",
            )
        )

        filing_status = "ok" if filing is not None and filing.action_status in {"ready", "conservative_ready"} else (
            "review" if filing is not None else "blocked"
        )
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="declaration_help",
                label="Steuererklaerungshilfe",
                status=filing_status,  # type: ignore[arg-type]
                detail=(
                    filing.next_action
                    if filing is not None
                    else "Filing-Matrix fuer dieses Jahr konnte nicht erzeugt werden."
                ),
                evidence_ref=readiness.filing_summary_endpoint,
            )
        )

        evidence_status = "blocked" if readiness.filing_status == "blocked" else (
            "review" if correction is not None and correction.amendment_review_recommended else "ok"
        )
        requirement_rows.append(
            TaxBmfFinalizationRequirement(
                key="evidence_package",
                label="Belegpaket / Korrekturkarte",
                status=evidence_status,  # type: ignore[arg-type]
                detail=(
                    correction.amendment_reason
                    if correction is not None
                    else "Jahresbelegpaket und Korrekturkarte verlinkt."
                ),
                evidence_ref=readiness.evidence_package_endpoint,
            )
        )
        return requirement_rows

    @staticmethod
    def _bmf_finalization_status(
        readiness: TaxBmfFilingReadinessYear,
        blocking_count: int,
        review_count: int,
    ) -> str:
        if readiness.filing_status == "empty":
            return "empty"
        if blocking_count:
            return "blocked"
        if readiness.filing_status == "bmf_ready" and review_count == 0:
            return "bmf_ready"
        if readiness.filing_status in {"bmf_ready", "conservative_appendix"}:
            return "conservative_ready"
        return "review_required"

    @staticmethod
    def _bmf_finalization_label(status: str) -> str:
        labels = {
            "bmf_ready": "BMF-ready",
            "conservative_ready": "Konservativ einreichbar",
            "review_required": "Review noetig",
            "blocked": "Blockiert",
            "empty": "Keine V2-Aktivitaet",
        }
        return labels.get(status, status)

    @staticmethod
    def _bmf_finalization_next_action(
        status: str,
        readiness: TaxBmfFilingReadinessYear,
        requirements: list[TaxBmfFinalizationRequirement],
    ) -> str:
        if status == "bmf_ready":
            return "Filing Summary, Checkliste und Jahresbelegpaket fuer die Erklaerung verwenden."
        if status == "conservative_ready":
            return "Konservative Beilage/Korrekturkarte beilegen und offene Review-Hinweise nicht als steuerneutrale Transfers behaupten."
        if status == "empty":
            return "Keine V2-Eingabewerte; optional Jahresbeleg archivieren."
        first_blocker = next((item for item in requirements if item.status == "blocked"), None)
        if first_blocker is not None:
            return f"Blocker schliessen: {first_blocker.label}."
        return readiness.next_action

    def _bmf_finalization_ascii(self, rows: list[TaxBmfFinalizationYear]) -> str:
        if not rows:
            return "Jahr | Status | Privat G/V | Rewards | Derivate | Blocker | Review"
        header = "Jahr | Status | Privat G/V | Rewards | Derivate | Blocker | Review"
        separator = "-----|--------|------------|---------|----------|---------|-------"
        return "\n".join([header, separator, *(row.display_line for row in rows)])

    def _bmf_finalization_line(
        self,
        *,
        year: int,
        label: str,
        taxable_private_disposals_eur: Decimal,
        rewards_mining_staking_income_eur: Decimal,
        derivative_pnl_eur: Decimal,
        blocking_count: int,
        review_count: int,
    ) -> str:
        return (
            f"{year} | {label} | "
            f"{self._eur(taxable_private_disposals_eur)} | "
            f"{self._eur(rewards_mining_staking_income_eur)} | "
            f"{self._eur(derivative_pnl_eur)} | "
            f"{blocking_count} | {review_count}"
        )

    def reward_bmf_recheck(self) -> TaxRewardBmfRecheckReport:
        generated_at = self._now()
        tax_summary = self.tax_years.summary()
        available_years = tax_summary.available_years
        rows = [self._reward_bmf_recheck_year(year) for year in available_years]
        return TaxRewardBmfRecheckReport(
            generated_at=generated_at,
            years=rows,
            available_years=available_years,
            total_reward_income_eur=sum((row.reward_income_eur for row in rows), Decimal("0")),
            total_reward_events_count=sum(row.reward_events_count for row in rows),
            years_with_rewards_count=sum(1 for row in rows if row.reward_events_count),
            review_years_count=sum(1 for row in rows if row.consistency_status == "review"),
            methodology=(
                "Read-only Recheck ueber alle Steuerjahre. Verglichen werden "
                "Tax-Year-Reward-Summen, Income-Guide-Klassifizierungen und "
                "Jahres-/Review-Indikatoren aus dem schnellen Tax-Year-Summary. "
                "Automatisch steuerlich eingetragen werden nur kanonische "
                "HNT/IOT/MOBILE Mining-/Reward-Events; Exchange-Earn, Wrapper, "
                "unbekannte Solana-Zufluesse und fehlende Bewertungen bleiben "
                "Review-Kontext. Fuer vollstaendige Wallet-FIFO-BMF-Readiness "
                "bleibt der Drilldown /api/v1/tax-years/{year}/methodology "
                "massgeblich."
            ),
        )

    def _bmf_filing_readiness_year(self, year: int, *, payment_row) -> TaxBmfFilingReadinessYear:
        report = self.report(year, include_gain_evidence=False)
        blocking_codes = [gap.code for gap in report.gaps if gap.blocks_bmf_ready or gap.severity == "blocker"]
        review_codes = [
            gap.code
            for gap in report.gaps
            if gap.code not in blocking_codes and gap.severity in {"warning", "info"}
        ]
        needs_appendix = any(
            code.startswith("wallet_fifo") or code.startswith("external_inflow")
            for code in [*blocking_codes, *review_codes]
        )
        appendix = self.tax_years.bmf_closure_appendix(year) if needs_appendix else None
        can_file_with_conservative_appendix = bool(
            appendix is not None and appendix.can_file_with_conservative_appendix
        )
        can_file_with_documented_review_only = bool(review_codes) and not blocking_codes and all(
            code in self.CONSERVATIVE_REVIEW_ONLY_CODES for code in review_codes
        )
        if report.status == "empty":
            filing_status = "empty"
            label = "Keine Aktivitaet"
            next_action = "Kein Eintrag aus V2-Werten; Jahresbeleg optional archivieren."
        elif report.bmf_ready:
            filing_status = "bmf_ready"
            label = "BMF-ready"
            next_action = "Filing Summary und Belegpaket fuer die Steuererklaerung verwenden."
        elif can_file_with_conservative_appendix or can_file_with_documented_review_only:
            filing_status = "conservative_appendix"
            label = "Konservativ belegbar"
            if can_file_with_conservative_appendix:
                next_action = (
                    "BMF-Closure-Appendix beilegen und keine offene Herkunft als "
                    "steuerneutralen Eigenwallet-Transfer behaupten."
                )
            else:
                next_action = (
                    "Nicht-blockierende Review-Hinweise im Jahrespaket beilegen; "
                    "keine zusaetzlichen Steuerbetraege aus der Warnung ableiten."
                )
        elif blocking_codes:
            filing_status = "blocked"
            label = "Blockiert"
            next_action = "Blockierende Gaps zuerst mit Belegen, Review-Entscheidung oder Importkorrektur schliessen."
        else:
            filing_status = "review_required"
            label = "Review noetig"
            next_action = "Warnungen fachlich pruefen und Belegpaket mit Review-Hinweisen verwenden."
        return TaxBmfFilingReadinessYear(
            year=year,
            filing_status=filing_status,
            status_label=label,
            methodology_status=report.status,
            bmf_ready=report.bmf_ready,
            can_file_with_conservative_appendix=can_file_with_conservative_appendix,
            appendix_status=appendix.status if appendix is not None else None,
            appendix_items_count=appendix.items_count if appendix is not None else 0,
            appendix_manual_evidence_required_count=(
                appendix.manual_evidence_required_count if appendix is not None else 0
            ),
            taxable_private_disposals_eur=(
                payment_row.private_disposals_gain_loss_eur if payment_row is not None else Decimal("0")
            ),
            rewards_mining_staking_income_eur=(
                payment_row.rewards_mining_staking_income_eur if payment_row is not None else Decimal("0")
            ),
            derivative_pnl_eur=payment_row.derivative_pnl_eur if payment_row is not None else Decimal("0"),
            blocking_gap_codes=blocking_codes,
            review_gap_codes=review_codes,
            next_action=next_action,
            methodology_endpoint=f"/api/v1/tax-years/{year}/methodology",
            filing_summary_endpoint=f"/api/v1/tax-years/{year}/filing-summary",
            bmf_closure_appendix_endpoint=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
            evidence_package_endpoint=f"/api/v1/export/tax-years/{year}/evidence-package.zip",
            display_line=self._bmf_filing_readiness_line(
                year=year,
                label=label,
                taxable_private_disposals_eur=(
                    payment_row.private_disposals_gain_loss_eur if payment_row is not None else Decimal("0")
                ),
                rewards_mining_staking_income_eur=(
                    payment_row.rewards_mining_staking_income_eur if payment_row is not None else Decimal("0")
                ),
                derivative_pnl_eur=payment_row.derivative_pnl_eur if payment_row is not None else Decimal("0"),
                blocking_count=len(blocking_codes),
                appendix_items_count=appendix.items_count if appendix is not None else 0,
            ),
        )

    def _bmf_filing_readiness_ascii(self, rows: list[TaxBmfFilingReadinessYear]) -> str:
        if not rows:
            return "Jahr | Status | Privat G/V | Rewards | Derivate | Blocker | Appendix"
        header = "Jahr | Status | Privat G/V | Rewards | Derivate | Blocker | Appendix"
        separator = "-----|--------|------------|---------|----------|---------|---------"
        return "\n".join([header, separator, *(row.display_line for row in rows)])

    def _bmf_filing_readiness_line(
        self,
        *,
        year: int,
        label: str,
        taxable_private_disposals_eur: Decimal,
        rewards_mining_staking_income_eur: Decimal,
        derivative_pnl_eur: Decimal,
        blocking_count: int,
        appendix_items_count: int,
    ) -> str:
        return (
            f"{year} | {label} | "
            f"{self._eur(taxable_private_disposals_eur)} | "
            f"{self._eur(rewards_mining_staking_income_eur)} | "
            f"{self._eur(derivative_pnl_eur)} | "
            f"{blocking_count} | {appendix_items_count}"
        )

    def _eur(self, value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01'))} EUR"

    def _bmf_filing_readiness_snapshot_path(self) -> Path:
        candidates = [
            self.store.path.parent / "var/bmf_filing_readiness/latest_bmf_filing_readiness_2021_2025.json",
            self.store.path.parent.parent / "var/bmf_filing_readiness/latest_bmf_filing_readiness_2021_2025.json",
            Path.cwd() / "var/bmf_filing_readiness/latest_bmf_filing_readiness_2021_2025.json",
            self.DEFAULT_BMF_FILING_READINESS_DIR / "latest_bmf_filing_readiness_2021_2025.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]

    def _can_use_default_bmf_snapshot(self) -> bool:
        default_db = Path("/workspace/steuerreport-v2-plan/data/steuerreport_v2.duckdb")
        try:
            return self.store.path.resolve() == default_db.resolve()
        except FileNotFoundError:
            return False

    def bmf_closure_backlog(self, year: int | None = None) -> TaxBmfClosureBacklogReport:
        generated_at = self._now()
        available_years = [year] if year is not None else [
            item_year for item_year in self._available_years() if 2021 <= item_year <= 2025
        ]
        rows = [self._bmf_closure_backlog_year(item_year) for item_year in available_years]
        blockers = sum(row.blocker_items_count for row in rows)
        reviews = sum(row.review_items_count for row in rows)
        total_exposure = sum((row.total_exposure_eur for row in rows), Decimal("0"))
        next_year = next((row.year for row in rows if row.blocker_items_count), None)
        return TaxBmfClosureBacklogReport(
            generated_at=generated_at,
            available_years=available_years,
            years=rows,
            blocker_items_count=blockers,
            review_items_count=reviews,
            total_exposure_eur=total_exposure,
            next_year_to_close=next_year,
            methodology=(
                "Read-only BMF-Closure-Backlog aus Methodology-Gaps und "
                "BMF-Closure-Appendix. Priorisiert technische Blocker, offene "
                "Wallet-/Depot-Herkunft, Asset-FIFO-Reviews und reine "
                "Dokumentationswarnungen. Es werden keine Steuerdaten, Lots, "
                "Imports, Preise oder Review-Entscheidungen geschrieben."
            ),
        )

    def bmf_closure_backlog_snapshot(
        self,
        *,
        artifact_path: Path | None = None,
    ) -> TaxBmfClosureBacklogSnapshot:
        path = artifact_path or self._bmf_closure_backlog_snapshot_path()
        if not path.exists():
            return TaxBmfClosureBacklogSnapshot(
                generated_at=self._now(),
                snapshot_exists=False,
                artifact_path=str(path),
                report=None,
                status="missing",
                note=(
                    "Noch kein BMF-Closure-Backlog-Snapshot vorhanden. "
                    "Erzeuge ihn mit scripts/run_bmf_closure_backlog_snapshot_20260622.py."
                ),
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            report = TaxBmfClosureBacklogReport.model_validate(payload)
        except Exception as exc:
            return TaxBmfClosureBacklogSnapshot(
                generated_at=self._now(),
                snapshot_exists=True,
                artifact_path=str(path),
                report=None,
                status="invalid",
                note=f"Snapshot konnte nicht validiert werden: {exc}",
            )
        return TaxBmfClosureBacklogSnapshot(
            generated_at=self._now(),
            snapshot_exists=True,
            artifact_path=str(path),
            report=report,
            status="available",
            note="Read-only Snapshot aus var/bmf_closure_backlog; API berechnet dabei keine Methodology neu.",
        )

    def write_bmf_closure_backlog_snapshot(
        self,
        *,
        output_dir: Path | None = None,
    ) -> Path:
        out = output_dir or self.DEFAULT_BMF_CLOSURE_BACKLOG_DIR
        out.mkdir(parents=True, exist_ok=True)
        report = self.bmf_closure_backlog()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact = out / f"{timestamp}_bmf_closure_backlog_2021_2025.json"
        latest = out / "latest_bmf_closure_backlog_2021_2025.json"
        content = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")
        artifact.write_bytes(content)
        latest.write_bytes(content)
        return latest

    def _bmf_closure_backlog_year(self, year: int) -> TaxBmfClosureBacklogYear:
        report = self.report(year, include_gain_evidence=False)
        appendix = self.tax_years.bmf_closure_appendix(year)
        items: list[TaxBmfClosureBacklogItem] = []
        for appendix_item in appendix.items:
            if appendix_item.closure_status in {
                "documented_non_live_opening_balance",
                "documented_fiat_purchase",
                "documented_legacy_hnt_cex_deposit",
                "documented_legacy_hnt_cex_deposit_mirror",
                "documented_fairspot_staking_return",
                "documented_legacy_counterparty_mirror",
                "documented_legacy_hnt_payment_provenance",
                "documented_binance_btt_bttc_redenomination",
                "documented_manual_cex_deposit_history",
                "documented_exchange_deposit_history",
                "external_or_unknown_origin_documented",
                "unverified_cex_deposit_sender",
            }:
                continue
            items.append(
                TaxBmfClosureBacklogItem(
                    year=year,
                    priority=self._backlog_priority(
                        appendix_item.closure_status,
                        appendix_item.carried_cost_basis_eur_total,
                    ),
                    category=self._backlog_category_from_appendix(appendix_item.closure_status),
                    blocker_type=appendix_item.closure_status,
                    severity="blocker" if appendix_item.manual_evidence_required else "warning",
                    asset=appendix_item.asset,
                    source=appendix_item.source,
                    pool_id=appendix_item.pool_id,
                    events_count=appendix_item.events_count,
                    quantity_total=appendix_item.quantity_total,
                    exposure_eur=appendix_item.carried_cost_basis_eur_total,
                    closure_status=appendix_item.closure_status,
                    required_evidence=self._required_evidence_for_appendix(appendix_item.closure_status),
                    next_action=appendix_item.recommended_action,
                    evidence_refs=appendix_item.evidence_refs,
                )
            )

        appendix_blockers = {
            item.blocker_type
            for item in items
            if item.category in {"wallet_fifo_provenance", "solana_batch"}
        }
        for gap in report.gaps:
            if gap.code == "wallet_fifo_unresolved_inbound_provenance" and appendix_blockers:
                continue
            if gap.code in {"wallet_fifo_evidence_overlay_ok", "asset_fifo_quote_attribution_documented"}:
                continue
            items.append(
                TaxBmfClosureBacklogItem(
                    year=year,
                    priority=self._backlog_priority(gap.code, Decimal("0")),
                    category=self._backlog_category_from_gap(gap.code),
                    blocker_type=gap.code,
                    severity=gap.severity,
                    events_count=gap.count,
                    required_evidence=self._required_evidence_for_gap(gap.code),
                    next_action=gap.action,
                    evidence_refs=[gap.evidence_ref] if gap.evidence_ref else [],
                )
            )

        items.sort(key=lambda item: (item.priority, item.year, item.asset or "", item.source or "", item.blocker_type))
        blocker_count = sum(1 for item in items if item.severity == "blocker")
        review_count = sum(1 for item in items if item.severity != "blocker")
        exposure = sum((item.exposure_eur for item in items), Decimal("0"))
        return TaxBmfClosureBacklogYear(
            year=year,
            status=report.status,
            bmf_ready=report.bmf_ready,
            blocker_items_count=blocker_count,
            review_items_count=review_count,
            total_exposure_eur=exposure,
            top_actions=[item.next_action for item in items[:3]],
            items=items,
        )

    def _backlog_priority(self, code: str, exposure_eur: Decimal) -> int:
        if code == "solana_batch_incomplete":
            return 10
        if code == "asset_fifo_possible_recalculation":
            return 20
        if code in {"unverified_cex_deposit_sender", "tax_neutral_candidate_review_required"}:
            return 30
        if code in {"review_required", "external_or_unknown_origin_documented"}:
            return 40 if abs(exposure_eur) >= Decimal("1000") else 50
        if code == "wallet_fifo_unresolved_inbound_provenance":
            return 45
        if code == "wallet_fifo_delta_present":
            return 70
        if code == "wallet_fifo_exchange_sequencing_documented":
            return 80
        return 90

    def _backlog_category_from_appendix(self, closure_status: str) -> str:
        if closure_status == "solana_batch_incomplete":
            return "solana_batch"
        return "wallet_fifo_provenance"

    def _backlog_category_from_gap(self, code: str) -> str:
        if code == "asset_fifo_possible_recalculation":
            return "asset_fifo_review"
        if code == "wallet_fifo_delta_present":
            return "wallet_fifo_delta"
        if code == "wallet_fifo_exchange_sequencing_documented":
            return "exchange_sequencing"
        if code.startswith("wallet_fifo"):
            return "wallet_fifo_provenance"
        return "documentation"

    def _required_evidence_for_appendix(self, closure_status: str) -> str:
        evidence_by_status = {
            "solana_batch_incomplete": "Solana-Provenance-Batch erneut erzeugen oder Raw-TX-Belege nachziehen.",
            "unverified_cex_deposit_sender": "CEX-Deposit-Beleg plus Sender-Ownership-Nachweis.",
            "tax_neutral_candidate_review_required": "Review-Decision mit TXID, Sender, Empfaenger, Menge und FIFO-Fortfuehrung.",
            "external_or_unknown_origin_documented": "Service-/Programm-/Exchange-Kontext oder konservative Offenlegung.",
            "review_required": "Withdrawal-/Deposit-/Onchain-Beleg mit Adresse, TXID, Zeitstempel und Menge.",
        }
        return evidence_by_status.get(closure_status, "Fachlichen Beleg und Review-Entscheidung nachreichen.")

    def _required_evidence_for_gap(self, code: str) -> str:
        evidence_by_code = {
            "asset_fifo_possible_recalculation": "Asset-FIFO-Correction-Review und Entscheidung, ob Tax-Lines nachgerechnet werden muessen.",
            "wallet_fifo_delta_present": "Wallet-FIFO-Delta im Jahresbeleg dokumentieren.",
            "wallet_fifo_exchange_sequencing_documented": "Exchange-Sequencing-Ausnahme mit Gap-Diagnose dokumentieren.",
            "wallet_fifo_unresolved_inbound_provenance": "Herkunft mit Withdrawal-/Deposit-/Onchain-Beleg verknuepfen.",
        }
        return evidence_by_code.get(code, "Methodology-Gap fachlich dokumentieren.")

    def _bmf_closure_backlog_snapshot_path(self) -> Path:
        candidates = [
            self.store.path.parent / "var/bmf_closure_backlog/latest_bmf_closure_backlog_2021_2025.json",
            self.store.path.parent.parent / "var/bmf_closure_backlog/latest_bmf_closure_backlog_2021_2025.json",
            Path.cwd() / "var/bmf_closure_backlog/latest_bmf_closure_backlog_2021_2025.json",
            self.DEFAULT_BMF_CLOSURE_BACKLOG_DIR / "latest_bmf_closure_backlog_2021_2025.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]

    def status(self, year: int) -> TaxYearComplianceStatus:
        return self._status_from_report(self.report(year))

    def report(self, year: int, *, include_gain_evidence: bool = True) -> TaxMethodologyReport:
        generated_at = self._now()
        policy = self.policy()
        detail = self.tax_years.detail(year)
        external = self.tax_years.external_inflow_report(year, limit=1)
        counts = self._year_counts(year)
        wallet_fifo_service = WalletFifoPreviewService(self.store)
        wallet_fifo = wallet_fifo_service.preview(year=year)
        wallet_fifo_exchange_sequencing_count = self._documented_exchange_sequencing_gap_count(
            wallet_fifo_service,
            year=year,
            unmatched_count=wallet_fifo.unmatched_count,
        )
        wallet_fifo_documented_non_live_count = self._documented_non_live_count(
            wallet_fifo_service,
            year=year,
            unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
        )
        wallet_fifo_documented_fiat_purchase_count = self._documented_fiat_purchase_count(
            wallet_fifo_service,
            year=year,
            unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
        )
        wallet_fifo_documented_legacy_cex_deposit_count = self._documented_legacy_cex_deposit_count(
            wallet_fifo_service,
            year=year,
            unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
        )
        wallet_fifo_documented_legacy_cex_deposit_mirror_count = (
            self._documented_legacy_cex_deposit_mirror_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_fairspot_staking_return_count = (
            self._documented_fairspot_staking_return_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_legacy_counterparty_mirror_count = (
            self._documented_legacy_counterparty_mirror_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_exchange_deposit_history_count = (
            self._documented_exchange_deposit_history_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_legacy_hnt_external_payment_count = (
            self._documented_legacy_hnt_external_payment_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_token_redenomination_count = (
            self._documented_token_redenomination_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_manual_cex_deposit_count = (
            self._documented_manual_cex_deposit_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_external_or_unknown_count = (
            self._documented_external_or_unknown_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        wallet_fifo_documented_unverified_cex_count = (
            self._documented_unverified_cex_count(
                wallet_fifo_service,
                year=year,
                unresolved_count=wallet_fifo.unresolved_inbound_provenance_count,
            )
        )
        asset_fifo_review = self.tax_years.asset_fifo_correction_review(
            year,
            limit=200,
            min_abs_gain_eur=self.ASSET_FIFO_CORRECTION_MIN_ABS_EUR,
        )
        gain_evidence = (
            self.tax_years.gain_evidence_review(year, limit=500)
            if include_gain_evidence and detail.tax_lines_count
            else None
        )
        gaps = self._gaps(
            year=year,
            tax_lines_count=detail.tax_lines_count,
            income_events_count=counts["income_events_count"],
            derivative_lines_count=counts["derivative_lines_count"],
            unmatched_disposals=detail.unmatched_disposals,
            missing_price_groups=detail.missing_price_groups,
            review_issues_count=detail.review_issues_count,
            external_review_count=external.review_count,
            external_unmatched_count=external.unmatched_count,
            traceability=counts,
            wallet_fifo_unmatched_count=wallet_fifo.unmatched_count,
            wallet_fifo_exchange_sequencing_count=wallet_fifo_exchange_sequencing_count,
            wallet_fifo_delta_eur=wallet_fifo.delta_gain_loss_eur,
            wallet_fifo_unresolved_provenance_count=wallet_fifo.unresolved_inbound_provenance_count,
            wallet_fifo_documented_non_live_count=wallet_fifo_documented_non_live_count,
            wallet_fifo_documented_fiat_purchase_count=wallet_fifo_documented_fiat_purchase_count,
            wallet_fifo_documented_legacy_cex_deposit_count=wallet_fifo_documented_legacy_cex_deposit_count,
            wallet_fifo_documented_legacy_cex_deposit_mirror_count=(
                wallet_fifo_documented_legacy_cex_deposit_mirror_count
            ),
            wallet_fifo_documented_fairspot_staking_return_count=(
                wallet_fifo_documented_fairspot_staking_return_count
            ),
            wallet_fifo_documented_legacy_counterparty_mirror_count=(
                wallet_fifo_documented_legacy_counterparty_mirror_count
            ),
            wallet_fifo_documented_exchange_deposit_history_count=(
                wallet_fifo_documented_exchange_deposit_history_count
            ),
            wallet_fifo_documented_legacy_hnt_external_payment_count=(
                wallet_fifo_documented_legacy_hnt_external_payment_count
            ),
            wallet_fifo_documented_token_redenomination_count=(
                wallet_fifo_documented_token_redenomination_count
            ),
            wallet_fifo_documented_manual_cex_deposit_count=wallet_fifo_documented_manual_cex_deposit_count,
            wallet_fifo_documented_external_or_unknown_count=wallet_fifo_documented_external_or_unknown_count,
            wallet_fifo_documented_unverified_cex_count=wallet_fifo_documented_unverified_cex_count,
            asset_fifo_possible_recalculation_count=asset_fifo_review.possible_recalculation_assets_count,
            asset_fifo_attribution_review_count=asset_fifo_review.attribution_review_assets_count,
            gain_evidence_price_delta_lines_count=(
                gain_evidence.price_delta_lines_count if gain_evidence is not None else 0
            ),
            gain_evidence_material_price_delta_eur=(
                gain_evidence.material_price_delta_eur if gain_evidence is not None else Decimal("0")
            ),
            gain_evidence_open_price_delta_eur=(
                gain_evidence.open_price_delta_eur if gain_evidence is not None else Decimal("0")
            ),
            gain_evidence_event_level_reconciled_lines_count=(
                gain_evidence.event_level_reconciled_lines_count if gain_evidence is not None else 0
            ),
            gain_evidence_acquisition_event_level_reconciled_lines_count=(
                gain_evidence.acquisition_event_level_reconciled_lines_count
                if gain_evidence is not None
                else 0
            ),
        )
        status = self._status(gaps, counts["activity_count"])
        traceability_score = self._traceability_score(gaps, counts)
        return TaxMethodologyReport(
            year=year,
            generated_at=generated_at,
            status=status,
            label=self._label(status),
            bmf_ready=status == "ok",
            policy=policy,
            metrics=self._metrics(
                status=status,
                detail_tax_lines_count=detail.tax_lines_count,
                counts=counts,
                external_review_count=external.review_count,
                external_unmatched_count=external.unmatched_count,
                wallet_fifo_unmatched_count=wallet_fifo.unmatched_count,
                wallet_fifo_exchange_sequencing_count=wallet_fifo_exchange_sequencing_count,
                asset_fifo_possible_recalculation_count=asset_fifo_review.possible_recalculation_assets_count,
                asset_fifo_attribution_review_count=asset_fifo_review.attribution_review_assets_count,
                gain_evidence_price_delta_lines_count=(
                    gain_evidence.price_delta_lines_count if gain_evidence is not None else 0
                ),
                gain_evidence_open_price_delta_eur=(
                    gain_evidence.open_price_delta_eur if gain_evidence is not None else Decimal("0")
                ),
                traceability_score=traceability_score,
            ),
            gaps=gaps,
            tax_lines_count=detail.tax_lines_count,
            income_events_count=counts["income_events_count"],
            derivative_lines_count=counts["derivative_lines_count"],
            sources=counts["sources"],
            accounts_count=counts["accounts_count"],
            assets_count=counts["assets_count"],
            traceability_score=traceability_score,
            methodology=(
                "BMF-Readiness-Report fuer ein Steuerjahr. Der Report bewertet "
                "Nachvollziehbarkeit und Methodenrisiken, veraendert aber keine "
                "Steuerdaten. Aktuelle produktive Steuerwerte bleiben global je "
                "Asset berechnet; Wallet-/Depot-FIFO, Transfer-Provenance und "
                "Asset-FIFO-Korrekturreview werden als read-only Evidence-Overlay "
                "gegengerechnet. BMF-ready wird nur gesetzt, wenn dieses Overlay "
                "keine blockierenden offenen Lots, Preis-/Review-/Zuflussluecken "
                "oder Korrekturkandidaten zeigt."
            ),
        )

    def _documented_exchange_sequencing_gap_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unmatched_count: int,
    ) -> int:
        if unmatched_count <= 0:
            return 0
        diagnosis = wallet_fifo_service.gap_diagnosis(year=year, limit=max(1, min(unmatched_count, 500)))
        events = self.store.list_canonical_events()
        documented = 0
        for gap in diagnosis.diagnoses:
            if self._is_documented_exchange_sequencing_gap(wallet_fifo_service, gap, events):
                documented += 1
        return documented

    def _documented_fiat_purchase_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return sum(
            item.events_count
            for item in closure.items
            if item.closure_status == "documented_fiat_purchase"
        )

    def _documented_non_live_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return sum(
            item.events_count
            for item in closure.items
            if item.closure_status == "documented_non_live_opening_balance"
        )

    def _documented_legacy_cex_deposit_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_legacy_cex_deposit_count

    def _documented_legacy_cex_deposit_mirror_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_legacy_cex_deposit_mirror_count

    def _documented_fairspot_staking_return_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_fairspot_staking_return_count

    def _documented_legacy_counterparty_mirror_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_legacy_counterparty_mirror_count

    def _documented_exchange_deposit_history_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_exchange_deposit_history_count

    def _documented_legacy_hnt_external_payment_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_legacy_hnt_external_payment_count

    def _documented_token_redenomination_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_token_redenomination_count

    def _documented_manual_cex_deposit_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return closure.documented_manual_cex_deposit_count

    def _documented_external_or_unknown_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return sum(
            item.events_count
            for item in closure.items
            if item.closure_status == "external_or_unknown_origin_documented"
        )

    def _documented_unverified_cex_count(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        *,
        year: int,
        unresolved_count: int,
    ) -> int:
        if unresolved_count <= 0:
            return 0
        closure = wallet_fifo_service.provenance_closure_report(year=year, limit=500)
        return sum(
            item.events_count
            for item in closure.items
            if item.closure_status == "unverified_cex_deposit_sender"
        )

    def _is_documented_exchange_sequencing_gap(
        self,
        wallet_fifo_service: WalletFifoPreviewService,
        gap: object,
        events: list[object],
    ) -> bool:
        pool_id = str(getattr(gap, "pool_id", "") or "")
        pool_source = pool_id.split(":", 1)[0].lower()
        if pool_source not in self.EXCHANGE_SEQUENCING_POOLS:
            return False
        missing_quantity = getattr(gap, "missing_quantity", Decimal("0"))
        if missing_quantity <= 0 or missing_quantity > self.EXCHANGE_SEQUENCING_GAP_MAX_QUANTITY:
            return False
        gap_time = getattr(gap, "event_time")
        window_end = gap_time + self.EXCHANGE_SEQUENCING_GAP_WINDOW
        asset = str(getattr(gap, "asset", "") or "").upper()
        covered_quantity = Decimal("0")
        for event in events:
            if str(getattr(event, "event_type", "") or "") != "trade":
                continue
            if str(getattr(event, "asset", "") or "").upper() != asset:
                continue
            if getattr(event, "quantity", Decimal("0")) <= 0:
                continue
            if wallet_fifo_service._pool_id(event) != pool_id:
                continue
            event_time = getattr(event, "event_time")
            if gap_time < event_time <= window_end:
                covered_quantity += getattr(event, "quantity", Decimal("0"))
                if covered_quantity >= missing_quantity:
                    return True
        return False

    def _available_years(self) -> list[int]:
        years = set(self.tax_years.summary().available_years)
        with self.store.connect() as con:
            rows = con.execute(
                """
                select distinct date_part('year', event_time)::integer as year
                from canonical_events
                union
                select distinct date_part('year', disposed_at)::integer as year
                from tax_lines
                union
                select distinct date_part('year', acquired_at)::integer as year
                from tax_lots
                union
                select distinct date_part('year', event_time)::integer as year
                from derivative_lines
                order by year
                """
            ).fetchall()
        years.update(int(row[0]) for row in rows if row[0] is not None)
        return sorted(years)

    def _year_counts(self, year: int) -> dict:
        with self.store.connect() as con:
            row = con.execute(
                """
                with year_events as (
                    select *
                    from canonical_events
                    where date_part('year', event_time)::integer = ?
                ),
                tax_year_lines as (
                    select l.*, lot.source_event_id as lot_source_event_id
                    from tax_lines l
                    left join tax_lots lot on lot.lot_id = l.lot_id
                    where date_part('year', l.disposed_at)::integer = ?
                )
                select
                    (select count(*)::integer from year_events) as canonical_events_count,
                    (select count(*)::integer from year_events where event_type in ('income', 'reward', 'staking', 'mining')) as income_events_count,
                    (select count(*)::integer from derivative_lines where date_part('year', event_time)::integer = ?) as derivative_lines_count,
                    (select count(*)::integer from tax_year_lines) as tax_lines_count,
                    (
                        select count(distinct l.tax_line_id)::integer
                        from tax_year_lines l
                        left join canonical_events disposal on disposal.event_id = l.source_event_id
                        left join canonical_events acquisition on acquisition.event_id = l.lot_source_event_id
                        where disposal.event_id is not null and acquisition.event_id is not null
                    ) as tax_lines_with_event_trace,
                    (select count(distinct source)::integer from year_events) as sources_count,
                    (select count(distinct coalesce(account, wallet, source))::integer from year_events) as accounts_count,
                    (select count(distinct upper(asset))::integer from year_events) as assets_count
                """,
                [year, year, year],
            ).fetchone()
            source_rows = con.execute(
                """
                select distinct source
                from canonical_events
                where date_part('year', event_time)::integer = ?
                order by source
                """,
                [year],
            ).fetchall()
        canonical_events_count = int(row[0] or 0)
        income_events_count = int(row[1] or 0)
        derivative_lines_count = int(row[2] or 0)
        tax_lines_count = int(row[3] or 0)
        return {
            "canonical_events_count": canonical_events_count,
            "income_events_count": income_events_count,
            "derivative_lines_count": derivative_lines_count,
            "tax_lines_count": tax_lines_count,
            "tax_lines_with_event_trace": int(row[4] or 0),
            "sources_count": int(row[5] or 0),
            "accounts_count": int(row[6] or 0),
            "assets_count": int(row[7] or 0),
            "sources": [str(source_row[0]) for source_row in source_rows],
            "activity_count": canonical_events_count + derivative_lines_count + tax_lines_count,
        }

    def _reward_bmf_recheck_year(self, year: int) -> TaxRewardBmfRecheckYear:
        detail = self.tax_years.detail(year)
        income = self.tax_years.income_report(year)
        classification_counts = income.classification_counts
        flags: list[str] = []
        if abs(detail.rewards_income_eur - income.reward_income_eur) > Decimal("0.000000000001"):
            flags.append("reward_sum_mismatch_between_tax_year_and_income_guide")
        if detail.rewards_events_count != classification_counts.get("reward_income_candidate", 0):
            flags.append("reward_event_count_mismatch_between_tax_year_and_income_guide")
        if classification_counts.get("exchange_earn_or_wrapper_review", 0):
            flags.append("exchange_earn_or_wrapper_review_present")
        if classification_counts.get("solana_external_inflow_or_airdrop_review", 0):
            flags.append("solana_external_or_airdrop_review_present")
        if income.missing_value_count:
            flags.append("income_values_missing")
        status = self._reward_recheck_status(detail_state=detail.state, flags=flags)
        if detail.export_blocked or detail.review_issues_count:
            flags.append("tax_year_review_or_export_block_present")
            status = "blocked"
        bmf_ready = status == "ok" and not flags
        consistency_status = "review" if flags else "ok"
        return TaxRewardBmfRecheckYear(
            year=year,
            status=status,
            bmf_ready=bmf_ready,
            reward_income_eur=detail.rewards_income_eur,
            reward_events_count=detail.rewards_events_count,
            income_guide_reward_eur=income.reward_income_eur,
            income_guide_events_count=income.events_count,
            reward_income_candidate_count=classification_counts.get("reward_income_candidate", 0),
            exchange_or_wrapper_review_count=classification_counts.get("exchange_earn_or_wrapper_review", 0),
            solana_external_or_airdrop_review_count=classification_counts.get(
                "solana_external_inflow_or_airdrop_review", 0
            ),
            missing_income_value_count=income.missing_value_count,
            evidence_required=bool(detail.rewards_events_count),
            consistency_status=consistency_status,
            flags=flags,
            income_guide_endpoint=f"/api/v1/tax-years/{year}/income-guide",
            methodology_endpoint=f"/api/v1/tax-years/{year}/methodology",
            evidence_package_endpoint=f"/api/v1/export/tax-years/{year}/evidence-package.zip",
        )

    def _reward_recheck_status(self, *, detail_state: str, flags: list[str]) -> TaxMethodologyStatus:
        if detail_state == "empty":
            return "empty"
        if detail_state == "blocked":
            return "blocked"
        if flags:
            return "review"
        return "ok"

    def _gaps(
        self,
        *,
        year: int,
        tax_lines_count: int,
        income_events_count: int,
        derivative_lines_count: int,
        unmatched_disposals: int,
        missing_price_groups: int,
        review_issues_count: int,
        external_review_count: int,
        external_unmatched_count: int,
        traceability: dict,
        wallet_fifo_unmatched_count: int,
        wallet_fifo_exchange_sequencing_count: int,
        wallet_fifo_delta_eur: Decimal,
        wallet_fifo_unresolved_provenance_count: int,
        wallet_fifo_documented_non_live_count: int,
        wallet_fifo_documented_fiat_purchase_count: int,
        wallet_fifo_documented_legacy_cex_deposit_count: int,
        wallet_fifo_documented_legacy_cex_deposit_mirror_count: int,
        wallet_fifo_documented_fairspot_staking_return_count: int,
        wallet_fifo_documented_legacy_counterparty_mirror_count: int,
        wallet_fifo_documented_exchange_deposit_history_count: int,
        wallet_fifo_documented_legacy_hnt_external_payment_count: int,
        wallet_fifo_documented_token_redenomination_count: int,
        wallet_fifo_documented_manual_cex_deposit_count: int,
        wallet_fifo_documented_external_or_unknown_count: int,
        wallet_fifo_documented_unverified_cex_count: int,
        asset_fifo_possible_recalculation_count: int,
        asset_fifo_attribution_review_count: int,
        gain_evidence_price_delta_lines_count: int = 0,
        gain_evidence_material_price_delta_eur: Decimal = Decimal("0"),
        gain_evidence_open_price_delta_eur: Decimal = Decimal("0"),
        gain_evidence_event_level_reconciled_lines_count: int = 0,
        gain_evidence_acquisition_event_level_reconciled_lines_count: int = 0,
    ) -> list[TaxMethodologyGap]:
        gaps: list[TaxMethodologyGap] = []
        if traceability["activity_count"] == 0:
            gaps.append(
                TaxMethodologyGap(
                    code="no_tax_year_activity",
                    severity="info",
                    message="Fuer dieses Jahr wurden keine steuerlichen V2-Aktivitaeten gefunden.",
                    action="Quellenabdeckung pruefen; bei echter Inaktivitaet nur archivieren.",
                    evidence_ref=f"/api/v1/tax-years/{year}/evidence",
                )
            )
            return gaps
        blocking_wallet_fifo_unmatched_count = max(0, wallet_fifo_unmatched_count - wallet_fifo_exchange_sequencing_count)
        if blocking_wallet_fifo_unmatched_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_preview_unmatched",
                    severity="blocker",
                    message=(
                        f"Wallet-/Depot-FIFO-Preview hat {blocking_wallet_fifo_unmatched_count} "
                        "Abgang/Abgaenge ohne Lot im jeweiligen Pool."
                    ),
                    count=blocking_wallet_fifo_unmatched_count,
                    action="Eigene Transfers, Quellimporte oder Anfangsbestaende je Wallet/Boerse klaeren.",
                    evidence_ref=f"/api/v1/tax-years/{year}/wallet-fifo-delta",
                    blocks_bmf_ready=True,
                )
            )
        elif wallet_fifo_exchange_sequencing_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_exchange_sequencing_documented",
                    severity="warning",
                    message=(
                        f"{wallet_fifo_exchange_sequencing_count} kleine CEX-/Grid-Sequencing-Luecke(n) "
                        "sind durch dasselbe Asset im selben Exchange-Pool innerhalb weniger Minuten gedeckt."
                    ),
                    count=wallet_fifo_exchange_sequencing_count,
                    action=(
                        "Als Exchange-Sequencing-Ausnahme im Jahresbeleg dokumentieren; "
                        "keine kuenstlichen Lots und keine Rueckdatierung erzeugen."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/wallet-fifo-gaps?limit=500",
                    blocks_bmf_ready=False,
                )
            )
        else:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_evidence_overlay_ok",
                    severity="info",
                    message=(
                        "Wallet-/Depot-FIFO ist als read-only Evidence-Overlay "
                        "verfuegbar und zeigt keine unmatched Abgaenge im Jahr."
                    ),
                    action=(
                        "Overlay im Belegpaket dokumentieren; produktive "
                        "Steuersummen bleiben unveraendert, solange keine "
                        "Korrekturkandidaten vorliegen."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/wallet-fifo-delta",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_delta_eur:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_delta_present",
                    severity="warning",
                    message=f"Wallet-FIFO weicht um {wallet_fifo_delta_eur} EUR von globaler FIFO ab.",
                    action="Delta je Jahr/Asset/Pool pruefen und fuer Steuerberater/Finanzamt dokumentieren.",
                    evidence_ref=f"/api/v1/tax-years/{year}/wallet-fifo-delta",
                    blocks_bmf_ready=False,
                )
            )
        unresolved_after_documented_fiat = max(
            0,
            wallet_fifo_unresolved_provenance_count
            - wallet_fifo_documented_non_live_count
            - wallet_fifo_documented_fiat_purchase_count
            - wallet_fifo_documented_legacy_cex_deposit_count
            - wallet_fifo_documented_legacy_cex_deposit_mirror_count
            - wallet_fifo_documented_fairspot_staking_return_count
            - wallet_fifo_documented_legacy_counterparty_mirror_count
            - wallet_fifo_documented_exchange_deposit_history_count
            - wallet_fifo_documented_legacy_hnt_external_payment_count
            - wallet_fifo_documented_token_redenomination_count
            - wallet_fifo_documented_manual_cex_deposit_count
            - wallet_fifo_documented_external_or_unknown_count
            - wallet_fifo_documented_unverified_cex_count,
        )
        if wallet_fifo_documented_non_live_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_non_live_opening_balance_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_non_live_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind als belegte Non-Live-Anfangsbestaende dokumentiert."
                    ),
                    count=wallet_fifo_documented_non_live_count,
                    action=(
                        "Als Anfangsbestand im Jahresbeleg ausweisen; nicht als Live-Zufluss "
                        "oder Eigenwallet-Transfer eskalieren."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_fiat_purchase_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_fiat_purchase_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_fiat_purchase_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind durch Fiat-Kaufhistorie belegt."
                    ),
                    count=wallet_fifo_documented_fiat_purchase_count,
                    action=(
                        "Als EUR-/Fiat-Anschaffung im Jahresbeleg dokumentieren; "
                        "nicht als Transfer-Herkunft eskalieren."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_legacy_cex_deposit_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_legacy_cex_deposit_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_legacy_cex_deposit_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind durch Heliumtracker plus CEX-Deposit-History belegt."
                    ),
                    count=wallet_fifo_documented_legacy_cex_deposit_count,
                    action=(
                        "Als Legacy-HNT-Transfer zur Boerse im Jahresbeleg dokumentieren; "
                        "nicht als Verkauf oder neue Anschaffung werten."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_legacy_cex_deposit_mirror_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_legacy_cex_deposit_mirror_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_legacy_cex_deposit_mirror_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind als Binance-Deposit-History-Spiegel "
                        "zu Legacy-HNT-Transfers belegt."
                    ),
                    count=wallet_fifo_documented_legacy_cex_deposit_mirror_count,
                    action=(
                        "Als Spiegelbeleg zum Legacy-HNT-CEX-Deposit dokumentieren; "
                        "nicht als zweite Anschaffung oder Verkauf werten."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_fairspot_staking_return_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_fairspot_staking_return_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_fairspot_staking_return_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind als Fairspot/Staking-Ruecktransfer belegt."
                    ),
                    count=wallet_fifo_documented_fairspot_staking_return_count,
                    action=(
                        "Als steuerneutralen Staking-/Service-Ruecktransfer mit "
                        "FIFO-Fortfuehrung dokumentieren; Fairspot nicht als "
                        "aktuelle Portfolio-Wallet bewerten."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_legacy_counterparty_mirror_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_legacy_counterparty_mirror_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_legacy_counterparty_mirror_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind als Legacy-Gegenpartei-Spiegel "
                        "zu Main-Legacy-Outflows belegt."
                    ),
                    count=wallet_fifo_documented_legacy_counterparty_mirror_count,
                    action=(
                        "Als Gegenpartei-/Service-Spiegel des Main-Legacy-Outflows "
                        "dokumentieren; nicht als aktuelle eigene Wallet oder neue "
                        "Anschaffung fortfuehren."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_exchange_deposit_history_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_exchange_deposit_history_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_exchange_deposit_history_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind durch Exchange-Deposit-History mit TXID, "
                        "Netzwerk, Zeitstempel und Menge belegt."
                    ),
                    count=wallet_fifo_documented_exchange_deposit_history_count,
                    action=(
                        "Als dokumentierten Exchange-Deposit/externen Zufluss im Jahresbeleg "
                        "ausweisen; nicht als steuerneutralen Eigenwallet-Transfer behandeln, "
                        "solange Sender-Ownership fehlt."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_legacy_hnt_external_payment_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_legacy_hnt_external_payment_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_legacy_hnt_external_payment_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind als externe Legacy-HNT-Payment-Evidence mit "
                        "Payer, Payee, TX-Hash, Zeitstempel, Menge und Oracle-Wert belegt."
                    ),
                    count=wallet_fifo_documented_legacy_hnt_external_payment_count,
                    action=(
                        "Konservativ als externe Legacy-HNT-Zahlung im Jahresbeleg offenlegen; "
                        "nicht als steuerneutralen Eigenwallet-Transfer behandeln."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_token_redenomination_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_token_redenomination_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_token_redenomination_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind als Token-Redenomination/Rebranding mit "
                        "passender Gegenzeile belegt."
                    ),
                    count=wallet_fifo_documented_token_redenomination_count,
                    action=(
                        "Als Redenomination im Jahresbeleg dokumentieren; nicht als "
                        "Reward, externe Herkunft oder Eigenwallet-Transfer behandeln."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_manual_cex_deposit_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_manual_cex_deposit_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_manual_cex_deposit_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind durch manuelle Deposit-Lots plus "
                        "CEX-Deposit-History belegt."
                    ),
                    count=wallet_fifo_documented_manual_cex_deposit_count,
                    action=(
                        "Als dokumentierten CEX-Deposit/externen Zufluss im Jahresbeleg "
                        "offenlegen; Sender-Ownership nur bei Zusatzbeleg behaupten."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_external_or_unknown_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_external_or_unknown_origin_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_external_or_unknown_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse sind durch Onchain/RPC-Batch konservativ "
                        "als extern/unklar dokumentiert."
                    ),
                    count=wallet_fifo_documented_external_or_unknown_count,
                    action=(
                        "Konservativ im Jahresbeleg offenlegen; nicht als steuerneutralen "
                        "Eigenwallet-Transfer behandeln."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if wallet_fifo_documented_unverified_cex_count:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_unverified_cex_deposit_documented",
                    severity="info",
                    message=(
                        f"{wallet_fifo_documented_unverified_cex_count} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse haben CEX-Deposit-Belege, aber keinen "
                        "Sender-Ownership-Nachweis."
                    ),
                    count=wallet_fifo_documented_unverified_cex_count,
                    action=(
                        "Konservativ als CEX-Deposit mit fehlender Sender-Ownership offenlegen; "
                        "nicht als steuerneutralen Eigenwallet-Transfer behandeln."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    blocks_bmf_ready=False,
                )
            )
        if unresolved_after_documented_fiat:
            gaps.append(
                TaxMethodologyGap(
                    code="wallet_fifo_unresolved_inbound_provenance",
                    severity="blocker",
                    message=(
                        f"{unresolved_after_documented_fiat} Wallet-/Depot-FIFO-"
                        "Zufluss/Zufluesse wurden nur provisorisch fortgeschrieben; "
                        "die Herkunft ist noch nicht als eigener Transfer, Bridge "
                        "oder Anfangsbestand belegt."
                    ),
                    count=unresolved_after_documented_fiat,
                    action=(
                        "Herkunft mit Withdrawal-/Deposit-/Onchain-Beleg verknuepfen "
                        "oder als belegten Anfangsbestand fachlich entscheiden."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/wallet-fifo-origin-trace",
                    blocks_bmf_ready=True,
                )
            )
        if asset_fifo_possible_recalculation_count:
            gaps.append(
                TaxMethodologyGap(
                    code="asset_fifo_possible_recalculation",
                    severity="blocker",
                    message=(
                        f"{asset_fifo_possible_recalculation_count} Asset(s) koennten "
                        "nach Rohbelegpruefung eine FIFO-/Normalizer-Neubewertung brauchen."
                    ),
                    count=asset_fifo_possible_recalculation_count,
                    action=(
                        "Asset-FIFO-Korrekturreview oeffnen, Rohbelege pruefen und "
                        "erst danach Steuerjahr freigeben."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/asset-fifo-correction-review",
                    blocks_bmf_ready=True,
                )
            )
        if asset_fifo_attribution_review_count:
            gaps.append(
                TaxMethodologyGap(
                    code="asset_fifo_quote_attribution_documented",
                    severity="info",
                    message=(
                        f"{asset_fifo_attribution_review_count} Asset(s) haben "
                        "Quote-/Attribution-Hinweise, die bereits in vorhandenen "
                        "Tax-Lines enthalten sind."
                    ),
                    count=asset_fifo_attribution_review_count,
                    action=(
                        "Als Darstellungs-/Belegkontext dokumentieren; nicht "
                        "zusaetzlich in die Jahressumme addieren."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/asset-fifo-correction-review",
                    blocks_bmf_ready=False,
                )
            )
        if gain_evidence_price_delta_lines_count and abs(gain_evidence_open_price_delta_eur) <= Decimal("0.01"):
            reconciled_lines = max(
                gain_evidence_event_level_reconciled_lines_count,
                gain_evidence_acquisition_event_level_reconciled_lines_count,
            )
            gaps.append(
                TaxMethodologyGap(
                    code="gain_evidence_event_level_reconciled",
                    severity="info",
                    message=(
                        f"{gain_evidence_price_delta_lines_count} Gain-Evidence-Preisdelta-Zeile(n) "
                        f"sind mit {reconciled_lines} Event-Level-Abgleich(en) plausibilisiert; "
                        f"Brutto-Delta {gain_evidence_material_price_delta_eur} EUR, "
                        f"offenes Delta {gain_evidence_open_price_delta_eur} EUR."
                    ),
                    count=gain_evidence_price_delta_lines_count,
                    action=(
                        "Event-Level-Gain-Evidence im Jahresbeleg archivieren; "
                        "Brutto-Preisdelta nicht als zusaetzlichen Gewinn oder "
                        "zusaetzlich eingesetztes Kapital interpretieren."
                    ),
                    evidence_ref=f"/api/v1/tax-years/{year}/gain-evidence-review?limit=500",
                    blocks_bmf_ready=False,
                )
            )
        if unmatched_disposals:
            gaps.append(
                TaxMethodologyGap(
                    code="unmatched_disposals",
                    severity="blocker",
                    message=f"{unmatched_disposals} FIFO-Abgang/Abgaenge ohne vollstaendiges Erwerbslot.",
                    count=unmatched_disposals,
                    action="Fehlende Imports, Transfers oder Anfangsbestaende klaeren.",
                    evidence_ref="/api/v1/tax/unmatched-disposals",
                    blocks_bmf_ready=True,
                )
            )
        if missing_price_groups:
            gaps.append(
                TaxMethodologyGap(
                    code="missing_price_groups",
                    severity="blocker",
                    message=f"{missing_price_groups} Preisgruppe(n) fehlen fuer Steuer-/Bewertungslogik.",
                    count=missing_price_groups,
                    action="Historische Tagespreise oder belegbare Fallbacks ergaenzen.",
                    evidence_ref="/api/v1/prices/coverage",
                    blocks_bmf_ready=True,
                )
            )
        if review_issues_count:
            gaps.append(
                TaxMethodologyGap(
                    code="review_issues_open",
                    severity="blocker",
                    message=f"{review_issues_count} Review-Issue(s) sind im Steuerjahr offen.",
                    count=review_issues_count,
                    action="Review-Issues mit Belegentscheidung schliessen.",
                    evidence_ref="/api/v1/review/gates",
                    blocks_bmf_ready=True,
                )
            )
        if external_review_count or external_unmatched_count:
            gaps.append(
                TaxMethodologyGap(
                    code="external_inflows_need_evidence",
                    severity="blocker",
                    message=(
                        f"{external_review_count} externe Zufluss-Kandidat(en) und "
                        f"{external_unmatched_count} unmatched Zufluss/Zufluesse brauchen Klaerung."
                    ),
                    count=external_review_count + external_unmatched_count,
                    action="Zufluesse als eigener Transfer, Reward, Airdrop, Servicezahlung oder unbekannt klassifizieren.",
                    evidence_ref="/api/v1/export/tax-external-inflows.csv",
                    blocks_bmf_ready=True,
                )
            )
        if tax_lines_count and traceability["tax_lines_with_event_trace"] < tax_lines_count:
            missing = tax_lines_count - traceability["tax_lines_with_event_trace"]
            gaps.append(
                TaxMethodologyGap(
                    code="tax_line_trace_incomplete",
                    severity="blocker",
                    message=f"{missing} Tax-Line(s) haben keine vollstaendige Disposal-/Lot-Event-Spur.",
                    count=missing,
                    action="Tax-Line zu Disposal Event und Erwerbslot zurueckverfolgen.",
                    evidence_ref=f"/api/v1/tax-years/{year}/drivers",
                    blocks_bmf_ready=True,
                )
            )
        if income_events_count and not tax_lines_count and not derivative_lines_count:
            gaps.append(
                TaxMethodologyGap(
                    code="income_only_year",
                    severity="info",
                    message="Jahr enthaelt Einnahmen wie Mining/Rewards/Staking, aber keine FIFO-Verkaeufe.",
                    action="Einnahmenbeleg und steuerliche Einordnung pruefen.",
                    evidence_ref=f"/api/v1/tax-years/{year}/income-guide",
                )
            )
        return gaps

    def _metrics(
        self,
        *,
        status: TaxMethodologyStatus,
        detail_tax_lines_count: int,
        counts: dict,
        external_review_count: int,
        external_unmatched_count: int,
        wallet_fifo_unmatched_count: int,
        wallet_fifo_exchange_sequencing_count: int,
        asset_fifo_possible_recalculation_count: int,
        asset_fifo_attribution_review_count: int,
        traceability_score: Decimal,
        gain_evidence_price_delta_lines_count: int = 0,
        gain_evidence_open_price_delta_eur: Decimal = Decimal("0"),
    ) -> list[TaxTraceabilityMetric]:
        tax_trace_status: TaxMethodologyStatus = "ok"
        if detail_tax_lines_count and counts["tax_lines_with_event_trace"] < detail_tax_lines_count:
            tax_trace_status = "blocked"
        return [
            TaxTraceabilityMetric(
                key="traceability_score",
                label="Nachverfolgbarkeit",
                status=status if status != "empty" else "empty",
                value=traceability_score,
                target=Decimal("100"),
                detail="Gesamtscore aus FIFO-Spur, Preisen, Review, externen Zufluessen und Methodenstatus.",
            ),
            TaxTraceabilityMetric(
                key="tax_line_event_trace",
                label="Tax-Line Event-Spur",
                status=tax_trace_status,
                value=counts["tax_lines_with_event_trace"],
                target=detail_tax_lines_count,
                detail="Tax-Line -> Disposal Event -> Erwerbslot -> Erwerbsereignis.",
            ),
            TaxTraceabilityMetric(
                key="source_coverage_observed",
                label="Quellen sichtbar",
                status="ok" if counts["sources_count"] else "empty",
                value=counts["sources_count"],
                target="alle relevanten Quellen je Jahr",
                detail="Anzahl unterschiedlicher Canonical-Event-Quellen im Steuerjahr.",
            ),
            TaxTraceabilityMetric(
                key="external_inflows_open",
                label="Externe Zufluesse offen",
                status="blocked" if external_review_count or external_unmatched_count else "ok",
                value=external_review_count + external_unmatched_count,
                target=0,
                detail="Ungeklaerte externe Zufluesse muessen vor BMF-Readiness klassifiziert sein.",
            ),
            TaxTraceabilityMetric(
                key="wallet_fifo_unmatched",
                label="Wallet-FIFO offene Lots",
                status=(
                    "blocked"
                    if wallet_fifo_unmatched_count > wallet_fifo_exchange_sequencing_count
                    else "review"
                    if wallet_fifo_exchange_sequencing_count
                    else "ok"
                ),
                value=max(0, wallet_fifo_unmatched_count - wallet_fifo_exchange_sequencing_count),
                target=0,
                detail=(
                    "Wallet-/Depot-FIFO-Evidence-Overlay darf keine echten unmatched Abgaenge enthalten. "
                    "Kleine dokumentierte CEX-/Grid-Sequencing-Ausnahmen bleiben als Review-Hinweis sichtbar."
                ),
            ),
            TaxTraceabilityMetric(
                key="asset_fifo_correction_candidates",
                label="Asset-FIFO Korrekturkandidaten",
                status="blocked" if asset_fifo_possible_recalculation_count else "ok",
                value=asset_fifo_possible_recalculation_count,
                target=0,
                detail="Nur echte moegliche Neuberechnungen blockieren; Quote-/Attribution-Hinweise bleiben Belegkontext.",
            ),
            TaxTraceabilityMetric(
                key="asset_fifo_attribution_notes",
                label="Asset-FIFO Attribution",
                status="review" if asset_fifo_attribution_review_count else "ok",
                value=asset_fifo_attribution_review_count,
                target="dokumentiert",
                detail="Quote-/Attribution-Hinweise, die nicht als zusaetzliche Steuerposition addiert werden duerfen.",
            ),
            TaxTraceabilityMetric(
                key="gain_evidence_event_level_reconciliation",
                label="Gain-Evidence Event-Level",
                status=(
                    "ok"
                    if not gain_evidence_price_delta_lines_count
                    or abs(gain_evidence_open_price_delta_eur) <= Decimal("0.01")
                    else "review"
                ),
                value=gain_evidence_open_price_delta_eur,
                target=Decimal("0"),
                detail=(
                    "Prueft, ob auffaellige Preisdelta-Summen aus FIFO-Split-/Quote-Allocation "
                    "auf Erwerbs- und Verkaufs-Event-Level plausibel geschlossen sind."
                ),
            ),
        ]

    def _traceability_score(self, gaps: list[TaxMethodologyGap], counts: dict) -> Decimal:
        if counts["activity_count"] == 0:
            return Decimal("0")
        score = Decimal("100")
        for gap in gaps:
            if gap.code == "fifo_scope_global_asset":
                score -= Decimal("25")
            elif gap.severity == "blocker":
                score -= Decimal("20")
            elif gap.severity == "warning":
                score -= Decimal("10")
        return max(score, Decimal("0"))

    def _status(self, gaps: list[TaxMethodologyGap], activity_count: int) -> TaxMethodologyStatus:
        if activity_count == 0:
            return "empty"
        if any(gap.severity == "blocker" for gap in gaps):
            return "blocked"
        if any(gap.blocks_bmf_ready or gap.severity == "warning" for gap in gaps):
            return "review"
        return "ok"

    def _status_from_report(self, report: TaxMethodologyReport) -> TaxYearComplianceStatus:
        return TaxYearComplianceStatus(
            year=report.year,
            status=report.status,
            label=report.label,
            bmf_ready=report.bmf_ready,
            tax_lines_count=report.tax_lines_count,
            income_events_count=report.income_events_count,
            derivative_lines_count=report.derivative_lines_count,
            unmatched_disposals=self._gap_count(report, "unmatched_disposals"),
            missing_price_groups=self._gap_count(report, "missing_price_groups"),
            review_issues_count=self._gap_count(report, "review_issues_open"),
            external_inflows_review_count=self._external_count(report),
            external_inflows_unmatched_count=0,
            traceability_score=report.traceability_score,
            gaps_count=len(report.gaps),
            blocking_gaps_count=sum(1 for gap in report.gaps if gap.blocks_bmf_ready),
            methodology_endpoint=f"/api/v1/tax-years/{report.year}/methodology",
            evidence_package_endpoint=f"/api/v1/export/tax-years/{report.year}/evidence-package.zip",
        )

    def _action_item_from_gap(self, year: int, gap: TaxMethodologyGap) -> TaxBmfActionItem:
        category = self._gap_category(gap.code)
        title = self._gap_title(gap.code)
        return TaxBmfActionItem(
            year=year,
            category=category,
            severity=gap.severity,
            code=gap.code,
            title=title,
            detail=gap.message,
            count=gap.count,
            blocks_bmf_ready=gap.blocks_bmf_ready,
            evidence_ref=gap.evidence_ref,
            action=gap.action,
        )

    def _gap_category(self, code: str) -> str:
        if code.startswith("wallet_fifo_delta"):
            return "wallet_fifo_delta"
        if code.startswith("wallet_fifo"):
            return "wallet_fifo"
        if code.startswith("asset_fifo"):
            return "asset_fifo"
        if code.startswith("external_inflows"):
            return "external_inflow"
        if code.startswith("missing_price"):
            return "price"
        if code.startswith("review"):
            return "review"
        if code.startswith("tax_line_trace"):
            return "traceability"
        if code.startswith("gain_evidence"):
            return "traceability"
        if code.startswith("no_tax_year_activity"):
            return "activity"
        if code.startswith("income"):
            return "income"
        return "traceability"

    def _gap_title(self, code: str) -> str:
        titles = {
            "wallet_fifo_preview_unmatched": "Wallet-/Depot-FIFO Herkunft fehlt",
            "wallet_fifo_exchange_sequencing_documented": "Wallet-FIFO Exchange-Sequencing dokumentiert",
            "wallet_fifo_delta_present": "Wallet-FIFO Delta dokumentieren",
            "wallet_fifo_evidence_overlay_ok": "Wallet-FIFO Evidence vorhanden",
            "wallet_fifo_unresolved_inbound_provenance": "Wallet-FIFO Zufluss-Herkunft offen",
            "wallet_fifo_fiat_purchase_documented": "Wallet-FIFO Fiat-Anschaffung dokumentiert",
            "wallet_fifo_non_live_opening_balance_documented": (
                "Wallet-FIFO Anfangsbestand dokumentiert"
            ),
            "wallet_fifo_legacy_cex_deposit_documented": "Wallet-FIFO Legacy-HNT-CEX-Deposit dokumentiert",
            "wallet_fifo_legacy_cex_deposit_mirror_documented": (
                "Wallet-FIFO Legacy-HNT-CEX-Deposit-Spiegel dokumentiert"
            ),
            "wallet_fifo_fairspot_staking_return_documented": (
                "Wallet-FIFO Fairspot/Staking-Ruecktransfer dokumentiert"
            ),
            "wallet_fifo_legacy_counterparty_mirror_documented": (
                "Wallet-FIFO Legacy-Gegenpartei-Spiegel dokumentiert"
            ),
            "wallet_fifo_exchange_deposit_history_documented": (
                "Wallet-FIFO Exchange-Deposit-History dokumentiert"
            ),
            "wallet_fifo_legacy_hnt_external_payment_documented": (
                "Wallet-FIFO externe Legacy-HNT-Zahlung dokumentiert"
            ),
            "wallet_fifo_token_redenomination_documented": "Wallet-FIFO Token-Redenomination dokumentiert",
            "wallet_fifo_manual_cex_deposit_documented": "Wallet-FIFO manueller CEX-Deposit dokumentiert",
            "wallet_fifo_external_or_unknown_origin_documented": (
                "Wallet-FIFO externe/unklare Herkunft dokumentiert"
            ),
            "wallet_fifo_unverified_cex_deposit_documented": (
                "Wallet-FIFO CEX-Deposit ohne Sender-Ownership dokumentiert"
            ),
            "asset_fifo_possible_recalculation": "Asset-FIFO moegliche Neuberechnung",
            "asset_fifo_quote_attribution_documented": "Quote-/Attribution dokumentiert",
            "gain_evidence_event_level_reconciled": "Gain-Evidence Event-Level plausibilisiert",
            "external_inflows_need_evidence": "Externe Zufluesse klaeren",
            "missing_price_groups": "Historische Preise ergaenzen",
            "review_issues_open": "Review-Issues schliessen",
            "tax_line_trace_incomplete": "Tax-Line Spur vervollstaendigen",
            "income_only_year": "Einnahmenjahr belegen",
            "no_tax_year_activity": "Keine Aktivitaet",
        }
        return titles.get(code, code.replace("_", " "))

    def _gap_count(self, report: TaxMethodologyReport, code: str) -> int:
        return sum(gap.count for gap in report.gaps if gap.code == code)

    def _external_count(self, report: TaxMethodologyReport) -> int:
        return sum(gap.count for gap in report.gaps if gap.code == "external_inflows_need_evidence")

    def _label(self, status: TaxMethodologyStatus) -> str:
        if status == "ok":
            return "BMF-ready"
        if status == "blocked":
            return "nicht einreichen"
        if status == "review":
            return "vor Einreichung pruefen"
        return "keine Aktivitaet"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
