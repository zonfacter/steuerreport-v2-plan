from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
import io
from zoneinfo import ZoneInfo
import zipfile

from steuerreport_v2.contracts.divorce import (
    DivorceEqualizationAccountAssetRow,
    DivorceEqualizationAccountRow,
    DivorceEqualizationAssetRow,
    DivorceEqualizationBmfTaxBoundary,
    DivorceEqualizationBucket,
    DivorceEqualizationCashFlow,
    DivorceEqualizationLiveReconciliationRow,
    DivorceEqualizationSummary,
    DivorceStichtagContext,
    DivorceValuationGate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce_capital_flows import DivorceCapitalFlowService
from steuerreport_v2.domain.divorce_inheritance import (
    DivorceInheritanceOriginService,
)
from steuerreport_v2.domain.divorce_service_routes import (
    DivorceServiceRouteEvidenceService,
)
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.stichtag_token_valuation import (
    StichtagTokenValuationService,
)
from steuerreport_v2.domain.tax import TaxService


class DivorceEqualizationService:
    VALUATION_TIMEZONE = "Europe/Berlin"
    DEFAULT_SEPARATION_DATE = date(2025, 6, 13)
    DEFAULT_END_ASSET_DATE = date(2026, 7, 24)
    DEFAULT_CUTOFF_AT = datetime(2025, 6, 13, 21, 59, 59, 999999, tzinfo=timezone.utc)
    DEFAULT_VALUATION_AT = datetime(
        2026, 7, 24, 21, 59, 59, 999999, tzinfo=timezone.utc
    )
    BGB_1384_URL = "https://www.gesetze-im-internet.de/bgb/__1384.html"
    BMF_REFERENCE_URL = (
        "https://www.bundesfinanzministerium.de/Content/DE/Downloads/"
        "BMF_Schreiben/Steuerarten/Einkommensteuer/"
        "2025-03-06-einzelfragen-kryptowerte-bmf-schreiben.pdf"
    )
    DUST_VALUE_EUR = Decimal("1")

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.token_valuation_service = StichtagTokenValuationService(store)

    def summary(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> DivorceEqualizationSummary:
        cutoff_utc = self._resolve_stichtag(
            local_date=separation_date,
            explicit_at=cutoff_at,
            default_date=self.DEFAULT_SEPARATION_DATE,
            label="Trennungsstichtag",
        )
        valuation_utc = self._resolve_stichtag(
            local_date=end_asset_date,
            explicit_at=valuation_at,
            default_date=self.DEFAULT_END_ASSET_DATE,
            label="Endvermoegensstichtag",
        )
        cutoff = self._naive(cutoff_utc)
        valuation = self._naive(valuation_utc)
        separation_day = self._local_date(cutoff_utc)
        end_asset_day = self._local_date(valuation_utc)
        evidence_reference = str(court_evidence_reference or "").strip() or None
        if valuation <= cutoff:
            raise ValueError(
                "Der Endvermoegensstichtag muss nach dem Trennungsstichtag liegen."
            )
        if materiality_threshold_eur < 0:
            raise ValueError("Die Materialitaetsschwelle darf nicht negativ sein.")
        latest_prices = self._prices_as_of(valuation)
        latest_event_at, latest_price_at = self._latest_timestamps()
        portfolio_service = PortfolioService(self.store)
        cutoff_portfolio = portfolio_service.as_of_snapshot(cutoff)
        valuation_portfolio = portfolio_service.as_of_snapshot(valuation)
        inheritance_service = DivorceInheritanceOriginService(self.store)
        inheritance_origin_gate = inheritance_service.report(
            separation_date=separation_day,
            end_asset_date=end_asset_day,
            valuation_portfolio=valuation_portfolio,
        )
        inheritance_binance_investments = next(
            (
                item.identified_investment_eur
                for item in inheritance_origin_gate.provider_summaries
                if item.provider == "binance"
            ),
            Decimal("0"),
        )
        canonical_binance_deposits = self._decimal_scalar(
            """
            select coalesce(sum(quantity), 0)
            from canonical_events
            where event_time > ? and event_time <= ?
              and source = 'binance'
              and event_type = 'transfer'
              and asset = 'EUR'
              and account = 'binance'
              and quantity > 0
            """,
            [cutoff, valuation],
        )
        fiat_deposits = (
            canonical_binance_deposits
            if cutoff_at is not None or valuation_at is not None
            else inheritance_binance_investments
        )
        confirmed_onramp, provisional_onramp = self._moonpay_onramp_values(
            cutoff,
            valuation,
        )
        external_invest_total = fiat_deposits + confirmed_onramp + provisional_onramp
        capital_flow_gate = DivorceCapitalFlowService(self.store).report(
            cutoff_at=cutoff_utc,
            valuation_at=valuation_utc,
            opening_value_eur=cutoff_portfolio.total_value_eur,
            closing_value_eur=valuation_portfolio.total_value_eur,
            binance_contributions_eur=fiat_deposits,
            confirmed_onramp_contributions_eur=confirmed_onramp,
            provisional_onramp_contributions_eur=provisional_onramp,
            materiality_threshold_eur=materiality_threshold_eur,
        )
        accounts = self._account_rows(
            cutoff_portfolio,
            valuation_portfolio,
            valuation_at=valuation,
            external_invest_by_account={
                "Binance": fiat_deposits,
                PortfolioService.KNOWN_JUP_WALLET: confirmed_onramp
                + provisional_onramp,
            },
        )
        live_reconciliation = self._live_reconciliation_rows(portfolio_service)
        valuation_review_value = sum(
            (item.valuation_review_value_eur for item in accounts), Decimal("0")
        )
        valuation_dust_value = self._valuation_flag_total(accounts, "dust_under_1_eur")
        valuation_without_review = (
            valuation_portfolio.total_value_eur - valuation_review_value
        )
        cutoff_gate = self._valuation_gate(
            cutoff_portfolio.positions,
            cutoff,
            materiality_threshold_eur,
        )
        valuation_gate = self._valuation_gate(
            valuation_portfolio.positions,
            valuation,
            materiality_threshold_eur,
        )
        marital = self._bucket(
            bucket_id="marital_pre_cutoff",
            label="Technische FIFO-Kontrollsicht: Alt-Lots vor Stichtag",
            description=(
                "Keine Vermoegenssumme. Diese technische Sicht zeigt FIFO-Lots mit "
                f"Anschaffung vor dem {separation_day.strftime('%d.%m.%Y')}. Sie kann Handelsdurchlauf/Kostenbasis "
                "enthalten und darf nicht als tatsaechlich besessenes Anlagevermoegen "
                "interpretiert werden."
            ),
            open_lot_predicate=lambda row: (
                self._naive(row["acquired_at"]) <= cutoff
                and self._naive(row["acquired_at"]) <= valuation
            ),
            sold_line_predicate=lambda line: (
                self._naive(line.acquired_at) <= cutoff
                and cutoff < self._naive(line.disposed_at) <= valuation
            ),
            latest_prices=latest_prices,
        )
        post_cutoff_direct_eur = self._bucket(
            bucket_id="post_cutoff_direct_eur_invest",
            label="Nach Stichtag direkt mit EUR gekauft",
            description=(
                f"Offene Lots ab dem {separation_day.strftime('%d.%m.%Y')}, deren Ursprungsevent direkt gegen "
                "EUR gekauft wurde. Das ist die engere Spur fuer Erbgeld-/Fiat-Invest."
            ),
            open_lot_predicate=lambda row: (
                cutoff < self._naive(row["acquired_at"]) <= valuation
                and str(row.get("quote_asset") or "").upper() == "EUR"
                and Decimal(str(row.get("event_quantity") or 0)) > 0
            ),
            sold_line_predicate=lambda _line: False,
            latest_prices=latest_prices,
        )
        post_cutoff_all = self._bucket(
            bucket_id="post_cutoff_all_lots",
            label="Alle nach Stichtag entstandenen Lots",
            description=(
                f"Alle offenen Lots ab dem {separation_day.strftime('%d.%m.%Y')} inklusive Krypto-Swaps, "
                "Rewards/Mining und Transfers. Diese Sicht ist weiter als die reine EUR-Invest-Spur."
            ),
            open_lot_predicate=lambda row: (
                cutoff < self._naive(row["acquired_at"]) <= valuation
            ),
            sold_line_predicate=lambda line: (
                cutoff < self._naive(line.acquired_at) <= valuation
                and self._naive(line.disposed_at) <= valuation
            ),
            latest_prices=latest_prices,
        )
        direct_eur_buys = self._decimal_scalar(
            """
            select coalesce(sum(abs(quote_quantity)), 0)
            from canonical_events
            where event_time > ? and event_time <= ?
              and quantity > 0
              and quote_asset = 'EUR'
            """,
            [cutoff, valuation],
        )
        eur_spent_without_quote = self._decimal_scalar(
            """
            select coalesce(sum(abs(quantity)), 0)
            from canonical_events
            where event_time > ? and event_time <= ?
              and event_type = 'trade'
              and asset = 'EUR'
              and quantity < 0
            """,
            [cutoff, valuation],
        )
        caveats = [
            (
                "Keine Rechtsberatung: Die Seite bereitet Belegzahlen fuer Zugewinnausgleich vor. "
                "Die juristische Einordnung muss durch Familienrechtsberatung erfolgen."
            ),
            (
                "Erbe/Schenkung wird nach § 1374 Abs. 2 BGB typischerweise dem Anfangsvermoegen "
                "zugerechnet; ausgleichsrelevant ist regelmaessig die Wertveraenderung, nicht der "
                "geerbte Betrag selbst."
            ),
            (
                "Die Hauptwerte dieser Seite sind Stichtags-Marktwerte aus dem Portfolio-Ledger. "
                "FIFO-Kostenbasiswerte sind nur technische Kontroll-/Steuersichten und kein Nachweis, "
                "dass dieser Betrag jemals als Vermoegen vorhanden war."
            ),
            (
                f"Der {end_asset_day.strftime('%d.%m.%Y')} wird als vom Nutzer benannter "
                "Endvermoegensstichtag verwendet. Fuer einen gerichtsfesten Nachweis muss belegt "
                "werden, dass dies der Zeitpunkt der Rechtshaengigkeit des Scheidungsantrags ist."
            ),
            (
                "Wenn der exakte Endvermoegensstichtag laut Gerichts-/Zustellungsbeleg abweicht, muessen die Preise fuer "
                "diesen Stichtag erneut importiert und die Auswertung neu erzeugt werden."
            ),
            (
                "MoonPay-/Apple-Pay-Zufluesse werden mit dem tatsaechlichen Zahlbetrag aus der "
                "SHA-256-gebundenen Trade History angesetzt, soweit der On-chain-Match streng "
                "freigegeben ist. Nur nicht vollstaendig gematchte Zeilen bleiben zum historischen "
                "Marktwert vorlaeufig; der Erbgeld-Herkunftsnachweis ist davon getrennt."
            ),
            (
                "Die flussbereinigte Wertveraenderung ist vorlaeufig, solange das "
                "Vermoegensfluss-Gate Kapitalherkunft oder materielle Abfluss-/Service-Ereignisse "
                "als offen ausweist. Nur bestaetigte externe Auszahlungen werden zurueckgerechnet."
            ),
            (
                "Trade-Republic- und Coinbase-Abfluesse werden im Erbgeld-Gate als externe "
                "Vermoegensquellen ausgewiesen. Sie werden nicht in den Krypto-Portfoliowert "
                "eingerechnet, bevor offizielle Depot-/Kontobelege fuer den Endvermoegensstichtag "
                "importiert und bewertet sind."
            ),
        ]
        return DivorceEqualizationSummary(
            generated_at=datetime.now(timezone.utc),
            stichtage=DivorceStichtagContext(
                separation_date=separation_day,
                separation_at_utc=cutoff_utc,
                end_asset_date=end_asset_day,
                end_asset_at_utc=valuation_utc,
                timezone=self.VALUATION_TIMEZONE,
                court_evidence_status=(
                    "documented" if evidence_reference else "pending_document"
                ),
                court_evidence_reference=evidence_reference,
                court_evidence_note=(
                    "Gerichts-/Zustellungsbeleg wurde referenziert."
                    if evidence_reference
                    else "Gerichts- oder Zustellungsbeleg fuer die Rechtshaengigkeit des "
                    "Scheidungsantrags dem finalen Dossier beilegen."
                ),
            ),
            cutoff_at=cutoff_utc,
            valuation_at=valuation_utc,
            latest_event_at=latest_event_at.replace(tzinfo=timezone.utc)
            if latest_event_at
            else None,
            latest_price_at=latest_price_at.replace(tzinfo=timezone.utc)
            if latest_price_at
            else None,
            cutoff_portfolio_value_eur=cutoff_portfolio.total_value_eur,
            valuation_portfolio_value_eur=valuation_portfolio.total_value_eur,
            valuation_review_value_eur=valuation_review_value,
            valuation_dust_value_eur=valuation_dust_value,
            valuation_value_without_review_assets_eur=valuation_without_review,
            gross_portfolio_change_eur=valuation_portfolio.total_value_eur
            - cutoff_portfolio.total_value_eur,
            gross_portfolio_change_without_review_assets_eur=valuation_without_review
            - cutoff_portfolio.total_value_eur,
            net_external_invest_since_cutoff_eur=external_invest_total,
            confirmed_external_invest_since_cutoff_eur=fiat_deposits + confirmed_onramp,
            confirmed_onramp_invest_since_cutoff_eur=confirmed_onramp,
            provisional_onramp_invest_since_cutoff_eur=provisional_onramp,
            adjusted_gain_loss_excluding_new_invest_eur=capital_flow_gate.flow_adjusted_change_eur,
            adjusted_gain_loss_without_review_assets_eur=(
                valuation_without_review
                + capital_flow_gate.confirmed_external_distributions_eur
                - cutoff_portfolio.total_value_eur
                - external_invest_total
            ),
            cutoff_missing_price_assets=cutoff_portfolio.missing_price_assets,
            valuation_missing_price_assets=valuation_portfolio.missing_price_assets,
            fiat_deposits_since_cutoff_eur=fiat_deposits,
            direct_eur_buys_since_cutoff_eur=direct_eur_buys,
            eur_asset_spent_without_quote_since_cutoff_eur=eur_spent_without_quote,
            inheritance_origin_gate=inheritance_origin_gate,
            capital_flow_gate=capital_flow_gate,
            cutoff_price_gate=cutoff_gate,
            valuation_price_gate=valuation_gate,
            marital_pre_cutoff=marital,
            post_cutoff_direct_eur_invest=post_cutoff_direct_eur,
            post_cutoff_all_lots=post_cutoff_all,
            accounts=accounts,
            live_reconciliation=live_reconciliation,
            bmf_tax_boundary=self._bmf_tax_boundary(),
            cash_flows=[
                DivorceEqualizationCashFlow(
                    label="Nachweisbare Binance-Fiat-Investitionen ab Stichtag",
                    amount_eur=fiat_deposits,
                    note=(
                        "Vereinigte Plattform- und Bankbelege inklusive direkter Fiat-Kaeufe; "
                        "Bank-/Plattformmatches werden nicht doppelt gezaehlt."
                    ),
                ),
                DivorceEqualizationCashFlow(
                    label="Direkte EUR-Kaeufe ab Stichtag",
                    amount_eur=direct_eur_buys,
                    note="Positive Krypto-Kaufereignisse mit quote_asset=EUR.",
                ),
                DivorceEqualizationCashFlow(
                    label="MoonPay-/Apple-Pay-Onramp durch Trade History belegt",
                    amount_eur=confirmed_onramp,
                    note="Tatsaechlicher EUR-Zahlbetrag inklusive Gebuehren; exakt mit dem On-chain Eingang gematcht.",
                ),
                DivorceEqualizationCashFlow(
                    label="MoonPay-/Apple-Pay-Onramp vorlaeufig",
                    amount_eur=provisional_onramp,
                    note="Nur nicht streng gematchte On-chain Eingaenge zum historischen Marktwert.",
                ),
                DivorceEqualizationCashFlow(
                    label="EUR-Trades ohne Quote-Ziel",
                    amount_eur=eur_spent_without_quote,
                    note="EUR-Abgaenge als asset=EUR ohne direkte Quote-Zuordnung; fuer Belegzwecke pruefen.",
                ),
            ],
            caveats=caveats,
            legal_note=(
                "BGB-Bezug: § 1373 BGB definiert Zugewinn als Differenz von End- und "
                "Anfangsvermoegen; § 1374 Abs. 2 BGB rechnet geerbtes oder geschenktes "
                "Vermoegen dem Anfangsvermoegen zu; § 1376 BGB regelt die Bewertung. "
                "Bei Scheidung ersetzt nach § 1384 BGB der Zeitpunkt der Rechtshaengigkeit "
                "des Scheidungsantrags den Zeitpunkt der Beendigung des Gueterstands."
            ),
            methodology=(
                "Read-only Auswertung fuer zwei deutsche Kalendertage. Der lokale Tagesabschluss "
                "in Europe/Berlin wird inklusive Sommer-/Winterzeit nach UTC normalisiert. Die "
                "Werte stammen aus Portfolio-Stichtagsbewertung, canonical_events, "
                "tax_lots, tax_lines und price_ledger. Die Hauptvermoegenswerte sind "
                "Portfolio-Marktwerte am Trennungs- und Endvermoegensstichtag. FIFO-Kostenbasis "
                "wird nur als technische Kontrollsicht fuer Lots ausgewiesen. Die "
                "flussbereinigte Veraenderung wird um belegte Kapitalzufluesse und ausschliesslich "
                "bestaetigte externe Auszahlungen korrigiert; interne Transfers bleiben neutral."
            ),
        )

    def _live_reconciliation_rows(
        self, portfolio_service: PortfolioService
    ) -> list[DivorceEqualizationLiveReconciliationRow]:
        relevant_sources = {
            "Binance",
            "Bitget",
            "Pionex",
            "Jup Wallet GmHY...3yu",
            "Solana Wallet 6K9n7y...qEwP",
        }
        report = portfolio_service.reconciliation_report()
        rows = [
            DivorceEqualizationLiveReconciliationRow(
                source_group=row.source_group,
                source_type=row.source_type,
                asset=row.asset,
                ledger_quantity=row.ledger_quantity,
                ledger_value_eur=row.ledger_value_eur,
                external_quantity=row.external_quantity,
                external_value_eur=row.external_value_eur,
                delta_quantity=row.delta_quantity,
                delta_value_eur=row.delta_value_eur,
                status=row.status,
                severity=row.severity,
                evidence=row.evidence,
                next_action=row.next_action,
            )
            for row in report.rows
            if row.source_group in relevant_sources
            or row.severity in {"blocker", "warning"}
        ]
        rows.sort(
            key=lambda row: (
                {"blocker": 0, "warning": 1, "info": 2}.get(row.severity, 3),
                row.source_group,
                row.asset or "",
            )
        )
        return rows

    def _bmf_tax_boundary(self) -> DivorceEqualizationBmfTaxBoundary:
        return DivorceEqualizationBmfTaxBoundary(
            bmf_reference="BMF-Schreiben vom 06.03.2025 zur ertragsteuerrechtlichen Behandlung bestimmter Kryptowerte",
            bmf_reference_url=self.BMF_REFERENCE_URL,
            tax_methodology_summary_endpoint="/api/v1/tax-methodology/summary",
            tax_year_methodology_endpoint_template="/api/v1/tax-years/{year}/methodology",
            tax_year_evidence_package_endpoint_template="/api/v1/export/tax-years/{year}/evidence-package.zip",
            boundary_notes=[
                (
                    "Diese Zugewinn-Auswertung ist eine familienrechtliche Portfolio- und "
                    "Belegsicht; sie ersetzt keine Steuerjahresberechnung."
                ),
                (
                    "BMF-relevante Steuerlogik bleibt in den Steuerjahr-Endpunkten: "
                    "Tax-Lines, einzutragende Rewards/Mining/Staking, Derivate, externe Zufluesse, "
                    "FIFO-Methodik und Belegpakete."
                ),
                (
                    "Eigene Transfers und Wallet-Wechsel duerfen fuer die Steuerlogik "
                    "keine neuen Gewinne erzeugen; die Herkunft muss ueber FIFO-/Provenance-"
                    "Artefakte nachvollziehbar bleiben."
                ),
                (
                    "Live-Bestaende sind Kontroll- und Bewertungsquelle. Fuer BMF-Readiness "
                    "muss die steuerliche Historie ueber importierte Transaktionen, Preise "
                    "und Review-Entscheidungen belegbar sein."
                ),
            ],
        )

    def valuation_tokens_csv(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> str:
        report = self.summary(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            court_evidence_reference=court_evidence_reference,
            cutoff_at=cutoff_at,
            valuation_at=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
        )
        return self._valuation_tokens_csv_for_report(report)

    @staticmethod
    def _valuation_tokens_csv_for_report(report: DivorceEqualizationSummary) -> str:
        output = io.StringIO()
        fieldnames = [
            "snapshot",
            "snapshot_at",
            "account",
            "source_accounts",
            "classification",
            "valuation_basis",
            "asset",
            "quantity",
            "value_eur",
            "valuation_flag",
            "price_source",
            "priced_at",
            "price_age_days",
            "price_status",
            "note",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for account in report.accounts:
            snapshots = (
                ("cutoff", report.cutoff_at, account.cutoff_assets),
                ("valuation", report.valuation_at, account.valuation_assets),
            )
            for snapshot, snapshot_at, assets in snapshots:
                for asset in assets:
                    writer.writerow(
                        {
                            "snapshot": snapshot,
                            "snapshot_at": snapshot_at.isoformat()
                            if snapshot_at
                            else "",
                            "account": account.account,
                            "source_accounts": "|".join(account.source_accounts),
                            "classification": account.classification,
                            "valuation_basis": account.valuation_basis,
                            "asset": asset.asset,
                            "quantity": str(asset.quantity),
                            "value_eur": str(asset.value_eur),
                            "valuation_flag": asset.valuation_flag,
                            "price_source": asset.price_source or "",
                            "priced_at": asset.priced_at.isoformat()
                            if asset.priced_at
                            else "",
                            "price_age_days": ""
                            if asset.price_age_days is None
                            else asset.price_age_days,
                            "price_status": asset.price_status,
                            "note": asset.note or "",
                        }
                    )
        return output.getvalue()

    def accounts_csv(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> str:
        report = self.summary(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            court_evidence_reference=court_evidence_reference,
            cutoff_at=cutoff_at,
            valuation_at=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
        )
        return self._accounts_csv_for_report(report)

    @staticmethod
    def _accounts_csv_for_report(report: DivorceEqualizationSummary) -> str:
        output = io.StringIO()
        fieldnames = [
            "account",
            "source_accounts",
            "classification",
            "valuation_basis",
            "cutoff_value_eur",
            "valuation_value_eur",
            "valuation_value_without_review_assets_eur",
            "valuation_review_value_eur",
            "gross_change_eur",
            "external_invest_since_cutoff_eur",
            "adjusted_gain_loss_eur",
            "position_count_cutoff",
            "position_count_valuation",
            "assets_cutoff",
            "assets_valuation",
            "asset_labels_cutoff",
            "asset_labels_valuation",
            "note",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for account in report.accounts:
            writer.writerow(
                {
                    "account": account.account,
                    "source_accounts": "|".join(account.source_accounts),
                    "classification": account.classification,
                    "valuation_basis": account.valuation_basis,
                    "cutoff_value_eur": str(account.cutoff_value_eur),
                    "valuation_value_eur": str(account.valuation_value_eur),
                    "valuation_value_without_review_assets_eur": str(
                        account.valuation_value_without_review_assets_eur
                    ),
                    "valuation_review_value_eur": str(
                        account.valuation_review_value_eur
                    ),
                    "gross_change_eur": str(account.gross_change_eur),
                    "external_invest_since_cutoff_eur": str(
                        account.external_invest_since_cutoff_eur
                    ),
                    "adjusted_gain_loss_eur": str(account.adjusted_gain_loss_eur),
                    "position_count_cutoff": account.position_count_cutoff,
                    "position_count_valuation": account.position_count_valuation,
                    "assets_cutoff": account.assets_cutoff,
                    "assets_valuation": account.assets_valuation,
                    "asset_labels_cutoff": "|".join(account.asset_labels_cutoff),
                    "asset_labels_valuation": "|".join(account.asset_labels_valuation),
                    "note": account.note or "",
                }
            )
        return output.getvalue()

    def live_reconciliation_csv(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> str:
        report = self.summary(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            court_evidence_reference=court_evidence_reference,
            cutoff_at=cutoff_at,
            valuation_at=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
        )
        return self._live_reconciliation_csv_for_report(report)

    def capital_flows_csv(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> str:
        report = self.summary(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            court_evidence_reference=court_evidence_reference,
            cutoff_at=cutoff_at,
            valuation_at=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
        )
        return self._capital_flows_csv_for_report(report)

    @staticmethod
    def _capital_flows_csv_for_report(report: DivorceEqualizationSummary) -> str:
        output = io.StringIO()
        fieldnames = [
            "row_type",
            "flow_id",
            "event_id",
            "event_time",
            "source",
            "account",
            "asset",
            "quantity",
            "value_eur",
            "classification",
            "evidence_status",
            "material",
            "affects_flow_adjusted_change",
            "capital_origin",
            "capital_origin_evidence_status",
            "tx_id",
            "raw_object_id",
            "evidence_ref",
            "note",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in report.capital_flow_gate.contributions:
            writer.writerow(
                {
                    "row_type": "contribution",
                    "flow_id": row.flow_id,
                    "value_eur": str(row.amount_eur),
                    "classification": row.transaction_evidence_status,
                    "evidence_status": row.transaction_evidence_status,
                    "capital_origin": row.capital_origin,
                    "capital_origin_evidence_status": row.capital_origin_evidence_status,
                    "evidence_ref": row.evidence_ref or "",
                    "note": row.note,
                }
            )
        for row in report.capital_flow_gate.outflows:
            writer.writerow(
                {
                    "row_type": "outflow",
                    "event_id": row.event_id,
                    "event_time": row.event_time.isoformat(),
                    "source": row.source,
                    "account": row.account or "",
                    "asset": row.asset,
                    "quantity": str(row.quantity),
                    "value_eur": "" if row.value_eur is None else str(row.value_eur),
                    "classification": row.classification,
                    "evidence_status": row.evidence_status,
                    "material": str(row.material).lower(),
                    "affects_flow_adjusted_change": str(
                        row.affects_flow_adjusted_change
                    ).lower(),
                    "tx_id": row.tx_id or "",
                    "raw_object_id": row.raw_object_id or "",
                    "evidence_ref": row.evidence_ref or "",
                    "note": row.note,
                }
            )
        return output.getvalue()

    @staticmethod
    def _live_reconciliation_csv_for_report(report: DivorceEqualizationSummary) -> str:
        output = io.StringIO()
        fieldnames = [
            "source_group",
            "source_type",
            "asset",
            "ledger_quantity",
            "ledger_value_eur",
            "external_quantity",
            "external_value_eur",
            "delta_quantity",
            "delta_value_eur",
            "status",
            "severity",
            "evidence",
            "next_action",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in report.live_reconciliation:
            writer.writerow(
                {
                    "source_group": row.source_group,
                    "source_type": row.source_type,
                    "asset": row.asset or "",
                    "ledger_quantity": ""
                    if row.ledger_quantity is None
                    else str(row.ledger_quantity),
                    "ledger_value_eur": str(row.ledger_value_eur),
                    "external_quantity": ""
                    if row.external_quantity is None
                    else str(row.external_quantity),
                    "external_value_eur": ""
                    if row.external_value_eur is None
                    else str(row.external_value_eur),
                    "delta_quantity": ""
                    if row.delta_quantity is None
                    else str(row.delta_quantity),
                    "delta_value_eur": ""
                    if row.delta_value_eur is None
                    else str(row.delta_value_eur),
                    "status": row.status,
                    "severity": row.severity,
                    "evidence": row.evidence,
                    "next_action": row.next_action,
                }
            )
        return output.getvalue()

    def evidence_package_zip(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> bytes:
        report = self.summary(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            court_evidence_reference=court_evidence_reference,
            cutoff_at=cutoff_at,
            valuation_at=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
        )
        summary_json = json.dumps(
            report.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")
        accounts_csv = self._accounts_csv_for_report(report).encode("utf-8")
        valuation_tokens_csv = self._valuation_tokens_csv_for_report(report).encode(
            "utf-8"
        )
        live_reconciliation_csv = self._live_reconciliation_csv_for_report(
            report
        ).encode("utf-8")
        capital_flows_csv = self._capital_flows_csv_for_report(report).encode("utf-8")
        capital_flows_json = json.dumps(
            report.capital_flow_gate.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        inheritance_origin_json = json.dumps(
            report.inheritance_origin_gate.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        inheritance_origin_csv = DivorceInheritanceOriginService.csv_for_report(
            report.inheritance_origin_gate
        ).encode("utf-8")
        inheritance_credits_csv = (
            DivorceInheritanceOriginService.inheritance_credits_csv_for_report(
                report.inheritance_origin_gate
            ).encode("utf-8")
        )
        trade_republic_documents_csv = (
            DivorceInheritanceOriginService.trade_republic_documents_csv_for_connector(
                report.inheritance_origin_gate.trade_republic_connector
            ).encode("utf-8")
        )
        inheritance_documents_csv = (
            DivorceInheritanceOriginService.inheritance_documents_csv_for_connector(
                report.inheritance_origin_gate.formal_inheritance_connector
            ).encode("utf-8")
        )
        coinbase_connector_csv = (
            DivorceInheritanceOriginService.coinbase_connector_csv_for_connector(
                report.inheritance_origin_gate.coinbase_connector
            ).encode("utf-8")
        )
        live_reconciliation_json = json.dumps(
            [row.model_dump(mode="json") for row in report.live_reconciliation],
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        price_gates_json = json.dumps(
            {
                "cutoff": report.cutoff_price_gate.model_dump(mode="json"),
                "valuation": report.valuation_price_gate.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        token_valuation_decisions_csv = self.token_valuation_service.decisions_csv(
            {
                report.stichtage.separation_date,
                report.stichtage.end_asset_date,
            }
        ).encode("utf-8")
        service_route_evidence_json = self._service_route_evidence_json_for_report(
            report
        )
        methodology = {
            "label": "divorce-equalization-evidence-package",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stichtage": report.stichtage.model_dump(mode="json"),
            "cutoff_at": report.cutoff_at.isoformat(),
            "valuation_at": report.valuation_at.isoformat()
            if report.valuation_at
            else None,
            "files": [
                {
                    "path": "00_Manifest/divorce-equalization-summary.json",
                    "source_endpoint": "/api/v1/divorce/equalization-summary",
                    "description": "Vollstaendige Zugewinn-Auswertung inklusive BMF-Abgrenzung.",
                },
                {
                    "path": "01_Konten/divorce-equalization-accounts.csv",
                    "source_endpoint": "/api/v1/divorce/equalization-summary/accounts.csv",
                    "description": "Wallet-/Konto-Uebersicht mit Stichtagswerten und Review-Token-Werten.",
                },
                {
                    "path": "02_Token/divorce-equalization-valuation-tokens.csv",
                    "source_endpoint": "/api/v1/divorce/equalization-summary/valuation-tokens.csv",
                    "description": "Token je Wallet fuer beide Stichtage mit Preisquelle, Preisalter und Markierung.",
                },
                {
                    "path": "02_Token/valuation-price-gates.json",
                    "source_endpoint": "/api/v1/divorce/equalization-summary",
                    "description": "Materialitaets- und Preisqualitaets-Gates fuer beide Stichtage.",
                },
                {
                    "path": "02_Token/stichtag-token-valuation-decisions.csv",
                    "source_endpoint": "/api/v1/prices/as-of-gate/token-review-decisions.csv",
                    "description": "Mintgenaue, stichtagsbezogene Annahmeentscheidungen fuer bewertete Risikotoken.",
                },
                {
                    "path": "03_Live_Abgleich/live-reconciliation.json",
                    "source_endpoint": "/api/v1/portfolio/reconciliation",
                    "description": "Read-only Live-/Solscan-/Connector-Abgleich fuer relevante Wallets und Quellen.",
                },
                {
                    "path": "03_Live_Abgleich/live-reconciliation.csv",
                    "source_endpoint": "/api/v1/divorce/equalization-summary/live-reconciliation.csv",
                    "description": "CSV-Version des Live-/Solscan-/Connector-Abgleichs.",
                },
                {
                    "path": "04_Vermoegensfluss/capital-flow-reconciliation.json",
                    "source_endpoint": "/api/v1/divorce/equalization-summary",
                    "description": "Fluss-Gate mit Kapitalherkunft, Abflussklassifikation und Szenariorechnung.",
                },
                {
                    "path": "04_Vermoegensfluss/capital-flow-reconciliation.csv",
                    "source_endpoint": "/api/v1/divorce/equalization-summary/capital-flows.csv",
                    "description": "Pruefbare Einzelzeilen der Kapitalzufluesse und negativen Transfers.",
                },
                {
                    "path": "04_Vermoegensfluss/service-route-evidence.json",
                    "source_endpoint": "/api/v1/divorce/service-route-evidence/{tx_id}",
                    "description": "SHA-gepruefter Solana-RPC-Lebenszyklus akzeptierter interner Servicepositionen ohne steuerliche Umdeutung.",
                },
                {
                    "path": "04_Vermoegensfluss/inheritance-origin.json",
                    "source_endpoint": "/api/v1/divorce/inheritance-origin",
                    "description": "Datensparsamer Erbgeld-, Bank- und Anbieter-Nachweis mit offenen Depotwert-Gates.",
                },
                {
                    "path": "04_Vermoegensfluss/inheritance-origin.csv",
                    "source_endpoint": "/api/v1/divorce/inheritance-origin.csv",
                    "description": "Gehashte Investmentabfluesse je Anbieter ohne Bank-Gegenparteien oder Kontodaten.",
                },
                {
                    "path": "04_Vermoegensfluss/inheritance-credit-evidence.csv",
                    "source_endpoint": "/api/v1/divorce/inheritance-credits.csv",
                    "description": "Einzelne Erbmittelzufluesse mit Betrag, Datumsbasis und SHA-256-Belegbindung.",
                },
                {
                    "path": "04_Vermoegensfluss/trade-republic-document-evidence.csv",
                    "source_endpoint": "/api/v1/divorce/trade-republic/documents.csv",
                    "description": "Datensparsame Parsergebnisse und SHA-256-Belegbindung ohne Dateinamen oder Rohdokumente.",
                },
                {
                    "path": "04_Vermoegensfluss/formal-inheritance-document-evidence.csv",
                    "source_endpoint": "/api/v1/divorce/inheritance-documents.csv",
                    "description": "SHA-256-Belegbindung und Reviewstatus des formalen Erbnachweises ohne Dateinamen oder Rohdokument.",
                },
                {
                    "path": "04_Vermoegensfluss/coinbase-history-valuation-evidence.csv",
                    "source_endpoint": "/api/v1/divorce/coinbase/connector.csv",
                    "description": "Hashgebundener Coinbase-Historien-, Mengen-, Preis- und Reviewstatus ohne Rohtransaktionsdaten.",
                },
                {
                    "path": "00_Manifest/methodik-und-bmf-abgrenzung.json",
                    "source_endpoint": None,
                    "description": "Read-only Methodik, BMF-Abgrenzung und rechtliche Caveats.",
                },
            ],
            "bmf_tax_boundary": report.bmf_tax_boundary.model_dump(mode="json"),
            "legal_note": report.legal_note,
            "methodology": report.methodology,
            "caveats": report.caveats,
            "read_only": True,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as package:
            package.writestr(
                "00_Manifest/divorce-equalization-summary.json", summary_json
            )
            package.writestr(
                "01_Konten/divorce-equalization-accounts.csv", accounts_csv
            )
            package.writestr(
                "02_Token/divorce-equalization-valuation-tokens.csv",
                valuation_tokens_csv,
            )
            package.writestr("02_Token/valuation-price-gates.json", price_gates_json)
            package.writestr(
                "02_Token/stichtag-token-valuation-decisions.csv",
                token_valuation_decisions_csv,
            )
            package.writestr(
                "03_Live_Abgleich/live-reconciliation.json", live_reconciliation_json
            )
            package.writestr(
                "03_Live_Abgleich/live-reconciliation.csv", live_reconciliation_csv
            )
            package.writestr(
                "04_Vermoegensfluss/capital-flow-reconciliation.json",
                capital_flows_json,
            )
            package.writestr(
                "04_Vermoegensfluss/capital-flow-reconciliation.csv", capital_flows_csv
            )
            package.writestr(
                "04_Vermoegensfluss/service-route-evidence.json",
                service_route_evidence_json,
            )
            package.writestr(
                "04_Vermoegensfluss/inheritance-origin.json", inheritance_origin_json
            )
            package.writestr(
                "04_Vermoegensfluss/inheritance-origin.csv", inheritance_origin_csv
            )
            package.writestr(
                "04_Vermoegensfluss/inheritance-credit-evidence.csv",
                inheritance_credits_csv,
            )
            package.writestr(
                "04_Vermoegensfluss/trade-republic-document-evidence.csv",
                trade_republic_documents_csv,
            )
            package.writestr(
                "04_Vermoegensfluss/formal-inheritance-document-evidence.csv",
                inheritance_documents_csv,
            )
            package.writestr(
                "04_Vermoegensfluss/coinbase-history-valuation-evidence.csv",
                coinbase_connector_csv,
            )
            package.writestr(
                "00_Manifest/methodik-und-bmf-abgrenzung.json",
                json.dumps(methodology, indent=2, ensure_ascii=False).encode("utf-8"),
            )
        return buffer.getvalue()

    def _service_route_evidence_json_for_report(
        self,
        report: DivorceEqualizationSummary,
    ) -> bytes:
        tx_ids = {
            str(row.tx_id)
            for row in report.capital_flow_gate.outflows
            if row.tx_id and row.classification == "internal_service_position_loss"
        }
        bundle = DivorceServiceRouteEvidenceService(
            self.store
        ).accepted_evidence_bundle(tx_ids)
        return json.dumps(
            bundle.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")

    def _valuation_flag_total(
        self, accounts: list[DivorceEqualizationAccountRow], flag: str
    ) -> Decimal:
        return sum(
            (
                asset.value_eur
                for account in accounts
                for asset in account.valuation_assets
                if asset.valuation_flag == flag
            ),
            Decimal("0"),
        )

    def _account_rows(
        self,
        cutoff_portfolio: object,
        valuation_portfolio: object,
        *,
        valuation_at: datetime,
        external_invest_by_account: dict[str, Decimal],
    ) -> list[DivorceEqualizationAccountRow]:
        cutoff_at = self._naive(cutoff_portfolio.as_of)
        cutoff_positions = self._positions_by_stable_account(cutoff_portfolio.positions)
        valuation_positions = self._positions_by_stable_account(
            valuation_portfolio.positions
        )
        rows: list[DivorceEqualizationAccountRow] = []
        for account in sorted(set(cutoff_positions) | set(valuation_positions)):
            cutoff_group = cutoff_positions.get(account, [])
            valuation_group = valuation_positions.get(account, [])
            cutoff_value = sum(
                (position.value_eur or Decimal("0") for position in cutoff_group),
                Decimal("0"),
            )
            valuation_value = sum(
                (position.value_eur or Decimal("0") for position in valuation_group),
                Decimal("0"),
            )
            cutoff_details = self._account_asset_rows(cutoff_group, cutoff_at)
            details = self._account_asset_rows(valuation_group, valuation_at)
            review_value = sum(
                (
                    item.value_eur
                    for item in details
                    if item.valuation_flag == "review_low_confidence_token"
                ),
                Decimal("0"),
            )
            classification, note = self._account_classification(account)
            external_invest = external_invest_by_account.get(account, Decimal("0"))
            source_accounts = sorted(
                {str(position.account) for position in cutoff_group + valuation_group}
            )
            rows.append(
                DivorceEqualizationAccountRow(
                    account=account,
                    source_accounts=source_accounts,
                    classification=classification,
                    valuation_basis="historical_ledger_as_of",
                    cutoff_value_eur=cutoff_value,
                    valuation_value_eur=valuation_value,
                    valuation_review_value_eur=review_value,
                    valuation_value_without_review_assets_eur=valuation_value
                    - review_value,
                    gross_change_eur=valuation_value - cutoff_value,
                    external_invest_since_cutoff_eur=external_invest,
                    adjusted_gain_loss_eur=valuation_value
                    - cutoff_value
                    - external_invest,
                    position_count_cutoff=len(cutoff_group),
                    position_count_valuation=len(valuation_group),
                    assets_cutoff=len(cutoff_details),
                    assets_valuation=len(details),
                    asset_labels_cutoff=[item.asset for item in cutoff_details],
                    asset_labels_valuation=[item.asset for item in details],
                    cutoff_assets=cutoff_details,
                    valuation_assets=details,
                    note=note,
                )
            )
        rows.sort(
            key=lambda row: abs(row.cutoff_value_eur) + abs(row.valuation_value_eur),
            reverse=True,
        )
        return rows

    def _positions_by_stable_account(
        self, positions: list[object]
    ) -> dict[str, list[object]]:
        grouped: defaultdict[str, list[object]] = defaultdict(list)
        for position in positions:
            grouped[self._stable_account(str(position.account))].append(position)
        return dict(grouped)

    def _account_asset_rows(
        self,
        positions: list[object],
        valuation_at: datetime,
    ) -> list[DivorceEqualizationAccountAssetRow]:
        grouped: defaultdict[str, list[object]] = defaultdict(list)
        for position in positions:
            grouped[str(position.asset).upper()].append(position)
        rows: list[DivorceEqualizationAccountAssetRow] = []
        for asset, asset_positions in grouped.items():
            value_eur = sum(
                (position.value_eur or Decimal("0") for position in asset_positions),
                Decimal("0"),
            )
            quantity = sum(
                (position.quantity for position in asset_positions), Decimal("0")
            )
            priced = [
                position
                for position in asset_positions
                if position.priced_at is not None
            ]
            latest = (
                max(priced, key=lambda position: position.priced_at) if priced else None
            )
            price_source = latest.price_source if latest is not None else None
            priced_at = latest.priced_at if latest is not None else None
            price_age_days, price_status = self._price_status(
                priced_at=priced_at,
                price_source=price_source,
                valuation_at=valuation_at,
            )
            flag, note = self._valuation_asset_flag(
                asset,
                value_eur,
                valuation_at=valuation_at,
            )
            rows.append(
                DivorceEqualizationAccountAssetRow(
                    asset=asset,
                    quantity=quantity,
                    value_eur=value_eur,
                    price_source=price_source,
                    priced_at=priced_at,
                    price_age_days=price_age_days,
                    price_status=price_status,
                    valuation_flag=flag,
                    note=note,
                )
            )
        rows.sort(key=lambda row: abs(row.value_eur), reverse=True)
        return rows

    @staticmethod
    def _stable_account(account: str) -> str:
        normalized = account.strip()
        lower = normalized.lower()
        if normalized in {
            PortfolioService.KNOWN_JUP_WALLET,
            PortfolioService.PRIMARY_SOLANA_WALLET,
        }:
            return normalized
        if lower in {"spot", "funding", "binance"} or "binance" in lower:
            return "Binance"
        if "bitget" in lower:
            return "Bitget"
        if "pionex" in lower:
            return "Pionex"
        if "coinbase" in lower:
            return "Coinbase"
        return normalized or "Unassigned"

    @staticmethod
    def _price_status(
        *,
        priced_at: datetime | None,
        price_source: str | None,
        valuation_at: datetime,
    ) -> tuple[int | None, str]:
        if priced_at is None:
            return None, "missing"
        normalized_price = DivorceEqualizationService._naive(priced_at)
        normalized_valuation = DivorceEqualizationService._naive(valuation_at)
        age_days = max((normalized_valuation.date() - normalized_price.date()).days, 0)
        if str(price_source or "").startswith("derived:event_quote"):
            return age_days, "derived_event_quote"
        if age_days == 0:
            return age_days, "same_day"
        if age_days == 1:
            return age_days, "prior_day"
        return age_days, "stale"

    def _valuation_gate(
        self,
        positions: list[object],
        valuation_at: datetime,
        materiality_threshold_eur: Decimal,
    ) -> DivorceValuationGate:
        same_day = 0
        prior_day = 0
        stale = 0
        missing = 0
        review = 0
        accepted_review = 0
        material = 0
        affected: set[str] = set()
        accepted_assets: set[str] = set()
        evidence_refs: set[str] = set()
        valuation_date = self._local_date(valuation_at)
        for position in positions:
            value_eur = abs(position.value_eur or Decimal("0"))
            asset = str(position.asset).upper()
            _age, price_status = self._price_status(
                priced_at=position.priced_at,
                price_source=position.price_source,
                valuation_at=valuation_at,
            )
            if price_status != "missing" and value_eur < materiality_threshold_eur:
                continue
            material += 1
            token_assessment = self.token_valuation_service.assessment(
                asset,
                valuation_date,
            )
            if (
                token_assessment.review_required
                and token_assessment.accepted_decision is None
            ):
                review += 1
                affected.add(asset)
            elif (
                token_assessment.review_required
                and token_assessment.accepted_decision is not None
            ):
                accepted_review += 1
                accepted_assets.add(asset)
                if token_assessment.accepted_decision.evidence_ref:
                    evidence_refs.add(token_assessment.accepted_decision.evidence_ref)
            if price_status == "same_day":
                same_day += 1
            elif price_status == "prior_day":
                prior_day += 1
                affected.add(asset)
            elif price_status == "missing":
                missing += 1
                affected.add(asset)
            elif price_status in {"stale", "derived_event_quote"}:
                stale += 1
                affected.add(asset)
        strict_ready = not any((prior_day, stale, missing, review))
        findings: list[str] = []
        if prior_day:
            findings.append(
                f"{prior_day} materielle Positionen nutzen den Preis des Vortags."
            )
        if stale:
            findings.append(
                f"{stale} materielle Positionen nutzen veraltete oder abgeleitete Preise."
            )
        if missing:
            findings.append(f"{missing} materielle Positionen besitzen keinen Preis.")
        if review:
            findings.append(
                f"{review} materielle Tokenpositionen sind als Risikopruefung markiert."
            )
        if accepted_review:
            findings.append(
                f"{accepted_review} materielle Risikotokenpositionen besitzen eine "
                "stichtagsbezogene, beleggebundene Bewertungsentscheidung."
            )
        if strict_ready:
            findings.append(
                "Alle materiellen Positionen besitzen einen belegten Same-Day-Preis; "
                "offene Token-Risikoflags bestehen nicht."
            )
        return DivorceValuationGate(
            valuation_at=valuation_at.replace(tzinfo=timezone.utc),
            materiality_threshold_eur=materiality_threshold_eur,
            positions_count=len(positions),
            material_positions_count=material,
            same_day_price_count=same_day,
            prior_day_price_count=prior_day,
            stale_price_count=stale,
            missing_price_count=missing,
            review_asset_count=review,
            accepted_review_asset_count=accepted_review,
            strict_ready=strict_ready,
            status="strict_ready" if strict_ready else "blocked",
            affected_assets=sorted(affected),
            accepted_review_assets=sorted(accepted_assets),
            token_review_evidence_refs=sorted(evidence_refs),
            findings=findings,
        )

    def _moonpay_onramp_values(
        self,
        cutoff: datetime,
        valuation: datetime,
    ) -> tuple[Decimal, Decimal]:
        report = MoonpayReceiptService(self.store).report(
            as_of=valuation.replace(tzinfo=timezone.utc)
        )
        items = [
            item
            for item in report.items
            if cutoff < self._naive(item.event_time) <= valuation
        ]
        confirmed = sum(
            (
                item.cost_basis_eur
                for item in items
                if item.strict_ready and item.cost_basis_eur is not None
            ),
            Decimal("0"),
        )
        provisional = sum(
            (
                item.provisional_market_value_eur
                for item in items
                if not item.strict_ready
            ),
            Decimal("0"),
        )
        return confirmed, provisional

    def _valuation_asset_flag(
        self,
        asset: str,
        value_eur: Decimal,
        *,
        valuation_at: datetime,
    ) -> tuple[str, str | None]:
        token_assessment = self.token_valuation_service.assessment(
            asset,
            self._local_date(valuation_at),
        )
        if (
            token_assessment.review_required
            and token_assessment.accepted_decision is None
        ):
            return (
                "review_low_confidence_token",
                "Bewertet, aber fuer Wallet-/Solscan-Abgleich separat pruefen; nicht automatisch aus Steuerdaten entfernt.",
            )
        if (
            token_assessment.review_required
            and token_assessment.accepted_decision is not None
        ):
            return (
                "valued_risk_review_accepted",
                "Exakter Mint und Same-Day-Preis wurden fuer diesen Stichtag beleggebunden angenommen.",
            )
        if abs(value_eur) < self.DUST_VALUE_EUR:
            return (
                "dust_under_1_eur",
                "Unter 1 EUR; fuer Anzeige/Portfolioanalyse als Staub behandeln.",
            )
        return "valued", None

    def _account_classification(self, account: str) -> tuple[str, str | None]:
        if account == PortfolioService.KNOWN_JUP_WALLET:
            return (
                "inheritance_jup_wallet",
                "Vom Nutzer als reine Erbgeld-/JUP-Wallet markiert; getrennt fuer Zugewinn-Belege ausweisen.",
            )
        if account == PortfolioService.PRIMARY_SOLANA_WALLET:
            return (
                "solana_main_wallet",
                "Solana Main Wallet; getrennt von der JUP-Erbgeld-Wallet ausweisen.",
            )
        if account == "Binance":
            return (
                "exchange_binance",
                "Binance-Unterkonten werden fuer den Stichtagsvergleich stabil zusammengefasst.",
            )
        if account == "Bitget":
            return (
                "exchange_bitget",
                "Bitget wird als eigene Handelsplattform ausgewiesen.",
            )
        if account == "Pionex":
            return (
                "exchange_pionex",
                "Pionex wird als eigene Handelsplattform ausgewiesen.",
            )
        if account == "Coinbase":
            return (
                "exchange_coinbase",
                "Coinbase wird als eigene Handelsplattform ausgewiesen.",
            )
        return "portfolio_account", None

    def _bucket(
        self,
        *,
        bucket_id: str,
        label: str,
        description: str,
        open_lot_predicate: object,
        sold_line_predicate: object,
        latest_prices: dict[str, tuple[Decimal, datetime, str]],
    ) -> DivorceEqualizationBucket:
        rows_by_asset: defaultdict[str, DivorceEqualizationAssetRow] = defaultdict(
            lambda: DivorceEqualizationAssetRow(asset="")
        )
        open_lots_count = 0
        missing_assets: set[str] = set()
        for lot in self._open_lot_rows():
            if not open_lot_predicate(lot):  # type: ignore[operator]
                continue
            asset = str(lot["asset"]).upper()
            row = rows_by_asset[asset]
            row.asset = asset
            open_lots_count += 1
            quantity_total = Decimal(str(lot["quantity_total"]))
            quantity_remaining = Decimal(str(lot["quantity_remaining"]))
            cost_basis_total = Decimal(str(lot["cost_basis_eur_total"]))
            open_cost = (
                Decimal("0")
                if quantity_total == 0
                else cost_basis_total * quantity_remaining / quantity_total
            )
            row.quantity_open += quantity_remaining
            row.open_cost_basis_eur += open_cost
            row.total_cost_basis_eur += open_cost
            price = latest_prices.get(asset)
            if price is None:
                row.missing_price_count += 1
                missing_assets.add(asset)
                continue
            price_eur, priced_at, source = price
            open_value = quantity_remaining * price_eur
            row.open_value_eur += open_value
            row.latest_price_eur = price_eur
            row.latest_price_at = priced_at
            row.latest_price_source = source
        sold_lines_count = 0
        for line in TaxService(self.store).list_tax_lines():
            if not sold_line_predicate(line):  # type: ignore[operator]
                continue
            asset = str(line.asset).upper()
            row = rows_by_asset[asset]
            row.asset = asset
            sold_lines_count += 1
            row.sold_quantity += line.quantity
            row.sold_cost_basis_eur += line.acquisition_cost_eur
            row.sold_proceeds_eur += line.disposal_proceeds_eur
            row.realized_gain_loss_eur += line.gain_loss_eur
            row.total_cost_basis_eur += line.acquisition_cost_eur
        assets = []
        for row in rows_by_asset.values():
            row.unrealized_gain_loss_eur = row.open_value_eur - row.open_cost_basis_eur
            row.total_value_or_proceeds_eur = row.open_value_eur + row.sold_proceeds_eur
            row.total_gain_loss_eur = (
                row.unrealized_gain_loss_eur + row.realized_gain_loss_eur
            )
            assets.append(row)
        assets.sort(
            key=lambda item: abs(item.total_value_or_proceeds_eur), reverse=True
        )
        open_cost = sum((item.open_cost_basis_eur for item in assets), Decimal("0"))
        open_value = sum((item.open_value_eur for item in assets), Decimal("0"))
        sold_cost = sum((item.sold_cost_basis_eur for item in assets), Decimal("0"))
        sold_proceeds = sum((item.sold_proceeds_eur for item in assets), Decimal("0"))
        realized = sum((item.realized_gain_loss_eur for item in assets), Decimal("0"))
        unrealized = open_value - open_cost
        return DivorceEqualizationBucket(
            bucket_id=bucket_id,
            label=label,
            description=description,
            open_lots_count=open_lots_count,
            sold_lines_count=sold_lines_count,
            open_cost_basis_eur=open_cost,
            open_value_eur=open_value,
            unrealized_gain_loss_eur=unrealized,
            sold_cost_basis_eur=sold_cost,
            sold_proceeds_eur=sold_proceeds,
            realized_gain_loss_eur=realized,
            total_cost_basis_eur=open_cost + sold_cost,
            total_value_or_proceeds_eur=open_value + sold_proceeds,
            total_gain_loss_eur=unrealized + realized,
            missing_price_assets=sorted(missing_assets),
            assets=assets,
        )

    def _open_lot_rows(self) -> list[dict[str, object]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    l.asset,
                    l.acquired_at,
                    l.quantity_total,
                    l.quantity_remaining,
                    l.cost_basis_eur_total,
                    l.source_event_id,
                    e.event_type,
                    e.source,
                    e.account,
                    e.quote_asset,
                    e.quantity as event_quantity
                from tax_lots l
                left join canonical_events e on e.event_id = l.source_event_id
                where l.quantity_remaining > 0
                """
            ).fetchall()
        keys = [
            "asset",
            "acquired_at",
            "quantity_total",
            "quantity_remaining",
            "cost_basis_eur_total",
            "source_event_id",
            "event_type",
            "source",
            "account",
            "quote_asset",
            "event_quantity",
        ]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def _prices_as_of(
        self, valuation_at: datetime
    ) -> dict[str, tuple[Decimal, datetime, str]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select p.asset, p.price_eur, p.priced_at, p.source
                from price_ledger p
                join (
                    select asset, max(priced_at) as max_priced_at
                    from price_ledger
                    where priced_at <= ?
                    group by asset
                ) latest on latest.asset = p.asset and latest.max_priced_at = p.priced_at
                """,
                [valuation_at],
            ).fetchall()
        return {
            str(asset).upper(): (Decimal(str(price_eur)), priced_at, str(source))
            for asset, price_eur, priced_at, source in rows
        }

    def _latest_timestamps(self) -> tuple[datetime | None, datetime | None]:
        with self.store.connect() as con:
            latest_event_at = con.execute(
                "select max(event_time) from canonical_events"
            ).fetchone()[0]
            latest_price_at = con.execute(
                "select max(priced_at) from price_ledger"
            ).fetchone()[0]
        return latest_event_at, latest_price_at

    def _decimal_scalar(self, sql: str, params: list[object]) -> Decimal:
        with self.store.connect() as con:
            value = con.execute(sql, params).fetchone()[0]
        return Decimal(str(value or 0))

    @classmethod
    def local_day_end_utc(cls, value: date) -> datetime:
        return datetime.combine(
            value,
            time.max,
            tzinfo=ZoneInfo(cls.VALUATION_TIMEZONE),
        ).astimezone(timezone.utc)

    @classmethod
    def _resolve_stichtag(
        cls,
        *,
        local_date: date | None,
        explicit_at: datetime | None,
        default_date: date,
        label: str,
    ) -> datetime:
        if local_date is not None:
            resolved = cls.local_day_end_utc(local_date)
            if explicit_at is not None:
                explicit_utc = (
                    explicit_at.replace(tzinfo=timezone.utc)
                    if explicit_at.tzinfo is None
                    else explicit_at.astimezone(timezone.utc)
                )
                if explicit_utc != resolved:
                    raise ValueError(
                        f"{label}: Datum und expliziter Zeitpunkt widersprechen sich."
                    )
            return resolved
        if explicit_at is None:
            return cls.local_day_end_utc(default_date)
        if explicit_at.tzinfo is None:
            return explicit_at.replace(tzinfo=timezone.utc)
        return explicit_at.astimezone(timezone.utc)

    @classmethod
    def _local_date(cls, value: datetime) -> date:
        aware = (
            value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        )
        return aware.astimezone(ZoneInfo(cls.VALUATION_TIMEZONE)).date()

    @staticmethod
    def _naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
