from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
import io
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
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService


class DivorceEqualizationService:
    DEFAULT_CUTOFF_AT = datetime(2025, 6, 13)
    BMF_REFERENCE_URL = (
        "https://www.bundesfinanzministerium.de/Content/DE/Downloads/"
        "BMF_Schreiben/Steuerarten/Einkommensteuer/"
        "2025-03-06-einzelfragen-kryptowerte-bmf-schreiben.pdf"
    )
    SOLANA_REVIEW_ASSETS = {"CBDC", "CWIF", "SHARK"}
    DUST_VALUE_EUR = Decimal("1")

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def summary(self, *, cutoff_at: datetime | None = None) -> DivorceEqualizationSummary:
        cutoff = self._naive(cutoff_at or self.DEFAULT_CUTOFF_AT)
        latest_prices = self._latest_prices()
        latest_event_at, latest_price_at = self._latest_timestamps()
        portfolio_service = PortfolioService(self.store)
        cutoff_portfolio = portfolio_service.as_of_snapshot(cutoff)
        valuation_portfolio = portfolio_service.snapshot()
        accounts = self._account_rows(cutoff_portfolio, valuation_portfolio)
        live_reconciliation = self._live_reconciliation_rows(portfolio_service)
        valuation_review_value = sum((item.valuation_review_value_eur for item in accounts), Decimal("0"))
        valuation_dust_value = self._valuation_flag_total(accounts, "dust_under_1_eur")
        valuation_without_review = valuation_portfolio.total_value_eur - valuation_review_value
        marital = self._bucket(
            bucket_id="marital_pre_cutoff",
            label="Technische FIFO-Kontrollsicht: Alt-Lots vor Stichtag",
            description=(
                "Keine Vermoegenssumme. Diese technische Sicht zeigt FIFO-Lots mit "
                "Anschaffung vor dem 13.06.2025. Sie kann Handelsdurchlauf/Kostenbasis "
                "enthalten und darf nicht als tatsaechlich besessenes Anlagevermoegen "
                "interpretiert werden."
            ),
            open_lot_predicate=lambda row: self._naive(row["acquired_at"]) < cutoff,
            sold_line_predicate=lambda line: (
                self._naive(line.acquired_at) < cutoff
                and self._naive(line.disposed_at) >= cutoff
            ),
            latest_prices=latest_prices,
        )
        post_cutoff_direct_eur = self._bucket(
            bucket_id="post_cutoff_direct_eur_invest",
            label="Nach Stichtag direkt mit EUR gekauft",
            description=(
                "Offene Lots ab dem 13.06.2025, deren Ursprungsevent direkt gegen "
                "EUR gekauft wurde. Das ist die engere Spur fuer Erbgeld-/Fiat-Invest."
            ),
            open_lot_predicate=lambda row: (
                self._naive(row["acquired_at"]) >= cutoff
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
                "Alle offenen Lots ab dem 13.06.2025 inklusive Krypto-Swaps, "
                "Rewards/Mining und Transfers. Diese Sicht ist weiter als die reine EUR-Invest-Spur."
            ),
            open_lot_predicate=lambda row: self._naive(row["acquired_at"]) >= cutoff,
            sold_line_predicate=lambda line: self._naive(line.acquired_at) >= cutoff,
            latest_prices=latest_prices,
        )
        fiat_deposits = self._decimal_scalar(
            """
            select coalesce(sum(quantity), 0)
            from canonical_events
            where event_time >= ?
              and source = 'binance'
              and event_type = 'transfer'
              and asset = 'EUR'
              and account = 'binance'
              and quantity > 0
            """,
            [cutoff],
        )
        direct_eur_buys = self._decimal_scalar(
            """
            select coalesce(sum(abs(quote_quantity)), 0)
            from canonical_events
            where event_time >= ?
              and quantity > 0
              and quote_asset = 'EUR'
            """,
            [cutoff],
        )
        eur_spent_without_quote = self._decimal_scalar(
            """
            select coalesce(sum(abs(quantity)), 0)
            from canonical_events
            where event_time >= ?
              and event_type = 'trade'
              and asset = 'EUR'
              and quantity < 0
            """,
            [cutoff],
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
                "Wenn der exakte Bewertungsstichtag gerichtlich abweicht, muessen die Preise fuer "
                "diesen Stichtag erneut importiert und die Auswertung neu erzeugt werden."
            ),
        ]
        return DivorceEqualizationSummary(
            generated_at=datetime.now(timezone.utc),
            cutoff_at=cutoff.replace(tzinfo=timezone.utc),
            valuation_at=latest_price_at.replace(tzinfo=timezone.utc) if latest_price_at else None,
            latest_event_at=latest_event_at.replace(tzinfo=timezone.utc) if latest_event_at else None,
            latest_price_at=latest_price_at.replace(tzinfo=timezone.utc) if latest_price_at else None,
            cutoff_portfolio_value_eur=cutoff_portfolio.total_value_eur,
            valuation_portfolio_value_eur=valuation_portfolio.total_value_eur,
            valuation_review_value_eur=valuation_review_value,
            valuation_dust_value_eur=valuation_dust_value,
            valuation_value_without_review_assets_eur=valuation_without_review,
            gross_portfolio_change_eur=valuation_portfolio.total_value_eur - cutoff_portfolio.total_value_eur,
            gross_portfolio_change_without_review_assets_eur=valuation_without_review - cutoff_portfolio.total_value_eur,
            net_external_invest_since_cutoff_eur=fiat_deposits,
            adjusted_gain_loss_excluding_new_invest_eur=(
                valuation_portfolio.total_value_eur
                - cutoff_portfolio.total_value_eur
                - fiat_deposits
            ),
            adjusted_gain_loss_without_review_assets_eur=(
                valuation_without_review
                - cutoff_portfolio.total_value_eur
                - fiat_deposits
            ),
            cutoff_missing_price_assets=cutoff_portfolio.missing_price_assets,
            valuation_missing_price_assets=valuation_portfolio.missing_price_assets,
            fiat_deposits_since_cutoff_eur=fiat_deposits,
            direct_eur_buys_since_cutoff_eur=direct_eur_buys,
            eur_asset_spent_without_quote_since_cutoff_eur=eur_spent_without_quote,
            marital_pre_cutoff=marital,
            post_cutoff_direct_eur_invest=post_cutoff_direct_eur,
            post_cutoff_all_lots=post_cutoff_all,
            accounts=accounts,
            live_reconciliation=live_reconciliation,
            bmf_tax_boundary=self._bmf_tax_boundary(),
            cash_flows=[
                DivorceEqualizationCashFlow(
                    label="Nachweisbare Binance-EUR-Zufluesse ab Stichtag",
                    amount_eur=fiat_deposits,
                    note="Externe Fiat-Zufluesse in Canonical Events: source=binance, account=binance.",
                ),
                DivorceEqualizationCashFlow(
                    label="Direkte EUR-Kaeufe ab Stichtag",
                    amount_eur=direct_eur_buys,
                    note="Positive Krypto-Kaufereignisse mit quote_asset=EUR.",
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
                "Vermoegen dem Anfangsvermoegen zu; § 1376 BGB regelt Bewertungszeitpunkte."
            ),
            methodology=(
                "Read-only Auswertung aus Portfolio-Stichtagsbewertung, canonical_events, "
                "tax_lots, tax_lines und price_ledger. Die Hauptvermoegenswerte sind "
                "Portfolio-Marktwerte zum Stichtag und Bewertungszeitpunkt. FIFO-Kostenbasis "
                "wird nur als technische Kontrollsicht fuer Lots ausgewiesen."
            ),
        )

    def _live_reconciliation_rows(self, portfolio_service: PortfolioService) -> list[DivorceEqualizationLiveReconciliationRow]:
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
            if row.source_group in relevant_sources or row.severity in {"blocker", "warning"}
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
                    "Tax-Lines, Rewards/Mining/Staking, Derivate, externe Zufluesse, "
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

    def valuation_tokens_csv(self, *, cutoff_at: datetime | None = None) -> str:
        report = self.summary(cutoff_at=cutoff_at)
        output = io.StringIO()
        fieldnames = [
            "account",
            "classification",
            "valuation_basis",
            "asset",
            "quantity",
            "value_eur",
            "valuation_flag",
            "price_source",
            "priced_at",
            "note",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for account in report.accounts:
            for asset in account.valuation_assets:
                writer.writerow(
                    {
                        "account": account.account,
                        "classification": account.classification,
                        "valuation_basis": account.valuation_basis,
                        "asset": asset.asset,
                        "quantity": str(asset.quantity),
                        "value_eur": str(asset.value_eur),
                        "valuation_flag": asset.valuation_flag,
                        "price_source": asset.price_source or "",
                        "priced_at": asset.priced_at.isoformat() if asset.priced_at else "",
                        "note": asset.note or "",
                    }
                )
        return output.getvalue()

    def accounts_csv(self, *, cutoff_at: datetime | None = None) -> str:
        report = self.summary(cutoff_at=cutoff_at)
        output = io.StringIO()
        fieldnames = [
            "account",
            "classification",
            "valuation_basis",
            "cutoff_value_eur",
            "valuation_value_eur",
            "valuation_value_without_review_assets_eur",
            "valuation_review_value_eur",
            "gross_change_eur",
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
                    "classification": account.classification,
                    "valuation_basis": account.valuation_basis,
                    "cutoff_value_eur": str(account.cutoff_value_eur),
                    "valuation_value_eur": str(account.valuation_value_eur),
                    "valuation_value_without_review_assets_eur": str(account.valuation_value_without_review_assets_eur),
                    "valuation_review_value_eur": str(account.valuation_review_value_eur),
                    "gross_change_eur": str(account.gross_change_eur),
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

    def live_reconciliation_csv(self, *, cutoff_at: datetime | None = None) -> str:
        report = self.summary(cutoff_at=cutoff_at)
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
                    "ledger_quantity": "" if row.ledger_quantity is None else str(row.ledger_quantity),
                    "ledger_value_eur": str(row.ledger_value_eur),
                    "external_quantity": "" if row.external_quantity is None else str(row.external_quantity),
                    "external_value_eur": "" if row.external_value_eur is None else str(row.external_value_eur),
                    "delta_quantity": "" if row.delta_quantity is None else str(row.delta_quantity),
                    "delta_value_eur": "" if row.delta_value_eur is None else str(row.delta_value_eur),
                    "status": row.status,
                    "severity": row.severity,
                    "evidence": row.evidence,
                    "next_action": row.next_action,
                }
            )
        return output.getvalue()

    def evidence_package_zip(self, *, cutoff_at: datetime | None = None) -> bytes:
        report = self.summary(cutoff_at=cutoff_at)
        summary_json = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")
        accounts_csv = self.accounts_csv(cutoff_at=cutoff_at).encode("utf-8")
        valuation_tokens_csv = self.valuation_tokens_csv(cutoff_at=cutoff_at).encode("utf-8")
        live_reconciliation_csv = self.live_reconciliation_csv(cutoff_at=cutoff_at).encode("utf-8")
        live_reconciliation_json = json.dumps(
            [row.model_dump(mode="json") for row in report.live_reconciliation],
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        methodology = {
            "label": "divorce-equalization-evidence-package",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cutoff_at": report.cutoff_at.isoformat(),
            "valuation_at": report.valuation_at.isoformat() if report.valuation_at else None,
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
                    "description": "Token je Wallet zum Bewertungsstand mit Preisquelle und Markierung.",
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
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("00_Manifest/divorce-equalization-summary.json", summary_json)
            package.writestr("01_Konten/divorce-equalization-accounts.csv", accounts_csv)
            package.writestr("02_Token/divorce-equalization-valuation-tokens.csv", valuation_tokens_csv)
            package.writestr("03_Live_Abgleich/live-reconciliation.json", live_reconciliation_json)
            package.writestr("03_Live_Abgleich/live-reconciliation.csv", live_reconciliation_csv)
            package.writestr(
                "00_Manifest/methodik-und-bmf-abgrenzung.json",
                json.dumps(methodology, indent=2, ensure_ascii=False).encode("utf-8"),
            )
        return buffer.getvalue()

    def _valuation_flag_total(self, accounts: list[DivorceEqualizationAccountRow], flag: str) -> Decimal:
        return sum(
            (
                asset.value_eur
                for account in accounts
                for asset in account.valuation_assets
                if asset.valuation_flag == flag
            ),
            Decimal("0"),
        )

    def _account_rows(self, cutoff_portfolio: object, valuation_portfolio: object) -> list[DivorceEqualizationAccountRow]:
        cutoff_by_account = {row.account: row for row in cutoff_portfolio.account_summary}
        valuation_by_account = {row.account: row for row in valuation_portfolio.account_summary}
        cutoff_assets = self._assets_by_account(cutoff_portfolio.positions)
        valuation_assets = self._assets_by_account(valuation_portfolio.positions)
        valuation_asset_details = self._valuation_assets_by_account(valuation_portfolio.positions)
        rows: list[DivorceEqualizationAccountRow] = []
        for account in sorted(set(cutoff_by_account) | set(valuation_by_account)):
            cutoff = cutoff_by_account.get(account)
            valuation = valuation_by_account.get(account)
            cutoff_value = cutoff.value_eur if cutoff else Decimal("0")
            valuation_value = valuation.value_eur if valuation else Decimal("0")
            details = valuation_asset_details.get(account, [])
            review_value = sum(
                (item.value_eur for item in details if item.valuation_flag == "review_low_confidence_token"),
                Decimal("0"),
            )
            classification, note = self._account_classification(account)
            rows.append(
                DivorceEqualizationAccountRow(
                    account=account,
                    classification=classification,
                    valuation_basis="current_live_anchored_snapshot",
                    cutoff_value_eur=cutoff_value,
                    valuation_value_eur=valuation_value,
                    valuation_review_value_eur=review_value,
                    valuation_value_without_review_assets_eur=valuation_value - review_value,
                    gross_change_eur=valuation_value - cutoff_value,
                    position_count_cutoff=cutoff.position_count if cutoff else 0,
                    position_count_valuation=valuation.position_count if valuation else 0,
                    assets_cutoff=cutoff.assets if cutoff else 0,
                    assets_valuation=valuation.assets if valuation else 0,
                    asset_labels_cutoff=cutoff_assets.get(account, []),
                    asset_labels_valuation=valuation_assets.get(account, []),
                    valuation_assets=details,
                    note=note,
                )
            )
        rows.sort(key=lambda row: abs(row.cutoff_value_eur) + abs(row.valuation_value_eur), reverse=True)
        return rows

    def _assets_by_account(self, positions: list[object]) -> dict[str, list[str]]:
        assets: defaultdict[str, set[str]] = defaultdict(set)
        for position in positions:
            assets[position.account].add(str(position.asset).upper())
        return {account: sorted(labels) for account, labels in assets.items()}

    def _valuation_assets_by_account(self, positions: list[object]) -> dict[str, list[DivorceEqualizationAccountAssetRow]]:
        grouped: defaultdict[str, list[DivorceEqualizationAccountAssetRow]] = defaultdict(list)
        for position in positions:
            asset = str(position.asset).upper()
            value_eur = position.value_eur or Decimal("0")
            flag, note = self._valuation_asset_flag(asset, value_eur)
            grouped[position.account].append(
                DivorceEqualizationAccountAssetRow(
                    asset=asset,
                    quantity=position.quantity,
                    value_eur=value_eur,
                    price_source=position.price_source,
                    priced_at=position.priced_at,
                    valuation_flag=flag,
                    note=note,
                )
            )
        for rows in grouped.values():
            rows.sort(key=lambda row: abs(row.value_eur), reverse=True)
        return dict(grouped)

    def _valuation_asset_flag(self, asset: str, value_eur: Decimal) -> tuple[str, str | None]:
        if asset in self.SOLANA_REVIEW_ASSETS:
            return (
                "review_low_confidence_token",
                "Bewertet, aber fuer Wallet-/Solscan-Abgleich separat pruefen; nicht automatisch aus Steuerdaten entfernt.",
            )
        if abs(value_eur) < self.DUST_VALUE_EUR:
            return "dust_under_1_eur", "Unter 1 EUR; fuer Anzeige/Portfolioanalyse als Staub behandeln."
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
        if account == "Binance Earn Flexible JUP001":
            return (
                "binance_jup_product",
                "Binance-JUP-Produkt separat pruefen und nicht mit Wallet-Bestaenden vermischen.",
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
            open_cost = Decimal("0") if quantity_total == 0 else cost_basis_total * quantity_remaining / quantity_total
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
            row.total_gain_loss_eur = row.unrealized_gain_loss_eur + row.realized_gain_loss_eur
            assets.append(row)
        assets.sort(key=lambda item: abs(item.total_value_or_proceeds_eur), reverse=True)
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

    def _latest_prices(self) -> dict[str, tuple[Decimal, datetime, str]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select p.asset, p.price_eur, p.priced_at, p.source
                from price_ledger p
                join (
                    select asset, max(priced_at) as max_priced_at
                    from price_ledger
                    group by asset
                ) latest on latest.asset = p.asset and latest.max_priced_at = p.priced_at
                """
            ).fetchall()
        return {
            str(asset).upper(): (Decimal(str(price_eur)), priced_at, str(source))
            for asset, price_eur, priced_at, source in rows
        }

    def _latest_timestamps(self) -> tuple[datetime | None, datetime | None]:
        with self.store.connect() as con:
            latest_event_at = con.execute("select max(event_time) from canonical_events").fetchone()[0]
            latest_price_at = con.execute("select max(priced_at) from price_ledger").fetchone()[0]
        return latest_event_at, latest_price_at

    def _decimal_scalar(self, sql: str, params: list[object]) -> Decimal:
        with self.store.connect() as con:
            value = con.execute(sql, params).fetchone()[0]
        return Decimal(str(value or 0))

    @staticmethod
    def _naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
