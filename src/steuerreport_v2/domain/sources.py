from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import re

from steuerreport_v2.contracts.sources import (
    BinanceEvidenceAssetReport,
    BinanceEvidenceEventSummary,
    BinanceEvidenceHistoryRequirement,
    BinanceEvidenceImportBatch,
    BinanceEarnHistoryPreflightReport,
    BinanceEarnHistoryProduct,
    BinanceReconciliationEvidenceReport,
    SourceAccountStatus,
    SourceAssetStatus,
    SourceConnectorDiagnostic,
    SourceConnectorDiagnosticsReport,
    SourceDetail,
    SourceEventPreview,
    SourceLiveComponent,
    SourceOverview,
    SourceOverviewHealth,
    SourceOverviewHealthIssue,
    SourceReconciliationAssetRow,
    SourceReconciliationBreakdown,
    SourceReconciliationStatus,
    SourceStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.jupiter import JupiterTokenService
from steuerreport_v2.domain.price_lookup import fiat_price_point
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.secrets import resolve_secret_value, secret_metadata


class SourceService:
    CONNECTOR_BY_SOURCE = {
        "Bitget": "bitget",
        "Pionex": "pionex",
        "Jup Wallet GmHY...3yu": "jup_wallet",
        "Solana Wallet 6K9n7y...qEwP": "solana_wallet",
        "Binance": "binance",
    }
    EXPECTED_ZERO_SOURCES = {"Bitget", "Pionex"}
    CEX_CONNECTORS = {"binance", "bitget", "pionex"}
    CEX_REQUIRED_SECRET_KEYS = {
        "binance": ("api_key", "api_secret"),
        "bitget": ("api_key", "api_secret", "passphrase"),
        "pionex": ("api_key", "api_secret"),
    }
    DUST_DELTA_VALUE_EUR = Decimal("5")
    LIVE_STALE_AFTER_DAYS = 3

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._jupiter_metadata_cache = None
        self._import_batches_cache: list[object] | None = None
        self._raw_payload_cache: dict[str, dict[str, object]] | None = None

    def overview(self) -> SourceOverview:
        portfolio_sources = PortfolioService(self.store).source_overview()
        display_total = sum(
            (
                self._display_value_for_group(group)[0]
                for group in portfolio_sources.groups
            ),
            Decimal("0"),
        )
        source_statuses = [
            self._status_for_group(group, display_total)
            for group in portfolio_sources.groups
        ]
        return SourceOverview(
            generated_at=datetime.now(timezone.utc),
            total_value_eur=display_total,
            sources=source_statuses,
            health=self._overview_health(source_statuses),
            methodology=(
                "Read-only Quellenuebersicht aus Portfolio-Quellengruppen, "
                "Review-Gate, Import-Batches und persistierten Live-Snapshot-"
                "Ankern. Wenn ein gespeicherter Live-Snapshot vorhanden ist, "
                "wird dieser als Anzeigenwert genutzt; Ledger und Delta bleiben "
                "je Quelle sichtbar. Externe Connectoren werden nicht abgefragt."
            ),
        )

    def detail(self, source_id: str) -> SourceDetail | None:
        overview = PortfolioService(self.store).source_overview()
        group = next(
            (
                item
                for item in overview.groups
                if self.source_id(item.source_group) == source_id
            ),
            None,
        )
        if group is None:
            return None

        display_total = sum((self._display_value_for_group(item)[0] for item in overview.groups), Decimal("0"))
        status = self._status_for_group(group, display_total)
        reconciliation = self._reconciliation_for_group(group)
        events = self._recent_events_for_group(group, limit=25)
        issues = self._issues_for_group(group)
        evidence_refs = self._evidence_refs(group, reconciliation)
        assets = self._display_assets_for_group(group, status.value_eur)
        return SourceDetail(
            **status.model_dump(),
            assets=assets,
            reconciliation=reconciliation,
            recent_events=events,
            open_issues=issues,
            evidence_refs=evidence_refs,
            full_accounts=[account.account for account in group.accounts],
            methodology=(
                "Detailansicht fuer eine lesbare Quelle. Wallet-Adressen werden "
                "im UI gekuerzt, bleiben hier aber als full_accounts und in den "
                "Account-Zeilen vollstaendig verfuegbar."
            ),
        )

    def connector_diagnostics(self) -> SourceConnectorDiagnosticsReport:
        overview = PortfolioService(self.store).source_overview()
        groups_by_label = {item.source_group: item for item in overview.groups}
        diagnostics: list[SourceConnectorDiagnostic] = []
        for label, connector_id in sorted(self.CONNECTOR_BY_SOURCE.items(), key=lambda item: item[0]):
            group = groups_by_label.get(label)
            source_id = self.source_id(label)
            stats = self._live_snapshot_stats(connector_id)
            age_days = self._live_age_days(stats["last_snapshot_at"])
            connector_type = "cex" if connector_id in self.CEX_CONNECTORS else "wallet"
            credential = (
                self._cex_credential_diagnostic(connector_id)
                if connector_type == "cex"
                else {
                    "status": "not_required",
                    "issue": None,
                    "keys_present": 0,
                    "keys_required": 0,
                    "updated_at_latest": None,
                }
            )
            status, message, next_action = self._connector_diagnostic_status(
                connector_type=connector_type,
                credential_status=str(credential["status"]),
                credential_issue=credential["issue"] if isinstance(credential["issue"], str) else None,
                last_snapshot_at=stats["last_snapshot_at"],
                age_days=age_days,
                group_value=group.value_eur if group is not None else Decimal("0"),
            )
            diagnostics.append(
                SourceConnectorDiagnostic(
                    source_id=source_id,
                    label=label,
                    connector_id=connector_id,
                    connector_type=connector_type,
                    status=status,
                    credential_status=str(credential["status"]),
                    credential_issue=credential["issue"] if isinstance(credential["issue"], str) else None,
                    credential_keys_present=int(credential["keys_present"]),
                    credential_keys_required=int(credential["keys_required"]),
                    credential_updated_at_latest=credential["updated_at_latest"]
                    if isinstance(credential["updated_at_latest"], datetime)
                    else None,
                    last_snapshot_at=stats["last_snapshot_at"],
                    last_snapshot_age_days=age_days,
                    last_snapshot_assets=int(stats["asset_count"]),
                    last_snapshot_value_eur=stats["value_eur"],
                    message=message,
                    next_action=next_action,
                )
            )
        return SourceConnectorDiagnosticsReport(
            generated_at=datetime.now(timezone.utc),
            diagnostics=diagnostics,
            missing_credentials=sum(
                1
                for item in diagnostics
                if item.credential_status in {"missing", "decrypt_failed", "error"}
            ),
            stale_snapshots=sum(
                1
                for item in diagnostics
                if item.last_snapshot_age_days is not None
                and item.last_snapshot_age_days > self.LIVE_STALE_AFTER_DAYS
            ),
            missing_snapshots=sum(1 for item in diagnostics if item.status == "missing_snapshot"),
            methodology=(
                "Read-only Connector-Diagnose. CEX-Credentials werden ueber den "
                "V1-Admin-Load-Pfad nur als entschluesselbar/nicht entschluesselbar "
                "geprueft; zusaetzlich werden V1-Settings-Metadaten ohne Secret-Werte "
                "gelesen. Secret-Werte werden nicht zurueckgegeben. Snapshot-Status "
                "stammt aus persistierten V2-Live-Snapshots und loest keine Exchange-"
                "Abfrage, FIFO-Buchung oder Ledger-Aenderung aus."
            ),
        )

    def reconciliation_breakdown(self, source_id: str) -> SourceReconciliationBreakdown | None:
        overview = PortfolioService(self.store).source_overview()
        group = next(
            (
                item
                for item in overview.groups
                if self.source_id(item.source_group) == source_id
            ),
            None,
        )
        if group is None:
            return None
        reconciliation = self._reconciliation_for_group(group)
        rows = self._reconciliation_asset_rows(group, reconciliation)
        connector_id = self.CONNECTOR_BY_SOURCE.get(group.source_group)
        live_components = self._stored_live_components(connector_id) if connector_id is not None else []
        severity = self._worst_severity([row.severity for row in rows] or [reconciliation.severity])
        return SourceReconciliationBreakdown(
            generated_at=datetime.now(timezone.utc),
            source_id=self.source_id(group.source_group),
            label=group.source_group,
            source_type=group.source_type,
            ledger_value_eur=reconciliation.ledger_value_eur,
            live_value_eur=reconciliation.live_value_eur,
            delta_value_eur=reconciliation.delta_value_eur,
            last_live_at=reconciliation.last_live_at,
            live_anchor_source=reconciliation.live_anchor_source,
            display_warning=self._display_warning_for_group(group, reconciliation),
            status=reconciliation.status,
            severity=severity,
            rows=rows,
            live_components=live_components,
            methodology=(
                "Read-only Asset-Drilldown aus V2-Ledger und gespeichertem "
                "API-Live-Snapshot. Deltas sind Pruefhinweise und erzeugen keine "
                "FIFO-, Ledger- oder Steuerkorrektur."
            ),
        )

    def binance_reconciliation_evidence(
        self,
        since: datetime | None = None,
        assets: list[str] | None = None,
    ) -> BinanceReconciliationEvidenceReport | None:
        since_at = since or datetime(2025, 1, 1, tzinfo=timezone.utc)
        selected_assets = sorted({asset.upper() for asset in (assets or ["JUP", "SOL", "EUR"])})
        breakdown = self.reconciliation_breakdown("binance")
        if breakdown is None:
            return None

        rows_by_asset = {row.asset.upper(): row for row in breakdown.rows}
        components_by_asset: dict[str, list[SourceLiveComponent]] = {}
        for component in breakdown.live_components:
            components_by_asset.setdefault(component.asset.upper(), []).append(component)
        summaries_by_asset = self._binance_event_summaries(since_at, selected_assets)
        history_requirements = self._binance_history_requirements(
            selected_assets,
            components_by_asset,
            summaries_by_asset,
        )
        asset_reports: list[BinanceEvidenceAssetReport] = []
        for asset in selected_assets:
            row = rows_by_asset.get(asset)
            summaries = summaries_by_asset.get(asset, [])
            unknown_count = sum(item.event_count for item in summaries if item.event_type == "unknown")
            live_components = components_by_asset.get(asset, [])
            asset_reports.append(
                BinanceEvidenceAssetReport(
                    asset=asset,
                    ledger_quantity=row.ledger_quantity if row is not None else Decimal("0"),
                    ledger_value_eur=row.ledger_value_eur if row is not None else Decimal("0"),
                    live_quantity=row.live_quantity if row is not None else None,
                    live_value_eur=row.live_value_eur if row is not None else None,
                    delta_quantity=row.delta_quantity if row is not None else None,
                    delta_value_eur=row.delta_value_eur if row is not None else None,
                    live_components=live_components,
                    event_summaries=summaries,
                    unknown_event_count=unknown_count,
                    suspected_gap=self._binance_suspected_gap(
                        asset,
                        live_components,
                        unknown_count,
                        row.status if row is not None else None,
                        history_requirements,
                    ),
                    next_action=self._binance_evidence_next_action(
                        asset,
                        live_components,
                        unknown_count,
                        history_requirements,
                    ),
                )
            )
        return BinanceReconciliationEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            since=since_at,
            assets=selected_assets,
            ledger_value_eur=breakdown.ledger_value_eur,
            live_value_eur=breakdown.live_value_eur,
            delta_value_eur=breakdown.delta_value_eur,
            last_live_at=breakdown.last_live_at,
            import_batches=self._binance_import_batches(),
            history_requirements=history_requirements,
            asset_reports=sorted(
                asset_reports,
                key=lambda item: (-abs(item.delta_value_eur or Decimal("0")), item.asset),
            ),
            methodology=(
                "Read-only Binance-Evidence-Report: vergleicht den steuerlichen "
                "V2-Ledger mit gespeicherten Binance-API-Live-Komponenten und "
                "Canonical-Event-Aggregaten seit dem Stichtag. Der Report erzeugt "
                "keine Ledger-, FIFO- oder Preisbuchungen."
            ),
        )

    def binance_earn_history_preflight(self) -> BinanceEarnHistoryPreflightReport:
        components = [
            component
            for component in self._stored_live_components("binance")
            if str(component.account_type or "").startswith("simple_earn")
        ]
        grouped: dict[tuple[str, str, str | None, str | None], list[SourceLiveComponent]] = {}
        for component in components:
            grouped.setdefault(
                (
                    component.asset,
                    str(component.account_type or ""),
                    component.product_id,
                    component.position_id,
                ),
                [],
            ).append(component)
        products: list[BinanceEarnHistoryProduct] = []
        for (asset, account_type, product_id, position_id), items in sorted(grouped.items()):
            quantity = sum((item.quantity for item in items), Decimal("0"))
            value = None
            values = [item.value_eur for item in items if item.value_eur is not None]
            if values:
                value = sum(values, Decimal("0"))
            evidence_refs = self._matching_binance_history_batches(
                self._earn_requirement_for_account_type(account_type),
                [item.filename for item in self._binance_import_batches()],
            )
            event_types = sorted(
                {
                    str(item.event_type)
                    for item in items
                    if item.event_type is not None
                }
            )
            import_status = "covered" if evidence_refs else "missing"
            products.append(
                BinanceEarnHistoryProduct(
                    asset=asset,
                    account_type=account_type,
                    product_id=product_id,
                    position_id=position_id,
                    live_quantity=quantity,
                    live_value_eur=value,
                    live_event_types=event_types,
                    required_movements=self._required_earn_movements(account_type),
                    import_status=import_status,
                    evidence_refs=evidence_refs,
                    api_probe_payload={
                        "connector_id": "binance",
                        "asset": asset,
                        "account_type": account_type,
                        "product_id": product_id,
                        "position_id": position_id,
                    },
                    next_action=(
                        "Passende Binance Simple-Earn-Historie importieren/API-historisieren; "
                        "Subscriptions und Redemptions als interne Produktumbuchungen pruefen, "
                        "Rewards separat als Ertrag pruefen."
                    ),
                )
            )
        missing = sum(1 for item in products if item.import_status == "missing")
        partial = sum(1 for item in products if item.import_status == "partial")
        covered = sum(1 for item in products if item.import_status == "covered")
        status = "ok" if products and missing == 0 and partial == 0 else "missing_history"
        if not products:
            status = "no_live_earn_products"
        return BinanceEarnHistoryPreflightReport(
            generated_at=datetime.now(timezone.utc),
            status=status,
            products=products,
            missing_products=missing,
            partial_products=partial,
            covered_products=covered,
            connector_endpoint="/api/v1/connectors/cex/balances-preview",
            methodology=(
                "Read-only Preflight aus gespeicherten Binance-Live-Produktkomponenten "
                "und vorhandenen Binance-Import-Batches. Der Report definiert den "
                "notwendigen History-Import fuer Simple Earn, erzeugt aber keine "
                "Canonical Events, FIFO-Lots oder Ledgerbuchungen."
            ),
        )

    @classmethod
    def source_id(cls, label: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        return slug or "source"

    def _status_for_group(self, group: object, total_value_eur: Decimal) -> SourceStatus:
        reconciliation = self._reconciliation_for_group(group)
        value_eur, value_basis = self._display_value_for_group(group)
        assets = self._display_assets_for_group(group, value_eur)
        live_age_days = self._live_age_days(reconciliation.last_live_at)
        open_price_issues = sum(
            1 for asset in assets if asset.value_eur == 0 and asset.asset.upper() != "EUR"
        )
        current_status = (
            reconciliation.status
            if (
                (
                    group.source_group == "Jup Wallet GmHY...3yu"
                    and reconciliation.status == "live_anchor_reconciled"
                )
                or (
                    group.source_group == "Binance"
                    and reconciliation.status == "reconciled_with_dust"
                )
            )
            else group.current_status
        )
        return SourceStatus(
            source_id=self.source_id(group.source_group),
            label=group.source_group,
            source_type=group.source_type,
            value_eur=value_eur,
            share_pct=self._share(value_eur, total_value_eur),
            account_count=group.account_count,
            asset_count=len(assets),
            position_count=group.position_count,
            current_status=current_status,
            value_basis=value_basis,
            last_imported_at=self._last_imported_at(group),
            last_live_at=reconciliation.last_live_at,
            live_age_days=live_age_days,
            live_freshness=self._live_freshness(reconciliation.last_live_at, live_age_days),
            ledger_value_eur=reconciliation.ledger_value_eur,
            live_value_eur=reconciliation.live_value_eur,
            delta_value_eur=reconciliation.delta_value_eur,
            live_anchor_source=reconciliation.live_anchor_source,
            display_warning=self._display_warning_for_group(group, reconciliation),
            open_price_issues=open_price_issues,
            open_reconciliation_issues=1 if reconciliation.severity in {"blocker", "warning"} else 0,
            import_batches=self._import_batch_count(group),
            last_evidence_files=self._last_evidence_files(group),
            top_assets=assets[:4],
            accounts=[
                SourceAccountStatus(
                    account=account.account,
                    display_account=self._short_account(account.account),
                    full_account=account.account,
                    value_eur=account.value_eur,
                    assets=account.assets,
                    position_count=account.position_count,
                )
                for account in group.accounts[:5]
            ],
            note=group.note,
        )

    def _overview_health(self, sources: list[SourceStatus]) -> SourceOverviewHealth:
        now = datetime.now(timezone.utc)
        live_connected = sum(1 for source in sources if source.last_live_at is not None)
        ledger_only = sum(1 for source in sources if source.value_basis == "ledger")
        stale_live = sum(
            1
            for source in sources
            if source.last_live_at is not None
            and self._live_snapshot_is_stale(source.last_live_at, now)
        )
        missing_live = sum(
            1
            for source in sources
            if self.CONNECTOR_BY_SOURCE.get(source.label) is not None
            and source.last_live_at is None
        )
        warning_sources = sum(
            1
            for source in sources
            if source.display_warning is not None
            or source.open_reconciliation_issues > 0
            or source.open_price_issues > 0
        )
        blocker_sources = sum(
            1
            for source in sources
            if source.open_reconciliation_issues > 0
            and source.current_status
            in {
                "wallet_history_partially_imported",
                "expected_live_zero",
                "known_wallet_missing_import",
            }
        )
        total_reconciliation_issues = sum(source.open_reconciliation_issues for source in sources)
        total_price_issues = sum(source.open_price_issues for source in sources)
        issues = self._overview_health_issues(sources)
        if any(issue.severity == "blocker" for issue in issues):
            status = "blocked"
            detail = "Mindestens eine Quelle hat einen wesentlichen Ledger-vs-Live-Abgleichspunkt."
        elif issues:
            status = "warning"
            detail = "Quellen sind lesbar, aber Live-Abdeckung, Snapshot-Alter oder Issues muessen geprueft werden."
        else:
            status = "ok"
            detail = "Alle angezeigten Quellen sind ohne offene Health-Hinweise."
        return SourceOverviewHealth(
            status=status,
            sources_count=len(sources),
            live_connected_sources=live_connected,
            ledger_only_sources=ledger_only,
            stale_live_sources=stale_live,
            warning_sources=warning_sources,
            blocker_sources=blocker_sources,
            missing_live_sources=missing_live,
            total_open_reconciliation_issues=total_reconciliation_issues,
            total_open_price_issues=total_price_issues,
            issues=issues,
            detail=detail,
        )

    def _overview_health_issues(self, sources: list[SourceStatus]) -> list[SourceOverviewHealthIssue]:
        issues: list[SourceOverviewHealthIssue] = []
        for source in sources:
            if self.CONNECTOR_BY_SOURCE.get(source.label) is not None and source.last_live_at is None:
                issues.append(
                    SourceOverviewHealthIssue(
                        source_id=source.source_id,
                        label=source.label,
                        severity="warning",
                        issue="missing_live_anchor",
                        detail="Fuer diese konfigurierte Quelle ist kein gespeicherter Live-Snapshot vorhanden.",
                        next_action="Quelle per API abfragen oder vorhandenen Live-Beleg pruefen.",
                    )
                )
            elif source.live_freshness == "stale":
                issues.append(
                    SourceOverviewHealthIssue(
                        source_id=source.source_id,
                        label=source.label,
                        severity="warning",
                        issue="stale_live_snapshot",
                        detail=f"Der letzte gespeicherte Live-Snapshot ist {source.live_age_days} Tage alt.",
                        next_action="Alle konfigurierten Quellen per API aktualisieren.",
                        live_age_days=source.live_age_days,
                        last_live_at=source.last_live_at,
                    )
                )
            if source.open_reconciliation_issues > 0:
                severity = (
                    "blocker"
                    if source.current_status
                    in {
                        "wallet_history_partially_imported",
                        "expected_live_zero",
                        "known_wallet_missing_import",
                    }
                    else "warning"
                )
                issues.append(
                    SourceOverviewHealthIssue(
                        source_id=source.source_id,
                        label=source.label,
                        severity=severity,
                        issue="reconciliation_issue",
                        detail=f"{source.open_reconciliation_issues} Reconciliation-Hinweis(e) fuer diese Quelle.",
                        next_action="Quellen-Drilldown und Ledger-vs-Live-Delta pruefen.",
                        live_age_days=source.live_age_days,
                        last_live_at=source.last_live_at,
                    )
                )
            if source.open_price_issues > 0:
                issues.append(
                    SourceOverviewHealthIssue(
                        source_id=source.source_id,
                        label=source.label,
                        severity="warning",
                        issue="price_issue",
                        detail=f"{source.open_price_issues} Asset(s) ohne verwertbaren Preis in dieser Quelle.",
                        next_action="Preisdeckung pruefen und fehlende Preise nachziehen.",
                        live_age_days=source.live_age_days,
                        last_live_at=source.last_live_at,
                    )
                )
            if source.display_warning is not None:
                issues.append(
                    SourceOverviewHealthIssue(
                        source_id=source.source_id,
                        label=source.label,
                        severity="warning",
                        issue="display_warning",
                        detail=source.display_warning,
                        next_action="Quelle im Detail pruefen; Deltas nicht automatisch als FIFO-Korrektur buchen.",
                        live_age_days=source.live_age_days,
                        last_live_at=source.last_live_at,
                    )
                )
        severity_order = {"blocker": 0, "warning": 1, "info": 2}
        issue_order = {"reconciliation_issue": 0, "display_warning": 1, "price_issue": 2, "missing_live_anchor": 3, "stale_live_snapshot": 4}
        return sorted(
            issues,
            key=lambda item: (
                severity_order.get(item.severity, 9),
                issue_order.get(item.issue, 9),
                item.label,
            ),
        )

    def _live_snapshot_is_stale(self, last_live_at: datetime, now: datetime) -> bool:
        comparable = last_live_at
        if comparable.tzinfo is None:
            comparable = comparable.replace(tzinfo=timezone.utc)
        return (now - comparable).days > self.LIVE_STALE_AFTER_DAYS

    def _live_age_days(self, last_live_at: datetime | None) -> int | None:
        if last_live_at is None:
            return None
        comparable = last_live_at
        if comparable.tzinfo is None:
            comparable = comparable.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - comparable).days)

    def _live_freshness(self, last_live_at: datetime | None, age_days: int | None) -> str:
        if last_live_at is None or age_days is None:
            return "missing"
        if age_days > self.LIVE_STALE_AFTER_DAYS:
            return "stale"
        return "fresh"

    def _connector_diagnostic_status(
        self,
        *,
        connector_type: str,
        credential_status: str,
        credential_issue: str | None,
        last_snapshot_at: datetime | None,
        age_days: int | None,
        group_value: Decimal,
    ) -> tuple[str, str, str]:
        if credential_status == "decrypt_failed":
            return (
                "credential_decrypt_failed",
                "API-Zugangsdaten sind als Secret-Zeilen vorhanden, aber mit dem aktuellen Master-Key nicht entschluesselbar.",
                "Passenden alten Master-Key wiederherstellen oder die API-Credentials neu speichern; danach Quellen per API abfragen.",
            )
        if credential_status == "missing":
            return (
                "missing_credentials",
                "API-Zugangsdaten sind in V1 aktuell nicht vollstaendig gespeichert.",
                "API-Key/Secret fuer diese Quelle in V1/V2-Admin neu hinterlegen und danach alle Quellen per API abfragen.",
            )
        if credential_status == "error":
            return (
                "credential_check_failed",
                f"Credential-Status konnte nicht gelesen werden{': ' + credential_issue if credential_issue else ''}.",
                "V1-Admin-Service und Secret-Key-Konfiguration pruefen; keine Live-Werte als frisch annehmen.",
            )
        if last_snapshot_at is None:
            return (
                "missing_snapshot",
                "Fuer diese konfigurierte Quelle gibt es keinen gespeicherten Live-Snapshot.",
                "Quelle per API abfragen und den danach gespeicherten Snapshot gegen den Ledger pruefen.",
            )
        if age_days is not None and age_days > self.LIVE_STALE_AFTER_DAYS:
            return (
                "stale_snapshot",
                f"Der letzte Live-Snapshot ist {age_days} Tage alt.",
                "Alle konfigurierten Quellen per API aktualisieren; alte Live-Werte nicht als aktuellen Bestand auslegen.",
            )
        if connector_type == "cex" and abs(group_value) < Decimal("1"):
            return (
                "fresh_zero_or_dust",
                "Credential-Check ist ok und der gespeicherte Live-Snapshot ist frisch; Ledgerwert liegt auf Null-/Dust-Niveau.",
                "Als Beleg sichtbar halten, aber nicht automatisch als FIFO-Korrektur buchen.",
            )
        return (
            "fresh",
            "Credential-Check und gespeicherter Live-Snapshot sind aktuell.",
            "Ledger-vs-Live-Delta im Quellen-Drilldown pruefen; keine automatische Steuerkorrektur.",
        )

    def _cex_credential_diagnostic(self, connector_id: str) -> dict[str, object]:
        required_keys = self.CEX_REQUIRED_SECRET_KEYS.get(connector_id, ())
        setting_keys = [f"secret.cex.{connector_id}.{suffix}" for suffix in required_keys]
        meta = secret_metadata(self.store, setting_keys)
        values = {key.rsplit(".", 1)[-1]: resolve_secret_value(self.store, key) for key in setting_keys}
        api_key = values.get("api_key", "")
        api_secret = values.get("api_secret", "")
        passphrase = values.get("passphrase", "")
        requires_passphrase = "passphrase" in self.CEX_REQUIRED_SECRET_KEYS.get(connector_id, ())
        required_present = int(meta["keys_present"]) >= int(meta["keys_required"])
        if api_key and api_secret:
            if requires_passphrase and not passphrase:
                return {**meta, "status": "missing", "issue": "passphrase_missing_or_not_decryptable"}
            return {**meta, "status": "configured", "issue": None}
        if required_present:
            return {**meta, "status": "decrypt_failed", "issue": "secret_rows_present_but_empty_after_decrypt"}
        return {**meta, "status": "missing", "issue": "secret_rows_missing"}

    def _cex_credential_status(self, connector_id: str) -> str:
        return str(self._cex_credential_diagnostic(connector_id)["status"])

    def _parse_datetime(self, value: object) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _live_snapshot_stats(self, connector_id: str) -> dict[str, object]:
        prices = PortfolioService(self.store)._latest_prices()
        with self.store.connect() as con:
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
                """,
                [connector_id, connector_id],
            ).fetchall()
        if not rows:
            return {
                "last_snapshot_at": None,
                "asset_count": 0,
                "value_eur": None,
            }
        fetched_at = rows[0][2]
        value = Decimal("0")
        asset_count = 0
        for asset, quantity, _fetched_at in rows:
            symbol = str(asset).upper()
            if symbol in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                continue
            asset_count += 1
            price = fiat_price_point(symbol) or prices.get(symbol)
            if price is not None:
                value += (quantity or Decimal("0")) * price.price_eur
        return {
            "last_snapshot_at": fetched_at,
            "asset_count": asset_count,
            "value_eur": value,
        }

    def _reconciliation_for_group(self, group: object) -> SourceReconciliationStatus:
        connector_id = self.CONNECTOR_BY_SOURCE.get(group.source_group)
        live_value = None
        last_live_at = None
        live_anchor_source = None
        if connector_id is not None:
            live_value, last_live_at = self._stored_live_value(connector_id)
            live_anchor_source = self._stored_live_source(connector_id)
        delta = None if live_value is None else live_value - group.value_eur
        severity = "info"
        status = "ledger_current_needs_live_anchor"
        next_action = "Live-Anker fuer diese Quelle speichern oder Detailbeleg pruefen."
        if group.source_group in self.EXPECTED_ZERO_SOURCES:
            status = "expected_live_zero"
            if live_value is None:
                delta = -group.value_eur
                severity = "blocker" if abs(group.value_eur) >= Decimal("5") else "warning"
            else:
                severity = "blocker" if abs(delta or Decimal("0")) >= Decimal("5") else "ok"
            next_action = "Live-Nullbestand gegen Ledger-Restbestand belegen und historische Abgaenge klaeren."
            if (
                group.source_group == "Bitget"
                and live_value is not None
                and abs(live_value) < Decimal("1")
                and abs(delta or Decimal("0")) < Decimal("10")
            ):
                status = "complete_export_strategy_reference_live_zero"
                severity = "info"
                next_action = (
                    "Kompletter Bitget-2024-Export liegt vor; Strategy.csv belegt "
                    "die Strategy-Kontexte. Live-Bestand ist nur API-Dust und wird "
                    "nicht als offene operative Reconciliation-Aufgabe gefuehrt."
                )
        elif group.current_status == "known_wallet_missing_import":
            if live_value is not None and abs(delta or Decimal("0")) < Decimal("5"):
                status = "live_anchor_reconciled"
                severity = "ok"
                next_action = "Live-Anker und V2-Ledger stimmen innerhalb der Reconciliation-Toleranz ueberein."
            else:
                status = "wallet_history_partially_imported"
                severity = "blocker"
                next_action = "Wallet-Historie vollstaendig importieren und Ledger-vs-Live-Differenz klaeren."
        elif group.source_group == "Binance" and self._has_product_live_snapshots("binance"):
            if live_value is not None and abs(delta or Decimal("0")) < self.DUST_DELTA_VALUE_EUR:
                status = "reconciled_with_dust"
                severity = "ok"
                next_action = (
                    "Binance-Livebestand und Ledger sind nur noch auf Dust-Level unterschiedlich; "
                    "als Beleg sichtbar halten, aber nicht als FIFO-Korrektur buchen."
                )
            else:
                status = "product_live_anchor_present"
                severity = "info"
                next_action = (
                    "Binance-Livebestand enthaelt Spot- und Earn-/Produktkonten; "
                    "Produktpositionen getrennt auditieren, nicht als fehlenden FIFO-Trade buchen."
                )
        elif live_value is not None:
            status = "live_anchor_present"
            severity = "warning" if abs(delta or Decimal("0")) >= Decimal("5") else "ok"
            next_action = "Delta pruefen, falls Live- und Ledgerwert wesentlich abweichen."
        return SourceReconciliationStatus(
            status=status,
            severity=severity,
            ledger_value_eur=group.value_eur,
            live_value_eur=live_value,
            delta_value_eur=delta,
            last_live_at=last_live_at,
            live_anchor_source=live_anchor_source,
            evidence=group.note,
            next_action=next_action,
        )

    def _display_warning_for_group(
        self,
        group: object,
        reconciliation: SourceReconciliationStatus,
    ) -> str | None:
        live_value = reconciliation.live_value_eur
        delta = reconciliation.delta_value_eur
        if live_value is None or delta is None:
            return None
        if (
            group.source_group == "Bitget"
            and reconciliation.status == "complete_export_strategy_reference_live_zero"
        ):
            return (
                "API-Livewert ist Dust; der komplette Bitget-2024-Export bleibt "
                "der steuerliche Beleg fuer den Restbestand."
            )
        if group.source_group == "Binance" and reconciliation.status == "reconciled_with_dust":
            return None
        if group.source_group == "Binance" and self._has_product_live_snapshots("binance"):
            return (
                "Anzeige nutzt gespeicherte Binance-API-Snapshots inklusive "
                "Spot/Earn/Product. Ledger-Delta bleibt offen und darf nicht als "
                "FIFO-Korrektur gebucht werden."
            )
        if abs(delta) >= Decimal("5"):
            return (
                "Anzeige nutzt gespeicherten API-Livewert; steuerlicher Ledger "
                "und Live-Anker weichen wesentlich ab."
            )
        return None

    def _has_product_live_snapshots(self, connector_id: str) -> bool:
        with self.store.connect() as con:
            row = con.execute(
                """
                select 1
                from portfolio_live_balance_snapshots
                where connector_id = ?
                  and coalesce(account_type, '') not in ('', 'spot')
                  and fetched_at = (
                    select max(fetched_at)
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                  )
                limit 1
                """,
                [connector_id, connector_id],
            ).fetchone()
        return row is not None

    def _reconciliation_asset_rows(
        self,
        group: object,
        reconciliation: SourceReconciliationStatus,
    ) -> list[SourceReconciliationAssetRow]:
        ledger_assets = {asset.asset: asset for asset in group.asset_summary}
        connector_id = self.CONNECTOR_BY_SOURCE.get(group.source_group)
        live_assets = self._stored_live_asset_breakdown(connector_id) if connector_id is not None else {}
        prices = PortfolioService(self.store)._latest_prices()
        rows: list[SourceReconciliationAssetRow] = []
        for asset in sorted(set(ledger_assets) | set(live_assets)):
            ledger = ledger_assets.get(asset)
            live = live_assets.get(asset)
            ledger_quantity = ledger.quantity if ledger is not None else Decimal("0")
            ledger_value = ledger.value_eur if ledger is not None else Decimal("0")
            live_quantity = live["quantity"] if live is not None else None
            price = fiat_price_point(asset) or prices.get(asset.upper())
            live_value = (
                None
                if live_quantity is None or price is None
                else live_quantity * price.price_eur
            )
            delta_quantity = None if live_quantity is None else live_quantity - ledger_quantity
            delta_value = None if live_value is None else live_value - ledger_value
            severity, status, next_action = self._asset_delta_status(
                group.source_group,
                delta_quantity,
                delta_value,
                ledger_value,
                live_quantity,
            )
            rows.append(
                SourceReconciliationAssetRow(
                    asset=asset,
                    ledger_quantity=ledger_quantity,
                    ledger_value_eur=ledger_value,
                    live_quantity=live_quantity,
                    live_value_eur=live_value,
                    delta_quantity=delta_quantity,
                    delta_value_eur=delta_value,
                    price_eur=price.price_eur if price is not None else None,
                    price_source=price.source if price is not None else None,
                    price_status=self._price_status(price.priced_at if price is not None else None),
                    live_components=int(live["components"]) if live is not None else 0,
                    live_account_types=sorted(live["account_types"]) if live is not None else [],
                    live_products=sorted(live["products"]) if live is not None else [],
                    status=status,
                    severity=severity,
                    next_action=next_action,
                )
            )
        return sorted(
            rows,
            key=lambda item: (
                {"blocker": 0, "warning": 1, "info": 2, "ok": 3}.get(item.severity, 9),
                -abs(item.delta_value_eur or item.ledger_value_eur),
                item.asset,
            ),
        )

    def _stored_live_asset_breakdown(
        self,
        connector_id: str | None,
    ) -> dict[str, dict[str, object]]:
        if connector_id is None:
            return {}
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, quantity, account_type, product_id, fetched_at
                from portfolio_live_balance_snapshots
                where connector_id = ?
                  and fetched_at = (
                    select max(fetched_at)
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                  )
                order by asset, account_type, product_id
                """,
                [connector_id, connector_id],
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for asset, quantity, account_type, product_id, _fetched_at in rows:
            symbol = str(asset).upper()
            if symbol in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                continue
            item = result.setdefault(
                symbol,
                {
                    "quantity": Decimal("0"),
                    "components": 0,
                    "account_types": set(),
                    "products": set(),
                },
            )
            item["quantity"] = item["quantity"] + (quantity or Decimal("0"))  # type: ignore[operator]
            item["components"] = int(item["components"]) + 1
            if account_type:
                item["account_types"].add(str(account_type))  # type: ignore[union-attr]
            if product_id:
                item["products"].add(str(product_id))  # type: ignore[union-attr]
        return result

    def _stored_live_components(self, connector_id: str | None) -> list[SourceLiveComponent]:
        if connector_id is None:
            return []
        prices = PortfolioService(self.store)._latest_prices()
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
        components: list[SourceLiveComponent] = []
        for asset, quantity, account_type, product_id, position_id, event_type in rows:
            symbol = str(asset).upper()
            if symbol in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                continue
            amount = quantity or Decimal("0")
            price = fiat_price_point(symbol) or prices.get(symbol)
            components.append(
                SourceLiveComponent(
                    asset=symbol,
                    quantity=amount,
                    value_eur=amount * price.price_eur if price is not None else None,
                    account_type=str(account_type) if account_type else None,
                    product_id=str(product_id) if product_id else None,
                    position_id=str(position_id) if position_id else None,
                    event_type=str(event_type) if event_type else None,
                    price_eur=price.price_eur if price is not None else None,
                    price_source=price.source if price is not None else None,
                )
            )
        return sorted(
            components,
            key=lambda item: (
                item.asset,
                str(item.account_type or ""),
                str(item.product_id or ""),
                -abs(item.value_eur or Decimal("0")),
            ),
        )

    def _binance_event_summaries(
        self,
        since: datetime,
        assets: list[str],
    ) -> dict[str, list[BinanceEvidenceEventSummary]]:
        if not assets:
            return {}
        placeholders = ", ".join(["?"] * len(assets))
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    date_part('year', event_time)::int as year,
                    upper(asset) as asset,
                    event_type,
                    nullif(account, '') as account,
                    count(*)::int as event_count,
                    coalesce(sum(quantity), 0) as quantity_sum
                from canonical_events
                where lower(source) = 'binance'
                  and event_time >= ?
                  and upper(asset) in ({placeholders})
                group by 1, 2, 3, 4
                order by 1, 2, 3, 4
                """,
                [since.replace(tzinfo=None), *assets],
            ).fetchall()
        result: dict[str, list[BinanceEvidenceEventSummary]] = {}
        for year, asset, event_type, account, event_count, quantity_sum in rows:
            symbol = str(asset).upper()
            result.setdefault(symbol, []).append(
                BinanceEvidenceEventSummary(
                    year=int(year),
                    asset=symbol,
                    event_type=str(event_type),
                    account=str(account) if account is not None else None,
                    event_count=int(event_count),
                    quantity_sum=quantity_sum or Decimal("0"),
                )
            )
        return result

    def _binance_import_batches(self) -> list[BinanceEvidenceImportBatch]:
        batches = [
            BinanceEvidenceImportBatch(
                filename=str(batch.filename or batch.batch_id),
                status=str(batch.status),
                created_at=batch.created_at,
            )
            for batch in self._import_batches()
            if batch.source.lower() in {"binance", "binance_simple_earn_api"}
        ]
        return sorted(batches, key=lambda item: item.created_at, reverse=True)[:12]

    def _binance_history_requirements(
        self,
        assets: list[str],
        components_by_asset: dict[str, list[SourceLiveComponent]],
        summaries_by_asset: dict[str, list[BinanceEvidenceEventSummary]],
    ) -> list[BinanceEvidenceHistoryRequirement]:
        batch_names = [item.filename for item in self._binance_import_batches()]
        requirements: list[BinanceEvidenceHistoryRequirement] = []
        for asset in assets:
            components = components_by_asset.get(asset, [])
            account_types = {str(component.account_type or "") for component in components}
            product_ids = sorted(
                {
                    str(component.product_id)
                    for component in components
                    if component.product_id is not None
                }
            )
            summaries = summaries_by_asset.get(asset, [])
            unknown_count = sum(item.event_count for item in summaries if item.event_type == "unknown")
            if "simple_earn_flexible" in account_types:
                requirements.append(
                    self._binance_history_requirement(
                        asset=asset,
                        account_type="simple_earn_flexible",
                        product_id=", ".join(product_ids) or None,
                        requirement="flexible_earn_subscription_redemption_reward_history",
                        batch_names=batch_names,
                        unknown_count=unknown_count,
                        recommended_source="Binance Simple Earn Flexible History/API fuer Subscriptions, Redemptions und Rewards.",
                    )
                )
            if "simple_earn_locked" in account_types:
                requirements.append(
                    self._binance_history_requirement(
                        asset=asset,
                        account_type="simple_earn_locked",
                        product_id=", ".join(product_ids) or None,
                        requirement="locked_earn_subscription_redemption_reward_history",
                        batch_names=batch_names,
                        unknown_count=unknown_count,
                        recommended_source="Binance Simple Earn Locked History/API fuer Subscriptions, Redemptions, Early Redemptions und Rewards.",
                    )
                )
            if asset == "EUR":
                requirements.append(
                    self._binance_history_requirement(
                        asset=asset,
                        account_type="spot",
                        product_id=None,
                        requirement="fiat_deposit_withdraw_buy_spend_history",
                        batch_names=batch_names,
                        unknown_count=unknown_count,
                        recommended_source="Binance Fiat Deposit/Withdraw/Buy/Spend Exporte plus Transaction-History-Spiegel.",
                    )
                )
        return sorted(
            requirements,
            key=lambda item: (
                {"missing": 0, "partial": 1, "covered": 2}.get(item.current_status, 9),
                item.asset,
                item.requirement,
            ),
        )

    def _binance_history_requirement(
        self,
        *,
        asset: str,
        account_type: str | None,
        product_id: str | None,
        requirement: str,
        batch_names: list[str],
        unknown_count: int,
        recommended_source: str,
    ) -> BinanceEvidenceHistoryRequirement:
        evidence_refs = self._matching_binance_history_batches(requirement, batch_names)
        if evidence_refs and unknown_count == 0:
            status = "covered"
            gap_reason = "Passende Import-Batches vorhanden und keine unknown Canonical Events fuer dieses Asset seit Stichtag."
        elif evidence_refs:
            status = "partial"
            gap_reason = "Passende Import-Batches vorhanden, aber unknown Canonical Events muessen noch gemappt werden."
        else:
            status = "missing"
            gap_reason = "Kein passender Binance-Historienimport fuer diese Live-Komponente erkennbar."
        return BinanceEvidenceHistoryRequirement(
            asset=asset,
            account_type=account_type,
            product_id=product_id,
            requirement=requirement,
            current_status=status,
            evidence_refs=evidence_refs,
            gap_reason=gap_reason,
            recommended_source=recommended_source,
        )

    def _matching_binance_history_batches(
        self,
        requirement: str,
        batch_names: list[str],
    ) -> list[str]:
        tokens_by_requirement = {
            "flexible_earn_subscription_redemption_reward_history": ("earn", "flexible"),
            "locked_earn_subscription_redemption_reward_history": ("earn", "locked"),
            "fiat_deposit_withdraw_buy_spend_history": ("fiat",),
        }
        tokens = tokens_by_requirement.get(requirement, ())
        if not tokens:
            return []
        if requirement in {
            "flexible_earn_subscription_redemption_reward_history",
            "locked_earn_subscription_redemption_reward_history",
        }:
            matches = [
                name
                for name in batch_names
                if (
                    all(token in name.lower() for token in tokens)
                    or "simple_earn" in name.lower()
                    or "simple-earn" in name.lower()
                    or "earn_history" in name.lower()
                )
            ]
        else:
            matches = [
                name
                for name in batch_names
                if all(token in name.lower() for token in tokens)
            ]
        if requirement == "fiat_deposit_withdraw_buy_spend_history":
            matches = [
                name
                for name in batch_names
                if any(token in name.lower() for token in ("fiat", "transaction-history"))
            ]
        return matches[:5]

    def _earn_requirement_for_account_type(self, account_type: str) -> str:
        if account_type == "simple_earn_locked":
            return "locked_earn_subscription_redemption_reward_history"
        return "flexible_earn_subscription_redemption_reward_history"

    def _required_earn_movements(self, account_type: str) -> list[str]:
        base = ["subscription", "redemption", "reward"]
        if account_type == "simple_earn_locked":
            return [*base, "early_redemption", "accrued_reward_snapshot"]
        return base

    def _binance_suspected_gap(
        self,
        asset: str,
        live_components: list[SourceLiveComponent],
        unknown_event_count: int,
        row_status: str | None,
        history_requirements: list[BinanceEvidenceHistoryRequirement] | None = None,
    ) -> str:
        account_types = {str(component.account_type or "") for component in live_components}
        if asset == "JUP" and "simple_earn_flexible" in account_types:
            if self._binance_requirement_has_evidence(
                history_requirements,
                asset,
                "flexible_earn_subscription_redemption_reward_history",
            ):
                return "earn_flexible_history_imported_mapping_review"
            return "missing_earn_flexible_history_or_product_mapping"
        if asset == "SOL" and "simple_earn_locked" in account_types:
            if self._binance_requirement_has_evidence(
                history_requirements,
                asset,
                "locked_earn_subscription_redemption_reward_history",
            ):
                return "locked_earn_history_imported_material_delta_review"
            return "missing_locked_earn_history_or_product_mapping"
        if asset == "EUR":
            return "missing_fiat_spend_or_conversion_mapping"
        if row_status == "missing_live_asset":
            return "ledger_only_not_in_live_snapshot"
        if unknown_event_count > 0:
            return "unknown_canonical_events_need_parser_mapping"
        return "no_specific_gap_detected"

    def _binance_evidence_next_action(
        self,
        asset: str,
        live_components: list[SourceLiveComponent],
        unknown_event_count: int,
        history_requirements: list[BinanceEvidenceHistoryRequirement] | None = None,
    ) -> str:
        account_types = {str(component.account_type or "") for component in live_components}
        if asset == "JUP" and "simple_earn_flexible" in account_types:
            if self._binance_requirement_has_evidence(
                history_requirements,
                asset,
                "flexible_earn_subscription_redemption_reward_history",
            ):
                return "JUP Simple-Earn-Harvest ist importiert; Restdelta und alte unknown Binance-Events als Mapping-/Dust-Pruefung halten."
            return "Binance Earn Flexible JUP-Historie exportieren/API-historisieren und Produktbewegungen als interne Umbuchungen pruefen."
        if asset == "SOL" and "simple_earn_locked" in account_types:
            if self._binance_requirement_has_evidence(
                history_requirements,
                asset,
                "locked_earn_subscription_redemption_reward_history",
            ):
                return "SOL Locked-Earn-Harvest ist importiert; materialisiertes Delta gegen Spot-, Redemption- und Produktwechsel-Historie pruefen."
            return "Binance Locked-Earn SOL Subscriptions, Redemptions und Rewards gegen Canonical Events abgleichen."
        if asset == "EUR":
            return "Fiat Buy/Deposit/Withdraw/Spend-Historie gegen EUR-Ledger und aktuelle Spot-Livekomponente abstimmen."
        if unknown_event_count > 0:
            return "Unknown Canonical Events anhand Raw Payload und Importprofil fachlich mappen."
        return "Delta dokumentiert halten und nur mit belegter Historie in FIFO/Ledger uebernehmen."

    def _binance_requirement_has_evidence(
        self,
        history_requirements: list[BinanceEvidenceHistoryRequirement] | None,
        asset: str,
        requirement: str,
    ) -> bool:
        if not history_requirements:
            return False
        return any(
            item.asset == asset
            and item.requirement == requirement
            and item.current_status in {"partial", "covered"}
            and bool(item.evidence_refs)
            for item in history_requirements
        )

    def _asset_delta_status(
        self,
        source_group: str,
        delta_quantity: Decimal | None,
        delta_value: Decimal | None,
        ledger_value: Decimal,
        live_quantity: Decimal | None,
    ) -> tuple[str, str, str]:
        if live_quantity is None:
            if abs(ledger_value) < self.DUST_DELTA_VALUE_EUR:
                return (
                    "info",
                    "ledger_only_dust",
                    "Kleinstwert ohne Live-Komponente; als Dust-/Airdrop-Rest dokumentiert halten.",
                )
            return (
                "info",
                "missing_live_asset",
                "Kein Live-Asset im gespeicherten Snapshot; Ledger-Historie und Connector-Abdeckung pruefen.",
            )
        if delta_quantity is not None and abs(delta_quantity) <= Decimal("0.00000001"):
            return (
                "ok",
                "quantity_reconciled",
                "Live-Menge und Ledger-Menge stimmen innerhalb der Toleranz ueberein.",
            )
        if delta_value is not None and abs(delta_value) < self.DUST_DELTA_VALUE_EUR:
            return (
                "info",
                "dust_delta",
                "Nur Dust-/Rundungsdelta unter 5 EUR; als Beleg sichtbar halten.",
            )
        severity = "warning"
        status = "material_live_ledger_delta"
        next_action = "Delta fachlich belegen; keine automatische FIFO- oder Ledger-Korrektur erzeugen."
        if (
            source_group == "Bitget"
            and live_quantity is not None
            and abs(live_quantity) <= Decimal("0.000001")
            and abs(delta_value if delta_value is not None else ledger_value) < Decimal("10")
        ):
            return (
                "info",
                "complete_export_strategy_reference_live_zero",
                "Kompletter Bitget-2024-Export liegt vor; API-Livebestand ist Dust. Keine kuenstliche Ausbuchung erzeugen.",
            )
        if source_group in self.EXPECTED_ZERO_SOURCES and abs(delta_value if delta_value is not None else ledger_value) >= Decimal("5"):
            severity = "blocker"
            status = "expected_zero_delta"
            next_action = "Expected-Zero-Quelle: historische Abgaenge oder Produktbuchungen mit Export/API belegen."
        if source_group == "Binance":
            next_action = (
                "Binance Spot/Earn/Product-Komponenten gegen Exporthistorie pruefen; "
                "Produktpositionen nicht als fehlenden FIFO-Trade buchen."
            )
        return severity, status, next_action

    def _worst_severity(self, values: list[str]) -> str:
        order = {"blocker": 0, "warning": 1, "info": 2, "ok": 3}
        return sorted(values, key=lambda value: order.get(value, 9))[0]

    def _display_value_for_group(self, group: object) -> tuple[Decimal, str]:
        connector_id = self.CONNECTOR_BY_SOURCE.get(group.source_group)
        if connector_id is None:
            return group.value_eur, "ledger"
        live_value, _ = self._stored_live_value(connector_id)
        if live_value is None:
            return group.value_eur, "ledger"
        return live_value, "live_api"

    def _display_assets_for_group(
        self,
        group: object,
        total_value_eur: Decimal,
    ) -> list[SourceAssetStatus]:
        connector_id = self.CONNECTOR_BY_SOURCE.get(group.source_group)
        if connector_id is not None:
            ledger_symbols = {str(asset.asset).upper() for asset in group.asset_summary}
            live_assets = self._stored_live_assets(connector_id, total_value_eur, ledger_symbols)
            if live_assets:
                return live_assets
        return [
            self._asset_status(asset, total_value_eur)
            for asset in group.asset_summary
        ]

    def _stored_live_assets(
        self,
        connector_id: str,
        total_value_eur: Decimal,
        ledger_symbols: set[str] | None = None,
    ) -> list[SourceAssetStatus]:
        ledger_symbols = ledger_symbols or set()
        prices = PortfolioService(self.store)._latest_prices()
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, sum(quantity), max(fetched_at)
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
        assets: list[SourceAssetStatus] = []
        for asset, quantity, fetched_at in rows:
            symbol = str(asset).upper()
            if symbol in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                continue
            amount = quantity or Decimal("0")
            price = fiat_price_point(symbol) or prices.get(symbol)
            if price is None and symbol not in ledger_symbols:
                continue
            value = amount * price.price_eur if price is not None else Decimal("0")
            assets.append(
                SourceAssetStatus(
                    asset=symbol,
                    quantity=amount,
                    value_eur=value,
                    share_pct=self._share(value, total_value_eur),
                    position_count=1,
                    price_status=self._price_status(price.priced_at if price is not None else None),
                    value_basis="live_api",
                    price_source=price.source if price is not None else None,
                    priced_at_latest=price.priced_at if price is not None else fetched_at,
                    **self._token_metadata_fields(symbol),
                )
            )
        return sorted(assets, key=lambda item: abs(item.value_eur), reverse=True)

    def _stored_live_value(self, connector_id: str) -> tuple[Decimal | None, datetime | None]:
        prices = PortfolioService(self.store)._latest_prices()
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, sum(quantity), max(fetched_at)
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
        if not rows:
            return None, None
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
        return total, latest_at

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

    def _asset_status(self, asset: object, total_value_eur: Decimal) -> SourceAssetStatus:
        return SourceAssetStatus(
            asset=asset.asset,
            quantity=asset.quantity,
            value_eur=asset.value_eur,
            share_pct=self._share(asset.value_eur, total_value_eur),
            position_count=asset.position_count,
            value_basis="ledger",
            **self._token_metadata_fields(str(asset.asset)),
        )

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

    def _token_metadata_for_asset(self, asset: str) -> object | None:
        if self._jupiter_metadata_cache is None:
            self._jupiter_metadata_cache = JupiterTokenService(self.store).cached_metadata_by_asset()
        return self._jupiter_metadata_cache.get(str(asset)) or self._jupiter_metadata_cache.get(str(asset).upper())

    def _recent_events_for_group(self, group: object, limit: int) -> list[SourceEventPreview]:
        accounts = {account.account for account in group.accounts}
        account_labels = {account.lower() for account in accounts}
        labels = {group.source_group.lower(), *account_labels}
        events = []
        for event in reversed(self.store.list_canonical_events()):
            source = (event.source or "").lower()
            account = (event.account or "").lower()
            wallet = (event.wallet or "").lower()
            raw_payload = self._raw_payload_for_event(event.raw_object_id)
            raw_counterparty = self._raw_counterparty_for_accounts(raw_payload, account_labels)
            is_canonical_match = (
                source in labels
                or account in labels
                or wallet in labels
                or event.account in accounts
            )
            if is_canonical_match or raw_counterparty is not None:
                events.append(
                    SourceEventPreview(
                        event_id=event.event_id,
                        event_time=event.event_time,
                        source=event.source,
                        event_type=event.event_type,
                        asset=event.asset,
                        quantity=event.quantity,
                        account=event.account,
                        counterparty_account=raw_counterparty,
                        raw_type=self._raw_type(raw_payload),
                        match_basis=(
                            "raw_counterparty"
                            if raw_counterparty is not None and not is_canonical_match
                            else "canonical_account"
                        ),
                        tx_id=event.tx_id,
                    )
                )
            if len(events) >= limit:
                break
        return events

    def _raw_payload_for_event(self, raw_object_id: str | None) -> dict[str, object] | None:
        if raw_object_id is None:
            return None
        if self._raw_payload_cache is None:
            payloads: dict[str, dict[str, object]] = {}
            for raw_object in self.store.list_raw_objects(limit=None):
                try:
                    payload = json.loads(raw_object.payload_json)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    payloads[raw_object.raw_object_id] = payload
            self._raw_payload_cache = payloads
        return self._raw_payload_cache.get(raw_object_id)

    def _raw_counterparty_for_accounts(
        self,
        raw_payload: dict[str, object] | None,
        account_labels: set[str],
    ) -> str | None:
        if raw_payload is None:
            return None
        for key, value in raw_payload.items():
            if self._raw_key(key) not in {
                "account",
                "address",
                "wallet",
                "wallet_address",
                "payer",
                "payee",
                "sender",
                "receiver",
                "from",
                "to",
                "from_address",
                "to_address",
            }:
                continue
            text = str(value).strip()
            if text.lower() in account_labels:
                return text
        return None

    def _raw_type(self, raw_payload: dict[str, object] | None) -> str | None:
        if raw_payload is None:
            return None
        for key, value in raw_payload.items():
            if self._raw_key(key) in {"type", "operation", "category", "reward_type"}:
                return str(value).strip() or None
        return None

    def _raw_key(self, key: object) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")

    def _issues_for_group(self, group: object) -> list[dict[str, object]]:
        return []

    def _last_imported_at(self, group: object) -> datetime | None:
        sources = self._raw_source_names(group)
        candidates = [
            batch.created_at
            for batch in self._import_batches()
            if batch.source.lower() in sources
        ]
        return max(candidates) if candidates else None

    def _import_batch_count(self, group: object) -> int:
        sources = self._raw_source_names(group)
        return sum(1 for batch in self._import_batches() if batch.source.lower() in sources)

    def _last_evidence_files(self, group: object) -> list[str]:
        sources = self._raw_source_names(group)
        files = [
            batch.filename or batch.batch_id
            for batch in self._import_batches()
            if batch.source.lower() in sources
        ]
        return [str(item) for item in files[:5]]

    def _import_batches(self) -> list[object]:
        if self._import_batches_cache is None:
            self._import_batches_cache = self.store.list_import_batches()
        return self._import_batches_cache

    def _raw_source_names(self, group: object) -> set[str]:
        source_type = group.source_type
        source_group = group.source_group.lower()
        names = {source_group}
        if source_group == "binance":
            names.update({"binance"})
        if source_group == "bitget":
            names.update({"bitget"})
        if source_group == "pionex":
            names.update({"pionex"})
        if source_type == "solana_wallet":
            names.update({"solana", "solana_rpc", "blockpit"})
        if source_type == "staking_platform":
            names.update({"helium", "fairspot"})
        if source_type == "legacy_wallet":
            names.update({"helium", "fairspot"})
        return names

    def _evidence_refs(
        self,
        group: object,
        reconciliation: SourceReconciliationStatus,
    ) -> list[str]:
        refs = []
        if group.note:
            refs.append(group.note)
        if reconciliation.evidence and reconciliation.evidence not in refs:
            refs.append(reconciliation.evidence)
        return refs

    def _share(self, value: Decimal, total: Decimal) -> Decimal:
        if total == 0:
            return Decimal("0.00")
        return (value / total * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    def _price_status(self, priced_at: datetime | None) -> str:
        if priced_at is None:
            return "missing"
        if priced_at.year == 1970:
            return "fiat"
        normalized = priced_at if priced_at.tzinfo is not None else priced_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - normalized).days
        if age_days <= PortfolioService.PRICE_FRESH_DAYS:
            return "fresh"
        if age_days <= PortfolioService.PRICE_STALE_DAYS:
            return "stale"
        return "old"

    def _short_account(self, value: str) -> str:
        if len(value) <= 22:
            return value
        return f"{value[:10]}...{value[-8:]}"
