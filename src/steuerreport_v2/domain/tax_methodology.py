from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from steuerreport_v2.contracts.tax_methodology import (
    TaxBmfActionItem,
    TaxBmfActionPlan,
    TaxBmfClosureBacklogItem,
    TaxBmfClosureBacklogReport,
    TaxBmfClosureBacklogSnapshot,
    TaxBmfClosureBacklogYear,
    TaxBmfFilingReadinessReport,
    TaxBmfFilingReadinessSnapshot,
    TaxBmfFilingReadinessYear,
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
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService


class TaxMethodologyService:
    METHOD_VERSION = "bmf_readiness_v2"
    FIFO_SCOPE = "global_asset_with_wallet_fifo_evidence_overlay_v1"
    ASSET_FIFO_CORRECTION_MIN_ABS_EUR = Decimal("100")
    EXCHANGE_SEQUENCING_GAP_MAX_QUANTITY = Decimal("1")
    EXCHANGE_SEQUENCING_GAP_WINDOW = timedelta(minutes=5)
    EXCHANGE_SEQUENCING_POOLS = {"binance", "bitget", "pionex"}
    DEFAULT_BMF_FILING_READINESS_DIR = Path("/workspace/steuerreport-v2-plan/var/bmf_filing_readiness")
    DEFAULT_BMF_CLOSURE_BACKLOG_DIR = Path("/workspace/steuerreport-v2-plan/var/bmf_closure_backlog")

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

    def bmf_action_plan(self, year: int | None = None) -> TaxBmfActionPlan:
        generated_at = self._now()
        available_years = [year] if year is not None else self._available_years()
        reports = [self.report(year) for year in available_years]
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
                "Deltas. Die Liste schreibt keine Steuerdaten."
            ),
        )

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
            status="available",
            note="Read-only Snapshot aus var/bmf_filing_readiness; API berechnet dabei keine Methodology neu.",
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
        report = self.report(year)
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
        if report.status == "empty":
            filing_status = "empty"
            label = "Keine Aktivitaet"
            next_action = "Kein Eintrag aus V2-Werten; Jahresbeleg optional archivieren."
        elif report.bmf_ready:
            filing_status = "bmf_ready"
            label = "BMF-ready"
            next_action = "Filing Summary und Belegpaket fuer die Steuererklaerung verwenden."
        elif can_file_with_conservative_appendix:
            filing_status = "conservative_appendix"
            label = "Konservativ belegbar"
            next_action = (
                "BMF-Closure-Appendix beilegen und keine offene Herkunft als "
                "steuerneutralen Eigenwallet-Transfer behaupten."
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
        report = self.report(year)
        appendix = self.tax_years.bmf_closure_appendix(year)
        items: list[TaxBmfClosureBacklogItem] = []
        for appendix_item in appendix.items:
            if appendix_item.closure_status in {
                "documented_non_live_opening_balance",
                "documented_fiat_purchase",
                "documented_legacy_hnt_cex_deposit",
                "documented_legacy_hnt_cex_deposit_mirror",
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

    def report(self, year: int) -> TaxMethodologyReport:
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
        asset_fifo_review = self.tax_years.asset_fifo_correction_review(
            year,
            limit=200,
            min_abs_gain_eur=self.ASSET_FIFO_CORRECTION_MIN_ABS_EUR,
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
            wallet_fifo_documented_fiat_purchase_count=wallet_fifo_documented_fiat_purchase_count,
            wallet_fifo_documented_legacy_cex_deposit_count=wallet_fifo_documented_legacy_cex_deposit_count,
            wallet_fifo_documented_legacy_cex_deposit_mirror_count=(
                wallet_fifo_documented_legacy_cex_deposit_mirror_count
            ),
            asset_fifo_possible_recalculation_count=asset_fifo_review.possible_recalculation_assets_count,
            asset_fifo_attribution_review_count=asset_fifo_review.attribution_review_assets_count,
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
        wallet_fifo_documented_fiat_purchase_count: int,
        wallet_fifo_documented_legacy_cex_deposit_count: int,
        wallet_fifo_documented_legacy_cex_deposit_mirror_count: int,
        asset_fifo_possible_recalculation_count: int,
        asset_fifo_attribution_review_count: int,
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
            - wallet_fifo_documented_fiat_purchase_count
            - wallet_fifo_documented_legacy_cex_deposit_count
            - wallet_fifo_documented_legacy_cex_deposit_mirror_count,
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
            "wallet_fifo_legacy_cex_deposit_documented": "Wallet-FIFO Legacy-HNT-CEX-Deposit dokumentiert",
            "wallet_fifo_legacy_cex_deposit_mirror_documented": (
                "Wallet-FIFO Legacy-HNT-CEX-Deposit-Spiegel dokumentiert"
            ),
            "asset_fifo_possible_recalculation": "Asset-FIFO moegliche Neuberechnung",
            "asset_fifo_quote_attribution_documented": "Quote-/Attribution dokumentiert",
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
