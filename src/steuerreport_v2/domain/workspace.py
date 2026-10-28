"""Read models for the UI, using existing valuation, ownership and review rules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.sources import SourceDetail
from steuerreport_v2.contracts.review import ReviewTask
from steuerreport_v2.contracts.workspace import (
    ActivityDetail, ActivityExport, ActivityPage, ActivityQuery, ActivityRow, WorkspaceSource,
    WorkspaceSourceDetail, WorkspaceSources, WorkspaceStatus,
    WorkspaceReviewQuery, WorkspaceReviewItem, WorkspaceReviewPage,
    WorkspaceLiveAsset, WorkspaceLiveBalance,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connectors import ConnectorService
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.price_lookup import fiat_price_point
from steuerreport_v2.domain.product_readiness import ProductReadinessService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.domain.tax_time import event_reporting_year_sql

UTC = timezone.utc
BERLIN = ZoneInfo("Europe/Berlin")
SYNC_CONNECTORS = {"binance", "bitget", "pionex", "coinbase", "jup_wallet", "solana_wallet"}
EVENT_COLUMNS = "e.event_id, e.source, e.source_ref, e.event_time, e.event_type, e.asset, e.quantity, e.quote_asset, e.quote_quantity, e.fee_asset, e.fee_quantity, e.tx_id, e.wallet, e.account, e.confidence, e.raw_object_id"
HINT = "(e.event_type = 'unknown' or e.raw_object_id is null or exists(select 1 from tax_unmatched_disposals u where u.source_event_id=e.event_id))"
CORRECTED = "exists(select 1 from ai_correction_overrides o where o.kind='event' and o.target_id=e.event_id and o.original_json <> o.corrected_json)"


def utc(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def naive_utc(value):
    return value.astimezone(UTC).replace(tzinfo=None)


def source_ref(key: str) -> str:
    return "s_" + hashlib.sha256(key.encode()).hexdigest()[:20]


def account_ref(account: str) -> str:
    return "a_" + hashlib.sha256(account.encode()).hexdigest()[:20]


@dataclass
class SourceScope:
    item: WorkspaceSource
    predicate: str
    parameters: list
    registry: object | None = None


class WorkspaceService:
    def __init__(self, store: DuckDbStore):
        self.store = store

    def source_scopes(self) -> list[SourceScope]:
        service = SourceService(self.store)
        overview = service.overview()
        groups = {SourceService.source_id(row.source_group): row for row in PortfolioService(self.store).source_overview().groups}
        diagnostics = {row.source_id: row for row in service.connector_diagnostics().diagnostics}
        catalog = ConnectorService(self.store).catalog()
        prices = PortfolioService(self.store)._latest_prices()
        registry = [row for row in SourceRegistryService(self.store).config().entries
                    if row.ownership in {"owned", "owned_historical_route"}]
        scopes: list[SourceScope] = []
        represented: set[str] = set()
        represented_scopes: dict[str, list[SourceScope]] = {}
        # Only actual holdings/imports/snapshots create rows, not generic placeholders.
        for row in overview.sources:
            if not (row.position_count or row.import_batches or row.last_live_at):
                continue
            if (row.source_type == "solana_wallet" and not row.position_count and not row.last_live_at
                    and not any(account.account for account in groups[row.source_id].accounts)):
                continue
            predicates = ["lower(e.source)=lower(?)"]
            parameters = [row.label]
            for account in groups[row.source_id].accounts:
                if account.account:
                    predicates.append("(e.account=? or e.wallet=?)")
                    parameters.extend([account.account, account.account])
            diagnostic = diagnostics.get(row.source_id)
            connector = diagnostic.connector_id if diagnostic else None
            ledger_unpriced = any(asset.quantity != 0 and fiat_price_point(asset.asset) is None and asset.asset.upper() not in prices for asset in groups[row.source_id].asset_summary)
            confirmed_empty = bool(connector and row.value_basis == "live_api" and
                                   PortfolioService(self.store)._latest_live_connector_anchor(connector)[0] == "empty_response")
            value = row.value_eur if (row.position_count or row.live_value_eur is not None) and (not row.open_price_issues or confirmed_empty or row.value_basis == "ledger" and not ledger_unpriced) else None
            if row.value_basis == "expected_zero_policy_no_current_live":
                value = None
            scopes.append(SourceScope(WorkspaceSource(
                ref=source_ref(row.source_id), label=row.label, source_type=row.source_type,
                legacy_source_id=row.source_id, connector_id=connector,
                connection_status=diagnostic.credential_status if diagnostic else "imported",
                last_success_at=utc(row.last_live_at), last_attempt=diagnostic.last_attempt if diagnostic else None,
                freshness=row.live_freshness, value_eur=value, value_basis=row.value_basis if value is not None else "unavailable",
                ledger_value_eur=row.ledger_value_eur if not ledger_unpriced else None, imports_count=row.import_batches,
                issues_count=row.open_price_issues + row.open_reconciliation_issues,
                price_issues_count=row.open_price_issues,
                reconciliation_issues_count=row.open_reconciliation_issues,
                reconciliation_status=row.current_status,
                can_sync=connector in SYNC_CONNECTORS and bool(diagnostic) and diagnostic.credential_status in {"configured", "not_required"},
                warning=row.display_warning,
            ), "(" + " or ".join(predicates) + ")", parameters))

        for entry in registry:
            existing = next((scope for scope in scopes if scope.item.legacy_source_id == entry.source_id or scope.item.label == entry.label), None)
            if existing:
                existing.registry = entry
                existing.item.ownership_status = entry.ownership
                continue
            predicates, parameters = [], []
            for identifier in entry.identifiers:
                if identifier.kind == "canonical_source":
                    predicates.append("e.source=?")
                    parameters.append(identifier.value)
                elif identifier.kind == "canonical_source_prefix":
                    predicates.append("starts_with(e.source, ?)")
                    parameters.append(identifier.value)
                else:
                    predicates.append("(e.account=? or e.wallet=?)")
                    parameters.extend([identifier.value, identifier.value])
            if not predicates:
                predicates.append("false")
            predicate = "(" + " or ".join(predicates) + ") and e.event_time>=?"
            parameters.append(naive_utc(utc(entry.valid_from)))
            if entry.valid_to:
                predicate += " and e.event_time<?"
                parameters.append(naive_utc(utc(entry.valid_to)))
            scopes.append(SourceScope(WorkspaceSource(
                ref=source_ref(entry.source_id), label=entry.label, source_type=entry.source_type,
                connection_status="registered", ownership_status=entry.ownership,
                warning=entry.coverage_limitation_note,
            ), predicate, parameters, entry))

        wallets = {connection.external_identifier: connection for connection in catalog.connections
                   if connection.connector_id == "solana-wallet" and connection.status != "revoked" and connection.revoked_at is None}
        portfolio = PortfolioService(self.store)
        configured_wallets: dict[str, str] = {}
        for address, connector in ((portfolio.PRIMARY_SOLANA_WALLET, "solana_wallet"), (portfolio.KNOWN_JUP_WALLET, "jup_wallet")):
            if address:
                configured_wallets.setdefault(address, connector)
        # Private profile entries remain visible without silently manufacturing
        # a cryptographic proof or a persisted connection during a GET request.
        for address in dict.fromkeys([*wallets, *configured_wallets]):
            connection = wallets.get(address)
            existing = next((scope for scope in scopes if
                (scope.registry and {identifier.value for identifier in scope.registry.identifiers if identifier.kind in {"account", "wallet", "address"}} == {address})
                or len(scope.parameters) == 3 and scope.parameters[-2:] == [address, address]), None)
            connector_id = configured_wallets.get(address)
            diagnostic = next((item for item in diagnostics.values() if item.connector_id == connector_id), None) if connector_id else None
            status = connection.status if connection else "address_saved"
            if existing:
                existing.item.ref = source_ref("wallet:" + address)
                existing.item.wallet_address = address
                if connector_id:
                    existing.item.connector_id = connector_id
                    existing.item.can_sync = bool(diagnostic and diagnostic.credential_status in {"configured", "not_required"})
                if connection:
                    existing.item.label = connection.display_label
                    existing.item.connection_status = status
                    if not existing.registry and connection.verified_at:
                        existing.item.ownership_status = "pending_registry"
                continue
            scopes.append(SourceScope(WorkspaceSource(
                ref=source_ref("wallet:" + address), label=connection.display_label if connection else f"Solana {address[:6]}...{address[-4:]}",
                source_type="wallet", connector_id=connector_id or "solana-wallet", wallet_address=address,
                connection_status=status, ownership_status="pending_registry" if connection and connection.verified_at else "not_assessed",
                last_success_at=utc(diagnostic.last_snapshot_at) if diagnostic else None,
                last_attempt=diagnostic.last_attempt if diagnostic else None,
                can_sync=bool(diagnostic and diagnostic.credential_status in {"configured", "not_required"}),
                warning="Adresse gespeichert. Historienimport und Quellenzuordnung separat pruefen; kein automatischer Eigentumsnachweis.",
            ), "(e.account=? or e.wallet=?)", [address, address]))

        # Each configured exchange account has an exact, stable source scope.
        # A provider-wide credential or balance is not another account's history.
        for connection in ConnectionService(self.store).list().connections:
            identifier = str(connection.id)
            account = "connection:" + identifier
            scopes.append(SourceScope(WorkspaceSource(
                ref=source_ref(account), label=connection.label, source_type="exchange",
                connector_id=connection.provider, connection_id=identifier,
                connection_status=connection.credentials.status,
                last_success_at=utc(connection.last_sync_at),
                can_sync=False,
                warning="Verbindungseigene Historie; keine automatische steuerliche Quellenfreigabe.",
            ), "(e.account=? or e.wallet=?)", [account, account]))

        with self.store.connect() as con:
            exact_accounts = {scope.item.wallet_address or "connection:" + scope.item.connection_id for scope in scopes if scope.item.wallet_address or scope.item.connection_id}
            exact_refs = [scope.item.ref for scope in scopes if scope.item.wallet_address or scope.item.connection_id]
            for scope in scopes:
                if scope.item.wallet_address or scope.item.connection_id:
                    scope.item.imports_count = 0
            # Raw-only documentary records still belong to the selected source.
            # An aggregate disappears only when every raw row is explicitly mapped.
            raw_coverage = con.execute(
                """
                select b.source, count(r.raw_object_id), count(r.raw_object_id) filter(where
                    e.account in (select unnest(?)) or e.wallet in (select unnest(?))
                    or json_extract_string(r.payload_json, '$.account') in (select unnest(?))
                    or json_extract_string(r.payload_json, '$.wallet_address') in (select unnest(?))
                    or json_extract_string(r.payload_json, '$.history_source_ref') in (select unnest(?)))
                from raw_import_batches b left join raw_objects r on r.batch_id=b.batch_id
                left join canonical_events e on e.raw_object_id=r.raw_object_id group by b.source
                """, [list(exact_accounts)] * 4 + [exact_refs],
            ).fetchall()
            fully_scoped = {source for source, total, matched in raw_coverage if total and total == matched}
            redundant = []
            for scope in scopes:
                if scope.item.wallet_address or scope.item.connection_id or not scope.item.legacy_source_id:
                    continue
                accounts = con.execute(f"select distinct coalesce(e.account, e.wallet) from canonical_events e where {scope.predicate}", scope.parameters).fetchall()
                if accounts and all(row[0] in exact_accounts for row in accounts):
                    redundant.append(scope)
                elif not accounts:
                    raw_sources = [source for source, _total, _matched in raw_coverage
                                   if SourceService.source_id(source) == scope.item.legacy_source_id]
                    if raw_sources and all(source in fully_scoped for source in raw_sources):
                        redundant.append(scope)
            scopes = [scope for scope in scopes if scope not in redundant]
            for scope in scopes:
                rows = con.execute(f"select e.source, count(*) from canonical_events e where {scope.predicate} group by e.source", scope.parameters).fetchall()
                scope.item.events_count = sum(row[1] for row in rows)
                represented.update(row[0] for row in rows)
                for source, _count in rows:
                    represented_scopes.setdefault(source, []).append(scope)
            for source, count in con.execute("select source, count(*) from canonical_events group by source order by source").fetchall():
                if source in represented:
                    continue
                key = SourceService.source_id(source)
                existing = next((scope for scope in scopes if scope.item.ref == source_ref(key)), None)
                if existing:
                    continue
                scopes.append(SourceScope(WorkspaceSource(
                    ref=source_ref(key), label=source, source_type="import",
                    connection_status="imported", events_count=count,
                ), "e.source=?", [source]))
            # Raw-only imports are still a user's source, even before normalization.
            imports = con.execute("select source, count(*) from raw_import_batches group by source").fetchall()
            for source, count in imports:
                for scope in scopes:
                    account = scope.item.wallet_address or ("connection:" + scope.item.connection_id if scope.item.connection_id else None)
                    if account:
                        scoped_count = con.execute(
                            """
                            select count(distinct b.batch_id) from raw_import_batches b
                            join raw_objects r on r.batch_id=b.batch_id
                            left join canonical_events e on e.raw_object_id=r.raw_object_id
                            where b.source=? and (e.account=? or e.wallet=?
                                or json_extract_string(r.payload_json, '$.account')=?
                                or json_extract_string(r.payload_json, '$.wallet_address')=?
                                or json_extract_string(r.payload_json, '$.history_source_ref')=?)
                            """, [source, account, account, account, account, scope.item.ref],
                        ).fetchone()[0]
                        scope.item.imports_count += scoped_count
                if source in fully_scoped:
                    continue
                key = SourceService.source_id(source)
                existing = next((scope for scope in scopes if scope.item.ref == source_ref(key)), None)
                if existing:
                    existing.item.imports_count = max(existing.item.imports_count, count)
                elif source in represented_scopes:
                    for scope in represented_scopes[source]:
                        if not scope.item.wallet_address and not scope.item.connection_id:
                            scope.item.imports_count = max(scope.item.imports_count, count)
                elif source not in represented:
                    scopes.append(SourceScope(WorkspaceSource(
                        ref=source_ref(key), label=source, source_type="import", imports_count=count,
                        connection_status="imported",
                    ), "e.source=?", [source]))

        for connector in catalog.connectors:
            if connector.category == "wallet":
                continue
            if any(scope.item.connection_id and scope.item.connector_id == connector.connector_id for scope in scopes):
                continue
            if connector.category not in {"exchange", "wallet"} or connector.connection_status in {"not_configured", "revoked"}:
                continue
            existing = next((scope for scope in scopes if not scope.item.connection_id and (
                scope.item.connector_id == connector.connector_id
                or scope.item.ref == source_ref(connector.connector_id))), None)
            if existing:
                existing.item.connection_status = connector.connection_status
                existing.item.connector_id = connector.connector_id
                existing.item.can_sync = connector.connector_id in SYNC_CONNECTORS
                continue
            diagnostic = next((row for row in diagnostics.values() if row.connector_id == connector.connector_id), None)
            scopes.append(SourceScope(WorkspaceSource(
                ref=source_ref(connector.connector_id), label=connector.label, source_type=connector.category,
                connector_id=connector.connector_id, connection_status=connector.connection_status,
                ownership_status="pending_registry" if connector.connection_status == "ownership_verified_pending_registry" else "not_assessed",
                last_success_at=utc(diagnostic.last_snapshot_at) if diagnostic else None,
                last_attempt=diagnostic.last_attempt if diagnostic else None,
                freshness="stale" if diagnostic and diagnostic.status == "stale_snapshot" else "missing",
                value_eur=diagnostic.last_snapshot_value_eur if diagnostic else None,
                value_basis="stored_live_snapshot" if diagnostic and diagnostic.last_snapshot_at else "unavailable",
                can_sync=connector.connector_id in SYNC_CONNECTORS,
            ), "lower(e.source)=lower(?)", [connector.connector_id]))
        for scope in scopes:
            live = self._wallet_live_balance(scope.item, portfolio)
            if live is None:
                continue
            scope.item.live_assets_count = len(live.assets)
            scope.item.live_unpriced_assets_count = live.unpriced_assets_count
            scope.item.live_value_eur = live.value_eur
            scope.item.live_balance_status = live.status
            scope.item.last_success_at = live.fetched_at
            scope.item.freshness = "stale" if (datetime.now(UTC) - live.fetched_at).days > SourceService.LIVE_STALE_AFTER_DAYS else "fresh"
            if scope.item.legacy_source_id is None:
                scope.item.value_basis = "stored_live_snapshot"
                scope.item.value_eur = live.value_eur
                scope.item.price_issues_count = sum(asset.price_status == "missing" for asset in live.assets)
                scope.item.issues_count += scope.item.price_issues_count
        return sorted(scopes, key=lambda scope: (scope.item.label.casefold(), scope.item.ref))

    def _wallet_live_balance(self, source: WorkspaceSource, portfolio: PortfolioService) -> WorkspaceLiveBalance | None:
        # Connector-wide snapshots only belong to their explicitly configured
        # profile wallet, never to every saved observation address.
        wallets = {"solana_wallet": portfolio.PRIMARY_SOLANA_WALLET, "jup_wallet": portfolio.KNOWN_JUP_WALLET}
        connector = source.connector_id
        if not source.wallet_address or wallets.get(connector) != source.wallet_address:
            return None
        status, fetched_at = portfolio._latest_live_connector_anchor(connector)
        if fetched_at is None:
            return None
        with self.store.connect() as con:
            rows = [] if status == "empty_response" else con.execute(
                "select asset, sum(quantity), list(distinct source) from portfolio_live_balance_snapshots where connector_id=? and fetched_at=? group by asset order by asset",
                [connector, fetched_at],
            ).fetchall()
        if not rows and status != "empty_response":
            return None
        prices = portfolio._latest_prices()
        assets = []
        sources = set()
        for asset, quantity, origins in rows:
            sources.update(origin for origin in origins if origin)
            receipt = asset in portfolio.NON_VALUED_LIVE_RECEIPT_ASSETS
            fiat = fiat_price_point(asset)
            price = None if receipt else fiat or prices.get(asset.upper())
            assets.append(WorkspaceLiveAsset(asset=asset, quantity=quantity,
                price_eur=price.price_eur if price else None, value_eur=quantity * price.price_eur if price else None,
                price_source=price.source if price else None, priced_at=utc(price.priced_at) if price else None,
                price_status="excluded_receipt" if receipt else "fiat" if fiat else SourceService(self.store)._price_status(price.priced_at if price else None)))
        unpriced = sum(asset.value_eur is None for asset in assets)
        return WorkspaceLiveBalance(fetched_at=utc(fetched_at), status="confirmed_empty" if status == "empty_response" else "available",
            assets=assets, value_eur=None if unpriced else sum((asset.value_eur for asset in assets), Decimal("0")),
            unpriced_assets_count=unpriced, sources=sorted(sources))

    def sources(self) -> WorkspaceSources:
        scopes = self.source_scopes()
        self._attach_review(scopes)
        with self.store.connect() as con:
            count = con.execute("select count(*) from canonical_events").fetchone()[0]
        return WorkspaceSources(generated_at=datetime.now(UTC), sources=[scope.item for scope in scopes], events_count=count,
                                methodology="Eigene importierte, registrierte oder konfigurierte Quellen; kein Anbieter-Katalog. Werte und Gates aus vorhandenen Services. Keine externe Abfrage und keine Aenderung der Ownership- oder Steuerregeln.")

    def source(self, ref: str) -> WorkspaceSourceDetail:
        scopes = self.source_scopes()
        scope = next((row for row in scopes if row.item.ref == ref or row.item.legacy_source_id and source_ref(row.item.legacy_source_id) == ref), None)
        if scope is None:
            raise LookupError("workspace_source_not_found")
        reviews = self._attach_review(scopes)
        valuation = None
        if scope.item.legacy_source_id:
            groups = PortfolioService(self.store).source_overview().groups
            group = next((row for row in groups if SourceService.source_id(row.source_group) == scope.item.legacy_source_id), None)
            if group:
                service = SourceService(self.store)
                status = service._status_for_group(group, sum((row.value_eur for row in groups), Decimal("0")))
                valuation = SourceDetail(**status.model_dump(), assets=service._display_assets_for_group(group, status.value_eur),
                    reconciliation=service._reconciliation_for_group(group),
                    evidence_refs=service._evidence_refs(group, service._reconciliation_for_group(group)),
                    full_accounts=[row.account for row in group.accounts],
                    methodology="Bestehende Bewertung. Ereignisse werden ausschliesslich separat paginiert geladen; kein Vollscan der Ereignisliste fuer diesen Detailaufruf.")
        evidence = scope.registry.model_dump(mode="json") if scope.registry else {"ownership": "not_assessed", "note": "Import oder API-Konfiguration bestaetigt nicht automatisch Eigentum oder steuerliche Aktivierung."}
        if scope.item.wallet_address:
            evidence["wallet_address"] = scope.item.wallet_address
        return WorkspaceSourceDetail(source=scope.item.model_copy(update={"ref": ref}), valuation=valuation,
                                     live_balance=self._wallet_live_balance(scope.item, PortfolioService(self.store)), evidence=evidence,
                                     review_tasks=[item for item in reviews if scope.item.ref in item.candidate_source_refs][:50])

    def _attach_review(self, scopes: list[SourceScope]) -> list[WorkspaceReviewItem]:
        items = self._review_items(ReviewService(self.store).tasks(limit=None).tasks, scopes)
        for scope in scopes:
            matched = [item for item in items if item.source_ref == scope.item.ref]
            related = [item for item in items if scope.item.ref in item.candidate_source_refs]
            scope.item.review_tasks_count = len(matched)
            scope.item.blocking_review_tasks_count = sum(item.task.blocks_export for item in related)
            scope.item.ambiguous_review_tasks_count = sum(item.context_status == "ambiguous" for item in related)
            scope.item.review_reconciliation_tasks_count = sum(item.task.category == "reconciliation" for item in related)
        return items

    def _review_items(self, tasks: list[ReviewTask], scopes: list[SourceScope]) -> list[WorkspaceReviewItem]:
        """Resolve exact account/source/event identities; never guess from task prose."""
        items = []
        with self.store.connect() as con:
            accounts = {}
            sources = {}
            for scope in scopes:
                rows = con.execute(f"select distinct e.account, e.wallet, e.source from canonical_events e where {scope.predicate}", scope.parameters).fetchall()
                accounts[scope.item.ref] = {value for row in rows for value in row[:2] if value}
                sources[scope.item.ref] = {row[2] for row in rows}
                if scope.registry:
                    for identifier in scope.registry.identifiers:
                        if identifier.kind == "canonical_source":
                            sources[scope.item.ref].add(identifier.value)
                        elif identifier.kind != "canonical_source_prefix":
                            accounts[scope.item.ref].add(identifier.value)
            for task in tasks:
                identities = [task.scope, *task.evidence_refs]
                account_ids = {identity.removeprefix("account:").rsplit(":asset:", 1)[0] for identity in identities if identity.startswith("account:")}
                account = next(iter(account_ids)) if len(account_ids) == 1 else None
                candidates = [value.removeprefix("canonical:").removeprefix("event:") for value in identities]
                event_rows = con.execute("select event_id, account, wallet, source from canonical_events where event_id in (select unnest(?)) or raw_object_id in (select unnest(?)) order by event_id", [candidates, candidates]).fetchall()
                matches = set()
                incomplete = False
                if account_ids:
                    matches = {ref for ref, values in accounts.items() if account_ids.intersection(values)}
                    incomplete = any(not any(account_id in values for values in accounts.values()) for account_id in account_ids)
                elif event_rows:
                    for scope in scopes:
                        found = con.execute(f"select 1 from canonical_events e where ({scope.predicate}) and e.event_id in (select unnest(?)) limit 1", [*scope.parameters, [row[0] for row in event_rows]]).fetchone()
                        if found:
                            matches.add(scope.item.ref)
                else:
                    # source_group is a structured identifier from the existing rule,
                    # unlike a translated title or the technical producer review_gate.
                    for scope in scopes:
                        if task.source_group and (task.source_group in sources[scope.item.ref]
                                                  or SourceService.source_id(task.source_group) == scope.item.legacy_source_id):
                            matches.add(scope.item.ref)
                        elif task.source in sources[scope.item.ref]:
                            matches.add(scope.item.ref)
                status = "matched" if len(matches) == 1 and not incomplete else "ambiguous" if matches else "unresolved"
                resolved = next(iter(matches)) if status == "matched" else None
                label = f"Konto {account}" if account else "Mehrere Konten" if len(account_ids) > 1 else next((scope.item.label for scope in scopes if scope.item.ref == resolved), "Fachliche Prüfung")
                if task.asset:
                    label += f" · Asset {task.asset}"
                items.append(WorkspaceReviewItem(task=task, event_ids=[row[0] for row in event_rows[:20]], source_ref=resolved,
                    candidate_source_refs=sorted(matches), account=account, account_ref=account_ref(account) if account else None,
                    context_status=status, context_label=label,
                    context_note="Über gespeicherte Konto-/Quellen- oder Ereignis-IDs zugeordnet." if resolved else
                    "Nicht alle Kontobezüge lassen sich einer Quelle zuordnen. Zuordnung vor einer Entscheidung prüfen." if incomplete and matches else
                    "Mehrere Quellen passen zu den gespeicherten IDs. Zuordnung vor einer Entscheidung prüfen." if matches else
                    "Keine eindeutige Zuordnung zu einer eigenen Quelle belegt. Vorbereitete Liste prüfen; keine Quelle wird geraten."))
        return items

    def scope(self, ref: str) -> SourceScope:
        scope = next((row for row in self.source_scopes() if row.item.ref == ref or row.item.legacy_source_id and source_ref(row.item.legacy_source_id) == ref), None)
        if scope is None:
            raise LookupError("workspace_source_not_found")
        return scope

    def status(self, year: int) -> WorkspaceStatus:
        with self.store.connect() as con:
            events = con.execute("select count(*) from canonical_events").fetchone()[0]
            year_events = con.execute("select count(*) from canonical_events e left join raw_objects r on r.raw_object_id=e.raw_object_id where " + event_reporting_year_sql("e", "r") + "=?", [year]).fetchone()[0]
            imports, last_import = con.execute("select count(*), max(created_at) from raw_import_batches").fetchone()
            balances = con.execute("select count(*) from balance_ledger").fetchone()[0]
            calculation = con.execute("select max(created_at) from tax_run_summaries").fetchone()[0]
        readiness = ProductReadinessService(self.store).report()
        review = ReviewService(self.store).gate()
        owned = len(self.source_scopes())
        stale = bool(last_import and calculation and last_import > calculation)
        preview = bool(year_events and calculation)
        final = bool(preview and not stale and review.allow_export and readiness.can_file_without_review and year in readiness.ready_years)
        if not owned:
            next_section, next_action = "sources", "Erste Quelle hinzufügen"
        elif not events:
            next_section, next_action = "import", "Transaktionshistorie importieren"
        elif not calculation or stale:
            next_section, next_action = "dashboard", "Daten neu berechnen"
        elif not review.allow_export or review.issues_open:
            next_section, next_action = "review", "Offene Hinweise klären"
        elif not final:
            next_section, next_action = "tax", "Steuerjahr und Freigaben prüfen"
        else:
            next_section, next_action = "export", "Bericht erstellen"
        return WorkspaceStatus(generated_at=datetime.now(UTC), year=year, events_count=events, year_events_count=year_events, imports_count=imports,
            balance_entries=balances, owned_sources_count=owned, last_import_at=utc(last_import), calculation_at=utc(calculation),
            calculation_stale=stale, review=review, readiness=readiness, preview_available=preview, final_available=final,
            summary="Finaler Bericht verfügbar" if final else "Vorschau verfügbar — finale Abgabe nicht freigegeben" if preview else "Noch keine berechnete Jahresvorschau",
            next_section=next_section, next_action=next_action,
            dimensions={"data": "Historie vorhanden — Abdeckung prüfen" if events else "Noch keine Transaktionshistorie",
                        "calculation": "Veraltet" if stale else "Berechnungsstand vorhanden" if calculation else "Noch nicht berechnet",
                        "methodology": {"current": "Gebundener Methoden-Prüfstand aktuell",
                                        "stale": "Methoden-Prüfstand veraltet",
                                        "unbound": "Methoden-Prüfstand ohne Datenbindung",
                                        "missing": "Noch kein Methoden-Prüfstand"}[readiness.snapshot_binding_status],
                        "review": ("1 offener Hinweis" if review.issues_open == 1 else f"{review.issues_open} offene Hinweise") if review.issues_open else "Keine Gate-Hinweise im geprüften Datenstand" if events else "Noch nicht prüfbar",
                        "year": "Freigegeben" if final else "Jahresbestätigung / Belege prüfen",
                        "export": "Final verfügbar" if final else "Nur Vorschau" if preview else "Noch nicht verfügbar"})

    def review_page(self, query: WorkspaceReviewQuery) -> WorkspaceReviewPage:
        summary = ReviewService(self.store).tasks(limit=None)
        tasks = [task for task in summary.tasks if
                 (not query.task_id or task.task_id == query.task_id)
                 and (not query.category or task.category == query.category)
                 and (not query.priority or task.priority == query.priority)
                 and (query.year is None or task.tax_year is None or task.tax_year == query.year)
                 and (not query.search.strip() or query.search.strip().casefold() in " ".join([task.title, task.detail, task.source, task.scope, task.asset or ""]).casefold())]
        pages = max(1, (len(tasks) + query.page_size - 1) // query.page_size)
        page = min(query.page, pages)
        scopes = self.source_scopes()
        if query.source_ref:
            resolved = self._review_items(tasks, scopes)
            filtered = [item for item in resolved if query.source_ref in item.candidate_source_refs]
            pages = max(1, (len(filtered) + query.page_size - 1) // query.page_size)
            page = min(query.page, pages)
            items = filtered[(page - 1) * query.page_size:page * query.page_size]
            total = len(filtered)
        else:
            items = self._review_items(tasks[(page - 1) * query.page_size:page * query.page_size], scopes)
            total = len(tasks)
        return WorkspaceReviewPage(generated_at=summary.generated_at, items=items, total=total, page=page, pages=pages,
                                   page_size=query.page_size, blocking_total=summary.blocking_tasks, unfiltered_total=summary.open_tasks)


class ActivityService:
    EXPORT_LIMIT = 25_000

    def __init__(self, store: DuckDbStore):
        self.store = store

    def where(self, query: ActivityQuery) -> tuple[str, list]:
        clauses, parameters = [], []
        if query.year is not None:
            clauses.append(event_reporting_year_sql("e", "r") + "=?")
            parameters.append(query.year)
        if query.start:
            clauses.append("e.event_time>=?")
            parameters.append(naive_utc(datetime.combine(query.start, time.min, BERLIN)))
        if query.end:
            clauses.append("e.event_time<?")
            parameters.append(naive_utc(datetime.combine(query.end + timedelta(days=1), time.min, BERLIN)))
        if query.source_ref:
            scope = WorkspaceService(self.store).scope(query.source_ref)
            clauses.append("(" + scope.predicate + ")")
            parameters.extend(scope.parameters)
        if query.account_ref:
            columns = ["l.account"] if query.mode == "ledger" else ["e.account", "e.wallet"]
            clauses.append("(" + " or ".join(f"('a_' || substr(sha256({column}), 1, 20))=?" for column in columns) + ")")
            parameters.extend([query.account_ref] * len(columns))
        if query.asset:
            if query.mode == "ledger" and query.account_ref:
                clauses.append("upper(l.asset)=upper(?)")
                parameters.append(query.asset)
            else:
                clauses.append("(upper(e.asset)=upper(?) or upper(e.quote_asset)=upper(?) or upper(e.fee_asset)=upper(?))")
                parameters.extend([query.asset] * 3)
        if query.event_type:
            clauses.append("e.event_type=?")
            parameters.append(query.event_type)
        if query.hint != "all":
            clauses.append(HINT if query.hint == "present" else "not " + HINT)
        if query.search.strip():
            clauses.append("(contains(lower(e.tx_id), lower(?)) or contains(lower(e.source_ref), lower(?)) or contains(lower(e.source), lower(?)) or contains(lower(e.event_id), lower(?)))")
            parameters.extend([query.search.strip()] * 4)
        return " and ".join(clauses) or "true", parameters

    def query(self, query: ActivityQuery) -> ActivityPage:
        where, parameters = self.where(query)
        join = "left join raw_objects r on r.raw_object_id=e.raw_object_id"
        base = f"canonical_events e {join}"
        row_id = "e.event_id"
        extra = "null::varchar, null::decimal(38,18), null::varchar"
        if query.mode == "ledger":
            base += " join balance_ledger l on l.event_id=e.event_id"
            row_id = "l.ledger_id"
            extra = "l.asset, l.delta_quantity, l.account"
        direction = "desc" if query.sort == "newest" else "asc"
        with self.store.connect() as con:
            account_label = None
            if query.account_ref:
                account_row = con.execute("select account from (select account from balance_ledger union select account from canonical_events union select wallet as account from canonical_events) where ('a_' || substr(sha256(account),1,20))=? limit 1", [query.account_ref]).fetchone()
                account_label = account_row[0] if account_row else None
            total = con.execute(f"select count(*) from {base} where {where}", parameters).fetchone()[0]
            pages = max(1, (total + query.page_size - 1) // query.page_size)
            page = min(query.page, pages)
            rows = con.execute(f"select {row_id}, {EVENT_COLUMNS}, {HINT}, {CORRECTED}, {extra} from {base} where {where} order by e.event_time {direction}, {row_id} asc limit ? offset ?",
                               [*parameters, query.page_size, (page - 1) * query.page_size]).fetchall()
        return ActivityPage(generated_at=datetime.now(UTC), total=total, pages=pages, page=page, page_size=query.page_size, mode=query.mode, account_label=account_label,
                            rows=[self.row(row) for row in rows])

    @staticmethod
    def row(row) -> ActivityRow:
        return ActivityRow(row_id=row[0], event=ActivityService.event(row[1:17]), has_hint=row[17], corrected=row[18],
                           ledger_asset=row[19], ledger_quantity=row[20], ledger_account=row[21])

    @staticmethod
    def event(row) -> CanonicalEvent:
        names = ["event_id", "source", "source_ref", "event_time", "event_type", "asset", "quantity", "quote_asset", "quote_quantity", "fee_asset", "fee_quantity", "tx_id", "wallet", "account", "confidence", "raw_object_id"]
        values = dict(zip(names, row))
        values["event_time"] = utc(values["event_time"])
        return CanonicalEvent(**values)

    def detail(self, event_id: str) -> ActivityDetail:
        with self.store.connect() as con:
            row = con.execute(f"select {EVENT_COLUMNS} from canonical_events e where e.event_id=?", [event_id]).fetchone()
            if row is None:
                raise LookupError("activity_event_not_found")
            event = self.event(row)
            raw = None
            if event.raw_object_id:
                original = con.execute("select r.raw_object_id, r.row_number, r.payload_json, b.batch_id, b.filename, b.file_hash, b.source from raw_objects r join raw_import_batches b on b.batch_id=r.batch_id where r.raw_object_id=?", [event.raw_object_id]).fetchone()
                if original:
                    raw = dict(zip(["raw_object_id", "row_number", "payload_json", "batch_id", "filename", "file_hash", "source"], original))
                    raw["filename"] = Path(str(raw["filename"])).name if raw["filename"] else None
            def related(table, column):
                count = con.execute(f"select count(*) from {table} where {column}=?", [event_id]).fetchone()[0]
                cursor = con.execute(f"select * from {table} where {column}=? order by all limit 200", [event_id])
                names = [col[0] for col in cursor.description]
                return count, [dict(zip(names, values)) for values in cursor.fetchall()]
            ledger_count, ledger = related("balance_ledger", "event_id")
            tax_count, tax_lines = related("tax_lines", "source_event_id")
            corrections = con.execute("select change_set_id, original_json, corrected_json from ai_correction_overrides where kind='event' and target_id=?", [event_id]).fetchall()
            decisions = con.execute("select payload_json from review_decisions where json_contains(json_extract(payload_json, '$.affected_ids'), ?) order by created_at desc limit 200", [json.dumps(event_id)]).fetchall()
        return ActivityDetail(event=event, raw=raw, ledger=ledger, tax_lines=tax_lines, ledger_count=ledger_count, tax_lines_count=tax_count,
                              corrections=[{"change_set_id": item[0], "before": json.loads(item[1]), "after": json.loads(item[2])} for item in corrections],
                              decisions=[json.loads(item[0]) for item in decisions])

    def export(self, request: ActivityExport) -> list[ActivityRow]:
        query = ActivityQuery(mode=request.query.mode) if request.scope == "all" else request.query
        where, parameters = self.where(query)
        base = "canonical_events e left join raw_objects r on r.raw_object_id=e.raw_object_id"
        row_id, extra = "e.event_id", "null::varchar, null::decimal(38,18), null::varchar"
        if query.mode == "ledger":
            base += " join balance_ledger l on l.event_id=e.event_id"
            row_id, extra = "l.ledger_id", "l.asset, l.delta_quantity, l.account"
        if request.scope == "selected":
            if not request.selected_ids:
                raise ValueError("activity_export_selection_empty")
            where += f" and {row_id} in (select unnest(?))"
            parameters.append(request.selected_ids)
        direction = "desc" if query.sort == "newest" else "asc"
        with self.store.connect() as con:
            total = con.execute(f"select count(*) from {base} where {where}", parameters).fetchone()[0]
            if total > self.EXPORT_LIMIT:
                raise OverflowError("activity_export_too_large")
            rows = con.execute(f"select {row_id}, {EVENT_COLUMNS}, {HINT}, {CORRECTED}, {extra} from {base} where {where} order by e.event_time {direction}, {row_id} asc", parameters).fetchall()
        return [self.row(row) for row in rows]
