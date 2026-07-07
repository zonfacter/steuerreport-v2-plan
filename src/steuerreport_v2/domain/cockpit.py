from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from steuerreport_v2.contracts.cockpit import (
    CockpitEvidenceHealth,
    CockpitLiveReconciliation,
    CockpitMetric,
    CockpitPipelineStatus,
    CockpitPortfolioPerformance,
    CockpitPriceCoverage,
    CockpitQuickAction,
    CockpitSummary,
    CockpitTask,
    CockpitTopAsset,
    CockpitTopSource,
)
from steuerreport_v2.contracts.portfolio import (
    PortfolioSourceAccount,
    PortfolioSourceAsset,
    PortfolioSourceGroup,
    PortfolioSourceOverview,
)
from steuerreport_v2.contracts.review import ReviewGate, ReviewIssue
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map,
    canonical_account_label,
)
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.price_lookup import fiat_price_point
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.valuation import PriceCoverageService


class CockpitService:
    EXPECTED_ZERO_SOURCES = {"Bitget", "Pionex"}
    CEX_LIVE_CONNECTORS = {"binance", "bitget", "pionex"}
    LIVE_STALE_AFTER_DAYS = 3
    CONNECTOR_BY_SOURCE = {
        "Binance": "binance",
        "Bitget": "bitget",
        "Pionex": "pionex",
        "Jup Wallet GmHY...3yu": "jup_wallet",
        "Solana Wallet 6K9n7y...qEwP": "solana_wallet",
    }

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._latest_live_snapshot_cache: dict[str, datetime | None] = {}

    def summary(self) -> CockpitSummary:
        generated_at = datetime.now(timezone.utc)
        with ThreadPoolExecutor(max_workers=7) as executor:
            sources_future = executor.submit(self._source_overview_light)
            price_future = executor.submit(lambda: PriceCoverageService(self.store).report())
            evidence_future = executor.submit(lambda: self._evidence_health(ReviewService(self.store)))
            source_live_future = executor.submit(self._source_live_values)
            pipeline_future = executor.submit(self._pipeline_status)
            top_assets_future = executor.submit(self._top_current_assets)
            current_missing_future = executor.submit(self._current_missing_price_assets)

            sources = sources_future.result()
            price_report = price_future.result()
            evidence_health = evidence_future.result()
            source_live = source_live_future.result()
            pipeline = pipeline_future.result()
            top_assets = top_assets_future.result()
            current_missing_assets = current_missing_future.result()

        review = self._review_gate_light(price_report)
        live = self._live_reconciliation_status(sources.groups, source_live)
        cockpit_value_eur = sum((asset.value_eur for asset in top_assets), Decimal("0"))
        if not top_assets:
            cockpit_value_eur = sources.total_value_eur
            top_assets = self._top_assets_from_source_overview(sources.groups, cockpit_value_eur)
        price_coverage = self._price_coverage_from_top_assets(
            top_assets,
            price_report.missing_count,
            sorted(set(price_report.missing_assets) | set(current_missing_assets)),
        )
        tasks = self._tasks(review, price_coverage, live)
        source_display_total = sum(
            (
                source_live.get(item.source_group, {}).get("live_value_eur")
                if source_live.get(item.source_group, {}).get("live_value_eur") is not None
                else item.value_eur
                for item in sources.groups
            ),
            Decimal("0"),
        )
        portfolio_performance = self._portfolio_performance(
            display_value_eur=cockpit_value_eur,
            display_value_basis=(
                "live_api"
                if any(asset.value_basis == "live_api" for asset in top_assets)
                else "calculated_ledger"
            ),
            calculated_value_eur=sources.total_value_eur,
        )

        return CockpitSummary(
            generated_at=generated_at,
            portfolio_value_eur=cockpit_value_eur,
            export_allowed=review.allow_export,
            export_status="frei" if review.allow_export else "blockiert",
            open_tasks=len(tasks),
            top_assets=top_assets[:5],
            top_sources=[
                CockpitTopSource(
                    source_group=item.source_group,
                    source_type=item.source_type,
                    value_eur=self._source_display_value(item, source_live),
                    share_pct=self._share(
                        self._source_display_value(item, source_live),
                        source_display_total,
                    ),
                    account_count=item.account_count,
                    assets=item.assets,
                    current_status=self._source_current_status(item, source_live),
                    value_basis=(
                        "live_api"
                        if item.source_group in source_live
                        and source_live[item.source_group]["live_value_eur"] is not None
                        else "ledger"
                    ),
                    ledger_value_eur=item.value_eur,
                    live_value_eur=source_live.get(item.source_group, {}).get("live_value_eur"),
                    delta_value_eur=(
                        None
                        if source_live.get(item.source_group, {}).get("live_value_eur") is None
                        else source_live[item.source_group]["live_value_eur"] - item.value_eur
                    ),
                    last_live_at=source_live.get(item.source_group, {}).get("last_live_at"),
                    live_anchor_source=source_live.get(item.source_group, {}).get("live_anchor_source"),
                    display_warning=self._source_display_warning(item, source_live),
                    note=item.note,
                    accounts=[account.account for account in item.accounts[:3]],
                )
                for item in sources.groups[:5]
            ],
            portfolio_performance=portfolio_performance,
            price_coverage=price_coverage,
            live_reconciliation=live,
            evidence_health=evidence_health,
            review=CockpitMetric(
                label="Exportstatus",
                value=review.allow_export,
                status="ok" if review.allow_export else "blocked",
                detail=(
                    f"{review.issues_current_open if review.issues_current_open is not None else review.issues_open} "
                    f"aktuell offen, {review.issues_historical_open} historisch offen"
                ),
            ),
            pipeline=pipeline,
            tasks=tasks,
            quick_actions=[
                CockpitQuickAction(label="Import starten", target="import", action_type="navigate"),
                CockpitQuickAction(label="Preise aktualisieren", target="portfolio", action_type="navigate"),
                CockpitQuickAction(label="Report-Center oeffnen", target="export", action_type="navigate"),
                CockpitQuickAction(label="Belegstatus pruefen", target="review", action_type="navigate"),
                CockpitQuickAction(label="Review-Issues bearbeiten", target="review", action_type="navigate"),
            ],
            methodology=(
                "Read-only Cockpit-Aggregation aus aktuellen Live-Snapshots, "
                "lesbarer Quellenuebersicht, Review-Gate, Preis-Coverage und "
                "persistierten Live-Abgleich-Ankern. Top-Assets und Cockpit-"
                "Hauptwert nutzen API-Livebestaende, wenn gespeicherte Connector-"
                "Snapshots vorhanden sind; Ledger-Werte bleiben je Quelle als "
                "steuerliche Abgleichsbasis sichtbar. Der Endpunkt schreibt keine "
                "Buchungen oder Review-Entscheidungen."
            ),
        )

    def _review_gate_light(self, price_report: object) -> ReviewGate:
        issues: list[ReviewIssue] = []
        for batch_id, count in self.store.unmapped_raw_object_counts().items():
            issues.append(
                ReviewIssue(
                    code="unmapped_raw_objects",
                    severity="high",
                    message=(
                        f"{count} Rohzeile(n) im Import-Batch konnten nicht "
                        "zu Canonical Events normalisiert werden."
                    ),
                    scope=f"import_batch:{batch_id}",
                    blocks_export=True,
                )
            )

        positions = self._current_account_asset_positions_light()
        prices = self.store.latest_price_points()
        for asset in sorted(
            {
                asset
                for (_account, asset), quantity in positions.items()
                if quantity != 0 and fiat_price_point(asset) is None and asset not in prices
            }
        ):
            issues.append(
                ReviewIssue(
                    code="missing_price",
                    severity="high",
                    message=f"Fuer {asset} fehlt ein EUR-Preis im Price-Ledger.",
                    scope=f"asset:{asset}",
                    blocks_export=True,
                )
            )

        accounts = [account for account, _asset in positions]
        if any("..." in account for account in accounts):
            aliases = build_account_alias_map(accounts)
            unresolved = sorted({account for account in accounts if "..." in account and account not in aliases})
            for account in unresolved:
                issues.append(
                    ReviewIssue(
                        code="unresolved_truncated_account",
                        severity="high",
                        message=(
                            "Gekuerzter Account kann keiner eindeutigen vollen "
                            f"Wallet zugeordnet werden: {account}."
                        ),
                        scope=f"account_alias:{account}",
                        blocks_export=True,
                    )
                )

        for item in price_report.missing:
            issues.append(
                ReviewIssue(
                    code="missing_event_price",
                    severity="high",
                    message=(
                        f"{item.event_count} steuerrelevante Event(s) fuer "
                        f"{item.asset} im Jahr {item.year} haben keine "
                        "historische EUR-Bewertung."
                    ),
                    scope=(
                        f"price_coverage:asset:{item.asset}:year:{item.year}:"
                        f"source:{item.source}:event_type:{item.event_type}:role:{item.role}"
                    ),
                    blocks_export=True,
                )
            )

        for (account, asset), quantity in positions.items():
            if quantity < 0:
                issues.append(
                    ReviewIssue(
                        code="negative_balance",
                        severity="high",
                        message=f"Negativer Bestand fuer {asset} auf {account}.",
                        scope=f"account:{account}:asset:{asset}",
                        blocks_export=True,
                    )
                )

        tax_issue = self._tax_unmatched_issue()
        if tax_issue is not None:
            issues.append(tax_issue)

        zero_cost_lots = self._zero_cost_tax_lots_count()
        if zero_cost_lots:
            issues.append(
                ReviewIssue(
                    code="zero_cost_tax_lots",
                    severity="high",
                    message=(
                        f"{zero_cost_lots} FIFO-Lot(s) haben 0 EUR "
                        "Anschaffungskosten. Bewertung oder Quellwert fehlt."
                    ),
                    scope="tax:fifo",
                    blocks_export=True,
                )
            )

        zero_proceeds_lines = self._zero_proceeds_tax_lines_count()
        if zero_proceeds_lines:
            issues.append(
                ReviewIssue(
                    code="zero_proceeds_tax_lines",
                    severity="high",
                    message=(
                        f"{zero_proceeds_lines} Steuerzeile(n) haben 0 EUR "
                        "Verkaufserloes. Quote- oder Asset-Bewertung fehlt."
                    ),
                    scope="tax:fifo",
                    blocks_export=True,
                )
            )

        derivative_missing = self._derivative_missing_price_count()
        if derivative_missing:
            issues.append(
                ReviewIssue(
                    code="derivative_missing_prices",
                    severity="high",
                    message=(
                        f"{derivative_missing} Derivate-Zeile(n) "
                        "haben keine EUR-Bewertung."
                    ),
                    scope="tax:derivatives",
                    blocks_export=True,
                )
            )

        current_issues = [issue for issue in issues if issue.is_current_scope]
        high_count = sum(1 for issue in current_issues if issue.severity == "high")
        medium_count = sum(1 for issue in current_issues if issue.severity == "medium")
        low_count = sum(1 for issue in current_issues if issue.severity == "low")
        blocking_count = sum(1 for issue in issues if issue.blocks_export)
        return ReviewGate(
            allow_export=blocking_count == 0,
            issues_open=len(current_issues),
            issues_open_total=len(issues),
            issues_current_open=len(current_issues),
            issues_historical_open=len(issues) - len(current_issues),
            issues_high_open=high_count,
            issues_medium_open=medium_count,
            issues_low_open=low_count,
            blocking_issues_open=blocking_count,
            issues=issues,
        )

    def _tax_unmatched_issue(self) -> ReviewIssue | None:
        with self.store.connect() as con:
            summary = con.execute(
                """
                select unmatched_disposals
                from tax_run_summaries
                order by created_at desc
                limit 1
                """
            ).fetchone()
        unmatched_count = int(summary[0] or 0) if summary is not None else 0
        if unmatched_count <= 0:
            return None
        with self.store.connect() as con:
            rows = con.execute(
                """
                select distinct date_part('year', event_time)::integer as year
                from tax_unmatched_disposals
                order by year
                """
            ).fetchall()
        years = sorted(int(row[0]) for row in rows if row[0] is not None)
        tax_year = years[0] if len(years) == 1 else None
        closed_years = ReviewService(self.store)._closed_tax_years()
        is_current_scope = not years or any(year not in closed_years for year in years)
        return ReviewIssue(
            code="unmatched_tax_disposal",
            severity="high",
            message=(
                f"{unmatched_count} Verkauf/Abgang konnte keinem FIFO-Lot "
                "zugeordnet werden."
            ),
            scope=f"tax:fifo:year:{tax_year}" if tax_year is not None else "tax:fifo",
            blocks_export=is_current_scope,
            tax_year=tax_year,
            is_current_scope=is_current_scope,
        )

    def _zero_cost_tax_lots_count(self) -> int:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(distinct lot.lot_id)
                from tax_lots lot
                join tax_lines line on line.lot_id = lot.lot_id
                where lot.cost_basis_eur_total = 0
                """
            ).fetchone()
        return int(row[0] if row is not None else 0)

    def _zero_proceeds_tax_lines_count(self) -> int:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(*)
                from tax_lines
                where disposal_proceeds_eur = 0
                """
            ).fetchone()
        return int(row[0] if row is not None else 0)

    def _derivative_missing_price_count(self) -> int:
        with self.store.connect() as con:
            row = con.execute(
                """
                select missing_price_count
                from derivative_run_summaries
                order by created_at desc
                limit 1
                """
            ).fetchone()
        return int(row[0] if row is not None else 0)

    def _source_overview_light(self) -> PortfolioSourceOverview:
        portfolio = PortfolioService(self.store)
        grouped_positions = self._current_account_asset_positions_light()
        portfolio._apply_live_balance_anchor(
            grouped_positions,
            account=portfolio.KNOWN_JUP_WALLET,
            connector_id="jup_wallet",
        )
        portfolio._apply_live_balance_anchor(
            grouped_positions,
            account=portfolio.PRIMARY_SOLANA_WALLET,
            connector_id="solana_wallet",
        )
        prices = portfolio._latest_prices()

        account_assets: dict[str, dict[str, dict[str, object]]] = {}
        total_value = Decimal("0")
        for (account, asset), quantity in sorted(grouped_positions.items()):
            if (
                portfolio._is_zero_quantity(quantity)
                or portfolio._is_transfer_counterparty_account(account)
                or portfolio._is_portfolio_excluded_account(account)
                or portfolio._is_current_source_excluded_account(account, asset)
            ):
                continue
            value = portfolio._portfolio_value(asset, quantity, prices) or Decimal("0")
            total_value += value
            source_account = portfolio._source_account_label(account, asset)
            item = account_assets.setdefault(source_account, {}).setdefault(
                asset,
                {
                    "quantity": Decimal("0"),
                    "value_eur": Decimal("0"),
                    "position_count": 0,
                },
            )
            item["quantity"] = item["quantity"] + quantity  # type: ignore[operator]
            item["value_eur"] = item["value_eur"] + value  # type: ignore[operator]
            item["position_count"] = int(item["position_count"]) + 1

        accounts: list[PortfolioSourceAccount] = []
        for account, assets in account_assets.items():
            source_group, source_type = portfolio._source_group_for_account(account, set(assets))
            asset_summary = [
                PortfolioSourceAsset(
                    asset=asset,
                    quantity=item["quantity"],  # type: ignore[arg-type]
                    value_eur=item["value_eur"],  # type: ignore[arg-type]
                    position_count=int(item["position_count"]),
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
                    current_status=portfolio._source_current_status(source_group),
                    note=portfolio._source_note(source_group, account),
                    asset_summary=asset_summary,
                )
            )

        if not any(account.account == portfolio.KNOWN_JUP_WALLET for account in accounts):
            accounts.append(
                PortfolioSourceAccount(
                    account=portfolio.KNOWN_JUP_WALLET,
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
                    current_status=portfolio._source_current_status(source_group),
                    note=portfolio._source_note(source_group, None),
                    accounts=sorted(group_accounts, key=lambda item: abs(item.value_eur), reverse=True),
                    asset_summary=group_asset_summary,
                )
            )

        return PortfolioSourceOverview(
            total_value_eur=total_value,
            groups=sorted(groups, key=lambda item: abs(item.value_eur), reverse=True),
            accounts=sorted(accounts, key=lambda item: abs(item.value_eur), reverse=True),
            methodology=(
                "Cockpit-Read-Model fuer Top-Quellen. Nutzt dieselben Portfolio-"
                "Exklusionen und gespeicherten Live-Anker wie die Detailansicht, "
                "materialisiert aber nur die fuer die Startseite noetigen Gruppen."
            ),
        )

    def _current_account_asset_positions_light(self) -> dict[tuple[str, str], Decimal]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select account, asset, sum(delta_quantity) as quantity
                from balance_ledger
                group by account, asset
                order by account, asset
                """
            ).fetchall()
        aliases = build_account_alias_map([row[0] for row in rows])
        positions: dict[tuple[str, str], Decimal] = {}
        for account, asset, quantity in rows:
            canonical_account = canonical_account_label(str(account), aliases)
            key = (canonical_account, str(asset))
            positions[key] = positions.get(key, Decimal("0")) + (quantity or Decimal("0"))
        return positions

    def _evidence_health(self, review_service: ReviewService) -> CockpitEvidenceHealth:
        report = review_service.evidence_traces()
        if report.missing_decision_count:
            status = "missing_decision"
        elif report.legacy_ref_count:
            status = "legacy_ref"
        elif report.traces_count and report.canonical_count == report.traces_count:
            status = "complete"
        else:
            status = "partial"
        return CockpitEvidenceHealth(
            status=status,
            traces_count=report.traces_count,
            canonical_count=report.canonical_count,
            legacy_ref_count=report.legacy_ref_count,
            missing_decision_count=report.missing_decision_count,
            detail=(
                "Alle bekannten Belegspuren sind kanonisch verlinkt."
                if status == "complete"
                else "Belegspuren im Review-Center pruefen."
            ),
        )

    def _top_current_assets(self) -> list[CockpitTopAsset]:
        prices = PortfolioService(self.store)._latest_prices()
        asset_totals: dict[str, dict[str, object]] = {}
        with self.store.connect() as con:
            for connector_id in self.CONNECTOR_BY_SOURCE.values():
                if not self._connector_live_snapshot_is_current(connector_id):
                    continue
                rows = con.execute(
                    """
                    select asset, quantity, fetched_at
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                      and fetched_at = (
                        select max(fetched_at)
                        from portfolio_live_balance_snapshots
                        where connector_id = ?
                      )
                    order by asset
                    """,
                    [connector_id, connector_id],
                ).fetchall()
                if not rows:
                    continue
                for asset, quantity, fetched_at in rows:
                    symbol = str(asset).upper()
                    if symbol in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                        continue
                    amount = quantity or Decimal("0")
                    if amount == 0:
                        continue
                    price = fiat_price_point(symbol) or prices.get(symbol)
                    if price is None and self._is_unpriced_live_token_identifier(symbol):
                        continue
                    value = amount * price.price_eur if price is not None else Decimal("0")
                    item = asset_totals.setdefault(
                        symbol,
                        {
                            "quantity": Decimal("0"),
                            "value_eur": Decimal("0"),
                            "connectors": set(),
                            "price_sources": set(),
                            "priced_at_latest": None,
                            "missing_price": False,
                        },
                    )
                    item["quantity"] = item["quantity"] + amount  # type: ignore[operator]
                    item["value_eur"] = item["value_eur"] + value  # type: ignore[operator]
                    item["connectors"].add(connector_id)  # type: ignore[union-attr]
                    if price is None:
                        item["missing_price"] = True
                    else:
                        item["price_sources"].add(price.source)  # type: ignore[union-attr]
                        priced_at = item["priced_at_latest"]
                        if priced_at is None or price.priced_at > priced_at:
                            item["priced_at_latest"] = price.priced_at

        total = sum((item["value_eur"] for item in asset_totals.values()), Decimal("0"))  # type: ignore[arg-type]
        return [
            CockpitTopAsset(
                asset=asset,
                quantity=item["quantity"],  # type: ignore[arg-type]
                value_eur=item["value_eur"],  # type: ignore[arg-type]
                share_pct=self._share(item["value_eur"], total),  # type: ignore[arg-type]
                price_status=(
                    "missing"
                    if item["missing_price"]
                    else self._price_status(item["priced_at_latest"])
                ),
                accounts=len(item["connectors"]),  # type: ignore[arg-type]
                value_basis="live_api",
                price_sources=sorted(item["price_sources"]),  # type: ignore[arg-type]
                priced_at_latest=item["priced_at_latest"],  # type: ignore[arg-type]
            )
            for asset, item in sorted(
                asset_totals.items(),
                key=lambda entry: abs(entry[1]["value_eur"]),  # type: ignore[arg-type]
                reverse=True,
            )
        ]

    def _top_assets_from_source_overview(
        self,
        groups: list[object],
        total: Decimal,
    ) -> list[CockpitTopAsset]:
        assets: dict[str, dict[str, object]] = {}
        for group in groups:
            for asset in group.asset_summary:
                item = assets.setdefault(
                    asset.asset,
                    {
                        "quantity": Decimal("0"),
                        "value_eur": Decimal("0"),
                        "accounts": 0,
                    },
                )
                item["quantity"] = item["quantity"] + asset.quantity  # type: ignore[operator]
                item["value_eur"] = item["value_eur"] + asset.value_eur  # type: ignore[operator]
                item["accounts"] = int(item["accounts"]) + asset.position_count
        return [
            CockpitTopAsset(
                asset=asset,
                quantity=item["quantity"],  # type: ignore[arg-type]
                value_eur=item["value_eur"],  # type: ignore[arg-type]
                share_pct=self._share(item["value_eur"], total),  # type: ignore[arg-type]
                price_status="ledger",
                accounts=int(item["accounts"]),
                value_basis="current_ledger",
            )
            for asset, item in sorted(
                assets.items(),
                key=lambda entry: abs(entry[1]["value_eur"]),  # type: ignore[arg-type]
                reverse=True,
            )
        ]

    def _price_status(self, priced_at: datetime | None) -> str:
        if priced_at is None:
            return "missing"
        if priced_at.year == 1970:
            return "fiat"
        age_days = (datetime.now(timezone.utc) - priced_at.replace(tzinfo=timezone.utc)).days
        if age_days <= PortfolioService.PRICE_FRESH_DAYS:
            return "fresh"
        if age_days <= PortfolioService.PRICE_STALE_DAYS:
            return "stale"
        return "old"

    def _source_live_values(self) -> dict[str, dict[str, object]]:
        prices = PortfolioService(self.store)._latest_prices()
        result: dict[str, dict[str, object]] = {}
        with self.store.connect() as con:
            for source_group, connector_id in self.CONNECTOR_BY_SOURCE.items():
                if not self._connector_live_snapshot_is_current(connector_id):
                    continue
                rows = con.execute(
                    """
                    select asset, quantity, fetched_at
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                      and fetched_at = (
                        select max(fetched_at)
                        from portfolio_live_balance_snapshots
                        where connector_id = ?
                      )
                    order by asset
                    """,
                    [connector_id, connector_id],
                ).fetchall()
                if not rows:
                    continue
                total = Decimal("0")
                latest_at = rows[0][2]
                for asset, quantity, fetched_at in rows:
                    if str(asset).upper() in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                        continue
                    latest_at = max(latest_at, fetched_at)
                    price = fiat_price_point(str(asset).upper()) or prices.get(str(asset).upper())
                    if price is None:
                        continue
                    total += (quantity or Decimal("0")) * price.price_eur
                result[source_group] = {
                    "live_value_eur": total,
                    "last_live_at": latest_at,
                    "live_anchor_source": self._stored_live_source(connector_id),
                }
        return result

    def _stored_live_source(self, connector_id: str) -> str | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select string_agg(distinct source, ', ' order by source)
                from portfolio_live_balance_snapshots
                where connector_id = ?
                  and fetched_at = (
                    select max(fetched_at)
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                  )
                """,
                [connector_id, connector_id],
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def _price_coverage_from_top_assets(
        self,
        asset_summary: list[CockpitTopAsset],
        missing_event_price_groups: int,
        missing_event_price_assets: list[str],
    ) -> CockpitPriceCoverage:
        status_counts: dict[str, int] = {}
        for item in asset_summary:
            status_counts[item.price_status] = status_counts.get(item.price_status, 0) + 1
        missing_assets = sorted(
            {item.asset for item in asset_summary if item.price_status == "missing"}
            | {asset.upper() for asset in missing_event_price_assets}
        )
        asset_names = {item.asset for item in asset_summary} | set(missing_assets)
        total_assets = len(asset_names)
        priced_assets = max(total_assets - len(missing_assets), 0)
        if total_assets == 0:
            coverage_pct = Decimal("100.00")
        else:
            coverage_pct = (Decimal(priced_assets) / Decimal(total_assets) * Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        return CockpitPriceCoverage(
            priced_assets=priced_assets,
            total_assets=total_assets,
            missing_assets=missing_assets,
            missing_event_price_groups=missing_event_price_groups,
            status_counts=status_counts,
            coverage_pct=coverage_pct,
        )

    def _portfolio_performance(
        self,
        *,
        display_value_eur: Decimal,
        display_value_basis: str,
        calculated_value_eur: Decimal,
    ) -> CockpitPortfolioPerformance:
        open_cost_basis = self._open_cost_basis_eur()
        net_fiat_invested = self._net_fiat_invested_eur()
        unrealized_return = display_value_eur - open_cost_basis
        unrealized_pct: Decimal | None = None
        if open_cost_basis != 0:
            unrealized_pct = (unrealized_return / open_cost_basis * Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        if open_cost_basis == 0 and display_value_eur == 0:
            cost_basis_status = "empty"
        elif open_cost_basis == 0:
            cost_basis_status = "missing_or_transfer_only"
        else:
            cost_basis_status = "available"
        return CockpitPortfolioPerformance(
            display_value_eur=display_value_eur,
            display_value_basis=display_value_basis,
            live_value_eur=display_value_eur if display_value_basis == "live_api" else None,
            calculated_value_eur=calculated_value_eur,
            open_cost_basis_eur=open_cost_basis,
            unrealized_return_eur=unrealized_return,
            unrealized_return_pct=unrealized_pct,
            net_fiat_invested_eur=net_fiat_invested,
            cost_basis_status=cost_basis_status,
            detail=(
                "Display-Wert nutzt gespeicherte Live-API-Snapshots, wenn vorhanden; "
                "Calculated Value bleibt der transaktionsbasierte Ledger-Wert. "
                "Kostenbasis stammt aus offenen FIFO-Lots, Net EUR invested aus "
                "EUR-Quote-Trades."
            ),
        )

    def _open_cost_basis_eur(self) -> Decimal:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select quantity_total, quantity_remaining, cost_basis_eur_total
                from tax_lots
                where quantity_remaining > 0
                """
            ).fetchall()
        total = Decimal("0")
        for quantity_total, quantity_remaining, cost_basis_total in rows:
            if not quantity_total:
                continue
            total += cost_basis_total * quantity_remaining / quantity_total
        return total

    def _net_fiat_invested_eur(self) -> Decimal:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    coalesce(sum(
                        case
                            when event_type = 'trade'
                             and quantity > 0
                             and upper(coalesce(quote_asset, '')) = 'EUR'
                            then abs(coalesce(quote_quantity, 0))
                            else 0
                        end
                    ), 0) as fiat_buys,
                    coalesce(sum(
                        case
                            when event_type = 'trade'
                             and quantity < 0
                             and upper(coalesce(quote_asset, '')) = 'EUR'
                            then abs(coalesce(quote_quantity, 0))
                            else 0
                        end
                    ), 0) as fiat_sells
                from canonical_events
                """
            ).fetchone()
        return (row[0] or Decimal("0")) - (row[1] or Decimal("0"))

    def _current_missing_price_assets(self) -> list[str]:
        portfolio = PortfolioService(self.store)
        prices = portfolio._latest_prices()
        missing: set[str] = set()
        with self.store.connect() as con:
            rows = con.execute(
                """
                select account, upper(asset) as asset, sum(delta_quantity) as quantity
                from balance_ledger
                group by account, upper(asset)
                order by account, asset
                """
            ).fetchall()
        for account, asset, quantity in rows:
            amount = quantity or Decimal("0")
            symbol = str(asset).upper()
            if portfolio._is_zero_quantity(amount):
                continue
            if portfolio._is_transfer_counterparty_account(str(account)):
                continue
            if portfolio._is_current_source_excluded_account(str(account), symbol):
                continue
            if fiat_price_point(symbol) is not None or prices.get(symbol) is not None:
                continue
            if self._is_unpriced_live_token_identifier(symbol):
                continue
            missing.add(symbol)
        return sorted(missing)

    @staticmethod
    def _is_unpriced_live_token_identifier(symbol: str) -> bool:
        normalized = str(symbol or "").strip().upper()
        if "..." in normalized:
            return True
        if len(normalized) >= 24 and normalized.replace("_", "").replace("-", "").isalnum():
            return True
        return False

    def _live_reconciliation_status(
        self,
        groups: list[object],
        source_live: dict[str, dict[str, object]],
    ) -> CockpitLiveReconciliation:
        stored = self._stored_live_anchor_summary()
        blocker_count = 0
        warning_count = 0
        missing_wallets: list[str] = []
        expected_zero_value = Decimal("0")
        live_unverified_value = Decimal("0")
        for group in groups:
            if group.current_status == "known_wallet_missing_import":
                live_value = source_live.get(group.source_group, {}).get("live_value_eur")
                delta = None if live_value is None else live_value - group.value_eur
                if delta is None or abs(delta) >= Decimal("5"):
                    blocker_count += 1
                    missing_wallets.extend(account.account for account in group.accounts)
                continue
            if group.source_group in PortfolioService.EXPECTED_ZERO_SOURCES:
                expected_zero_value += group.value_eur
                live_value = source_live.get(group.source_group, {}).get("live_value_eur")
                value_for_severity = (
                    -group.value_eur
                    if live_value is None
                    else live_value - group.value_eur
                )
                if abs(value_for_severity) < PortfolioService.EXPECTED_ZERO_DUST_INFO_VALUE_EUR:
                    continue
                if abs(value_for_severity) >= PortfolioService.EXPECTED_ZERO_BLOCKER_VALUE_EUR:
                    blocker_count += 1
                else:
                    warning_count += 1
                continue
            live_unverified_value += group.value_eur
        display_warning_count = sum(
            1 for group in groups if self._source_display_warning(group, source_live) is not None
        )
        warning_count += display_warning_count
        if stored["connectors"] == 0:
            warning_count += 1
        status = "ok"
        if blocker_count:
            status = "blocked"
        elif warning_count:
            status = "warning"
        return CockpitLiveReconciliation(
            status=status,
            stored_live_connectors=stored["connectors"],
            stored_live_assets=stored["assets"],
            latest_live_snapshot_at=stored["latest_at"],
            missing_wallets=sorted(set(missing_wallets)),
            expected_zero_sources_open_value_eur=expected_zero_value,
            live_unverified_value_eur=live_unverified_value,
            blocker_count=blocker_count,
            warning_count=warning_count,
            detail=(
                "Verwendet nur gespeicherte Live-Balance-Snapshots; externe "
                "Connectoren werden beim Cockpit-Laden nicht abgefragt. "
                "Die Cockpit-Zeile ist eine verdichtete Vorpruefung; die "
                "vollstaendige Reconciliation-Tabelle bleibt in der Portfolio-"
                "Detailansicht."
            ),
        )

    def _stored_live_anchor_summary(self) -> dict[str, object]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    connector_id,
                    count(*)::integer as assets,
                    max(fetched_at) as latest_at
                from portfolio_live_balance_snapshots
                where upper(asset) not in (
                    select * from unnest(?)
                )
                  and fetched_at = (
                    select max(latest.fetched_at)
                    from portfolio_live_balance_snapshots latest
                    where latest.connector_id = portfolio_live_balance_snapshots.connector_id
                  )
                group by connector_id
                """
                ,
                [list(PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS)],
            ).fetchall()
        current_rows = [
            row
            for row in rows
            if self._live_snapshot_at_is_current(str(row[0]), row[2])
        ]
        return {
            "connectors": len({str(row[0]) for row in current_rows}),
            "assets": sum(int(row[1] or 0) for row in current_rows),
            "latest_at": max((row[2] for row in current_rows), default=None),
        }

    def _connector_live_snapshot_is_current(self, connector_id: str) -> bool:
        latest_at = self._latest_live_snapshot_at(connector_id)
        return self._live_snapshot_at_is_current(connector_id, latest_at)

    def _live_snapshot_at_is_current(self, connector_id: str, latest_at: datetime | None) -> bool:
        if latest_at is None:
            return False
        if connector_id not in self.CEX_LIVE_CONNECTORS:
            return True
        comparable = latest_at
        if comparable.tzinfo is None:
            comparable = comparable.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - comparable).days <= self.LIVE_STALE_AFTER_DAYS

    def _latest_live_snapshot_at(self, connector_id: str) -> datetime | None:
        if connector_id in self._latest_live_snapshot_cache:
            return self._latest_live_snapshot_cache[connector_id]
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
            self._latest_live_snapshot_cache[connector_id] = None
            return None
        self._latest_live_snapshot_cache[connector_id] = row[0]
        return row[0]

    def _source_display_value(
        self,
        group: object,
        source_live: dict[str, dict[str, object]],
    ) -> Decimal:
        live_value = source_live.get(group.source_group, {}).get("live_value_eur")
        if live_value is None:
            return group.value_eur
        return live_value  # type: ignore[return-value]

    def _source_current_status(
        self,
        group: object,
        source_live: dict[str, dict[str, object]],
    ) -> str:
        if group.source_group == "Jup Wallet GmHY...3yu":
            live_value = source_live.get(group.source_group, {}).get("live_value_eur")
            if live_value is not None and abs(live_value - group.value_eur) < Decimal("5"):  # type: ignore[operator]
                return "live_anchor_reconciled"
        return group.current_status

    def _source_display_warning(
        self,
        group: object,
        source_live: dict[str, dict[str, object]],
    ) -> str | None:
        live_value = source_live.get(group.source_group, {}).get("live_value_eur")
        if live_value is None:
            return None
        delta = live_value - group.value_eur  # type: ignore[operator]
        if (
            group.source_group == "Bitget"
            and abs(live_value) < Decimal("1")  # type: ignore[arg-type]
            and abs(delta) < Decimal("10")
        ):
            return "API-Dust; steuerliche Klaerung laeuft ueber den vollstaendigen Bitget-Export."
        if group.source_group == "Binance":
            return (
                "Livewert aus gespeicherten Binance-API-Snapshots inkl. "
                "Spot/Earn/Product; Ledger-Delta bleibt separat zu klaeren."
            )
        if abs(delta) >= Decimal("5"):
            return "API-Livewert und steuerlicher Ledger weichen wesentlich ab."
        return None

    def _pipeline_status(self) -> CockpitPipelineStatus:
        batches = self.store.list_import_batches()
        with self.store.connect() as con:
            row = con.execute(
                "select max(event_time) from canonical_events"
            ).fetchone()
        latest_batch = batches[0] if batches else None
        return CockpitPipelineStatus(
            last_import_at=latest_batch.created_at if latest_batch is not None else None,
            last_import_source=latest_batch.source if latest_batch is not None else None,
            last_canonical_event_at=row[0],
            import_batches=len(batches),
        )

    def _tasks(
        self,
        review: object,
        price_coverage: CockpitPriceCoverage,
        live: CockpitLiveReconciliation,
    ) -> list[CockpitTask]:
        tasks: list[CockpitTask] = []
        current_open = review.issues_current_open if review.issues_current_open is not None else review.issues_open
        if current_open:
            top_issue = review.issues[0] if review.issues else None
            tasks.append(
                CockpitTask(
                    priority="high",
                    title="Review-Issues klaeren",
                    detail=top_issue.message if top_issue is not None else "Offene Review-Issues blockieren den Abschluss.",
                    target="review",
                    count=current_open,
                )
            )
        if price_coverage.missing_assets or price_coverage.missing_event_price_groups:
            tasks.append(
                CockpitTask(
                    priority="high",
                    title="Preisdeckung vervollstaendigen",
                    detail=(
                        f"Fehlende aktuelle Assets: {', '.join(price_coverage.missing_assets) or 'keine'}; "
                        f"historische Preisgruppen: {price_coverage.missing_event_price_groups}."
                    ),
                    target="portfolio",
                    count=len(price_coverage.missing_assets) + price_coverage.missing_event_price_groups,
                )
            )
        if live.status != "ok":
            tasks.append(
                CockpitTask(
                    priority="medium" if live.status == "warning" else "high",
                    title="Live-Abgleich pruefen",
                    detail=(
                        f"{live.blocker_count} Blocker, {live.warning_count} Warnungen; "
                        f"gespeicherte Connector-Anker: {live.stored_live_connectors}."
                    ),
                    target="portfolio",
                    count=live.blocker_count + live.warning_count,
                )
            )
        if review.issues_historical_open:
            tasks.append(
                CockpitTask(
                    priority="low",
                    title="Historische Punkte dokumentieren",
                    detail="Historische offene Punkte bleiben sichtbar, blockieren aber nicht zwingend den aktuellen Export.",
                    target="review",
                    count=review.issues_historical_open,
                )
            )
        return tasks[:3]

    def _share(self, value: Decimal, total: Decimal) -> Decimal:
        if total == 0:
            return Decimal("0.00")
        return (value / total * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
