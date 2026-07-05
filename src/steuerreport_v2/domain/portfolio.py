from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from types import SimpleNamespace
import urllib.parse
import urllib.request

import httpx

from steuerreport_v2.contracts.jupiter import JupiterTokenMetadataCacheItem
from steuerreport_v2.contracts.portfolio import (
    PortfolioAccountAlias,
    PortfolioAccountSummary,
    PortfolioAsOfSnapshot,
    PortfolioAssetSummary,
    PortfolioFiatDeposit,
    PortfolioFiatDepositReport,
    PortfolioInvestmentLocation,
    PortfolioPriceQuality,
    PortfolioLiveBalanceSnapshot,
    PortfolioReconciliationReport,
    PortfolioReconciliationRefreshConnectorResult,
    PortfolioReconciliationRefreshResult,
    PortfolioReconciliationRow,
    PortfolioSeparationReport,
    PortfolioSeparationLot,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioSourceAccount,
    PortfolioSourceAsset,
    PortfolioSourceGroup,
    PortfolioSourceOverview,
    PortfolioTokenRiskReport,
    PortfolioTokenRiskRow,
    PortfolioTrendPoint,
    PortfolioValuationAuditReport,
    PortfolioValuationAuditRow,
    PortfolioVirtualWallet,
    PortfolioWalletHistoryImportRequest,
    PortfolioWalletHistoryImportResult,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map_for_store,
    canonical_account_label,
    unresolved_truncated_account_labels,
)
from steuerreport_v2.domain.jupiter import JupiterTokenService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup, fiat_price_point
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.secrets import resolve_secret_value
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


