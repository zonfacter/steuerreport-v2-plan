from __future__ import annotations

from steuerreport_v2.private_settings import private_config_path

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from steuerreport_v2.contracts.source_registry import (
    SourceRegistryConfig,
    SourceRegistryEntry,
    SourceRegistryEntryStatus,
    SourceRegistryLedgerAdjustment,
    SourceRegistryObservation,
    SourceRegistryQuantityDelta,
    SourceRegistryRunReport,
)
from steuerreport_v2.contracts.sources import SourceConnectorAttempt
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.sources import SourceService


class SourceRegistryService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_CONFIG_PATH = private_config_path('source_registry.json')
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/source_registry"
    QUANTITY_TOLERANCE = Decimal("0.000000000001")
    REVIEW_VALUE_EUR = Decimal("1")
    BLOCKER_VALUE_EUR = Decimal("10")
    BINANCE_NONLEDGER_ACCRUAL_ACCOUNT_PREFIX = "binance earn rewards "
    LIVE_STALE_AFTER = timedelta(days=3)
    LIVE_CONNECTOR_BY_SOURCE_ID = {
        "solana-main-wallet": "solana_wallet",
        "jup-inheritance-wallet": "jup_wallet",
        "binance-account": "binance",
        "bitget-account": "bitget",
        "pionex-account": "pionex",
        "coinbase-account": "coinbase",
    }

    def __init__(
        self,
        store: DuckDbStore,
        *,
        config_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.artifact_root = artifact_root or self._default_artifact_root()

    def config(self) -> SourceRegistryConfig:
        return SourceRegistryConfig.model_validate_json(self.config_path.read_text(encoding="utf-8"))

    def run(self) -> SourceRegistryRunReport:
        generated_at = datetime.now(timezone.utc)
        config_content = self.config_path.read_bytes()
        config = SourceRegistryConfig.model_validate_json(config_content)
        invalid_entries = self._validate_config(config)
        observations = self._observations(config)
        unregistered = [item for item in observations if item.matched_source_id is None]
        portfolio_service = PortfolioService(self.store)
        ledger_snapshot = portfolio_service.as_of_snapshot(generated_at)
        live_snapshot = portfolio_service.snapshot()
        portfolio_policy_violations = self._portfolio_policy_violations(config, live_snapshot.positions)
        source_service = SourceService(self.store)
        connector_attempts = {
            connector_id: source_service.latest_connector_attempt(connector_id)
            for connector_id in set(self.LIVE_CONNECTOR_BY_SOURCE_ID.values())
        }
        entry_rows = self._entry_rows(
            config=config,
            observations=observations,
            ledger_positions=ledger_snapshot.positions,
            live_positions=live_snapshot.positions,
            live_snapshot_metadata=self._live_snapshot_metadata(generated_at),
            connector_attempts=connector_attempts,
        )
        owned_rows = [
            row
            for row in entry_rows
            if row.ownership in {"owned", "owned_historical_route"}
        ]
        quantity_blockers = [row for row in entry_rows if row.quantity_gate_status == "blocked"]
        strict_ready = (
            not invalid_entries
            and not unregistered
            and not portfolio_policy_violations
            and bool(owned_rows)
            and all(row.strict_ready for row in owned_rows)
        )
        has_blocker = bool(
            invalid_entries
            or unregistered
            or portfolio_policy_violations
            or quantity_blockers
            or any(not row.strict_ready for row in owned_rows)
        )
        status = "strict_ready" if strict_ready else "blocked" if has_blocker else "review"
        semantic_sha256 = self._semantic_digest(config, observations, entry_rows)
        artifact_path = self.artifact_root / "latest_source_registry.json"
        report = SourceRegistryRunReport(
            generated_at=generated_at,
            registry_version=config.registry_version,
            status=status,
            strict_ready=strict_ready,
            config_sha256=self._sha256(config_content),
            semantic_sha256=semantic_sha256,
            entries_count=len(config.entries),
            owned_entries_count=len(owned_rows),
            complete_entries_count=sum(row.coverage_status == "complete" for row in entry_rows),
            partial_entries_count=sum(row.coverage_status == "partial" for row in entry_rows),
            provider_coverage_gap_entries_count=sum(
                row.coverage_gate_status == "provider_gap" for row in entry_rows
            ),
            user_evidence_gap_entries_count=sum(
                row.coverage_gate_status == "missing_evidence" for row in entry_rows
            ),
            documented_route_entries_count=sum(
                row.coverage_gate_status == "documented_route" for row in entry_rows
            ),
            observed_groups_count=len(observations),
            unregistered_observations_count=len(unregistered),
            portfolio_policy_violations_count=len(portfolio_policy_violations),
            quantity_blocker_entries_count=len(quantity_blockers),
            ledger_adjustments_count=len(config.ledger_adjustments),
            applied_ledger_adjustments_count=sum(len(row.ledger_adjustments) for row in entry_rows),
            transfer_evidence_count=len(config.transfer_evidence),
            approved_transfer_evidence_count=sum(
                item.evidence_status == "approved_complete" for item in config.transfer_evidence
            ),
            invalid_entries=invalid_entries,
            unregistered_observations=unregistered,
            portfolio_policy_violations=portfolio_policy_violations,
            entries=entry_rows,
            observations=observations,
            artifact_path=self._display_path(artifact_path),
            config_path=self._display_path(self.config_path),
            findings=self._findings(
                invalid_entries=invalid_entries,
                unregistered=unregistered,
                portfolio_policy_violations=portfolio_policy_violations,
                owned_rows=owned_rows,
            ),
            next_actions=self._next_actions(entry_rows, unregistered, portfolio_policy_violations),
            methodology=(
                "Versionierte read-only Quellenregistry. Explizite Identifier ordnen Canonical Source-"
                "und Account-Gruppen nach Eigentum, Rolle, Gueltigkeitszeitraum, Portfolio- und FIFO-"
                "Policy zu. Exakte Account-/Wallet-Identifier haben Vorrang vor generischen Source-"
                "Identifiern. Fuer aktuelle eigene Portfolioquellen wird der rein historische Ledger-"
                "Bestand nur mit einem frischen live verankerten Snapshot verglichen. Status, "
                "Abrufzeit und Wertbasis werden je Quelle ausgegeben; bei stale oder missing bleibt "
                "der Wert ausdruecklich ein Ledger-Fallback und das Delta ist nicht belastbar. "
                "Unregistrierte Gruppen, im Portfolio sichtbare Infrastruktur, echte fehlende "
                "Account-Historien, dokumentierte Provider-Grenzen oder materielle Mengendeltas "
                "verhindern strict_ready. Ein ausgeschlossener historischer Transferpfad darf dagegen "
                "bestimmungsgemaess evidence_only sein, wenn Registry und Belegreferenz ihn explizit als "
                "documented_transfer_route_only klassifizieren. Beleggebundene Ledger-Overlays schliessen ausschliesslich "
                "fehlende Transfergegenbuchungen in diesem Reconciliation-Lauf; Rohledger, Canonical Events, "
                "FIFO-Lots und Steuerdaten bleiben unveraendert. Noch nicht gutgeschriebene Binance-Earn-"
                "Abgrenzungen bleiben als Live-Vermoegenswert sichtbar, werden jedoch nicht als fehlende "
                "steuerliche Ledgerbuchung gewertet."
            ),
        )
        content = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")
        self._atomic_write(artifact_path, content)
        versioned_path = self.artifact_root / f"source_registry_{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
        self._atomic_write(versioned_path, content)
        return report

    def latest(self) -> SourceRegistryRunReport | None:
        path = self.artifact_root / "latest_source_registry.json"
        try:
            return SourceRegistryRunReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _observations(self, config: SourceRegistryConfig) -> list[SourceRegistryObservation]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    source,
                    coalesce(account, wallet) as observed_account,
                    count(*)::integer,
                    min(event_time),
                    max(event_time)
                from canonical_events
                group by source, observed_account
                order by source, observed_account
                """
            ).fetchall()
        observations: list[SourceRegistryObservation] = []
        for source, account, count, first_at, last_at in rows:
            match, match_kind = self._best_match(config.entries, str(source), str(account or ""))
            observations.append(
                SourceRegistryObservation(
                    canonical_source=str(source),
                    account=str(account) if account is not None else None,
                    events_count=int(count or 0),
                    first_event_at=self._as_utc(first_at),
                    last_event_at=self._as_utc(last_at),
                    matched_source_id=match.source_id if match else None,
                    match_kind=match_kind,
                )
            )
        return observations

    def _entry_rows(
        self,
        *,
        config: SourceRegistryConfig,
        observations: list[SourceRegistryObservation],
        ledger_positions: list[object],
        live_positions: list[object],
        live_snapshot_metadata: dict[str, tuple[str, datetime | None]],
        connector_attempts: dict[str, SourceConnectorAttempt | None],
    ) -> list[SourceRegistryEntryStatus]:
        observed_by_source: defaultdict[str, list[SourceRegistryObservation]] = defaultdict(list)
        for observation in observations:
            if observation.matched_source_id:
                observed_by_source[observation.matched_source_id].append(observation)
        rows: list[SourceRegistryEntryStatus] = []
        for entry in config.entries:
            entry_observations = observed_by_source.get(entry.source_id, [])
            ledger = self._positions_for_entry(entry, ledger_positions)
            live = self._positions_for_entry(entry, live_positions)
            connector_id = self._connector_id_for_entry(entry)
            live_snapshot_status, latest_live_snapshot_at = (
                live_snapshot_metadata.get(connector_id, ("missing", None))
                if connector_id
                else ("not_applicable", None)
            )
            last_connector_attempt = (
                connector_attempts.get(connector_id) if connector_id else None
            )
            adjustments = [
                adjustment
                for adjustment in config.ledger_adjustments
                if adjustment.source_id == entry.source_id
            ]
            ledger_value = sum((position.value_eur or Decimal("0") for position in ledger), Decimal("0"))
            price_by_asset = {
                str(position.asset).upper(): position.price_eur
                for position in ledger + live
                if position.price_eur is not None
            }
            adjustment_value = sum(
                (
                    adjustment.quantity_delta
                    * price_by_asset.get(adjustment.asset.upper(), Decimal("0"))
                )
                for adjustment in adjustments
            )
            reconciled_ledger_value = ledger_value + adjustment_value
            live_nonledger_accruals: dict[str, Decimal] = {}
            if live_snapshot_status == "current":
                live_nonledger_accruals = self._live_nonledger_accrual_quantities(
                    entry,
                    live,
                )
                quantity_deltas = self._quantity_deltas(
                    ledger,
                    live,
                    adjustments,
                    live_nonledger_accruals,
                )
                live_value = sum(
                    (position.value_eur or Decimal("0") for position in live),
                    Decimal("0"),
                )
                live_nonledger_accrual_value = sum(
                    (
                        position.value_eur or Decimal("0")
                        for position in live
                        if self._is_live_nonledger_accrual_position(entry, position)
                    ),
                    Decimal("0"),
                )
                reconciliation_live_value = live_value - live_nonledger_accrual_value
                live_balance_basis = "current_live_snapshot"
            else:
                quantity_deltas = []
                live_value = reconciled_ledger_value
                live_nonledger_accrual_value = Decimal("0")
                reconciliation_live_value = reconciled_ledger_value
                live_balance_basis = (
                    "ledger_fallback"
                    if live_snapshot_status in {"stale", "missing"}
                    else "not_applicable"
                )
            quantity_status = self._quantity_status(
                entry,
                quantity_deltas,
                reconciliation_live_value,
                live_snapshot_status=live_snapshot_status,
            )
            coverage_gate_status = self._coverage_gate_status(entry)
            findings: list[str] = []
            if coverage_gate_status == "provider_gap":
                if entry.coverage_limitation == "provider_api_history_boundary":
                    findings.append(
                        "Historische Vollabdeckung ist durch die dokumentierte "
                        "Provider-API-Rueckblickgrenze begrenzt; dies ist keine "
                        "unregistrierte Quelle."
                    )
                else:
                    findings.append(
                        "Das vollstaendige Anbieterpaket enthaelt das benoetigte "
                        "Originalfeld nicht; dies ist eine Provider-Exportfeldluecke."
                    )
            elif coverage_gate_status == "missing_evidence":
                findings.append(
                    "Originale Account-History oder ein gleichwertiger Primaerbeleg fehlt."
                )
            elif coverage_gate_status == "documented_route":
                findings.append(
                    "Evidence-only ist fuer diesen ausgeschlossenen historischen "
                    "Transferpfad der dokumentierte Sollzustand."
                )
            if not entry.evidence_refs:
                findings.append("Keine Belegreferenz hinterlegt.")
            if live_snapshot_status == "stale":
                findings.append(
                    "Live-Snapshot ist nicht aktuell "
                    f"({latest_live_snapshot_at.isoformat() if latest_live_snapshot_at else 'unbekannt'}); "
                    "der angezeigte Wert ist nur der Ledger-Fallback."
                )
            elif live_snapshot_status == "missing":
                findings.append(
                    "Kein Live-Snapshot vorhanden; der angezeigte Wert ist nur der Ledger-Fallback."
                )
            if SourceService._failed_attempt_is_current(
                last_connector_attempt, latest_live_snapshot_at
            ):
                findings.append(
                    "Letzter Connector-Abruf fehlgeschlagen "
                    f"({last_connector_attempt.attempted_at.isoformat()}): "
                    f"{last_connector_attempt.message or last_connector_attempt.status}."
                )
            elif quantity_status == "blocked":
                if entry.portfolio_policy == "expected_zero":
                    findings.append(
                        "Materieller Live-Bestand widerspricht der Registry-Policy expected_zero."
                    )
                else:
                    findings.append(
                        "Materielle Live-vs-Ledger-Mengendifferenz oder unbewertete Mengendifferenz."
                    )
            elif quantity_status == "review":
                if entry.portfolio_policy == "expected_zero":
                    findings.append(
                        "Live-Bestand ueber 1 EUR widerspricht der Registry-Policy expected_zero."
                    )
                else:
                    findings.append(
                        "Live-vs-Ledger-Differenz ueber 1 EUR muss geprueft werden."
                    )
            if adjustments:
                findings.append(
                    f"{len(adjustments)} beleggebundene Ledger-Transferkorrektur(en) angewandt; Rohledger bleibt erhalten."
                )
            if live_nonledger_accruals:
                findings.append(
                    "Noch nicht gutgeschriebene Binance-Earn-Abgrenzung bleibt im "
                    "Live-Vermoegenswert, ist aber vom FIFO-/Ledger-Mengengate getrennt."
                )
            strict_ready = (
                entry.ownership not in {"owned", "owned_historical_route"}
                or (
                    coverage_gate_status in {"satisfied", "documented_route"}
                    and bool(entry.evidence_refs)
                    and quantity_status in {"matched", "not_applicable"}
                )
            )
            rows.append(
                SourceRegistryEntryStatus(
                    source_id=entry.source_id,
                    label=entry.label,
                    source_type=entry.source_type,
                    ownership=entry.ownership,
                    role=entry.role,
                    portfolio_policy=entry.portfolio_policy,
                    fifo_policy=entry.fifo_policy,
                    valid_from=entry.valid_from,
                    valid_to=entry.valid_to,
                    coverage_status=entry.coverage_status,
                    coverage_limitation=entry.coverage_limitation,
                    coverage_limitation_note=entry.coverage_limitation_note,
                    additional_user_evidence_required=(
                        entry.additional_user_evidence_required
                    ),
                    coverage_gate_status=coverage_gate_status,
                    coverage_from=entry.coverage_from,
                    coverage_to=entry.coverage_to,
                    observed_events_count=sum(item.events_count for item in entry_observations),
                    observed_first_event_at=min(
                        (item.first_event_at for item in entry_observations if item.first_event_at),
                        default=None,
                    ),
                    observed_last_event_at=max(
                        (item.last_event_at for item in entry_observations if item.last_event_at),
                        default=None,
                    ),
                    observed_accounts=sorted({item.account for item in entry_observations if item.account}),
                    evidence_refs=entry.evidence_refs,
                    current_ledger_value_eur=ledger_value,
                    current_ledger_adjustment_value_eur=adjustment_value,
                    current_reconciled_ledger_value_eur=reconciled_ledger_value,
                    current_live_anchored_value_eur=live_value,
                    current_live_nonledger_accrual_value_eur=live_nonledger_accrual_value,
                    current_reconciliation_live_value_eur=reconciliation_live_value,
                    current_value_delta_eur=(
                        reconciliation_live_value - reconciled_ledger_value
                    ),
                    live_snapshot_status=live_snapshot_status,
                    latest_live_snapshot_at=latest_live_snapshot_at,
                    live_balance_basis=live_balance_basis,
                    last_connector_attempt=last_connector_attempt,
                    ledger_adjustments=adjustments,
                    quantity_gate_status=quantity_status,
                    quantity_deltas=quantity_deltas,
                    strict_ready=strict_ready,
                    findings=findings,
                )
            )
        return rows

    @classmethod
    def _connector_id_for_entry(cls, entry: SourceRegistryEntry) -> str | None:
        configured = cls.LIVE_CONNECTOR_BY_SOURCE_ID.get(entry.source_id)
        if configured:
            return configured
        account_connectors = {
            PortfolioService.PRIMARY_SOLANA_WALLET.casefold(): "solana_wallet",
            PortfolioService.KNOWN_JUP_WALLET.casefold(): "jup_wallet",
            "binance": "binance",
            "binance spot": "binance",
            "bitget": "bitget",
            "pionex": "pionex",
            "coinbase": "coinbase",
        }
        source_connectors = {
            "binance": "binance",
            "bitget": "bitget",
            "pionex": "pionex",
            "coinbase": "coinbase",
        }
        for identifier in entry.identifiers:
            normalized = identifier.value.strip().casefold()
            if identifier.kind in {"account", "wallet", "address"}:
                connector = account_connectors.get(normalized)
                if connector:
                    return connector
            if identifier.kind == "canonical_source":
                connector = source_connectors.get(normalized)
                if connector:
                    return connector
        return None

    def _positions_for_entry(self, entry: SourceRegistryEntry, positions: list[object]) -> list[object]:
        account_values = {
            identifier.value.casefold()
            for identifier in entry.identifiers
            if identifier.kind in {"account", "wallet", "address"}
        }
        return [position for position in positions if str(position.account).casefold() in account_values]

    def _quantity_deltas(
        self,
        ledger_positions: list[object],
        live_positions: list[object],
        adjustments: list[SourceRegistryLedgerAdjustment] | None = None,
        live_nonledger_accruals: dict[str, Decimal] | None = None,
    ) -> list[SourceRegistryQuantityDelta]:
        raw_ledger_by_asset = self._position_quantities(ledger_positions)
        live_by_asset = self._position_quantities(live_positions)
        adjustment_by_asset: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for adjustment in adjustments or []:
            adjustment_by_asset[adjustment.asset.upper()] += adjustment.quantity_delta
        live_nonledger_accruals = live_nonledger_accruals or {}
        price_by_asset: dict[str, Decimal] = {}
        for position in ledger_positions + live_positions:
            if position.price_eur is not None:
                price_by_asset[str(position.asset).upper()] = position.price_eur
        rows: list[SourceRegistryQuantityDelta] = []
        for asset in sorted(
            set(raw_ledger_by_asset)
            | set(live_by_asset)
            | set(adjustment_by_asset)
            | set(live_nonledger_accruals)
        ):
            raw_ledger_quantity = raw_ledger_by_asset.get(asset, Decimal("0"))
            adjustment_quantity = adjustment_by_asset.get(asset, Decimal("0"))
            ledger_quantity = raw_ledger_quantity + adjustment_quantity
            raw_live_quantity = live_by_asset.get(asset, Decimal("0"))
            live_nonledger_accrual_quantity = live_nonledger_accruals.get(
                asset,
                Decimal("0"),
            )
            live_quantity = raw_live_quantity - live_nonledger_accrual_quantity
            delta = live_quantity - ledger_quantity
            if (
                abs(delta) <= self.QUANTITY_TOLERANCE
                and abs(live_nonledger_accrual_quantity) <= self.QUANTITY_TOLERANCE
            ):
                continue
            rows.append(
                SourceRegistryQuantityDelta(
                    asset=asset,
                    raw_ledger_quantity=raw_ledger_quantity,
                    ledger_adjustment_quantity=adjustment_quantity,
                    ledger_quantity=ledger_quantity,
                    raw_live_anchored_quantity=raw_live_quantity,
                    live_nonledger_accrual_quantity=live_nonledger_accrual_quantity,
                    live_anchored_quantity=live_quantity,
                    quantity_delta=delta,
                    value_delta_eur=delta * price_by_asset.get(asset, Decimal("0")),
                )
            )
        rows.sort(key=lambda row: (abs(row.value_delta_eur), abs(row.quantity_delta)), reverse=True)
        return rows

    def _live_nonledger_accrual_quantities(
        self,
        entry: SourceRegistryEntry,
        live_positions: list[object],
    ) -> dict[str, Decimal]:
        quantities: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for position in live_positions:
            if self._is_live_nonledger_accrual_position(entry, position):
                quantities[str(position.asset).upper()] += position.quantity
        return dict(quantities)

    def _is_live_nonledger_accrual_position(
        self,
        entry: SourceRegistryEntry,
        position: object,
    ) -> bool:
        return (
            entry.source_id == "binance-account"
            and str(position.account).casefold().startswith(
                self.BINANCE_NONLEDGER_ACCRUAL_ACCOUNT_PREFIX
            )
        )

    def _quantity_status(
        self,
        entry: SourceRegistryEntry,
        deltas: list[SourceRegistryQuantityDelta],
        live_value: Decimal,
        *,
        live_snapshot_status: str = "not_applicable",
    ) -> str:
        if entry.portfolio_policy == "exclude":
            return "not_applicable"
        if live_snapshot_status in {"stale", "missing"}:
            return "review"
        if entry.portfolio_policy == "expected_zero":
            if abs(live_value) >= self.BLOCKER_VALUE_EUR:
                return "blocked"
            if abs(live_value) >= self.REVIEW_VALUE_EUR:
                return "review"
            return "matched"
        if any(
            abs(item.value_delta_eur) >= self.BLOCKER_VALUE_EUR
            or (item.value_delta_eur == 0 and abs(item.quantity_delta) > self.QUANTITY_TOLERANCE)
            for item in deltas
        ):
            return "blocked"
        if any(abs(item.value_delta_eur) >= self.REVIEW_VALUE_EUR for item in deltas):
            return "review"
        return "matched"

    @staticmethod
    def _coverage_gate_status(entry: SourceRegistryEntry) -> str:
        if (
            entry.coverage_status == "evidence_only"
            and entry.coverage_limitation == "documented_transfer_route_only"
            and entry.portfolio_policy == "exclude"
            and entry.fifo_policy == "transfer_bridge"
        ):
            return "documented_route"
        if entry.ownership not in {"owned", "owned_historical_route"}:
            return "satisfied"
        if entry.coverage_status == "complete":
            return "satisfied"
        if entry.coverage_limitation in {
            "provider_api_history_boundary",
            "provider_export_field_gap",
        }:
            return "provider_gap"
        return "missing_evidence"

    def _live_snapshot_metadata(
        self,
        generated_at: datetime,
    ) -> dict[str, tuple[str, datetime | None]]:
        portfolio_service = PortfolioService(self.store)
        metadata: dict[str, tuple[str, datetime | None]] = {}
        for connector_id in set(self.LIVE_CONNECTOR_BY_SOURCE_ID.values()):
            latest_at = portfolio_service._latest_live_snapshot_at(connector_id)
            if latest_at is None:
                metadata[connector_id] = ("missing", None)
            else:
                comparable = latest_at
                if comparable.tzinfo is None:
                    comparable = comparable.replace(tzinfo=timezone.utc)
                if connector_id in {
                    "binance",
                    "bitget",
                    "pionex",
                    "coinbase",
                } and generated_at - comparable > self.LIVE_STALE_AFTER:
                    metadata[connector_id] = ("stale", comparable)
                else:
                    metadata[connector_id] = ("current", comparable)
        return metadata

    def _portfolio_policy_violations(
        self,
        config: SourceRegistryConfig,
        positions: list[object],
    ) -> list[str]:
        violations: set[str] = set()
        for position in positions:
            value = abs(position.value_eur or Decimal("0"))
            entry, _match_kind = self._best_match(config.entries, "", str(position.account))
            if entry is None and value >= self.REVIEW_VALUE_EUR:
                violations.add(f"Unregistriertes Portfolio-Konto: {position.account}")
            elif entry is not None and entry.portfolio_policy == "exclude" and value >= self.REVIEW_VALUE_EUR:
                violations.add(f"Ausgeschlossene Quelle im Portfolio: {entry.source_id} / {position.account}")
        return sorted(violations)

    @staticmethod
    def _position_quantities(positions: list[object]) -> dict[str, Decimal]:
        quantities: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for position in positions:
            quantities[str(position.asset).upper()] += position.quantity
        return dict(quantities)

    @classmethod
    def _best_match(
        cls,
        entries: list[SourceRegistryEntry],
        source: str,
        account: str,
    ) -> tuple[SourceRegistryEntry | None, str | None]:
        candidates: list[tuple[int, SourceRegistryEntry, str]] = []
        for entry in entries:
            for identifier in entry.identifiers:
                score = cls._identifier_score(identifier.kind, identifier.value, source, account)
                if score:
                    candidates.append((score, entry, identifier.kind))
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: (item[0], item[1].source_id), reverse=True)
        _score, entry, kind = candidates[0]
        return entry, kind

    @staticmethod
    def _identifier_score(kind: str, value: str, source: str, account: str) -> int:
        expected = value.strip().casefold()
        if kind in {"account", "wallet", "address"} and account.strip().casefold() == expected:
            return 100
        if kind == "canonical_source" and source.strip().casefold() == expected:
            return 50
        if kind == "canonical_source_prefix" and source.strip().casefold().startswith(expected):
            return 40
        return 0

    @staticmethod
    def _validate_config(config: SourceRegistryConfig) -> list[str]:
        findings: list[str] = []
        source_ids: set[str] = set()
        identifiers: dict[tuple[str, str], str] = {}
        for entry in config.entries:
            if entry.source_id in source_ids:
                findings.append(f"Doppelte source_id: {entry.source_id}")
            source_ids.add(entry.source_id)
            if entry.valid_to and entry.valid_to < entry.valid_from:
                findings.append(f"valid_to liegt vor valid_from: {entry.source_id}")
            if entry.coverage_from and entry.coverage_to and entry.coverage_to < entry.coverage_from:
                findings.append(f"coverage_to liegt vor coverage_from: {entry.source_id}")
            if (
                entry.coverage_status == "complete"
                and entry.coverage_limitation != "none"
            ):
                findings.append(
                    f"Complete-Abdeckung mit Coverage-Limitation: {entry.source_id}"
                )
            if (
                entry.coverage_status == "partial"
                and entry.ownership in {"owned", "owned_historical_route"}
                and entry.coverage_limitation == "none"
            ):
                findings.append(
                    f"Partial-Abdeckung ohne klassifizierte Limitation: {entry.source_id}"
                )
            if entry.coverage_limitation == "documented_transfer_route_only" and not (
                entry.coverage_status == "evidence_only"
                and entry.portfolio_policy == "exclude"
                and entry.fifo_policy == "transfer_bridge"
            ):
                findings.append(
                    f"Ungueltige documented-transfer-route-Kombination: {entry.source_id}"
                )
            if (
                entry.additional_user_evidence_required
                and entry.coverage_limitation != "missing_original_account_history"
            ):
                findings.append(
                    f"Nutzerbeleg angefordert ohne echte Account-History-Luecke: {entry.source_id}"
                )
            if not entry.identifiers:
                findings.append(f"Keine Identifier: {entry.source_id}")
            for identifier in entry.identifiers:
                key = (identifier.kind, identifier.value.casefold())
                previous = identifiers.get(key)
                if previous and previous != entry.source_id:
                    findings.append(
                        f"Doppelter Identifier {identifier.kind}:{identifier.value}: {previous}, {entry.source_id}"
                    )
                identifiers[key] = entry.source_id
        adjustment_ids: set[str] = set()
        for adjustment in config.ledger_adjustments:
            if adjustment.adjustment_id in adjustment_ids:
                findings.append(f"Doppelte adjustment_id: {adjustment.adjustment_id}")
            adjustment_ids.add(adjustment.adjustment_id)
            if adjustment.source_id not in source_ids:
                findings.append(
                    f"Unbekannte Anpassungsquelle {adjustment.source_id}: {adjustment.adjustment_id}"
                )
            if adjustment.target_source_id and adjustment.target_source_id not in source_ids:
                findings.append(
                    f"Unbekannte Anpassungszielquelle {adjustment.target_source_id}: {adjustment.adjustment_id}"
                )
            if adjustment.quantity_delta == 0:
                findings.append(f"Ledger-Anpassung ohne Menge: {adjustment.adjustment_id}")
            if not adjustment.tx_id.strip():
                findings.append(f"Ledger-Anpassung ohne TXID: {adjustment.adjustment_id}")
            if not adjustment.evidence_refs:
                findings.append(f"Ledger-Anpassung ohne Belegreferenz: {adjustment.adjustment_id}")
        evidence_ids: set[str] = set()
        evidence_tx_ids: set[str] = set()
        for evidence in config.transfer_evidence:
            if evidence.evidence_id in evidence_ids:
                findings.append(f"Doppelte transfer evidence_id: {evidence.evidence_id}")
            evidence_ids.add(evidence.evidence_id)
            if evidence.tx_id in evidence_tx_ids:
                findings.append(f"Doppelte Transfer-TXID: {evidence.tx_id}")
            evidence_tx_ids.add(evidence.tx_id)
            if evidence.source_id not in source_ids:
                findings.append(f"Unbekannte Transferquelle {evidence.source_id}: {evidence.evidence_id}")
            if evidence.target_source_id not in source_ids:
                findings.append(f"Unbekannte Transferzielquelle {evidence.target_source_id}: {evidence.evidence_id}")
            if evidence.quantity <= 0:
                findings.append(f"Transferbeleg ohne positive Menge: {evidence.evidence_id}")
            if not evidence.tx_id.strip():
                findings.append(f"Transferbeleg ohne TXID: {evidence.evidence_id}")
            if not evidence.evidence_refs:
                findings.append(f"Transferbeleg ohne Belegreferenz: {evidence.evidence_id}")
        return findings

    @staticmethod
    def _findings(
        *,
        invalid_entries: list[str],
        unregistered: list[SourceRegistryObservation],
        portfolio_policy_violations: list[str],
        owned_rows: list[SourceRegistryEntryStatus],
    ) -> list[str]:
        findings = list(invalid_entries)
        if unregistered:
            findings.append(f"{len(unregistered)} Canonical Source-/Account-Gruppen sind nicht registriert.")
        findings.extend(portfolio_policy_violations)
        for row in owned_rows:
            if not row.strict_ready:
                findings.append(f"{row.label}: " + " ".join(row.findings or ["nicht strict_ready"]))
        if not findings:
            findings.append("Alle eigenen Quellen sind zeitlich, fachlich und mengenbezogen belegt.")
        return findings

    @staticmethod
    def _next_actions(
        rows: list[SourceRegistryEntryStatus],
        unregistered: list[SourceRegistryObservation],
        violations: list[str],
    ) -> list[str]:
        actions: list[str] = []
        if unregistered:
            actions.append("Unregistrierte Canonical Source-/Account-Gruppen fachlich zuordnen.")
        if violations:
            actions.append("Portfolio-Policy-Verstoesse schliessen; Infrastruktur und Legacy duerfen nicht bewertet werden.")
        for row in rows:
            if row.coverage_gate_status == "provider_gap":
                actions.append(
                    f"{row.label}: dokumentierte Provider-Grenze fachlich behandeln; "
                    "identische bereits gelieferte Nutzerexporte nicht erneut anfordern."
                )
            elif row.coverage_gate_status == "missing_evidence":
                actions.append(
                    f"{row.label}: originale Account-History oder gleichwertigen "
                    "Primaerbeleg beschaffen."
                )
            if row.quantity_gate_status in {"blocked", "review"}:
                if row.live_snapshot_status in {"stale", "missing"}:
                    if SourceService._failed_attempt_is_current(
                        row.last_connector_attempt, row.latest_live_snapshot_at
                    ):
                        actions.append(
                            f"{row.label}: "
                            + SourceService._connector_error_next_action(
                                str(row.last_connector_attempt.message or "")
                            )
                        )
                    else:
                        actions.append(
                            f"{row.label}: Connector-Live-Snapshot aktualisieren; "
                            "Ledger-Fallback nicht als Livebestand auslegen."
                        )
                elif row.portfolio_policy == "expected_zero":
                    actions.append(
                        f"{row.label}: erwarteten Nullbestand gegen aktuellen Plattformbeleg "
                        "pruefen oder Registry-Policy fachlich anpassen."
                    )
                else:
                    actions.append(
                        f"{row.label}: Live-vs-Ledger-Mengendeltas anhand "
                        "TXIDs/Account-Logs schliessen."
                    )
        return list(dict.fromkeys(actions))

    @staticmethod
    def _semantic_digest(
        config: SourceRegistryConfig,
        observations: list[SourceRegistryObservation],
        rows: list[SourceRegistryEntryStatus],
    ) -> str:
        payload = {
            "config": config.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in observations],
            "entries": [item.model_dump(mode="json") for item in rows],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/source_registry"

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
