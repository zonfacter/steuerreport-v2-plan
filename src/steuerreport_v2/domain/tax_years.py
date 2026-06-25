from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from decimal import Decimal
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from steuerreport_v2.contracts.tax_years import (
    TaxDeclarationGuide,
    TaxDeclarationGuideEntry,
    TaxYearFilingActionStatus,
    TaxYearFilingClosureRow,
    TaxIncomeAssetBreakdown,
    TaxIncomeEventPreview,
    TaxIncomeReport,
    TaxExternalInflowMatch,
    TaxExternalInflowReport,
    TaxPaymentChecklistItem,
    TaxPaymentOverview,
    TaxPaymentOverviewRow,
    TaxLossRealizationLot,
    TaxLossRealizationPlanner,
    TaxRewardTradingSeparationReport,
    TaxRewardTradingSeparationRow,
    TaxYearGainLossRealityAssetRow,
    TaxYearGainLossRealityCheck,
    TaxYearGainEvidenceDeltaGroup,
    TaxYearGainEvidenceAcquisitionEventDeltaLine,
    TaxYearGainEvidenceAcquisitionEventDeltaReview,
    TaxYearGainEvidenceEventDeltaLine,
    TaxYearGainEvidenceEventDeltaReview,
    TaxYearGainEvidencePriceDeltaDrilldown,
    TaxYearGainEvidencePriceDeltaLine,
    TaxYearGainEvidenceLine,
    TaxYearGainEvidenceReview,
    TaxYearCorrectionMap,
    TaxYearCorrectionMapLine,
    TaxYearFilingChecklistItem,
    TaxYearFilingMatrix,
    TaxYearFilingMatrixRow,
    TaxYearFilingSummary,
    TaxYearFilingSummaryLine,
    TaxYearsCorrectionMap,
    TaxYearsFilingClosureOverview,
    TaxYearAssetFifoDrilldown,
    TaxYearAssetFifoEvent,
    TaxYearAssetFifoLine,
    TaxYearAssetFifoCorrectionReviewReport,
    TaxYearAssetFifoCorrectionReviewRow,
    TaxYearBmfClosureAppendix,
    TaxYearBmfClosureAppendixItem,
    TaxYearAssetFifoPlausibilityReport,
    TaxYearAssetFifoPlausibilityRow,
    TaxYearAssetFifoRawEvidence,
    TaxYearAssetBreakdown,
    TaxYearDetail,
    TaxYearDriverLine,
    TaxYearDriverReport,
    TaxYearEvidenceItem,
    TaxYearEvidenceReport,
    TaxYearIssue,
    TaxYearReviewDecisionSummary,
    TaxYearTurnoverAssetBreakdown,
    TaxYearTurnoverAudit,
    TaxYearTurnoverAuditSummaryRow,
    TaxYearTurnoverSourceBreakdown,
    TaxSolanaProgramIncomeAssetSummary,
    TaxHeliumSwapContextAssetSummary,
    TaxHeliumSwapEvidenceReview,
    TaxHeliumSwapEvidenceRow,
    TaxHeliumSwapContextReview,
    TaxHeliumSwapContextRow,
    TaxHeliumSwapContextYearSummary,
    TaxSolanaProgramIncomeReview,
    TaxSolanaProgramIncomeRow,
    TaxSolanaProgramIncomeYearSummary,
    TaxSolanaStablecoinFxAssetSummary,
    TaxSolanaStablecoinFxReview,
    TaxSolanaStablecoinFxRow,
    TaxSolanaStablecoinSwapAssetSummary,
    TaxSolanaStablecoinSwapContextReview,
    TaxSolanaStablecoinSwapContextRow,
    TaxStablecoinFifoAssetSummary,
    TaxStablecoinFifoLine,
    TaxStablecoinFifoReview,
    TaxStablecoinFifoSourceSummary,
    TaxStablecoinQuoteLegReview,
    TaxStablecoinQuoteLegRow,
    TaxStablecoinQuoteLegSummary,
    TaxYearsTurnoverAuditSummary,
    TaxYearsSummary,
    TaxYearStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.valuation import PriceCoverageService


INCOME_EVENT_TYPES = {"income", "reward", "staking", "mining"}
STABLECOIN_LIKE_ASSETS = {"USDC", "USDT", "DAI", "BUSD", "FDUSD", "TUSD", "EURC", "EURS"}
HELIUM_REWARD_ASSETS = ("HNT", "IOT", "MOBILE")
HELIUM_SWAP_ALCHEMY_AUDIT_PATH = (
    Path("/workspace/steuerreport-v2-plan")
    / "var"
    / "helium_swap_alchemy_audits"
    / "latest_all_years_helium_swap_alchemy_audit.json"
)


class TaxYearService:
    DEFAULT_YEARS = range(2020, 2027)

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._tax_lines_cache: list[object] | None = None
        self._unmatched_cache: list[object] | None = None
        self._missing_prices_cache: list[object] | None = None
        self._derivative_lines_cache: list[object] | None = None
        self._tax_totals_cache: dict[int, dict[str, Decimal | int]] | None = None
        self._payment_tax_totals_cache: dict[int, dict[str, Decimal | int]] | None = None
        self._asset_breakdown_cache: dict[int, list[TaxYearAssetBreakdown]] | None = None
        self._income_totals_cache: dict[int, dict[str, Decimal | int]] | None = None
        self._fees_cache: dict[int, Decimal] | None = None
        self._derivatives_cache: dict[int, dict[str, Decimal | int]] | None = None
        self._payment_derivatives_cache: dict[int, dict[str, Decimal | int]] | None = None
        self._payment_missing_price_groups_cache: dict[int, int] | None = None
        self._payment_unmatched_disposals_cache: dict[int, int] | None = None
        self._income_reports_cache: dict[int, TaxIncomeReport] | None = None
        self._income_asset_breakdown_from_lots_cache: dict[int, list[TaxIncomeAssetBreakdown]] = {}
        self._external_solana_inflow_counts_cache: dict[int, int] | None = None
        self._status_cache: dict[int, TaxYearStatus] = {}
        self._declaration_guide_cache: dict[int, TaxDeclarationGuide] = {}
        self._external_inflow_report_cache: dict[tuple[int, int], TaxExternalInflowReport] = {}
        self._bmf_closure_appendix_cache: dict[tuple[int, int], TaxYearBmfClosureAppendix] = {}

    def summary(self) -> TaxYearsSummary:
        years = self._available_years()
        statuses = [self._status_for_year(year) for year in years]
        return TaxYearsSummary(
            years=statuses,
            available_years=years,
            methodology=(
                "Aggregiert je Steuerjahr aus FIFO-Tax-Lines, unmatched "
                "Disposals, historischen Preisgaps, Derivate-Lines und "
                "Income/Reward/Mining/Staking-Events. Die Logik schreibt keine "
                "Steuerdaten und ersetzt nicht das globale Review-/Export-Gate. "
                "Private Veraeusserungen werden fuer die steuerpflichtige Summe "
                "nach Haltezeit getrennt: bis 365 Tage steuerpflichtig, darueber "
                "nachrichtlich steuerfrei."
            ),
        )

    def detail(self, year: int) -> TaxYearDetail:
        status = self._status_for_year(year)
        missing = [item for item in self._missing_prices() if item.year == year]
        unmatched = [item for item in self._unmatched_disposals() if item.event_time.year == year]
        tax_lines = [item for item in self._tax_lines() if item.disposed_at.year == year]
        return TaxYearDetail(
            **status.model_dump(),
            asset_breakdown=self._asset_breakdown(year),
            missing_price_assets=sorted({item.asset for item in missing}),
            sample_unmatched_ids=[item.unmatched_id for item in unmatched[:10]],
            sample_tax_line_ids=[item.tax_line_id for item in tax_lines[:10]],
            methodology=(
                "Jahresdetail fuer Status, Gewinne, Einkuenfte, Derivate und "
                "Blocker. Historisch geschlossene Jahre bleiben sichtbar; offene "
                "Punkte dort werden als historisch markiert."
            ),
        )

    def payment_overview(self, *, years: list[int] | None = None) -> TaxPaymentOverview:
        rows: list[TaxPaymentOverviewRow] = []
        statuses = self._payment_statuses(years=years)
        for status in statuses:
            caveats = self._payment_caveats(status)
            blocking_caveats = [
                issue.message
                for issue in status.issues
                if issue.blocks_export
            ]
            caveats = blocking_caveats + caveats
            declaration_parts = []
            if status.realized_gain_loss_eur:
                declaration_parts.append("Anlage SO")
            if status.rewards_income_eur:
                declaration_parts.append("Sonstige Einkuenfte/EUR")
            if status.derivative_pnl_eur:
                declaration_parts.append("Derivate/Termingeschaefte pruefen")
            declaration_bucket = " + ".join(declaration_parts) if declaration_parts else "keine Eingabe aus V2-Werten"
            where_to_enter = self._where_to_enter(status)
            what_to_do = self._tax_year_next_action(status)
            rows.append(
                TaxPaymentOverviewRow(
                    year=status.year,
                    status=status.label,
                    private_disposals_gain_loss_eur=status.realized_gain_loss_eur,
                    rewards_mining_staking_income_eur=status.rewards_income_eur,
                    derivative_pnl_eur=status.derivative_pnl_eur,
                    tax_free_private_disposals_eur=status.tax_free_gain_loss_eur,
                    declaration_bucket=declaration_bucket,
                    where_to_enter=where_to_enter,
                    what_to_do=what_to_do,
                    evidence_refs=self._payment_evidence_exports(),
                    caveats=caveats[:5],
                    checklist=self._payment_checklist(status, caveats),
                    display_line=self._payment_overview_line(status, declaration_bucket, what_to_do),
                )
            )
        return TaxPaymentOverview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            ascii_table=self._payment_ascii_table(rows),
            methodology=(
                "Read-only vereinfachter Steuer-Eingabezettel aus bestehenden "
                "Tax-Year-Aggregaten und Declaration-Guide. Er berechnet keine "
                "neue Steuerlast und ersetzt keine Einkommensteuerberechnung; "
                "er zeigt nur, welche V2-Betraege je Jahr wohin gehoeren."
            ),
        )

    def _payment_statuses(self, *, years: list[int] | None = None) -> list[TaxYearStatus]:
        selected_years = sorted(years if years is not None else self._payment_available_years())
        return [self._payment_status_for_year(year) for year in selected_years]

    def _payment_available_years(self) -> list[int]:
        years = set(self.DEFAULT_YEARS)
        with self.store.connect() as con:
            rows = con.execute(
                """
                select year from (
                    select distinct date_part('year', disposed_at)::integer as year from tax_lines
                    union
                    select distinct date_part('year', event_time)::integer as year from tax_unmatched_disposals
                    union
                    select distinct date_part('year', event_time)::integer as year from derivative_lines
                    union
                    select distinct date_part('year', event_time)::integer as year
                    from canonical_events
                    where event_type in ('income', 'reward', 'staking', 'mining')
                )
                order by year
                """
            ).fetchall()
        years.update(int(row[0]) for row in rows if row[0] is not None)
        years.update(self._closed_tax_years())
        return sorted(years)

    def _payment_status_for_year(self, year: int) -> TaxYearStatus:
        tax = self._payment_tax_totals_by_year().get(year, {})
        income = self._income_totals_by_year().get(year, {})
        derivatives = self._payment_derivatives_by_year().get(year, {})
        missing_count = self._payment_missing_price_groups_by_year().get(year, 0)
        unmatched_count = self._payment_unmatched_disposals_by_year().get(year, 0)
        closed_years = self._closed_tax_years()
        is_closed = year in closed_years
        issues: list[TaxYearIssue] = []
        if missing_count:
            issues.append(
                TaxYearIssue(
                    code="missing_event_price",
                    severity="high",
                    message=f"{missing_count} Preisgruppe(n) ohne historische EUR-Bewertung.",
                    count=missing_count,
                    blocks_export=not is_closed,
                )
            )
        if unmatched_count:
            issues.append(
                TaxYearIssue(
                    code="unmatched_tax_disposal",
                    severity="high",
                    message=f"{unmatched_count} FIFO-Abgang/Abgaenge ohne vollstaendiges Lot.",
                    count=unmatched_count,
                    blocks_export=not is_closed,
                )
            )
        derivative_missing = int(derivatives.get("missing_price_count", 0) or 0)
        if derivative_missing:
            issues.append(
                TaxYearIssue(
                    code="derivative_missing_prices",
                    severity="high",
                    message=f"{derivative_missing} Derivate-Zeile(n) ohne EUR-Bewertung.",
                    count=derivative_missing,
                    blocks_export=not is_closed,
                )
            )
        has_activity = any(
            [
                int(tax.get("tax_lines_count", 0) or 0),
                int(tax.get("tax_free_lines_count", 0) or 0),
                int(income.get("events", 0) or 0),
                int(derivatives.get("lines", 0) or 0),
                missing_count,
                unmatched_count,
            ]
        )
        blocks = any(issue.blocks_export for issue in issues)
        if blocks:
            state = "blocked"
            label = "blockiert"
        elif issues and is_closed:
            state = "historical_open"
            label = "nur historisch offen"
        elif has_activity or is_closed:
            state = "finished"
            label = "fertig"
        else:
            state = "empty"
            label = "leer"
        return TaxYearStatus(
            year=year,
            state=state,
            label=label,
            is_closed_historical_year=is_closed,
            export_blocked=blocks,
            realized_gain_loss_eur=tax.get("gain_loss", Decimal("0")),
            taxable_disposal_proceeds_eur=tax.get("proceeds", Decimal("0")),
            acquisition_cost_eur=tax.get("acquisition_cost", Decimal("0")),
            tax_lines_count=int(tax.get("tax_lines_count", 0) or 0),
            tax_free_gain_loss_eur=tax.get("tax_free_gain_loss", Decimal("0")),
            tax_free_disposal_proceeds_eur=tax.get("tax_free_proceeds", Decimal("0")),
            tax_free_acquisition_cost_eur=tax.get("tax_free_acquisition_cost", Decimal("0")),
            tax_free_lines_count=int(tax.get("tax_free_lines_count", 0) or 0),
            rewards_income_eur=income.get("income_eur", Decimal("0")),
            rewards_events_count=int(income.get("events", 0) or 0),
            derivative_pnl_eur=derivatives.get("pnl", Decimal("0")),
            derivative_lines_count=int(derivatives.get("lines", 0) or 0),
            fees_eur=self._fees_by_year().get(year, Decimal("0")),
            missing_price_groups=missing_count,
            unmatched_disposals=unmatched_count,
            review_issues_count=len(issues),
            top_assets=[],
            issues=issues,
        )

    def _payment_tax_totals_by_year(self) -> dict[int, dict[str, Decimal | int]]:
        if self._payment_tax_totals_cache is not None:
            return self._payment_tax_totals_cache
        totals: dict[int, dict[str, Decimal | int]] = {}
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    date_part('year', disposed_at)::integer as year,
                    coalesce(sum(case when holding_days <= 365 then gain_loss_eur else 0 end), 0) as gain_loss,
                    coalesce(sum(case when holding_days <= 365 then disposal_proceeds_eur else 0 end), 0) as proceeds,
                    coalesce(sum(case when holding_days <= 365 then acquisition_cost_eur else 0 end), 0) as acquisition_cost,
                    count(*) filter (where holding_days <= 365)::integer as tax_lines_count,
                    coalesce(sum(case when holding_days > 365 then gain_loss_eur else 0 end), 0) as tax_free_gain_loss,
                    coalesce(sum(case when holding_days > 365 then disposal_proceeds_eur else 0 end), 0) as tax_free_proceeds,
                    coalesce(sum(case when holding_days > 365 then acquisition_cost_eur else 0 end), 0) as tax_free_acquisition_cost,
                    count(*) filter (where holding_days > 365)::integer as tax_free_lines_count
                from tax_lines
                group by year
                order by year
                """
            ).fetchall()
        for (
            year,
            gain_loss,
            proceeds,
            acquisition_cost,
            tax_lines_count,
            tax_free_gain_loss,
            tax_free_proceeds,
            tax_free_acquisition_cost,
            tax_free_lines_count,
        ) in rows:
            totals[int(year)] = {
                "gain_loss": gain_loss or Decimal("0"),
                "proceeds": proceeds or Decimal("0"),
                "acquisition_cost": acquisition_cost or Decimal("0"),
                "tax_lines_count": int(tax_lines_count or 0),
                "tax_free_gain_loss": tax_free_gain_loss or Decimal("0"),
                "tax_free_proceeds": tax_free_proceeds or Decimal("0"),
                "tax_free_acquisition_cost": tax_free_acquisition_cost or Decimal("0"),
                "tax_free_lines_count": int(tax_free_lines_count or 0),
            }
        self._payment_tax_totals_cache = totals
        return totals

    def _payment_derivatives_by_year(self) -> dict[int, dict[str, Decimal | int]]:
        if self._payment_derivatives_cache is not None:
            return self._payment_derivatives_cache
        totals: dict[int, dict[str, Decimal | int]] = {}
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    date_part('year', event_time)::integer as year,
                    coalesce(sum(value_eur), 0) as pnl,
                    count(*)::integer as lines,
                    count(*) filter (where price_source is null)::integer as missing_price_count
                from derivative_lines
                group by year
                order by year
                """
            ).fetchall()
        for year, pnl, lines, missing_price_count in rows:
            totals[int(year)] = {
                "pnl": pnl or Decimal("0"),
                "lines": int(lines or 0),
                "missing_price_count": int(missing_price_count or 0),
            }
        self._payment_derivatives_cache = totals
        return totals

    def _payment_missing_price_groups_by_year(self) -> dict[int, int]:
        if self._payment_missing_price_groups_cache is not None:
            return self._payment_missing_price_groups_cache
        query = PriceCoverageService(self.store)._missing_price_query(
            """
            date_part('year', req.event_time)::integer as year,
            req.asset,
            req.source,
            req.event_type,
            req.role
            """,
            """
            date_part('year', req.event_time),
            req.asset,
            req.source,
            req.event_type,
            req.role
            """,
            """
            year,
            req.asset,
            req.source,
            req.event_type,
            req.role
            """,
        )
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select year, count(*)::integer as groups_count
                from ({query}) missing_groups
                group by year
                order by year
                """
            ).fetchall()
        self._payment_missing_price_groups_cache = {
            int(year): int(groups_count or 0)
            for year, groups_count in rows
        }
        return self._payment_missing_price_groups_cache

    def _payment_unmatched_disposals_by_year(self) -> dict[int, int]:
        if self._payment_unmatched_disposals_cache is not None:
            return self._payment_unmatched_disposals_cache
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    date_part('year', event_time)::integer as year,
                    count(*)::integer as unmatched_count
                from tax_unmatched_disposals
                group by year
                order by year
                """
            ).fetchall()
        self._payment_unmatched_disposals_cache = {
            int(year): int(unmatched_count or 0)
            for year, unmatched_count in rows
        }
        return self._payment_unmatched_disposals_cache

    def _payment_ascii_table(self, rows: list[TaxPaymentOverviewRow]) -> str:
        headers = ["Jahr", "SO G/V", "Rewards", "Derivate", "Steuerfrei", "Eintragen", "Status"]
        body = [
            [
                str(row.year),
                self._fmt_eur(row.private_disposals_gain_loss_eur),
                self._fmt_eur(row.rewards_mining_staking_income_eur),
                self._fmt_eur(row.derivative_pnl_eur),
                self._fmt_eur(row.tax_free_private_disposals_eur),
                row.declaration_bucket,
                row.status,
            ]
            for row in rows
            if (
                row.private_disposals_gain_loss_eur
                or row.rewards_mining_staking_income_eur
                or row.derivative_pnl_eur
                or row.tax_free_private_disposals_eur
                or row.status != "leer"
            )
        ]
        table_rows = [headers, *body]
        widths = [
            max(len(str(item[index])) for item in table_rows)
            for index in range(len(headers))
        ]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(headers), sep, *(fmt(row) for row in body), sep])

    def declaration_guide(self, year: int) -> TaxDeclarationGuide:
        cached = self._declaration_guide_cache.get(year)
        if cached is not None:
            return cached.model_copy(deep=True)
        status = self._status_for_year(year)
        assets = self._asset_breakdown(year)
        hnt = next((item for item in assets if item.asset.upper() == "HNT"), None)
        loss_assets = [item for item in assets if item.gain_loss_eur < 0]
        gain_assets = [item for item in assets if item.gain_loss_eur > 0]
        entries = [
            TaxDeclarationGuideEntry(
                section="Private Veraeusserungsgeschaefte / Anlage SO",
                field_label="Gewinn oder Verlust aus privaten Veraeusserungsgeschaeften mit Kryptowerten",
                amount_eur=status.realized_gain_loss_eur,
                sign="loss" if status.realized_gain_loss_eur < 0 else "gain" if status.realized_gain_loss_eur > 0 else "neutral",
                evidence_ref="/api/v1/export/tax-lines.csv",
                note=(
                    "Saldo aus FIFO-Tax-Lines des Jahres. Negative Werte sind als Verlust "
                    "aus privaten Veraeusserungsgeschaeften nachweisbar, nicht als frei erfundene Gegenbuchung."
                ),
            ),
            TaxDeclarationGuideEntry(
                section="Private Veraeusserungsgeschaefte / Anlage SO",
                field_label="Veraeusserungserloese",
                amount_eur=status.taxable_disposal_proceeds_eur,
                sign="neutral",
                evidence_ref="/api/v1/export/tax-lines.csv",
                note="Summe der EUR-Veraeusserungserloese aus steuerlichen Tax-Lines.",
            ),
            TaxDeclarationGuideEntry(
                section="Private Veraeusserungsgeschaefte / Anlage SO",
                field_label="Anschaffungskosten",
                amount_eur=status.acquisition_cost_eur,
                sign="neutral",
                evidence_ref="/api/v1/export/tax-lines.csv",
                note="Summe der FIFO-Anschaffungskosten der veraeusserten Mengen.",
            ),
        ]
        if status.tax_free_lines_count:
            entries.append(
                TaxDeclarationGuideEntry(
                    section="Steuerfreie Veraeusserungen nach Haltefrist",
                    field_label="Nachrichtlich: Gewinn/Verlust aus > 1 Jahr gehaltenen Lots",
                    amount_eur=status.tax_free_gain_loss_eur,
                    sign="neutral",
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    note=(
                        "FIFO-Zeilen mit Haltezeit ueber 365 Tagen. Diese werden nicht in den "
                        "steuerpflichtigen Anlage-SO-Saldo eingerechnet."
                    ),
                )
            )
        if status.rewards_income_eur:
            entries.append(
                TaxDeclarationGuideEntry(
                    section="Sonstige Einkuenfte",
                    field_label="Einzutragende Rewards / Mining / Staking",
                    amount_eur=status.rewards_income_eur,
                    sign="income",
                    evidence_ref=f"/api/v1/tax-years/{year}/income-guide",
                    note=(
                        "Eng klassifizierte Reward-/Mining-/Staking-Einnahmen. "
                        "Review-only Income-Kontexte stehen getrennt im Income Guide "
                        "und werden hier nicht automatisch addiert."
                    ),
                )
            )
        if hnt is not None:
            entries.append(
                TaxDeclarationGuideEntry(
                    section="HNT Schwerpunkt",
                    field_label="HNT Gewinn/Verlust",
                    amount_eur=hnt.gain_loss_eur,
                    sign="loss" if hnt.gain_loss_eur < 0 else "gain" if hnt.gain_loss_eur > 0 else "neutral",
                    evidence_ref="/api/v1/export/hnt-provenance-events.csv",
                    note="HNT-spezifischer FIFO-Saldo mit Bridge-/Fairspot-/Legacy-Nachweisen.",
                )
            )
        external_inflows = self.external_inflow_report(year, limit=0)
        review_decisions = self._review_decisions_for_year(year)
        if external_inflows.review_count or external_inflows.unmatched_count:
            entries.append(
                TaxDeclarationGuideEntry(
                    section="Pruefbereich externe Solana-Zufluesse",
                    field_label="Review/Unmatched externe Solana-Zufluesse",
                    amount_eur=external_inflows.review_value_eur + external_inflows.unmatched_value_eur,
                    sign="neutral",
                    evidence_ref="/api/v1/export/tax-external-inflows.csv",
                    note=(
                        "Nicht automatisch als Einkuenfte deklariert. Diese Zufluesse brauchen "
                        "Beleg als eigener Transfer, Airdrop/Claim oder Importklassifizierung."
                    ),
                )
            )
        caveats = []
        if status.review_issues_count:
            caveats.append(f"{status.review_issues_count} Jahres-Issue(s) pruefen.")
        if status.missing_price_groups:
            caveats.append(f"{status.missing_price_groups} Preisgruppe(n) fehlen.")
        if status.unmatched_disposals:
            caveats.append(f"{status.unmatched_disposals} FIFO-Abgaenge sind unmatched.")
        if external_inflows.review_count or external_inflows.unmatched_count:
            caveats.append(
                "Externe Solana-Zufluesse pruefen: "
                f"{external_inflows.review_count} Review-Kandidat(en), "
                f"{external_inflows.unmatched_count} unmatched; CSV: /api/v1/export/tax-external-inflows.csv."
            )
        if review_decisions:
            caveats.append(
                f"{len(review_decisions)} Review-Entscheidung(en) mit Jahresbezug im Belegpaket beruecksichtigen."
            )
        caveats.append(
            "Formularzeilen koennen sich je ELSTER/WISO-Version unterscheiden; diese Hilfe liefert Betragslogik und Belegverweise, keine ERiC-Uebertragung."
        )
        guide = TaxDeclarationGuide(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            export_ready=not status.export_blocked,
            realized_gain_loss_eur=status.realized_gain_loss_eur,
            taxable_disposal_proceeds_eur=status.taxable_disposal_proceeds_eur,
            acquisition_cost_eur=status.acquisition_cost_eur,
            tax_free_gain_loss_eur=status.tax_free_gain_loss_eur,
            tax_free_disposal_proceeds_eur=status.tax_free_disposal_proceeds_eur,
            tax_free_acquisition_cost_eur=status.tax_free_acquisition_cost_eur,
            tax_free_lines_count=status.tax_free_lines_count,
            rewards_income_eur=status.rewards_income_eur,
            derivative_pnl_eur=status.derivative_pnl_eur,
            hnt_gain_loss_eur=hnt.gain_loss_eur if hnt is not None else Decimal("0"),
            hnt_disposal_proceeds_eur=hnt.proceeds_eur if hnt is not None else Decimal("0"),
            hnt_acquisition_cost_eur=hnt.acquisition_cost_eur if hnt is not None else Decimal("0"),
            hnt_tax_line_count=hnt.tax_line_count if hnt is not None else 0,
            loss_assets=loss_assets,
            gain_assets=gain_assets,
            entries=entries,
            review_decisions=review_decisions,
            caveats=caveats,
            evidence_exports=[
                "/api/v1/export/tax-lines.csv",
                "/api/v1/export/tax-income-guide.csv",
                "/api/v1/export/tax-external-inflows.csv",
                "/api/v1/export/review-decisions.csv",
                "/api/v1/export/hnt-provenance-timeline.csv",
                "/api/v1/export/hnt-provenance-events.csv",
                "/api/v1/export/evidence-package.zip",
            ],
            methodology=(
                "Read-only Eingabehilfe aus Tax-Year-Aggregaten, Asset-Breakdown "
                "und HNT-Provenance. Alle Zeiten werden intern als UTC gespeichert; "
                "Betragsausgabe bleibt Decimal-basiert."
            ),
        )
        self._declaration_guide_cache[year] = guide.model_copy(deep=True)
        return guide

    def _where_to_enter(self, status: TaxYearStatus) -> str:
        targets = []
        if status.realized_gain_loss_eur:
            targets.append("Private Veraeusserungsgeschaefte mit Kryptowerten: Gewinn/Verlust, Erloese, Anschaffungskosten")
        if status.rewards_income_eur:
            targets.append("Einzutragende Rewards/Mining/Staking als sonstige Einkuenfte bzw. EÜR-nahe Einnahmen pruefen")
        if status.derivative_pnl_eur:
            targets.append("Derivate/Termingeschaefte separat pruefen")
        if status.tax_free_lines_count:
            targets.append("Steuerfreie >365-Tage-Verkaeufe nur nachrichtlich/belegseitig aufbewahren")
        return " | ".join(targets) if targets else "Keine steuerliche Eingabe aus aktuellen V2-Jahreswerten."

    def _tax_year_next_action(self, status: TaxYearStatus) -> str:
        if status.export_blocked:
            return "Nicht einreichen: erst fehlende Preise/FIFO-Issues/Derivate-Issues klaeren."
        if status.state == "historical_open":
            return "Historisch offen: nur als Altjahres-Hinweis pruefen; aktuelle Exportfreigabe wird nicht blockiert."
        if status.realized_gain_loss_eur < 0:
            return "Verlust belegbar erfassen und mit Tax-Lines/Exportpaket nachweisen."
        if status.realized_gain_loss_eur > 0 or status.rewards_income_eur > 0 or status.derivative_pnl_eur:
            return "Betrag in Steuererklaerung uebernehmen und Exportpaket als Beleg bereithalten."
        return "Keine Zahlung aus V2-Jahreswerten erkennbar; Belege trotzdem archivieren."

    def _payment_checklist(
        self,
        status: TaxYearStatus,
        caveats: list[str],
    ) -> list[TaxPaymentChecklistItem]:
        items: list[TaxPaymentChecklistItem] = []
        if status.realized_gain_loss_eur:
            disposition = "Verlust" if status.realized_gain_loss_eur < 0 else "Gewinn"
            items.append(
                TaxPaymentChecklistItem(
                    category="eintragen",
                    label=f"Private Veraeusserungen: {disposition}",
                    amount_eur=status.realized_gain_loss_eur,
                    target="Anlage SO: Gewinn/Verlust aus Kryptowerten",
                    detail=(
                        "Saldo aus steuerpflichtigen FIFO-Tax-Lines bis 365 Tage. "
                        "Erloese und Anschaffungskosten mit dem Tax-Line-Export belegen."
                    ),
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    severity="info",
                )
            )
            if status.taxable_disposal_proceeds_eur or status.acquisition_cost_eur:
                items.append(
                    TaxPaymentChecklistItem(
                        category="eintragen",
                        label="Erloese und Anschaffungskosten",
                        amount_eur=None,
                        target="Anlage SO Detailwerte",
                        detail=(
                            "Erloese "
                            f"{self._fmt_eur(status.taxable_disposal_proceeds_eur)}, "
                            "Anschaffungskosten "
                            f"{self._fmt_eur(status.acquisition_cost_eur)}."
                        ),
                        evidence_ref="/api/v1/export/tax-lines.csv",
                        severity="info",
                    )
                )
        if status.rewards_income_eur:
            items.append(
                TaxPaymentChecklistItem(
                    category="eintragen",
                    label="Einzutragende Rewards / Mining / Staking",
                    amount_eur=status.rewards_income_eur,
                    target="Sonstige Einkuenfte oder EÜR-nahe Einnahmen pruefen",
                    detail=(
                        "Eng klassifizierte Mining-, Reward- und Staking-Zufluesse "
                        "getrennt von privaten Veraeusserungen erfassen."
                    ),
                    evidence_ref="/api/v1/export/tax-income-guide.csv",
                    severity="info",
                )
            )
        if status.tax_free_lines_count:
            items.append(
                TaxPaymentChecklistItem(
                    category="beleg",
                    label="Steuerfrei nach Haltefrist",
                    amount_eur=status.tax_free_gain_loss_eur,
                    target="Nicht in den steuerpflichtigen Anlage-SO-Saldo uebernehmen",
                    detail=(
                        f"{status.tax_free_lines_count} FIFO-Zeile(n) mit Haltezeit ueber 365 Tagen. "
                        "Nur nachrichtlich und als Beleg fuer den Stichtagsverlauf aufbewahren."
                    ),
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    severity="info",
                )
            )
        if status.derivative_pnl_eur:
            items.append(
                TaxPaymentChecklistItem(
                    category="pruefen",
                    label="Derivate / Termingeschaefte",
                    amount_eur=status.derivative_pnl_eur,
                    target="Separat gegen Derivate-Report pruefen",
                    detail="Derivate werden nicht in den privaten Krypto-FIFO-Saldo gemischt.",
                    evidence_ref="/api/v1/export/derivative-lines.csv",
                    severity="warning",
                )
            )
        for issue in status.issues:
            if issue.blocks_export:
                items.append(
                    TaxPaymentChecklistItem(
                        category="pruefen",
                        label=issue.code,
                        amount_eur=None,
                        target="Vor Einreichung klaeren",
                        detail=issue.message,
                        evidence_ref="/api/v1/tax-years/summary",
                        severity="blocker",
                    )
                )
        for caveat in caveats:
            if "Externe Solana-Zufluesse" in caveat:
                items.append(
                    TaxPaymentChecklistItem(
                        category="pruefen",
                        label="Externe Solana-Zufluesse",
                        amount_eur=None,
                        target="Transfer/Airdrop/Importklassifizierung belegen",
                        detail=caveat,
                        evidence_ref="/api/v1/export/tax-external-inflows.csv",
                        severity="warning",
                    )
                )
                break
        if not items:
            items.append(
                TaxPaymentChecklistItem(
                    category="beleg",
                    label="Keine V2-Eingabewerte",
                    amount_eur=None,
                    target="Belege archivieren",
                    detail="Fuer dieses Jahr sind in V2 keine steuerlichen Eingabebetraege erkennbar.",
                    evidence_ref="/api/v1/export/evidence-package.zip",
                    severity="info",
                )
            )
        return items

    @staticmethod
    def _payment_evidence_exports() -> list[str]:
        return [
            "/api/v1/export/tax-lines.csv",
            "/api/v1/export/tax-income-guide.csv",
            "/api/v1/export/tax-external-inflows.csv",
            "/api/v1/export/hnt-provenance-timeline.csv",
            "/api/v1/export/hnt-provenance-events.csv",
            "/api/v1/export/evidence-package.zip",
        ]

    def _payment_caveats(self, status: TaxYearStatus) -> list[str]:
        caveats: list[str] = []
        if status.review_issues_count:
            caveats.append(f"{status.review_issues_count} Jahres-Issue(s) pruefen.")
        if status.missing_price_groups:
            caveats.append(f"{status.missing_price_groups} Preisgruppe(n) fehlen.")
        if status.unmatched_disposals:
            caveats.append(f"{status.unmatched_disposals} FIFO-Abgaenge sind unmatched.")
        external_inflows_count = self._external_solana_inflow_count(status.year)
        if external_inflows_count:
            caveats.append(
                "Externe Solana-Zufluesse pruefen: "
                f"{external_inflows_count} Kandidat(en); Detail/CSV: "
                "/api/v1/export/tax-external-inflows.csv."
            )
        caveats.append(
            "Formularzeilen koennen sich je ELSTER/WISO-Version unterscheiden; diese Hilfe liefert Betragslogik und Belegverweise, keine ERiC-Uebertragung."
        )
        return caveats

    def _payment_overview_line(
        self,
        status: TaxYearStatus,
        declaration_bucket: str,
        what_to_do: str,
    ) -> str:
        return (
            f"{status.year} | SO G/V {self._fmt_eur(status.realized_gain_loss_eur)} | "
            f"Rewards {self._fmt_eur(status.rewards_income_eur)} | "
            f"Derivate {self._fmt_eur(status.derivative_pnl_eur)} | "
            f"steuerfrei {self._fmt_eur(status.tax_free_gain_loss_eur)} | "
            f"{declaration_bucket} | {what_to_do}"
        )

    def _review_decisions_for_year(self, year: int) -> list[TaxYearReviewDecisionSummary]:
        decisions: list[TaxYearReviewDecisionSummary] = []
        for decision in self.store.list_review_decisions():
            if not self._decision_matches_year(decision.scope, decision.payload, year):
                continue
            decisions.append(
                TaxYearReviewDecisionSummary(
                    decision_id=decision.decision_id,
                    decision_type=decision.decision_type,
                    scope=decision.scope,
                    title=decision.title,
                    evidence_ref=decision.evidence_ref,
                    category="pruefen" if self._decision_needs_review(decision.payload) else "beleg",
                    effect_summary=self._decision_effect_summary(decision.payload),
                    created_at=decision.created_at.isoformat(),
                )
            )
        return decisions

    @staticmethod
    def _decision_matches_year(scope: str, payload: dict[str, object], year: int) -> bool:
        year_text = str(year)
        if f"year:{year_text}" in scope or f"jahr:{year_text}" in scope:
            return True
        for key in ("year", "tax_year", "jahr"):
            value = payload.get(key)
            if value is not None and str(value) == year_text:
                return True
        years = payload.get("years")
        if isinstance(years, list) and year_text in {str(item) for item in years}:
            return True
        return False

    @staticmethod
    def _decision_needs_review(payload: dict[str, object]) -> bool:
        status = str(payload.get("decision_status") or payload.get("status") or "").lower()
        return any(marker in status for marker in ("review", "manual", "required", "pruef"))

    @staticmethod
    def _decision_effect_summary(payload: dict[str, object]) -> str:
        effects = []
        for key, label in (
            ("import_effect", "Import"),
            ("ledger_effect", "Ledger"),
            ("fifo_effect", "FIFO"),
            ("tax_line_effect", "Tax-Lines"),
        ):
            value = payload.get(key)
            if value is not None:
                effects.append(f"{label}: {value}")
        if effects:
            return " | ".join(effects)
        return "Beleg-/Methodikentscheidung; keine automatische Datenwirkung dokumentiert."

    @staticmethod
    def _fmt_eur(value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01'))} EUR"

    def filing_summary(self, year: int) -> TaxYearFilingSummary:
        status = self._status_for_year(year)
        guide = self.declaration_guide(year)
        review_decisions = self._review_decisions_for_year(year)
        bmf_closure_appendix = self.bmf_closure_appendix(year)
        lines: list[TaxYearFilingSummaryLine] = []
        order = 1

        if status.realized_gain_loss_eur:
            label = "Privates Veraeusserungsergebnis"
            treatment = "steuerpflichtiger Verlust" if status.realized_gain_loss_eur < 0 else "steuerpflichtiger Gewinn"
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="private_disposal",
                    label=label,
                    amount_eur=status.realized_gain_loss_eur,
                    tax_treatment=treatment,
                    declaration_target="Anlage SO: Gewinn/Verlust aus privaten Veraeusserungsgeschaeften mit Kryptowerten",
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    note=(
                        "FIFO-Saldo aus steuerpflichtigen Veraeusserungen bis 365 Tage. "
                        f"Erloese {self._fmt_eur(status.taxable_disposal_proceeds_eur)}, "
                        f"Anschaffungskosten {self._fmt_eur(status.acquisition_cost_eur)}."
                    ),
                )
            )
            order += 1
        else:
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="private_disposal",
                    label="Privates Veraeusserungsergebnis",
                    amount_eur=Decimal("0"),
                    tax_treatment="kein V2-Eingabebetrag",
                    declaration_target="Keine Anlage-SO-Eingabe aus steuerpflichtigen V2-FIFO-Zeilen",
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    note="Fuer dieses Jahr liegt kein steuerpflichtiger FIFO-Gewinn oder -Verlust vor.",
                )
            )
            order += 1

        if status.rewards_income_eur:
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="income",
                    label="Einzutragende Rewards / Mining / Staking",
                    amount_eur=status.rewards_income_eur,
                    tax_treatment="steuerpflichtige Einnahmen",
                    declaration_target="Sonstige Einkuenfte bzw. EÜR-nahe Einnahmen pruefen",
                    evidence_ref="/api/v1/export/tax-income-guide.csv",
                    note=(
                        "Nur eng klassifizierte Reward-/Mining-/Staking-Zufluesse. "
                        "Review-only Income-Kontexte sind im Income Guide separat markiert."
                    ),
                )
            )
            order += 1

        if status.derivative_pnl_eur:
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="derivative",
                    label="Derivate / Termingeschaefte",
                    amount_eur=status.derivative_pnl_eur,
                    tax_treatment="separat pruefen",
                    declaration_target="Nicht mit privaten Krypto-FIFO-Zeilen vermischen",
                    evidence_ref="/api/v1/export/derivative-lines.csv",
                    note="Derivate bleiben als eigener Pruefbereich sichtbar.",
                )
            )
            order += 1

        if status.tax_free_lines_count:
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="tax_free",
                    label="Steuerfreie Veraeusserungen > 365 Tage",
                    amount_eur=status.tax_free_gain_loss_eur,
                    tax_treatment="nicht steuerpflichtig nach Haltefrist",
                    declaration_target="Nicht in den steuerpflichtigen Anlage-SO-Saldo uebernehmen",
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    note=f"{status.tax_free_lines_count} FIFO-Zeile(n) bleiben nachrichtlich fuer die Historie belegbar.",
                )
            )
            order += 1

        try:
            from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService

            cex_anchor_feasibility = WalletFifoPreviewService(self.store).cex_exchange_outflow_anchor_feasibility(
                year,
                source_exchange="bitget",
                target_cex="binance",
                network="SOL",
            )
        except Exception:
            cex_anchor_feasibility = None

        if cex_anchor_feasibility and cex_anchor_feasibility.decisions_count:
            anchor_ready = cex_anchor_feasibility.anchor_missing_count == 0
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="evidence",
                    label="CEX-FIFO-Anker Bitget -> Binance",
                    amount_eur=None,
                    tax_treatment=(
                        "steuerneutraler Depotwechsel mit FIFO-Fortschreibung"
                        if anchor_ready
                        else "Review-Entscheidung vorhanden, FIFO-Anker pruefen"
                    ),
                    declaration_target=(
                        "Nicht als Veraeusserung eintragen; Belegkette im Jahrespaket archivieren"
                    ),
                    evidence_ref=(
                        f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility"
                        "?source_exchange=bitget&target_cex=binance&network=SOL"
                    ),
                    note=(
                        f"{cex_anchor_feasibility.anchor_ready_count} von "
                        f"{cex_anchor_feasibility.decisions_count} Exchange-Outflow-Entscheidung(en) "
                        "haben einen vorhandenen Wallet-FIFO-Transferanker."
                    ),
                )
            )
            order += 1

        if bmf_closure_appendix.items_count:
            appendix_ready = (
                bmf_closure_appendix.status == "ready"
                or bmf_closure_appendix.can_file_with_conservative_appendix
            )
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="appendix",
                    label="BMF-Abschlussbeilage Herkunft",
                    amount_eur=None,
                    tax_treatment=(
                        "konservativ belegbar"
                        if appendix_ready
                        else "vor Einreichung pruefen"
                    ),
                    declaration_target="Nicht als Betrag eintragen; Herkunftsbeilage archivieren/beilegen",
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    note=(
                        f"{bmf_closure_appendix.items_count} Herkunftsposition(en), "
                        f"{bmf_closure_appendix.conservative_items_count} konservativ belegbar, "
                        f"{bmf_closure_appendix.manual_evidence_required_count} manuell zu pruefen. "
                        "Keine offene Herkunft als steuerneutralen Eigenwallet-Transfer behaupten."
                    ),
                )
            )
            order += 1

        lines.append(
            TaxYearFilingSummaryLine(
                order=order,
                topic="evidence",
                label="Belegpaket",
                amount_eur=None,
                tax_treatment="Nachweis",
                declaration_target="Exportpaket archivieren und bei Rueckfragen vorlegen",
                evidence_ref="/api/v1/export/evidence-package.zip",
                note="ZIP enthaelt die steuerlichen CSVs, Guides und Nachweisdateien.",
            )
        )
        order += 1

        if review_decisions:
            lines.append(
                TaxYearFilingSummaryLine(
                    order=order,
                    topic="review",
                    label="Review-Entscheidungen mit Jahresbezug",
                    amount_eur=None,
                    tax_treatment="Beleg-/Methodikentscheidung",
                    declaration_target="Nicht als Betrag eintragen; Entscheidung als Nachweis zum Steuerjahr archivieren",
                    evidence_ref="/api/v1/export/review-decisions.csv",
                    note=(
                        f"{len(review_decisions)} Entscheidung(en) betreffen dieses Steuerjahr. "
                        "Details stehen im Filing JSON und in review-decisions.csv."
                    ),
                )
            )
            order += 1

        warnings = list(guide.caveats)
        if bmf_closure_appendix.items_count and bmf_closure_appendix.status != "ready":
            warnings.append(
                "BMF-Abschlussbeilage enthaelt konservativ dokumentierte Herkunftspositionen; "
                "Details vor Abgabe mit dem Belegpaket pruefen."
            )
        for issue in status.issues:
            if issue.blocks_export:
                lines.append(
                    TaxYearFilingSummaryLine(
                        order=order,
                        topic="review",
                        label=issue.code,
                        amount_eur=None,
                        tax_treatment="vor Einreichung klaeren",
                        declaration_target="Review Gate / Jahresstatus",
                        evidence_ref="/api/v1/tax-years/summary",
                        note=issue.message,
                    )
                )
                order += 1

        checklist = self._filing_checklist(lines)
        return TaxYearFilingSummary(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            export_ready=not status.export_blocked,
            status_label=status.label,
            plain_language_summary=self._filing_plain_language_summary(status),
            taxable_private_disposals_eur=status.realized_gain_loss_eur,
            taxable_disposal_proceeds_eur=status.taxable_disposal_proceeds_eur,
            acquisition_cost_eur=status.acquisition_cost_eur,
            rewards_mining_staking_income_eur=status.rewards_income_eur,
            derivative_pnl_eur=status.derivative_pnl_eur,
            tax_free_private_disposals_eur=status.tax_free_gain_loss_eur,
            tax_free_lines_count=status.tax_free_lines_count,
            bmf_closure_appendix_status=bmf_closure_appendix.status,
            bmf_closure_appendix_items_count=bmf_closure_appendix.items_count,
            bmf_closure_appendix_manual_evidence_required_count=(
                bmf_closure_appendix.manual_evidence_required_count
            ),
            can_file_with_conservative_appendix=bmf_closure_appendix.can_file_with_conservative_appendix,
            lines=lines,
            checklist=checklist,
            review_decisions=review_decisions,
            warnings=warnings,
            ascii_table=self._filing_ascii_table(year, lines),
            checklist_ascii=self._filing_checklist_ascii(year, checklist),
            methodology=(
                "Read-only Steuerjahr-Erklaerung aus Tax-Year-Status, Declaration-Guide, "
                "BMF-Abschlussbeilage und vorhandenen Exportverweisen. Es werden keine "
                "FIFO-Lots, Preise, Imports oder Steuerentscheidungen geschrieben."
            ),
        )

    def _filing_plain_language_summary(self, status: TaxYearStatus) -> str:
        parts = []
        if status.realized_gain_loss_eur < 0:
            parts.append(f"privater Verlust {self._fmt_eur(status.realized_gain_loss_eur)}")
        elif status.realized_gain_loss_eur > 0:
            parts.append(f"privater Gewinn {self._fmt_eur(status.realized_gain_loss_eur)}")
        if status.rewards_income_eur:
            parts.append(f"einzutragende Rewards/Mining/Staking {self._fmt_eur(status.rewards_income_eur)}")
        if status.derivative_pnl_eur:
            parts.append(f"Derivate {self._fmt_eur(status.derivative_pnl_eur)}")
        if status.tax_free_lines_count:
            parts.append(f"steuerfrei nach Haltefrist {self._fmt_eur(status.tax_free_gain_loss_eur)}")
        if not parts:
            parts.append("keine V2-Eingabebetraege")
        if status.export_blocked:
            parts.append("vor Einreichung blockierende Punkte klaeren")
        return f"{status.year}: " + "; ".join(parts) + "."

    def filing_matrix(self, *, years: list[int] | None = None) -> TaxYearFilingMatrix:
        if years is None:
            snapshot_matrix = self._filing_matrix_from_readiness_snapshot()
            if snapshot_matrix is not None:
                return snapshot_matrix
        selected_years = sorted(years if years is not None else self._payment_available_years())
        rows: list[TaxYearFilingMatrixRow] = []
        for year in selected_years:
            summary = self.filing_summary(year)
            counts: dict[str, int] = defaultdict(int)
            for item in summary.checklist:
                counts[item.category] += 1
            action_status = self._filing_matrix_action_status(summary, counts)
            rows.append(
                TaxYearFilingMatrixRow(
                    year=year,
                    status_label=summary.status_label,
                    export_ready=summary.export_ready,
                    action_status=action_status,
                    next_action=self._filing_matrix_next_action(summary, counts, action_status),
                    taxable_private_disposals_eur=summary.taxable_private_disposals_eur,
                    rewards_mining_staking_income_eur=summary.rewards_mining_staking_income_eur,
                    derivative_pnl_eur=summary.derivative_pnl_eur,
                    tax_free_private_disposals_eur=summary.tax_free_private_disposals_eur,
                    checklist_counts=dict(counts),
                    bmf_closure_appendix_status=summary.bmf_closure_appendix_status,
                    bmf_closure_appendix_items_count=summary.bmf_closure_appendix_items_count,
                    bmf_closure_appendix_manual_evidence_required_count=(
                        summary.bmf_closure_appendix_manual_evidence_required_count
                    ),
                    warnings_count=len(summary.warnings),
                    review_decisions_count=len(summary.review_decisions),
                    filing_summary_endpoint=f"/api/v1/tax-years/{year}/filing-summary",
                    filing_checklist_csv_endpoint=f"/api/v1/export/tax-years/{year}/filing-checklist.csv",
                    evidence_package_endpoint=f"/api/v1/export/tax-years/{year}/evidence-package.zip",
                    display_line=self._filing_matrix_display_line(summary, counts, action_status),
                )
            )
        return TaxYearFilingMatrix(
            generated_at=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            ready_years=[row.year for row in rows if row.action_status == "ready"],
            conservative_ready_years=[row.year for row in rows if row.action_status == "conservative_ready"],
            review_years=[row.year for row in rows if row.action_status == "review"],
            blocked_years=[row.year for row in rows if row.action_status == "blocked"],
            ascii_table=self._filing_matrix_ascii_table(rows),
            methodology=(
                "Read-only Jahresmatrix aus bestehenden Filing-Summaries. "
                "Sie verdichtet Eintragen, Beilegen, Archivieren und Pruefen pro Jahr "
                "und schreibt keine FIFO-Lots, Preise, Imports oder Review-Entscheidungen."
            ),
        )

    def correction_map(self, *, years: list[int] | None = None) -> TaxYearsCorrectionMap:
        if years is None:
            snapshot_map = self._correction_map_from_readiness_snapshot()
            if snapshot_map is not None:
                return snapshot_map
        selected_years = sorted(years if years is not None else [2021, 2022, 2023, 2024, 2025])
        maps = [self.year_correction_map(year) for year in selected_years]
        return TaxYearsCorrectionMap(
            generated_at=datetime.now(timezone.utc).isoformat(),
            years=maps,
            amendment_review_years=[item.year for item in maps if item.amendment_review_recommended],
            archive_only_years=[
                item.year
                for item in maps
                if not item.amendment_review_recommended
                and not any(line.risk_level == "blocked" for line in item.lines)
            ],
            blocked_years=[
                item.year
                for item in maps
                if any(line.risk_level == "blocked" for line in item.lines)
            ],
            ascii_table=self._correction_map_ascii_table(maps),
            methodology=(
                "Read-only Korrekturkarte fuer Steuerjahre. Sie nutzt ausschliesslich "
                "die bestehende Filing-Summary je Jahr und berechnet keine Steuerdaten "
                "neu. Sie ist keine Rechtsberatung; sie zeigt, welche V2-Zahlen und "
                "Belege fuer eine Vorjahrespruefung oder Nachreichung relevant sind."
            ),
        )

    def filing_closure_overview(self, *, years: list[int] | None = None) -> TaxYearsFilingClosureOverview:
        selected_years = sorted(years if years is not None else [2021, 2022, 2023, 2024, 2025])
        payment = self.payment_overview(years=selected_years)
        filing = self.filing_matrix()
        if not all(year in {row.year for row in filing.rows} for year in selected_years):
            filing = self.filing_matrix(years=selected_years)
        correction = self.correction_map()
        if not all(year in {row.year for row in correction.years} for year in selected_years):
            correction = self.correction_map(years=selected_years)
        payment_by_year = {row.year: row for row in payment.rows}
        filing_by_year = {row.year: row for row in filing.rows}
        correction_by_year = {row.year: row for row in correction.years}
        rows: list[TaxYearFilingClosureRow] = []
        for year in selected_years:
            payment_row = payment_by_year.get(year)
            filing_row = filing_by_year.get(year)
            correction_row = correction_by_year.get(year)
            counts = filing_row.checklist_counts if filing_row is not None else {}
            action_status: TaxYearFilingActionStatus = filing_row.action_status if filing_row is not None else "review"
            private_disposals = (
                filing_row.taxable_private_disposals_eur
                if filing_row is not None
                else payment_row.private_disposals_gain_loss_eur
                if payment_row is not None
                else Decimal("0")
            )
            rewards = (
                filing_row.rewards_mining_staking_income_eur
                if filing_row is not None
                else payment_row.rewards_mining_staking_income_eur
                if payment_row is not None
                else Decimal("0")
            )
            derivative = (
                filing_row.derivative_pnl_eur
                if filing_row is not None
                else payment_row.derivative_pnl_eur
                if payment_row is not None
                else Decimal("0")
            )
            tax_free = (
                filing_row.tax_free_private_disposals_eur
                if filing_row is not None
                else payment_row.tax_free_private_disposals_eur
                if payment_row is not None
                else Decimal("0")
            )
            correction_action = (
                "Korrektur/Nachreichung pruefen"
                if correction_row is not None and correction_row.amendment_review_recommended
                else "Archivieren"
            )
            next_action = filing_row.next_action if filing_row is not None else "Jahresdaten pruefen."
            row = TaxYearFilingClosureRow(
                year=year,
                filing_status=action_status,
                filing_status_label=filing_row.status_label if filing_row is not None else "Pruefen",
                export_ready=filing_row.export_ready if filing_row is not None else False,
                declaration_bucket=(
                    payment_row.declaration_bucket if payment_row is not None else "keine Eingabe aus V2-Werten"
                ),
                where_to_enter=payment_row.where_to_enter if payment_row is not None else "Pruefen",
                private_disposals_gain_loss_eur=private_disposals,
                rewards_mining_staking_income_eur=rewards,
                derivative_pnl_eur=derivative,
                tax_free_private_disposals_eur=tax_free,
                eintragen_count=int(counts.get("eintragen", 0) or 0),
                beilegen_count=int(counts.get("beilegen", 0) or 0),
                pruefen_count=int(counts.get("pruefen", 0) or 0),
                archivieren_count=int(counts.get("archivieren", 0) or 0),
                amendment_review_recommended=(
                    correction_row.amendment_review_recommended if correction_row is not None else False
                ),
                amendment_reason=(
                    correction_row.amendment_reason if correction_row is not None else "Korrekturkarte nicht geladen."
                ),
                next_action=next_action,
                correction_action=correction_action,
                filing_summary_endpoint=f"/api/v1/tax-years/{year}/filing-summary",
                filing_checklist_csv_endpoint=f"/api/v1/export/tax-years/{year}/filing-checklist.csv",
                correction_map_endpoint=f"/api/v1/tax-years/{year}/correction-map",
                correction_map_csv_endpoint=f"/api/v1/export/tax-years/{year}/correction-map.csv",
                evidence_package_endpoint=f"/api/v1/export/tax-years/{year}/evidence-package.zip",
                display_line=(
                    f"{year} | {action_status} | SO {self._fmt_eur(private_disposals)} | "
                    f"Rewards {self._fmt_eur(rewards)} | Derivate {self._fmt_eur(derivative)} | "
                    f"Steuerfrei {self._fmt_eur(tax_free)} | {correction_action}"
                ),
            )
            rows.append(row)
        return TaxYearsFilingClosureOverview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            ready_years=[row.year for row in rows if row.filing_status == "ready"],
            conservative_ready_years=[row.year for row in rows if row.filing_status == "conservative_ready"],
            review_years=[row.year for row in rows if row.filing_status == "review"],
            blocked_years=[row.year for row in rows if row.filing_status == "blocked"],
            amendment_review_years=[row.year for row in rows if row.amendment_review_recommended],
            total_private_disposals_gain_loss_eur=sum(
                (row.private_disposals_gain_loss_eur for row in rows), Decimal("0")
            ),
            total_rewards_mining_staking_income_eur=sum(
                (row.rewards_mining_staking_income_eur for row in rows), Decimal("0")
            ),
            total_derivative_pnl_eur=sum((row.derivative_pnl_eur for row in rows), Decimal("0")),
            total_tax_free_private_disposals_eur=sum(
                (row.tax_free_private_disposals_eur for row in rows), Decimal("0")
            ),
            ascii_table=self._filing_closure_ascii_table(rows),
            methodology=(
                "Read-only Abschlussuebersicht aus Payment-Overview, Filing-Matrix "
                "und Korrekturkarte. Sie schreibt keine FIFO-Lots, Preise, Imports "
                "oder Review-Entscheidungen und ist keine Rechtsberatung."
            ),
        )

    def _year_correction_map_from_readiness_snapshot(self, year: int) -> TaxYearCorrectionMap | None:
        snapshot_map = self._correction_map_from_readiness_snapshot()
        if snapshot_map is None:
            return None
        return next((item for item in snapshot_map.years if item.year == year), None)

    def _correction_map_from_readiness_snapshot(self) -> TaxYearsCorrectionMap | None:
        path = self._bmf_filing_readiness_snapshot_path()
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        years_payload = payload.get("years")
        if not isinstance(years_payload, list):
            return None
        selected_years = [
            int(item["year"])
            for item in years_payload
            if isinstance(item, dict) and item.get("year") is not None
        ]
        payment_rows = {row.year: row for row in self.payment_overview(years=selected_years).rows}
        maps: list[TaxYearCorrectionMap] = []
        for item in years_payload:
            if not isinstance(item, dict):
                continue
            year = int(item.get("year"))
            taxable_private = Decimal(str(item.get("taxable_private_disposals_eur") or "0"))
            rewards_income = Decimal(str(item.get("rewards_mining_staking_income_eur") or "0"))
            derivative_pnl = Decimal(str(item.get("derivative_pnl_eur") or "0"))
            payment_row = payment_rows.get(year)
            tax_free = payment_row.tax_free_private_disposals_eur if payment_row is not None else Decimal("0")
            appendix_items = int(item.get("appendix_items_count") or 0)
            appendix_manual = int(item.get("appendix_manual_evidence_required_count") or 0)
            blocking_codes = item.get("blocking_gap_codes") if isinstance(item.get("blocking_gap_codes"), list) else []
            review_codes = item.get("review_gap_codes") if isinstance(item.get("review_gap_codes"), list) else []
            lines = self._snapshot_correction_lines(
                year=year,
                taxable_private=taxable_private,
                rewards_income=rewards_income,
                derivative_pnl=derivative_pnl,
                tax_free=tax_free,
                appendix_items=appendix_items,
                appendix_manual=appendix_manual,
                review_codes_count=len(review_codes),
                blocking_codes_count=len(blocking_codes),
            )
            amendment_relevant = any(
                line.action_category in {"eintragen", "korrigieren_pruefen"} or line.risk_level == "blocked"
                for line in lines
            )
            if blocking_codes:
                reason = "Vor Korrektur/Nachreichung blockierende BMF-Punkte klaeren."
            elif amendment_relevant:
                reason = (
                    "V2 enthaelt eintragungsrelevante Jahreswerte. Wenn die urspruengliche "
                    "Erklaerung davon abweicht oder diese Werte fehlten, Korrektur/Nachreichung pruefen."
                )
            else:
                reason = "Keine eintragungsrelevanten V2-Betraege; Belege archivieren."
            maps.append(
                TaxYearCorrectionMap(
                    year=year,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    filing_status=str(item.get("status_label") or item.get("filing_status") or "-"),
                    amendment_review_recommended=amendment_relevant,
                    amendment_reason=reason,
                    taxable_private_disposals_eur=taxable_private,
                    rewards_mining_staking_income_eur=rewards_income,
                    derivative_pnl_eur=derivative_pnl,
                    tax_free_private_disposals_eur=tax_free,
                    lines=lines,
                    ascii_table=self._year_correction_map_ascii_table(year, lines, reason),
                    methodology=(
                        "Schnelle read-only Korrekturkarte aus dem BMF-Filing-Readiness-"
                        "Snapshot und Payment-Overview. Fuer Detailbelege den Jahres-"
                        "Endpunkt oder das Jahres-Belegpaket oeffnen."
                    ),
                )
            )
        maps.sort(key=lambda entry: entry.year)
        return TaxYearsCorrectionMap(
            generated_at=datetime.now(timezone.utc).isoformat(),
            years=maps,
            amendment_review_years=[entry.year for entry in maps if entry.amendment_review_recommended],
            archive_only_years=[entry.year for entry in maps if not entry.amendment_review_recommended],
            blocked_years=[
                entry.year
                for entry in maps
                if any(line.risk_level == "blocked" for line in entry.lines)
            ],
            ascii_table=self._correction_map_ascii_table(maps),
            methodology=(
                "Read-only Gesamt-Korrekturkarte aus dem vorhandenen BMF-Filing-"
                "Readiness-Snapshot. Sie ist fuer die UI optimiert und schreibt "
                "keine FIFO-Lots, Preise, Imports oder Review-Entscheidungen."
            ),
        )

    def _snapshot_correction_lines(
        self,
        *,
        year: int,
        taxable_private: Decimal,
        rewards_income: Decimal,
        derivative_pnl: Decimal,
        tax_free: Decimal,
        appendix_items: int,
        appendix_manual: int,
        review_codes_count: int,
        blocking_codes_count: int,
    ) -> list[TaxYearCorrectionMapLine]:
        lines: list[TaxYearCorrectionMapLine] = []
        order = 1
        for topic, label, amount, target in (
            (
                "private_disposal",
                "Privates Veraeusserungsergebnis",
                taxable_private,
                "Anlage SO: Gewinn/Verlust aus privaten Veraeusserungsgeschaeften mit Kryptowerten",
            ),
            (
                "income",
                "Rewards / Mining / Staking",
                rewards_income,
                "Sonstige Einkuenfte bzw. EÜR-nahe Einnahmen pruefen",
            ),
            (
                "derivative",
                "Derivate / Termingeschaefte",
                derivative_pnl,
                "Nicht mit privaten Krypto-FIFO-Zeilen vermischen",
            ),
        ):
            if amount:
                lines.append(
                    TaxYearCorrectionMapLine(
                        order=order,
                        topic=topic,
                        label=label,
                        action_category="korrigieren_pruefen",
                        amount_eur=amount,
                        declaration_target=target,
                        evidence_ref=f"/api/v1/tax-years/{year}/filing-summary",
                        correction_note=(
                            "Betrag mit der urspruenglich abgegebenen Steuererklaerung "
                            "vergleichen und bei Abweichung als Korrektur-/Nachreichungsposition pruefen."
                        ),
                        risk_level="review",
                    )
                )
                order += 1
        if tax_free:
            lines.append(
                TaxYearCorrectionMapLine(
                    order=order,
                    topic="tax_free",
                    label="Steuerfreie Veraeusserungen > 365 Tage",
                    action_category="archivieren",
                    amount_eur=tax_free,
                    declaration_target="Nicht in den steuerpflichtigen Anlage-SO-Saldo uebernehmen",
                    evidence_ref="/api/v1/export/tax-lines.csv",
                    correction_note="Nach Haltefrist steuerfrei; fuer Rueckfragen mit FIFO-Beleg archivieren.",
                    risk_level="info",
                )
            )
            order += 1
        if appendix_items:
            lines.append(
                TaxYearCorrectionMapLine(
                    order=order,
                    topic="appendix",
                    label="BMF-Abschlussbeilage Herkunft",
                    action_category="beilegen",
                    amount_eur=None,
                    declaration_target="Nicht als Betrag eintragen; Herkunftsbeilage archivieren/beilegen",
                    evidence_ref=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                    correction_note=(
                        f"{appendix_items} Herkunftsposition(en), {appendix_manual} manuell zu pruefen. "
                        "Die Beilage erzeugt keinen zusaetzlichen Steuerbetrag."
                    ),
                    risk_level="review" if appendix_manual else "info",
                )
            )
            order += 1
        if review_codes_count or blocking_codes_count:
            lines.append(
                TaxYearCorrectionMapLine(
                    order=order,
                    topic="review",
                    label="BMF-/Methodik-Pruefpunkte",
                    action_category="pruefen" if blocking_codes_count else "beilegen",
                    amount_eur=None,
                    declaration_target="Nicht als Betrag eintragen; Status mit Jahrespaket belegen",
                    evidence_ref=f"/api/v1/tax-years/{year}/methodology",
                    correction_note=(
                        f"{review_codes_count} Review-Code(s), {blocking_codes_count} Blocker-Code(s) "
                        "aus dem BMF-Filing-Readiness-Snapshot."
                    ),
                    risk_level="blocked" if blocking_codes_count else "review",
                )
            )
            order += 1
        lines.append(
            TaxYearCorrectionMapLine(
                order=order,
                topic="evidence",
                label="Jahres-Belegpaket",
                action_category="archivieren",
                amount_eur=None,
                declaration_target="Exportpaket archivieren und bei Rueckfragen vorlegen",
                evidence_ref=f"/api/v1/export/tax-years/{year}/evidence-package.zip",
                correction_note="Enthaelt Filing Summary, Korrekturkarte, Belegkarte und FIFO-/Herkunftsbelege.",
                risk_level="info",
            )
        )
        return lines

    def year_correction_map(self, year: int) -> TaxYearCorrectionMap:
        snapshot_map = self._year_correction_map_from_readiness_snapshot(year)
        if snapshot_map is not None:
            return snapshot_map
        summary = self.filing_summary(year)
        lines: list[TaxYearCorrectionMapLine] = []
        order = 1
        amendment_relevant = False
        blocked = False
        for line in summary.lines:
            action_category, risk_level, note = self._correction_action_for_filing_line(line, summary)
            if action_category in {"eintragen", "korrigieren_pruefen"}:
                amendment_relevant = True
            if risk_level == "blocked":
                blocked = True
            lines.append(
                TaxYearCorrectionMapLine(
                    order=order,
                    topic=line.topic,
                    label=line.label,
                    action_category=action_category,
                    amount_eur=line.amount_eur,
                    declaration_target=line.declaration_target,
                    evidence_ref=line.evidence_ref,
                    correction_note=note,
                    risk_level=risk_level,
                )
            )
            order += 1

        if blocked:
            reason = "Vor Korrektur/Nachreichung blockierende Jahrespunkte klaeren."
        elif amendment_relevant:
            reason = (
                "V2 enthaelt eintragungsrelevante Jahreswerte. Wenn die urspruengliche "
                "Erklaerung davon abweicht oder diese Werte fehlten, Korrektur/Nachreichung pruefen."
            )
        else:
            reason = "Keine eintragungsrelevanten V2-Betraege; Belege archivieren."
        return TaxYearCorrectionMap(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            filing_status=summary.status_label,
            amendment_review_recommended=amendment_relevant or blocked,
            amendment_reason=reason,
            taxable_private_disposals_eur=summary.taxable_private_disposals_eur,
            rewards_mining_staking_income_eur=summary.rewards_mining_staking_income_eur,
            derivative_pnl_eur=summary.derivative_pnl_eur,
            tax_free_private_disposals_eur=summary.tax_free_private_disposals_eur,
            lines=lines,
            ascii_table=self._year_correction_map_ascii_table(year, lines, reason),
            methodology=(
                "Read-only Vorjahres-Korrekturkarte aus der vorhandenen Filing-Summary. "
                "Eintraege mit Betrag zeigen moegliche Erklaerungs- oder Korrekturwerte; "
                "Belege und BMF-Herkunftsbeilagen werden nicht als zusaetzliche "
                "Betragszeilen verstanden."
            ),
        )

    def _correction_action_for_filing_line(
        self,
        line: TaxYearFilingSummaryLine,
        summary: TaxYearFilingSummary,
    ) -> tuple[
        Literal["eintragen", "korrigieren_pruefen", "beilegen", "archivieren", "pruefen"],
        Literal["info", "review", "blocked"],
        str,
    ]:
        amount = line.amount_eur or Decimal("0")
        if line.topic in {"private_disposal", "income", "derivative"} and amount:
            return (
                "korrigieren_pruefen",
                "review" if summary.export_ready else "blocked",
                (
                    "Betrag mit der urspruenglich abgegebenen Steuererklaerung vergleichen. "
                    "Bei Abweichung als Korrektur-/Nachreichungsposition mit Belegpfad pruefen."
                ),
            )
        if line.topic == "tax_free":
            return (
                "archivieren",
                "info",
                (
                    "Nach Haltefrist steuerfrei; nicht in den steuerpflichtigen Saldo uebernehmen, "
                    "aber fuer Rueckfragen mit FIFO-Beleg archivieren."
                ),
            )
        if line.topic == "appendix":
            risk: Literal["info", "review", "blocked"] = (
                "review" if summary.bmf_closure_appendix_manual_evidence_required_count else "info"
            )
            return (
                "beilegen",
                risk,
                (
                    "BMF-Herkunftsbeilage beilegen oder archivieren. Sie erklaert Herkunft/"
                    "Transferstatus und erzeugt keinen zusaetzlichen Steuerbetrag."
                ),
            )
        if line.topic == "review" or not summary.export_ready:
            return (
                "pruefen",
                "blocked" if not summary.export_ready else "review",
                "Review-/Methodikpunkt vor Abgabe oder Korrektur gegen Belege pruefen.",
            )
        return (
            "archivieren",
            "info",
            "Beleg im Jahrespaket archivieren und nur bei Rueckfragen vorlegen.",
        )

    def _year_correction_map_ascii_table(
        self,
        year: int,
        lines: list[TaxYearCorrectionMapLine],
        reason: str,
    ) -> str:
        header = "Jahr | Aktion | Bereich | Betrag | Ziel"
        sep = "---|---|---|---|---"
        body = [
            " | ".join(
                [
                    str(year),
                    item.action_category,
                    item.label,
                    self._fmt_eur(item.amount_eur or Decimal("0")) if item.amount_eur is not None else "-",
                    item.declaration_target[:64],
                ]
            )
            for item in lines
        ]
        return "\n".join([header, sep, *body, "", f"Hinweis: {reason}"])

    def _correction_map_ascii_table(self, maps: list[TaxYearCorrectionMap]) -> str:
        header = "Jahr | Status | Korrektur pruefen | Privat G/V | Rewards | Derivate | Steuerfrei"
        sep = "---|---|---|---|---|---|---"
        body = [
            " | ".join(
                [
                    str(item.year),
                    item.filing_status,
                    "ja" if item.amendment_review_recommended else "nein",
                    self._fmt_eur(item.taxable_private_disposals_eur),
                    self._fmt_eur(item.rewards_mining_staking_income_eur),
                    self._fmt_eur(item.derivative_pnl_eur),
                    self._fmt_eur(item.tax_free_private_disposals_eur),
                ]
            )
            for item in maps
        ]
        return "\n".join([header, sep, *body])

    def _filing_closure_ascii_table(self, rows: list[TaxYearFilingClosureRow]) -> str:
        header = (
            "Jahr | Status | Anlage SO | Rewards | Derivate | Steuerfrei | "
            "Eintragen | Beilegen | Pruefen | Abschluss"
        )
        sep = "---|---|---|---|---|---|---|---|---|---"
        body = [
            " | ".join(
                [
                    str(row.year),
                    row.filing_status,
                    self._fmt_eur(row.private_disposals_gain_loss_eur),
                    self._fmt_eur(row.rewards_mining_staking_income_eur),
                    self._fmt_eur(row.derivative_pnl_eur),
                    self._fmt_eur(row.tax_free_private_disposals_eur),
                    str(row.eintragen_count),
                    str(row.beilegen_count),
                    str(row.pruefen_count),
                    row.correction_action,
                ]
            )
            for row in rows
        ]
        return "\n".join([header, sep, *body])

    def _filing_matrix_from_readiness_snapshot(self) -> TaxYearFilingMatrix | None:
        path = self._bmf_filing_readiness_snapshot_path()
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        years_payload = payload.get("years")
        if not isinstance(years_payload, list):
            return None

        payment_rows = {
            row.year: row
            for row in self.payment_overview(
                years=[
                    int(item["year"])
                    for item in years_payload
                    if isinstance(item, dict) and item.get("year") is not None
                ]
            ).rows
        }
        rows: list[TaxYearFilingMatrixRow] = []
        for item in years_payload:
            if not isinstance(item, dict):
                continue
            year = int(item.get("year"))
            payment_row = payment_rows.get(year)
            blocking_codes = item.get("blocking_gap_codes") if isinstance(item.get("blocking_gap_codes"), list) else []
            review_codes = item.get("review_gap_codes") if isinstance(item.get("review_gap_codes"), list) else []
            appendix_items_count = int(item.get("appendix_items_count") or 0)
            appendix_manual_count = int(item.get("appendix_manual_evidence_required_count") or 0)
            derivative_pnl = Decimal(str(item.get("derivative_pnl_eur") or "0"))
            action_status: TaxYearFilingActionStatus
            if blocking_codes:
                action_status = "blocked"
            elif item.get("bmf_ready") is True and not review_codes:
                action_status = "ready"
            elif item.get("can_file_with_conservative_appendix") is True or item.get("filing_status") == "conservative_appendix":
                action_status = "conservative_ready"
            else:
                action_status = "review"
            counts = self._filing_matrix_snapshot_counts(
                payment_row=payment_row,
                appendix_items_count=appendix_items_count,
                derivative_pnl=derivative_pnl,
                review_codes_count=0 if action_status == "conservative_ready" else len(review_codes),
                blocking_codes_count=len(blocking_codes),
            )
            next_action = self._filing_matrix_snapshot_next_action(counts, action_status)
            if action_status != "conservative_ready" and item.get("next_action"):
                next_action = str(item.get("next_action"))
            taxable_private = Decimal(str(item.get("taxable_private_disposals_eur") or "0"))
            rewards_income = Decimal(str(item.get("rewards_mining_staking_income_eur") or "0"))
            row = TaxYearFilingMatrixRow(
                year=year,
                status_label=str(item.get("status_label") or item.get("filing_status") or "-"),
                export_ready=not bool(blocking_codes),
                action_status=action_status,
                next_action=next_action,
                taxable_private_disposals_eur=taxable_private,
                rewards_mining_staking_income_eur=rewards_income,
                derivative_pnl_eur=derivative_pnl,
                tax_free_private_disposals_eur=(
                    payment_row.tax_free_private_disposals_eur if payment_row is not None else Decimal("0")
                ),
                checklist_counts=counts,
                bmf_closure_appendix_status=str(item.get("appendix_status") or "") or None,
                bmf_closure_appendix_items_count=appendix_items_count,
                bmf_closure_appendix_manual_evidence_required_count=appendix_manual_count,
                warnings_count=len(review_codes),
                review_decisions_count=0,
                filing_summary_endpoint=str(item.get("filing_summary_endpoint") or f"/api/v1/tax-years/{year}/filing-summary"),
                filing_checklist_csv_endpoint=f"/api/v1/export/tax-years/{year}/filing-checklist.csv",
                evidence_package_endpoint=str(
                    item.get("evidence_package_endpoint") or f"/api/v1/export/tax-years/{year}/evidence-package.zip"
                ),
                display_line=(
                    f"{year} | {action_status} | SO {self._fmt_eur(taxable_private)} | "
                    f"Rewards {self._fmt_eur(rewards_income)} | "
                    f"Beilegen {counts.get('beilegen', 0)} | Pruefen {counts.get('pruefen', 0)}"
                ),
            )
            rows.append(row)
        return TaxYearFilingMatrix(
            generated_at=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            ready_years=[row.year for row in rows if row.action_status == "ready"],
            conservative_ready_years=[row.year for row in rows if row.action_status == "conservative_ready"],
            review_years=[row.year for row in rows if row.action_status == "review"],
            blocked_years=[row.year for row in rows if row.action_status == "blocked"],
            ascii_table=self._filing_matrix_ascii_table(rows),
            methodology=(
                "Read-only Jahresmatrix aus dem letzten BMF-Filing-Readiness-Snapshot "
                f"`{path}` plus schneller Payment-Overview. Die Matrix schreibt keine "
                "FIFO-Lots, Preise, Imports oder Review-Entscheidungen."
            ),
        )

    @staticmethod
    def _filing_matrix_snapshot_counts(
        *,
        payment_row: TaxPaymentOverviewRow | None,
        appendix_items_count: int,
        derivative_pnl: Decimal,
        review_codes_count: int,
        blocking_codes_count: int,
    ) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        if payment_row is not None:
            if payment_row.private_disposals_gain_loss_eur:
                counts["eintragen"] += 1
            else:
                counts["archivieren"] += 1
            if payment_row.rewards_mining_staking_income_eur:
                counts["eintragen"] += 1
            if payment_row.tax_free_private_disposals_eur:
                counts["archivieren"] += 1
        if derivative_pnl:
            counts["pruefen"] += 1
        if appendix_items_count:
            counts["beilegen"] += 1
        if review_codes_count or blocking_codes_count:
            counts["pruefen"] += review_codes_count + blocking_codes_count
        counts["archivieren"] += 1
        return dict(counts)

    @staticmethod
    def _filing_matrix_snapshot_next_action(
        counts: dict[str, int], action_status: TaxYearFilingActionStatus
    ) -> str:
        if action_status == "blocked":
            return "Blockierende Punkte vor Export oder Abgabe klaeren."
        if action_status == "conservative_ready":
            return "Konservativ belegbar: Herkunftsbeilage und Jahrespaket mit abgeben."
        if counts.get("pruefen", 0):
            return f"{counts.get('pruefen', 0)} Pruefpunkt(e) fachlich klaeren."
        if counts.get("beilegen", 0):
            return "Herkunftsbeilage und Jahrespaket bereithalten."
        if counts.get("eintragen", 0):
            return "Eintragungswerte uebernehmen und Belege archivieren."
        return "Jahrespaket archivieren; keine V2-Eingabebetraege."

    def _bmf_filing_readiness_snapshot_path(self) -> Path | None:
        candidates = [
            self.store.path.parent / "var/bmf_filing_readiness/latest_bmf_filing_readiness_2021_2025.json",
            self.store.path.parent.parent / "var/bmf_filing_readiness/latest_bmf_filing_readiness_2021_2025.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _filing_matrix_action_status(
        summary: TaxYearFilingSummary, counts: dict[str, int]
    ) -> TaxYearFilingActionStatus:
        if not summary.export_ready:
            return "blocked"
        if summary.can_file_with_conservative_appendix and not summary.bmf_closure_appendix_manual_evidence_required_count:
            return "conservative_ready"
        if counts.get("pruefen", 0) or summary.warnings:
            return "review"
        return "ready"

    @staticmethod
    def _filing_matrix_next_action(
        summary: TaxYearFilingSummary,
        counts: dict[str, int],
        action_status: TaxYearFilingActionStatus,
    ) -> str:
        if action_status == "blocked":
            return "Blockierende Punkte vor Export oder Abgabe klaeren."
        if action_status == "conservative_ready":
            return "Konservativ belegbar: Herkunftsbeilage und Jahrespaket mit abgeben."
        if counts.get("pruefen", 0):
            return f"{counts.get('pruefen', 0)} Pruefpunkt(e) fachlich klaeren."
        if summary.bmf_closure_appendix_items_count:
            return "Herkunftsbeilage und Jahrespaket bereithalten."
        if counts.get("eintragen", 0):
            return "Eintragungswerte uebernehmen und Belege archivieren."
        return "Jahrespaket archivieren; keine V2-Eingabebetraege."

    def _filing_matrix_display_line(
        self,
        summary: TaxYearFilingSummary,
        counts: dict[str, int],
        action_status: TaxYearFilingActionStatus,
    ) -> str:
        return (
            f"{summary.year} | {action_status} | SO {self._fmt_eur(summary.taxable_private_disposals_eur)} | "
            f"Rewards {self._fmt_eur(summary.rewards_mining_staking_income_eur)} | "
            f"Beilegen {counts.get('beilegen', 0)} | Pruefen {counts.get('pruefen', 0)}"
        )

    def _filing_matrix_ascii_table(self, rows: list[TaxYearFilingMatrixRow]) -> str:
        table_rows = [["Jahr", "Status", "Anlage SO", "Rewards", "Beilegen", "Pruefen", "Naechster Schritt"]]
        for row in rows:
            table_rows.append(
                [
                    str(row.year),
                    row.action_status,
                    self._fmt_eur(row.taxable_private_disposals_eur),
                    self._fmt_eur(row.rewards_mining_staking_income_eur),
                    str(row.checklist_counts.get("beilegen", 0)),
                    str(row.checklist_counts.get("pruefen", 0)),
                    row.next_action,
                ]
            )
        widths = [max(len(str(row[index])) for row in table_rows) for index in range(len(table_rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(table_rows[0]), sep, *(fmt(row) for row in table_rows[1:]), sep])

    def _filing_ascii_table(self, year: int, lines: list[TaxYearFilingSummaryLine]) -> str:
        rows = [["Jahr", "Bereich", "Betrag", "Steuerliche Behandlung", "Ziel"]]
        for line in lines:
            rows.append(
                [
                    str(year),
                    line.label,
                    self._fmt_eur(line.amount_eur) if line.amount_eur is not None else "-",
                    line.tax_treatment,
                    line.declaration_target,
                ]
            )
        widths = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(rows[0]), sep, *(fmt(row) for row in rows[1:]), sep])

    def _reward_trading_separation_ascii_table(
        self, rows: list[TaxRewardTradingSeparationRow]
    ) -> str:
        table_rows = [
            [
                "Jahr",
                "Asset",
                "Reward/Einnahme",
                "Reward Events",
                "Handel steuerpfl.",
                "Handel steuerfrei",
                "FIFO Zeilen",
            ]
        ]
        for row in rows:
            table_rows.append(
                [
                    str(row.year),
                    row.asset,
                    self._fmt_eur(row.reward_income_eur),
                    str(row.reward_events_count),
                    self._fmt_eur(row.trade_taxable_gain_loss_eur),
                    self._fmt_eur(row.trade_tax_free_gain_loss_eur),
                    str(row.trade_taxable_lines_count + row.trade_tax_free_lines_count),
                ]
            )
        if len(table_rows) == 1:
            table_rows.append(
                [
                    "-",
                    "-",
                    self._fmt_eur(Decimal("0")),
                    "0",
                    self._fmt_eur(Decimal("0")),
                    self._fmt_eur(Decimal("0")),
                    "0",
                ]
            )
        widths = [max(len(str(row[index])) for row in table_rows) for index in range(len(table_rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(table_rows[0]), sep, *(fmt(row) for row in table_rows[1:]), sep])

    def _gain_loss_reality_ascii_table(self, rows: list[TaxYearGainLossRealityAssetRow]) -> str:
        table_rows = [
            [
                "Asset",
                "Realisiert steuerpfl.",
                "Steuerfrei",
                "Heute offen",
                "Offene Kosten",
                "Unrealisiert",
                "Nicht geltend",
            ]
        ]
        for row in rows:
            table_rows.append(
                [
                    row.asset,
                    self._fmt_eur(row.realized_taxable_gain_loss_eur),
                    self._fmt_eur(row.realized_tax_free_gain_loss_eur),
                    self._fmt_eur(row.open_current_value_eur),
                    self._fmt_eur(row.open_cost_basis_eur),
                    self._fmt_eur(row.open_unrealized_gain_loss_eur),
                    self._fmt_eur(row.potential_loss_not_realized_eur),
                ]
            )
        if len(table_rows) == 1:
            table_rows.append(["-", self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0"))])
        widths = [max(len(str(row[index])) for row in table_rows) for index in range(len(table_rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(table_rows[0]), sep, *(fmt(row) for row in table_rows[1:]), sep])

    def _gain_evidence_ascii_table(self, rows: list[TaxYearGainEvidenceLine]) -> str:
        table_rows = [["Risiko", "Asset", "G/V", "Kosten", "Erloes", "Erwerb Roh", "Verkauf Roh", "Bewertung"]]
        for row in rows:
            table_rows.append(
                [
                    row.risk_level,
                    row.asset,
                    self._fmt_eur(row.gain_loss_eur),
                    self._fmt_eur(row.acquisition_cost_eur),
                    self._fmt_eur(row.disposal_proceeds_eur),
                    row.acquisition_raw_evidence,
                    row.disposal_raw_evidence,
                    row.valuation_path,
                ]
            )
        if len(table_rows) == 1:
            table_rows.append(["-", "-", self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), "-", "-", "-"])
        widths = [max(len(str(row[index])) for row in table_rows) for index in range(len(table_rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(table_rows[0]), sep, *(fmt(row) for row in table_rows[1:]), sep])

    @staticmethod
    def _gain_evidence_valuation_path(acquisition_quote_asset: str | None, disposal_quote_asset: str | None) -> str:
        parts: list[str] = []
        if acquisition_quote_asset:
            parts.append(f"acq_quote={acquisition_quote_asset.upper()}")
        else:
            parts.append("acq_price_lookup_or_reward_basis")
        if disposal_quote_asset:
            parts.append(f"disp_quote={disposal_quote_asset.upper()}")
        else:
            parts.append("disp_price_lookup")
        return " | ".join(parts)

    def _gain_evidence_price_check(
        self,
        *,
        price_lookup: HistoricalPriceLookup,
        quote_asset: str | None,
        quote_quantity: Decimal | None,
        event_quantity: Decimal | None = None,
        fallback_asset: str,
        fallback_quantity: Decimal,
        event_time: datetime,
        actual_value: Decimal,
    ) -> dict[str, object]:
        price_asset = str(quote_asset or fallback_asset).upper()
        fallback_asset_normalized = str(fallback_asset).upper()
        if quote_quantity is not None and price_asset != fallback_asset_normalized:
            price_quantity = abs(quote_quantity)
            if event_quantity:
                event_abs = abs(event_quantity)
                line_abs = abs(fallback_quantity)
                if event_abs and line_abs and line_abs < event_abs:
                    price_quantity = price_quantity * line_abs / event_abs
        else:
            price_quantity = abs(fallback_quantity)
        price_point = price_lookup.at_or_before(price_asset, event_time)
        if price_point is None:
            return {
                "price_asset": price_asset,
                "price_eur": None,
                "price_source": None,
                "priced_at": None,
                "price_age_days": None,
                "expected_value": None,
                "delta_eur": None,
                "delta_pct": None,
            }
        expected_value = price_quantity * price_point.price_eur
        delta_eur = actual_value - expected_value
        delta_pct = abs(delta_eur) / expected_value * Decimal("100") if expected_value else None
        normalized_event_time = event_time if event_time.tzinfo is not None else event_time.replace(tzinfo=timezone.utc)
        normalized_price_time = (
            price_point.priced_at
            if price_point.priced_at.tzinfo is not None
            else price_point.priced_at.replace(tzinfo=timezone.utc)
        )
        return {
            "price_asset": price_asset,
            "price_eur": price_point.price_eur,
            "price_source": price_point.source,
            "priced_at": price_point.priced_at.isoformat(),
            "price_age_days": max((normalized_event_time.date() - normalized_price_time.date()).days, 0),
            "expected_value": expected_value,
            "delta_eur": delta_eur,
            "delta_pct": delta_pct,
        }

    @staticmethod
    def _gain_evidence_reasons(
        *,
        acquisition_raw_object_id: str | None,
        disposal_raw_object_id: str | None,
        acquisition_quote_asset: str | None,
        disposal_quote_asset: str | None,
        acquisition_source: str | None,
        disposal_source: str | None,
        gain_loss_ratio_pct: Decimal,
        acquisition_price_delta_pct: Decimal | None,
        disposal_price_delta_pct: Decimal | None,
        acquisition_price_age_days: int | None,
        disposal_price_age_days: int | None,
        acquisition_price_source: str | None,
        disposal_price_source: str | None,
    ) -> list[str]:
        reasons: list[str] = []
        if not acquisition_raw_object_id:
            reasons.append("acquisition_raw_missing")
        if not disposal_raw_object_id:
            reasons.append("disposal_raw_missing")
        if not acquisition_price_source:
            reasons.append("acquisition_price_missing")
        if not disposal_price_source:
            reasons.append("disposal_price_missing")
        quote_assets = {str(item).upper() for item in (acquisition_quote_asset, disposal_quote_asset) if item}
        if quote_assets and not quote_assets.issubset({"EUR"}):
            reasons.append("non_eur_quote_or_stablecoin_valuation")
        if abs(gain_loss_ratio_pct) >= Decimal("50"):
            reasons.append("large_gain_loss_ratio")
        if acquisition_source and disposal_source and acquisition_source != disposal_source:
            reasons.append("cross_source_fifo")
        if acquisition_price_delta_pct is not None and acquisition_price_delta_pct > Decimal("0.5"):
            reasons.append("acquisition_price_delta_review")
        if disposal_price_delta_pct is not None and disposal_price_delta_pct > Decimal("0.5"):
            reasons.append("disposal_price_delta_review")
        if acquisition_price_age_days is not None and acquisition_price_age_days > 7:
            reasons.append("acquisition_stale_price")
        if disposal_price_age_days is not None and disposal_price_age_days > 7:
            reasons.append("disposal_stale_price")
        if acquisition_price_source and HistoricalPriceLookup.is_derived_source(acquisition_price_source):
            reasons.append("acquisition_derived_price")
        if disposal_price_source and HistoricalPriceLookup.is_derived_source(disposal_price_source):
            reasons.append("disposal_derived_price")
        return reasons or ["evidence_path_present"]

    @staticmethod
    def _gain_evidence_risk(reasons: list[str]) -> Literal["ok", "review", "high"]:
        high = {"acquisition_raw_missing", "disposal_raw_missing", "acquisition_price_missing", "disposal_price_missing"}
        if any(reason in high for reason in reasons):
            return "high"
        review = {"non_eur_quote_or_stablecoin_valuation", "large_gain_loss_ratio", "cross_source_fifo"}
        if any(reason in review for reason in reasons):
            return "review"
        return "ok"

    @staticmethod
    def _decimal_or_zero(value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal("0")

    def _gain_evidence_delta_decision(
        self,
        *,
        acquisition_quote_asset: str | None,
        disposal_quote_asset: str | None,
        acquisition_source: str | None,
        disposal_source: str | None,
        acquisition_price: dict[str, object],
        disposal_price: dict[str, object],
        reasons: list[str],
    ) -> tuple[Decimal, Decimal, str, str, str]:
        absolute_delta = abs(self._decimal_or_zero(acquisition_price.get("delta_eur"))) + abs(
            self._decimal_or_zero(disposal_price.get("delta_eur"))
        )
        max_delta_pct = max(
            self._decimal_or_zero(acquisition_price.get("delta_pct")),
            self._decimal_or_zero(disposal_price.get("delta_pct")),
        )
        quote_assets = {
            str(asset).upper()
            for asset in (acquisition_quote_asset, disposal_quote_asset)
            if asset
        }
        non_eur_quotes = {asset for asset in quote_assets if asset != "EUR"}
        stablecoin_quotes = non_eur_quotes & STABLECOIN_LIKE_ASSETS
        token_quotes = non_eur_quotes - STABLECOIN_LIKE_ASSETS
        price_sources = {
            str(source)
            for source in (acquisition_price.get("price_source"), disposal_price.get("price_source"))
            if source
        }

        if "acquisition_price_missing" in reasons or "disposal_price_missing" in reasons:
            return (
                absolute_delta,
                max_delta_pct,
                "missing_price_evidence",
                "Mindestens eine Seite der FIFO-Zeile hat keinen historischen EUR-Preis.",
                "Historischen Tagespreis oder Rohbeleg fuer Erwerb und Veraeusserung nachziehen; erst danach steuerlich final bewerten.",
            )
        if absolute_delta < Decimal("0.01") and max_delta_pct <= Decimal("0.5"):
            return (
                absolute_delta,
                max_delta_pct,
                "no_material_delta",
                "Tax-Line-Wert und erwarteter Preiswert stimmen innerhalb der Materialitaet ueberein.",
                "Kein manueller Eingriff noetig; Belegpfad archivieren.",
            )
        if stablecoin_quotes:
            return (
                absolute_delta,
                max_delta_pct,
                "stablecoin_fx_or_market_delta",
                "Die Abweichung entsteht in einer Stablecoin-Quote; meist USD/EUR-FX, Tageskurs oder Zeitstempelversatz.",
                "Quote-Menge, Stablecoin-Mint und USD/EUR-Preisquelle am exakten UTC-Zeitpunkt pruefen.",
            )
        if token_quotes:
            return (
                absolute_delta,
                max_delta_pct,
                "dex_route_or_token_quote_delta",
                "Die Bewertung nutzt ein Token-Quote-Bein aus einem Swap oder DEX-Route statt direktem EUR.",
                "On-chain Swap-Route mit Token-Transfers, Quote-Mint und Gegenwert aus Solscan/Helius/Jupiter abgleichen.",
            )
        if acquisition_source and disposal_source and acquisition_source != disposal_source:
            return (
                absolute_delta,
                max_delta_pct,
                "cross_source_fifo_context",
                "Die FIFO-Kette verbindet unterschiedliche Quellen; Preisdelta kann aus Transfer-/Exchange-Kontext stammen.",
                "Transferneutralitaet und Besitzkette zwischen den Quellen dokumentieren, danach FIFO-Vererbung bestaetigen.",
            )
        if any(HistoricalPriceLookup.is_derived_source(source) for source in price_sources):
            return (
                absolute_delta,
                max_delta_pct,
                "derived_price_review",
                "Mindestens ein Preis ist abgeleitet; die Tax-Line ist plausibel, aber nicht primaer belegt.",
                "Abgeleitete Preisquelle gegen Primaerquelle oder Exchange-/Explorer-Rohdaten gegenpruefen.",
            )
        return (
            absolute_delta,
            max_delta_pct,
            "normalizer_review",
            "Es liegt eine materielle Preisabweichung ohne eindeutige Quote- oder Quellenursache vor.",
            "Raw-Object, Normalizer-Mapping, quote_asset und quote_quantity der betroffenen Events pruefen.",
        )

    def _gain_evidence_delta_groups(
        self,
        year: int,
        lines: list[TaxYearGainEvidenceLine],
    ) -> list[TaxYearGainEvidenceDeltaGroup]:
        grouped: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "risk_level": "ok",
                "lines_count": 0,
                "gain_loss_eur": Decimal("0"),
                "absolute_delta_eur": Decimal("0"),
                "open_delta_eur": Decimal("0"),
                "max_delta_pct": Decimal("0"),
                "assets": set(),
                "quote_assets": set(),
                "sources": set(),
                "explanation": "",
                "recommended_action": "",
            }
        )
        risk_rank = {"ok": 0, "review": 1, "high": 2}
        for line in lines:
            if line.delta_classification == "no_material_delta":
                continue
            item = grouped[line.delta_classification]
            item["lines_count"] = int(item["lines_count"]) + 1
            item["gain_loss_eur"] = item["gain_loss_eur"] + line.gain_loss_eur  # type: ignore[operator]
            item["absolute_delta_eur"] = item["absolute_delta_eur"] + line.absolute_price_delta_eur  # type: ignore[operator]
            item["open_delta_eur"] = item["open_delta_eur"] + line.open_price_delta_eur  # type: ignore[operator]
            item["max_delta_pct"] = max(item["max_delta_pct"], line.max_price_delta_pct)  # type: ignore[arg-type]
            item["assets"].add(line.asset.upper())  # type: ignore[union-attr]
            for quote_asset in (line.acquisition_quote_asset, line.disposal_quote_asset):
                if quote_asset:
                    item["quote_assets"].add(quote_asset.upper())  # type: ignore[union-attr]
            for source in (line.acquisition_source, line.disposal_source):
                if source:
                    item["sources"].add(source)  # type: ignore[union-attr]
            item["explanation"] = line.delta_explanation
            item["recommended_action"] = line.delta_recommended_action
            if risk_rank[line.risk_level] > risk_rank[str(item["risk_level"])]:
                item["risk_level"] = line.risk_level

        groups = [
            TaxYearGainEvidenceDeltaGroup(
                year=year,
                classification=classification,
                risk_level=item["risk_level"],  # type: ignore[arg-type]
                lines_count=int(item["lines_count"]),
                gain_loss_eur=item["gain_loss_eur"],  # type: ignore[arg-type]
                absolute_delta_eur=item["absolute_delta_eur"],  # type: ignore[arg-type]
                open_delta_eur=item["open_delta_eur"],  # type: ignore[arg-type]
                max_delta_pct=item["max_delta_pct"],  # type: ignore[arg-type]
                assets=sorted(item["assets"]),  # type: ignore[arg-type]
                quote_assets=sorted(item["quote_assets"]),  # type: ignore[arg-type]
                sources=sorted(item["sources"]),  # type: ignore[arg-type]
                explanation=str(item["explanation"]),
                recommended_action=str(item["recommended_action"]),
            )
            for classification, item in grouped.items()
        ]
        groups.sort(key=lambda group: (group.risk_level != "high", -group.absolute_delta_eur))
        return groups

    @staticmethod
    def _gain_evidence_side_diagnosis(
        *,
        delta_eur: Decimal,
        delta_pct: Decimal,
        quote_asset: str | None,
        quote_quantity: Decimal | None,
        price_source: str | None,
        event_split_count: int,
    ) -> str:
        if abs(delta_eur) < Decimal("0.01") and delta_pct <= Decimal("0.5"):
            return "ok"
        if not price_source:
            return "missing_price_evidence"
        if event_split_count > 1 and quote_quantity is not None:
            return "quote_allocation_or_split_line"
        quote = quote_asset.upper() if quote_asset else None
        if quote in STABLECOIN_LIKE_ASSETS:
            return "stablecoin_fx_or_market_delta"
        if quote and quote != "EUR":
            return "dex_route_or_token_quote_delta"
        if HistoricalPriceLookup.is_derived_source(price_source):
            return "derived_price_review"
        return "normalizer_review"

    @staticmethod
    def _gain_evidence_dominant_side(
        acquisition_delta: Decimal,
        disposal_delta: Decimal,
    ) -> Literal["acquisition", "disposal", "both", "none"]:
        acq = abs(acquisition_delta)
        disp = abs(disposal_delta)
        if acq < Decimal("0.01") and disp < Decimal("0.01"):
            return "none"
        if acq and disp and min(acq, disp) / max(acq, disp) >= Decimal("0.25"):
            return "both"
        return "acquisition" if acq > disp else "disposal"

    @staticmethod
    def _gain_evidence_root_cause(acquisition_diagnosis: str, disposal_diagnosis: str) -> str:
        diagnoses = [item for item in (acquisition_diagnosis, disposal_diagnosis) if item != "ok"]
        if not diagnoses:
            return "no_material_delta"
        if "quote_allocation_or_split_line" in diagnoses:
            return "quote_allocation_or_split_line"
        if "missing_price_evidence" in diagnoses:
            return "missing_price_evidence"
        if "stablecoin_fx_or_market_delta" in diagnoses:
            return "stablecoin_fx_or_market_delta"
        if "dex_route_or_token_quote_delta" in diagnoses:
            return "dex_route_or_token_quote_delta"
        if "derived_price_review" in diagnoses:
            return "derived_price_review"
        return "normalizer_review"

    @staticmethod
    def _gain_evidence_root_cause_text(root_cause: str) -> tuple[str, str]:
        if root_cause == "quote_allocation_or_split_line":
            return (
                "Dasselbe Quote-Bein eines Swap-/Trade-Events erscheint in mehreren FIFO-Zeilen; der erwartete Quote-Wert ist dadurch vermutlich nicht proportional auf die Teilzeilen verteilt.",
                "Event-Rohdaten und Normalizer-Allocation pruefen: Quote-Menge muss je FIFO-Teilzeile anteilig oder ueber das Event aggregiert bewertet werden.",
            )
        if root_cause == "stablecoin_fx_or_market_delta":
            return (
                "Die Abweichung sitzt in einem Stablecoin-Bein; wahrscheinlich sind USD/EUR-Kurs, Tageszeitpunkt oder Stablecoin-Preisquelle massgeblich.",
                "USDC/USDT-Mint, Quote-Menge, UTC-Zeitpunkt und USD/EUR-FX-Quelle gegen den Rohbeleg abgleichen.",
            )
        if root_cause == "dex_route_or_token_quote_delta":
            return (
                "Die Abweichung sitzt in einem Token-Quote-Bein einer DEX-/Swap-Route.",
                "Route mit On-chain Transfers, Token-Mints und Jupiter/Solscan/Helius-Belegen gegenpruefen.",
            )
        if root_cause == "missing_price_evidence":
            return (
                "Mindestens eine Seite hat keinen belastbaren historischen EUR-Preis.",
                "Preisquelle nachziehen oder Rohbeleg mit EUR-Gegenwert dokumentieren.",
            )
        if root_cause == "derived_price_review":
            return (
                "Mindestens eine Seite nutzt einen abgeleiteten Preis statt eines primaeren Belegs.",
                "Abgeleitete Preisquelle mit Exchange- oder Explorer-Rohdaten plausibilisieren.",
            )
        return (
            "Die Abweichung passt zu keinem bekannten Muster und muss im Normalizer-Mapping geprueft werden.",
            "Raw-Object, quote_asset, quote_quantity und Event-Typ der betroffenen Seite pruefen.",
        )

    def _gain_evidence_split_delta_by_disposal_event(
        self,
        year: int,
        *,
        limit: int = 200,
    ) -> tuple[dict[str, Decimal], dict[str, int]]:
        review = self.gain_evidence_review(year, limit=max(1, min(limit, 500)))
        disposal_counts: dict[str, int] = defaultdict(int)
        for line in review.lines:
            if line.disposal_event_id:
                disposal_counts[line.disposal_event_id] += 1
        split_delta_by_event: dict[str, Decimal] = defaultdict(Decimal)
        split_count_by_event: dict[str, int] = defaultdict(int)
        for line in review.lines:
            if not line.disposal_event_id:
                continue
            disposal_delta = line.disposal_proceeds_delta_eur or Decimal("0")
            disposal_delta_pct = line.disposal_proceeds_delta_pct or Decimal("0")
            diagnosis = self._gain_evidence_side_diagnosis(
                delta_eur=disposal_delta,
                delta_pct=disposal_delta_pct,
                quote_asset=line.disposal_quote_asset,
                quote_quantity=line.disposal_quote_quantity,
                price_source=line.disposal_price_source,
                event_split_count=disposal_counts.get(line.disposal_event_id, 0),
            )
            if diagnosis == "quote_allocation_or_split_line":
                split_delta_by_event[line.disposal_event_id] += line.absolute_price_delta_eur
                split_count_by_event[line.disposal_event_id] += 1
        return split_delta_by_event, split_count_by_event

    def gain_evidence_price_delta_drilldown(
        self,
        year: int,
        *,
        classification: str | None = None,
        limit: int = 200,
    ) -> TaxYearGainEvidencePriceDeltaDrilldown:
        review = self.gain_evidence_review(year, limit=max(1, min(limit, 500)))
        selected = [
            line
            for line in review.lines
            if line.delta_classification != "no_material_delta"
            and (classification is None or line.delta_classification == classification)
        ]
        acquisition_counts: dict[str, int] = defaultdict(int)
        disposal_counts: dict[str, int] = defaultdict(int)
        for line in selected:
            if line.acquisition_event_id:
                acquisition_counts[line.acquisition_event_id] += 1
            if line.disposal_event_id:
                disposal_counts[line.disposal_event_id] += 1
        event_level_by_id = self._gain_evidence_event_delta_lines_by_id(
            year,
            limit=max(1, min(limit, 500)),
            include_split_delta=False,
        )
        acquisition_event_level_by_id = self._gain_evidence_acquisition_event_delta_lines_by_id(
            year,
            limit=max(1, min(limit, 500)),
        )

        rows: list[TaxYearGainEvidencePriceDeltaLine] = []
        root_counts: dict[str, int] = defaultdict(int)
        dominant_counts = {"acquisition": 0, "disposal": 0, "both": 0, "none": 0}
        split_line_review_count = 0
        event_level_reconciled_count = 0
        event_level_review_count = 0
        event_level_unchecked_count = 0
        for line in selected:
            acquisition_delta = line.acquisition_cost_delta_eur or Decimal("0")
            disposal_delta = line.disposal_proceeds_delta_eur or Decimal("0")
            acquisition_delta_pct = line.acquisition_cost_delta_pct or Decimal("0")
            disposal_delta_pct = line.disposal_proceeds_delta_pct or Decimal("0")
            acquisition_split_count = acquisition_counts.get(line.acquisition_event_id or "", 0)
            disposal_split_count = disposal_counts.get(line.disposal_event_id or "", 0)
            acquisition_diagnosis = self._gain_evidence_side_diagnosis(
                delta_eur=acquisition_delta,
                delta_pct=acquisition_delta_pct,
                quote_asset=line.acquisition_quote_asset,
                quote_quantity=line.acquisition_quote_quantity,
                price_source=line.acquisition_price_source,
                event_split_count=acquisition_split_count,
            )
            disposal_diagnosis = self._gain_evidence_side_diagnosis(
                delta_eur=disposal_delta,
                delta_pct=disposal_delta_pct,
                quote_asset=line.disposal_quote_asset,
                quote_quantity=line.disposal_quote_quantity,
                price_source=line.disposal_price_source,
                event_split_count=disposal_split_count,
            )
            dominant_side = self._gain_evidence_dominant_side(acquisition_delta, disposal_delta)
            root_cause = self._gain_evidence_root_cause(acquisition_diagnosis, disposal_diagnosis)
            explanation, action = self._gain_evidence_root_cause_text(root_cause)
            event_level = event_level_by_id.get(line.disposal_event_id or "")
            if event_level and event_level.status == "event_level_ok":
                event_level_reconciled_count += 1
                if root_cause == "quote_allocation_or_split_line":
                    explanation = (
                        "Event-Level ist plausibel; dieses Delta ist ein FIFO-Teilzeilen-/Quote-Allocation-Artefakt."
                    )
                    action = "Nicht als echten zusaetzlichen Gewinn werten; Event-Level-Beleg archivieren."
            elif event_level and event_level.status == "event_level_review":
                event_level_review_count += 1
            else:
                event_level_unchecked_count += 1
            root_counts[root_cause] += 1
            dominant_counts[dominant_side] += 1
            if root_cause == "quote_allocation_or_split_line":
                split_line_review_count += 1
            rows.append(
                TaxYearGainEvidencePriceDeltaLine(
                    year=year,
                    tax_line_id=line.tax_line_id,
                    asset=line.asset,
                    acquired_at=line.acquired_at,
                    disposed_at=line.disposed_at,
                    gain_loss_eur=line.gain_loss_eur,
                    classification=line.delta_classification,
                    dominant_side=dominant_side,
                    acquisition_delta_eur=acquisition_delta,
                    acquisition_delta_pct=acquisition_delta_pct,
                    disposal_delta_eur=disposal_delta,
                    disposal_delta_pct=disposal_delta_pct,
                    absolute_delta_eur=line.absolute_price_delta_eur,
                    max_delta_pct=line.max_price_delta_pct,
                    acquisition_quote_asset=line.acquisition_quote_asset,
                    acquisition_quote_quantity=line.acquisition_quote_quantity,
                    acquisition_event_id=line.acquisition_event_id,
                    acquisition_event_split_count=acquisition_split_count,
                    acquisition_side_diagnosis=acquisition_diagnosis,
                    disposal_quote_asset=line.disposal_quote_asset,
                    disposal_quote_quantity=line.disposal_quote_quantity,
                    disposal_event_id=line.disposal_event_id,
                    disposal_event_split_count=disposal_split_count,
                    disposal_side_diagnosis=disposal_diagnosis,
                    event_level_status=event_level.status if event_level else None,
                    event_level_delta_eur=event_level.event_delta_eur if event_level else None,
                    event_level_delta_pct=event_level.event_delta_pct if event_level else None,
                    event_level_explanation=event_level.explanation if event_level else None,
                    root_cause=root_cause,
                    explanation=explanation,
                    recommended_action=action,
                    asset_fifo_drilldown_endpoint=line.asset_fifo_drilldown_endpoint,
                )
            )
        rows.sort(key=lambda row: row.absolute_delta_eur, reverse=True)
        return TaxYearGainEvidencePriceDeltaDrilldown(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            classification_filter=classification,
            lines_count=len(rows),
            gain_loss_eur=sum((row.gain_loss_eur for row in rows), Decimal("0")),
            absolute_delta_eur=sum((row.absolute_delta_eur for row in rows), Decimal("0")),
            acquisition_delta_eur=sum((abs(row.acquisition_delta_eur) for row in rows), Decimal("0")),
            disposal_delta_eur=sum((abs(row.disposal_delta_eur) for row in rows), Decimal("0")),
            dominant_acquisition_count=dominant_counts["acquisition"],
            dominant_disposal_count=dominant_counts["disposal"],
            dominant_both_count=dominant_counts["both"],
            split_line_review_count=split_line_review_count,
            root_cause_counts=dict(sorted(root_counts.items())),
            event_level_reconciled_count=event_level_reconciled_count,
            event_level_review_count=event_level_review_count,
            event_level_unchecked_count=event_level_unchecked_count,
            lines=rows,
            caveats=[
                "Read-only Drilldown: erklaert Preisdelta-Ursachen, korrigiert aber keine Tax-Lines.",
                "Split-Line-Hinweise bedeuten: ein Event kann mehrere FIFO-Zeilen erzeugen; Quote-Werte muessen dann proportional oder aggregiert betrachtet werden.",
            ],
            methodology=(
                "Der Drilldown nimmt die bestehenden Gain-Evidence-Zeilen, zaehlt wiederverwendete Erwerbs-/Disposal-Events "
                "und diagnostiziert jede Seite separat. Grosse Deltas bei mehrfach genutzten Event-Quotes werden als "
                "quote_allocation_or_split_line markiert, weil dort die wahrscheinlichste Ursache eine nicht anteilige "
                "Quote-Bewertung pro FIFO-Teilzeile ist."
            ),
        )

    @staticmethod
    def _gain_evidence_event_delta_text(
        *,
        status: str,
        split_line_absolute_delta_eur: Decimal,
        event_delta_eur: Decimal | None,
    ) -> tuple[str, str]:
        if status == "missing_price_evidence":
            return (
                "Der Event kann nicht auf Event-Level bewertet werden, weil der historische Preis fehlt.",
                "Historischen Preis fuer das Quote-Asset am UTC-Zeitpunkt nachziehen.",
            )
        if status == "event_level_ok" and split_line_absolute_delta_eur > Decimal("1"):
            return (
                "Das Event ist aggregiert plausibel; die hohen Teilzeilen-Deltas entstehen durch FIFO-Splits desselben Quote-Beins.",
                "Teilzeilen-Deltas nicht als eigenstaendigen Steuerfehler werten; Event-Level-Beleg im Jahrespaket archivieren.",
            )
        if status == "event_level_ok":
            return (
                "Das Event ist aggregiert plausibel und die Teilzeilen-Deltas sind nicht materiell.",
                "Kein Korrekturbedarf; Event-Beleg archivieren.",
            )
        return (
            "Auch aggregiert weicht der Tax-Line-Erloes vom Event-Quote-Wert ab.",
            "Normalizer-Mapping, Quote-Menge, Preisquelle und Rohbeleg des gesamten Events pruefen.",
        )

    def _gain_evidence_event_delta_lines_by_id(
        self,
        year: int,
        *,
        limit: int = 200,
        include_split_delta: bool = True,
    ) -> dict[str, TaxYearGainEvidenceEventDeltaLine]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    de.event_id,
                    min(l.disposed_at) as disposed_at,
                    any_value(de.source) as source,
                    any_value(de.event_type) as event_type,
                    any_value(de.asset) as event_asset,
                    any_value(de.quantity) as event_quantity,
                    any_value(de.quote_asset) as quote_asset,
                    any_value(de.quote_quantity) as quote_quantity,
                    count(*)::integer as tax_line_count,
                    string_agg(distinct l.asset, ',') as assets,
                    coalesce(sum(abs(l.quantity)), 0) as taxable_disposed_quantity,
                    coalesce(sum(l.disposal_proceeds_eur), 0) as actual_proceeds_eur
                from tax_lines l
                join canonical_events de on de.event_id = l.source_event_id
                where date_part('year', l.disposed_at)::integer = ?
                  and l.holding_days <= 365
                  and de.event_id is not null
                  and de.quote_asset is not null
                  and de.quote_quantity is not null
                group by de.event_id
                order by count(*) desc, abs(sum(l.disposal_proceeds_eur)) desc, de.event_id
                limit ?
                """,
                [year, max(1, min(limit, 500))],
            ).fetchall()

        if include_split_delta:
            split_delta_by_event, split_count_by_event = self._gain_evidence_split_delta_by_disposal_event(
                year,
                limit=limit,
            )
        else:
            split_delta_by_event, split_count_by_event = defaultdict(Decimal), defaultdict(int)

        price_lookup = HistoricalPriceLookup(self.store)
        lines: list[TaxYearGainEvidenceEventDeltaLine] = []
        for (
            event_id,
            disposed_at,
            source,
            event_type,
            event_asset,
            event_quantity,
            quote_asset,
            quote_quantity,
            tax_line_count,
            assets,
            taxable_disposed_quantity,
            actual_proceeds_eur,
        ) in rows:
            event_asset_key = str(event_asset or "").upper()
            quote_asset_key = str(quote_asset or "").upper()
            asset_set = {asset.strip().upper() for asset in str(assets or "").split(",") if asset}
            if event_asset_key in asset_set and event_quantity is not None and event_quantity < 0:
                total_disposed_quantity = abs(event_quantity)
            elif quote_asset_key in asset_set and quote_quantity is not None:
                total_disposed_quantity = abs(quote_quantity)
            else:
                total_disposed_quantity = taxable_disposed_quantity or None
            taxable_fraction = (
                taxable_disposed_quantity / total_disposed_quantity
                if total_disposed_quantity and taxable_disposed_quantity <= total_disposed_quantity
                else Decimal("1")
            )
            price = self._gain_evidence_price_check(
                price_lookup=price_lookup,
                quote_asset=quote_asset,
                quote_quantity=quote_quantity,
                fallback_asset=quote_asset,
                fallback_quantity=abs(quote_quantity or Decimal("0")),
                event_time=disposed_at,
                actual_value=actual_proceeds_eur or Decimal("0"),
            )
            event_total_expected = price["expected_value"]
            expected = event_total_expected * taxable_fraction if isinstance(event_total_expected, Decimal) else None
            delta = (actual_proceeds_eur or Decimal("0")) - expected if expected is not None else None
            delta_pct = abs(delta) / expected * Decimal("100") if expected else None
            if price["price_source"] is None:
                status: Literal["event_level_ok", "event_level_review", "missing_price_evidence"] = "missing_price_evidence"
            elif delta is not None and (abs(delta) < Decimal("0.01") or (delta_pct is not None and delta_pct <= Decimal("0.5"))):
                status = "event_level_ok"
            else:
                status = "event_level_review"
            split_delta = split_delta_by_event.get(event_id, Decimal("0"))
            explanation, action = self._gain_evidence_event_delta_text(
                status=status,
                split_line_absolute_delta_eur=split_delta,
                event_delta_eur=delta if isinstance(delta, Decimal) else None,
            )
            lines.append(
                TaxYearGainEvidenceEventDeltaLine(
                    year=year,
                    disposal_event_id=event_id,
                    disposed_at=disposed_at.isoformat(),
                    source=source,
                    event_type=event_type,
                    event_asset=event_asset,
                    event_quantity=event_quantity,
                    quote_asset=quote_asset,
                    quote_quantity=quote_quantity,
                    price_asset=price["price_asset"],
                    price_eur=price["price_eur"],
                    price_source=price["price_source"],
                    priced_at=price["priced_at"],
                    price_age_days=price["price_age_days"],
                    tax_line_count=int(tax_line_count or 0),
                    assets=sorted(str(assets or "").split(",")) if assets else [],
                    taxable_disposed_quantity=taxable_disposed_quantity or Decimal("0"),
                    total_event_disposed_quantity=total_disposed_quantity,
                    taxable_event_fraction=taxable_fraction,
                    event_total_proceeds_eur=event_total_expected,  # type: ignore[arg-type]
                    actual_proceeds_eur=actual_proceeds_eur or Decimal("0"),
                    expected_proceeds_eur=expected,  # type: ignore[arg-type]
                    event_delta_eur=delta,  # type: ignore[arg-type]
                    event_delta_pct=delta_pct,  # type: ignore[arg-type]
                    split_line_absolute_delta_eur=split_delta,
                    split_line_count=split_count_by_event.get(event_id, 0),
                    status=status,
                    explanation=explanation,
                    recommended_action=action,
                )
            )
        return {line.disposal_event_id: line for line in lines}

    def _gain_evidence_acquisition_event_delta_lines_by_id(
        self,
        year: int,
        *,
        limit: int = 200,
    ) -> dict[str, TaxYearGainEvidenceAcquisitionEventDeltaLine]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    ae.event_id,
                    min(lot.acquired_at) as acquired_at,
                    any_value(ae.source) as source,
                    any_value(ae.event_type) as event_type,
                    any_value(ae.asset) as event_asset,
                    any_value(ae.quantity) as event_quantity,
                    any_value(ae.quote_asset) as quote_asset,
                    any_value(ae.quote_quantity) as quote_quantity,
                    count(*)::integer as tax_line_count,
                    string_agg(distinct l.asset, ',') as assets,
                    coalesce(sum(abs(l.quantity)), 0) as taxable_consumed_quantity,
                    coalesce(sum(l.acquisition_cost_eur), 0) as actual_cost_eur
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                join canonical_events ae on ae.event_id = lot.source_event_id
                where date_part('year', l.disposed_at)::integer = ?
                  and l.holding_days <= 365
                  and ae.event_id is not null
                  and ae.quote_asset is not null
                  and ae.quote_quantity is not null
                group by ae.event_id
                order by count(*) desc, abs(sum(l.acquisition_cost_eur)) desc, ae.event_id
                limit ?
                """,
                [year, max(1, min(limit, 500))],
            ).fetchall()
        price_lookup = HistoricalPriceLookup(self.store)
        lines: list[TaxYearGainEvidenceAcquisitionEventDeltaLine] = []
        for (
            event_id,
            acquired_at,
            source,
            event_type,
            event_asset,
            event_quantity,
            quote_asset,
            quote_quantity,
            tax_line_count,
            assets,
            taxable_consumed_quantity,
            actual_cost_eur,
        ) in rows:
            event_asset_key = str(event_asset or "").upper()
            asset_set = {asset.strip().upper() for asset in str(assets or "").split(",") if asset}
            if event_asset_key in asset_set and event_quantity is not None and event_quantity > 0:
                total_acquired_quantity = abs(event_quantity)
            else:
                total_acquired_quantity = taxable_consumed_quantity or None
            taxable_fraction = (
                taxable_consumed_quantity / total_acquired_quantity
                if total_acquired_quantity and taxable_consumed_quantity <= total_acquired_quantity
                else Decimal("1")
            )
            price = self._gain_evidence_price_check(
                price_lookup=price_lookup,
                quote_asset=quote_asset,
                quote_quantity=quote_quantity,
                fallback_asset=quote_asset,
                fallback_quantity=abs(quote_quantity or Decimal("0")),
                event_time=acquired_at,
                actual_value=actual_cost_eur or Decimal("0"),
            )
            event_total_expected = price["expected_value"]
            expected = event_total_expected * taxable_fraction if isinstance(event_total_expected, Decimal) else None
            delta = (actual_cost_eur or Decimal("0")) - expected if expected is not None else None
            delta_pct = abs(delta) / expected * Decimal("100") if expected else None
            if price["price_source"] is None:
                status: Literal["event_level_ok", "event_level_review", "missing_price_evidence"] = "missing_price_evidence"
            elif delta is not None and (abs(delta) < Decimal("0.01") or (delta_pct is not None and delta_pct <= Decimal("0.5"))):
                status = "event_level_ok"
            else:
                status = "event_level_review"
            explanation, action = self._gain_evidence_event_delta_text(
                status=status,
                split_line_absolute_delta_eur=Decimal("0"),
                event_delta_eur=delta if isinstance(delta, Decimal) else None,
            )
            if status == "event_level_ok":
                explanation = "Das Erwerbs-Event ist anteilig plausibel; Erwerbsseiten-Teilzeilen-Deltas sind FIFO-Split-/Quote-Allocation-Artefakte."
                action = "Erwerbs-Event-Level-Beleg archivieren; nicht als offenen Anschaffungspreisfehler werten."
            lines.append(
                TaxYearGainEvidenceAcquisitionEventDeltaLine(
                    year=year,
                    acquisition_event_id=event_id,
                    acquired_at=acquired_at.isoformat(),
                    source=source,
                    event_type=event_type,
                    event_asset=event_asset,
                    event_quantity=event_quantity,
                    quote_asset=quote_asset,
                    quote_quantity=quote_quantity,
                    price_asset=price["price_asset"],
                    price_eur=price["price_eur"],
                    price_source=price["price_source"],
                    priced_at=price["priced_at"],
                    price_age_days=price["price_age_days"],
                    tax_line_count=int(tax_line_count or 0),
                    assets=sorted(str(assets or "").split(",")) if assets else [],
                    taxable_consumed_quantity=taxable_consumed_quantity or Decimal("0"),
                    total_event_acquired_quantity=total_acquired_quantity,
                    taxable_event_fraction=taxable_fraction,
                    event_total_cost_eur=event_total_expected,  # type: ignore[arg-type]
                    actual_cost_eur=actual_cost_eur or Decimal("0"),
                    expected_cost_eur=expected,  # type: ignore[arg-type]
                    event_delta_eur=delta,  # type: ignore[arg-type]
                    event_delta_pct=delta_pct,  # type: ignore[arg-type]
                    status=status,
                    explanation=explanation,
                    recommended_action=action,
                )
            )
        return {line.acquisition_event_id: line for line in lines}

    def gain_evidence_acquisition_event_delta_review(
        self,
        year: int,
        *,
        limit: int = 200,
    ) -> TaxYearGainEvidenceAcquisitionEventDeltaReview:
        lines = list(self._gain_evidence_acquisition_event_delta_lines_by_id(year, limit=limit).values())
        lines.sort(
            key=lambda line: (
                line.status != "event_level_review",
                -abs(line.event_delta_eur or Decimal("0")),
                -line.actual_cost_eur,
            )
        )
        expected_total = sum((line.expected_cost_eur or Decimal("0") for line in lines), Decimal("0"))
        actual_total = sum((line.actual_cost_eur for line in lines), Decimal("0"))
        return TaxYearGainEvidenceAcquisitionEventDeltaReview(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            events_count=len(lines),
            event_level_ok_count=sum(1 for line in lines if line.status == "event_level_ok"),
            event_level_review_count=sum(1 for line in lines if line.status == "event_level_review"),
            missing_price_count=sum(1 for line in lines if line.status == "missing_price_evidence"),
            tax_line_count=sum(line.tax_line_count for line in lines),
            actual_cost_eur=actual_total,
            expected_cost_eur=expected_total,
            event_delta_eur=actual_total - expected_total,
            lines=lines,
            caveats=[
                "Read-only Erwerbs-Event-Plausibilisierung: keine Tax-Line-, Lot- oder FIFO-Aenderung.",
                "Event-Level OK bedeutet, dass Anschaffungskosten anteilig zum Erwerbs-Event passen; andere Belegthemen bleiben separat.",
            ],
            methodology=(
                "Aggregiert steuerpflichtig verbrauchte FIFO-Mengen je Acquisition-Event und vergleicht die Summe "
                "der Anschaffungskosten mit quote_quantity mal historischem EUR-Preis, anteilig zur im Steuerjahr "
                "steuerpflichtig verbrauchten Menge."
            ),
        )

    def gain_evidence_event_delta_review(
        self,
        year: int,
        *,
        limit: int = 200,
    ) -> TaxYearGainEvidenceEventDeltaReview:
        lines = list(
            self._gain_evidence_event_delta_lines_by_id(
                year,
                limit=limit,
                include_split_delta=True,
            ).values()
        )
        lines.sort(
            key=lambda line: (
                line.status != "event_level_review",
                -line.split_line_absolute_delta_eur,
                -abs(line.event_delta_eur or Decimal("0")),
            )
        )
        expected_total = sum((line.expected_proceeds_eur or Decimal("0") for line in lines), Decimal("0"))
        actual_total = sum((line.actual_proceeds_eur for line in lines), Decimal("0"))
        return TaxYearGainEvidenceEventDeltaReview(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            events_count=len(lines),
            event_level_ok_count=sum(1 for line in lines if line.status == "event_level_ok"),
            event_level_review_count=sum(1 for line in lines if line.status == "event_level_review"),
            missing_price_count=sum(1 for line in lines if line.status == "missing_price_evidence"),
            tax_line_count=sum(line.tax_line_count for line in lines),
            actual_proceeds_eur=actual_total,
            expected_proceeds_eur=expected_total,
            event_delta_eur=actual_total - expected_total,
            split_line_absolute_delta_eur=sum((line.split_line_absolute_delta_eur for line in lines), Decimal("0")),
            lines=lines,
            caveats=[
                "Read-only Event-Level-Plausibilisierung: keine Tax-Line-, Lot- oder FIFO-Aenderung.",
                "Event-Level OK bedeutet nicht automatisch steuerlich final, aber es entkraeftet Teilzeilen-Deltas als isolierten Bewertungsfehler.",
            ],
            methodology=(
                "Aggregiert steuerpflichtige Tax-Lines je Disposal-Event und vergleicht die Summe der Erloese "
                "mit quote_quantity mal historischem EUR-Preis des Event-Quote-Assets. Dadurch werden FIFO-Split-Artefakte "
                "von echten Event-Level-Bewertungsabweichungen getrennt."
            ),
        )

    def _loss_realization_ascii_table(self, rows: list[TaxLossRealizationLot]) -> str:
        table_rows = [
            [
                "Status",
                "Asset",
                "Anschaffung",
                "Letzter §23 Tag",
                "Wert",
                "Kosten",
                "Unrealisiert",
                "Quelle",
            ]
        ]
        for row in rows:
            table_rows.append(
                [
                    row.status,
                    row.asset,
                    row.acquired_at[:10],
                    row.last_tax_relevant_disposal_date,
                    self._fmt_eur(row.current_value_eur),
                    self._fmt_eur(row.cost_basis_eur_remaining),
                    self._fmt_eur(row.unrealized_gain_loss_eur),
                    row.source or "-",
                ]
            )
        if len(table_rows) == 1:
            table_rows.append(["-", "-", "-", "-", self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), self._fmt_eur(Decimal("0")), "-"])
        widths = [max(len(str(row[index])) for row in table_rows) for index in range(len(table_rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(table_rows[0]), sep, *(fmt(row) for row in table_rows[1:]), sep])

    def _gain_loss_reality_summary(
        self,
        *,
        year: int,
        gross_proceeds: Decimal,
        taxable_gain: Decimal,
        tax_free_gain: Decimal,
        open_value: Decimal,
        open_unrealized: Decimal,
        potential_loss: Decimal,
    ) -> str:
        return (
            f"{year}: Handels-/Swap-Volumen {self._fmt_eur(gross_proceeds)} ist kein eingesetztes "
            f"oder ausgezahltes EUR-Kapital. Steuerpflichtig realisiert: {self._fmt_eur(taxable_gain)}. "
            f"Nach Haltefrist steuerfrei realisiert: {self._fmt_eur(tax_free_gain)}. "
            f"Heute offene Positionen im Report: {self._fmt_eur(open_value)} mit unrealisiertem "
            f"G/V {self._fmt_eur(open_unrealized)}. Davon waeren Verluste erst bei Veraeusserung "
            f"realisierbar: {self._fmt_eur(potential_loss)}."
        )

    @staticmethod
    def _gain_loss_reality_note(
        *,
        taxable_gain: Decimal,
        open_value: Decimal,
        open_unrealized: Decimal,
    ) -> str:
        if taxable_gain > 0 and open_unrealized < 0:
            return "Realisierter Gewinn im Steuerjahr; heutiger Verlust ist offen/unrealisiert und daher nicht automatisch geltend gemacht."
        if taxable_gain > 0 and open_value == 0:
            return "Gewinn wurde im Steuerjahr realisiert; heute ist keine offene Position dieses Assets sichtbar."
        if taxable_gain < 0:
            return "Realisierter steuerpflichtiger Verlust ist bereits in den Tax-Lines enthalten."
        if open_unrealized < 0:
            return "Heute gehaltener Verlust ist offen/unrealisiert; steuerlich erst bei Veraeusserung relevant."
        if open_value > 0:
            return "Heute offene Position vorhanden; aktueller G/V ist nur nachrichtlich unrealisiert."
        return "Keine materielle offene Position; Wirkung stammt aus realisierten Tax-Lines."

    def _filing_checklist(
        self, lines: list[TaxYearFilingSummaryLine]
    ) -> list[TaxYearFilingChecklistItem]:
        items: list[TaxYearFilingChecklistItem] = []
        for line in lines:
            category = self._filing_checklist_category(line)
            items.append(
                TaxYearFilingChecklistItem(
                    order=line.order,
                    category=category,
                    label=line.label,
                    action=self._filing_checklist_action(line, category),
                    source_topic=line.topic,
                    amount_eur=line.amount_eur,
                    evidence_ref=line.evidence_ref,
                    done_when=self._filing_checklist_done_when(line, category),
                    note=line.note,
                )
            )
        return items

    @staticmethod
    def _filing_checklist_category(line: TaxYearFilingSummaryLine) -> Literal[
        "eintragen", "beilegen", "archivieren", "pruefen"
    ]:
        if line.topic in {"private_disposal", "income"} and line.amount_eur not in (None, Decimal("0")):
            return "eintragen"
        if line.topic == "derivative":
            return "pruefen"
        if line.topic == "appendix":
            return "beilegen" if "konservativ belegbar" in line.tax_treatment else "pruefen"
        if line.topic == "review":
            return "pruefen"
        if line.topic == "evidence":
            return "archivieren"
        return "archivieren"

    def _filing_checklist_action(self, line: TaxYearFilingSummaryLine, category: str) -> str:
        if category == "eintragen":
            return (
                f"Betrag {self._fmt_eur(line.amount_eur or Decimal('0'))} "
                "in der angegebenen Steuererklaerungsrubrik beruecksichtigen."
            )
        if category == "beilegen":
            return "Nachweis als Beilage zum Steuerjahr bereithalten; keinen zusaetzlichen Betrag eintragen."
        if category == "pruefen":
            return "Vor Abgabe fachlich pruefen und erst danach final behandeln."
        return "Nachweis im Jahrespaket archivieren und bei Rueckfragen vorlegen."

    @staticmethod
    def _filing_checklist_done_when(line: TaxYearFilingSummaryLine, category: str) -> str:
        if category == "eintragen":
            return "Der Betrag ist in der Steuererklaerung erfasst und der Beleg ist abgelegt."
        if category == "beilegen":
            return "Die Beilage ist im Jahrespaket vorhanden oder separat fuer das Finanzamt bereit."
        if category == "pruefen":
            return "Eine Review- oder Steuerberaterentscheidung ist dokumentiert."
        return "Der Export oder JSON-Beleg ist im Jahresordner gespeichert."

    def _filing_checklist_ascii(
        self, year: int, checklist: list[TaxYearFilingChecklistItem]
    ) -> str:
        rows = [["Jahr", "Kategorie", "Punkt", "Betrag", "Erledigt wenn"]]
        for item in checklist:
            rows.append(
                [
                    str(year),
                    item.category,
                    item.label,
                    self._fmt_eur(item.amount_eur) if item.amount_eur is not None else "-",
                    item.done_when,
                ]
            )
        widths = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
        sep = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def fmt(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |"

        return "\n".join([sep, fmt(rows[0]), sep, *(fmt(row) for row in rows[1:]), sep])

    @staticmethod
    def _evidence_item_status(count: int, *, review: bool = False, blocked: bool = False) -> str:
        if blocked:
            return "blocked"
        if review:
            return "review"
        return "available" if count else "empty"

    def income_report(self, year: int) -> TaxIncomeReport:
        return self._income_reports_by_year().get(
            year,
            TaxIncomeReport(
                year=year,
                generated_at=datetime.now(timezone.utc).isoformat(),
                methodology=(
                    "Read-only Mining/Reward/Income-Auswertung. EUR-Werte werden "
                    "direkt aus EUR-Quote oder ersatzweise aus historischem "
                    "Asset/EUR-Preis am Ereigniszeitpunkt bewertet."
                ),
            ),
        )

    def reward_trading_separation(
        self,
        *,
        years: list[int] | None = None,
        assets: tuple[str, ...] = HELIUM_REWARD_ASSETS,
    ) -> TaxRewardTradingSeparationReport:
        selected_years = years if years is not None else [year for year in self._available_years() if 2021 <= year <= 2025]
        asset_keys = tuple(asset.upper() for asset in assets)
        rows: list[TaxRewardTradingSeparationRow] = []
        for year in selected_years:
            income = self.income_report(year)
            income_by_asset: dict[str, dict[str, object]] = {
                asset: {
                    "income": Decimal("0"),
                    "quantity": Decimal("0"),
                    "events": 0,
                    "event_types": set(),
                    "sources": set(),
                }
                for asset in asset_keys
            }
            for item in income.assets:
                asset = item.asset.upper()
                if asset not in income_by_asset:
                    continue
                if not self._is_taxable_reward_income(
                    event_type=item.event_type,
                    source=",".join(item.sources),
                    asset=item.asset,
                    quantity=item.quantity,
                ):
                    continue
                bucket = income_by_asset[asset]
                bucket["income"] = bucket["income"] + item.income_eur  # type: ignore[operator]
                bucket["quantity"] = bucket["quantity"] + item.quantity  # type: ignore[operator]
                bucket["events"] = int(bucket["events"]) + item.events_count
                bucket["event_types"].add(item.event_type)  # type: ignore[union-attr]
                bucket["sources"].update(item.sources)  # type: ignore[union-attr]

            lines_by_asset: dict[str, list[object]] = {asset: [] for asset in asset_keys}
            for line in self._tax_lines():
                asset = str(getattr(line, "asset", "") or "").upper()
                if asset in lines_by_asset and getattr(line, "disposed_at").year == year:
                    lines_by_asset[asset].append(line)

            for asset in asset_keys:
                reward = income_by_asset[asset]
                tax_lines = lines_by_asset[asset]
                taxable_lines = [line for line in tax_lines if self._is_taxable_private_disposal(line)]
                tax_free_lines = [line for line in tax_lines if not self._is_taxable_private_disposal(line)]
                if not int(reward["events"]) and not tax_lines:
                    continue
                rows.append(
                    TaxRewardTradingSeparationRow(
                        year=year,
                        asset=asset,
                        reward_income_eur=reward["income"],  # type: ignore[arg-type]
                        reward_quantity=reward["quantity"],  # type: ignore[arg-type]
                        reward_events_count=int(reward["events"]),
                        reward_event_types=sorted(reward["event_types"]),  # type: ignore[arg-type]
                        reward_sources=sorted(reward["sources"]),  # type: ignore[arg-type]
                        trade_taxable_gain_loss_eur=sum((line.gain_loss_eur for line in taxable_lines), Decimal("0")),
                        trade_taxable_proceeds_eur=sum((line.disposal_proceeds_eur for line in taxable_lines), Decimal("0")),
                        trade_taxable_acquisition_cost_eur=sum(
                            (line.acquisition_cost_eur for line in taxable_lines), Decimal("0")
                        ),
                        trade_taxable_lines_count=len(taxable_lines),
                        trade_tax_free_gain_loss_eur=sum((line.gain_loss_eur for line in tax_free_lines), Decimal("0")),
                        trade_tax_free_proceeds_eur=sum((line.disposal_proceeds_eur for line in tax_free_lines), Decimal("0")),
                        trade_tax_free_acquisition_cost_eur=sum(
                            (line.acquisition_cost_eur for line in tax_free_lines), Decimal("0")
                        ),
                        trade_tax_free_lines_count=len(tax_free_lines),
                        total_trade_gain_loss_eur=sum((line.gain_loss_eur for line in tax_lines), Decimal("0")),
                        tax_note=(
                            "Reward/Mining ist der Einnahmevorgang zum Zuflusswert. "
                            "Der spaetere Handel wird separat als private FIFO-Veraeusserung ausgewiesen; "
                            "bei Haltedauer ueber 365 Tagen nur nachrichtlich steuerfrei."
                        ),
                        income_guide_endpoint=f"/api/v1/tax-years/{year}/income-guide",
                        asset_fifo_drilldown_endpoint=f"/api/v1/tax-years/{year}/asset-fifo-drilldown?asset={asset}",
                    )
                )
        rows.sort(key=lambda item: (item.year, item.asset))
        return TaxRewardTradingSeparationReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            years=selected_years,
            assets=list(asset_keys),
            total_reward_income_eur=sum((row.reward_income_eur for row in rows), Decimal("0")),
            total_trade_taxable_gain_loss_eur=sum((row.trade_taxable_gain_loss_eur for row in rows), Decimal("0")),
            total_trade_tax_free_gain_loss_eur=sum((row.trade_tax_free_gain_loss_eur for row in rows), Decimal("0")),
            rows=rows,
            ascii_table=self._reward_trading_separation_ascii_table(rows),
            methodology=(
                "Read-only BMF-nahe Trennung fuer HNT/IOT/MOBILE. Helium-Reward-/Mining-Zufluesse "
                "werden als eigener Einnahmeblock zum Zuflusswert gezeigt. Spaetere Verkaeufe, Swaps "
                "oder Quote-Bein-Verwertungen bleiben getrennte FIFO-Veraeusserungen nach Haltefrist. "
                "Der Report schreibt keine Lots, Tax-Lines oder Preise und ersetzt keine steuerliche Beratung."
            ),
        )

    def income_asset_breakdown_from_lots(self, year: int) -> list[TaxIncomeAssetBreakdown]:
        cached = self._income_asset_breakdown_from_lots_cache.get(year)
        if cached is not None:
            return [item.model_copy(deep=True) for item in cached]
        with self.store.connect() as con:
            rows = con.execute(
                """
                with lot_values as (
                    select
                        source_event_id,
                        sum(cost_basis_eur_total) as value_eur
                    from tax_lots
                    group by source_event_id
                )
                select
                    e.event_id,
                    e.event_time,
                    e.event_type,
                    e.source,
                    e.account,
                    e.asset,
                    e.quantity,
                    e.quote_asset,
                    e.tx_id,
                    coalesce(l.value_eur, 0) as value_eur,
                    case when l.source_event_id is null then false else true end as has_lot
                from canonical_events e
                left join lot_values l on l.source_event_id = e.event_id
                where e.event_type in ('income', 'reward', 'staking', 'mining')
                  and date_part('year', e.event_time) = ?
                order by e.event_time, e.event_id
                """,
                [year],
            ).fetchall()
        tx_context = self._income_tx_context()
        grouped: dict[str, TaxIncomeAssetBreakdown] = {}
        for (
            _event_id,
            _event_time,
            event_type,
            source,
            account,
            asset,
            quantity,
            quote_asset,
            tx_id,
            value_eur,
            has_lot,
        ) in rows:
            classification = self._income_classification(
                event_type=event_type,
                source=source,
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                account=account,
                tx_id=tx_id,
                tx_context=tx_context,
            )
            asset_key = f"{asset.upper()}::{event_type}::{classification}"
            item = grouped.setdefault(
                asset_key,
                TaxIncomeAssetBreakdown(
                    asset=asset,
                    event_type=event_type,
                    classification=classification,
                ),
            )
            item.events_count += 1
            item.quantity += quantity
            if source not in item.sources:
                item.sources.append(source)
            if quantity > 0:
                if has_lot:
                    item.income_eur += value_eur or Decimal("0")
                else:
                    item.missing_value_count += 1
        assets = sorted(grouped.values(), key=lambda item: abs(item.income_eur), reverse=True)
        for item in assets:
            item.sources = sorted(item.sources)
        self._income_asset_breakdown_from_lots_cache[year] = [
            item.model_copy(deep=True) for item in assets
        ]
        return assets

    def driver_report(self, year: int, *, limit: int = 50) -> TaxYearDriverReport:
        lines = [line for line in self._tax_lines() if line.disposed_at.year == year]
        taxable = [line for line in lines if self._is_taxable_private_disposal(line)]
        tax_free = [line for line in lines if not self._is_taxable_private_disposal(line)]
        taxable.sort(key=lambda item: abs(item.gain_loss_eur), reverse=True)
        tax_free.sort(key=lambda item: abs(item.gain_loss_eur), reverse=True)
        return TaxYearDriverReport(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            taxable_gain_loss_eur=sum((line.gain_loss_eur for line in taxable), Decimal("0")),
            tax_free_gain_loss_eur=sum((line.gain_loss_eur for line in tax_free), Decimal("0")),
            top_taxable_assets=self._asset_breakdown(year)[:20],
            top_tax_free_assets=self._asset_breakdown_for_lines(tax_free)[:20],
            top_taxable_lines=[self._driver_line(line, taxable=True) for line in taxable[:limit]],
            top_tax_free_lines=[self._driver_line(line, taxable=False) for line in tax_free[:limit]],
            methodology=(
                "Read-only Plausibilitaetsbericht aus bestehenden Tax-Lines. "
                "Top-Zeilen sind nach absolutem Gewinn/Verlust sortiert; "
                "steuerpflichtig bedeutet holding_days <= 365."
            ),
        )

    def gain_loss_reality_check(self, year: int, *, limit: int = 40) -> TaxYearGainLossRealityCheck:
        lines = [line for line in self._tax_lines() if line.disposed_at.year == year]
        taxable = [line for line in lines if self._is_taxable_private_disposal(line)]
        tax_free = [line for line in lines if not self._is_taxable_private_disposal(line)]
        grouped: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "taxable_gain": Decimal("0"),
                "taxable_proceeds": Decimal("0"),
                "taxable_cost": Decimal("0"),
                "taxable_lines": 0,
                "tax_free_gain": Decimal("0"),
                "tax_free_lines": 0,
                "open_quantity": Decimal("0"),
                "open_value": Decimal("0"),
                "open_cost": Decimal("0"),
                "open_unrealized": Decimal("0"),
                "open_lots": 0,
                "open_tax_free_now_value": Decimal("0"),
                "open_not_yet_tax_free_value": Decimal("0"),
                "price_sources": set(),
            }
        )
        for line in taxable:
            item = grouped[line.asset.upper()]
            item["taxable_gain"] = item["taxable_gain"] + line.gain_loss_eur  # type: ignore[operator]
            item["taxable_proceeds"] = item["taxable_proceeds"] + line.disposal_proceeds_eur  # type: ignore[operator]
            item["taxable_cost"] = item["taxable_cost"] + line.acquisition_cost_eur  # type: ignore[operator]
            item["taxable_lines"] = int(item["taxable_lines"]) + 1
        for line in tax_free:
            item = grouped[line.asset.upper()]
            item["tax_free_gain"] = item["tax_free_gain"] + line.gain_loss_eur  # type: ignore[operator]
            item["tax_free_lines"] = int(item["tax_free_lines"]) + 1

        holdings = TaxService(self.store).holding_period_report(min_value_eur=Decimal("0"))
        for lot in holdings.lots:
            item = grouped[lot.asset.upper()]
            item["open_quantity"] = item["open_quantity"] + lot.quantity_remaining  # type: ignore[operator]
            item["open_value"] = item["open_value"] + lot.current_value_eur  # type: ignore[operator]
            item["open_cost"] = item["open_cost"] + lot.cost_basis_eur_remaining  # type: ignore[operator]
            item["open_unrealized"] = item["open_unrealized"] + lot.unrealized_gain_loss_eur  # type: ignore[operator]
            item["open_lots"] = int(item["open_lots"]) + 1
            if lot.bucket == "tax_free_now":
                item["open_tax_free_now_value"] = item["open_tax_free_now_value"] + lot.current_value_eur  # type: ignore[operator]
            else:
                item["open_not_yet_tax_free_value"] = item["open_not_yet_tax_free_value"] + lot.current_value_eur  # type: ignore[operator]
            item["price_sources"].add(lot.price_source)  # type: ignore[union-attr]

        rows: list[TaxYearGainLossRealityAssetRow] = []
        for asset, item in grouped.items():
            taxable_gain = item["taxable_gain"]
            tax_free_gain = item["tax_free_gain"]
            open_value = item["open_value"]
            open_unrealized = item["open_unrealized"]
            if not any((taxable_gain, tax_free_gain, open_value, open_unrealized)):
                continue
            price_sources = sorted(source for source in item["price_sources"] if source)  # type: ignore[union-attr]
            rows.append(
                TaxYearGainLossRealityAssetRow(
                    year=year,
                    asset=asset,
                    realized_taxable_gain_loss_eur=taxable_gain,  # type: ignore[arg-type]
                    realized_taxable_proceeds_eur=item["taxable_proceeds"],  # type: ignore[arg-type]
                    realized_taxable_acquisition_cost_eur=item["taxable_cost"],  # type: ignore[arg-type]
                    realized_taxable_lines_count=int(item["taxable_lines"]),
                    realized_tax_free_gain_loss_eur=tax_free_gain,  # type: ignore[arg-type]
                    realized_tax_free_lines_count=int(item["tax_free_lines"]),
                    open_quantity=item["open_quantity"],  # type: ignore[arg-type]
                    open_current_value_eur=open_value,  # type: ignore[arg-type]
                    open_cost_basis_eur=item["open_cost"],  # type: ignore[arg-type]
                    open_unrealized_gain_loss_eur=open_unrealized,  # type: ignore[arg-type]
                    open_lots_count=int(item["open_lots"]),
                    open_tax_free_now_value_eur=item["open_tax_free_now_value"],  # type: ignore[arg-type]
                    open_not_yet_tax_free_value_eur=item["open_not_yet_tax_free_value"],  # type: ignore[arg-type]
                    potential_loss_not_realized_eur=(
                        open_unrealized if open_unrealized < 0 else Decimal("0")  # type: ignore[operator]
                    ),
                    current_price_source=", ".join(price_sources[:3]) if price_sources else None,
                    note=self._gain_loss_reality_note(
                        taxable_gain=taxable_gain,  # type: ignore[arg-type]
                        open_value=open_value,  # type: ignore[arg-type]
                        open_unrealized=open_unrealized,  # type: ignore[arg-type]
                    ),
                    asset_fifo_drilldown_endpoint=f"/api/v1/tax-years/{year}/asset-fifo-drilldown?asset={asset}",
                )
            )
        rows.sort(
            key=lambda row: (
                abs(row.realized_taxable_gain_loss_eur)
                + abs(row.open_unrealized_gain_loss_eur)
                + abs(row.realized_tax_free_gain_loss_eur)
            ),
            reverse=True,
        )
        rows = rows[: max(1, min(limit, 200))]
        taxable_gain_total = sum((line.gain_loss_eur for line in taxable), Decimal("0"))
        tax_free_gain_total = sum((line.gain_loss_eur for line in tax_free), Decimal("0"))
        gross_proceeds = sum((line.disposal_proceeds_eur for line in lines), Decimal("0"))
        open_value_total = sum((row.open_current_value_eur for row in rows), Decimal("0"))
        open_cost_total = sum((row.open_cost_basis_eur for row in rows), Decimal("0"))
        open_unrealized_total = sum((row.open_unrealized_gain_loss_eur for row in rows), Decimal("0"))
        potential_loss_total = sum((row.potential_loss_not_realized_eur for row in rows), Decimal("0"))
        return TaxYearGainLossRealityCheck(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            taxable_gain_loss_eur=taxable_gain_total,
            tax_free_gain_loss_eur=tax_free_gain_total,
            gross_disposal_proceeds_eur=gross_proceeds,
            open_current_value_eur=open_value_total,
            open_cost_basis_eur=open_cost_total,
            open_unrealized_gain_loss_eur=open_unrealized_total,
            potential_loss_not_realized_eur=potential_loss_total,
            rows=rows,
            plain_language_summary=self._gain_loss_reality_summary(
                year=year,
                gross_proceeds=gross_proceeds,
                taxable_gain=taxable_gain_total,
                tax_free_gain=tax_free_gain_total,
                open_value=open_value_total,
                open_unrealized=open_unrealized_total,
                potential_loss=potential_loss_total,
            ),
            caveats=[
                "Realisierter Gewinn/Verlust entsteht nur bei Verkauf, Swap oder anderer Veraeusserung in den Tax-Lines.",
                "Heute noch gehaltene Token zeigen nur unrealisierten Gewinn/Verlust; dieser ist nicht automatisch steuerlich geltend gemacht.",
                "Handels-/Swap-Volumen ist kein Nachweis fuer eingezahltes oder ausgezahltes EUR-Kapital.",
            ],
            ascii_table=self._gain_loss_reality_ascii_table(rows),
            methodology=(
                "Read-only Realitaetscheck aus bestehenden Tax-Lines und offenen Holding-Period-Lots. "
                "Er trennt realisierte steuerpflichtige FIFO-Ergebnisse, steuerfreie Ergebnisse nach Haltefrist "
                "und heute noch offene unrealisierte Gewinne/Verluste. Es werden keine Steuerdaten neu berechnet "
                "oder geschrieben."
            ),
        )

    def gain_evidence_review(self, year: int, *, limit: int = 80) -> TaxYearGainEvidenceReview:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    l.tax_line_id,
                    l.asset,
                    lot.acquired_at,
                    l.disposed_at,
                    l.holding_days,
                    l.quantity,
                    l.acquisition_cost_eur,
                    l.disposal_proceeds_eur,
                    l.gain_loss_eur,
                    l.lot_id,
                    ae.event_id,
                    ae.source,
                    ae.event_type,
                    ae.quantity,
                    ae.quote_asset,
                    ae.quote_quantity,
                    ae.raw_object_id,
                    de.event_id,
                    de.source,
                    de.event_type,
                    de.quantity,
                    de.quote_asset,
                    de.quote_quantity,
                    de.raw_object_id
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                left join canonical_events ae on ae.event_id = lot.source_event_id
                left join canonical_events de on de.event_id = l.source_event_id
                where date_part('year', l.disposed_at)::integer = ?
                  and l.holding_days <= 365
                order by abs(l.gain_loss_eur) desc, l.disposed_at, l.tax_line_id
                limit ?
                """,
                [year, max(1, min(limit, 500))],
            ).fetchall()
        lines: list[TaxYearGainEvidenceLine] = []
        price_lookup = HistoricalPriceLookup(self.store)
        event_level_by_id = self._gain_evidence_event_delta_lines_by_id(
            year,
            limit=max(1, min(limit, 500)),
            include_split_delta=False,
        )
        acquisition_event_level_by_id = self._gain_evidence_acquisition_event_delta_lines_by_id(
            year,
            limit=max(1, min(limit, 500)),
        )
        for row in rows:
            gain_loss = row[8] or Decimal("0")
            proceeds = row[7] or Decimal("0")
            ratio = (gain_loss / proceeds * Decimal("100")) if proceeds else Decimal("0")
            acquired_at = row[2]
            disposed_at = row[3]
            acquisition_price = self._gain_evidence_price_check(
                price_lookup=price_lookup,
                quote_asset=row[14],
                quote_quantity=row[15],
                event_quantity=row[13],
                fallback_asset=row[1],
                fallback_quantity=row[5],
                event_time=acquired_at,
                actual_value=row[6],
            )
            disposal_price = self._gain_evidence_price_check(
                price_lookup=price_lookup,
                quote_asset=row[21],
                quote_quantity=row[22],
                event_quantity=row[20],
                fallback_asset=row[1],
                fallback_quantity=row[5],
                event_time=disposed_at,
                actual_value=proceeds,
            )
            reasons = self._gain_evidence_reasons(
                acquisition_raw_object_id=row[16],
                disposal_raw_object_id=row[23],
                acquisition_quote_asset=row[14],
                disposal_quote_asset=row[21],
                acquisition_source=row[11],
                disposal_source=row[18],
                gain_loss_ratio_pct=ratio,
                acquisition_price_delta_pct=acquisition_price["delta_pct"],
                disposal_price_delta_pct=disposal_price["delta_pct"],
                acquisition_price_age_days=acquisition_price["price_age_days"],
                disposal_price_age_days=disposal_price["price_age_days"],
                acquisition_price_source=acquisition_price["price_source"],
                disposal_price_source=disposal_price["price_source"],
            )
            (
                absolute_price_delta_eur,
                max_price_delta_pct,
                delta_classification,
                delta_explanation,
                delta_recommended_action,
            ) = self._gain_evidence_delta_decision(
                acquisition_quote_asset=row[14],
                disposal_quote_asset=row[21],
                acquisition_source=row[11],
                disposal_source=row[18],
                acquisition_price=acquisition_price,
                disposal_price=disposal_price,
                reasons=reasons,
            )
            event_level = event_level_by_id.get(row[17] or "")
            event_level_reconciled = bool(event_level and event_level.status == "event_level_ok")
            acquisition_event_level = acquisition_event_level_by_id.get(row[10] or "")
            acquisition_event_level_reconciled = bool(
                acquisition_event_level and acquisition_event_level.status == "event_level_ok"
            )
            acquisition_delta_eur = self._decimal_or_zero(acquisition_price["delta_eur"])
            disposal_delta_eur = self._decimal_or_zero(disposal_price["delta_eur"])
            open_price_delta_eur = (
                Decimal("0") if acquisition_event_level_reconciled else abs(acquisition_delta_eur)
            ) + (
                Decimal("0") if event_level_reconciled else abs(disposal_delta_eur)
            )
            event_level_note = None
            acquisition_event_level_note = None
            if acquisition_event_level_reconciled and abs(acquisition_delta_eur) > Decimal("0.01"):
                acquisition_event_level_note = (
                    "Erwerbsseiten-Delta ist Acquisition-Event-Level abgeglichen; es ist als FIFO-Split-/Quote-Allocation-Artefakt zu behandeln."
                )
                if "acquisition_price_delta_review" in reasons:
                    reasons = [reason for reason in reasons if reason != "acquisition_price_delta_review"]
                if "acquisition_event_level_reconciled" not in reasons:
                    reasons.append("acquisition_event_level_reconciled")
            if event_level_reconciled and abs(disposal_delta_eur) > Decimal("0.01"):
                event_level_note = (
                    "Verkaufsseiten-Delta ist Event-Level abgeglichen; es ist als Handelsvolumen-/FIFO-Split-Artefakt zu behandeln."
                )
                if "disposal_price_delta_review" in reasons:
                    reasons = [reason for reason in reasons if reason != "disposal_price_delta_review"]
                if "event_level_reconciled" not in reasons:
                    reasons.append("event_level_reconciled")
                delta_explanation = (
                    "Das Verkaufsseiten-Delta ist auf Event-Level plausibel; offen bleibt nur ein moegliches Erwerbsseiten-Delta."
                )
                delta_recommended_action = (
                    "Event-Level-Beleg archivieren und nur offene Erwerbs-/Rohbelegthemen weiter pruefen."
                )
            if acquisition_event_level_reconciled and event_level_reconciled and open_price_delta_eur == Decimal("0"):
                delta_explanation = (
                    "Erwerbs- und Verkaufsseiten-Deltas sind auf Event-Level plausibel; das Brutto-Delta ist ein FIFO-Split-/Quote-Allocation-Artefakt."
                )
                delta_recommended_action = "Event-Level-Belege archivieren; kein offenes Preisdelta in dieser Zeile."
            risk = self._gain_evidence_risk(reasons)
            lines.append(
                TaxYearGainEvidenceLine(
                    tax_line_id=row[0],
                    asset=row[1],
                    acquired_at=acquired_at.isoformat(),
                    disposed_at=disposed_at.isoformat(),
                    holding_days=int(row[4] or 0),
                    quantity=row[5],
                    acquisition_cost_eur=row[6],
                    disposal_proceeds_eur=proceeds,
                    gain_loss_eur=gain_loss,
                    gain_loss_ratio_pct=ratio,
                    lot_id=row[9],
                    acquisition_event_id=row[10],
                    acquisition_source=row[11],
                    acquisition_event_type=row[12],
                    acquisition_quote_asset=row[14],
                    acquisition_quote_quantity=row[15],
                    acquisition_raw_object_id=row[16],
                    acquisition_raw_evidence="present" if row[16] else "missing",
                    acquisition_price_asset=acquisition_price["price_asset"],
                    acquisition_price_eur=acquisition_price["price_eur"],
                    acquisition_price_source=acquisition_price["price_source"],
                    acquisition_priced_at=acquisition_price["priced_at"],
                    acquisition_price_age_days=acquisition_price["price_age_days"],
                    acquisition_expected_cost_eur=acquisition_price["expected_value"],
                    acquisition_cost_delta_eur=acquisition_price["delta_eur"],
                    acquisition_cost_delta_pct=acquisition_price["delta_pct"],
                    disposal_event_id=row[17],
                    disposal_source=row[18],
                    disposal_event_type=row[19],
                    disposal_quote_asset=row[21],
                    disposal_quote_quantity=row[22],
                    disposal_raw_object_id=row[23],
                    disposal_raw_evidence="present" if row[23] else "missing",
                    disposal_price_asset=disposal_price["price_asset"],
                    disposal_price_eur=disposal_price["price_eur"],
                    disposal_price_source=disposal_price["price_source"],
                    disposal_priced_at=disposal_price["priced_at"],
                    disposal_price_age_days=disposal_price["price_age_days"],
                    disposal_expected_proceeds_eur=disposal_price["expected_value"],
                    disposal_proceeds_delta_eur=disposal_price["delta_eur"],
                    disposal_proceeds_delta_pct=disposal_price["delta_pct"],
                    absolute_price_delta_eur=absolute_price_delta_eur,
                    open_price_delta_eur=open_price_delta_eur,
                    max_price_delta_pct=max_price_delta_pct,
                    delta_classification=delta_classification,
                    delta_explanation=delta_explanation,
                    delta_recommended_action=delta_recommended_action,
                    event_level_status=event_level.status if event_level else None,
                    event_level_delta_eur=event_level.event_delta_eur if event_level else None,
                    event_level_delta_pct=event_level.event_delta_pct if event_level else None,
                    event_level_reconciled=event_level_reconciled,
                    event_level_note=event_level_note,
                    acquisition_event_level_status=acquisition_event_level.status if acquisition_event_level else None,
                    acquisition_event_level_delta_eur=(
                        acquisition_event_level.event_delta_eur if acquisition_event_level else None
                    ),
                    acquisition_event_level_delta_pct=(
                        acquisition_event_level.event_delta_pct if acquisition_event_level else None
                    ),
                    acquisition_event_level_reconciled=acquisition_event_level_reconciled,
                    acquisition_event_level_note=acquisition_event_level_note,
                    valuation_path=self._gain_evidence_valuation_path(row[14], row[21]),
                    risk_level=risk,
                    review_reasons=reasons,
                    asset_fifo_drilldown_endpoint=f"/api/v1/tax-years/{year}/asset-fifo-drilldown?asset={row[1]}",
                )
            )
        taxable_total = sum(
            (line.gain_loss_eur for line in self._tax_lines() if line.disposed_at.year == year and self._is_taxable_private_disposal(line)),
            Decimal("0"),
        )
        delta_groups = self._gain_evidence_delta_groups(year, lines)
        return TaxYearGainEvidenceReview(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            taxable_gain_loss_eur=taxable_total,
            reviewed_gain_loss_eur=sum((line.gain_loss_eur for line in lines), Decimal("0")),
            reviewed_lines_count=len(lines),
            high_risk_lines_count=sum(1 for line in lines if line.risk_level == "high"),
            review_lines_count=sum(1 for line in lines if line.risk_level == "review"),
            ok_lines_count=sum(1 for line in lines if line.risk_level == "ok"),
            price_delta_lines_count=sum(1 for line in lines if line.delta_classification != "no_material_delta"),
            event_level_reconciled_lines_count=sum(1 for line in lines if line.event_level_reconciled),
            acquisition_event_level_reconciled_lines_count=sum(
                1 for line in lines if line.acquisition_event_level_reconciled
            ),
            material_price_delta_eur=sum((line.absolute_price_delta_eur for line in lines), Decimal("0")),
            open_price_delta_eur=sum((line.open_price_delta_eur for line in lines), Decimal("0")),
            delta_groups=delta_groups,
            lines=lines,
            caveats=[
                "Read-only Belegcheck: bewertet vorhandene Tax-Lines, rechnet FIFO aber nicht neu.",
                "Fehlende Rohbelege, nicht-EUR-Quote-Beine und hohe Gewinnquoten sind Review-Signale, keine automatische Korrektur.",
                "Preisdelta-Gruppen erklaeren, warum Tax-Line-Wert und erwarteter Quote-/Preiswert abweichen koennen.",
                "Event-Level abgeglichene Verkaufsseiten-Deltas werden als Handelsvolumen-/FIFO-Split-Artefakt aus dem offenen Preisdelta herausgerechnet.",
                "Die geprueften Top-Zeilen sind nach absolutem G/V sortiert und decken nicht zwingend alle kleinen Zeilen ab.",
            ],
            ascii_table=self._gain_evidence_ascii_table(lines),
            methodology=(
                "Read-only Gewinn-Belegcheck aus tax_lines, tax_lots, canonical_events und raw_objects. "
                "Der Report priorisiert die groessten steuerpflichtigen Gewinn-/Verlustzeilen und markiert, "
                "ob Erwerbs- und Veraeusserungsrohbelege vorhanden sind, ob EUR direkt aus dem Event kommt "
                "oder Quote-/Stablecoin-/implizite Bewertungen geprueft werden muessen."
            ),
        )

    def loss_realization_planner(
        self,
        *,
        min_loss_eur: Decimal = Decimal("1"),
        min_value_eur: Decimal = Decimal("1"),
        limit: int = 100,
    ) -> TaxLossRealizationPlanner:
        holdings = TaxService(self.store).holding_period_report(min_value_eur=min_value_eur)
        rows: list[TaxLossRealizationLot] = []
        for lot in holdings.lots:
            unrealized = lot.unrealized_gain_loss_eur
            if abs(unrealized) < min_loss_eur and unrealized < 0:
                continue
            if unrealized < 0 and lot.days_until_tax_free > 0:
                status = "tax_relevant_loss_if_sold_now"
                action_note = (
                    "Verlust waere bei Verkauf/Swap vor Ablauf der Jahresfrist grundsaetzlich "
                    "als privater Veraeusserungsverlust nach FIFO nachweisbar."
                )
            elif unrealized < 0:
                status = "loss_window_expired"
                action_note = (
                    "Der Lot ist bereits ausserhalb der privaten Jahresfrist. Ein heutiger Verkauf "
                    "waere regelmaessig steuerfrei; der Verlust ist konservativ nicht als §23-Verlust geplant."
                )
            else:
                status = "not_a_loss"
                action_note = "Aktuell kein Verlust-Lot; nur zur Vollstaendigkeit bei materieller offener Position sichtbar."
            if status == "not_a_loss" and lot.current_value_eur < min_value_eur:
                continue
            last_tax_relevant = (lot.tax_free_at - timedelta(days=1)).date().isoformat()
            rows.append(
                TaxLossRealizationLot(
                    lot_id=lot.lot_id,
                    asset=lot.asset,
                    acquired_at=lot.acquired_at.isoformat(),
                    tax_free_at=lot.tax_free_at.isoformat(),
                    last_tax_relevant_disposal_date=last_tax_relevant,
                    days_until_tax_free=lot.days_until_tax_free,
                    bucket=lot.bucket,
                    status=status,
                    quantity_remaining=lot.quantity_remaining,
                    cost_basis_eur_remaining=lot.cost_basis_eur_remaining,
                    current_value_eur=lot.current_value_eur,
                    unrealized_gain_loss_eur=unrealized,
                    current_price_eur=lot.current_price_eur,
                    price_source=lot.price_source,
                    priced_at=lot.priced_at.isoformat(),
                    source_event_id=lot.source_event_id,
                    source=lot.source,
                    account=lot.account,
                    evidence_note=(
                        "Belegpfad: offener FIFO-Lot, source_event_id, Importquelle/Account, "
                        "aktuelle Preisquelle und spaetere Verkaufs-/Swap-Tax-Line gemeinsam archivieren."
                    ),
                    action_note=action_note,
                )
            )
        status_order = {
            "tax_relevant_loss_if_sold_now": 0,
            "loss_window_expired": 1,
            "not_a_loss": 2,
        }
        rows.sort(key=lambda row: (status_order[row.status], row.unrealized_gain_loss_eur, row.tax_free_at, row.asset))
        rows = rows[: max(1, min(limit, 500))]
        tax_relevant_loss = sum(
            (row.unrealized_gain_loss_eur for row in rows if row.status == "tax_relevant_loss_if_sold_now"),
            Decimal("0"),
        )
        expired_loss = sum(
            (row.unrealized_gain_loss_eur for row in rows if row.status == "loss_window_expired"),
            Decimal("0"),
        )
        unrealized_gain = sum(
            (row.unrealized_gain_loss_eur for row in rows if row.unrealized_gain_loss_eur > 0),
            Decimal("0"),
        )
        return TaxLossRealizationPlanner(
            generated_at=datetime.now(timezone.utc).isoformat(),
            as_of=holdings.as_of.isoformat(),
            min_loss_eur=min_loss_eur,
            min_value_eur=min_value_eur,
            tax_relevant_loss_if_sold_now_eur=tax_relevant_loss,
            expired_loss_not_tax_relevant_eur=expired_loss,
            unrealized_gain_eur=unrealized_gain,
            tax_relevant_lots_count=sum(1 for row in rows if row.status == "tax_relevant_loss_if_sold_now"),
            expired_loss_lots_count=sum(1 for row in rows if row.status == "loss_window_expired"),
            rows=rows,
            caveats=[
                "Read-only Planung: Es wird kein Verkauf ausgeloest und keine Steuerzeile geschrieben.",
                "Ein Verlust wird erst durch Verkauf, Swap oder andere Veraeusserung realisiert.",
                "Private §23-Verluste sind konservativ nur innerhalb der Jahresfrist geplant; nach Ablauf der Frist ist auch ein Verlust regelmaessig steuerlich unbeachtlich.",
                "Vor Umsetzung steuerlich pruefen, besonders bei Reward-/Mining-Herkunft, Betriebsvermoegen oder gewerblicher Einordnung.",
            ],
            ascii_table=self._loss_realization_ascii_table(rows),
            methodology=(
                "Read-only Verlustrealisierungsplan aus offenen FIFO-Lots, aktueller Preisbewertung "
                "und Haltefrist. Der Report zeigt, welche offenen Verluste bei sofortiger Veraeusserung "
                "innerhalb der Jahresfrist nachweisbar waeren und welche Verlustfenster bereits abgelaufen sind."
            ),
        )

    def asset_fifo_drilldown(
        self,
        year: int,
        *,
        asset: str,
        limit: int = 200,
    ) -> TaxYearAssetFifoDrilldown:
        asset_key = asset.strip().upper()
        if not asset_key:
            asset_key = "UNKNOWN"
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    l.tax_line_id,
                    l.asset,
                    l.quantity,
                    lot.acquired_at,
                    l.disposed_at,
                    l.holding_days,
                    l.acquisition_cost_eur,
                    l.disposal_proceeds_eur,
                    l.gain_loss_eur,
                    l.source_event_id,
                    l.lot_id,
                    ae.event_id,
                    ae.source,
                    ae.source_ref,
                    ae.event_time,
                    ae.event_type,
                    ae.asset,
                    ae.quantity,
                    ae.quote_asset,
                    ae.quote_quantity,
                    ae.tx_id,
                    ae.wallet,
                    ae.account,
                    ae.raw_object_id,
                    de.event_id,
                    de.source,
                    de.source_ref,
                    de.event_time,
                    de.event_type,
                    de.asset,
                    de.quantity,
                    de.quote_asset,
                    de.quote_quantity,
                    de.tx_id,
                    de.wallet,
                    de.account,
                    de.raw_object_id,
                    ar.raw_object_id,
                    ar.batch_id,
                    ab.source,
                    ab.filename,
                    ar.row_number,
                    ar.payload_json,
                    dr.raw_object_id,
                    dr.batch_id,
                    db.source,
                    db.filename,
                    dr.row_number,
                    dr.payload_json
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                left join canonical_events ae on ae.event_id = lot.source_event_id
                left join canonical_events de on de.event_id = l.source_event_id
                left join raw_objects ar on ar.raw_object_id = ae.raw_object_id
                left join raw_import_batches ab on ab.batch_id = ar.batch_id
                left join raw_objects dr on dr.raw_object_id = de.raw_object_id
                left join raw_import_batches db on db.batch_id = dr.batch_id
                where date_part('year', l.disposed_at)::integer = ?
                  and upper(l.asset) = ?
                order by l.disposed_at, l.tax_line_id
                limit ?
                """,
                [year, asset_key, max(1, min(limit, 1000))],
            ).fetchall()
        lines: list[TaxYearAssetFifoLine] = []
        quote_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            acquired_at = row[3]
            disposed_at = row[4]
            taxable = int(row[5]) <= 365
            acquisition_event = self._asset_fifo_event(row[11:24])
            disposal_event = self._asset_fifo_event(row[24:37])
            acquisition_raw = self._asset_fifo_raw(row[37:43])
            disposal_raw = self._asset_fifo_raw(row[43:49])
            for event in (acquisition_event, disposal_event):
                if event and event.quote_asset:
                    quote_counts[event.quote_asset.upper()] += 1
            lines.append(
                TaxYearAssetFifoLine(
                    tax_line_id=row[0],
                    asset=row[1],
                    quantity=row[2],
                    acquired_at=acquired_at.isoformat(),
                    disposed_at=disposed_at.isoformat(),
                    holding_days=row[5],
                    taxable=taxable,
                    acquisition_cost_eur=row[6],
                    disposal_proceeds_eur=row[7],
                    gain_loss_eur=row[8],
                    source_event_id=row[9],
                    lot_id=row[10],
                    acquisition_event=acquisition_event,
                    disposal_event=disposal_event,
                    acquisition_raw=acquisition_raw,
                    disposal_raw=disposal_raw,
                )
            )
        taxable_lines = [line for line in lines if line.taxable]
        tax_free_lines = [line for line in lines if not line.taxable]
        caveats: list[str] = []
        if not lines:
            caveats.append("Fuer dieses Asset gibt es im ausgewaehlten Jahr keine Tax-Lines.")
        if any(line.acquisition_raw is None or line.disposal_raw is None for line in lines):
            caveats.append(
                "Mindestens eine Tax-Line hat keinen vollstaendigen Rohdatenbeleg fuer Erwerb oder Veraeusserung."
            )
        if len(quote_counts) > 1 or (quote_counts and asset_key in quote_counts):
            caveats.append(
                "Das Asset taucht in Quote-Beinen auf. Gewinne koennen in Gegenwaehrungs-/Stablecoin-Zeilen sichtbar werden."
            )
        return TaxYearAssetFifoDrilldown(
            year=year,
            asset=asset_key,
            generated_at=datetime.now(timezone.utc).isoformat(),
            lines_count=len(lines),
            taxable_lines_count=len(taxable_lines),
            tax_free_lines_count=len(tax_free_lines),
            acquisition_cost_eur=sum((line.acquisition_cost_eur for line in lines), Decimal("0")),
            disposal_proceeds_eur=sum((line.disposal_proceeds_eur for line in lines), Decimal("0")),
            gain_loss_eur=sum((line.gain_loss_eur for line in lines), Decimal("0")),
            taxable_gain_loss_eur=sum((line.gain_loss_eur for line in taxable_lines), Decimal("0")),
            tax_free_gain_loss_eur=sum((line.gain_loss_eur for line in tax_free_lines), Decimal("0")),
            quote_asset_occurrences=dict(sorted(quote_counts.items())),
            lines=lines,
            caveats=caveats,
            methodology=(
                "Read-only Asset-FIFO-Drilldown aus vorhandenen tax_lines, tax_lots, "
                "canonical_events und raw_objects. Er berechnet FIFO nicht neu, sondern "
                "macht Erwerb, Veraeusserung, Haltefrist, EUR-Kosten, EUR-Erloese und "
                "Rohimport-Belege je Asset-Zeile sichtbar."
            ),
        )

    def asset_fifo_plausibility(
        self,
        year: int,
        *,
        limit: int = 100,
        min_abs_gain_eur: Decimal = Decimal("100"),
    ) -> TaxYearAssetFifoPlausibilityReport:
        with self.store.connect() as con:
            rows = con.execute(
                """
                with linked as (
                    select
                        date_part('year', l.disposed_at)::integer as year,
                        upper(l.asset) as tax_asset,
                        upper(coalesce(de.asset, '')) as disposal_asset,
                        upper(coalesce(de.quote_asset, '')) as disposal_quote_asset,
                        upper(coalesce(ae.asset, '')) as acquisition_asset,
                        upper(coalesce(ae.quote_asset, '')) as acquisition_quote_asset,
                        l.gain_loss_eur,
                        l.disposal_proceeds_eur,
                        l.tax_line_id
                    from tax_lines l
                    join tax_lots lot on lot.lot_id = l.lot_id
                    left join canonical_events de on de.event_id = l.source_event_id
                    left join canonical_events ae on ae.event_id = lot.source_event_id
                    where date_part('year', l.disposed_at)::integer = ?
                ),
                assets as (
                    select distinct asset from (
                        select tax_asset as asset from linked where tax_asset <> ''
                        union select disposal_asset from linked where disposal_asset <> ''
                        union select disposal_quote_asset from linked where disposal_quote_asset <> ''
                        union select acquisition_asset from linked where acquisition_asset <> ''
                        union select acquisition_quote_asset from linked where acquisition_quote_asset <> ''
                    )
                ),
                quote_assets as (
                    select
                        asset,
                        string_agg(distinct quote_asset, ',' order by quote_asset) as quote_assets
                    from (
                        select tax_asset as asset, disposal_quote_asset as quote_asset from linked
                        union all
                        select tax_asset as asset, acquisition_quote_asset as quote_asset from linked
                    )
                    where asset <> '' and quote_asset <> ''
                    group by asset
                ),
                asset_year as (
                    select
                        a.asset,
                        count(*) filter (where l.tax_asset = a.asset) as direct_lines,
                        coalesce(sum(l.gain_loss_eur) filter (where l.tax_asset = a.asset), 0) as direct_gain,
                        coalesce(sum(l.disposal_proceeds_eur) filter (where l.tax_asset = a.asset), 0) as direct_proceeds,
                        count(*) filter (
                            where l.tax_asset <> a.asset
                              and (
                                  l.disposal_asset = a.asset
                                  or l.disposal_quote_asset = a.asset
                                  or l.acquisition_asset = a.asset
                                  or l.acquisition_quote_asset = a.asset
                              )
                        ) as linked_lines,
                        coalesce(sum(l.gain_loss_eur) filter (
                            where l.tax_asset <> a.asset
                              and (
                                  l.disposal_asset = a.asset
                                  or l.disposal_quote_asset = a.asset
                                  or l.acquisition_asset = a.asset
                                  or l.acquisition_quote_asset = a.asset
                              )
                        ), 0) as linked_gain,
                        coalesce(sum(l.disposal_proceeds_eur) filter (
                            where l.tax_asset <> a.asset
                              and (
                                  l.disposal_asset = a.asset
                                  or l.disposal_quote_asset = a.asset
                                  or l.acquisition_asset = a.asset
                                  or l.acquisition_quote_asset = a.asset
                              )
                        ), 0) as linked_proceeds,
                        coalesce(qa.quote_assets, '') as quote_assets
                    from assets a
                    left join linked l on (
                        l.tax_asset = a.asset
                        or l.disposal_asset = a.asset
                        or l.disposal_quote_asset = a.asset
                        or l.acquisition_asset = a.asset
                        or l.acquisition_quote_asset = a.asset
                    )
                    left join quote_assets qa on qa.asset = a.asset
                    group by a.asset, qa.quote_assets
                )
                select
                    asset,
                    direct_lines,
                    direct_gain,
                    direct_proceeds,
                    linked_lines,
                    linked_gain,
                    linked_proceeds,
                    coalesce(quote_assets, '') as quote_assets
                from asset_year
                where abs(direct_gain) >= ?
                   or abs(linked_gain) >= ?
                   or linked_lines >= 20
                order by abs(linked_gain) desc, abs(direct_gain) desc, asset
                limit ?
                """,
                [
                    year,
                    min_abs_gain_eur,
                    min_abs_gain_eur,
                    max(1, min(limit, 500)),
                ],
            ).fetchall()
        report_rows: list[TaxYearAssetFifoPlausibilityRow] = []
        for row in rows:
            asset = row[0]
            direct_gain = row[2] or Decimal("0")
            linked_gain = row[5] or Decimal("0")
            direct_lines = int(row[1] or 0)
            linked_lines = int(row[4] or 0)
            reasons = self._asset_fifo_plausibility_reasons(
                direct_gain=direct_gain,
                linked_gain=linked_gain,
                direct_lines=direct_lines,
                linked_lines=linked_lines,
                min_abs_gain_eur=min_abs_gain_eur,
            )
            risk = self._asset_fifo_plausibility_risk(reasons)
            quote_assets = [item for item in str(row[7] or "").split(",") if item]
            report_rows.append(
                TaxYearAssetFifoPlausibilityRow(
                    year=year,
                    asset=asset,
                    risk_level=risk,
                    direct_tax_lines_count=direct_lines,
                    direct_gain_loss_eur=direct_gain,
                    direct_disposal_proceeds_eur=row[3] or Decimal("0"),
                    linked_tax_lines_count=linked_lines,
                    linked_gain_loss_eur=linked_gain,
                    linked_disposal_proceeds_eur=row[6] or Decimal("0"),
                    total_related_gain_loss_eur=direct_gain + linked_gain,
                    hidden_quote_gain_loss_eur=linked_gain if direct_lines else Decimal("0"),
                    quote_assets=quote_assets,
                    reasons=reasons,
                    drilldown_endpoint=f"/api/v1/tax-years/{year}/asset-fifo-drilldown?asset={asset}",
                )
            )
        return TaxYearAssetFifoPlausibilityReport(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            assets_count=len(report_rows),
            high_risk_assets_count=sum(1 for row in report_rows if row.risk_level == "high"),
            review_assets_count=sum(1 for row in report_rows if row.risk_level == "review"),
            ok_assets_count=sum(1 for row in report_rows if row.risk_level == "ok"),
            min_abs_gain_eur=min_abs_gain_eur,
            rows=report_rows,
            methodology=(
                "Read-only All-Asset-FIFO-Plausibilitaet. Der Report vergleicht "
                "das direkte FIFO-Ergebnis eines Assets mit Tax-Lines, in denen "
                "dasselbe Asset nur als Erwerbs-, Veraeusserungs- oder Quote-Bein "
                "auftaucht. So werden verdeckte Quote-/Stablecoin-Effekte wie beim "
                "TRUMP/USDT-Fall jahresweit priorisiert."
            ),
        )

    def asset_fifo_correction_review(
        self,
        year: int,
        *,
        limit: int = 100,
        min_abs_gain_eur: Decimal = Decimal("100"),
    ) -> TaxYearAssetFifoCorrectionReviewReport:
        plausibility = self.asset_fifo_plausibility(
            year,
            limit=limit,
            min_abs_gain_eur=min_abs_gain_eur,
        )
        rows: list[TaxYearAssetFifoCorrectionReviewRow] = []
        for item in plausibility.rows:
            raw_counts = self._asset_fifo_related_raw_counts(year, item.asset)
            role_counts = self._asset_fifo_related_role_counts(year, item.asset)
            action, tax_impact, conclusion, next_step = self._asset_fifo_correction_decision(
                item,
                role_counts=role_counts,
                related_missing_raw_evidence_count=raw_counts["missing"],
                min_abs_gain_eur=min_abs_gain_eur,
            )
            rows.append(
                TaxYearAssetFifoCorrectionReviewRow(
                    year=year,
                    asset=item.asset,
                    risk_level=item.risk_level,
                    recommended_action=action,
                    tax_sum_impact=tax_impact,
                    direct_gain_loss_eur=item.direct_gain_loss_eur,
                    linked_gain_loss_eur=item.linked_gain_loss_eur,
                    total_related_gain_loss_eur=item.total_related_gain_loss_eur,
                    direct_tax_lines_count=item.direct_tax_lines_count,
                    linked_tax_lines_count=item.linked_tax_lines_count,
                    related_raw_evidence_count=raw_counts["present"],
                    related_missing_raw_evidence_count=raw_counts["missing"],
                    conclusion=conclusion,
                    next_step=next_step,
                    reasons=item.reasons,
                    drilldown_endpoint=item.drilldown_endpoint,
                )
            )
        return TaxYearAssetFifoCorrectionReviewReport(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            rows_count=len(rows),
            possible_recalculation_assets_count=sum(
                1 for row in rows if row.tax_sum_impact == "possible_recalculation_after_review"
            ),
            attribution_review_assets_count=sum(
                1 for row in rows if row.tax_sum_impact == "already_in_existing_tax_lines"
            ),
            no_action_assets_count=sum(1 for row in rows if row.tax_sum_impact == "none_expected"),
            rows=rows,
            methodology=(
                "Read-only Korrektur-/Belegreview auf Basis des All-Asset-FIFO-"
                "Plausibilitaetsreports. Der Report aendert keine Tax-Lines und "
                "zaehlt verknuepfte Quote-Bein-Werte nicht zusaetzlich zur "
                "Jahressumme. Er priorisiert, ob nur die Darstellung/Attribution "
                "erklaert werden muss oder ob Normalizer/FIFO nach Rohbelegpruefung "
                "neu bewertet werden koennten."
            ),
        )

    def turnover_audit(self, year: int, *, limit: int = 20) -> TaxYearTurnoverAudit:
        lines = [line for line in self._tax_lines() if line.disposed_at.year == year]
        taxable = [line for line in lines if self._is_taxable_private_disposal(line)]
        tax_free = [line for line in lines if not self._is_taxable_private_disposal(line)]
        gross_proceeds = sum((line.disposal_proceeds_eur for line in lines), Decimal("0"))
        taxable_gain = sum((line.gain_loss_eur for line in taxable), Decimal("0"))
        tax_free_gain = sum((line.gain_loss_eur for line in tax_free), Decimal("0"))
        taxable_proceeds = sum((line.disposal_proceeds_eur for line in taxable), Decimal("0"))
        tax_free_proceeds = sum((line.disposal_proceeds_eur for line in tax_free), Decimal("0"))
        stablecoin_lines = [line for line in lines if self._is_stablecoin_like(line.asset)]
        stablecoin_proceeds = sum((line.disposal_proceeds_eur for line in stablecoin_lines), Decimal("0"))
        stablecoin_gain = sum((line.gain_loss_eur for line in stablecoin_lines), Decimal("0"))
        external = self.external_inflow_report(year, limit=0)
        review_unmatched_value = external.review_value_eur + external.unmatched_value_eur
        caveats: list[str] = [
            (
                "Handels-/Swap-Volumen ist die EUR-Bewertung von Verkaeufen und "
                "Crypto-zu-Crypto-Tauschvorgaengen. Es ist kein Nachweis, dass dieser "
                "Betrag als EUR eingezahlt oder ausgezahlt wurde."
            )
        ]
        if stablecoin_proceeds:
            caveats.append(
                "Stablecoin-Handelsvolumen kann hoch sein, obwohl der "
                "Gewinn/Verlust nahe null liegt; relevant fuer die Steuer ist die "
                "FIFO-Differenz aus Erloes minus Anschaffungskosten."
            )
            stablecoin_gain_ratio = abs(stablecoin_gain) / stablecoin_proceeds if stablecoin_proceeds else Decimal("0")
            if abs(stablecoin_gain) >= Decimal("100") and stablecoin_gain_ratio >= Decimal("0.01"):
                caveats.append(
                    "Stablecoin-FIFO-Ergebnis ist materiell. Das ist ein Plausibilitaetsrisiko "
                    "und sollte gegen echte Stablecoin-Anschaffungen, FX-Umrechnung, "
                    "Quote-Beine und fehlende Transfer-Herkunft geprueft werden."
                )
        if external.review_count or external.unmatched_count:
            caveats.append(
                "Externe Solana-Zufluesse sind noch nicht voll belegt. Diese Werte "
                "duerfen nicht als sauber erklaert gelten, bis Transfer-/Herkunftsbelege "
                "zugeordnet sind."
            )
        return TaxYearTurnoverAudit(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            gross_disposal_proceeds_eur=gross_proceeds,
            taxable_gain_loss_eur=taxable_gain,
            tax_free_gain_loss_eur=tax_free_gain,
            combined_gain_loss_eur=taxable_gain + tax_free_gain,
            taxable_disposal_proceeds_eur=taxable_proceeds,
            tax_free_disposal_proceeds_eur=tax_free_proceeds,
            stablecoin_gross_disposal_proceeds_eur=stablecoin_proceeds,
            stablecoin_gain_loss_eur=stablecoin_gain,
            tax_lines_count=len(taxable),
            tax_free_lines_count=len(tax_free),
            external_inflows_review_count=external.review_count,
            external_inflows_unmatched_count=external.unmatched_count,
            external_inflows_review_unmatched_value_eur=review_unmatched_value,
            plain_language_summary=self._turnover_plain_language_summary(
                year,
                gross_proceeds=gross_proceeds,
                taxable_gain=taxable_gain,
                tax_free_gain=tax_free_gain,
                stablecoin_proceeds=stablecoin_proceeds,
                stablecoin_gain=stablecoin_gain,
                external_value=review_unmatched_value,
            ),
            caveats=caveats,
            top_assets_by_proceeds=self._turnover_assets(lines, sort_by="proceeds")[:limit],
            top_assets_by_gain=self._turnover_assets(lines, sort_by="gain")[:limit],
            top_sources_by_proceeds=self._turnover_sources(year, limit=limit),
            top_taxable_lines_by_gain=[
                self._driver_line(line, taxable=True)
                for line in sorted(taxable, key=lambda item: abs(item.gain_loss_eur), reverse=True)[:limit]
            ],
            top_lines_by_proceeds=[
                self._driver_line(line, taxable=self._is_taxable_private_disposal(line))
                for line in sorted(lines, key=lambda item: item.disposal_proceeds_eur, reverse=True)[:limit]
            ],
            methodology=(
                "Read-only Jahresumsatz-Audit aus bestehenden Tax-Lines und Canonical Events. "
                "Berechnet keine FIFO-Werte neu, sondern erklaert die bereits vorhandenen "
                "Handels-/Swap-Volumen, steuerpflichtigen Ergebnisse, steuerfreien Ergebnisse und "
                "Stablecoin-/Quellen-Treiber."
            ),
        )

    def turnover_audit_summary(self, *, limit: int = 20) -> TaxYearsTurnoverAuditSummary:
        rows = [
            self._turnover_summary_row(self.turnover_audit(year, limit=limit))
            for year in self._available_years()
        ]
        return TaxYearsTurnoverAuditSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            years=rows,
            high_risk_years_count=sum(1 for row in rows if row.risk_level == "high"),
            review_years_count=sum(1 for row in rows if row.risk_level == "review"),
            ok_years_count=sum(1 for row in rows if row.risk_level == "ok"),
            methodology=(
                "Read-only Sammelaudit ueber alle verfuegbaren Steuerjahre. "
                "Bewertet Handels-/Swap-Volumen, steuerpflichtige Ergebnisse, steuerfreie "
                "Ergebnisse, Stablecoin-FIFO-Ergebnis und externe Solana-Zufluesse. "
                "Schreibt keine Steuerdaten und ersetzt keine Einzelbelegpruefung."
            ),
        )

    def solana_program_income_review(
        self,
        year: int | None = None,
        *,
        limit: int = 200,
    ) -> TaxSolanaProgramIncomeReview:
        rows = self._solana_program_income_rows(year=year)
        total_value = sum((row.value_eur or Decimal("0") for row in rows), Decimal("0"))
        asset_groups: dict[tuple[int, str], TaxSolanaProgramIncomeAssetSummary] = {}
        for row in rows:
            row_year = datetime.fromisoformat(row.event_time).year
            key = (row_year, row.asset.upper())
            item = asset_groups.setdefault(
                key,
                TaxSolanaProgramIncomeAssetSummary(year=row_year, asset=row.asset.upper()),
            )
            item.events_count += 1
            item.quantity += row.quantity
            item.value_eur += row.value_eur or Decimal("0")
        asset_summaries = sorted(asset_groups.values(), key=lambda item: abs(item.value_eur), reverse=True)
        year_groups: dict[int, TaxSolanaProgramIncomeYearSummary] = {}
        for item in asset_summaries:
            summary = year_groups.setdefault(
                item.year,
                TaxSolanaProgramIncomeYearSummary(year=item.year),
            )
            summary.events_count += item.events_count
            summary.value_eur += item.value_eur
            summary.assets_count += 1
            if len(summary.top_assets) < 8:
                summary.top_assets.append(item)
        return TaxSolanaProgramIncomeReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            events_count=len(rows),
            total_value_eur=total_value,
            years=sorted(year_groups.values(), key=lambda item: item.year),
            assets=asset_summaries[:limit],
            rows=sorted(rows, key=lambda item: abs(item.value_eur or Decimal("0")), reverse=True)[:limit],
            methodology=(
                "Read-only Drilldown fuer Solana-income-Events mit weiterem "
                "Programm-/Transfer-/Unknown-Kontext im selben tx_id. Diese Events "
                "werden nicht als externe Zufluesse gewertet, sondern als "
                "Swap-/Programm-/Quote-Bein-Plausibilitaet fuer Stablecoin/FIFO "
                "geprueft."
            ),
        )

    def helium_swap_context_review(
        self,
        year: int | None = None,
        *,
        limit: int = 200,
    ) -> TaxHeliumSwapContextReview:
        program_rows = [
            row
            for row in self._solana_program_income_rows(
                year=year,
                classifications={
                    "solana_program_or_swap_income_review",
                    "solana_swap_or_transfer_with_outgoing_review",
                },
            )
            if row.asset.upper() in HELIUM_REWARD_ASSETS
        ]
        program_rows.extend(self._helium_solana_trade_context_rows(year=year))
        reward_report = self.reward_trading_separation(
            years=[year] if year is not None else [item for item in self._available_years() if 2021 <= item <= 2026],
            assets=HELIUM_REWARD_ASSETS,
        )
        reward_by_year_asset = {
            (row.year, row.asset.upper()): row
            for row in reward_report.rows
        }
        trade_by_year_asset = self._helium_trade_tax_line_summary_by_year_asset()

        asset_groups: dict[tuple[int, str], TaxHeliumSwapContextAssetSummary] = {}
        row_items: list[TaxHeliumSwapContextRow] = []
        for row in program_rows:
            row_year = datetime.fromisoformat(row.event_time).year
            asset = row.asset.upper()
            key = (row_year, asset)
            asset_item = asset_groups.setdefault(
                key,
                TaxHeliumSwapContextAssetSummary(year=row_year, asset=asset),
            )
            asset_item.swap_context_events_count += 1
            asset_item.swap_context_quantity += row.quantity
            asset_item.swap_context_value_eur += row.value_eur or Decimal("0")
            row_items.append(
                TaxHeliumSwapContextRow(
                    event_id=row.event_id,
                    event_time=row.event_time,
                    year=row_year,
                    source=row.source,
                    account=row.account,
                    asset=asset,
                    quantity=row.quantity,
                    value_eur=row.value_eur,
                    tx_id=row.tx_id,
                    tx_total_count=row.tx_total_count,
                    tx_positive_count=row.tx_positive_count,
                    tx_negative_count=row.tx_negative_count,
                    tx_assets=row.tx_assets,
                    review_reason=self._helium_swap_context_reason(row),
                    fifo_drilldown_endpoint=f"/api/v1/tax-years/{row_year}/asset-fifo-drilldown?asset={asset}",
                )
            )

        for key in set(asset_groups) | set(reward_by_year_asset) | set(trade_by_year_asset):
            row_year, asset = key
            if year is not None and row_year != year:
                continue
            asset_item = asset_groups.setdefault(
                key,
                TaxHeliumSwapContextAssetSummary(year=row_year, asset=asset),
            )
            reward = reward_by_year_asset.get(key)
            if reward is not None:
                asset_item.reward_income_eur = reward.reward_income_eur
                asset_item.reward_quantity = reward.reward_quantity
                asset_item.reward_events_count = reward.reward_events_count
            trade = trade_by_year_asset.get(key, {})
            asset_item.taxable_trade_gain_loss_eur = trade.get("taxable_gain_loss_eur", Decimal("0"))
            asset_item.tax_free_trade_gain_loss_eur = trade.get("tax_free_gain_loss_eur", Decimal("0"))
            asset_item.total_trade_gain_loss_eur = (
                asset_item.taxable_trade_gain_loss_eur + asset_item.tax_free_trade_gain_loss_eur
            )
            asset_item.taxable_trade_lines_count = int(trade.get("taxable_lines_count", 0))
            asset_item.tax_free_trade_lines_count = int(trade.get("tax_free_lines_count", 0))

        year_groups: dict[int, TaxHeliumSwapContextYearSummary] = {}
        for item in asset_groups.values():
            summary = year_groups.setdefault(item.year, TaxHeliumSwapContextYearSummary(year=item.year))
            summary.swap_context_events_count += item.swap_context_events_count
            summary.swap_context_value_eur += item.swap_context_value_eur
            summary.taxable_trade_gain_loss_eur += item.taxable_trade_gain_loss_eur
            summary.tax_free_trade_gain_loss_eur += item.tax_free_trade_gain_loss_eur
            summary.total_trade_gain_loss_eur += item.total_trade_gain_loss_eur
            summary.reward_income_eur += item.reward_income_eur
            summary.assets_count += 1

        assets = sorted(
            asset_groups.values(),
            key=lambda item: (
                item.year,
                -abs(item.swap_context_value_eur),
                item.asset,
            ),
        )
        row_items.sort(key=lambda item: (item.year, -abs(item.value_eur or Decimal("0")), item.event_time))
        return TaxHeliumSwapContextReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            events_count=len(program_rows),
            total_context_value_eur=sum((row.value_eur or Decimal("0") for row in row_items), Decimal("0")),
            total_taxable_trade_gain_loss_eur=sum((item.taxable_trade_gain_loss_eur for item in assets), Decimal("0")),
            total_tax_free_trade_gain_loss_eur=sum((item.tax_free_trade_gain_loss_eur for item in assets), Decimal("0")),
            total_trade_gain_loss_eur=sum((item.total_trade_gain_loss_eur for item in assets), Decimal("0")),
            total_reward_income_eur=sum((item.reward_income_eur for item in assets), Decimal("0")),
            years=sorted(year_groups.values(), key=lambda item: item.year),
            assets=assets[:limit],
            rows=row_items[:limit],
            methodology=(
                "Read-only Helium-Solana-Swap-Bruecke fuer HNT/IOT/MOBILE. "
                "Solana-Programm-/Swap-Kontexte werden ausdruecklich nicht als "
                "Reward/Mining deklariert, sondern neben vorhandenen FIFO-Tax-Lines "
                "als Trading-/Swap-Kontext ausgewiesen. Der Report schreibt keine "
                "Events, Lots, Preise oder Steuerzeilen."
            ),
        )

    def helium_swap_evidence_review(
        self,
        year: int | None = None,
        *,
        limit: int = 50,
    ) -> TaxHeliumSwapEvidenceReview:
        context = self.helium_swap_context_review(year=year, limit=100_000)
        grouped: dict[str, dict[str, object]] = {}
        for row in context.rows:
            if not row.tx_id:
                continue
            item = grouped.setdefault(
                row.tx_id,
                {
                    "tx_id": row.tx_id,
                    "year": row.year,
                    "first_event_time": row.event_time,
                    "account": row.account,
                    "assets": set(),
                    "events_count": 0,
                    "positive_events_count": 0,
                    "negative_events_count": 0,
                    "context_value_eur": Decimal("0"),
                    "max_event_value_eur": Decimal("0"),
                    "review_reasons": set(),
                },
            )
            if row.event_time < str(item["first_event_time"]):
                item["first_event_time"] = row.event_time
            item["year"] = min(int(item["year"]), row.year)
            if not item.get("account") and row.account:
                item["account"] = row.account
            assets = item["assets"]
            if isinstance(assets, set):
                assets.add(row.asset.upper())
                for asset in (row.tx_assets or "").split(","):
                    normalized = asset.strip().upper()
                    if normalized:
                        assets.add(normalized)
            item["events_count"] = int(item["events_count"]) + 1
            item["positive_events_count"] = int(item["positive_events_count"]) + row.tx_positive_count
            item["negative_events_count"] = int(item["negative_events_count"]) + row.tx_negative_count
            value = row.value_eur or Decimal("0")
            item["context_value_eur"] = item["context_value_eur"] + value  # type: ignore[operator]
            item["max_event_value_eur"] = max(  # type: ignore[assignment]
                item["max_event_value_eur"],
                abs(value),
            )
            reasons = item["review_reasons"]
            if isinstance(reasons, set):
                reasons.add(row.review_reason)

        raw_by_tx = self._raw_evidence_summary_by_tx(set(grouped))
        rows: list[TaxHeliumSwapEvidenceRow] = []
        for tx_id, item in grouped.items():
            raw = raw_by_tx.get(tx_id, {})
            raw_count = int(raw.get("raw_evidence_count", 0) or 0)
            raw_filenames = [str(value) for value in raw.get("raw_filenames", []) if str(value or "").strip()]
            raw_sources = [str(value) for value in raw.get("raw_sources", []) if str(value or "").strip()]
            assets = item.get("assets", set())
            review_reasons = item.get("review_reasons", set())
            row_year = int(item["year"])
            main_asset = self._primary_helium_asset_from_set(assets if isinstance(assets, set) else set())
            rows.append(
                TaxHeliumSwapEvidenceRow(
                    tx_id=tx_id,
                    year=row_year,
                    first_event_time=str(item["first_event_time"]),
                    account=str(item["account"]) if item.get("account") else None,
                    assets=", ".join(sorted(assets)) if isinstance(assets, set) else "",
                    events_count=int(item["events_count"]),
                    positive_events_count=int(item["positive_events_count"]),
                    negative_events_count=int(item["negative_events_count"]),
                    context_value_eur=item["context_value_eur"],  # type: ignore[arg-type]
                    max_event_value_eur=item["max_event_value_eur"],  # type: ignore[arg-type]
                    raw_evidence_count=raw_count,
                    raw_filenames=raw_filenames,
                    raw_sources=raw_sources,
                    evidence_status="raw_evidence_ready" if raw_count else "missing_raw_evidence",
                    review_reason=", ".join(sorted(review_reasons)) if isinstance(review_reasons, set) else "",
                    context_endpoint=f"/api/v1/tax-years/{row_year}/helium-swap-context",
                    fifo_drilldown_endpoint=f"/api/v1/tax-years/{row_year}/asset-fifo-drilldown?asset={main_asset}",
                )
            )
        rows.sort(key=lambda item: (item.evidence_status != "missing_raw_evidence", -abs(item.max_event_value_eur), item.tx_id))
        limited_rows = rows[:limit]
        return TaxHeliumSwapEvidenceReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            tx_count=len(rows),
            raw_evidence_ready_count=sum(1 for row in rows if row.raw_evidence_count > 0),
            raw_evidence_missing_count=sum(1 for row in rows if row.raw_evidence_count == 0),
            total_context_value_eur=sum((row.context_value_eur for row in rows), Decimal("0")),
            rows=limited_rows,
            methodology=(
                "Read-only Top-TxID-Belegmatrix fuer HNT/IOT/MOBILE-Swap-/Trading-Kontexte. "
                "Die Auswertung gruppiert vorhandene Helium-Swap-Kontext-Events je tx_id "
                "und prueft lokal, ob kanonische Events mit Raw-Object-/Import-Batch-Belegen "
                "vorhanden sind. Es werden keine externen APIs abgefragt und keine Steuer-, "
                "Lot- oder Importdaten geschrieben."
            ),
        )

    def stablecoin_fifo_review(
        self,
        year: int | None = None,
        *,
        limit: int = 200,
    ) -> TaxStablecoinFifoReview:
        rows = self._stablecoin_fifo_lines(year=year)
        total_proceeds = sum((row.disposal_proceeds_eur for row in rows), Decimal("0"))
        total_cost = sum((row.acquisition_cost_eur for row in rows), Decimal("0"))
        total_gain = sum((row.gain_loss_eur for row in rows), Decimal("0"))
        taxable_gain = sum((row.gain_loss_eur for row in rows if row.taxable), Decimal("0"))
        tax_free_gain = total_gain - taxable_gain
        asset_groups: dict[tuple[int, str], TaxStablecoinFifoAssetSummary] = {}
        source_groups: dict[tuple[int, str, str, str, str | None, str | None, str | None], TaxStablecoinFifoSourceSummary] = {}
        for row in rows:
            asset_key = (row.year, row.asset.upper())
            asset_item = asset_groups.setdefault(
                asset_key,
                TaxStablecoinFifoAssetSummary(year=row.year, asset=row.asset.upper()),
            )
            asset_item.tax_line_count += 1
            asset_item.disposal_proceeds_eur += row.disposal_proceeds_eur
            asset_item.acquisition_cost_eur += row.acquisition_cost_eur
            asset_item.gain_loss_eur += row.gain_loss_eur
            if row.taxable:
                asset_item.taxable_gain_loss_eur += row.gain_loss_eur
            else:
                asset_item.tax_free_gain_loss_eur += row.gain_loss_eur

            source_key = (
                row.year,
                row.asset.upper(),
                row.disposal_source or "unknown",
                row.disposal_event_type or "unknown",
                row.disposal_quote_asset,
                row.acquisition_source,
                row.acquisition_event_type,
            )
            source_item = source_groups.setdefault(
                source_key,
                TaxStablecoinFifoSourceSummary(
                    year=row.year,
                    asset=row.asset.upper(),
                    disposal_source=row.disposal_source or "unknown",
                    disposal_event_type=row.disposal_event_type or "unknown",
                    disposal_quote_asset=row.disposal_quote_asset,
                    acquisition_source=row.acquisition_source,
                    acquisition_event_type=row.acquisition_event_type,
                ),
            )
            source_item.tax_line_count += 1
            source_item.disposal_proceeds_eur += row.disposal_proceeds_eur
            source_item.acquisition_cost_eur += row.acquisition_cost_eur
            source_item.gain_loss_eur += row.gain_loss_eur
            if row.acquisition_evidence_status == "raw_import_row_available":
                source_item.acquisition_raw_evidence_count += 1
            else:
                source_item.acquisition_missing_raw_evidence_count += 1

        return TaxStablecoinFifoReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            tax_line_count=len(rows),
            disposal_proceeds_eur=total_proceeds,
            acquisition_cost_eur=total_cost,
            gain_loss_eur=total_gain,
            taxable_gain_loss_eur=taxable_gain,
            tax_free_gain_loss_eur=tax_free_gain,
            assets=sorted(asset_groups.values(), key=lambda item: abs(item.gain_loss_eur), reverse=True),
            sources=sorted(source_groups.values(), key=lambda item: abs(item.gain_loss_eur), reverse=True)[:limit],
            rows=sorted(rows, key=lambda item: abs(item.gain_loss_eur), reverse=True)[:limit],
            methodology=(
                "Read-only Stablecoin-FIFO-Drilldown aus bestehenden tax_lines, "
                "tax_lots und canonical_events. Zeigt, welche Stablecoin-Lots und "
                "welche Disposal-/Acquisition-Quellen die materiellen Gewinne oder "
                "Verluste verursachen. Berechnet FIFO nicht neu und schreibt keine Daten."
            ),
        )

    def stablecoin_quote_leg_review(
        self,
        year: int | None = None,
        *,
        limit: int = 200,
    ) -> TaxStablecoinQuoteLegReview:
        rows = self._stablecoin_quote_leg_rows(year=year)
        summaries: dict[tuple[int, str, str, str], TaxStablecoinQuoteLegSummary] = {}
        for row in rows:
            key = (row.year, row.source, row.stable_asset, row.stable_role)
            item = summaries.setdefault(
                key,
                TaxStablecoinQuoteLegSummary(
                    year=row.year,
                    source=row.source,
                    stable_asset=row.stable_asset,
                    stable_role=row.stable_role,
                ),
            )
            item.events_count += 1
            if row.expected_tax_line:
                item.expected_tax_line_events_count += 1
            if row.expected_tax_line and row.stable_tax_lines_count == 0:
                item.missing_expected_tax_line_events_count += 1
            item.stable_tax_lines_count += row.stable_tax_lines_count
            item.stable_gain_loss_eur += row.stable_gain_loss_eur
            item.stable_disposal_proceeds_eur += row.stable_disposal_proceeds_eur

        stable_tax_lines_count = sum(row.stable_tax_lines_count for row in rows)
        stable_proceeds = sum((row.stable_disposal_proceeds_eur for row in rows), Decimal("0"))
        stable_gain = sum((row.stable_gain_loss_eur for row in rows), Decimal("0"))
        expected_count = sum(1 for row in rows if row.expected_tax_line)
        missing_expected_count = sum(1 for row in rows if row.expected_tax_line and row.stable_tax_lines_count == 0)
        ordered_rows = sorted(
            rows,
            key=lambda item: (
                item.review_reason != "missing_expected_stablecoin_tax_line",
                item.review_reason != "stable_to_stable_quote_leg_review",
                -abs(item.stable_gain_loss_eur),
                item.event_time,
                item.event_id,
            ),
        )
        return TaxStablecoinQuoteLegReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            events_count=len(rows),
            expected_tax_line_events_count=expected_count,
            missing_expected_tax_line_events_count=missing_expected_count,
            same_stable_pair_events_count=sum(1 for row in rows if row.stable_role == "same_stable_asset_and_quote"),
            stable_to_stable_events_count=sum(1 for row in rows if row.stable_role in {"stable_to_stable", "same_stable_asset_and_quote"}),
            stable_tax_lines_count=stable_tax_lines_count,
            stable_disposal_proceeds_eur=stable_proceeds,
            stable_gain_loss_eur=stable_gain,
            summaries=sorted(summaries.values(), key=lambda item: abs(item.stable_gain_loss_eur), reverse=True)[:limit],
            rows=ordered_rows[:limit],
            methodology=(
                "Read-only Stablecoin-Quote-Bein-Pruefung aus canonical_events und "
                "bestehenden tax_lines. Erwartet Tax-Lines fuer Stablecoin-Abgaenge "
                "als Asset oder Quote-Bein bei Buy-Events, weist erhaltene "
                "Stablecoin-Quote-Lots aus und markiert Stablecoin-zu-Stablecoin-"
                "Events separat. Berechnet FIFO nicht neu und schreibt keine Daten."
            ),
        )

    def solana_stablecoin_swap_context_review(
        self,
        year: int | None = None,
        *,
        limit: int = 200,
    ) -> TaxSolanaStablecoinSwapContextReview:
        quote_rows = [
            row
            for row in self._stablecoin_quote_leg_rows(year=year)
            if row.source == "solana_rpc"
            and row.tx_id
            and (
                row.expected_tax_line
                or row.stable_role in {"stable_to_stable", "same_stable_asset_and_quote"}
                or abs(row.stable_gain_loss_eur) >= Decimal("100")
            )
        ]
        tx_context = self._stablecoin_solana_tx_context({str(row.tx_id) for row in quote_rows if row.tx_id})
        token_status = self._jupiter_token_status_by_symbol()
        rows: list[TaxSolanaStablecoinSwapContextRow] = []
        for row in quote_rows:
            context = tx_context.get(str(row.tx_id), {})
            classification, confidence, recommended_action = self._solana_stablecoin_swap_classification(
                quote_row=row,
                tx_assets=str(context.get("tx_assets") or ""),
                tx_total_count=int(context.get("tx_total_count") or 0),
                raw_evidence_count=int(context.get("raw_evidence_count") or 0),
            )
            jupiter_asset_status = token_status.get(row.asset.upper(), "unknown")
            jupiter_quote_status = token_status.get(str(row.quote_asset or "").upper(), "unknown")
            rows.append(
                TaxSolanaStablecoinSwapContextRow(
                    event_id=row.event_id,
                    year=row.year,
                    event_time=row.event_time,
                    account=row.account,
                    asset=row.asset,
                    quantity=row.quantity,
                    quote_asset=row.quote_asset,
                    quote_quantity=row.quote_quantity,
                    tx_id=row.tx_id,
                    stable_role=row.stable_role,
                    expected_tax_effect=row.expected_tax_effect,
                    stable_tax_lines_count=row.stable_tax_lines_count,
                    stable_disposal_proceeds_eur=row.stable_disposal_proceeds_eur,
                    stable_gain_loss_eur=row.stable_gain_loss_eur,
                    tx_total_count=int(context.get("tx_total_count") or 0),
                    tx_positive_count=int(context.get("tx_positive_count") or 0),
                    tx_negative_count=int(context.get("tx_negative_count") or 0),
                    tx_zero_count=int(context.get("tx_zero_count") or 0),
                    tx_assets=str(context.get("tx_assets") or ""),
                    tx_event_types=str(context.get("tx_event_types") or ""),
                    raw_evidence_count=int(context.get("raw_evidence_count") or 0),
                    raw_filenames=list(context.get("raw_filenames") or []),
                    jupiter_asset_status=jupiter_asset_status,
                    jupiter_quote_status=jupiter_quote_status,
                    classification=classification,
                    confidence=confidence,
                    review_reason=self._solana_stablecoin_swap_review_reason(
                        row=row,
                        raw_evidence_count=int(context.get("raw_evidence_count") or 0),
                        jupiter_asset_status=jupiter_asset_status,
                        jupiter_quote_status=jupiter_quote_status,
                    ),
                    recommended_action=recommended_action,
                )
            )

        asset_groups: dict[tuple[int, str, str | None], TaxSolanaStablecoinSwapAssetSummary] = {}
        for row in rows:
            key = (row.year, row.asset, row.quote_asset)
            item = asset_groups.setdefault(
                key,
                TaxSolanaStablecoinSwapAssetSummary(year=row.year, asset=row.asset, quote_asset=row.quote_asset),
            )
            item.events_count += 1
            item.stable_tax_lines_count += row.stable_tax_lines_count
            item.stable_gain_loss_eur += row.stable_gain_loss_eur
            item.stable_disposal_proceeds_eur += row.stable_disposal_proceeds_eur
            item.raw_evidence_count += row.raw_evidence_count

        rows.sort(
            key=lambda item: (
                item.classification != "solana_swap_stablecoin_quote_disposal",
                item.classification != "solana_stablecoin_conversion_review",
                -abs(item.stable_gain_loss_eur),
                item.event_time,
                item.event_id,
            )
        )
        return TaxSolanaStablecoinSwapContextReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            events_count=len(rows),
            material_events_count=sum(1 for row in rows if abs(row.stable_gain_loss_eur) >= Decimal("100")),
            stable_to_stable_events_count=sum(1 for row in rows if row.stable_role in {"stable_to_stable", "same_stable_asset_and_quote"}),
            missing_raw_evidence_count=sum(1 for row in rows if row.raw_evidence_count == 0),
            verified_or_known_token_events_count=sum(
                1
                for row in rows
                if row.jupiter_asset_status in {"verified", "unverified_plausible"}
                or row.jupiter_quote_status in {"verified", "unverified_plausible"}
            ),
            stable_tax_lines_count=sum(row.stable_tax_lines_count for row in rows),
            stable_disposal_proceeds_eur=sum((row.stable_disposal_proceeds_eur for row in rows), Decimal("0")),
            stable_gain_loss_eur=sum((row.stable_gain_loss_eur for row in rows), Decimal("0")),
            assets=sorted(asset_groups.values(), key=lambda item: abs(item.stable_gain_loss_eur), reverse=True)[:limit],
            rows=rows[:limit],
            methodology=(
                "Read-only Solana-Stablecoin-Swap-Kontext aus bestehenden "
                "canonical_events, raw_objects und Jupiter-Metadata-Cache. "
                "Der Endpunkt klassifiziert Solana-RPC-Stablecoin-Quote-Beine "
                "als Swap-/Conversion-/Review-Kontext, schreibt keine Imports, "
                "keine Preise und keine FIFO-/Steuerdaten."
            ),
        )

    def solana_stablecoin_fx_review(
        self,
        year: int | None = None,
        *,
        limit: int = 200,
    ) -> TaxSolanaStablecoinFxReview:
        swap_rows = [
            row
            for row in self.solana_stablecoin_swap_context_review(year=year, limit=10_000).rows
            if row.expected_tax_effect == "stable_quote_disposal"
            and row.quote_asset
            and row.quote_quantity is not None
            and row.stable_tax_lines_count > 0
        ]
        price_lookup = HistoricalPriceLookup(self.store)
        rows: list[TaxSolanaStablecoinFxRow] = []
        for row in swap_rows:
            event_time = datetime.fromisoformat(row.event_time)
            stable_quantity = abs(row.quote_quantity or Decimal("0"))
            price_point = price_lookup.at_or_before(str(row.quote_asset), event_time)
            implied_price = (
                row.stable_disposal_proceeds_eur / stable_quantity
                if stable_quantity > 0
                else None
            )
            price_age_days: int | None = None
            price_delta_pct: Decimal | None = None
            selected_price: Decimal | None = None
            selected_source: str | None = None
            selected_priced_at: str | None = None
            if price_point is not None:
                selected_price = price_point.price_eur
                selected_source = price_point.source
                selected_priced_at = price_point.priced_at.isoformat()
                price_age_days = max((event_time.date() - price_point.priced_at.date()).days, 0)
                if implied_price is not None and selected_price > 0:
                    price_delta_pct = abs(implied_price - selected_price) / selected_price * Decimal("100")
            fx_basis_status = self._stablecoin_fx_basis_status(selected_source)
            review_reason, recommended_action = self._stablecoin_fx_review_reason(
                price_point_source=selected_source,
                price_age_days=price_age_days,
                price_delta_pct=price_delta_pct,
                gain_loss_eur=row.stable_gain_loss_eur,
            )
            rows.append(
                TaxSolanaStablecoinFxRow(
                    event_id=row.event_id,
                    year=row.year,
                    event_time=row.event_time,
                    asset=row.asset,
                    quantity=row.quantity,
                    stable_asset=str(row.quote_asset),
                    stable_quantity=stable_quantity,
                    tx_id=row.tx_id,
                    stable_tax_lines_count=row.stable_tax_lines_count,
                    stable_disposal_proceeds_eur=row.stable_disposal_proceeds_eur,
                    stable_gain_loss_eur=row.stable_gain_loss_eur,
                    implied_stable_price_eur=implied_price,
                    selected_price_eur=selected_price,
                    selected_price_source=selected_source,
                    selected_priced_at=selected_priced_at,
                    price_age_days=price_age_days,
                    price_delta_pct=price_delta_pct,
                    fx_basis_status=fx_basis_status,
                    review_reason=review_reason,
                    recommended_action=recommended_action,
                )
            )

        asset_groups: dict[tuple[int, str, str | None], TaxSolanaStablecoinFxAssetSummary] = {}
        for row in rows:
            key = (row.year, row.stable_asset.upper(), row.selected_price_source)
            item = asset_groups.setdefault(
                key,
                TaxSolanaStablecoinFxAssetSummary(
                    year=row.year,
                    stable_asset=row.stable_asset.upper(),
                    price_source=row.selected_price_source,
                ),
            )
            item.events_count += 1
            if abs(row.stable_gain_loss_eur) >= Decimal("100"):
                item.material_events_count += 1
            item.stable_quantity += row.stable_quantity
            item.stable_disposal_proceeds_eur += row.stable_disposal_proceeds_eur
            item.stable_gain_loss_eur += row.stable_gain_loss_eur
            item.max_price_age_days = max(item.max_price_age_days, row.price_age_days or 0)
            item.max_abs_price_delta_pct = max(item.max_abs_price_delta_pct, row.price_delta_pct or Decimal("0"))

        rows.sort(
            key=lambda item: (
                item.review_reason == "stablecoin_fx_price_basis_ok",
                item.review_reason != "missing_stablecoin_price",
                -abs(item.stable_gain_loss_eur),
                item.event_time,
                item.event_id,
            )
        )
        return TaxSolanaStablecoinFxReview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            events_count=len(rows),
            material_events_count=sum(1 for row in rows if abs(row.stable_gain_loss_eur) >= Decimal("100")),
            missing_price_count=sum(1 for row in rows if row.selected_price_eur is None),
            stale_price_count=sum(1 for row in rows if (row.price_age_days or 0) > 7),
            derived_price_count=sum(1 for row in rows if row.fx_basis_status == "derived_event_quote_review"),
            fx_backed_price_count=sum(1 for row in rows if row.fx_basis_status == "fx_backed"),
            market_price_count=sum(1 for row in rows if row.fx_basis_status == "market_price_review"),
            stable_disposal_proceeds_eur=sum((row.stable_disposal_proceeds_eur for row in rows), Decimal("0")),
            stable_gain_loss_eur=sum((row.stable_gain_loss_eur for row in rows), Decimal("0")),
            assets=sorted(asset_groups.values(), key=lambda item: abs(item.stable_gain_loss_eur), reverse=True)[:limit],
            rows=rows[:limit],
            methodology=(
                "Read-only Preis-/FX-Review fuer Solana-Stablecoin-Quote-Beine. "
                "Die Auswahl des historischen Stablecoin-EUR-Preises erfolgt ueber "
                "denselben HistoricalPriceLookup wie die Steuer-FIFO-Bewertung. "
                "Der Endpunkt schreibt keine Preise, keine Imports und keine "
                "FIFO-/Steuerdaten."
            ),
        )

    def evidence_report(self, year: int) -> TaxYearEvidenceReport:
        from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService

        status = self._status_for_year(year)
        guide = self.declaration_guide(year)
        external = self.external_inflow_report(year, limit=0)
        solana_swaps = self.solana_stablecoin_swap_context_review(year, limit=10_000)
        helium_swaps = self.helium_swap_context_review(year, limit=10_000)
        helium_swap_evidence = self.helium_swap_evidence_review(year, limit=10_000)
        helium_swap_alchemy = self._helium_swap_alchemy_audit_match_summary(
            {row.tx_id for row in helium_swap_evidence.rows if row.tx_id}
        )
        wallet_fifo_service = WalletFifoPreviewService(self.store)
        bmf_closure = self.bmf_closure_appendix(year)
        cex_outflow = wallet_fifo_service.cex_exchange_outflow_evidence(
            year,
            source_exchange="bitget",
            target_cex="binance",
            network="SOL",
        )
        cex_anchor_feasibility = wallet_fifo_service.cex_exchange_outflow_anchor_feasibility(
            year,
            source_exchange="bitget",
            target_cex="binance",
            network="SOL",
        )
        hnt = next((item for item in self._asset_breakdown(year) if item.asset.upper() == "HNT"), None)
        hnt_line_count = hnt.tax_line_count if hnt is not None else 0
        hnt_gain_loss = hnt.gain_loss_eur if hnt is not None else Decimal("0")
        tax_line_total = status.tax_lines_count + status.tax_free_lines_count
        review_decisions = self._review_decisions_for_year(year)
        items = [
            TaxYearEvidenceItem(
                evidence_id="tax-lines",
                category="eintragen" if status.tax_lines_count else "beleg",
                label="FIFO Tax-Lines",
                endpoint="/api/v1/export/tax-lines.csv",
                file_format="csv",
                record_count=tax_line_total,
                amount_eur=status.realized_gain_loss_eur,
                status=self._evidence_item_status(tax_line_total, blocked=status.export_blocked),
                required=bool(tax_line_total or status.export_blocked),
                note=(
                    "Belegt steuerpflichtige Veraeusserungen, Anschaffungskosten, "
                    "Erloese, Gewinne/Verluste und steuerfreie >365-Tage-Zeilen."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-payment-overview",
                category="beleg",
                label="Steuer-Eingabezettel",
                endpoint="/api/v1/export/tax-payment-overview.json",
                file_format="json",
                record_count=len(guide.entries),
                amount_eur=status.realized_gain_loss_eur + status.rewards_income_eur + status.derivative_pnl_eur,
                status="available",
                required=True,
                note="Lesbare Jahresuebersicht mit ASCII-Tabelle und Aufgaben: eintragen, nur Beleg, pruefen.",
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-income-guide",
                category="eintragen" if status.rewards_events_count else "beleg",
                label="Einzutragende Rewards / Mining / Staking",
                endpoint="/api/v1/export/tax-income-guide.csv",
                file_format="csv",
                record_count=status.rewards_events_count,
                amount_eur=status.rewards_income_eur,
                status=self._evidence_item_status(status.rewards_events_count),
                required=bool(status.rewards_events_count),
                note=(
                    "Belegt einzutragende Reward-/Mining-/Staking-Einkuenfte. "
                    "Review-only Income ist in derselben CSV getrennt markiert."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="derivative-lines",
                category="pruefen" if status.derivative_lines_count else "beleg",
                label="Derivate / Termingeschaefte",
                endpoint="/api/v1/export/derivative-lines.csv",
                file_format="csv",
                record_count=status.derivative_lines_count,
                amount_eur=status.derivative_pnl_eur,
                status=self._evidence_item_status(status.derivative_lines_count, review=bool(status.derivative_lines_count)),
                required=bool(status.derivative_lines_count),
                note="Separater Derivate-Beleg; wird nicht in den Krypto-FIFO-Saldo gemischt.",
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-external-inflows",
                category="pruefen" if external.review_count or external.unmatched_count else "beleg",
                label="Externe Solana-Zufluesse",
                endpoint="/api/v1/export/tax-external-inflows.csv",
                file_format="csv",
                record_count=external.inflows_count,
                amount_eur=external.review_value_eur + external.unmatched_value_eur,
                status="review" if external.review_count or external.unmatched_count else self._evidence_item_status(external.inflows_count),
                required=bool(external.review_count or external.unmatched_count),
                note="Belegt, welche Solana-Zufluesse Transfer-, Airdrop- oder Importklassifizierungspruefung brauchen.",
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-solana-stablecoin-swap-evidence",
                category="beleg" if solana_swaps.missing_raw_evidence_count == 0 else "pruefen",
                label="Solana Stablecoin Swap Signaturen",
                endpoint="/api/v1/export/tax-solana-stablecoin-swap-evidence.csv",
                file_format="csv",
                record_count=solana_swaps.events_count,
                amount_eur=solana_swaps.stable_gain_loss_eur,
                status=(
                    "review"
                    if solana_swaps.missing_raw_evidence_count
                    else self._evidence_item_status(solana_swaps.events_count)
                ),
                required=bool(solana_swaps.events_count),
                note=(
                    "Belegt Solana-Swap-Signaturen, Stablecoin-Quote-Beine, "
                    "Jupiter-Tokenstatus und FX-/Preisgrundlage je Swap-Event."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-solana-stablecoin-swap-fifo-lines",
                category="beleg",
                label="Solana Stablecoin FIFO-Splits",
                endpoint="/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv",
                file_format="csv",
                record_count=solana_swaps.stable_tax_lines_count,
                amount_eur=solana_swaps.stable_gain_loss_eur,
                status=self._evidence_item_status(solana_swaps.stable_tax_lines_count),
                required=bool(solana_swaps.stable_tax_lines_count),
                note=(
                    "Verknuepft jede Stablecoin-Swap-Signatur mit den konkreten "
                    "FIFO-Tax-Line-Splits inklusive Lot-, Acquisition- und "
                    "Disposal-Belegreferenzen."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-helium-swap-context",
                category="beleg" if helium_swaps.events_count else "pruefen",
                label="Helium Swap-/Trading-Kontext",
                endpoint="/api/v1/export/tax-helium-swap-context.csv",
                file_format="csv",
                record_count=helium_swaps.events_count,
                amount_eur=helium_swaps.total_trade_gain_loss_eur,
                status=self._evidence_item_status(helium_swaps.events_count),
                required=bool(helium_swaps.events_count),
                note=(
                    "Trennt HNT/IOT/MOBILE-Solana-Swap-/Trading-Kontexte von "
                    "Reward-/Mining-Einnahmen und verweist auf die bestehenden "
                    "FIFO-Drilldowns."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-helium-swap-evidence-review",
                category=(
                    "beleg"
                    if helium_swap_evidence.tx_count and helium_swap_evidence.raw_evidence_missing_count == 0
                    else "pruefen"
                ),
                label="Helium Swap-TxID Belegmatrix",
                endpoint="/api/v1/export/tax-helium-swap-evidence-review.csv",
                file_format="csv",
                record_count=helium_swap_evidence.tx_count,
                amount_eur=helium_swap_evidence.total_context_value_eur,
                status=(
                    "available"
                    if helium_swap_evidence.tx_count and helium_swap_evidence.raw_evidence_missing_count == 0
                    else self._evidence_item_status(helium_swap_evidence.tx_count)
                ),
                required=bool(helium_swap_evidence.tx_count),
                note=(
                    "Gruppiert HNT/IOT/MOBILE-Swap-Kontexte je TxID und zeigt, "
                    "ob lokale Raw-/Import-Belege fuer die Transaktion vorhanden sind."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="tax-helium-swap-alchemy-audit",
                category=(
                    "beleg"
                    if helium_swap_alchemy["expected_count"]
                    and helium_swap_alchemy["missing_count"] == 0
                    and helium_swap_alchemy["confirmed_count"] == helium_swap_alchemy["expected_count"]
                    else "pruefen"
                ),
                label="Helium Swap Alchemy Onchain-Audit",
                endpoint="/api/v1/export/tax-helium-swap-alchemy-audit.json",
                file_format="json",
                record_count=int(helium_swap_alchemy["confirmed_count"]),
                amount_eur=helium_swap_evidence.total_context_value_eur,
                status=(
                    "available"
                    if helium_swap_alchemy["expected_count"]
                    and helium_swap_alchemy["missing_count"] == 0
                    and helium_swap_alchemy["confirmed_count"] == helium_swap_alchemy["expected_count"]
                    else "review"
                    if helium_swap_alchemy["expected_count"]
                    else "empty"
                ),
                required=bool(helium_swap_alchemy["expected_count"]),
                note=(
                    f"Alchemy-Gegenpruefung fuer Helium-Swap-TxIDs: "
                    f"{helium_swap_alchemy['confirmed_count']}/{helium_swap_alchemy['expected_count']} "
                    f"TxIDs bestaetigt, {helium_swap_alchemy['missing_count']} fehlen im Audit-Artefakt."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="bmf-closure-appendix",
                category="pruefen" if bmf_closure.manual_evidence_required_count else "beleg",
                label="BMF Abschlussbeilage Herkunft",
                endpoint=f"/api/v1/tax-years/{year}/bmf-closure-appendix",
                file_format="json",
                record_count=bmf_closure.items_count,
                amount_eur=sum(
                    (item.carried_cost_basis_eur_total for item in bmf_closure.items),
                    Decimal("0"),
                ),
                status=(
                    "blocked"
                    if bmf_closure.status == "blocked"
                    else "review"
                    if bmf_closure.status == "review"
                    else self._evidence_item_status(bmf_closure.items_count)
                ),
                required=bool(bmf_closure.items_count),
                note=(
                    "Konservative Jahresbeilage fuer offene Wallet-FIFO-Herkunft: "
                    "unbekannte Sender werden nicht als steuerneutrale Eigenwallet-"
                    "Transfers behauptet, sondern mit Belegpfaden offengelegt."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="cex-exchange-outflow-evidence",
                category="beleg" if cex_outflow.missing_count == 0 else "pruefen",
                label="CEX-zu-CEX Transferbelege",
                endpoint=f"/api/v1/tax-years/{year}/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL",
                file_format="json",
                record_count=cex_outflow.rows_count,
                amount_eur=None,
                status=(
                    "review"
                    if cex_outflow.missing_count
                    else self._evidence_item_status(cex_outflow.rows_count)
                ),
                required=bool(cex_outflow.rows_count),
                note=(
                    "Belegt Bitget-zu-Binance/Solana-Transfers anhand Exchange-Withdrawal-"
                    "Raw-Evidence, Onchain-Deposit-TXID, Netto-Menge und Fee-Abzug. "
                    "Dient als Review-/Belegschicht fuer steuerneutrale FIFO-Fortfuehrung."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="cex-exchange-outflow-anchor-feasibility",
                category="beleg" if cex_anchor_feasibility.anchor_missing_count == 0 else "pruefen",
                label="CEX FIFO-Anker-Vorpruefung",
                endpoint=f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL",
                file_format="json",
                record_count=cex_anchor_feasibility.decisions_count,
                amount_eur=None,
                status=(
                    "review"
                    if cex_anchor_feasibility.anchor_missing_count
                    else self._evidence_item_status(cex_anchor_feasibility.decisions_count)
                ),
                required=bool(cex_anchor_feasibility.decisions_count),
                note=(
                    "Read-only Vorpruefung, ob gespeicherte CEX-zu-CEX-Review-"
                    "Decisions bereits durch Wallet-FIFO-Transfertraces als "
                    "stichtagsgenaue FIFO-Anker fortgefuehrt werden koennen."
                ),
            ),
            TaxYearEvidenceItem(
                evidence_id="hnt-provenance-events",
                category="beleg",
                label="HNT Provenance Events",
                endpoint="/api/v1/export/hnt-provenance-events.csv",
                file_format="csv",
                record_count=hnt_line_count,
                amount_eur=hnt_gain_loss,
                status=self._evidence_item_status(hnt_line_count),
                required=hnt is not None,
                note="HNT-spezifischer Beleg fuer FIFO-, Bridge-, Legacy- und Fairspot-Nachvollziehbarkeit.",
            ),
            TaxYearEvidenceItem(
                evidence_id="review-decisions",
                category="beleg",
                label="Review-Entscheidungen zum Jahr",
                endpoint="/api/v1/export/review-decisions.csv",
                file_format="csv",
                record_count=len(review_decisions),
                amount_eur=None,
                status=self._evidence_item_status(len(review_decisions)),
                required=bool(review_decisions),
                note="Belegt fachliche Entscheidungen mit eindeutigem Jahresbezug; keine automatische Steuerdatenwirkung.",
            ),
            TaxYearEvidenceItem(
                evidence_id="evidence-package",
                category="paket",
                label="Gesamtes Belegpaket",
                endpoint="/api/v1/export/evidence-package.zip",
                file_format="zip",
                record_count=len(guide.evidence_exports),
                amount_eur=None,
                status="available" if not status.export_blocked else "review",
                required=True,
                note="ZIP mit Manifest, Paketindex, Audit JSON, Steuer-CSV, Solana-/HNT-/Review-Belegen.",
            ),
        ]
        return TaxYearEvidenceReport(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            export_ready=not status.export_blocked,
            items=items,
            methodology=(
                "Read-only Belegkarte aus vorhandenen Jahresaggregaten und Exportpfaden. "
                "Sie erzeugt keine FIFO-Lots, keine Imports und keine Review-Entscheidungen."
            ),
        )

    def bmf_closure_appendix(self, year: int, *, limit: int = 500) -> TaxYearBmfClosureAppendix:
        from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService

        cache_key = (year, limit)
        cached = self._bmf_closure_appendix_cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(deep=True)
        closure = WalletFifoPreviewService(self.store).provenance_closure_report(year=year, limit=limit)
        items: list[TaxYearBmfClosureAppendixItem] = []
        for item in closure.items:
            recommended_tax_treatment = (
                "Nicht automatisch als steuerneutraler Eigenwallet-Transfer behandeln."
            )
            filing_disclosure = (
                "Offene Herkunft im Jahresbeleg ausweisen; FIFO-/Kostenbasis bleibt "
                "als vorhandene V2-Bewertung dokumentiert, ohne zusaetzliche "
                "Steuerneutralitaet zu behaupten."
            )
            manual_evidence_required = item.requires_review
            conservative_treatment_available = item.closure_status in {
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
            }
            if item.closure_status == "documented_non_live_opening_balance":
                recommended_tax_treatment = (
                    "Als belegten Anfangsbestand fuehren; kein Live-Zufluss, "
                    "keine steuerbare Veraeusserung und keine neue Haltefristbehauptung."
                )
                filing_disclosure = (
                    "Anfangsbestand separat im Belegpaket ausweisen und nicht als "
                    "Portfolio-Live-Wallet oder neuen Transfer eskalieren."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_fiat_purchase":
                recommended_tax_treatment = (
                    "Als belegte Anschaffung gegen Fiat fuehren; kein Transfer, "
                    "keine steuerneutrale Umbuchung und keine offene Senderwallet."
                )
                filing_disclosure = (
                    "Binance-Fiat-Buy-History mit Betrag, Fiat-Gegenwert, "
                    "Zeitstempel und Transaction-ID im Belegpaket ausweisen."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_legacy_hnt_cex_deposit":
                recommended_tax_treatment = (
                    "Als belegten Legacy-HNT-Transfer zur Boerse fuehren; keine "
                    "Veraeusserung durch den Transfer selbst und keine neue Anschaffung."
                )
                filing_disclosure = (
                    "Heliumtracker-Abgang und Binance-Deposit-History mit Adresse, "
                    "TXID, Zeitstempel und Menge gemeinsam beilegen."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_legacy_hnt_cex_deposit_mirror":
                recommended_tax_treatment = (
                    "Als Binance-Deposit-History-Spiegel eines belegten Legacy-HNT-"
                    "Transfers fuehren; keine zweite Anschaffung und keine "
                    "Veraeusserung durch den Spiegelbeleg."
                )
                filing_disclosure = (
                    "Binance-Deposit-History mit TXID/Adresse und passenden "
                    "Heliumtracker-Abgang gemeinsam beilegen."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_fairspot_staking_return":
                recommended_tax_treatment = (
                    "Als belegten Fairspot/Staking-Ruecktransfer zur Main-Legacy-"
                    "Wallet fuehren; keine Veraeusserung durch den Transfer selbst "
                    "und keine neue Anschaffung."
                )
                filing_disclosure = (
                    "Helium-Raw-Evidence mit Payer/Payee, Transaction-Hash, "
                    "Zeitstempel und Menge beilegen. Fairspot bleibt "
                    "Transfer-Gegenpartei, nicht aktuelle Portfolio-Wallet."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_legacy_counterparty_mirror":
                recommended_tax_treatment = (
                    "Als belegten Gegenpartei-/Service-Spiegel eines Main-Legacy-"
                    "Outflows fuehren; nicht als aktuelle eigene Wallet oder "
                    "neue Anschaffung fortfuehren."
                )
                filing_disclosure = (
                    "Main-Legacy-Outflow mit TX-Hash, Zieladresse, Zeitstempel "
                    "und Menge beilegen. Steuerliche Behandlung des Main-Outflows "
                    "separat ueber Tax-Lines/Belegkette nachvollziehen."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_exchange_deposit_history":
                recommended_tax_treatment = (
                    "Als belegten Exchange-Deposit/externen Zufluss fuehren; keine "
                    "steuerneutrale Eigenwallet-Umbuchung und keine FIFO-Fortfuehrung "
                    "behaupten, solange Sender-Ownership fehlt."
                )
                filing_disclosure = (
                    "Exchange-Deposit-History mit TXID, Netzwerk, Zeitstempel, Asset "
                    "und Menge beilegen. Spaetere Sendernachweise koennen per Review "
                    "zu Transfer/FIFO-Fortfuehrung nachgezogen werden."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_legacy_hnt_payment_provenance":
                recommended_tax_treatment = (
                    "Als belegte Legacy-HNT-Payment-Provenance fuehren. Fairspot-"
                    "Ruecktransfers koennen als steuerneutraler Ruecktransfer "
                    "dokumentiert werden; externe Payments ohne Sender-Ownership "
                    "nicht als Eigenwallet-Transfer/FIFO-Fortfuehrung behaupten."
                )
                filing_disclosure = (
                    "Helium-Raw-Evidence mit Payer/Payee, TX-Hash, Zeitstempel, "
                    "Menge und Oracle-Wert beilegen. Externe Payment-Anteile "
                    "konservativ offenlegen."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_binance_btt_bttc_redenomination":
                recommended_tax_treatment = (
                    "Als belegte BTT/BTTC-Redenomination fuehren; keine neue "
                    "externe Herkunft, kein Reward und kein Eigenwallet-Transfer."
                )
                filing_disclosure = (
                    "Binance-Transaction-History mit BTT-Abgang `Token Swap - "
                    "Redenomination/Rebranding` und BTTC-Zugang `Airdrop Assets` "
                    "im Faktor 1:1000 beilegen."
                )
                manual_evidence_required = False
            elif item.closure_status == "documented_manual_cex_deposit_history":
                recommended_tax_treatment = (
                    "Als dokumentierten CEX-Deposit/externen Zufluss fuehren; keine "
                    "steuerneutrale Eigenwallet-Umbuchung behaupten, solange "
                    "Sender-Ownership fehlt."
                )
                filing_disclosure = (
                    "Manuellen Deposit-Lot und CEX-Deposit-History mit Adresse, "
                    "Netzwerk, TXID, Zeitstempel und Menge gemeinsam beilegen."
                )
                manual_evidence_required = False
            elif item.closure_status == "external_or_unknown_origin_documented":
                recommended_tax_treatment = (
                    "Konservativ als externen oder ungeklarten Zufluss dokumentieren; "
                    "keine steuerneutrale Eigenwallet-Umbuchung ansetzen."
                )
                filing_disclosure = (
                    "Solana/RPC-Provenance-Batch beilegen. Falls spaeter eigener "
                    "Sender-/Service-Kontext belegt wird, kann der Fall per Review "
                    "zu Transfer/FIFO-Fortfuehrung nachgezogen werden."
                )
                manual_evidence_required = False
            elif item.closure_status == "unverified_cex_deposit_sender":
                recommended_tax_treatment = (
                    "Binance-Deposit nur dann als steuerneutralen Depotwechsel nutzen, "
                    "wenn Sender-Ownership nachgereicht wird; bis dahin konservativ "
                    "nicht als Eigenwallet-Transfer behaupten."
                )
                filing_disclosure = (
                    "CEX-Deposit-Beleg und Sender-Ownership-Report beilegen. Die "
                    "Sender-Wallet ist nicht in der Owned-Wallet-Registry belegt."
                )
                manual_evidence_required = False
            elif item.closure_status == "tax_neutral_candidate_review_required":
                recommended_tax_treatment = (
                    "Potentiell steuerneutraler Transfer; erst nach fachlicher "
                    "Review-Entscheidung FIFO-Fortfuehrung als final behandeln."
                )
                filing_disclosure = (
                    "Als Review-Kandidat ausweisen und die Review-Entscheidung mit "
                    "TXID, Sender, Empfaenger und Menge beilegen."
                )
                conservative_treatment_available = False
            elif item.closure_status == "solana_batch_incomplete":
                recommended_tax_treatment = (
                    "Nicht abschliessen; Solana-Provenance-Batch erneut erzeugen "
                    "oder Rohbelege nachziehen."
                )
                filing_disclosure = "Offenen technischen Nachweis als Blocker im Belegpaket fuehren."
                conservative_treatment_available = False

            items.append(
                TaxYearBmfClosureAppendixItem(
                    category=item.category,
                    closure_status=item.closure_status,
                    asset=item.asset,
                    pool_id=item.pool_id,
                    source=item.source,
                    account=item.account,
                    events_count=item.events_count,
                    quantity_total=item.quantity_total,
                    carried_cost_basis_eur_total=item.carried_cost_basis_eur_total,
                    evidence_status=item.evidence_status,
                    recommended_tax_treatment=recommended_tax_treatment,
                    filing_disclosure=filing_disclosure,
                    manual_evidence_required=manual_evidence_required,
                    conservative_treatment_available=conservative_treatment_available,
                    evidence_refs=item.evidence_refs,
                    recommended_action=item.recommended_action,
                )
            )

        manual_count = sum(1 for item in items if item.manual_evidence_required)
        conservative_count = sum(1 for item in items if item.conservative_treatment_available)
        tax_neutral_candidates = sum(
            1 for item in items if item.closure_status == "tax_neutral_candidate_review_required"
        )
        if not items:
            status = "ready"
        elif any(item.closure_status == "solana_batch_incomplete" for item in items):
            status = "blocked"
        elif tax_neutral_candidates:
            status = "review"
        elif manual_count:
            status = "review"
        else:
            status = "ready"
        report = TaxYearBmfClosureAppendix(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            status=status,
            items_count=len(items),
            conservative_items_count=conservative_count,
            manual_evidence_required_count=manual_count,
            tax_neutral_candidates_count=tax_neutral_candidates,
            can_file_with_conservative_appendix=bool(items)
            and status != "blocked"
            and conservative_count == len(items),
            items=items,
            methodology=(
                "Read-only BMF-Abschlussbeilage fuer offene Wallet-FIFO-Herkunft. "
                "Sie uebersetzt den Provenance-Closure-Status in eine konservative "
                "steuerliche Belegsprache: keine ungepruefte Steuerneutralitaet, "
                "keine automatische FIFO-Fortschreibung und keine Datenmutation. "
                "Unbekannte Sender werden dokumentiert, aber nicht als eigene "
                "Wallets angenommen."
            ),
        )
        self._bmf_closure_appendix_cache[cache_key] = report.model_copy(deep=True)
        return report

    def external_inflow_report(self, year: int, *, limit: int = 200) -> TaxExternalInflowReport:
        cache_key = (year, limit)
        cached = self._external_inflow_report_cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(deep=True)
        lookup = self._income_price_lookup([])
        inflows = self._external_solana_income_rows(year)
        outgoing = self._outgoing_events_by_asset()
        rows: list[TaxExternalInflowMatch] = []
        total_value = Decimal("0")
        matched_value = Decimal("0")
        review_value = Decimal("0")
        unmatched_value = Decimal("0")
        matched_count = 0
        review_count = 0
        unmatched_count = 0

        assets = sorted({row[4].upper() for row in inflows})
        lookup = self._income_price_lookup([asset for asset in assets if asset != "EUR"])
        for row in inflows:
            (
                event_id,
                event_time,
                source,
                account,
                asset,
                quantity,
                quote_asset,
                quote_quantity,
                tx_id,
            ) = row
            price_eur = None
            if quantity > 0 and not (quote_asset and str(quote_asset).upper() == "EUR") and asset.upper() != "EUR":
                price = self._income_price_at(asset, event_time, lookup)
                if price is not None:
                    price_eur = price[0]
            value_eur = self._income_row_value(
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                quote_quantity=quote_quantity,
                price_eur=price_eur,
            )
            if value_eur is not None:
                total_value += value_eur
            best = self._best_external_inflow_match(
                inflow_event_id=event_id,
                event_time=event_time,
                asset=asset,
                quantity=quantity,
                account=account,
                tx_id=tx_id,
                outgoing=outgoing.get(asset.upper(), []),
            )
            if best is not None:
                status = "matched_transfer_candidate" if best["score"] >= 65 else "review_transfer_candidate"
                if status == "matched_transfer_candidate":
                    matched_count += 1
                    if value_eur is not None:
                        matched_value += value_eur
                else:
                    review_count += 1
                    if value_eur is not None:
                        review_value += value_eur
                rows.append(
                    TaxExternalInflowMatch(
                        inflow_event_id=event_id,
                        event_time=event_time.isoformat(),
                        source=source,
                        account=account,
                        asset=asset,
                        quantity=quantity,
                        value_eur=value_eur,
                        tx_id=tx_id,
                        status=status,
                        best_match_score=int(best["score"]),
                        matched_event_id=best["event_id"],
                        matched_time=best["event_time"].isoformat(),
                        matched_source=best["source"],
                        matched_account=best["account"],
                        matched_quantity=best["quantity"],
                        matched_tx_id=best["tx_id"],
                        amount_delta=best["amount_delta"],
                        time_delta_seconds=best["time_delta_seconds"],
                        reasons=best["reasons"],
                        warnings=best["warnings"],
                    )
                )
                continue
            unmatched_count += 1
            if value_eur is not None:
                unmatched_value += value_eur
            rows.append(
                TaxExternalInflowMatch(
                    inflow_event_id=event_id,
                    event_time=event_time.isoformat(),
                    source=source,
                    account=account,
                    asset=asset,
                    quantity=quantity,
                    value_eur=value_eur,
                    tx_id=tx_id,
                    status="unmatched_external_inflow",
                    warnings=["Keine plausible vorherige Gegenbuchung im Ledger gefunden."],
                )
            )

        rows.sort(key=lambda item: (item.status, -abs(item.value_eur or Decimal("0")), item.event_time))
        report = TaxExternalInflowReport(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            inflows_count=len(inflows),
            matched_count=matched_count,
            review_count=review_count,
            unmatched_count=unmatched_count,
            total_value_eur=total_value,
            matched_value_eur=matched_value,
            review_value_eur=review_value,
            unmatched_value_eur=unmatched_value,
            assets=assets,
            rows=rows[: max(limit, 0)],
            methodology=(
                "Read-only Matching fuer Solana-income-Zufluesse ohne Gegenseite "
                "in derselben Signatur. Es wird gegen fruehere negative Events "
                "desselben Assets gematcht; Treffer sind Belegkandidaten und "
                "aendern keine Imports, FIFO-Lots oder Steuerdaten."
            ),
        )
        self._external_inflow_report_cache[cache_key] = report.model_copy(deep=True)
        return report

    def _status_for_year(self, year: int) -> TaxYearStatus:
        cached = self._status_cache.get(year)
        if cached is not None:
            return cached.model_copy(deep=True)
        tax = self._tax_totals_by_year().get(year, {})
        income = self._income_totals_by_year().get(year, {})
        derivatives = self._derivatives_by_year().get(year, {})
        missing = [
            item
            for item in self._missing_prices()
            if item.year == year
        ]
        unmatched = [
            item
            for item in self._unmatched_disposals()
            if item.event_time.year == year
        ]
        closed_years = self._closed_tax_years()
        is_closed = year in closed_years
        issues: list[TaxYearIssue] = []
        if missing:
            issues.append(
                TaxYearIssue(
                    code="missing_event_price",
                    severity="high",
                    message=f"{len(missing)} Preisgruppe(n) ohne historische EUR-Bewertung.",
                    count=len(missing),
                    blocks_export=not is_closed,
                )
            )
        if unmatched:
            issues.append(
                TaxYearIssue(
                    code="unmatched_tax_disposal",
                    severity="high",
                    message=f"{len(unmatched)} FIFO-Abgang/Abgaenge ohne vollstaendiges Lot.",
                    count=len(unmatched),
                    blocks_export=not is_closed,
                )
            )
        derivative_missing = int(derivatives.get("missing_price_count", 0) or 0)
        if derivative_missing:
            issues.append(
                TaxYearIssue(
                    code="derivative_missing_prices",
                    severity="high",
                    message=f"{derivative_missing} Derivate-Zeile(n) ohne EUR-Bewertung.",
                    count=derivative_missing,
                    blocks_export=not is_closed,
                )
            )

        has_activity = any(
            [
                int(tax.get("tax_lines_count", 0) or 0),
                int(tax.get("tax_free_lines_count", 0) or 0),
                int(income.get("events", 0) or 0),
                int(derivatives.get("lines", 0) or 0),
                missing,
                unmatched,
            ]
        )
        blocks = any(issue.blocks_export for issue in issues)
        if blocks:
            state = "blocked"
            label = "blockiert"
        elif issues and is_closed:
            state = "historical_open"
            label = "nur historisch offen"
        elif has_activity or is_closed:
            state = "finished"
            label = "fertig"
        else:
            state = "empty"
            label = "leer"

        status = TaxYearStatus(
            year=year,
            state=state,
            label=label,
            is_closed_historical_year=is_closed,
            export_blocked=blocks,
            realized_gain_loss_eur=tax.get("gain_loss", Decimal("0")),
            taxable_disposal_proceeds_eur=tax.get("proceeds", Decimal("0")),
            acquisition_cost_eur=tax.get("acquisition_cost", Decimal("0")),
            tax_lines_count=int(tax.get("tax_lines_count", 0) or 0),
            tax_free_gain_loss_eur=tax.get("tax_free_gain_loss", Decimal("0")),
            tax_free_disposal_proceeds_eur=tax.get("tax_free_proceeds", Decimal("0")),
            tax_free_acquisition_cost_eur=tax.get("tax_free_acquisition_cost", Decimal("0")),
            tax_free_lines_count=int(tax.get("tax_free_lines_count", 0) or 0),
            rewards_income_eur=income.get("income_eur", Decimal("0")),
            rewards_events_count=int(income.get("events", 0) or 0),
            derivative_pnl_eur=derivatives.get("pnl", Decimal("0")),
            derivative_lines_count=int(derivatives.get("lines", 0) or 0),
            fees_eur=self._fees_by_year().get(year, Decimal("0")),
            missing_price_groups=len(missing),
            unmatched_disposals=len(unmatched),
            review_issues_count=len(issues),
            top_assets=self._asset_breakdown(year)[:5],
            issues=issues,
        )
        self._status_cache[year] = status.model_copy(deep=True)
        return status

    def _available_years(self) -> list[int]:
        years = set(self.DEFAULT_YEARS)
        for line in self._tax_lines():
            years.add(line.disposed_at.year)
            years.add(line.acquired_at.year)
        for item in self._unmatched_disposals():
            years.add(item.event_time.year)
        for item in self._missing_prices():
            years.add(item.year)
        for line in self._derivative_lines():
            years.add(line.event_time.year)
        return sorted(years)

    def _tax_totals_by_year(self) -> dict[int, dict[str, Decimal | int]]:
        if self._tax_totals_cache is not None:
            return self._tax_totals_cache
        totals: dict[int, dict[str, Decimal | int]] = defaultdict(
            lambda: {
                "gain_loss": Decimal("0"),
                "proceeds": Decimal("0"),
                "acquisition_cost": Decimal("0"),
                "tax_lines_count": 0,
                "tax_free_gain_loss": Decimal("0"),
                "tax_free_proceeds": Decimal("0"),
                "tax_free_acquisition_cost": Decimal("0"),
                "tax_free_lines_count": 0,
            }
        )
        for line in self._tax_lines():
            item = totals[line.disposed_at.year]
            if self._is_taxable_private_disposal(line):
                item["gain_loss"] = item["gain_loss"] + line.gain_loss_eur  # type: ignore[operator]
                item["proceeds"] = item["proceeds"] + line.disposal_proceeds_eur  # type: ignore[operator]
                item["acquisition_cost"] = item["acquisition_cost"] + line.acquisition_cost_eur  # type: ignore[operator]
                item["tax_lines_count"] = int(item["tax_lines_count"]) + 1
            else:
                item["tax_free_gain_loss"] = item["tax_free_gain_loss"] + line.gain_loss_eur  # type: ignore[operator]
                item["tax_free_proceeds"] = item["tax_free_proceeds"] + line.disposal_proceeds_eur  # type: ignore[operator]
                item["tax_free_acquisition_cost"] = item["tax_free_acquisition_cost"] + line.acquisition_cost_eur  # type: ignore[operator]
                item["tax_free_lines_count"] = int(item["tax_free_lines_count"]) + 1
        self._tax_totals_cache = totals
        return totals

    def _asset_breakdown(self, year: int) -> list[TaxYearAssetBreakdown]:
        if self._asset_breakdown_cache is not None:
            return self._asset_breakdown_cache.get(year, [])
        grouped_by_year: dict[int, dict[str, TaxYearAssetBreakdown]] = defaultdict(dict)
        for line in self._tax_lines():
            if not self._is_taxable_private_disposal(line):
                continue
            grouped = grouped_by_year[line.disposed_at.year]
            item = grouped.setdefault(line.asset, TaxYearAssetBreakdown(asset=line.asset))
            item.gain_loss_eur += line.gain_loss_eur
            item.proceeds_eur += line.disposal_proceeds_eur
            item.acquisition_cost_eur += line.acquisition_cost_eur
            item.tax_line_count += 1
        self._asset_breakdown_cache = {
            item_year: sorted(items.values(), key=lambda item: abs(item.gain_loss_eur), reverse=True)
            for item_year, items in grouped_by_year.items()
        }
        return self._asset_breakdown_cache.get(year, [])

    @staticmethod
    def _is_taxable_private_disposal(line: object) -> bool:
        return int(getattr(line, "holding_days", 0) or 0) <= 365

    @staticmethod
    def _is_stablecoin_like(asset: str) -> bool:
        return asset.upper() in STABLECOIN_LIKE_ASSETS

    @staticmethod
    def _is_taxable_reward_income(
        *,
        event_type: str,
        source: str,
        asset: str,
        quantity: Decimal,
    ) -> bool:
        if quantity <= 0:
            return False
        if event_type not in {"reward", "staking", "mining"}:
            return False
        # Auto-eintragung ist bewusst eng: HNT/IOT/MOBILE-Zaehler werden nur
        # aufgenommen, wenn der Import sie bereits als Mining oder Reward
        # klassifiziert hat. Solana-RPC setzt das nur bei belegten Helium
        # Reward-Instructions wie SetCurrentRewardsWrapperV1 und
        # DistributeCompressionRewardsV0.
        return event_type in {"reward", "mining"} and asset.upper() in {"HNT", "IOT", "MOBILE"}

    def _income_totals_by_year(self) -> dict[int, dict[str, Decimal | int]]:
        if self._income_totals_cache is not None:
            return self._income_totals_cache
        totals: dict[int, dict[str, Decimal | int]] = defaultdict(
            lambda: {"income_eur": Decimal("0"), "events": 0}
        )
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    date_part('year', e.event_time)::integer as year,
                    count(*)::integer as events,
                    coalesce(sum(l.cost_basis_eur_total), 0) as income_eur
                from canonical_events e
                left join tax_lots l on l.source_event_id = e.event_id
                where e.event_type in ('reward', 'mining')
                  and upper(e.asset) in ('HNT', 'IOT', 'MOBILE')
                group by year
                order by year
                """
            ).fetchall()
        for year, events, income_eur in rows:
            totals[int(year)] = {
                "income_eur": income_eur or Decimal("0"),
                "events": int(events or 0),
            }
        self._income_totals_cache = totals
        return totals

    def _income_reports_by_year(self) -> dict[int, TaxIncomeReport]:
        if self._income_reports_cache is not None:
            return self._income_reports_cache
        grouped: dict[int, dict[str, object]] = defaultdict(
            lambda: {
                "total": Decimal("0"),
                "reward_total": Decimal("0"),
                "generic_total": Decimal("0"),
                "reward_events": 0,
                "review_only_events": 0,
                "events": 0,
                "valued": 0,
                "missing": 0,
                "ignored": 0,
                "classifications": defaultdict(int),
                "assets": {},
                "missing_assets": set(),
                "previews": [],
            }
        )
        rows = self._income_event_rows(event_types=tuple(sorted(INCOME_EVENT_TYPES)))
        tx_context = self._income_tx_context()
        reward_tx_ids = self._taxable_reward_tx_ids_by_asset()
        income_price_lookup = self._income_price_lookup(
            sorted({str(row[5]).upper() for row in rows if row[6] > 0 and str(row[5]).upper() != "EUR"})
        )
        for row in rows:
            (
                event_id,
                event_time,
                event_type,
                source,
                account,
                asset,
                quantity,
                quote_asset,
                quote_quantity,
                tx_id,
            ) = row
            if self._is_duplicate_review_income_for_reward_tx(
                event_type=event_type,
                asset=asset,
                quantity=quantity,
                tx_id=tx_id,
                reward_tx_ids=reward_tx_ids,
            ):
                continue
            price_eur = None
            price_source = None
            priced_at = None
            if quantity > 0 and not (quote_asset and str(quote_asset).upper() == "EUR") and asset.upper() != "EUR":
                price = self._income_price_at(asset, event_time, income_price_lookup)
                if price is not None:
                    price_eur, price_source, priced_at = price
            year = event_time.year
            value_eur = self._income_row_value(
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                quote_quantity=quote_quantity,
                price_eur=price_eur,
            )
            if quantity > 0 and quote_asset and str(quote_asset).upper() == "EUR" and quote_quantity is not None:
                price_source = "event_quote:EUR"
                priced_at = event_time
            elif quantity > 0 and asset.upper() == "EUR":
                price_source = "fiat:EUR"
                priced_at = event_time
            bucket = grouped[year]
            bucket["events"] = int(bucket["events"]) + 1
            classification = self._income_classification(
                event_type=event_type,
                source=source,
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                account=account,
                tx_id=tx_id,
                tx_context=tx_context,
            )
            classifications = bucket["classifications"]  # type: ignore[assignment]
            classifications[classification] += 1  # type: ignore[index]
            if quantity > 0:
                if self._is_taxable_reward_income(
                    event_type=event_type,
                    source=source,
                    asset=asset,
                    quantity=quantity,
                ):
                    bucket["reward_events"] = int(bucket["reward_events"]) + 1
                else:
                    bucket["review_only_events"] = int(bucket["review_only_events"]) + 1
            asset_key = f"{asset.upper()}::{event_type}::{classification}"
            assets = bucket["assets"]  # type: ignore[assignment]
            item = assets.setdefault(  # type: ignore[union-attr]
                asset_key,
                TaxIncomeAssetBreakdown(
                    asset=asset,
                    event_type=event_type,
                    classification=classification,
                ),
            )
            item.events_count += 1
            item.quantity += quantity
            if source not in item.sources:
                item.sources.append(source)
            if quantity <= 0:
                bucket["ignored"] = int(bucket["ignored"]) + 1
                status = "non_positive_ignored"
            elif value_eur is None:
                bucket["missing"] = int(bucket["missing"]) + 1
                item.missing_value_count += 1
                missing_assets = bucket["missing_assets"]  # type: ignore[assignment]
                missing_assets.add(asset.upper())  # type: ignore[union-attr]
                status = "missing_price"
            else:
                bucket["valued"] = int(bucket["valued"]) + 1
                bucket["total"] = bucket["total"] + value_eur  # type: ignore[operator]
                if self._is_taxable_reward_income(
                    event_type=event_type,
                    source=source,
                    asset=asset,
                    quantity=quantity,
                ):
                    bucket["reward_total"] = bucket["reward_total"] + value_eur  # type: ignore[operator]
                else:
                    bucket["generic_total"] = bucket["generic_total"] + value_eur  # type: ignore[operator]
                item.income_eur += value_eur
                status = "valued"
            previews = bucket["previews"]  # type: ignore[assignment]
            if len(previews) < 200:  # type: ignore[arg-type]
                previews.append(  # type: ignore[union-attr]
                    TaxIncomeEventPreview(
                        event_id=event_id,
                        event_time=event_time.isoformat(),
                        event_type=event_type,
                        source=source,
                        account=account,
                        asset=asset,
                        quantity=quantity,
                        income_eur=value_eur,
                        price_source=price_source,
                        priced_at=priced_at.isoformat() if priced_at is not None else None,
                        valuation_status=status,
                        classification=classification,
                    )
                )
        reports: dict[int, TaxIncomeReport] = {}
        for year, bucket in grouped.items():
            assets = list(bucket["assets"].values())  # type: ignore[union-attr]
            for item in assets:
                item.sources = sorted(item.sources)
            reports[year] = TaxIncomeReport(
                year=year,
                generated_at=datetime.now(timezone.utc).isoformat(),
                total_income_eur=bucket["total"],  # type: ignore[arg-type]
                reward_income_eur=bucket["reward_total"],  # type: ignore[arg-type]
                generic_income_eur=bucket["generic_total"],  # type: ignore[arg-type]
                declaration_income_eur=bucket["reward_total"],  # type: ignore[arg-type]
                review_only_income_eur=bucket["generic_total"],  # type: ignore[arg-type]
                taxable_reward_events_count=int(bucket["reward_events"]),
                review_only_events_count=int(bucket["review_only_events"]),
                events_count=int(bucket["events"]),
                valued_events_count=int(bucket["valued"]),
                missing_value_count=int(bucket["missing"]),
                ignored_non_positive_count=int(bucket["ignored"]),
                classification_counts=dict(sorted(bucket["classifications"].items())),  # type: ignore[union-attr]
                assets=sorted(assets, key=lambda item: abs(item.income_eur), reverse=True),
                missing_assets=sorted(bucket["missing_assets"]),  # type: ignore[arg-type]
                events=bucket["previews"],  # type: ignore[arg-type]
                methodology=(
                    "Read-only Mining/Reward/Income-Auswertung. EUR-Werte werden "
                    "direkt aus EUR-Quote oder ersatzweise aus historischem "
                    "Asset/EUR-Preis am Ereigniszeitpunkt bewertet. Fehlende Preise "
                    "werden ausgewiesen und nicht geschaetzt. EÜR-nahe Reward-Summe "
                    "enthaelt nur fachlich bestaetigte Helium-HNT/IOT/MOBILE-"
                    "Mining-/Reward-Zufluesse. Exchange-Earn, Wrapper- und "
                    "Distribution-Events werden separat als Review-Kontext gezeigt."
                ),
            )
        self._income_reports_cache = reports
        return reports

    @staticmethod
    def _income_classification(
        *,
        event_type: str,
        source: str,
        asset: str,
        quantity: Decimal,
        quote_asset: str | None,
        account: str | None,
        tx_id: str | None,
        tx_context: dict[str, dict[str, object]],
    ) -> str:
        if quantity <= 0:
            return "non_positive_ignored"
        if TaxYearService._is_taxable_reward_income(
            event_type=event_type,
            source=source,
            asset=asset,
            quantity=quantity,
        ):
            return "reward_income_candidate"
        if event_type in {"reward", "staking", "mining"}:
            return "exchange_earn_or_wrapper_review"
        if event_type == "income" and source == "solana_rpc" and quote_asset is None:
            context = tx_context.get(tx_id or "")
            if context and int(context.get("negative_count", 0) or 0) > 0:
                return "solana_swap_or_transfer_with_outgoing_review"
            if TaxYearService._is_strict_external_solana_income_context(context):
                return "solana_external_inflow_or_airdrop_review"
            return "solana_program_or_swap_income_review"
        if event_type == "income" and source == "binance" and quote_asset is None:
            if abs(quantity) < Decimal("1") and asset.upper() not in {"USDT", "USDC", "EUR"}:
                return "binance_dust_or_rounding_review"
            return "binance_distribution_or_transfer_review"
        if event_type == "income" and account and "earn" in account.lower():
            return "earn_income_review"
        return "generic_income_review"

    @staticmethod
    def _income_row_value(
        *,
        asset: str,
        quantity: Decimal,
        quote_asset: str | None,
        quote_quantity: Decimal | None,
        price_eur: Decimal | None,
    ) -> Decimal | None:
        if quantity <= 0:
            return None
        if quote_asset and str(quote_asset).upper() == "EUR" and quote_quantity is not None:
            return abs(quote_quantity)
        if asset.upper() == "EUR":
            return quantity
        if price_eur is None:
            return None
        return quantity * price_eur

    def _income_event_rows(self, *, event_types: tuple[str, ...]) -> list[tuple[object, ...]]:
        placeholders = ",".join(["?"] * len(event_types))
        with self.store.connect() as con:
            return con.execute(
                f"""
                select
                    e.event_id,
                    e.event_time,
                    e.event_type,
                    e.source,
                    e.account,
                    e.asset,
                    e.quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    e.tx_id
                from canonical_events e
                where e.event_type in ({placeholders})
                order by e.event_time, e.event_id
                """,
                list(event_types),
            ).fetchall()

    def _taxable_reward_tx_ids_by_asset(self) -> dict[str, set[str]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select upper(asset) as asset, tx_id
                from canonical_events
                where tx_id is not null
                  and quantity > 0
                  and event_type in ('reward', 'mining')
                  and upper(asset) in ('HNT', 'IOT', 'MOBILE')
                """
            ).fetchall()
        grouped: dict[str, set[str]] = defaultdict(set)
        for asset, tx_id in rows:
            if tx_id:
                grouped[str(asset).upper()].add(str(tx_id))
        return grouped

    @staticmethod
    def _is_duplicate_review_income_for_reward_tx(
        *,
        event_type: str,
        asset: str,
        quantity: Decimal,
        tx_id: str | None,
        reward_tx_ids: dict[str, set[str]],
    ) -> bool:
        if quantity <= 0 or event_type != "income" or not tx_id:
            return False
        return str(tx_id) in reward_tx_ids.get(asset.upper(), set())

    def _external_solana_income_rows(self, year: int) -> list[tuple[object, ...]]:
        tx_context = self._income_tx_context()
        reward_tx_ids = self._taxable_reward_tx_ids_by_asset()
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    event_id,
                    event_time,
                    source,
                    account,
                    asset,
                    quantity,
                    quote_asset,
                    quote_quantity,
                    tx_id
                from canonical_events
                where source = 'solana_rpc'
                  and event_type = 'income'
                  and quantity > 0
                  and quote_asset is null
                  and date_part('year', event_time)::integer = ?
                order by event_time, event_id
                """,
                [year],
            ).fetchall()
        return [
            row for row in rows
            if self._is_strict_external_solana_income_context(tx_context.get(row[8] or ""))
            and not self._is_duplicate_review_income_for_reward_tx(
                event_type="income",
                asset=str(row[4]),
                quantity=row[5],
                tx_id=row[8],
                reward_tx_ids=reward_tx_ids,
            )
        ]

    def _external_solana_inflow_count(self, year: int) -> int:
        if self._external_solana_inflow_counts_cache is None:
            tx_context = self._income_tx_context()
            reward_tx_ids = self._taxable_reward_tx_ids_by_asset()
            counts: dict[int, int] = defaultdict(int)
            with self.store.connect() as con:
                rows = con.execute(
                    """
                    select
                        date_part('year', event_time)::integer as year,
                        asset,
                        quantity,
                        tx_id
                    from canonical_events
                    where source = 'solana_rpc'
                      and event_type = 'income'
                      and quantity > 0
                      and quote_asset is null
                    order by event_time, event_id
                    """
                ).fetchall()
            for item_year, asset, quantity, tx_id in rows:
                if (
                    self._is_strict_external_solana_income_context(tx_context.get(tx_id or ""))
                    and not self._is_duplicate_review_income_for_reward_tx(
                        event_type="income",
                        asset=str(asset),
                        quantity=quantity,
                        tx_id=tx_id,
                        reward_tx_ids=reward_tx_ids,
                    )
                ):
                    counts[int(item_year)] += 1
            self._external_solana_inflow_counts_cache = dict(counts)
        return self._external_solana_inflow_counts_cache.get(year, 0)

    def _outgoing_events_by_asset(self) -> dict[str, list[dict[str, object]]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select event_id, event_time, source, account, asset, quantity, tx_id
                from canonical_events
                where quantity < 0
                  and event_type in ('transfer', 'trade', 'income', 'reward', 'staking', 'mining')
                order by event_time
                """
            ).fetchall()
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for event_id, event_time, source, account, asset, quantity, tx_id in rows:
            grouped[asset.upper()].append(
                {
                    "event_id": event_id,
                    "event_time": event_time,
                    "source": source,
                    "account": account,
                    "asset": asset,
                    "quantity": quantity,
                    "tx_id": tx_id,
                }
            )
        return grouped

    def _best_external_inflow_match(
        self,
        *,
        inflow_event_id: str,
        event_time: datetime,
        asset: str,
        quantity: Decimal,
        account: str | None,
        tx_id: str | None,
        outgoing: list[dict[str, object]],
    ) -> dict[str, object] | None:
        best: dict[str, object] | None = None
        for candidate in outgoing:
            if candidate["event_id"] == inflow_event_id:
                continue
            candidate_time = candidate["event_time"]
            if candidate_time > event_time:
                continue
            out_quantity = abs(candidate["quantity"])
            amount_delta = out_quantity - quantity
            tolerance = self._external_inflow_amount_tolerance(out_quantity, quantity)
            if abs(amount_delta) > tolerance:
                continue
            time_delta_seconds = int((event_time - candidate_time).total_seconds())
            score = 25
            reasons = [f"Menge innerhalb Toleranz {tolerance}"]
            warnings: list[str] = []
            if amount_delta == 0:
                score += 20
                reasons.append("Menge exakt gleich")
            if time_delta_seconds <= 6 * 3600:
                score += 30
                reasons.append("Zeitfenster <= 6h")
            elif time_delta_seconds <= 24 * 3600:
                score += 25
                reasons.append("Zeitfenster <= 24h")
            elif time_delta_seconds <= 7 * 24 * 3600:
                score += 15
                reasons.append("Zeitfenster <= 7d")
            elif time_delta_seconds <= 30 * 24 * 3600:
                score += 5
                reasons.append("Zeitfenster <= 30d")
            else:
                score -= 10
                warnings.append("Zeitabstand > 30 Tage")
            if candidate["source"] != "solana_rpc":
                score += 10
                reasons.append("Gegenbuchung aus anderer Quelle")
            if candidate["account"] and account and candidate["account"] != account:
                score += 5
                reasons.append("Unterschiedliche Konten")
            elif candidate["account"] and account and candidate["account"] == account:
                score -= 20
                warnings.append("Gleiche Quelle/Wallet; eher interne Solana-Bewegung als externer Transferbeleg")
            if tx_id and candidate["tx_id"]:
                if tx_id == candidate["tx_id"]:
                    score += 30
                    reasons.append("TX-ID stimmt ueberein")
                else:
                    warnings.append("TX-ID unterscheidet sich")
            result = {
                **candidate,
                "score": score,
                "amount_delta": amount_delta,
                "time_delta_seconds": time_delta_seconds,
                "reasons": reasons,
                "warnings": warnings,
            }
            if best is None or int(result["score"]) > int(best["score"]):
                best = result
        return best

    @staticmethod
    def _external_inflow_amount_tolerance(amount_out: Decimal, amount_in: Decimal) -> Decimal:
        base = max(amount_out, amount_in)
        return max(base * Decimal("0.0005"), Decimal("0.00000001"))

    def _income_tx_context(self) -> dict[str, dict[str, object]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    tx_id,
                    count(*)::integer as total_count,
                    count(*) filter (where quantity > 0)::integer as positive_count,
                    count(*) filter (where quantity < 0)::integer as negative_count,
                    count(*) filter (where quantity = 0)::integer as zero_count,
                    string_agg(distinct asset, ', ' order by asset) as assets
                from canonical_events
                where tx_id is not null
                group by tx_id
                """
            ).fetchall()
        return {
            row[0]: {
                "total_count": int(row[1] or 0),
                "positive_count": int(row[2] or 0),
                "negative_count": int(row[3] or 0),
                "zero_count": int(row[4] or 0),
                "assets": row[5] or "",
            }
            for row in rows
        }

    @staticmethod
    def _is_strict_external_solana_income_context(context: dict[str, object] | None) -> bool:
        if not context:
            return True
        return (
            int(context.get("total_count", 0) or 0) == 1
            and int(context.get("positive_count", 0) or 0) == 1
            and int(context.get("negative_count", 0) or 0) == 0
            and int(context.get("zero_count", 0) or 0) == 0
        )

    def _income_price_lookup(
        self,
        assets: list[str],
    ) -> dict[str, tuple[list[datetime], list[tuple[datetime, Decimal, str, Decimal, str]]]]:
        if not assets:
            return {}
        placeholders = ",".join(["?"] * len(assets))
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select upper(asset) as asset, priced_at, price_eur, source, confidence, price_id
                from price_ledger
                where upper(asset) in ({placeholders})
                  and price_eur > 0
                order by upper(asset), priced_at, created_at, price_id
                """,
                assets,
            ).fetchall()
        grouped: dict[str, list[tuple[datetime, Decimal, str, Decimal, str]]] = defaultdict(list)
        for asset, priced_at, price_eur, source, confidence, price_id in rows:
            grouped[asset].append((priced_at, price_eur, source, confidence, price_id))
        return {asset: ([item[0] for item in items], items) for asset, items in grouped.items()}

    @classmethod
    def _income_price_at(
        cls,
        asset: str,
        event_time: datetime,
        lookup: dict[str, tuple[list[datetime], list[tuple[datetime, Decimal, str, Decimal, str]]]],
    ) -> tuple[Decimal, str, datetime] | None:
        entry = lookup.get(asset.upper())
        if entry is None:
            return None
        times, items = entry
        index = bisect_right(times, event_time) - 1
        if index < 0:
            return None
        candidates = items[: index + 1]
        same_day_primary = [
            item for item in candidates
            if item[0].date() == event_time.date()
            and not cls._is_derived_price_source(item[2])
        ]
        selected = max(same_day_primary or candidates, key=cls._income_price_selection_key)
        priced_at, price_eur, source, _confidence, _price_id = selected
        return price_eur, source, priced_at

    @staticmethod
    def _income_price_selection_key(item: tuple[datetime, Decimal, str, Decimal, str]) -> tuple[datetime, int, Decimal, str]:
        priced_at, _price_eur, source, confidence, price_id = item
        return (
            priced_at,
            0 if TaxYearService._is_derived_price_source(source) else 10,
            confidence,
            price_id,
        )

    @staticmethod
    def _is_derived_price_source(source: str) -> bool:
        return source.strip().lower().startswith("derived:")

    @staticmethod
    def _asset_breakdown_for_lines(lines: list[object]) -> list[TaxYearAssetBreakdown]:
        grouped: dict[str, TaxYearAssetBreakdown] = {}
        for line in lines:
            item = grouped.setdefault(line.asset, TaxYearAssetBreakdown(asset=line.asset))
            item.gain_loss_eur += line.gain_loss_eur
            item.proceeds_eur += line.disposal_proceeds_eur
            item.acquisition_cost_eur += line.acquisition_cost_eur
            item.tax_line_count += 1
        return sorted(grouped.values(), key=lambda item: abs(item.gain_loss_eur), reverse=True)

    def _turnover_assets(
        self,
        lines: list[object],
        *,
        sort_by: str,
    ) -> list[TaxYearTurnoverAssetBreakdown]:
        grouped: dict[str, TaxYearTurnoverAssetBreakdown] = {}
        for line in lines:
            item = grouped.setdefault(
                line.asset,
                TaxYearTurnoverAssetBreakdown(
                    asset=line.asset,
                    stablecoin_like=self._is_stablecoin_like(line.asset),
                ),
            )
            item.tax_line_count += 1
            item.gross_disposal_proceeds_eur += line.disposal_proceeds_eur
            item.acquisition_cost_eur += line.acquisition_cost_eur
            item.gain_loss_eur += line.gain_loss_eur
            if self._is_taxable_private_disposal(line):
                item.taxable_gain_loss_eur += line.gain_loss_eur
            else:
                item.tax_free_gain_loss_eur += line.gain_loss_eur
        if sort_by == "proceeds":
            return sorted(grouped.values(), key=lambda item: abs(item.gross_disposal_proceeds_eur), reverse=True)
        return sorted(grouped.values(), key=lambda item: abs(item.gain_loss_eur), reverse=True)

    def _turnover_sources(self, year: int, *, limit: int) -> list[TaxYearTurnoverSourceBreakdown]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    coalesce(e.source, 'unknown') as source,
                    coalesce(e.event_type, 'unknown') as event_type,
                    l.asset as asset,
                    e.quote_asset as quote_asset,
                    count(*)::integer as tax_line_count,
                    coalesce(sum(l.disposal_proceeds_eur), 0) as proceeds_eur,
                    coalesce(sum(l.acquisition_cost_eur), 0) as acquisition_cost_eur,
                    coalesce(sum(l.gain_loss_eur), 0) as gain_loss_eur
                from tax_lines l
                left join canonical_events e on e.event_id = l.source_event_id
                where date_part('year', l.disposed_at)::integer = ?
                group by source, event_type, l.asset, e.quote_asset
                order by abs(coalesce(sum(l.disposal_proceeds_eur), 0)) desc
                limit ?
                """,
                [year, limit],
            ).fetchall()
        return [
            TaxYearTurnoverSourceBreakdown(
                source=row[0],
                event_type=row[1],
                asset=row[2],
                quote_asset=row[3],
                tax_line_count=row[4],
                gross_disposal_proceeds_eur=row[5],
                acquisition_cost_eur=row[6],
                gain_loss_eur=row[7],
            )
            for row in rows
        ]

    @staticmethod
    def _turnover_plain_language_summary(
        year: int,
        *,
        gross_proceeds: Decimal,
        taxable_gain: Decimal,
        tax_free_gain: Decimal,
        stablecoin_proceeds: Decimal,
        stablecoin_gain: Decimal,
        external_value: Decimal,
    ) -> str:
        return (
            f"{year}: Handels-/Swap-Volumen {gross_proceeds:.2f} EUR ist "
            f"kein eingesetztes oder ausgezahltes EUR-Kapital. "
            f"Steuerpflichtiger privater Gewinn/Verlust: {taxable_gain:.2f} EUR; "
            f"steuerfreier Gewinn/Verlust nach Haltefrist: {tax_free_gain:.2f} EUR. "
            f"Stablecoin-Handelsvolumen: {stablecoin_proceeds:.2f} EUR bei "
            f"{stablecoin_gain:.2f} EUR FIFO-Ergebnis. "
            f"Offene externe Zufluesse zur Belegpruefung: {external_value:.2f} EUR."
        )

    @staticmethod
    def _turnover_summary_row(audit: TaxYearTurnoverAudit) -> TaxYearTurnoverAuditSummaryRow:
        stablecoin_ratio = (
            abs(audit.stablecoin_gain_loss_eur) / audit.stablecoin_gross_disposal_proceeds_eur * Decimal("100")
            if audit.stablecoin_gross_disposal_proceeds_eur
            else Decimal("0")
        )
        reasons: list[str] = []
        if audit.stablecoin_gross_disposal_proceeds_eur:
            reasons.append("stablecoin_turnover_present")
        if abs(audit.stablecoin_gain_loss_eur) >= Decimal("100") and stablecoin_ratio >= Decimal("1"):
            reasons.append("material_stablecoin_fifo_gain_or_loss")
        if audit.external_inflows_review_count or audit.external_inflows_unmatched_count:
            reasons.append("external_solana_inflows_need_evidence")
        if audit.external_inflows_review_unmatched_value_eur >= Decimal("1000"):
            reasons.append("material_external_inflow_value")
        if audit.gross_disposal_proceeds_eur and abs(audit.combined_gain_loss_eur) > audit.gross_disposal_proceeds_eur:
            reasons.append("gain_exceeds_gross_turnover")
        if "material_stablecoin_fifo_gain_or_loss" in reasons or "material_external_inflow_value" in reasons:
            risk_level = "high"
        elif reasons:
            risk_level = "review"
        else:
            risk_level = "ok"
        return TaxYearTurnoverAuditSummaryRow(
            year=audit.year,
            risk_level=risk_level,
            gross_disposal_proceeds_eur=audit.gross_disposal_proceeds_eur,
            taxable_gain_loss_eur=audit.taxable_gain_loss_eur,
            tax_free_gain_loss_eur=audit.tax_free_gain_loss_eur,
            stablecoin_gross_disposal_proceeds_eur=audit.stablecoin_gross_disposal_proceeds_eur,
            stablecoin_gain_loss_eur=audit.stablecoin_gain_loss_eur,
            stablecoin_gain_ratio_pct=stablecoin_ratio,
            external_inflows_review_unmatched_value_eur=audit.external_inflows_review_unmatched_value_eur,
            external_inflows_review_count=audit.external_inflows_review_count,
            external_inflows_unmatched_count=audit.external_inflows_unmatched_count,
            caveats_count=len(audit.caveats),
            reasons=reasons,
            audit_endpoint=f"/api/v1/tax-years/{audit.year}/turnover-audit",
        )

    def _solana_program_income_rows(
        self,
        year: int | None,
        *,
        classifications: set[str] | None = None,
    ) -> list[TaxSolanaProgramIncomeRow]:
        rows = self._income_event_rows(event_types=("income",))
        tx_context = self._income_tx_context()
        assets = sorted({str(row[5]).upper() for row in rows if row[6] > 0 and str(row[5]).upper() != "EUR"})
        price_lookup = self._income_price_lookup(assets)
        results: list[TaxSolanaProgramIncomeRow] = []
        accepted_classifications = classifications or {"solana_program_or_swap_income_review"}
        for (
            event_id,
            event_time,
            event_type,
            source,
            account,
            asset,
            quantity,
            quote_asset,
            quote_quantity,
            tx_id,
        ) in rows:
            if year is not None and event_time.year != year:
                continue
            classification = self._income_classification(
                event_type=event_type,
                source=source,
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                account=account,
                tx_id=tx_id,
                tx_context=tx_context,
            )
            if classification not in accepted_classifications:
                continue
            price_eur = None
            if quantity > 0 and asset.upper() != "EUR":
                price = self._income_price_at(asset, event_time, price_lookup)
                if price is not None:
                    price_eur = price[0]
            value_eur = self._income_row_value(
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                quote_quantity=quote_quantity,
                price_eur=price_eur,
            )
            context = tx_context.get(tx_id or "", {})
            results.append(
                TaxSolanaProgramIncomeRow(
                    event_id=event_id,
                    event_time=event_time.isoformat(),
                    source=source,
                    account=account,
                    asset=asset,
                    quantity=quantity,
                    value_eur=value_eur,
                    tx_id=tx_id,
                    tx_total_count=int(context.get("total_count", 0) or 0),
                    tx_positive_count=int(context.get("positive_count", 0) or 0),
                    tx_negative_count=int(context.get("negative_count", 0) or 0),
                    tx_zero_count=int(context.get("zero_count", 0) or 0),
                    tx_assets=str(context.get("assets", "") or ""),
                    classification=classification,
                    review_reason=self._solana_program_income_reason(context),
                )
            )
        return results

    @staticmethod
    def _solana_program_income_reason(context: dict[str, object]) -> str:
        total = int(context.get("total_count", 0) or 0)
        negative = int(context.get("negative_count", 0) or 0)
        zero = int(context.get("zero_count", 0) or 0)
        if negative > 0:
            return "same_tx_has_outgoing_leg"
        if zero > 0:
            return "same_tx_has_zero_or_unknown_program_context"
        if total > 1:
            return "same_tx_has_additional_positive_program_context"
        return "non_isolated_solana_income_context"

    @staticmethod
    def _helium_swap_context_reason(row: TaxSolanaProgramIncomeRow) -> str:
        if row.classification == "solana_helium_trade_context":
            return "helium_asset_normalized_as_solana_trade"
        if row.tx_negative_count > 0:
            return "helium_asset_received_in_same_tx_with_outgoing_leg"
        if row.tx_total_count > 1:
            return "helium_asset_received_in_multi_leg_solana_program_context"
        return "helium_asset_program_context_not_reward"

    def _helium_solana_trade_context_rows(self, year: int | None) -> list[TaxSolanaProgramIncomeRow]:
        rows = self._income_event_rows(event_types=("trade",))
        tx_context = self._income_tx_context()
        assets = sorted({str(row[5]).upper() for row in rows if row[6] > 0 and str(row[5]).upper() != "EUR"})
        price_lookup = self._income_price_lookup(assets)
        results: list[TaxSolanaProgramIncomeRow] = []
        for (
            event_id,
            event_time,
            _event_type,
            source,
            account,
            asset,
            quantity,
            quote_asset,
            quote_quantity,
            tx_id,
        ) in rows:
            if year is not None and event_time.year != year:
                continue
            asset_key = str(asset).upper()
            if source != "solana_rpc" or asset_key not in HELIUM_REWARD_ASSETS or quantity <= 0:
                continue
            price_eur = None
            if asset_key != "EUR":
                price = self._income_price_at(asset, event_time, price_lookup)
                if price is not None:
                    price_eur = price[0]
            value_eur = self._income_row_value(
                asset=asset,
                quantity=quantity,
                quote_asset=quote_asset,
                quote_quantity=quote_quantity,
                price_eur=price_eur,
            )
            context = tx_context.get(tx_id or "", {})
            results.append(
                TaxSolanaProgramIncomeRow(
                    event_id=event_id,
                    event_time=event_time.isoformat(),
                    source=source,
                    account=account,
                    asset=asset_key,
                    quantity=quantity,
                    value_eur=value_eur,
                    tx_id=tx_id,
                    tx_total_count=int(context.get("total_count", 0) or 0),
                    tx_positive_count=int(context.get("positive_count", 0) or 0),
                    tx_negative_count=int(context.get("negative_count", 0) or 0),
                    tx_zero_count=int(context.get("zero_count", 0) or 0),
                    tx_assets=str(context.get("assets", "") or ""),
                    classification="solana_helium_trade_context",
                    review_reason="helium_asset_normalized_as_solana_trade",
                )
            )
        return results

    @staticmethod
    def _primary_helium_asset_from_set(assets: set[object]) -> str:
        normalized = {str(asset).upper() for asset in assets}
        for asset in HELIUM_REWARD_ASSETS:
            if asset in normalized:
                return asset
        return "HNT"

    def _raw_evidence_summary_by_tx(self, tx_ids: set[str]) -> dict[str, dict[str, object]]:
        if not tx_ids:
            return {}
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    e.tx_id,
                    e.event_id,
                    e.raw_object_id,
                    b.source,
                    b.filename
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where e.tx_id in (select unnest(?))
                order by e.tx_id, e.event_time, e.event_id
                """,
                [list(tx_ids)],
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for tx_id, _event_id, raw_object_id, source, filename in rows:
            if not tx_id:
                continue
            item = result.setdefault(
                str(tx_id),
                {
                    "raw_object_ids": set(),
                    "raw_filenames": set(),
                    "raw_sources": set(),
                },
            )
            raw_ids = item["raw_object_ids"]
            raw_filenames = item["raw_filenames"]
            raw_sources = item["raw_sources"]
            if raw_object_id and isinstance(raw_ids, set):
                raw_ids.add(str(raw_object_id))
            if filename and isinstance(raw_filenames, set):
                raw_filenames.add(self._safe_evidence_filename(filename))
            if source and isinstance(raw_sources, set):
                raw_sources.add(str(source))
        return {
            tx_id: {
                "raw_evidence_count": len(item["raw_object_ids"]) if isinstance(item["raw_object_ids"], set) else 0,
                "raw_filenames": sorted(item["raw_filenames"]) if isinstance(item["raw_filenames"], set) else [],
                "raw_sources": sorted(item["raw_sources"]) if isinstance(item["raw_sources"], set) else [],
            }
            for tx_id, item in result.items()
        }

    @staticmethod
    def _safe_evidence_filename(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        basename = text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or text
        if basename == "steuerreport_ai_readonly.tmp.sqlite":
            return "read-only-sqlite-evidence"
        return basename

    def _helium_swap_alchemy_audit_match_summary(self, expected_tx_ids: set[str]) -> dict[str, int | str]:
        if not expected_tx_ids:
            return {
                "status": "empty",
                "expected_count": 0,
                "artifact_tx_count": 0,
                "confirmed_count": 0,
                "missing_count": 0,
            }
        if not HELIUM_SWAP_ALCHEMY_AUDIT_PATH.exists():
            return {
                "status": "missing_artifact",
                "expected_count": len(expected_tx_ids),
                "artifact_tx_count": 0,
                "confirmed_count": 0,
                "missing_count": len(expected_tx_ids),
            }
        try:
            payload = json.loads(HELIUM_SWAP_ALCHEMY_AUDIT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {
                "status": "invalid_artifact",
                "expected_count": len(expected_tx_ids),
                "artifact_tx_count": 0,
                "confirmed_count": 0,
                "missing_count": len(expected_tx_ids),
            }
        rows = payload.get("rows") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        confirmed = {
            str(row.get("tx_id"))
            for row in rows
            if isinstance(row, dict)
            and row.get("tx_id")
            and row.get("review_status") == "alchemy_confirmed"
        }
        missing = expected_tx_ids - confirmed
        return {
            "status": "complete" if not missing else "partial",
            "expected_count": len(expected_tx_ids),
            "artifact_tx_count": len(rows),
            "confirmed_count": len(expected_tx_ids & confirmed),
            "missing_count": len(missing),
        }

    def _helium_trade_tax_line_summary_by_year_asset(self) -> dict[tuple[int, str], dict[str, Decimal | int]]:
        result: dict[tuple[int, str], dict[str, Decimal | int]] = {}
        for line in self._tax_lines():
            asset = str(getattr(line, "asset", "") or "").upper()
            if asset not in HELIUM_REWARD_ASSETS:
                continue
            year = getattr(line, "disposed_at").year
            key = (year, asset)
            item = result.setdefault(
                key,
                {
                    "taxable_gain_loss_eur": Decimal("0"),
                    "tax_free_gain_loss_eur": Decimal("0"),
                    "taxable_lines_count": 0,
                    "tax_free_lines_count": 0,
                },
            )
            if self._is_taxable_private_disposal(line):
                item["taxable_gain_loss_eur"] = item["taxable_gain_loss_eur"] + line.gain_loss_eur  # type: ignore[operator]
                item["taxable_lines_count"] = int(item["taxable_lines_count"]) + 1
            else:
                item["tax_free_gain_loss_eur"] = item["tax_free_gain_loss_eur"] + line.gain_loss_eur  # type: ignore[operator]
                item["tax_free_lines_count"] = int(item["tax_free_lines_count"]) + 1
        return result

    def _stablecoin_fifo_lines(self, year: int | None) -> list[TaxStablecoinFifoLine]:
        params: list[object] = [list(STABLECOIN_LIKE_ASSETS)]
        year_filter = ""
        if year is not None:
            year_filter = "and date_part('year', l.disposed_at)::integer = ?"
            params.append(year)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    l.tax_line_id,
                    date_part('year', l.disposed_at)::integer as year,
                    l.asset,
                    l.quantity,
                    lot.acquired_at,
                    l.disposed_at,
                    l.holding_days,
                    l.acquisition_cost_eur,
                    l.disposal_proceeds_eur,
                    l.gain_loss_eur,
                    l.source_event_id as disposal_event_id,
                    d.source as disposal_source,
                    d.event_type as disposal_event_type,
                    d.quote_asset as disposal_quote_asset,
                    d.quote_quantity as disposal_quote_quantity,
                    d.tx_id as disposal_tx_id,
                    d.account as disposal_account,
                    d.raw_object_id as disposal_raw_object_id,
                    dr.batch_id as disposal_batch_id,
                    db.filename as disposal_batch_filename,
                    dr.row_number as disposal_row_number,
                    l.lot_id,
                    lot.source_event_id as acquisition_event_id,
                    a.source as acquisition_source,
                    a.event_type as acquisition_event_type,
                    a.quote_asset as acquisition_quote_asset,
                    a.quote_quantity as acquisition_quote_quantity,
                    a.tx_id as acquisition_tx_id,
                    a.account as acquisition_account,
                    a.raw_object_id as acquisition_raw_object_id,
                    ar.batch_id as acquisition_batch_id,
                    ab.filename as acquisition_batch_filename,
                    ar.row_number as acquisition_row_number
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                left join canonical_events d on d.event_id = l.source_event_id
                left join canonical_events a on a.event_id = lot.source_event_id
                left join raw_objects dr on dr.raw_object_id = d.raw_object_id
                left join raw_import_batches db on db.batch_id = dr.batch_id
                left join raw_objects ar on ar.raw_object_id = a.raw_object_id
                left join raw_import_batches ab on ab.batch_id = ar.batch_id
                where upper(l.asset) in (select unnest(?))
                {year_filter}
                order by abs(l.gain_loss_eur) desc, l.disposed_at, l.tax_line_id
                """,
                params,
            ).fetchall()
        tx_context = self._income_tx_context()
        result: list[TaxStablecoinFifoLine] = []
        for row in rows:
            holding_days = int(row[6] or 0)
            acquisition_classification = self._income_classification(
                event_type=row[24] or "",
                source=row[23] or "",
                asset=row[2],
                quantity=row[3],
                quote_asset=row[25],
                account=row[28],
                tx_id=row[27],
                tx_context=tx_context,
            )
            acquisition_evidence_status = (
                "raw_import_row_available"
                if row[29] and row[30]
                else "canonical_event_without_raw_row"
                if row[18]
                else "missing_acquisition_event"
            )
            result.append(
                TaxStablecoinFifoLine(
                    tax_line_id=row[0],
                    year=int(row[1]),
                    asset=row[2],
                    quantity=row[3],
                    acquired_at=row[4].isoformat(),
                    disposed_at=row[5].isoformat(),
                    holding_days=holding_days,
                    taxable=holding_days <= 365,
                    acquisition_cost_eur=row[7],
                    disposal_proceeds_eur=row[8],
                    gain_loss_eur=row[9],
                    disposal_event_id=row[10],
                    disposal_source=row[11],
                    disposal_event_type=row[12],
                    disposal_quote_asset=row[13],
                    disposal_quote_quantity=row[14],
                    disposal_tx_id=row[15],
                    disposal_account=row[16],
                    disposal_raw_object_id=row[17],
                    disposal_batch_id=row[18],
                    disposal_batch_filename=row[19],
                    disposal_row_number=row[20],
                    lot_id=row[21],
                    acquisition_event_id=row[22],
                    acquisition_source=row[23],
                    acquisition_event_type=row[24],
                    acquisition_quote_asset=row[25],
                    acquisition_quote_quantity=row[26],
                    acquisition_tx_id=row[27],
                    acquisition_account=row[28],
                    acquisition_raw_object_id=row[29],
                    acquisition_batch_id=row[30],
                    acquisition_batch_filename=row[31],
                    acquisition_row_number=row[32],
                    acquisition_evidence_status=acquisition_evidence_status,
                    acquisition_classification=acquisition_classification,
                    review_reason=self._stablecoin_fifo_review_reason(
                        gain_loss_eur=row[9],
                        acquisition_classification=acquisition_classification,
                        acquisition_source=row[23],
                        disposal_source=row[11],
                    ),
                )
            )
        return result

    @staticmethod
    def _stablecoin_fifo_review_reason(
        *,
        gain_loss_eur: Decimal,
        acquisition_classification: str,
        acquisition_source: str | None,
        disposal_source: str | None,
    ) -> str:
        if acquisition_classification == "solana_program_or_swap_income_review":
            return "stablecoin_lot_from_solana_program_context"
        if abs(gain_loss_eur) >= Decimal("100"):
            return "material_stablecoin_fifo_gain_loss"
        if acquisition_source != disposal_source:
            return "stablecoin_lot_cross_source"
        return "stablecoin_fifo_line_review"

    def _stablecoin_quote_leg_rows(self, year: int | None) -> list[TaxStablecoinQuoteLegRow]:
        params: list[object] = [list(STABLECOIN_LIKE_ASSETS) for _ in range(13)]
        year_filter = ""
        if year is not None:
            year_filter = "and date_part('year', e.event_time)::integer = ?"
            params.append(year)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                with stable_events as (
                    select
                        e.event_id,
                        date_part('year', e.event_time)::integer as year,
                        e.event_time,
                        e.source,
                        e.account,
                        e.event_type,
                        upper(e.asset) as asset,
                        e.quantity,
                        upper(e.quote_asset) as quote_asset,
                        e.quote_quantity,
                        e.tx_id,
                        e.raw_object_id,
                        r.batch_id,
                        b.filename,
                        r.row_number,
                        case
                            when upper(e.asset) in (select unnest(?))
                             and upper(e.quote_asset) in (select unnest(?))
                             and upper(e.asset) = upper(e.quote_asset)
                                then 'same_stable_asset_and_quote'
                            when upper(e.asset) in (select unnest(?))
                             and upper(e.quote_asset) in (select unnest(?))
                                then 'stable_to_stable'
                            when upper(e.asset) in (select unnest(?))
                                then 'stable_asset'
                            when upper(e.quote_asset) in (select unnest(?))
                                then 'stable_quote'
                            else 'none'
                        end as stable_role,
                        case
                            when upper(e.asset) in (select unnest(?))
                             and upper(e.quote_asset) in (select unnest(?))
                             and e.quantity > 0
                                then upper(e.quote_asset)
                            when upper(e.asset) in (select unnest(?))
                             and upper(e.quote_asset) in (select unnest(?))
                             and e.quantity < 0
                                then upper(e.asset)
                            when upper(e.asset) in (select unnest(?)) then upper(e.asset)
                            else upper(e.quote_asset)
                        end as stable_asset
                    from canonical_events e
                    left join raw_objects r on r.raw_object_id = e.raw_object_id
                    left join raw_import_batches b on b.batch_id = r.batch_id
                    where e.event_type = 'trade'
                      and (
                        upper(e.asset) in (select unnest(?))
                        or upper(e.quote_asset) in (select unnest(?))
                      )
                      and upper(e.asset) <> 'EUR'
                      and coalesce(upper(e.quote_asset), '') <> 'EUR'
                      {year_filter}
                ),
                event_tax_lines as (
                    select
                        se.event_id,
                        count(l.tax_line_id)::integer as stable_tax_lines_count,
                        coalesce(sum(l.disposal_proceeds_eur), 0) as stable_disposal_proceeds_eur,
                        coalesce(sum(l.gain_loss_eur), 0) as stable_gain_loss_eur
                    from stable_events se
                    left join tax_lines l
                      on l.source_event_id = se.event_id
                     and upper(l.asset) = se.stable_asset
                    group by se.event_id
                )
                select
                    se.event_id,
                    se.year,
                    se.event_time,
                    se.source,
                    se.account,
                    se.event_type,
                    se.asset,
                    se.quantity,
                    se.quote_asset,
                    se.quote_quantity,
                    se.tx_id,
                    se.raw_object_id,
                    se.batch_id,
                    se.filename,
                    se.row_number,
                    se.stable_role,
                    se.stable_asset,
                    etl.stable_tax_lines_count,
                    etl.stable_disposal_proceeds_eur,
                    etl.stable_gain_loss_eur
                from stable_events se
                left join event_tax_lines etl on etl.event_id = se.event_id
                order by se.event_time, se.event_id
                """,
                params,
            ).fetchall()
        result: list[TaxStablecoinQuoteLegRow] = []
        for row in rows:
            quantity = row[7] or Decimal("0")
            role = row[15]
            expected_tax_effect, expected_tax_line = self._stablecoin_quote_expected_effect(
                stable_role=role,
                quantity=quantity,
            )
            stable_tax_lines_count = int(row[17] or 0)
            result.append(
                TaxStablecoinQuoteLegRow(
                    event_id=row[0],
                    year=int(row[1]),
                    event_time=row[2].isoformat(),
                    source=row[3],
                    account=row[4],
                    event_type=row[5],
                    asset=row[6],
                    quantity=quantity,
                    quote_asset=row[8],
                    quote_quantity=row[9],
                    tx_id=row[10],
                    raw_object_id=row[11],
                    batch_id=row[12],
                    batch_filename=row[13],
                    row_number=row[14],
                    stable_role=role,
                    stable_asset=row[16],
                    expected_tax_effect=expected_tax_effect,
                    expected_tax_line=expected_tax_line,
                    stable_tax_lines_count=stable_tax_lines_count,
                    stable_disposal_proceeds_eur=row[18] or Decimal("0"),
                    stable_gain_loss_eur=row[19] or Decimal("0"),
                    review_reason=self._stablecoin_quote_leg_review_reason(
                        stable_role=role,
                        expected_tax_line=expected_tax_line,
                        stable_tax_lines_count=stable_tax_lines_count,
                        stable_gain_loss_eur=row[19] or Decimal("0"),
                    ),
                )
            )
        return result

    @staticmethod
    def _stablecoin_quote_expected_effect(*, stable_role: str, quantity: Decimal) -> tuple[str, bool]:
        if stable_role == "same_stable_asset_and_quote":
            return "same_stable_asset_and_quote_review", quantity < 0
        if stable_role == "stable_to_stable":
            return "stable_to_stable_quote_leg_review", quantity > 0
        if stable_role == "stable_quote":
            return ("stable_quote_disposal", True) if quantity > 0 else ("stable_quote_lot_acquisition", False)
        if stable_role == "stable_asset":
            return ("stable_asset_disposal", True) if quantity < 0 else ("stable_lot_acquisition", False)
        return "not_stablecoin_relevant", False

    @staticmethod
    def _stablecoin_quote_leg_review_reason(
        *,
        stable_role: str,
        expected_tax_line: bool,
        stable_tax_lines_count: int,
        stable_gain_loss_eur: Decimal,
    ) -> str:
        if expected_tax_line and stable_tax_lines_count == 0:
            return "missing_expected_stablecoin_tax_line"
        if stable_role in {"stable_to_stable", "same_stable_asset_and_quote"}:
            return "stable_to_stable_quote_leg_review"
        if abs(stable_gain_loss_eur) >= Decimal("100"):
            return "material_stablecoin_quote_leg_gain_loss"
        return "stablecoin_quote_leg_ok"

    def _stablecoin_solana_tx_context(self, tx_ids: set[str]) -> dict[str, dict[str, object]]:
        if not tx_ids:
            return {}
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    e.tx_id,
                    count(*)::integer as tx_total_count,
                    sum(case when e.quantity > 0 then 1 else 0 end)::integer as tx_positive_count,
                    sum(case when e.quantity < 0 then 1 else 0 end)::integer as tx_negative_count,
                    sum(case when e.quantity = 0 then 1 else 0 end)::integer as tx_zero_count,
                    string_agg(distinct upper(e.asset), ', ' order by upper(e.asset)) as tx_assets,
                    string_agg(distinct e.event_type, ', ' order by e.event_type) as tx_event_types,
                    count(r.raw_object_id)::integer as raw_evidence_count,
                    string_agg(distinct coalesce(b.filename, 'unknown'), ' | ' order by coalesce(b.filename, 'unknown')) as raw_filenames
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where e.tx_id in (select unnest(?))
                group by e.tx_id
                """,
                [list(tx_ids)],
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            filenames = [item.strip() for item in str(row[8] or "").split("|") if item.strip()]
            result[str(row[0])] = {
                "tx_total_count": int(row[1] or 0),
                "tx_positive_count": int(row[2] or 0),
                "tx_negative_count": int(row[3] or 0),
                "tx_zero_count": int(row[4] or 0),
                "tx_assets": str(row[5] or ""),
                "tx_event_types": str(row[6] or ""),
                "raw_evidence_count": int(row[7] or 0),
                "raw_filenames": filenames,
            }
        return result

    def _jupiter_token_status_by_symbol(self) -> dict[str, str]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select upper(coalesce(symbol, mint)) as key, risk_status
                from jupiter_token_metadata_cache
                where coalesce(symbol, mint) is not null
                """
            ).fetchall()
        result = {str(row[0]).upper(): str(row[1]) for row in rows if row[0]}
        for stable in STABLECOIN_LIKE_ASSETS:
            result.setdefault(stable, "verified")
        result.setdefault("SOL", "verified")
        return result

    @staticmethod
    def _solana_stablecoin_swap_classification(
        *,
        quote_row: TaxStablecoinQuoteLegRow,
        tx_assets: str,
        tx_total_count: int,
        raw_evidence_count: int,
    ) -> tuple[str, str, str]:
        stable_assets = set(STABLECOIN_LIKE_ASSETS)
        assets = {item.strip().upper() for item in tx_assets.split(",") if item.strip()}
        has_stable = bool(assets & stable_assets)
        has_non_stable = bool(assets - stable_assets)
        if quote_row.stable_role in {"stable_to_stable", "same_stable_asset_and_quote"}:
            return (
                "solana_stablecoin_conversion_review",
                "medium" if raw_evidence_count else "low",
                "Stablecoin-zu-Stablecoin-Transaktion gegen Solscan/Jupiter pruefen und als Swap, Transfer oder Conversion dokumentieren.",
            )
        if quote_row.expected_tax_effect == "stable_quote_disposal" and has_stable and has_non_stable and tx_total_count >= 1:
            return (
                "solana_swap_stablecoin_quote_disposal",
                "high" if raw_evidence_count else "medium",
                "Als Solana-Swap-Kontext plausibel; Signatur/Raw-Zeile als Beleg zum FIFO-Quote-Bein aufbewahren.",
            )
        if abs(quote_row.stable_gain_loss_eur) >= Decimal("100"):
            return (
                "material_solana_stablecoin_quote_review",
                "medium" if raw_evidence_count else "low",
                "Materielles Stablecoin-Quote-Ergebnis; Signaturdetails und Preis-/FX-Bewertung pruefen.",
            )
        return (
            "solana_stablecoin_quote_context",
            "medium" if raw_evidence_count else "low",
            "Solana-Stablecoin-Quote-Bein im Kontext belassen und bei Jahresbelegen mit ausweisen.",
        )

    @staticmethod
    def _solana_stablecoin_swap_review_reason(
        *,
        row: TaxStablecoinQuoteLegRow,
        raw_evidence_count: int,
        jupiter_asset_status: str,
        jupiter_quote_status: str,
    ) -> str:
        if raw_evidence_count == 0:
            return "missing_solana_raw_evidence"
        if row.stable_role in {"stable_to_stable", "same_stable_asset_and_quote"}:
            return "stablecoin_conversion_needs_classification"
        if abs(row.stable_gain_loss_eur) >= Decimal("100"):
            return "material_solana_stablecoin_quote_gain_loss"
        if jupiter_asset_status == "unknown" and jupiter_quote_status == "unknown":
            return "jupiter_metadata_unknown"
        return "solana_swap_context_evidence_available"

    @staticmethod
    def _stablecoin_fx_basis_status(price_source: str | None) -> str:
        if not price_source:
            return "missing_price"
        normalized = price_source.lower()
        if "usd_eur" in normalized or "fx" in normalized or "ecb" in normalized:
            return "fx_backed"
        if HistoricalPriceLookup.is_derived_source(price_source):
            return "derived_event_quote_review"
        if "coingecko" in normalized or "market" in normalized or "manual" in normalized or "unit" in normalized:
            return "market_price_review"
        return "price_source_review"

    @staticmethod
    def _stablecoin_fx_review_reason(
        *,
        price_point_source: str | None,
        price_age_days: int | None,
        price_delta_pct: Decimal | None,
        gain_loss_eur: Decimal,
    ) -> tuple[str, str]:
        if not price_point_source:
            return (
                "missing_stablecoin_price",
                "Historischen Stablecoin-EUR-Preis bzw. USD/EUR-FX fuer den Swap-Zeitpunkt belegen.",
            )
        if price_age_days is not None and price_age_days > 7:
            return (
                "stale_stablecoin_price",
                "Preispunkt liegt mehr als 7 Tage vor dem Swap; Tages-FX oder naeheren Stablecoin-Preis pruefen.",
            )
        if HistoricalPriceLookup.is_derived_source(price_point_source):
            return (
                "derived_event_quote_price_review",
                "Derived/Event-Quote nicht als finale FX-Evidenz verwenden; USD/EUR-FX oder belastbaren Marktpreis nachweisen.",
            )
        if price_delta_pct is not None and price_delta_pct > Decimal("0.1"):
            return (
                "stablecoin_price_delta_review",
                "Implied Stablecoin-Preis weicht vom ausgewaehlten Preispunkt ab; Tax-Line-Proceeds und Preisquelle pruefen.",
            )
        if abs(gain_loss_eur) >= Decimal("100") and "usd_eur" not in price_point_source.lower() and "fx" not in price_point_source.lower():
            return (
                "material_stablecoin_market_price_review",
                "Materielle Stablecoin-Zeile nutzt Markt-/Manuellpreis; fuer Finanzamt USD/EUR-FX oder Preisbeleg archivieren.",
            )
        return (
            "stablecoin_fx_price_basis_ok",
            "Preisquelle und Tax-Line-Proceeds sind rechnerisch konsistent; Belegquelle im Jahrespaket mitfuehren.",
        )

    @staticmethod
    def _driver_line(line: object, *, taxable: bool) -> TaxYearDriverLine:
        return TaxYearDriverLine(
            tax_line_id=line.tax_line_id,
            asset=line.asset,
            acquired_at=line.acquired_at.isoformat(),
            disposed_at=line.disposed_at.isoformat(),
            holding_days=line.holding_days,
            quantity=line.quantity,
            acquisition_cost_eur=line.acquisition_cost_eur,
            disposal_proceeds_eur=line.disposal_proceeds_eur,
            gain_loss_eur=line.gain_loss_eur,
            taxable=taxable,
            source_event_id=line.source_event_id,
            lot_id=line.lot_id,
        )

    @staticmethod
    def _asset_fifo_event(row: tuple[object, ...]) -> TaxYearAssetFifoEvent | None:
        if not row or row[0] is None:
            return None
        event_time = row[3]
        return TaxYearAssetFifoEvent(
            event_id=row[0],
            source=row[1],
            source_ref=row[2],
            event_time=event_time.isoformat() if event_time is not None else None,
            event_type=row[4],
            asset=row[5],
            quantity=row[6],
            quote_asset=row[7],
            quote_quantity=row[8],
            tx_id=row[9],
            wallet=row[10],
            account=row[11],
            raw_object_id=row[12],
        )

    @staticmethod
    def _asset_fifo_raw(row: tuple[object, ...]) -> TaxYearAssetFifoRawEvidence | None:
        if not row or row[0] is None:
            return None
        return TaxYearAssetFifoRawEvidence(
            raw_object_id=row[0],
            batch_id=row[1],
            source=row[2],
            filename=row[3],
            row_number=row[4],
            payload_json=row[5],
        )

    @staticmethod
    def _asset_fifo_plausibility_reasons(
        *,
        direct_gain: Decimal,
        linked_gain: Decimal,
        direct_lines: int,
        linked_lines: int,
        min_abs_gain_eur: Decimal,
    ) -> list[str]:
        reasons: list[str] = []
        if abs(linked_gain) >= min_abs_gain_eur:
            reasons.append("material_linked_quote_gain_or_loss")
        if direct_lines and abs(direct_gain) < min_abs_gain_eur and abs(linked_gain) >= min_abs_gain_eur:
            reasons.append("direct_asset_near_zero_but_quote_effect_material")
        if direct_lines == 0 and linked_lines:
            reasons.append("asset_only_seen_in_related_quote_or_counter_events")
        if linked_lines >= 20:
            reasons.append("many_related_quote_or_counter_lines")
        if abs(direct_gain) >= min_abs_gain_eur:
            reasons.append("material_direct_asset_gain_or_loss")
        return reasons or ["no_material_plausibility_signal"]

    @staticmethod
    def _asset_fifo_plausibility_risk(reasons: list[str]) -> Literal["ok", "review", "high"]:
        high_reasons = {
            "direct_asset_near_zero_but_quote_effect_material",
            "asset_only_seen_in_related_quote_or_counter_events",
        }
        if any(reason in high_reasons for reason in reasons):
            return "high"
        if any(reason != "no_material_plausibility_signal" for reason in reasons):
            return "review"
        return "ok"

    def _asset_fifo_related_raw_counts(self, year: int, asset: str) -> dict[str, int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    sum(
                        case
                            when coalesce(ae.raw_object_id, de.raw_object_id) is not null then 1
                            else 0
                        end
                    )::integer as present_count,
                    sum(
                        case
                            when coalesce(ae.raw_object_id, de.raw_object_id) is null then 1
                            else 0
                        end
                    )::integer as missing_count
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                left join canonical_events de on de.event_id = l.source_event_id
                left join canonical_events ae on ae.event_id = lot.source_event_id
                where date_part('year', l.disposed_at)::integer = ?
                  and (
                      upper(l.asset) = ?
                      or upper(coalesce(de.asset, '')) = ?
                      or upper(coalesce(de.quote_asset, '')) = ?
                      or upper(coalesce(ae.asset, '')) = ?
                      or upper(coalesce(ae.quote_asset, '')) = ?
                  )
                """,
                [year, asset, asset, asset, asset, asset],
            ).fetchone()
        return {
            "present": int((row[0] if row else 0) or 0),
            "missing": int((row[1] if row else 0) or 0),
        }

    def _asset_fifo_related_role_counts(self, year: int, asset: str) -> dict[str, int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    sum(case when upper(l.asset) = ? then 1 else 0 end)::integer as direct_tax_asset,
                    sum(
                        case
                            when upper(coalesce(de.asset, '')) = ? and coalesce(de.quantity, 0) < 0 then 1
                            else 0
                        end
                    )::integer as disposal_asset,
                    sum(
                        case
                            when upper(coalesce(de.quote_asset, '')) = ? and coalesce(de.quantity, 0) > 0 then 1
                            else 0
                        end
                    )::integer as disposal_quote_asset,
                    sum(case when upper(coalesce(ae.asset, '')) = ? then 1 else 0 end)::integer as acquisition_asset,
                    sum(case when upper(coalesce(ae.quote_asset, '')) = ? then 1 else 0 end)::integer as acquisition_quote_asset
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                left join canonical_events de on de.event_id = l.source_event_id
                left join canonical_events ae on ae.event_id = lot.source_event_id
                where date_part('year', l.disposed_at)::integer = ?
                  and (
                      upper(l.asset) = ?
                      or upper(coalesce(de.asset, '')) = ?
                      or upper(coalesce(de.quote_asset, '')) = ?
                      or upper(coalesce(ae.asset, '')) = ?
                      or upper(coalesce(ae.quote_asset, '')) = ?
                  )
                """,
                [asset, asset, asset, asset, asset, year, asset, asset, asset, asset, asset],
            ).fetchone()
        return {
            "direct_tax_asset": int((row[0] if row else 0) or 0),
            "disposal_asset": int((row[1] if row else 0) or 0),
            "disposal_quote_asset": int((row[2] if row else 0) or 0),
            "acquisition_asset": int((row[3] if row else 0) or 0),
            "acquisition_quote_asset": int((row[4] if row else 0) or 0),
        }

    @staticmethod
    def _asset_fifo_correction_decision(
        row: TaxYearAssetFifoPlausibilityRow,
        *,
        role_counts: dict[str, int],
        related_missing_raw_evidence_count: int,
        min_abs_gain_eur: Decimal,
    ) -> tuple[
        Literal[
            "no_action",
            "keep_tax_sum_review_presentation",
            "verify_quote_leg_attribution",
            "verify_normalizer_or_missing_asset_side",
        ],
        Literal[
            "none_expected",
            "already_in_existing_tax_lines",
            "possible_recalculation_after_review",
        ],
        str,
        str,
    ]:
        if related_missing_raw_evidence_count:
            return (
                "verify_normalizer_or_missing_asset_side",
                "possible_recalculation_after_review",
                (
                    "Rohbelege fehlen in mindestens einer verknuepften Tax-Line. "
                    "Eine neue steuerliche Bewertung ist erst nach Belegklaerung ausgeschlossen."
                ),
                "Rohimport-Zeilen und Normalizer-Zuordnung fuer dieses Asset pruefen.",
            )
        if abs(row.total_related_gain_loss_eur) < min_abs_gain_eur:
            return (
                "no_action",
                "none_expected",
                "Kein materielles Korrektursignal im gewaehlten Schwellwert.",
                "Keine Aktion noetig.",
            )
        current_disposal_roles = role_counts.get("direct_tax_asset", 0) + role_counts.get("disposal_asset", 0) + role_counts.get("disposal_quote_asset", 0)
        cost_basis_roles = role_counts.get("acquisition_asset", 0) + role_counts.get("acquisition_quote_asset", 0)
        if (
            "asset_only_seen_in_related_quote_or_counter_events" in row.reasons
            and current_disposal_roles == 0
            and cost_basis_roles > 0
        ):
            return (
                "keep_tax_sum_review_presentation",
                "already_in_existing_tax_lines",
                (
                    "Das Asset erscheint im ausgewaehlten Jahr nur als historische "
                    "Kostenbasis-/Quote-Herkunft eines anderen Lots. Das ist kein "
                    "neuer steuerpflichtiger Vorgang dieses Jahres."
                ),
                "Als Herkunftsspur im Belegpaket zeigen; direkte Steuerjahressumme nicht aendern.",
            )
        if "asset_only_seen_in_related_quote_or_counter_events" in row.reasons:
            return (
                "verify_normalizer_or_missing_asset_side",
                "possible_recalculation_after_review",
                (
                    "Das Asset hat keine direkten Tax-Lines, wirkt aber materiell in "
                    "Gegenbein-Zeilen. Das kann korrekt sein, muss aber gegen den "
                    "Originalimport geprueft werden."
                ),
                "Pruefen, ob das Asset im Import nur als Quote-Bein vorkam oder eine direkte Asset-Seite fehlt.",
            )
        if "direct_asset_near_zero_but_quote_effect_material" in row.reasons:
            return (
                "verify_quote_leg_attribution",
                "already_in_existing_tax_lines",
                (
                    "Die steuerliche Wirkung ist in bestehenden Gegenwaehrungs-Tax-Lines enthalten, "
                    "aber fuer Menschen unter dem Asset-Namen nicht eindeutig sichtbar."
                ),
                "Quote-/Gegenbein-Zeilen mit dem Asset-Drilldown belegen und im Jahresbericht erklaeren.",
            )
        if abs(row.direct_gain_loss_eur) >= min_abs_gain_eur or abs(row.linked_gain_loss_eur) >= min_abs_gain_eur:
            return (
                "keep_tax_sum_review_presentation",
                "already_in_existing_tax_lines",
                (
                    "Direkte und/oder verknuepfte Werte sind materiell, aber bereits in vorhandenen "
                    "Tax-Lines enthalten. Primaer ist die Darstellung und Belegkette zu pruefen."
                ),
                "Asset-Drilldown als Beleg nutzen und bei Bedarf im Filing-/Evidence-Report hervorheben.",
            )
        return (
            "no_action",
            "none_expected",
            "Kein materielles Korrektursignal im gewaehlten Schwellwert.",
            "Keine Aktion noetig.",
        )

    def _fees_by_year(self) -> dict[int, Decimal]:
        if self._fees_cache is not None:
            return self._fees_cache
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    date_part('year', event_time)::integer as year,
                    sum(
                        case
                            when event_type = 'fee'
                             and upper(coalesce(quote_asset, '')) = 'EUR'
                            then abs(coalesce(quote_quantity, 0))
                            else 0
                        end
                    ) as fees_eur
                from canonical_events
                group by year
                """
            ).fetchall()
        self._fees_cache = {int(row[0]): row[1] or Decimal("0") for row in rows}
        return self._fees_cache

    def _derivatives_by_year(self) -> dict[int, dict[str, Decimal | int]]:
        if self._derivatives_cache is not None:
            return self._derivatives_cache
        totals: dict[int, dict[str, Decimal | int]] = defaultdict(
            lambda: {"pnl": Decimal("0"), "lines": 0, "missing_price_count": 0}
        )
        for line in self._derivative_lines():
            item = totals[line.event_time.year]
            item["pnl"] = item["pnl"] + line.value_eur  # type: ignore[operator]
            item["lines"] = int(item["lines"]) + 1
            if line.price_source is None:
                item["missing_price_count"] = int(item["missing_price_count"]) + 1
        self._derivatives_cache = totals
        return totals

    def _tax_lines(self) -> list[object]:
        if self._tax_lines_cache is None:
            self._tax_lines_cache = TaxService(self.store).list_tax_lines()
        return self._tax_lines_cache

    def _unmatched_disposals(self) -> list[object]:
        if self._unmatched_cache is None:
            self._unmatched_cache = TaxService(self.store).list_unmatched_disposals()
        return self._unmatched_cache

    def _missing_prices(self) -> list[object]:
        if self._missing_prices_cache is None:
            self._missing_prices_cache = PriceCoverageService(self.store).report().missing
        return self._missing_prices_cache

    def _derivative_lines(self) -> list[object]:
        if self._derivative_lines_cache is None:
            self._derivative_lines_cache = DerivativesManager(self.store).list_lines()
        return self._derivative_lines_cache

    def _closed_tax_years(self) -> set[int]:
        for setting in self.store.list_admin_settings():
            if setting.key != "runtime.review.closed_tax_years":
                continue
            try:
                parsed = json.loads(setting.value_json)
            except json.JSONDecodeError:
                return set()
            if not isinstance(parsed, list):
                return set()
            return {int(item) for item in parsed if isinstance(item, int)}
        return set()