class PortfolioService:
    DEFAULT_SEPARATION_CUTOFF = datetime(2025, 6, 13, tzinfo=timezone.utc)
    SEPARATION_LABEL = "Virtuelle Wallet: Neubestand ab 13.06.2025"
    SEPARATION_EXCLUDED_ASSETS = {"EUR"}
    PORTFOLIO_EXCLUDED_ACCOUNTS = {"binance"}
    MAIN_HELIUM_LEGACY_WALLET = "1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV"
    HELIUM_TO_SOLANA_MIGRATION_ACCOUNT = "Helium -> Solana Migration Startbestand"
    HELIUM_SERVICE_TO_SOLANA_MIGRATION_ACCOUNT = "Helium Service-Transfers -> Solana Startbestand"
    HELIUM_LEGACY_ASSETS = {"HNT", "IOT", "MOBILE"}
    FAIRSPOT_STAKING_WALLET = "13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"
    KNOWN_JUP_WALLET = "4dCdKKXm1aHzMLFHFz7Cyn6CA14RK7WdYKeAGrHx4fod"
    PRIMARY_SOLANA_WALLET = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
    SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
    SOLANA_RPC_URLS = [
        "https://api.mainnet-beta.solana.com",
        "https://solana-rpc.publicnode.com",
        "https://solana.publicnode.dev",
    ]
    SOLSCAN_PRO_BASE_URL = "https://pro-api.solscan.io/v2.0"
    SOLANA_MINT_SYMBOLS = {
        "JUPYIWRYJFSKUPIHA7HKER8VUTAEFOSYBKEDZNSDVCN": "JUP",
        "HNTYVP6YFM1HG25TN9WGLQM12B8TQMCKNKRDU1OXWUX": "HNT",
        "EPJFWDD5AUFQSSQEM2QN1XZYBAPC8G4WEGGKZWYTDT1V": "USDC",
    }
    EXPECTED_ZERO_SOURCES = {"Bitget", "Pionex"}
    EXPECTED_ZERO_BLOCKER_VALUE_EUR = Decimal("10")
    EXPECTED_ZERO_DUST_INFO_VALUE_EUR = Decimal("1")
    EXPECTED_ZERO_LIVE_DUST_QUANTITY = Decimal("0.000001")
    MIN_POSITION_QUANTITY = Decimal("0.000000000001")
    NON_VALUED_LIVE_RECEIPT_ASSETS = {"LDJUP"}
    V1_CONNECTOR_BASE_URL = os.environ.get("STEUERREPORT_V1_CONNECTOR_BASE_URL", "")
    V1_RECONCILIATION_EVIDENCE = {
        "Bitget": (
            "Historischer V1-Referenzbeleg: docs/88_BITGET_2025_API_DEEP_PROBE_2026-05-09.md; "
            "V1 All-Token-Abgleich als Altbeleg: docs/200_ALL_TOKEN_CURRENT_BALANCE_RECONCILIATION_2026-05-10.md"
        ),
        "Pionex": (
            "Historischer V1-Referenzbeleg: docs/200_ALL_TOKEN_CURRENT_BALANCE_RECONCILIATION_2026-05-10.md; "
            "Pionex Gap-Analyse: docs/146_PIONEX_USDT_PLATFORM_GAP_CURRENT_2026-05-09.md und "
            "docs/167_PIONEX_USDT_FINAL_BLOCKER_AUDIT_2026-05-09.md"
        ),
        "Jup Wallet GmHY...3yu": "Nutzerhinweis 2026-05-25: aktuelle Jup-Wallet, in V2 noch nicht importiert.",
    }
    PRICE_FRESH_DAYS = 3
    PRICE_STALE_DAYS = 14
    CEX_LIVE_CONNECTORS = {"binance", "bitget", "pionex"}
    CEX_REQUIRED_SECRET_KEYS = {
        "binance": ("api_key", "api_secret"),
        "bitget": ("api_key", "api_secret", "passphrase"),
        "pionex": ("api_key", "api_secret"),
    }
    LIVE_STALE_AFTER_DAYS = 3

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._canonical_events_cache: list[object] | None = None
        self._canonical_events_by_id_cache: dict[str, object] | None = None
        self._tax_lots_cache: list[object] | None = None
        self._tax_lines_cache: list[object] | None = None
        self._latest_prices_cache: dict[str, object] | None = None
        self._connector_errors: dict[str, str] = {}
        self._price_lookup_cache: HistoricalPriceLookup | None = None
        self._separation_lots_cache: dict[datetime, list[tuple[object, object]]] = {}
        self._virtual_wallet_cache: dict[datetime, PortfolioVirtualWallet] = {}
        self._solscan_live_prices_usd: dict[str, Decimal] = {}
        self._jupiter_metadata_cache: dict[str, JupiterTokenMetadataCacheItem] | None = None

    def snapshot(self) -> PortfolioSnapshot:
        balances = BalanceLedgerBuilder(self.store).positions()
        account_aliases = build_account_alias_map_for_store(
            self.store,
            [balance.account for balance in balances],
        )
        grouped_balances: dict[tuple[str, str], Decimal] = {}
        for balance in balances:
            account = canonical_account_label(balance.account, account_aliases)
            key = (account, balance.asset)
            grouped_balances[key] = grouped_balances.get(key, Decimal("0")) + balance.quantity
        self._apply_live_balance_anchor(
            grouped_balances,
            account=self.KNOWN_JUP_WALLET,
            connector_id="jup_wallet",
        )
        self._apply_live_balance_anchor(
            grouped_balances,
            account=self.PRIMARY_SOLANA_WALLET,
            connector_id="solana_wallet",
        )
        self._apply_expected_zero_live_anchors(grouped_balances)
        self._apply_binance_live_product_anchor(grouped_balances)
        prices = self._latest_prices()
        positions: list[PortfolioPosition] = []
        excluded_positions: list[PortfolioPosition] = []
        total = Decimal("0")
        excluded_total = Decimal("0")
        missing: set[str] = set()

        for (account, asset), quantity in sorted(grouped_balances.items()):
            if self._is_zero_quantity(quantity):
                continue
            if self._is_transfer_counterparty_account(account) or self._is_current_source_excluded_account(account, asset):
                continue
            price = fiat_price_point(asset) or prices.get(asset)
            if price is None:
                missing.add(asset)
                position = PortfolioPosition(
                    account=account,
                    asset=asset,
                    quantity=quantity,
                    **self._token_metadata_fields(asset),
                )
                if self._is_portfolio_excluded_account(account):
                    excluded_positions.append(position)
                else:
                    positions.append(position)
                continue

            value = quantity * price.price_eur
            position = PortfolioPosition(
                account=account,
                asset=asset,
                quantity=quantity,
                price_eur=price.price_eur,
                value_eur=value,
                price_source=price.source,
                priced_at=price.priced_at,
                **self._token_metadata_fields(asset),
            )
            if self._is_portfolio_excluded_account(account):
                excluded_total += value
                excluded_positions.append(position)
            else:
                total += value
                positions.append(position)

        return PortfolioSnapshot(
            positions=positions,
            total_value_eur=total,
            asset_summary=self._asset_summary(positions),
            account_summary=self._account_summary(positions),
            excluded_account_summary=self._account_summary(excluded_positions),
            excluded_value_eur=excluded_total,
            missing_price_assets=sorted(missing),
            separation_virtual_wallet=self.separation_virtual_wallet(),
            resolved_account_aliases=[
                PortfolioAccountAlias(alias=alias, canonical_account=canonical)
                for alias, canonical in sorted(account_aliases.items())
            ],
            unresolved_truncated_accounts=unresolved_truncated_account_labels(
                [balance.account for balance in balances],
                account_aliases,
            ),
        )

    def as_of_snapshot(self, as_of: str | date | datetime | None = None) -> PortfolioAsOfSnapshot:
        valuation_at = self._normalize_as_of(as_of)
        balances = self._positions_as_of(valuation_at)
        account_aliases = build_account_alias_map_for_store(
            self.store,
            [balance.account for balance in balances],
        )
        grouped_balances: dict[tuple[str, str], Decimal] = {}
        for balance in balances:
            account = canonical_account_label(balance.account, account_aliases)
            key = (account, balance.asset)
            grouped_balances[key] = grouped_balances.get(key, Decimal("0")) + balance.quantity

        prices = self._price_lookup()
        positions: list[PortfolioPosition] = []
        excluded_positions: list[PortfolioPosition] = []
        total = Decimal("0")
        excluded_total = Decimal("0")
        missing: set[str] = set()

        for (account, asset), quantity in sorted(grouped_balances.items()):
            if self._is_zero_quantity(quantity):
                continue
            if self._is_transfer_counterparty_account(account) or self._is_current_source_excluded_account(account, asset):
                continue
            price = prices.at_or_before(asset, valuation_at)
            if price is None:
                missing.add(asset)
                position = PortfolioPosition(
                    account=account,
                    asset=asset,
                    quantity=quantity,
                    **self._token_metadata_fields(asset),
                )
                if self._is_portfolio_excluded_account(account):
                    excluded_positions.append(position)
                else:
                    positions.append(position)
                continue

            value = quantity * price.price_eur
            position = PortfolioPosition(
                account=account,
                asset=asset,
                quantity=quantity,
                price_eur=price.price_eur,
                value_eur=value,
                price_source=price.source,
                priced_at=price.priced_at,
                **self._token_metadata_fields(asset),
            )
            if self._is_portfolio_excluded_account(account):
                excluded_total += value
                excluded_positions.append(position)
            else:
                total += value
                positions.append(position)

        return PortfolioAsOfSnapshot(
            as_of=valuation_at,
            label=f"Portfolio zum Stichtag {valuation_at.date().isoformat()}",
            positions=positions,
            total_value_eur=total,
            asset_summary=self._asset_summary(positions, valuation_at=valuation_at),
            account_summary=self._account_summary(positions),
            excluded_account_summary=self._account_summary(excluded_positions),
            excluded_value_eur=excluded_total,
            missing_price_assets=sorted(missing),
            resolved_account_aliases=[
                PortfolioAccountAlias(alias=alias, canonical_account=canonical)
                for alias, canonical in sorted(account_aliases.items())
            ],
            unresolved_truncated_accounts=unresolved_truncated_account_labels(
                [balance.account for balance in balances],
                account_aliases,
            ),
            methodology=(
                "Summiert Balance-Ledger-Deltas bis einschliesslich Stichtag und "
                "bewertet jede Asset-Position mit dem letzten belegten EUR-Preis "
                "am oder vor dem Stichtag. Datum ohne Uhrzeit wird als "
                "23:59:59.999999 UTC interpretiert. Transfer- und Bridge-"
                "Gegenparteien bleiben in der Historie/Auditspur sichtbar, werden "
                "aber nicht als aktuelle Portfolio-Orte bewertet."
            ),
            transfer_context_note=(
                "Legacy-, Fairspot- und CEX-Gegenparteien sind Transfer-/Bridge-"
                "Nachweise fuer die stichtagsgenaue Historie. Sie werden nicht als "
                "steuerpflichtige Veraeusserung behandelt, solange kein Trade/"
                "Income-Kontext vorliegt."
            ),
        )

    def valuation_audit(self) -> PortfolioValuationAuditReport:
        snapshot = self.snapshot()
        previous_prices = self._previous_prices_by_asset()
        rows: list[PortfolioValuationAuditRow] = []
        previous_total = Decimal("0")
        has_previous = False
        for asset in snapshot.asset_summary:
            previous = previous_prices.get(asset.asset.upper())
            previous_value = None
            price_delta_pct = None
            value_delta = None
            if previous is not None:
                _priced_at, previous_price_eur, previous_source = previous
                previous_value = asset.quantity * previous_price_eur
                previous_total += previous_value
                has_previous = True
                if previous_price_eur:
                    current_price = self._current_price_from_summary(asset)
                    if current_price is not None:
                        price_delta_pct = ((current_price - previous_price_eur) / previous_price_eur) * Decimal("100")
                        value_delta = asset.value_eur - previous_value
            else:
                _priced_at = None
                previous_price_eur = None
                previous_source = None
            rows.append(
                PortfolioValuationAuditRow(
                    asset=asset.asset,
                    quantity=asset.quantity,
                    current_price_eur=self._current_price_from_summary(asset),
                    current_value_eur=asset.value_eur,
                    current_price_source=", ".join(asset.price_sources) if asset.price_sources else None,
                    current_priced_at=asset.priced_at_latest,
                    current_price_status=asset.price_status,
                    previous_price_eur=previous_price_eur,
                    previous_value_eur=previous_value,
                    previous_price_source=previous_source,
                    previous_priced_at=_priced_at,
                    price_delta_pct=price_delta_pct,
                    value_delta_eur=value_delta,
                    accounts=asset.accounts,
                    position_count=asset.position_count,
                    note=self._valuation_audit_note(asset, previous is not None, value_delta),
                )
            )
        return PortfolioValuationAuditReport(
            generated_at=datetime.now(timezone.utc),
            total_value_eur=snapshot.total_value_eur,
            previous_total_value_eur=previous_total if has_previous else None,
            value_delta_eur=(snapshot.total_value_eur - previous_total) if has_previous else None,
            rows=sorted(rows, key=lambda item: abs(item.value_delta_eur or item.current_value_eur), reverse=True),
            methodology=(
                "Read-only Bewertungsanalyse aus aktuellem Portfolio-Snapshot und "
                "vorherigem Preisledger-Punkt je Asset. Mengen stammen aus dem "
                "bestehenden Portfolio-Snapshot; es werden keine Preise, Imports, "
                "FIFO-Lots oder Review-Entscheidungen geschrieben."
            ),
        )

    def source_overview(self) -> PortfolioSourceOverview:
        grouped_positions = self._current_account_asset_positions()
        self._apply_live_balance_anchor(
            grouped_positions,
            account=self.KNOWN_JUP_WALLET,
            connector_id="jup_wallet",
        )
        self._apply_live_balance_anchor(
            grouped_positions,
            account=self.PRIMARY_SOLANA_WALLET,
            connector_id="solana_wallet",
        )
        prices = self._latest_prices()
        positions: list[PortfolioPosition] = []
        total_value = Decimal("0")
        for (account, asset), quantity in sorted(grouped_positions.items()):
            if (
                self._is_zero_quantity(quantity)
                or self._is_transfer_counterparty_account(account)
                or self._is_portfolio_excluded_account(account)
                or self._is_current_source_excluded_account(account, asset)
            ):
                continue
            price = fiat_price_point(asset) or prices.get(asset.upper())
            value = self._portfolio_value(asset, quantity, prices)
            position = PortfolioPosition(
                account=account,
                asset=asset,
                quantity=quantity,
                price_eur=price.price_eur if price is not None else None,
                value_eur=value,
                price_source=price.source if price is not None else None,
                priced_at=price.priced_at if price is not None else None,
                **self._token_metadata_fields(asset),
            )
            positions.append(position)
            total_value += value or Decimal("0")
        account_assets: dict[str, dict[str, dict[str, object]]] = {}
        for position in positions:
            account = self._source_account_label(position.account, position.asset)
            asset = position.asset
            item = account_assets.setdefault(account, {}).setdefault(
                asset,
                {
                    "quantity": Decimal("0"),
                    "value_eur": Decimal("0"),
                    "position_count": 0,
                },
            )
            item["quantity"] = item["quantity"] + position.quantity  # type: ignore[operator]
            item["value_eur"] = item["value_eur"] + (position.value_eur or Decimal("0"))  # type: ignore[operator]
            item["position_count"] = int(item["position_count"]) + 1

        accounts: list[PortfolioSourceAccount] = []
        for account, assets in account_assets.items():
            source_group, source_type = self._source_group_for_account(account, set(assets))
            asset_summary = [
                PortfolioSourceAsset(
                    asset=asset,
                    quantity=item["quantity"],  # type: ignore[arg-type]
                    value_eur=item["value_eur"],  # type: ignore[arg-type]
                    position_count=int(item["position_count"]),
                    **self._token_metadata_fields(asset),
                )
                for asset, item in sorted(
                    assets.items(),
                    key=lambda entry: abs(entry[1]["value_eur"]),  # type: ignore[arg-type]
                    reverse=True,
                )
            ]
            accounts.append(
                PortfolioSourceAccount(
                    account=account,
                    source_group=source_group,
                    source_type=source_type,
                    value_eur=sum((item.value_eur for item in asset_summary), Decimal("0")),
                    position_count=sum((item.position_count for item in asset_summary), 0),
                    assets=len(asset_summary),
                    current_status=self._source_current_status(source_group),
                    note=self._source_note(source_group, account),
                    asset_summary=asset_summary,
                )
            )

        if not any(account.account == self.KNOWN_JUP_WALLET for account in accounts):
            accounts.append(
                PortfolioSourceAccount(
                    account=self.KNOWN_JUP_WALLET,
                    source_group="Jup Wallet GmHY...3yu",
                    source_type="solana_wallet",
                    value_eur=Decimal("0"),
                    position_count=0,
                    assets=0,
                    current_status="known_wallet_missing_import",
                    note=(
                        "Vom Nutzer als aktuelle Jup-Wallet benannt; in Raw-/Canonical-"
                        "Daten bisher nicht gefunden."
                    ),
                )
            )

        grouped: dict[str, list[PortfolioSourceAccount]] = {}
        for account in accounts:
            grouped.setdefault(account.source_group, []).append(account)

        groups: list[PortfolioSourceGroup] = []
        for source_group, group_accounts in grouped.items():
            source_type = group_accounts[0].source_type
            asset_totals: dict[str, dict[str, object]] = {}
            for account in group_accounts:
                for asset in account.asset_summary:
                    item = asset_totals.setdefault(
                        asset.asset,
                        {
                            "quantity": Decimal("0"),
                            "value_eur": Decimal("0"),
                            "position_count": 0,
                        },
                    )
                    item["quantity"] = item["quantity"] + asset.quantity  # type: ignore[operator]
                    item["value_eur"] = item["value_eur"] + asset.value_eur  # type: ignore[operator]
                    item["position_count"] = int(item["position_count"]) + asset.position_count
            group_asset_summary = [
                PortfolioSourceAsset(
                    asset=asset,
                    quantity=item["quantity"],  # type: ignore[arg-type]
                    value_eur=item["value_eur"],  # type: ignore[arg-type]
                    position_count=int(item["position_count"]),
                    **self._token_metadata_fields(asset),
                )
                for asset, item in sorted(
                    asset_totals.items(),
                    key=lambda entry: abs(entry[1]["value_eur"]),  # type: ignore[arg-type]
                    reverse=True,
                )
            ]
            groups.append(
                PortfolioSourceGroup(
                    source_group=source_group,
                    source_type=source_type,
                    value_eur=sum((account.value_eur for account in group_accounts), Decimal("0")),
                    account_count=len(group_accounts),
                    position_count=sum((account.position_count for account in group_accounts), 0),
                    assets=len(group_asset_summary),
                    current_status=self._source_current_status(source_group),
                    note=self._source_note(source_group, None),
                    accounts=sorted(
                        group_accounts,
                        key=lambda item: abs(item.value_eur),
                        reverse=True,
                    ),
                    asset_summary=group_asset_summary,
                )
            )

        return PortfolioSourceOverview(
            total_value_eur=total_value,
            groups=sorted(groups, key=lambda item: abs(item.value_eur), reverse=True),
            accounts=sorted(accounts, key=lambda item: abs(item.value_eur), reverse=True),
            methodology=(
                "Gruppiert aktuelle Portfolio-Positionen nach lesbarer Quelle. "
                "Binance-Unterkonten wie Spot/Funding werden Binance zugeordnet. "
                "Aktuelle Solana-Wallet-Werte stammen aus gespeicherten "
                "Live-Snapshots, bevorzugt Solscan. Helium-Legacy- und "
                "Service-Wallets werden nicht mehr als aktuelle Quellen "
                "ausgewiesen; ihre Originalevents bleiben fuer FIFO erhalten."
            ),
        )

    def token_risk_report(
        self,
        risk_status: str = "all",
        min_value_eur: Decimal = Decimal("1"),
    ) -> PortfolioTokenRiskReport:
        normalized_risk = str(risk_status or "all").strip().lower()
        allowed = {"all", "spam_review", "review", "unverified_plausible", "verified", "unknown"}
        if normalized_risk not in allowed:
            raise ValueError("unsupported_risk_status")
        threshold = max(Decimal(str(min_value_eur)), Decimal("0"))
        snapshot = self.snapshot()
        positions_by_asset: dict[str, list[PortfolioPosition]] = {}
        for position in snapshot.positions:
            positions_by_asset.setdefault(position.asset, []).append(position)
        rows: list[PortfolioTokenRiskRow] = []
        counts = {
            "spam_review": 0,
            "review": 0,
            "unverified_plausible": 0,
            "verified": 0,
        }
        for asset in snapshot.asset_summary:
            risk = str(asset.token_risk_status or "unknown")
            if risk in counts:
                counts[risk] += 1
            if normalized_risk != "all" and risk != normalized_risk:
                continue
            if abs(asset.value_eur) < threshold:
                continue
            metadata = self._token_metadata_for_asset(asset.asset)
            rows.append(
                PortfolioTokenRiskRow(
                    asset=asset.asset,
                    token_name=asset.token_name,
                    token_symbol=asset.token_symbol,
                    token_mint=asset.token_mint,
                    token_verified=asset.token_verified,
                    token_risk_status=risk,
                    quantity=asset.quantity,
                    value_eur=asset.value_eur,
                    position_count=asset.position_count,
                    accounts=asset.accounts,
                    price_status=asset.price_status,
                    priced_at_latest=asset.priced_at_latest,
                    discovered_sources=metadata.discovered_sources if metadata is not None else [],
                    positions=positions_by_asset.get(asset.asset, []),
                )
            )
        return PortfolioTokenRiskReport(
            generated_at=datetime.now(timezone.utc),
            risk_status=normalized_risk,
            min_value_eur=threshold,
            total_value_eur=sum((row.value_eur for row in rows), Decimal("0")),
            rows_count=len(rows),
            spam_review_count=counts["spam_review"],
            review_count=counts["review"],
            unverified_plausible_count=counts["unverified_plausible"],
            verified_count=counts["verified"],
            rows=sorted(rows, key=lambda row: abs(row.value_eur), reverse=True),
            methodology=(
                "Read-only Portfolio-Token-Risiko aus dem aktuellen Portfolio-Snapshot "
                "und Jupiter Metadata Cache. Der Report filtert nur Anzeigezeilen; "
                "er schreibt keine Ledger-, FIFO-, Preis-, Import- oder Steuerdaten."
            ),
        )

    def reconciliation_report(self) -> PortfolioReconciliationReport:
        overview = self.source_overview()
        generated_at = datetime.now(timezone.utc)
        rows: list[PortfolioReconciliationRow] = []
        expected_zero_value = Decimal("0")
        live_unverified_value = Decimal("0")
        missing_wallets: list[str] = []
        prices = self._latest_prices()

        for group in overview.groups:
            if group.current_status == "known_wallet_missing_import":
                external_balances = self._external_live_balances("jup_wallet")
                missing_wallets.extend(account.account for account in group.accounts)
                if external_balances:
                    ledger_assets = self._ledger_assets_for_account(self.KNOWN_JUP_WALLET, prices)
                    for asset, quantity in sorted(external_balances.items()):
                        ledger_asset = ledger_assets.get(asset)
                        ledger_quantity = ledger_asset.quantity if ledger_asset is not None else Decimal("0")
                        ledger_value = ledger_asset.value_eur if ledger_asset is not None else Decimal("0")
                        external_value = self._portfolio_value(asset, quantity, prices)
                        delta_quantity = quantity - ledger_quantity
                        delta_value = external_value - ledger_value if external_value is not None else None
                        reconciled = self._is_live_delta_reconciled(delta_quantity, delta_value)
                        rows.append(
                            PortfolioReconciliationRow(
                                source_group=group.source_group,
                                source_type=group.source_type,
                                asset=asset,
                                ledger_quantity=ledger_quantity,
                                ledger_value_eur=ledger_value,
                                external_quantity=quantity,
                                external_value_eur=external_value,
                                delta_quantity=delta_quantity,
                                delta_value_eur=delta_value,
                                status=(
                                    "live_anchor_reconciled"
                                    if reconciled
                                    else (
                                        "wallet_history_partially_imported"
                                        if ledger_quantity != 0
                                        else "missing_wallet_history_live_balance_found"
                                    )
                                ),
                                severity="info" if reconciled else "blocker",
                                evidence=self.V1_RECONCILIATION_EVIDENCE.get(group.source_group, group.note or ""),
                                next_action=(
                                    "Live-Anker und V2-Ledger stimmen innerhalb der Reconciliation-Toleranz ueberein."
                                    if reconciled
                                    else (
                                        "Solana-RPC Live-Snapshot ist vorhanden; jetzt muss die Transaktionshistorie "
                                        "fuer diese Wallet importiert und in Canonical Events ueberfuehrt werden."
                                    )
                                ),
                            )
                        )
                else:
                    rows.append(
                        PortfolioReconciliationRow(
                            source_group=group.source_group,
                            source_type=group.source_type,
                            asset=None,
                            ledger_value_eur=group.value_eur,
                            status="missing_live_wallet_import",
                            severity="blocker",
                            evidence=self.V1_RECONCILIATION_EVIDENCE.get(group.source_group, group.note or ""),
                            next_action=(
                                "Solana-RPC Live-Snapshot und Transaktionshistorie fuer diese Wallet "
                                "importieren; danach Bestand und Anschaffungskette gegen V2-Ledger pruefen."
                            ),
                        )
                    )
                continue

            if group.source_group in self.EXPECTED_ZERO_SOURCES:
                expected_zero_value += group.value_eur
                external_balances = self._external_live_balances(group.source_group.lower())
                ledger_assets = {item.asset: item for item in group.asset_summary}
                all_assets = sorted(set(ledger_assets) | set(external_balances))
                if not all_assets:
                    all_assets = ["__empty__"]
                for asset_name in all_assets:
                    ledger_asset = ledger_assets.get(asset_name)
                    ledger_quantity = ledger_asset.quantity if ledger_asset is not None else Decimal("0")
                    ledger_value = ledger_asset.value_eur if ledger_asset is not None else Decimal("0")
                    external_quantity = external_balances.get(asset_name)
                    external_value = self._portfolio_value(asset_name, external_quantity, prices)
                    delta_quantity = None if external_quantity is None else external_quantity - ledger_quantity
                    delta_value = None if external_value is None else external_value - ledger_value
                    value_for_severity = delta_value if delta_value is not None else -ledger_value
                    reconciled = self._is_live_delta_reconciled(delta_quantity, delta_value)
                    dust_residual = abs(value_for_severity) < self.EXPECTED_ZERO_DUST_INFO_VALUE_EUR
                    if reconciled:
                        severity = "info"
                        status = "live_anchor_reconciled"
                        next_action = (
                            "Live-Anker und V2-Ledger stimmen innerhalb der Reconciliation-Toleranz ueberein."
                        )
                    elif dust_residual:
                        severity = "info"
                        status = (
                            "dust_live_anchor_delta"
                            if external_quantity is not None
                            else "dust_expected_live_zero"
                        )
                        next_action = (
                            "Nur Dust-/Rundungsrest unter 1 EUR; FIFO-Spur bleibt erhalten, "
                            "aber kein operativer Live-Blocker."
                        )
                    else:
                        severity = (
                            "blocker"
                            if abs(value_for_severity) >= self.EXPECTED_ZERO_BLOCKER_VALUE_EUR
                            else "warning"
                        )
                        status = (
                            "mismatch_live_anchor"
                            if external_quantity is not None
                            else "mismatch_expected_live_zero"
                        )
                        next_action = (
                            "V2-Connector-/Export-Abgleich nachziehen und die fehlende "
                            "historische Abgangs-/Produktbuchung belegen; nicht als steuerwirksamen "
                            "Verkauf erfinden."
                        )
                        if (
                            group.source_group == "Bitget"
                            and asset_name == "USDT"
                            and external_quantity is not None
                            and abs(external_quantity) <= self.EXPECTED_ZERO_LIVE_DUST_QUANTITY
                            and severity == "warning"
                        ):
                            severity = "info"
                            status = "complete_export_strategy_reference_live_zero"
                            next_action = (
                                "Kompletter Bitget-2024-Export liegt vor. Strategy.csv belegt "
                                "die Strategy-Kontexte bis 2024-12-20 19:34:28 UTC+8; aktueller "
                                "API-Livebestand ist praktisch null. Keine kuenstliche "
                                "Ausbuchung erzeugen und Strategy.csv nur als Evidence-Kontext "
                                "gegen Doppelzaehlung fuehren."
                            )
                    evidence = self.V1_RECONCILIATION_EVIDENCE.get(group.source_group, group.note or "")
                    if status == "complete_export_strategy_reference_live_zero":
                        evidence = (
                            f"{evidence}; V2 Beleg: "
                            "docs/347_BITGET_USDT_STRATEGY_RESIDUAL_WARNING_2026-05-30.md"
                        )
                    rows.append(
                        PortfolioReconciliationRow(
                            source_group=group.source_group,
                            source_type=group.source_type,
                            asset=None if asset_name == "__empty__" else asset_name,
                            ledger_quantity=None if asset_name == "__empty__" else ledger_quantity,
                            ledger_value_eur=ledger_value,
                            external_quantity=external_quantity,
                            external_value_eur=external_value,
                            delta_quantity=delta_quantity,
                            delta_value_eur=delta_value,
                            status=status,
                            severity=severity,
                            evidence=evidence,
                            next_action=next_action,
                        )
                    )
                continue

            live_unverified_value += group.value_eur
            rows.append(
                PortfolioReconciliationRow(
                    source_group=group.source_group,
                    source_type=group.source_type,
                    asset=None,
                    ledger_value_eur=group.value_eur,
                    status="ledger_current_needs_live_anchor",
                    severity="info",
                    evidence=group.note or "V2-Ledgerbestand; Live-Connector-Abgleich noch nicht in V2 persistiert.",
                    next_action=(
                        "V2-Connectoren oder belegte Export-/On-chain-Artefakte als Read-Only-"
                        "Reconciliation-Anker ausfuehren und Ergebnis je Asset speichern."
                    ),
                )
            )

        return PortfolioReconciliationReport(
            generated_at=generated_at,
            total_ledger_value_eur=overview.total_value_eur,
            expected_zero_ledger_value_eur=expected_zero_value,
            live_unverified_ledger_value_eur=live_unverified_value,
            missing_wallets=(
                sorted(set(missing_wallets))
                if any(row.source_group == "Jup Wallet GmHY...3yu" and row.severity == "blocker" for row in rows)
                else []
            ),
            rows=sorted(
                rows,
                key=lambda item: (
                    {"blocker": 0, "warning": 1, "info": 2}.get(item.severity, 9),
                    -abs(item.ledger_value_eur),
                    item.source_group,
                    item.asset or "",
                ),
            ),
            connector_actions=[
                "CEX Balance Preview aus V1 fuer Binance, Bitget und Pionex nach V2 migrieren.",
                "Binance Spot + Simple Earn Flexible + Locked Earn getrennt als Live-Anker speichern.",
                "Bitget/Pionex Live-Null gegen V2-Ledger-Restbestand pruefen und historische Abgaenge belegen.",
                f"Solana Wallet {self.KNOWN_JUP_WALLET} per RPC und Historienimport aufnehmen.",
                "Helium Legacy Main-Wallet und Staking-Roundtrips gegen Transferkette dokumentieren.",
            ],
            methodology=(
                "Vergleicht den aktuellen V2-Balance-Ledger mit belegten V1-Live-Abgleichankern. "
                "Bei Quellen mit erwartetem Live-Nullbestand wird die Differenz als Reconciliation-"
                "Fehler ausgewiesen. Es wird keine steuerliche Gegenbuchung automatisch erzeugt; "
                "Korrekturen muessen aus API-/Export-/Onchain-Belegen oder expliziten Review-"
                "Entscheidungen stammen."
            ),
        )

    def _is_live_delta_reconciled(
        self,
        delta_quantity: Decimal | None,
        delta_value: Decimal | None,
    ) -> bool:
        if delta_quantity is None:
            return False
        if abs(delta_quantity) <= Decimal("0.00000001"):
            return True
        return delta_value is not None and abs(delta_value) < Decimal("5")

    def _external_live_balances(self, connector_id: str) -> dict[str, Decimal]:
        stored = self._stored_live_balance_snapshots(connector_id)
        if stored:
            return stored
        if connector_id == "jup_wallet":
            return self._v1_solana_wallet_balances(self.KNOWN_JUP_WALLET)
        return self._v1_cex_live_balances(connector_id)

    def _stored_live_balance_snapshots(self, connector_id: str) -> dict[str, Decimal]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, sum(quantity)
                from portfolio_live_balance_snapshots
                where connector_id = ?
                  and fetched_at = (
                    select max(fetched_at)
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                  )
                group by asset
                order by asset
                """,
                [connector_id, connector_id],
            ).fetchall()
        return {str(row[0]).upper(): row[1] or Decimal("0") for row in rows}

    def _apply_live_balance_anchor(
        self,
        grouped_balances: dict[tuple[str, str], Decimal],
        *,
        account: str,
        connector_id: str,
    ) -> None:
        if not self._connector_live_snapshot_is_current(connector_id):
            return
        live_balances = self._stored_live_balance_snapshots(connector_id)
        if not live_balances:
            return
        ledger_assets = {asset for current_account, asset in grouped_balances if current_account == account}
        prices = self._latest_prices()
        for key in list(grouped_balances):
            if key[0] == account:
                del grouped_balances[key]
        for asset, quantity in live_balances.items():
            if (
                asset not in ledger_assets
                and asset not in self.NON_VALUED_LIVE_RECEIPT_ASSETS
                and fiat_price_point(asset) is None
                and prices.get(asset.upper()) is None
            ):
                continue
            grouped_balances[(account, asset)] = quantity

    def _apply_expected_zero_live_anchors(
        self,
        grouped_balances: dict[tuple[str, str], Decimal],
    ) -> None:
        for account, connector_id in (("bitget", "bitget"), ("pionex", "pionex")):
            self._apply_live_balance_anchor(
                grouped_balances,
                account=account,
                connector_id=connector_id,
            )

    def _apply_binance_live_product_anchor(
        self,
        grouped_balances: dict[tuple[str, str], Decimal],
    ) -> None:
        if not self._connector_live_snapshot_is_current("binance"):
            return
        snapshots = self._latest_live_balance_snapshot_rows("binance")
        if not snapshots:
            return
        for account, asset in list(grouped_balances):
            source_group, _source_type = self._source_group_for_account(account, {asset})
            if source_group == "Binance":
                del grouped_balances[(account, asset)]
        for snapshot in snapshots:
            if snapshot["asset"] in self.NON_VALUED_LIVE_RECEIPT_ASSETS:
                continue
            account = self._live_snapshot_account_label(snapshot)
            key = (account, snapshot["asset"])
            grouped_balances[key] = grouped_balances.get(key, Decimal("0")) + snapshot["quantity"]

    def _connector_live_snapshot_is_current(self, connector_id: str) -> bool:
        latest_at = self._latest_live_snapshot_at(connector_id)
        if latest_at is None:
            return False
        if connector_id not in self.CEX_LIVE_CONNECTORS:
            return True
        comparable = latest_at
        if comparable.tzinfo is None:
            comparable = comparable.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - comparable).days <= self.LIVE_STALE_AFTER_DAYS

    def _latest_live_balance_snapshot_rows(self, connector_id: str) -> list[dict[str, object]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, quantity, account_type, product_id, position_id, event_type
                from portfolio_live_balance_snapshots
                where connector_id = ?
                  and fetched_at = (
                    select max(fetched_at)
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                  )
                order by asset, account_type, product_id, position_id, event_type
                """,
                [connector_id, connector_id],
            ).fetchall()
        return [
            {
                "asset": str(asset).upper(),
                "quantity": quantity or Decimal("0"),
                "account_type": account_type,
                "product_id": product_id,
                "position_id": position_id,
                "event_type": event_type,
            }
            for asset, quantity, account_type, product_id, position_id, event_type in rows
        ]

    def _live_snapshot_account_label(self, snapshot: dict[str, object]) -> str:
        account_type = str(snapshot.get("account_type") or "spot").strip().lower()
        product_id = str(snapshot.get("product_id") or "").strip()
        event_type = str(snapshot.get("event_type") or "").strip().lower()
        if account_type == "spot":
            return "Binance Spot"
        if account_type == "funding":
            return "Binance Funding"
        if account_type == "simple_earn_flexible":
            return f"Binance Earn Flexible {product_id}".strip()
        if account_type == "simple_earn_locked":
            if event_type == "earn_accrued_reward_snapshot":
                return f"Binance Earn Rewards {product_id}".strip()
            return f"Binance Earn Locked {product_id}".strip()
        return f"Binance {account_type.replace('_', ' ').title()} {product_id}".strip()

    def _ledger_assets_for_account(
        self,
        account: str,
        prices: dict[str, object],
    ) -> dict[str, PortfolioSourceAsset]:
        assets: dict[str, PortfolioSourceAsset] = {}
        for (ledger_account, asset), quantity in self._current_account_asset_positions().items():
            if ledger_account != account or quantity == 0:
                continue
            value = self._portfolio_value(asset, quantity, prices) or Decimal("0")
            assets[asset] = PortfolioSourceAsset(
                asset=asset,
                quantity=quantity,
                value_eur=value,
                position_count=1,
            )
        return assets

    def refresh_reconciliation_snapshots(
        self,
        connectors: list[str] | None = None,
    ) -> PortfolioReconciliationRefreshResult:
        connector_ids = [
            item.lower()
            for item in (connectors or ["binance", "bitget", "pionex", "jup_wallet", "solana_wallet"])
            if item.strip()
        ]
        fetched_at = datetime.now(timezone.utc)
        snapshots: list[PortfolioLiveBalanceSnapshot] = []
        connector_results: list[PortfolioReconciliationRefreshConnectorResult] = []
        for connector_id in connector_ids:
            previous_snapshot_at = self._latest_live_snapshot_at(connector_id)
            connector_snapshots: list[PortfolioLiveBalanceSnapshot] = []
            missing_configuration = False
            if connector_id == "jup_wallet":
                missing_configuration = not bool(self.V1_CONNECTOR_BASE_URL or self._solscan_api_key())
                balances = self._v1_solana_wallet_balances(self.KNOWN_JUP_WALLET)
                if not balances:
                    balances = self._solscan_wallet_balances(self.KNOWN_JUP_WALLET)
            elif connector_id == "solana_wallet":
                missing_configuration = not bool(self.V1_CONNECTOR_BASE_URL or self._solscan_api_key())
                balances = self._v1_solana_wallet_balances(self.PRIMARY_SOLANA_WALLET)
                if not balances:
                    balances = self._solscan_wallet_balances(self.PRIMARY_SOLANA_WALLET)
            else:
                missing_configuration = not self._cex_credentials_configured(connector_id)
                balances = self._v1_cex_live_balance_snapshots(connector_id, fetched_at)
                if not balances:
                    balances = self._v1_cex_live_balances(connector_id)
            if connector_id in {"jup_wallet", "solana_wallet"}:
                self._store_solscan_live_prices(fetched_at)
            if isinstance(balances, list):
                connector_snapshots.extend(balances)
            else:
                for asset, quantity in sorted(balances.items()):
                    connector_snapshots.append(
                        PortfolioLiveBalanceSnapshot(
                            snapshot_id=f"{connector_id}:{asset}:{fetched_at.isoformat()}",
                            connector_id=connector_id,
                            asset=asset,
                            quantity=quantity,
                            source=self._snapshot_source_for_connector(connector_id),
                            fetched_at=fetched_at,
                        )
                    )
            snapshots.extend(connector_snapshots)
            connector_results.append(
                PortfolioReconciliationRefreshConnectorResult(
                    connector_id=connector_id,
                    status=(
                        "refreshed"
                        if connector_snapshots
                        else "connector_error"
                        if self._connector_errors.get(connector_id)
                        else "missing_configuration"
                        if missing_configuration
                        else "empty_response"
                    ),
                    snapshots=len(connector_snapshots),
                    previous_snapshot_at=previous_snapshot_at,
                    message=(
                        f"{len(connector_snapshots)} Live-Snapshot(s) gespeichert."
                        if connector_snapshots
                        else self._connector_errors[connector_id]
                        if self._connector_errors.get(connector_id)
                        else "Connector ist nicht konfiguriert."
                        if missing_configuration
                        else "Connector lieferte keine verwertbaren Live-Bestaende; vorhandene Snapshots bleiben erhalten."
                    ),
                )
            )
        self._replace_live_balance_snapshots(snapshots)
        return PortfolioReconciliationRefreshResult(
            fetched_at=fetched_at,
            connectors=connector_ids,
            imported_snapshots=len(snapshots),
            snapshots=snapshots,
            connector_results=connector_results,
            report=self.reconciliation_report(),
        )

    def _latest_live_snapshot_at(self, connector_id: str) -> datetime | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select max(fetched_at)
                from portfolio_live_balance_snapshots
                where connector_id = ?
                """,
                [connector_id],
            ).fetchone()
        if row is None:
            return None
        return row[0]

    def _snapshot_source_for_connector(self, connector_id: str) -> str:
        endpoint = (
            "solscan_pro:/account/portfolio"
            if connector_id in {"jup_wallet", "solana_wallet"}
            else (
            "/api/v1/connectors/solana/balance-snapshot"
            if connector_id == "jup_wallet"
            else "/api/v1/connectors/cex/balances-preview"
            )
        )
        if connector_id in {"jup_wallet", "solana_wallet"}:
            return endpoint
        return f"v1_bridge:{self.V1_CONNECTOR_BASE_URL.rstrip('/')}{endpoint}"

    def import_jup_wallet_history(
        self,
        request: PortfolioWalletHistoryImportRequest | None = None,
    ) -> PortfolioWalletHistoryImportResult:
        request = request or PortfolioWalletHistoryImportRequest()
        wallet_address = request.wallet_address or self.KNOWN_JUP_WALLET
        preview = self._v1_solana_wallet_history(
            wallet_address=wallet_address,
            before_signature=request.before_signature,
            max_signatures=request.max_signatures,
            max_transactions=request.max_transactions,
            aggregate_jupiter=request.aggregate_jupiter,
            jupiter_window_seconds=request.jupiter_window_seconds,
        )
        rows = preview.get("rows", [])
        if not isinstance(rows, list):
            rows = []
        source = "solana_rpc"
        filename = f"v1_solana_rpc_{wallet_address}_{request.max_signatures}_{request.before_signature or 'latest'}.json"
        file_hash = "sha256:" + hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        existing = self.store.get_import_batch_by_file_hash(source, file_hash)
        batch = CsvRawImporter(self.store).import_rows(
            source=source,
            filename=filename,
            file_hash=file_hash,
            rows=rows,
        )
        pipeline = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        warnings = preview.get("warnings", [])
        return PortfolioWalletHistoryImportResult(
            wallet_address=wallet_address,
            source=source,
            batch_id=batch.batch_id,
            filename=filename,
            fetched_rows=len(rows),
            signature_count=int(preview.get("signature_count", 0) or 0),
            first_signature=preview.get("first_signature") if isinstance(preview.get("first_signature"), str) else None,
            last_signature=preview.get("last_signature") if isinstance(preview.get("last_signature"), str) else None,
            duplicate_batch=existing is not None,
            normalized_events=pipeline.normalized_events,
            skipped_raw_objects=pipeline.skipped_raw_objects,
            pipeline=pipeline.model_dump(),
            warnings=[item for item in warnings if isinstance(item, dict)],
        )

    def _v1_solana_wallet_history(
        self,
        *,
        wallet_address: str,
        before_signature: str | None,
        max_signatures: int,
        max_transactions: int,
        aggregate_jupiter: bool,
        jupiter_window_seconds: int,
    ) -> dict[str, object]:
        # The V1 wallet-preview endpoint can block for minutes on public RPC
        # transaction detail calls. For V2 imports we use a small direct RPC
        # mapper and keep V1 as a conceptual compatibility source.
        return self._solana_wallet_history_direct(
            wallet_address=wallet_address,
            before_signature=before_signature,
            max_signatures=min(max_signatures, max_transactions),
            warning="using_v2_direct_rpc_history_import",
        )
        if not self.V1_CONNECTOR_BASE_URL:
            return {"rows": [], "warnings": [{"code": "v1_bridge_disabled", "message": "V1 bridge URL is empty."}]}
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    f"{self.V1_CONNECTOR_BASE_URL.rstrip('/')}/api/v1/connectors/solana/wallet-preview",
                    json={
                        "wallet_address": wallet_address,
                        "before_signature": before_signature,
                        "timeout_seconds": 20,
                        "max_signatures": max_signatures,
                        "max_transactions": max_transactions,
                        "aggregate_jupiter": aggregate_jupiter,
                        "jupiter_window_seconds": jupiter_window_seconds,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            return self._solana_wallet_history_direct(
                wallet_address=wallet_address,
                before_signature=before_signature,
                max_signatures=min(max_signatures, max_transactions),
                warning=f"v1_solana_wallet_preview_failed: {exc}",
            )
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise RuntimeError(f"v1_solana_wallet_preview_error: {payload.get('errors')}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError("v1_solana_wallet_preview_invalid_payload")
        return data

    def _solana_wallet_history_direct(
        self,
        *,
        wallet_address: str,
        before_signature: str | None,
        max_signatures: int,
        warning: str,
    ) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        warnings = [{"code": "v1_bridge_fallback_direct_rpc", "message": warning}]
        signatures = self._solana_rpc(
            "getSignaturesForAddress",
            [
                wallet_address,
                {
                    "limit": min(max(max_signatures, 1), 1000),
                    **({"before": before_signature} if before_signature else {}),
                },
            ],
            timeout_seconds=30,
        )
        if not isinstance(signatures, list):
            raise RuntimeError("solana_direct_signatures_invalid_payload")
        signature_values = [
            str(item.get("signature"))
            for item in signatures
            if isinstance(item, dict) and item.get("signature")
        ]
        for signature in signature_values:
            try:
                tx = self._solana_rpc(
                    "getTransaction",
                    [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                    timeout_seconds=30,
                )
            except Exception as exc:
                warnings.append({"code": "solana_direct_transaction_failed", "message": f"{signature}: {exc}"})
                continue
            if not isinstance(tx, dict):
                warnings.append({"code": "solana_direct_transaction_missing", "message": signature})
                continue
            rows.extend(self._solana_transaction_rows(wallet_address, signature, tx))
        return {
            "wallet_address": wallet_address,
            "rpc_url": self.SOLANA_RPC_URL,
            "signature_count": len(signature_values),
            "first_signature": signature_values[0] if signature_values else None,
            "last_signature": signature_values[-1] if signature_values else None,
            "count": len(rows),
            "rows": rows,
            "warnings": warnings,
        }

    def _solana_rpc(self, method: str, params: list[object], timeout_seconds: int) -> object:
        errors: list[str] = []
        with httpx.Client(timeout=timeout_seconds) as client:
            for rpc_url in self.SOLANA_RPC_URLS:
                try:
                    response = client.post(
                        rpc_url,
                        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("error"):
                        errors.append(f"{rpc_url}: {payload['error']}")
                        continue
                    return payload.get("result") if isinstance(payload, dict) else None
                except Exception as exc:
                    errors.append(f"{rpc_url}: {exc}")
                    continue
        raise RuntimeError("; ".join(errors[-3:]))

    def _solana_transaction_rows(
        self,
        wallet_address: str,
        signature: str,
        tx: dict[str, object],
    ) -> list[dict[str, object]]:
        block_time = tx.get("blockTime")
        timestamp = datetime.fromtimestamp(int(block_time), timezone.utc).isoformat() if block_time else ""
        meta = tx.get("meta") if isinstance(tx.get("meta"), dict) else {}
        transaction = tx.get("transaction") if isinstance(tx.get("transaction"), dict) else {}
        message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
        account_keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
        wallet_index = self._solana_wallet_account_index(account_keys, wallet_address)
        rows: list[dict[str, object]] = []
        if wallet_index is not None:
            pre_balances = meta.get("preBalances") if isinstance(meta.get("preBalances"), list) else []
            post_balances = meta.get("postBalances") if isinstance(meta.get("postBalances"), list) else []
            if wallet_index < len(pre_balances) and wallet_index < len(post_balances):
                delta_lamports = Decimal(str(post_balances[wallet_index])) - Decimal(str(pre_balances[wallet_index]))
                if delta_lamports:
                    rows.append(
                        self._solana_row(
                            timestamp=timestamp,
                            signature=signature,
                            wallet_address=wallet_address,
                            event_type="sol_transfer",
                            asset="SOL",
                            delta=delta_lamports / Decimal("1000000000"),
                        )
                    )
        token_deltas = self._solana_token_deltas(
            pre=meta.get("preTokenBalances") if isinstance(meta.get("preTokenBalances"), list) else [],
            post=meta.get("postTokenBalances") if isinstance(meta.get("postTokenBalances"), list) else [],
            wallet_address=wallet_address,
        )
        for asset, delta in sorted(token_deltas.items()):
            if delta:
                rows.append(
                    self._solana_row(
                        timestamp=timestamp,
                        signature=signature,
                        wallet_address=wallet_address,
                        event_type="token_transfer",
                        asset=asset,
                        delta=delta,
                    )
                )
        return rows

    def _solana_wallet_account_index(self, account_keys: list[object], wallet_address: str) -> int | None:
        for index, key in enumerate(account_keys):
            if isinstance(key, str) and key == wallet_address:
                return index
            if isinstance(key, dict) and str(key.get("pubkey") or "") == wallet_address:
                return index
        return None

    def _solana_token_deltas(
        self,
        *,
        pre: list[object],
        post: list[object],
        wallet_address: str,
    ) -> dict[str, Decimal]:
        pre_balances = self._solana_token_balance_map(pre, wallet_address)
        post_balances = self._solana_token_balance_map(post, wallet_address)
        result: dict[str, Decimal] = {}
        for key in sorted(set(pre_balances) | set(post_balances)):
            asset = self.SOLANA_MINT_SYMBOLS.get(key, key[:6] + "..." + key[-4:])
            result[asset] = result.get(asset, Decimal("0")) + post_balances.get(key, Decimal("0")) - pre_balances.get(key, Decimal("0"))
        return result

    def _solana_token_balance_map(self, balances: list[object], wallet_address: str) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for item in balances:
            if not isinstance(item, dict):
                continue
            owner = str(item.get("owner") or "")
            if owner and owner != wallet_address:
                continue
            mint = str(item.get("mint") or "").upper()
            amount = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
            quantity = self._decimal_from_payload(amount.get("uiAmountString") if isinstance(amount, dict) else "0")
            if mint:
                result[mint] = result.get(mint, Decimal("0")) + quantity
        return result

    def _solana_row(
        self,
        *,
        timestamp: str,
        signature: str,
        wallet_address: str,
        event_type: str,
        asset: str,
        delta: Decimal,
    ) -> dict[str, object]:
        return {
            "timestamp_utc": timestamp,
            "event_type": event_type,
            "asset": asset,
            "quantity": abs(delta).normalize().to_eng_string(),
            "side": "in" if delta > 0 else "out",
            "tx_id": signature,
            "wallet_address": wallet_address,
        }

    def _v1_solana_wallet_balances(self, wallet_address: str) -> dict[str, Decimal]:
        if not self.V1_CONNECTOR_BASE_URL:
            return {}
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    f"{self.V1_CONNECTOR_BASE_URL.rstrip('/')}/api/v1/connectors/solana/balance-snapshot",
                    json={
                        "wallet_address": wallet_address,
                        "timeout_seconds": 20,
                        "max_tokens": 500,
                        "include_prices": True,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return {}
        balances: dict[str, Decimal] = {}
        sol_balance = self._decimal_from_payload(data.get("sol_balance"))
        if sol_balance > 0:
            balances["SOL"] = sol_balance
        tokens = data.get("tokens")
        if isinstance(tokens, list):
            for row in tokens:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or row.get("asset") or "").strip().upper()
                if not symbol:
                    continue
                balances[symbol] = balances.get(symbol, Decimal("0")) + self._decimal_from_payload(row.get("quantity"))
        return {asset: quantity for asset, quantity in balances.items() if quantity != 0}

    def _decimal_from_payload(self, value: object) -> Decimal:
        try:
            return Decimal(str(value or "0"))
        except Exception:
            return Decimal("0")

    def _v1_cex_live_balances(self, connector_id: str) -> dict[str, Decimal]:
        snapshots = self._v1_cex_live_balance_snapshots(connector_id, datetime.now(timezone.utc))
        balances: dict[str, Decimal] = {}
        for snapshot in snapshots:
            balances[snapshot.asset] = balances.get(snapshot.asset, Decimal("0")) + snapshot.quantity
        return balances

    def _cex_credentials_configured(self, connector_id: str) -> bool:
        required = self.CEX_REQUIRED_SECRET_KEYS.get(connector_id, ())
        if not required:
            return False
        return all(
            bool(resolve_secret_value(self.store, f"secret.cex.{connector_id}.{suffix}"))
            for suffix in required
        )

    def _v1_cex_live_balance_snapshots(
        self,
        connector_id: str,
        fetched_at: datetime,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        if not self.V1_CONNECTOR_BASE_URL:
            self._connector_errors[connector_id] = "V1-Connector-Bridge ist nicht konfiguriert."
            return []
        try:
            with httpx.Client(timeout=8) as client:
                response = client.post(
                    f"{self.V1_CONNECTOR_BASE_URL.rstrip('/')}/api/v1/connectors/cex/balances-preview",
                    json={"connector_id": connector_id, "timeout_seconds": 20},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            self._connector_errors[connector_id] = f"V1-Connector-Aufruf fehlgeschlagen: {exc}"
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and payload.get("status") == "error":
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    self._connector_errors[connector_id] = str(first.get("message") or first.get("code") or "connector_error")
            else:
                self._connector_errors[connector_id] = "V1-Connector meldete einen Fehler."
            return []
        rows = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            self._connector_errors[connector_id] = "V1-Connector lieferte keine rows-Liste."
            return []
        snapshots: list[PortfolioLiveBalanceSnapshot] = []
        seen: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset") or "").strip().upper()
            if not asset:
                continue
            try:
                quantity = Decimal(str(row.get("quantity") or "0"))
            except Exception:
                quantity = Decimal("0")
            if quantity == 0:
                continue
            account_type = str(row.get("account_type") or "").strip() or None
            product_id = str(row.get("product_id") or "").strip() or None
            position_id = str(row.get("position_id") or "").strip() or None
            event_type = str(row.get("event_type") or "").strip() or None
            key = ":".join(
                [
                    connector_id,
                    asset,
                    account_type or "",
                    product_id or "",
                    position_id or "",
                    event_type or "",
                    fetched_at.isoformat(),
                ]
            )
            index = seen.get(key, 0)
            seen[key] = index + 1
            snapshots.append(
                PortfolioLiveBalanceSnapshot(
                    snapshot_id=f"{key}:{index}",
                    connector_id=connector_id,
                    asset=asset,
                    quantity=quantity,
                    source=self._snapshot_source_for_connector(connector_id),
                    fetched_at=fetched_at,
                    account_type=account_type,
                    product_id=product_id,
                    position_id=position_id,
                    event_type=event_type,
                )
            )
        return snapshots

    def _solscan_wallet_balances(self, wallet_address: str) -> dict[str, Decimal]:
        api_key = self._solscan_api_key()
        if not api_key:
            return {}
        url = (
            f"{self.SOLSCAN_PRO_BASE_URL.rstrip('/')}/account/portfolio?"
            f"{urllib.parse.urlencode({'address': wallet_address})}"
        )
        request = urllib.request.Request(
            url,
            headers={"token": api_key, "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            return {}
        data = payload.get("data") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(data, dict):
            return {}
        balances: dict[str, Decimal] = {}
        self._solscan_live_prices_usd = {}
        native = data.get("native_balance")
        if isinstance(native, dict):
            symbol = str(native.get("token_symbol") or "SOL").strip().upper()
            balance = self._decimal_from_payload(native.get("balance"))
            if symbol and balance != 0:
                balances[symbol] = balances.get(symbol, Decimal("0")) + balance
                price_usd = self._decimal_from_payload(native.get("token_price"))
                if price_usd > 0:
                    self._solscan_live_prices_usd[symbol] = price_usd
        tokens = data.get("tokens")
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                symbol = str(token.get("token_symbol") or "").strip().upper()
                balance = self._decimal_from_payload(token.get("balance"))
                if symbol and balance != 0:
                    balances[symbol] = balances.get(symbol, Decimal("0")) + balance
                    price_usd = self._decimal_from_payload(token.get("token_price"))
                    if price_usd > 0:
                        self._solscan_live_prices_usd[symbol] = price_usd
        return balances

    def _store_solscan_live_prices(self, priced_at: datetime) -> None:
        if not self._solscan_live_prices_usd:
            return
        usd_eur = self._current_usd_eur_rate()
        if usd_eur <= 0:
            return
        self.store.add_price_points(
            [
                PricePointCreate(
                    asset=asset,
                    price_eur=price_usd * usd_eur,
                    priced_at=priced_at,
                    source="solscan_pro:account_portfolio:usd_eur:ecb",
                    confidence=Decimal("0.98"),
                )
                for asset, price_usd in sorted(self._solscan_live_prices_usd.items())
                if price_usd > 0
            ]
        )

    def _current_usd_eur_rate(self) -> Decimal:
        try:
            with urllib.request.urlopen(
                "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
                timeout=10,
            ) as response:
                text = response.read().decode("utf-8", errors="replace")
            match = re.search(r"currency='USD' rate='([0-9.]+)'", text)
            if not match:
                return Decimal("0")
            eur_usd = Decimal(match.group(1))
            if eur_usd <= 0:
                return Decimal("0")
            return Decimal("1") / eur_usd
        except Exception:
            return Decimal("0")

    def _solscan_api_key(self) -> str:
        return resolve_secret_value(self.store, "secret.solscan.api_key")

    def _replace_live_balance_snapshots(
        self,
        snapshots: list[PortfolioLiveBalanceSnapshot],
    ) -> None:
        if not snapshots:
            return
        connectors = sorted({snapshot.connector_id for snapshot in snapshots})
        with self.store.connect() as con:
            for connector_id in connectors:
                con.execute(
                    "delete from portfolio_live_balance_snapshots where connector_id = ?",
                    [connector_id],
                )
            con.executemany(
                """
                insert into portfolio_live_balance_snapshots (
                    snapshot_id, connector_id, asset, quantity, source, fetched_at,
                    account_type, product_id, position_id, event_type
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        snapshot.snapshot_id,
                        snapshot.connector_id,
                        snapshot.asset,
                        snapshot.quantity,
                        snapshot.source,
                        snapshot.fetched_at,
                        snapshot.account_type,
                        snapshot.product_id,
                        snapshot.position_id,
                        snapshot.event_type,
                    ]
                    for snapshot in snapshots
                ],
            )

    def _portfolio_value(
        self,
        asset: str,
        quantity: Decimal | None,
        prices: dict[str, object],
    ) -> Decimal | None:
        if quantity is None:
            return None
        price = fiat_price_point(asset) or prices.get(asset.upper())
        if price is None:
            return None
        return quantity * price.price_eur

    def _is_portfolio_excluded_account(self, account: str) -> bool:
        return account.strip().lower() in self.PORTFOLIO_EXCLUDED_ACCOUNTS

    def _is_zero_quantity(self, quantity: Decimal) -> bool:
        return abs(quantity) <= self.MIN_POSITION_QUANTITY

    def _is_transfer_counterparty_account(self, account: str) -> bool:
        return account.strip() == self.FAIRSPOT_STAKING_WALLET

    def _is_current_source_excluded_account(self, account: str, asset: str) -> bool:
        normalized = account.strip()
        return normalized in {
            self.HELIUM_TO_SOLANA_MIGRATION_ACCOUNT,
            self.HELIUM_SERVICE_TO_SOLANA_MIGRATION_ACCOUNT,
            self.FAIRSPOT_STAKING_WALLET,
        } or self._is_helium_legacy_service_account(normalized, asset)

    def _asset_summary(
        self,
        positions: list[PortfolioPosition],
        valuation_at: datetime | None = None,
    ) -> list[PortfolioAssetSummary]:
        valuation_at = valuation_at or datetime.now(timezone.utc)
        grouped: dict[str, dict[str, object]] = {}
        for position in positions:
            item = grouped.setdefault(
                position.asset,
                {
                    "quantity": Decimal("0"),
                    "value_eur": Decimal("0"),
                    "position_count": 0,
                    "accounts": set(),
                    "price_sources": set(),
                    "priced_at_latest": None,
                },
            )
            item["quantity"] = item["quantity"] + position.quantity  # type: ignore[operator]
            item["value_eur"] = item["value_eur"] + (position.value_eur or Decimal("0"))  # type: ignore[operator]
            item["position_count"] = int(item["position_count"]) + 1
            item["accounts"].add(position.account)  # type: ignore[union-attr]
            if position.price_source:
                item["price_sources"].add(position.price_source)  # type: ignore[union-attr]
            if position.priced_at is not None and (
                item["priced_at_latest"] is None
                or position.priced_at > item["priced_at_latest"]
            ):
                item["priced_at_latest"] = position.priced_at
        result: list[PortfolioAssetSummary] = []
        for asset, item in sorted(
            grouped.items(),
            key=lambda entry: abs(entry[1]["value_eur"]),  # type: ignore[arg-type]
            reverse=True,
        ):
            priced_at = item["priced_at_latest"]
            price_sources = sorted(item["price_sources"])  # type: ignore[arg-type]
            is_fiat = any(source.startswith("fiat:") for source in price_sources)
            age_days = None if is_fiat else (
                (valuation_at - self._normalize_cutoff(priced_at)).days
                if priced_at is not None
                else None
            )
            result.append(
                PortfolioAssetSummary(
                    asset=asset,
                    quantity=item["quantity"],  # type: ignore[arg-type]
                    value_eur=item["value_eur"],  # type: ignore[arg-type]
                    position_count=int(item["position_count"]),
                    accounts=len(item["accounts"]),  # type: ignore[arg-type]
                    price_sources=price_sources,
                    priced_at_latest=priced_at,  # type: ignore[arg-type]
                    price_age_days=age_days,
                    price_status="fiat" if is_fiat else self._portfolio_price_status(age_days),
                    **self._token_metadata_fields(asset),
                )
            )
        return result

    def _token_metadata_fields(self, asset: str) -> dict[str, object]:
        metadata = self._token_metadata_for_asset(asset)
        if metadata is None:
            return {}
        return {
            "token_name": metadata.name,
            "token_symbol": metadata.symbol,
            "token_mint": metadata.mint,
            "token_verified": metadata.is_verified,
            "token_risk_status": metadata.risk_status,
        }

    def _token_metadata_for_asset(self, asset: str) -> JupiterTokenMetadataCacheItem | None:
        if self._jupiter_metadata_cache is None:
            self._jupiter_metadata_cache = JupiterTokenService(self.store).cached_metadata_by_asset()
        return self._jupiter_metadata_cache.get(str(asset)) or self._jupiter_metadata_cache.get(str(asset).upper())

    def _portfolio_price_status(self, age_days: int | None) -> str:
        if age_days is None:
            return "missing"
        if age_days <= self.PRICE_FRESH_DAYS:
            return "fresh"
        if age_days <= self.PRICE_STALE_DAYS:
            return "stale"
        return "outdated"

    @staticmethod
    def _current_price_from_summary(asset: PortfolioAssetSummary) -> Decimal | None:
        if asset.quantity == 0:
            return None
        return asset.value_eur / asset.quantity

    def _previous_prices_by_asset(self) -> dict[str, tuple[datetime, Decimal, str]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                with ranked as (
                    select
                        upper(asset) as asset,
                        priced_at,
                        price_eur,
                        source,
                        row_number() over (
                            partition by upper(asset)
                            order by priced_at desc, created_at desc, price_id desc
                        ) as rn
                    from price_ledger
                    where price_eur > 0
                )
                select asset, priced_at, price_eur, source
                from ranked
                where rn = 2
                """
            ).fetchall()
        return {
            str(asset).upper(): (priced_at, price_eur, source)
            for asset, priced_at, price_eur, source in rows
        }

    @staticmethod
    def _valuation_audit_note(
        asset: PortfolioAssetSummary,
        has_previous: bool,
        value_delta: Decimal | None,
    ) -> str:
        if asset.price_status == "missing":
            return "Keine aktuelle EUR-Bewertung vorhanden."
        if not has_previous:
            return "Kein vorheriger Preisledger-Punkt fuer Delta-Vergleich vorhanden."
        if value_delta is None:
            return "Preisvergleich vorhanden, aber Delta nicht berechenbar."
        if abs(value_delta) < Decimal("1"):
            return "Bewertungsaenderung unter 1 EUR."
        return "Wertdelta stammt aus Preisbewegung bei unveraenderter Snapshot-Menge."

    def _account_summary(
        self,
        positions: list[PortfolioPosition],
    ) -> list[PortfolioAccountSummary]:
        grouped: dict[str, dict[str, object]] = {}
        for position in positions:
            item = grouped.setdefault(
                position.account,
                {
                    "value_eur": Decimal("0"),
                    "position_count": 0,
                    "assets": set(),
                },
            )
            item["value_eur"] = item["value_eur"] + (position.value_eur or Decimal("0"))  # type: ignore[operator]
            item["position_count"] = int(item["position_count"]) + 1
            item["assets"].add(position.asset)  # type: ignore[union-attr]
        return [
            PortfolioAccountSummary(
                account=account,
                value_eur=item["value_eur"],  # type: ignore[arg-type]
                position_count=int(item["position_count"]),
                assets=len(item["assets"]),  # type: ignore[arg-type]
            )
            for account, item in sorted(
                grouped.items(),
                key=lambda entry: abs(entry[1]["value_eur"]),  # type: ignore[arg-type]
                reverse=True,
            )
        ]

    def separation_virtual_wallet(
        self,
        cutoff: datetime | None = None,
    ) -> PortfolioVirtualWallet:
        cutoff = self._normalize_cutoff(cutoff)
        cached = self._virtual_wallet_cache.get(cutoff)
        if cached is not None:
            return cached
        lot_quantities: dict[str, Decimal] = {}
        for lot, _event in self._separation_fiat_purchase_lots(cutoff):
            lot_quantities[lot.asset] = lot_quantities.get(lot.asset, Decimal("0")) + lot.quantity_remaining
        prices = self._latest_prices()
        positions: list[PortfolioPosition] = []
        total = Decimal("0")
        missing: set[str] = set()

        for asset, added_quantity in sorted(lot_quantities.items()):
            if self._is_separation_excluded_asset(asset):
                continue
            if added_quantity <= 0:
                continue
            price = fiat_price_point(asset) or prices.get(asset)
            if price is None:
                missing.add(asset)
                positions.append(
                    PortfolioPosition(
                        account=self.SEPARATION_LABEL,
                        asset=asset,
                        quantity=added_quantity,
                        **self._token_metadata_fields(asset),
                    )
                )
                continue
            value = added_quantity * price.price_eur
            total += value
            positions.append(
                PortfolioPosition(
                    account=self.SEPARATION_LABEL,
                    asset=asset,
                    quantity=added_quantity,
                    price_eur=price.price_eur,
                    value_eur=value,
                    price_source=price.source,
                    priced_at=price.priced_at,
                    **self._token_metadata_fields(asset),
                )
            )

        virtual_wallet = PortfolioVirtualWallet(
            label=self.SEPARATION_LABEL,
            cutoff_date=cutoff.date().isoformat(),
            positions=positions,
            total_value_eur=total,
            missing_price_assets=sorted(missing),
            methodology=(
                "Pro Asset: offene FIFO-Restmengen aus echten EUR-Kaeufen ab "
                "2025-06-13T00:00:00Z. Gezaehlt werden nur Canonical Events "
                "mit event_type=trade, positiver Token-Menge und "
                "quote_asset=EUR. Staking, Rewards, Mining, Zinsen, Deposits, "
                "Transfers, Redeems und reine Bestandszunahmen werden nicht "
                "als Investment-Neubestand gefuehrt."
            ),
        )
        self._virtual_wallet_cache[cutoff] = virtual_wallet
        return virtual_wallet

    def separation_report(
        self,
        cutoff: datetime | None = None,
    ) -> PortfolioSeparationReport:
        cutoff = self._normalize_cutoff(cutoff)
        valuation_at = datetime.now(timezone.utc)
        virtual_wallet = self.separation_virtual_wallet(cutoff)
        unrealized_lots = self.separation_unrealized_lots(cutoff, valuation_at)
        current_value_total = sum(
            (
                lot.current_value_eur
                for lot in unrealized_lots
                if lot.current_value_eur is not None
            ),
            Decimal("0"),
        )
        cost_basis_total = sum((lot.cost_basis_eur for lot in unrealized_lots), Decimal("0"))
        return PortfolioSeparationReport(
            label=virtual_wallet.label,
            cutoff_date=virtual_wallet.cutoff_date,
            valuation_at=valuation_at,
            virtual_wallet=virtual_wallet,
            trend=self.separation_trend(cutoff),
            investment_locations=self.separation_investment_locations(cutoff),
            unrealized_lots=unrealized_lots,
            price_quality=self.separation_price_quality(virtual_wallet.positions, valuation_at),
            unmatched_lot_assets=self._unmatched_lot_assets(
                virtual_wallet.positions,
                unrealized_lots,
            ),
            cost_basis_eur_total=cost_basis_total,
            current_value_eur_total=current_value_total,
            unrealized_gain_loss_eur_total=current_value_total - cost_basis_total,
            grafana_hint=(
                "Grafana kann diesen JSON-Endpunkt mit dem JSON-API-Plugin lesen. "
                "Zeitachse: trend[].date, Wert: trend[].total_value_eur. "
                "Investment-Orte: investment_locations. Anschaffungssicht: "
                "unrealized_lots."
            ),
        )

    def fiat_deposit_report(
        self,
        cutoff: datetime | None = None,
        source: str = "binance",
    ) -> PortfolioFiatDepositReport:
        cutoff = self._normalize_cutoff(cutoff)
        target_source = source.lower()
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    e.event_time,
                    e.source,
                    e.account,
                    e.asset,
                    e.quantity,
                    json_extract_string(r.payload_json, '$."Deposit Amount"') as deposit_amount_original,
                    json_extract_string(r.payload_json, '$.Method') as method,
                    json_extract_string(r.payload_json, '$.Status') as status,
                    coalesce(e.tx_id, e.source_ref) as transaction_id,
                    b.filename as source_file,
                    r.row_number,
                    e.raw_object_id
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where e.event_time >= ?
                  and lower(e.source) = ?
                  and lower(coalesce(e.account, '')) = ?
                  and e.event_type = 'transfer'
                  and upper(e.asset) = 'EUR'
                  and e.quantity > 0
                order by e.event_time, e.event_id
                """,
                [cutoff, target_source, target_source],
            ).fetchall()

        deposits: list[PortfolioFiatDeposit] = []
        total_receive = Decimal("0")
        total_deposit: Decimal | None = Decimal("0")
        for row in rows:
            receive_amount = row[4] or Decimal("0")
            total_receive += receive_amount
            deposit_amount = self._parse_eur_amount(row[5])
            if deposit_amount is None:
                total_deposit = None
            elif total_deposit is not None:
                total_deposit += deposit_amount
            deposits.append(
                PortfolioFiatDeposit(
                    time_utc=self._normalize_cutoff(row[0]),
                    source=row[1],
                    account=row[2],
                    asset=row[3],
                    receive_amount_eur=receive_amount,
                    deposit_amount_original=row[5],
                    method=row[6],
                    status=row[7],
                    transaction_id=row[8],
                    source_file=row[9],
                    source_row=row[10],
                    raw_object_id=row[11],
                )
            )

        total_difference = None
        if total_deposit is not None:
            total_difference = total_deposit - total_receive
        return PortfolioFiatDepositReport(
            cutoff_date=cutoff.date().isoformat(),
            target_source=target_source,
            rows=deposits,
            rows_count=len(deposits),
            total_receive_amount_eur=total_receive,
            total_deposit_amount_eur=total_deposit,
            total_fee_or_difference_eur=total_difference,
            methodology=(
                "Zaehlt externe Fiat-EUR-Einzahlungen ab Stichtag aus "
                "canonical_events mit source/account gleich Zielplattform, "
                "event_type=transfer, asset=EUR und positiver Menge. Interne "
                "Spot-Gegenbuchungen werden nicht mitgezaehlt, damit "
                "Einzahlungen nicht doppelt erscheinen."
            ),
        )

    def separation_unrealized_lots(
        self,
        cutoff: datetime | None = None,
        valuation_at: datetime | None = None,
    ) -> list[PortfolioSeparationLot]:
        cutoff = self._normalize_cutoff(cutoff)
        valuation_at = self._normalize_cutoff(valuation_at)
        prices = self._latest_prices()
        events_by_id = self._canonical_events_by_id()
        remaining_virtual_quantities = {
            position.asset: position.quantity
            for position in self.separation_virtual_wallet(cutoff).positions
            if position.quantity > 0
        }
        lots: list[PortfolioSeparationLot] = []
        for lot, source_event in self._separation_fiat_purchase_lots(cutoff):
            acquired_at = self._normalize_cutoff(lot.acquired_at)
            remaining_virtual_quantity = remaining_virtual_quantities.get(lot.asset, Decimal("0"))
            if remaining_virtual_quantity <= 0:
                continue
            allocated_quantity = min(lot.quantity_remaining, remaining_virtual_quantity)
            remaining_virtual_quantities[lot.asset] = remaining_virtual_quantity - allocated_quantity
            cost_basis = lot.cost_basis_eur_total * (allocated_quantity / lot.quantity_total)
            price = fiat_price_point(lot.asset, valuation_at) or prices.get(lot.asset.upper())
            quality = self._price_quality(lot.asset, price, valuation_at)
            current_value = allocated_quantity * price.price_eur if price is not None else None
            source_event = events_by_id.get(lot.source_event_id)
            lots.append(
                PortfolioSeparationLot(
                    lot_id=lot.lot_id,
                    asset=lot.asset,
                    acquired_at=acquired_at,
                    quantity_remaining=allocated_quantity,
                    cost_basis_eur=cost_basis,
                    current_value_eur=current_value,
                    unrealized_gain_loss_eur=current_value - cost_basis
                    if current_value is not None
                    else None,
                    price_eur=price.price_eur if price is not None else None,
                    price_source=price.source if price is not None else None,
                    priced_at=price.priced_at if price is not None else None,
                    price_age_days=quality.price_age_days,
                    price_status=quality.status,
                    source_event_id=lot.source_event_id,
                    source=source_event.source,
                    account=source_event.account,
                    event_type=source_event.event_type,
                )
            )
        return sorted(lots, key=lambda item: (item.acquired_at, item.asset, item.lot_id))

    def separation_price_quality(
        self,
        positions: list[PortfolioPosition],
        valuation_at: datetime | None = None,
    ) -> list[PortfolioPriceQuality]:
        valuation_at = self._normalize_cutoff(valuation_at)
        result: list[PortfolioPriceQuality] = []
        for position in positions:
            price = None
            if position.price_eur is not None and position.price_source is not None:
                price = SimpleNamespace(
                    asset=position.asset,
                    price_eur=position.price_eur,
                    source=position.price_source,
                    priced_at=position.priced_at,
                )
            result.append(self._price_quality(position.asset, price, valuation_at))
        return result

    def separation_trend(
        self,
        cutoff: datetime | None = None,
    ) -> list[PortfolioTrendPoint]:
        cutoff = self._normalize_cutoff(cutoff)
        lots = self._separation_fiat_purchase_lots(cutoff)
        tax_lines = self._tax_lines()
        disposals_by_lot: dict[str, list[tuple[datetime, Decimal]]] = {}
        for line in tax_lines:
            disposals_by_lot.setdefault(line.lot_id, []).append(
                (self._normalize_cutoff(line.disposed_at), line.quantity)
            )
        point_dates = {cutoff.date()}
        for lot, _event in lots:
            point_dates.add(self._normalize_cutoff(lot.acquired_at).date())
            for disposed_at, _quantity in disposals_by_lot.get(lot.lot_id, []):
                point_dates.add(disposed_at.date())
        price_lookup = self._price_lookup()
        points: list[PortfolioTrendPoint] = []
        for point_date in sorted(point_dates):
            point_time = datetime.combine(point_date, time.max, tzinfo=timezone.utc)
            lookup_time = point_time.replace(tzinfo=None)
            quantities: dict[str, Decimal] = {}
            for lot, _event in lots:
                acquired_at = self._normalize_cutoff(lot.acquired_at)
                if acquired_at.date() > point_date:
                    continue
                quantity = lot.quantity_total
                for disposed_at, disposed_quantity in disposals_by_lot.get(lot.lot_id, []):
                    if disposed_at.date() <= point_date:
                        quantity -= disposed_quantity
                if quantity <= 0:
                    continue
                quantities[lot.asset] = quantities.get(lot.asset, Decimal("0")) + quantity
            total = Decimal("0")
            missing: set[str] = set()
            for asset, quantity in sorted(quantities.items()):
                if self._is_separation_excluded_asset(asset):
                    continue
                price = fiat_price_point(asset, point_time) or price_lookup.at_or_before(asset, lookup_time)
                if price is None:
                    missing.add(asset)
                    continue
                total += quantity * price.price_eur
            points.append(
                PortfolioTrendPoint(
                    date=point_date.isoformat(),
                    total_value_eur=total,
                    missing_price_assets=sorted(missing),
                )
            )
        return points

    def _separation_fiat_purchase_lots(
        self,
        cutoff: datetime,
    ) -> list[tuple[object, object]]:
        cached = self._separation_lots_cache.get(cutoff)
        if cached is not None:
            return cached
        events_by_id = self._canonical_events_by_id()
        result = []
        for lot in self._tax_lots():
            acquired_at = self._normalize_cutoff(lot.acquired_at)
            if acquired_at < cutoff or lot.quantity_remaining <= 0:
                continue
            if self._is_separation_excluded_asset(lot.asset):
                continue
            source_event = events_by_id.get(lot.source_event_id)
            if source_event is None:
                continue
            if not self._is_separation_fiat_purchase_event(source_event):
                continue
            result.append((lot, source_event))
        self._separation_lots_cache[cutoff] = result
        return result

    def _is_separation_fiat_purchase_event(self, event: object) -> bool:
        quote_asset = getattr(event, "quote_asset", None)
        quote_quantity = getattr(event, "quote_quantity", None)
        return (
            getattr(event, "event_type", None) == "trade"
            and getattr(event, "quantity", Decimal("0")) > 0
            and quote_asset is not None
            and str(quote_asset).upper() == "EUR"
            and quote_quantity is not None
            and quote_quantity != 0
        )

    def _parse_eur_amount(self, value: str | None) -> Decimal | None:
        if value is None:
            return None
        cleaned = value.upper().replace("EUR", "").strip()
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except Exception:
            return None

    def separation_investment_locations(
        self,
        cutoff: datetime | None = None,
    ) -> list[PortfolioInvestmentLocation]:
        cutoff = self._normalize_cutoff(cutoff)
        virtual_quantities = {
            position.asset: position.quantity
            for position in self.separation_virtual_wallet(cutoff).positions
            if position.quantity > 0
        }
        prices = self._latest_prices()
        locations: list[PortfolioInvestmentLocation] = []
        account_positions = self._current_account_asset_positions()
        for asset, virtual_quantity in sorted(virtual_quantities.items()):
            remaining = virtual_quantity
            candidates = [
                (account, quantity)
                for (account, candidate_asset), quantity in account_positions.items()
                if candidate_asset == asset and quantity > 0
            ]
            for account, quantity in sorted(candidates, key=lambda item: (item[0], item[1])):
                if remaining <= 0:
                    break
                allocated = min(quantity, remaining)
                remaining -= allocated
                price = fiat_price_point(asset) or prices.get(asset)
                if price is None:
                    locations.append(
                        PortfolioInvestmentLocation(
                            account=account,
                            asset=asset,
                            quantity=allocated,
                        )
                    )
                    continue
                locations.append(
                    PortfolioInvestmentLocation(
                        account=account,
                        asset=asset,
                        quantity=allocated,
                        price_eur=price.price_eur,
                        value_eur=allocated * price.price_eur,
                        price_source=price.source,
                        priced_at=price.priced_at,
                    )
                )
        return locations

    def _asset_balances_before_and_now(
        self,
        cutoff: datetime,
    ) -> list[tuple[str, Decimal, Decimal]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    asset,
                    sum(case when event_time < ? then delta_quantity else 0 end) as pre_cutoff_quantity,
                    sum(delta_quantity) as current_quantity
                from balance_ledger
                group by asset
                order by asset
                """,
                [cutoff],
            ).fetchall()
        return [(row[0], row[1] or Decimal("0"), row[2] or Decimal("0")) for row in rows]

    def _normalize_cutoff(self, cutoff: datetime | None) -> datetime:
        cutoff = cutoff or self.DEFAULT_SEPARATION_CUTOFF
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        return cutoff.astimezone(timezone.utc)

    def _normalize_as_of(self, value: str | date | datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, date):
            result = datetime.combine(value, time.max, tzinfo=timezone.utc)
        else:
            raw = value.strip()
            if not raw:
                return datetime.now(timezone.utc)
            if raw.endswith("Z"):
                raw = f"{raw[:-1]}+00:00"
            parsed_date: date | None = None
            try:
                parsed_date = date.fromisoformat(raw)
            except ValueError:
                parsed_date = None
            if parsed_date is not None and "T" not in raw and " " not in raw:
                result = datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)
            else:
                result = datetime.fromisoformat(raw)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    def _positions_as_of(self, as_of: datetime) -> list[SimpleNamespace]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select account, asset, sum(delta_quantity) as quantity
                from balance_ledger
                where event_time <= ?
                group by account, asset
                order by account, asset
                """,
                [as_of],
            ).fetchall()
        return [
            SimpleNamespace(account=row[0], asset=row[1], quantity=row[2])
            for row in rows
        ]

    def _asset_balances_at(self, at_time: datetime, *, before: bool) -> dict[str, Decimal]:
        operator = "<" if before else "<="
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select asset, sum(delta_quantity) as quantity
                from balance_ledger
                where event_time {operator} ?
                group by asset
                order by asset
                """,
                [at_time],
            ).fetchall()
        return {row[0]: row[1] or Decimal("0") for row in rows}

    def _current_account_asset_positions(self) -> dict[tuple[str, str], Decimal]:
        balances = BalanceLedgerBuilder(self.store).positions()
        account_aliases = build_account_alias_map_for_store(
            self.store,
            [balance.account for balance in balances],
        )
        positions: dict[tuple[str, str], Decimal] = {}
        for balance in balances:
            account = canonical_account_label(balance.account, account_aliases)
            key = (account, balance.asset)
            positions[key] = positions.get(key, Decimal("0")) + balance.quantity
        return positions

    def _canonical_events(self) -> list[object]:
        if self._canonical_events_cache is None:
            self._canonical_events_cache = self.store.list_canonical_events()
        return self._canonical_events_cache

    def _canonical_events_by_id(self) -> dict[str, object]:
        if self._canonical_events_by_id_cache is None:
            self._canonical_events_by_id_cache = {
                event.event_id: event for event in self._canonical_events()
            }
        return self._canonical_events_by_id_cache

    def _tax_lots(self) -> list[object]:
        if self._tax_lots_cache is None:
            self._tax_lots_cache = TaxService(self.store).list_tax_lots()
        return self._tax_lots_cache

    def _tax_lines(self) -> list[object]:
        if self._tax_lines_cache is None:
            self._tax_lines_cache = TaxService(self.store).list_tax_lines()
        return self._tax_lines_cache

    def _latest_prices(self) -> dict[str, object]:
        if self._latest_prices_cache is None:
            self._latest_prices_cache = self.store.latest_price_points()
        return self._latest_prices_cache

    def _price_lookup(self) -> HistoricalPriceLookup:
        if self._price_lookup_cache is None:
            self._price_lookup_cache = HistoricalPriceLookup(self.store)
        return self._price_lookup_cache

    def _source_group_for_account(
        self,
        account: str,
        assets: set[str],
    ) -> tuple[str, str]:
        normalized = account.strip()
        lower = normalized.lower()
        if lower in {"spot", "funding", "binance"} or "binance" in lower:
            return "Binance", "exchange"
        if "pionex" in lower:
            return "Pionex", "exchange"
        if "bitget" in lower:
            return "Bitget", "exchange"
        if lower == "helium":
            return "Solana Wallet 6K9n7y...qEwP", "solana_wallet"
        if normalized == self.HELIUM_TO_SOLANA_MIGRATION_ACCOUNT:
            return "Solana Wallet 6K9n7y...qEwP", "solana_wallet"
        if normalized == self.HELIUM_SERVICE_TO_SOLANA_MIGRATION_ACCOUNT:
            return "Solana Wallet 6K9n7y...qEwP", "solana_wallet"
        if normalized == self.MAIN_HELIUM_LEGACY_WALLET:
            return "Solana Wallet 6K9n7y...qEwP", "solana_wallet"
        if normalized == self.KNOWN_JUP_WALLET:
            return "Jup Wallet GmHY...3yu", "solana_wallet"
        if normalized == self.PRIMARY_SOLANA_WALLET:
            return "Solana Wallet 6K9n7y...qEwP", "solana_wallet"
        if normalized == self.FAIRSPOT_STAKING_WALLET:
            return "Fairspot Staking Transfer Counterparty", "transfer_counterparty"
        if "HNT" in {asset.upper() for asset in assets} and _looks_like_base58_wallet(normalized):
            return "Helium Legacy Wallets", "legacy_wallet"
        if _looks_like_base58_wallet(normalized):
            return "Solana Wallets", "solana_wallet"
        return normalized or "Unassigned", "account"

    def _source_current_status(self, source_group: str) -> str:
        if source_group in self.EXPECTED_ZERO_SOURCES:
            return "ledger_residual_expected_zero"
        if source_group == "Jup Wallet GmHY...3yu":
            return "known_wallet_missing_import"
        return "ledger_current"

    def _source_note(self, source_group: str, account: str | None) -> str | None:
        if source_group == "Bitget":
            return (
                "Ledger-Restbestand aus Importdaten; Nutzerhinweis: aktueller Bitget-"
                "Bestand sollte per API 0 sein. Gegenbuchung/Reconciliation pruefen."
            )
        if source_group == "Pionex":
            return (
                "Ledger-Restbestand aus Importdaten; Nutzerhinweis: aktueller Pionex-"
                "Bestand sollte 0 sein. Historische Exportluecke oder fehlende "
                "Abgangsbuchung pruefen."
            )
        if account == self.HELIUM_TO_SOLANA_MIGRATION_ACCOUNT:
            return (
                "Historischer Blockchain-Wechsel: frueherer Helium-Main-Wallet-"
                "Restbestand wird als erster Transfer/Startbestand der Solana-"
                "Wallet gefuehrt, nicht als aktuelle Helium-Quelle."
            )
        if account == self.HELIUM_SERVICE_TO_SOLANA_MIGRATION_ACCOUNT:
            return (
                "Helium-Legacy-/Service-Wallets sind keine aktuellen eigenen "
                "Wallets. Ihre Restwerte werden fuer das Dashboard als "
                "historischer Transfer-/Startbestand der Solana-Wallet gefuehrt; "
                "die Originalevents bleiben fuer FIFO-Pruefung erhalten."
            )
        if source_group == "Fairspot Staking Transfer Counterparty":
            return (
                "Bekannte Fairspot-/Staking-Plattform des Nutzers. HNT-Transfers "
                "zu dieser Adresse werden als Transfer-Gegenpartei fuer FIFO-"
                "Nachverfolgung erhalten, aber nicht als aktuelle Portfolio-Wallet "
                "oder eigene Dashboard-Quelle bewertet. "
                "Fairspot-Beleg: https://www.fairspot.host/hnt-export-mining-tax"
                "?account=13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"
            )
        if source_group == "Jup Wallet GmHY...3yu":
            return (
                "Aktuelle Jup-Wallet laut Nutzer. Historie wird ueber Solscan "
                "Balance-Change importiert; Live-Anker stammt aus Solscan Pro."
            )
        return None

    def _source_account_label(self, account: str, asset: str) -> str:
        normalized = account.strip()
        if normalized == self.MAIN_HELIUM_LEGACY_WALLET:
            return self.HELIUM_TO_SOLANA_MIGRATION_ACCOUNT
        if normalized == self.FAIRSPOT_STAKING_WALLET:
            return account
        if self._is_helium_legacy_service_account(normalized, asset):
            return self.HELIUM_SERVICE_TO_SOLANA_MIGRATION_ACCOUNT
        return account

    def _is_helium_legacy_service_account(self, account: str, asset: str) -> bool:
        if asset.upper() not in self.HELIUM_LEGACY_ASSETS:
            return False
        lower = account.lower()
        if lower == "helium":
            return True
        if account in {
            self.PRIMARY_SOLANA_WALLET,
            self.KNOWN_JUP_WALLET,
            self.FAIRSPOT_STAKING_WALLET,
        }:
            return False
        return _looks_like_base58_wallet(account)

    def _is_separation_excluded_asset(self, asset: str) -> bool:
        return asset.upper() in self.SEPARATION_EXCLUDED_ASSETS

    def _price_quality(
        self,
        asset: str,
        price: object | None,
        valuation_at: datetime,
    ) -> PortfolioPriceQuality:
        if price is None:
            return PortfolioPriceQuality(
                asset=asset.upper(),
                status="missing",
                warning="Kein Preis fuer die aktuelle Bewertung vorhanden.",
            )
        priced_at = self._normalize_cutoff(getattr(price, "priced_at"))
        source = str(getattr(price, "source"))
        age_days = max((valuation_at.date() - priced_at.date()).days, 0)
        status = "ok"
        warning = None
        if source.startswith("derived:event_quote"):
            status = "derived_event_quote"
            warning = (
                "Preis stammt aus einem Transaktions-Quote und ist keine "
                "unabhaengige Marktpreisquelle fuer den Bewertungsstichtag."
            )
        elif age_days > self.PRICE_STALE_DAYS:
            status = "stale"
            warning = (
                f"Preis ist {age_days} Tage vor dem Bewertungsstichtag datiert."
            )
        elif age_days > self.PRICE_FRESH_DAYS:
            status = "aged"
            warning = (
                f"Preis ist {age_days} Tage vor dem Bewertungsstichtag datiert."
            )
        return PortfolioPriceQuality(
            asset=asset.upper(),
            price_eur=getattr(price, "price_eur"),
            price_source=source,
            priced_at=priced_at,
            price_age_days=age_days,
            status=status,
            warning=warning,
        )

    def _unmatched_lot_assets(
        self,
        positions: list[PortfolioPosition],
        lots: list[PortfolioSeparationLot],
    ) -> list[str]:
        lot_quantities: dict[str, Decimal] = {}
        for lot in lots:
            lot_quantities[lot.asset] = lot_quantities.get(lot.asset, Decimal("0")) + lot.quantity_remaining
        unmatched: list[str] = []
        for position in positions:
            allocated = lot_quantities.get(position.asset, Decimal("0"))
            if position.quantity - allocated > Decimal("0.000000000000000001"):
                unmatched.append(position.asset)
        return sorted(set(unmatched))

    def _daily_asset_deltas_since(self, cutoff: datetime) -> dict[date, dict[str, Decimal]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select cast(event_time as date) as event_date, asset, sum(delta_quantity) as quantity
                from balance_ledger
                where event_time >= ?
                group by event_date, asset
                order by event_date, asset
                """,
                [cutoff],
            ).fetchall()
        result: dict[date, dict[str, Decimal]] = {}
        for row in rows:
            result.setdefault(row[0], {})[row[1]] = row[2] or Decimal("0")
        return result


def _looks_like_base58_wallet(value: str) -> bool:
    if len(value) < 24 or "..." in value:
        return False
    alphabet = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    return all(char in alphabet for char in value)
