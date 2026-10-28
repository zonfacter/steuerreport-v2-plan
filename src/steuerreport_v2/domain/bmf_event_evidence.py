from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from steuerreport_v2.contracts.bmf_event_evidence import (
    BmfCanonicalEventEvidence,
    BmfEventPriceEvidence,
    BmfEventSourceEvidence,
    BmfFifoDiscrepancyEvidenceRow,
    BmfFifoEventEvidenceGroup,
    BmfFifoEventEvidenceReport,
    BmfFifoEventEvidenceRunRequest,
    BmfLedgerEvidenceGroup,
    BmfOpeningBalanceEvidence,
    BmfOriginEvidenceGroup,
    BmfOriginResolution,
)
from steuerreport_v2.contracts.bmf_fifo_staging import BmfCombinedFifoEventRow
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_fifo_staging import BmfCombinedFifoStagingService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.lot_origin import LotOriginIndex
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import (
    event_reporting_year_sql,
    reporting_tax_year,
    reporting_year_sql,
)
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


@dataclass(frozen=True)
class _Scope:
    key: str
    label: str
    assets: frozenset[str]
    years: frozenset[int]


@dataclass(frozen=True)
class _EventRecord:
    event_id: str
    event_time: datetime
    source: str
    source_ref: str | None
    event_type: str
    asset: str
    quantity: Decimal
    quote_asset: str | None
    quote_quantity: Decimal | None
    tx_id: str | None
    wallet: str | None
    account: str | None
    confidence: Decimal
    raw_object_id: str | None
    batch_id: str | None
    batch_source: str | None
    filename: str | None
    file_hash: str | None
    row_number: int | None
    payload_json: str | None


class BmfFifoEventEvidenceService:
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/bmf_event_evidence"
    STALE_PRICE_HOURS = Decimal("24")
    ONCHAIN_SOURCES = {
        "alchemy",
        "helius",
        "solana_rpc",
        "solscan",
    }
    REVIEW_ORIGIN_CLASSIFICATIONS = {
        "missing_origin",
        "origin_classification_review",
        "potential_business_inventory",
        "separate_income_review",
        "internal_transfer_fifo_carry_review",
        "opening_reconstruction_limit",
    }
    BLOCKING_EVENT_CODES = {
        "missing_canonical_event",
        "missing_raw_evidence",
        "missing_onchain_identifier",
        "received_price_missing",
        "lot_origin_unresolved",
    }
    SCOPES = (
        _Scope(
            "hnt_legacy_2021_2022",
            "HNT Legacy 2021-2022",
            frozenset({"HNT"}),
            frozenset({2021, 2022}),
        ),
        _Scope(
            "hnt_solana_2024",
            "HNT Solana 2024",
            frozenset({"HNT"}),
            frozenset({2024}),
        ),
        _Scope(
            "jup_2024_2026",
            "JUP 2024-2026",
            frozenset({"JUP"}),
            frozenset({2024, 2025, 2026}),
        ),
        _Scope(
            "sol_2024_2026",
            "SOL 2024-2026",
            frozenset({"SOL"}),
            frozenset({2024, 2025, 2026}),
        ),
        _Scope(
            "trump_2024_2026",
            "TRUMP 2024-2026",
            frozenset({"TRUMP"}),
            frozenset({2024, 2025, 2026}),
        ),
        _Scope(
            "usdt_2024_2026",
            "USDT 2024-2026",
            frozenset({"USDT"}),
            frozenset({2024, 2025, 2026}),
        ),
        _Scope(
            "mxc_2021_2026",
            "MXC 2021-2026",
            frozenset({"MXC"}),
            frozenset({2021, 2022, 2023, 2024, 2025, 2026}),
        ),
    )

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
        staging_service: BmfCombinedFifoStagingService | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()
        self.staging_service = staging_service or BmfCombinedFifoStagingService(store)

    def run(
        self,
        request: BmfFifoEventEvidenceRunRequest,
    ) -> BmfFifoEventEvidenceReport:
        staging = self.staging_service.latest()
        if staging is None:
            raise ValueError(
                "Zuerst muss ein BMF-Gesamt-FIFO-Staging-Lauf erzeugt werden."
            )
        generated_at = datetime.now(timezone.utc)
        productive_before = self.staging_service._productive_tax_sha256()
        current_input_fingerprint = WalletFifoParallelRunService(
            self.store
        ).input_fingerprint(staging.as_of)
        staging_matches_current_input = (
            staging.input_fingerprint_digest == current_input_fingerprint.digest
            and staging.origin_trace_policy == BmfCombinedFifoStagingService.ORIGIN_TRACE_POLICY
        )
        staging_matches_current = (
            staging.productive_tax_component_sha256 == productive_before
        )

        eligible = [
            row
            for row in staging.top_events
            if self._scope_for(row) is not None
            and (self._material_delta(row) >= request.min_abs_delta_eur
                 or row.lineage_issue_codes
                 or set(row.origin_classifications) & self.REVIEW_ORIGIN_CLASSIFICATIONS)
        ]
        eligible.sort(key=self._row_sort_key)
        selected = eligible[: request.limit]
        full_ledger_scope = request.scope_mode == "full_ledger"
        scope_complete = full_ledger_scope or len(selected) == len(eligible)
        evidence_staging_rows = eligible if full_ledger_scope else selected
        event_ids = {
            event_id
            for row in evidence_staging_rows
            for event_id in (
                row.disposal_event_id,
                *row.acquisition_source_event_ids,
                *row.direct_acquisition_event_ids,
                *row.lineage_event_ids,
            )
        }
        ledger_event_ids: set[str] = set()
        tax_graph_roles: dict[str, set[str]] = {}
        if full_ledger_scope:
            ledger_event_ids = self._full_ledger_event_ids(
                years=staging.years,
                as_of=staging.as_of,
            )
            tax_graph_roles = self._tax_graph_roles(
                years=staging.years,
                as_of=staging.as_of,
            )
            # Full-Ledger umfasst auch Vorjahresherkunft ausserhalb der Prioritaetsgruppen.
            for row in staging.top_events:
                tax_graph_roles.setdefault(row.disposal_event_id, set()).add("disposal")
                for event_id in set(row.acquisition_source_event_ids) | set(row.direct_acquisition_event_ids) | set(row.lineage_event_ids):
                    tax_graph_roles.setdefault(event_id, set()).add("acquisition")
            event_ids.update(ledger_event_ids)
            event_ids.update(tax_graph_roles)
        synthetic_fee_rows = {
            row.disposal_event_id: row
            for row in evidence_staging_rows
            if self._is_synthetic_fee_event_id(row.disposal_event_id)
        }
        records = self._event_records(event_ids)
        synthetic_fee_parents = self._synthetic_fee_parent_records(
            synthetic_fee_rows
        )
        price_lookup = HistoricalPriceLookup(self.store)
        evidence_by_id: dict[str, BmfCanonicalEventEvidence] = {}
        for event_id in sorted(event_ids):
            evidence = (
                self._synthetic_fee_evidence(
                    event_id,
                    synthetic_fee_rows[event_id],
                    synthetic_fee_parents.get(event_id, []),
                    price_lookup,
                )
                if event_id in synthetic_fee_rows
                else self._event_evidence(
                    event_id,
                    records.get(event_id),
                    price_lookup,
                )
            )
            roles = sorted(tax_graph_roles.get(event_id, set()))
            if roles:
                evidence = evidence.model_copy(
                    update={
                        "tax_graph_roles": roles,
                        "evidence_digest": self._sha256_json(
                            {
                                "event_evidence_digest": evidence.evidence_digest,
                                "tax_graph_roles": roles,
                            }
                        ),
                    }
                )
            evidence_by_id[event_id] = evidence

        all_discrepancy_rows = [
            self._discrepancy_row(row, evidence_by_id)
            for row in evidence_staging_rows
        ]
        discrepancy_rows = all_discrepancy_rows[: request.limit]
        groups = [
            self._group(scope, evidence_staging_rows, evidence_by_id)
            for scope in self.SCOPES
        ]

        unique_evidence = list(evidence_by_id.values())
        ready_events = [row for row in unique_evidence if row.status == "ready"]
        review_events = [row for row in unique_evidence if row.status == "review"]
        blocked_events = [row for row in unique_evidence if row.status == "blocked"]
        issue_events = sorted(
            [row for row in unique_evidence if row.status != "ready"],
            key=self._issue_sort_key,
        )
        selected_issues = issue_events[: request.issue_limit]
        unresolved_origin_rows = sum(
            1
            for row in all_discrepancy_rows
            if set(row.origin_classifications)
            & self.REVIEW_ORIGIN_CLASSIFICATIONS
        )
        documented_business_rows = sum(
            1
            for row in all_discrepancy_rows
            if "potential_business_inventory" in row.origin_classifications
        )
        documented_swap_rows = sum(
            1
            for row in all_discrepancy_rows
            if "documented_swap_acquisition" in row.origin_classifications
        )
        internal_transfer_rows = sum(
            1
            for row in all_discrepancy_rows
            if "internal_transfer_fifo_carry_review"
            in row.origin_classifications
        )
        opening_reconstruction_rows = sum(
            1
            for row in all_discrepancy_rows
            if "opening_reconstruction_limit" in row.origin_classifications
        )
        unclassified_origin_rows = sum(
            1
            for row in all_discrepancy_rows
            if set(row.origin_classifications)
            & {"origin_classification_review", "missing_origin"}
        )
        separate_income_rows = sum(
            1
            for row in all_discrepancy_rows
            if "separate_income_review" in row.origin_classifications
        )
        origin_groups = self._origin_evidence_groups(
            evidence_staging_rows,
            evidence_by_id,
        )
        opening_balance_evidence = self._opening_balance_evidence(unique_evidence)
        ledger_groups = (
            self._ledger_groups(unique_evidence) if full_ledger_scope else []
        )
        counts = self._evidence_counts(unique_evidence)
        status = self._report_status(
            blocked_events_count=len(blocked_events),
            blocked_origin_rows_count=sum(
                1 for row in all_discrepancy_rows if row.status == "blocked"
            ),
            review_events_count=len(review_events),
            unresolved_origin_rows_count=unresolved_origin_rows,
            scope_complete=scope_complete,
            staging_matches_current=(
                staging_matches_current and staging_matches_current_input
            ),
        )
        fingerprint = self._evidence_fingerprint(
            staging.run_id,
            unique_evidence,
        )
        run_id = (
            f"bmf-event-evidence-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{fingerprint[:12]}"
        )
        artifact_path = self.artifact_root / f"{run_id}.json"
        latest_path = self.artifact_root / "latest.json"
        all_event_evidence_path = self.artifact_root / f"{run_id}.events.jsonl.gz"
        productive_after = self.staging_service._productive_tax_sha256()
        productive_unchanged = productive_before == productive_after
        if not productive_unchanged:
            raise RuntimeError(
                "Read-only BMF-Eventbelegpruefung hat produktive Tax-Tabellen veraendert."
            )

        all_event_sha256, all_event_bytes = self._write_gzip_jsonl(
            all_event_evidence_path,
            unique_evidence,
        )
        findings = self._findings(
            selected_rows=len(all_discrepancy_rows),
            unique_events=len(unique_evidence),
            counts=counts,
            review_events=len(review_events),
            blocked_events=len(blocked_events),
            unresolved_origin_rows=unresolved_origin_rows,
            scope_complete=scope_complete,
            staging_matches_current=(
                staging_matches_current and staging_matches_current_input
            ),
            full_ledger_scope=full_ledger_scope,
        )
        if staging.origin_trace_policy != BmfCombinedFifoStagingService.ORIGIN_TRACE_POLICY:
            findings.append("Der gespeicherte Prueflauf verwendet noch die fruehere direkte Herkunftszuordnung. Eine neue isolierte Herkunftsvorschau ist erforderlich; alte Artefakte bleiben unveraendert.")
        if full_ledger_scope:
            unknown_tax_graph_events = sum(
                1
                for item in unique_evidence
                if (item.event_type or "").lower() == "unknown"
                and item.tax_graph_roles
            )
            findings.extend(
                [
                    f"Der Vollstaendigkeitslauf bindet {len(ledger_event_ids)} Canonical Events des Ledger-Zeitraums.",
                    f"{len(tax_graph_roles)} Events sind als Anschaffung oder Veraeusserung in der FIFO-Steuergraphik referenziert.",
                    f"{sum(1 for item in unique_evidence if (item.event_type or '').lower() == 'unknown')} Canonical Events tragen noch den Typ unknown und bleiben klassifikationsseitig im Review.",
                    f"{unknown_tax_graph_events} unknown-Events wirken als Anschaffung oder Veraeusserung im FIFO-Steuergraphen.",
                ]
            )
        findings.append(
            f"{documented_business_rows} Delta-Zeilen enthalten belegte HNT/IOT/MOBILE-Betriebsinventar-Urspruenge; "
            f"{documented_swap_rows} enthalten rohbelegte Swap-Erwerbe, {internal_transfer_rows} interne Transfer-Urspruenge mit offener FIFO-Fortfuehrung, "
            f"{opening_reconstruction_rows} eine dokumentierte Rekonstruktionsgrenze, {unclassified_origin_rows} echte Rest-Unklarheiten und "
            f"{separate_income_rows} separate Einkunfts-Urspruenge."
        )
        next_actions = self._next_actions(
            counts=counts,
            unresolved_origin_rows=unresolved_origin_rows,
            staging_matches_current=(
                staging_matches_current and staging_matches_current_input
            ),
        )
        if unclassified_origin_rows:
            next_actions.append(
                "Die verbleibenden echten Rest-Unklarheiten nur mit Originalroute oder zusaetzlichem Primaerbeleg klassifizieren."
            )
        if internal_transfer_rows:
            next_actions.append(
                "Bei belegten CEX-internen Transfers die Vorlot-Verknuepfung samt Anschaffungsdatum und Kostenbasis pruefen; der Transfer selbst ist weder Verkauf noch neuer Ertrag."
            )
        if opening_reconstruction_rows:
            next_actions.append(
                "Die dokumentierte Minimalrekonstruktion als Nachweisgrenze ausweisen; ohne Originaltransaktion keine behauptete Herkunft oder historische Kostenbasis ergaenzen."
            )
        if documented_business_rows:
            next_actions.append(
                "Belegte Mining-/Netzwerk-Rewards bis zu einer ausdruecklich dokumentierten Entnahme als Betriebsinventar fuehren; nicht automatisch in private Paragraph-23-FIFO uebernehmen."
            )

        report = BmfFifoEventEvidenceReport(
            run_id=run_id,
            generated_at=generated_at,
            status=status,
            staging_run_id=staging.run_id,
            staging_generated_at=staging.generated_at,
            staging_input_fingerprint_digest=staging.input_fingerprint_digest,
            current_input_fingerprint_digest=current_input_fingerprint.digest,
            staging_matches_current_input=staging_matches_current_input,
            staging_productive_tax_component_sha256=(
                staging.productive_tax_component_sha256
            ),
            current_productive_tax_component_sha256=productive_before,
            staging_matches_current_tax_component=staging_matches_current,
            productive_tax_tables_unchanged=productive_unchanged,
            scope_complete_for_staging_artifact=scope_complete,
            full_ledger_scope=full_ledger_scope,
            ledger_events_count=len(ledger_event_ids),
            tax_graph_events_count=len(tax_graph_roles),
            tax_graph_missing_events_count=sum(
                1 for event_id in tax_graph_roles if event_id not in records
            ),
            unknown_event_type_count=sum(
                1
                for item in unique_evidence
                if (item.event_type or "").lower() == "unknown"
            ),
            unknown_tax_graph_events_count=sum(
                1
                for item in unique_evidence
                if (item.event_type or "").lower() == "unknown"
                and item.tax_graph_roles
            ),
            staging_rows_count=len(staging.top_events),
            selected_discrepancy_rows_count=len(discrepancy_rows),
            unique_events_count=len(unique_evidence),
            ready_events_count=len(ready_events),
            review_events_count=len(review_events),
            blocked_events_count=len(blocked_events),
            raw_evidence_ready_count=counts["raw_ready"],
            independent_price_ready_count=counts["independent_price"],
            derived_price_review_count=counts["derived_price"],
            stale_price_review_count=counts["stale_price"],
            missing_price_count=counts["missing_price"],
            missing_canonical_events_count=counts["missing_event"],
            missing_raw_evidence_count=counts["missing_raw"],
            missing_required_identifiers_count=counts["missing_identifier"],
            unresolved_origin_rows_count=unresolved_origin_rows,
            documented_business_inventory_rows_count=documented_business_rows,
            documented_swap_acquisition_rows_count=documented_swap_rows,
            internal_transfer_fifo_carry_rows_count=internal_transfer_rows,
            opening_reconstruction_rows_count=opening_reconstruction_rows,
            unclassified_origin_rows_count=unclassified_origin_rows,
            separate_income_review_rows_count=separate_income_rows,
            opening_balance_events_count=len(opening_balance_evidence),
            signed_combined_delta_eur=sum(
                (row.combined_delta_eur for row in all_discrepancy_rows),
                Decimal("0"),
            ),
            absolute_combined_delta_eur=sum(
                (abs(row.combined_delta_eur) for row in all_discrepancy_rows),
                Decimal("0"),
            ),
            groups=groups,
            ledger_groups=ledger_groups,
            origin_evidence_groups=origin_groups,
            opening_balance_evidence=opening_balance_evidence,
            discrepancy_rows=discrepancy_rows,
            discrepancy_rows_truncated=(
                len(discrepancy_rows) != len(all_discrepancy_rows)
            ),
            event_issues=selected_issues,
            event_issues_truncated=len(selected_issues) != len(issue_events),
            artifact_path=self._display_path(artifact_path),
            latest_artifact_path=self._display_path(latest_path),
            all_event_evidence_artifact_path=self._display_path(
                all_event_evidence_path
            ),
            all_event_evidence_artifact_sha256=all_event_sha256,
            all_event_evidence_artifact_bytes=all_event_bytes,
            all_event_evidence_compression="gzip-jsonl",
            findings=findings,
            next_actions=next_actions,
            methodology=(
                "Versionierte read-only Belegbindung fuer "
                + (
                    "alle Canonical Events der Staging-Jahre und den vollstaendigen FIFO-Steuergraphen. "
                    if full_ledger_scope
                    else "die priorisierten Delta-Events des letzten BMF-Gesamt-FIFO-Stagings. "
                )
                + "Disposal- und Acquisition-Events "
                "werden mit Canonical Event, Raw-Importdatei/-zeile, TxID oder CEX-"
                "Referenz sowie dem am Ereigniszeitpunkt wirksamen erhaltenen und "
                "hingegebenen EUR-Preis verbunden. Abgeleitete oder mehr als 24 Stunden "
                "alte Preise bleiben Review; fehlendes Canonical Event, Rohbeleg, "
                "On-Chain-Kennzeichen oder erhaltener Tokenpreis blockiert. Rohpayloads "
                "werden nur per SHA-256 gebunden. Deterministisch erzeugte Transfer-"
                "Gebuehrenzeilen binden ihre Parent-Events und bleiben als synthetische "
                "Ableitung im Review, statt ein nicht existentes Canonical Event zu "
                "fordern. Vollstaendige Einzelnachweise werden als komprimiertes JSONL-"
                "Artefakt gespeichert; die API liefert nur Gruppen und begrenzte Issues. "
                "Der Lauf schreibt "
                "keine Steuer-, Ledger-, Preis- oder Importdaten."
            ),
        )
        content = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        self._atomic_write(artifact_path, content)
        self._atomic_write(latest_path, content)
        return report

    def latest(self) -> BmfFifoEventEvidenceReport | None:
        try:
            return BmfFifoEventEvidenceReport.model_validate_json(
                (self.artifact_root / "latest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _full_ledger_event_ids(
        self,
        *,
        years: list[int],
        as_of: datetime,
    ) -> set[str]:
        if not years:
            return set()
        placeholders = ", ".join("?" for _ in years)
        event_year = event_reporting_year_sql("event", "raw")
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select event.event_id
                from canonical_events event
                left join raw_objects raw
                  on raw.raw_object_id = event.raw_object_id
                where {event_year} in ({placeholders})
                  and event.event_time <= ?
                """,
                [*years, self._as_utc(as_of).replace(tzinfo=None)],
            ).fetchall()
        return {str(row[0]) for row in rows}

    def _tax_graph_roles(
        self,
        *,
        years: list[int],
        as_of: datetime,
    ) -> dict[str, set[str]]:
        if not years:
            return {}
        placeholders = ", ".join("?" for _ in years)
        disposal_year = reporting_year_sql("line.disposed_at")
        parameters = [
            *years,
            self._as_utc(as_of).replace(tzinfo=None),
            *years,
            self._as_utc(as_of).replace(tzinfo=None),
        ]
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select line.source_event_id, 'disposal' as event_role
                from tax_lines line
                where {disposal_year} in ({placeholders})
                  and line.disposed_at <= ?
                  and nullif(trim(line.source_event_id), '') is not null
                union all
                select coalesce(
                    nullif(trim(line.acquisition_source_event_id), ''),
                    nullif(trim(lot.source_event_id), '')
                ) as event_id,
                'acquisition' as event_role
                from tax_lines line
                left join tax_lots lot on lot.lot_id = line.lot_id
                where {disposal_year} in ({placeholders})
                  and line.disposed_at <= ?
                  and coalesce(
                    nullif(trim(line.acquisition_source_event_id), ''),
                    nullif(trim(lot.source_event_id), '')
                  ) is not null
                """,
                parameters,
            ).fetchall()
        result: dict[str, set[str]] = defaultdict(set)
        for event_id, event_role in rows:
            result[str(event_id)].add(str(event_role))
        with self.store.connect() as con:
            cursor = con.execute(f"""select line.* from tax_lines line
                where {disposal_year} in ({placeholders}) and line.disposed_at <= ?""",
                [*years, self._as_utc(as_of).replace(tzinfo=None)])
            columns = [item[0] for item in cursor.description]
            lines = [SimpleNamespace(**dict(zip(columns, row))) for row in cursor.fetchall()]
        index = LotOriginIndex(TaxService(self.store).list_tax_lots(), self.store.list_canonical_events())
        for line in lines:
            for event_id in index.source_event_ids(index.resolve(line)):
                result[event_id].add("acquisition")
        return dict(result)

    def _origin_evidence_groups(
        self,
        rows: list[BmfCombinedFifoEventRow],
        evidence_by_id: dict[str, BmfCanonicalEventEvidence],
    ) -> list[BmfOriginEvidenceGroup]:
        grouped: dict[
            tuple[str, str | None, str | None, str | None],
            dict[str, object],
        ] = defaultdict(
            lambda: {
                "event_ids": set(),
                "disposal_ids": set(),
                "evidence": [],
            }
        )
        for row in rows:
            for event_id in sorted(set(row.acquisition_source_event_ids)):
                evidence = evidence_by_id[event_id]
                classification = self._origin_classification(evidence)
                key = (
                    classification,
                    evidence.source,
                    evidence.event_type,
                    row.asset.upper(),
                )
                grouped[key]["event_ids"].add(event_id)  # type: ignore[union-attr]
                grouped[key]["disposal_ids"].add(  # type: ignore[union-attr]
                    row.disposal_event_id
                )
                grouped[key]["evidence"].append(evidence)  # type: ignore[union-attr]

        result: list[BmfOriginEvidenceGroup] = []
        for key, values in grouped.items():
            classification, source, event_type, asset = key
            evidence_rows = {
                item.event_id: item
                for item in values["evidence"]  # type: ignore[union-attr]
            }
            unique = list(evidence_rows.values())
            blocked = any(item.status == "blocked" for item in unique)
            raw_ready = sum(
                1 for item in unique if item.source_evidence.raw_object_id
            )
            resolutions = [
                self._origin_resolution_for_evidence(item) for item in unique
            ]
            primary_resolution = resolutions[0]
            tax_sphere = primary_resolution.tax_sphere
            status = "blocked" if blocked else primary_resolution.status
            decision_basis = primary_resolution.decision_basis
            evidence_markers = sorted(
                {
                    marker
                    for resolution in resolutions
                    for marker in resolution.evidence_markers
                }
            )
            fifo_carry_required = any(
                resolution.fifo_carry_forward_required
                for resolution in resolutions
            )
            event_times = [item.event_time for item in unique if item.event_time]
            result.append(
                BmfOriginEvidenceGroup(
                    classification=classification,
                    source=source,
                    event_type=event_type,
                    asset=asset,
                    canonical_event_assets=sorted(
                        {
                            item.asset.upper()
                            for item in unique
                            if item.asset
                        }
                    ),
                    unique_origin_events_count=len(unique),
                    affected_discrepancy_rows_count=len(
                        values["disposal_ids"]  # type: ignore[arg-type]
                    ),
                    raw_evidence_ready_count=raw_ready,
                    first_event_at=min(event_times) if event_times else None,
                    last_event_at=max(event_times) if event_times else None,
                    status=status,  # type: ignore[arg-type]
                    tax_sphere=tax_sphere,  # type: ignore[arg-type]
                    evidence_markers=evidence_markers,
                    fifo_carry_forward_required=fifo_carry_required,
                    decision_basis=decision_basis,
                    evidence_digest=self._sha256_text(
                        "\n".join(
                            f"{item.event_id}:{item.evidence_digest}"
                            for item in sorted(unique, key=lambda value: value.event_id)
                        )
                    ),
                )
            )
        result.sort(
            key=lambda item: (
                0 if item.status == "blocked" else 1 if item.status == "review" else 2,
                item.classification,
                item.source or "",
                item.event_type or "",
                item.asset or "",
            )
        )
        return result

    @classmethod
    def _origin_classification(cls, event: BmfCanonicalEventEvidence) -> str:
        return cls._origin_resolution_for_evidence(event).classification

    @classmethod
    def _origin_resolution_for_evidence(
        cls,
        event: BmfCanonicalEventEvidence,
    ) -> BmfOriginResolution:
        if event.origin_resolution is not None:
            return event.origin_resolution
        if event.event_time is None:
            return BmfOriginResolution(
                classification="missing_origin",
                status="blocked",
                tax_sphere="unclassified",
                decision_basis=(
                    "Das Ursprungslot ist nicht mit einem Canonical Event verbunden."
                ),
            )
        asset = (event.asset or "").upper()
        source = (event.source or "").lower() or None
        event_type = (event.event_type or "").lower() or None
        if asset in BusinessRewardInventoryReviewService.DEFAULT_ASSETS:
            classification, reason = (
                BusinessRewardInventoryReviewService.classify_origin(
                    source,
                    event_type,
                )
            )
            return cls._generic_origin_resolution(classification, reason)
        if event_type in {"mining", "reward", "staking"}:
            return cls._generic_origin_resolution(
                "separate_income_review",
                "Reward-/Mining-/Staking-Zugang ausserhalb der Helium-Assets ist als separate Einkunftsart zu pruefen.",
            )
        return cls._generic_origin_resolution(
            "non_reward_origin",
            "Der direkte Ursprung ist kein Reward-, Mining- oder Staking-Ereignis.",
        )

    @classmethod
    def _resolve_origin(cls, event: _EventRecord) -> BmfOriginResolution:
        source = event.source.strip().lower()
        event_type = event.event_type.strip().lower()
        asset = event.asset.strip().upper()
        payload_values, payload_text = cls._origin_payload_values(
            event.payload_json
        )
        operation_values = payload_values.get("operation", set())
        action_values = payload_values.get("action", set())
        defi_labels = payload_values.get("defi_label", set())
        evidence_markers: list[str] = []

        reward_programs = {
            "setcurrentrewardswrapperv1": "program:SetCurrentRewardsWrapperV1",
            "setcurrentrewardsv0": "program:SetCurrentRewardsV0",
            "distributecompressionrewardsv0": (
                "program:DistributeCompressionRewardsV0"
            ),
        }
        normalized_payload = "".join(
            character.lower()
            for character in payload_text
            if character.isalnum()
        )
        matched_reward_programs = sorted(
            marker
            for key, marker in reward_programs.items()
            if key in normalized_payload
        )
        if (
            asset in BusinessRewardInventoryReviewService.DEFAULT_ASSETS
            and matched_reward_programs
        ):
            evidence_markers.extend(matched_reward_programs)
            evidence_markers.extend(
                f"raw:defi_label={value}"
                for value in sorted(defi_labels)
                if value
            )
            return BmfOriginResolution(
                classification="potential_business_inventory",
                status="documented",
                tax_sphere="business_inventory",
                evidence_markers=sorted(set(evidence_markers)),
                decision_basis=(
                    "Der gebundene Raw-Beleg enthaelt ein Helium-Rewards-Programm. "
                    "Der Zugang ist daher als Netzwerk-Reward dokumentiert und bleibt "
                    "bis zu einer belegten Entnahme im betrieblichen Pruefpfad."
                ),
            )

        if source == "opening-balance":
            marker = (
                f"raw:file={event.filename}"
                if event.filename
                else "raw:source=opening-balance"
            )
            return BmfOriginResolution(
                classification="opening_reconstruction_limit",
                status="review",
                tax_sphere="opening_reconstruction",
                evidence_markers=[marker],
                fifo_carry_forward_required=True,
                decision_basis=(
                    "Der gebundene Opening-Balance-Beleg dokumentiert eine Rekonstruktionsgrenze, "
                    "aber keine Originalanschaffung. Er ist kein Reward und kein Live-Zufluss; "
                    "die historische Kostenbasis bleibt auf die dokumentierte Grenze beschraenkt."
                ),
            )

        strategy_actions = {
            value for value in action_values if value.startswith("strategy_transfer_")
        }
        simple_earn_redemptions = {
            value
            for value in operation_values
            if "simple earn" in value
            and any(
                token in value
                for token in ("redemption", "subscription", "transfer")
            )
        }
        if (source == "bitget" and strategy_actions) or (
            source == "binance" and simple_earn_redemptions
        ):
            evidence_markers.extend(
                f"raw:action={value}" for value in sorted(strategy_actions)
            )
            evidence_markers.extend(
                f"raw:operation={value}"
                for value in sorted(simple_earn_redemptions)
            )
            return BmfOriginResolution(
                classification="internal_transfer_fifo_carry_review",
                status="review",
                tax_sphere="fifo_carry_forward",
                evidence_markers=evidence_markers,
                fifo_carry_forward_required=True,
                decision_basis=(
                    "Der Raw-Beleg bezeichnet eine interne CEX-Umbuchung. Sie ist weder "
                    "Verkauf noch neuer Ertrag; Anschaffungsdatum und Kostenbasis muessen "
                    "aus dem Vorlot fortgefuehrt und gesondert verknuepft werden."
                ),
            )

        simple_earn_income = {
            value
            for value in operation_values
            if "simple earn" in value
            and any(
                token in value
                for token in ("interest", "reward", "distribution")
            )
        }
        if source == "binance" and simple_earn_income:
            return BmfOriginResolution(
                classification="separate_income_review",
                status="review",
                tax_sphere="separate_income",
                evidence_markers=[
                    f"raw:operation={value}"
                    for value in sorted(simple_earn_income)
                ],
                decision_basis=(
                    "Der Binance-Rohbeleg bezeichnet Simple-Earn-Ertrag. Er ist getrennt "
                    "von Helium-Mining-/Netzwerk-Rewards steuerlich einzuordnen."
                ),
            )

        if "swap" in defi_labels and event_type in {
            "income",
            "trade",
            "transfer",
        }:
            return BmfOriginResolution(
                classification="documented_swap_acquisition",
                status="documented",
                tax_sphere="private_acquisition",
                evidence_markers=["raw:defi_label=swap"],
                decision_basis=(
                    "Der On-Chain-Rohbeleg kennzeichnet den Zugang als Swap-Gegenleistung. "
                    "Er ist ein Anschaffungsvorgang und kein Mining-, Reward- oder "
                    "Staking-Ertrag."
                ),
            )

        if asset in BusinessRewardInventoryReviewService.DEFAULT_ASSETS:
            classification, reason = (
                BusinessRewardInventoryReviewService.classify_origin(
                    source or None,
                    event_type or None,
                )
            )
            return cls._generic_origin_resolution(classification, reason)
        if event_type in {"mining", "reward", "staking"}:
            return cls._generic_origin_resolution(
                "separate_income_review",
                "Reward-/Mining-/Staking-Zugang ausserhalb der Helium-Assets ist als separate Einkunftsart zu pruefen.",
            )
        return cls._generic_origin_resolution(
            "non_reward_origin",
            "Der direkte Ursprung ist kein Reward-, Mining- oder Staking-Ereignis.",
        )

    @staticmethod
    def _generic_origin_resolution(
        classification: str,
        decision_basis: str,
    ) -> BmfOriginResolution:
        mapping = {
            "potential_business_inventory": ("documented", "business_inventory"),
            "separate_income_review": ("review", "separate_income"),
            "origin_classification_review": ("review", "unclassified"),
            "missing_origin": ("blocked", "unclassified"),
            "non_reward_origin": ("documented", "non_reward"),
        }
        status, tax_sphere = mapping[classification]
        return BmfOriginResolution(
            classification=classification,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            tax_sphere=tax_sphere,  # type: ignore[arg-type]
            decision_basis=decision_basis,
        )

    @staticmethod
    def _origin_payload_values(
        payload_json: str | None,
    ) -> tuple[dict[str, set[str]], str]:
        if not payload_json:
            return {}, ""
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            return {}, payload_json
        selected_keys = {
            "action",
            "defi_label",
            "operation",
        }
        result: dict[str, set[str]] = defaultdict(set)
        pending = [payload]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                for key, nested in value.items():
                    normalized_key = str(key).strip().lower()
                    if normalized_key in selected_keys and not isinstance(
                        nested,
                        (dict, list),
                    ):
                        text = str(nested).strip().lower()
                        if text:
                            result[normalized_key].add(text)
                    elif isinstance(nested, (dict, list)):
                        pending.append(nested)
            elif isinstance(value, list):
                pending.extend(value)
        return dict(result), json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _opening_balance_evidence(
        self,
        evidence: list[BmfCanonicalEventEvidence],
    ) -> list[BmfOpeningBalanceEvidence]:
        result: list[BmfOpeningBalanceEvidence] = []
        for item in evidence:
            if (item.source or "").lower() != "opening-balance" or not item.event_time:
                continue
            source_evidence = item.source_evidence
            filename = source_evidence.filename or ""
            if (
                item.asset == "HNT"
                and item.source_ref == "pionex-hnt-minimum-reconciliation-2022"
                and filename.endswith("pionex_hnt_minimum_reconciliation_2022.csv")
            ):
                documentation_status = "documented_minimum_reconstruction"
                limitations = [
                    "Der vollstaendige Pionex-Trade-Export belegt die notwendige Minimalmenge, nicht die urspruengliche Anschaffung.",
                    "Die Rekonstruktion nutzt konservativ 0,00 EUR Kostenbasis.",
                    "Es wird weder ein externer Zufluss noch ein Reward oder Eigenwallet-Transfer behauptet.",
                ]
            elif filename.endswith("opening-balance-adjustments.csv"):
                documentation_status = "balance_adjustment_only"
                limitations = [
                    "Die CSV belegt nur eine historische Saldenkorrektur.",
                    "Originaltransaktion, Gegenkonto und urspruengliche Anschaffung sind nicht belegt.",
                    "Der Eintrag darf nicht als Live-Zufluss oder Eigenwallet-Transfer interpretiert werden.",
                ]
            else:
                documentation_status = "undocumented"
                limitations = [
                    "Der Opening-Balance-Eintrag besitzt keine bekannte fachliche Rekonstruktionsakte."
                ]
            result.append(
                BmfOpeningBalanceEvidence(
                    event_id=item.event_id,
                    event_time=item.event_time,
                    source=item.source or "opening-balance",
                    account=item.account,
                    asset=item.asset or "",
                    quantity=item.quantity or Decimal("0"),
                    source_ref=item.source_ref,
                    tx_id=item.tx_id,
                    raw_object_id=source_evidence.raw_object_id,
                    raw_filename=source_evidence.filename,
                    raw_row_number=source_evidence.row_number,
                    raw_payload_sha256=source_evidence.raw_payload_sha256,
                    documentation_status=documentation_status,  # type: ignore[arg-type]
                    original_transaction_available=False,
                    limitations=limitations,
                    evidence_digest=self._sha256_json(
                        {
                            "event_evidence_digest": item.evidence_digest,
                            "documentation_status": documentation_status,
                            "limitations": limitations,
                        }
                    ),
                )
            )
        result.sort(key=lambda item: (item.event_time, item.event_id))
        return result

    def _ledger_groups(
        self,
        evidence: list[BmfCanonicalEventEvidence],
    ) -> list[BmfLedgerEvidenceGroup]:
        grouped: dict[
            tuple[int, str, str],
            list[BmfCanonicalEventEvidence],
        ] = defaultdict(list)
        for item in evidence:
            if item.event_time is None:
                continue
            grouped[
                (
                    reporting_tax_year(item.event_time),
                    item.source or "missing",
                    item.event_type or "missing",
                )
            ].append(item)
        result: list[BmfLedgerEvidenceGroup] = []
        for (year, source, event_type), rows in grouped.items():
            counts = self._evidence_counts(rows)
            result.append(
                BmfLedgerEvidenceGroup(
                    year=year,
                    source=source,
                    event_type=event_type,
                    events_count=len(rows),
                    tax_graph_events_count=sum(
                        1 for item in rows if item.tax_graph_roles
                    ),
                    ready_events_count=sum(
                        1 for item in rows if item.status == "ready"
                    ),
                    review_events_count=sum(
                        1 for item in rows if item.status == "review"
                    ),
                    blocked_events_count=sum(
                        1 for item in rows if item.status == "blocked"
                    ),
                    raw_evidence_ready_count=counts["raw_ready"],
                    independent_price_ready_count=counts["independent_price"],
                    derived_price_review_count=counts["derived_price"],
                    stale_price_review_count=counts["stale_price"],
                    missing_price_count=counts["missing_price"],
                    issue_codes=sorted(
                        {
                            code
                            for item in rows
                            for code in item.issue_codes
                        }
                    ),
                )
            )
        result.sort(key=lambda item: (item.year, item.source, item.event_type))
        return result

    def _write_gzip_jsonl(
        self,
        path: Path,
        evidence: list[BmfCanonicalEventEvidence],
    ) -> tuple[str, int]:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as raw_file:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_file,
                mtime=0,
            ) as compressed:
                for item in sorted(evidence, key=lambda row: row.event_id):
                    payload = json.dumps(
                        item.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    compressed.write(payload + b"\n")
        temporary.replace(path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), path.stat().st_size

    def _event_records(self, event_ids: set[str]) -> dict[str, _EventRecord]:
        if not event_ids:
            return {}
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    e.event_id,
                    e.event_time,
                    e.source,
                    e.source_ref,
                    e.event_type,
                    e.asset,
                    e.quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    e.tx_id,
                    e.wallet,
                    e.account,
                    e.confidence,
                    e.raw_object_id,
                    r.batch_id,
                    b.source,
                    b.filename,
                    b.file_hash,
                    r.row_number,
                    r.payload_json
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where e.event_id in (select unnest(?))
                """,
                [sorted(event_ids)],
            ).fetchall()
        return {row[0]: self._record_from_row(row) for row in rows}

    def _synthetic_fee_parent_records(
        self,
        synthetic_rows: dict[str, BmfCombinedFifoEventRow],
    ) -> dict[str, list[_EventRecord]]:
        if not synthetic_rows:
            return {}
        direct_ids: set[str] = set()
        tx_ids: set[str] = set()
        event_times: set[datetime] = set()
        for event_id, row in synthetic_rows.items():
            ids, tx_id = self._synthetic_fee_parent_keys(event_id)
            direct_ids.update(ids)
            if tx_id:
                tx_ids.add(tx_id)
            event_times.add(row.disposed_at.replace(tzinfo=None))
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    e.event_id,
                    e.event_time,
                    e.source,
                    e.source_ref,
                    e.event_type,
                    e.asset,
                    e.quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    e.tx_id,
                    e.wallet,
                    e.account,
                    e.confidence,
                    e.raw_object_id,
                    r.batch_id,
                    b.source,
                    b.filename,
                    b.file_hash,
                    r.row_number,
                    r.payload_json
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where e.event_id in (select unnest(?))
                   or coalesce(e.tx_id, '') in (select unnest(?))
                   or e.event_time in (select unnest(?))
                """,
                [
                    sorted(direct_ids) or ["__none__"],
                    sorted(tx_ids) or ["__none__"],
                    sorted(event_times),
                ],
            ).fetchall()
        candidates = [self._record_from_row(row) for row in rows]
        result: dict[str, list[_EventRecord]] = {}
        for event_id, row in synthetic_rows.items():
            ids, tx_id = self._synthetic_fee_parent_keys(event_id)
            selected: dict[str, _EventRecord] = {}
            for candidate in candidates:
                same_time_asset = (
                    candidate.event_time == self._as_utc(row.disposed_at)
                    and candidate.asset.upper() == row.asset.upper()
                )
                if (
                    candidate.event_id in ids
                    or (tx_id is not None and candidate.tx_id == tx_id)
                    or same_time_asset
                ):
                    selected[candidate.event_id] = candidate
            result[event_id] = sorted(
                selected.values(),
                key=lambda item: (
                    item.event_time != self._as_utc(row.disposed_at),
                    item.raw_object_id is None,
                    item.event_id,
                ),
            )
        return result

    @classmethod
    def _synthetic_fee_parent_keys(
        cls,
        event_id: str,
    ) -> tuple[set[str], str | None]:
        parts = event_id.split(":")
        if event_id.startswith("cross-cex:") and len(parts) >= 4:
            return {parts[1], parts[2]}, None
        if event_id.startswith("solana-program-escrow:") and len(parts) >= 3:
            return {parts[1]}, None
        if event_id.startswith("external:") and len(parts) >= 3:
            return set(), parts[1]
        return set(), None

    @staticmethod
    def _is_synthetic_fee_event_id(event_id: str) -> bool:
        return event_id.startswith(
            ("external:", "solana-program-escrow:", "cross-cex:")
        ) and event_id.endswith(":fee")

    def _record_from_row(self, row: tuple[object, ...]) -> _EventRecord:
        return _EventRecord(
            event_id=str(row[0]),
            event_time=self._as_utc(row[1]),  # type: ignore[arg-type]
            source=str(row[2]),
            source_ref=str(row[3]) if row[3] is not None else None,
            event_type=str(row[4]),
            asset=str(row[5]),
            quantity=Decimal(str(row[6])),
            quote_asset=str(row[7]) if row[7] is not None else None,
            quote_quantity=(
                Decimal(str(row[8])) if row[8] is not None else None
            ),
            tx_id=str(row[9]) if row[9] is not None else None,
            wallet=str(row[10]) if row[10] is not None else None,
            account=str(row[11]) if row[11] is not None else None,
            confidence=Decimal(str(row[12] or "0")),
            raw_object_id=str(row[13]) if row[13] is not None else None,
            batch_id=str(row[14]) if row[14] is not None else None,
            batch_source=str(row[15]) if row[15] is not None else None,
            filename=str(row[16]) if row[16] is not None else None,
            file_hash=str(row[17]) if row[17] is not None else None,
            row_number=int(row[18]) if row[18] is not None else None,
            payload_json=str(row[19]) if row[19] is not None else None,
        )

    def _event_evidence(
        self,
        event_id: str,
        event: _EventRecord | None,
        price_lookup: HistoricalPriceLookup,
    ) -> BmfCanonicalEventEvidence:
        if event is None:
            source_evidence = BmfEventSourceEvidence(
                identifier_kind="missing",
                status="blocked",
                issue_codes=["missing_canonical_event"],
            )
            return BmfCanonicalEventEvidence(
                event_id=event_id,
                source_evidence=source_evidence,
                origin_resolution=BmfOriginResolution(
                    classification="missing_origin",
                    status="blocked",
                    tax_sphere="unclassified",
                    decision_basis=(
                        "Das Ursprungslot ist nicht mit einem Canonical Event verbunden."
                    ),
                ),
                status="blocked",
                issue_codes=["missing_canonical_event"],
                evidence_digest=self._sha256_text(
                    f"{event_id}|missing_canonical_event"
                ),
            )

        source_evidence = self._source_evidence(event)
        origin_resolution = self._resolve_origin(event)
        received, given = self._price_evidence(event, price_lookup)
        issue_codes = list(source_evidence.issue_codes)
        if event.event_type.strip().lower() == "unknown":
            issue_codes.append("event_type_classification_review")
        if received.quality == "missing":
            issue_codes.append("received_price_missing")
        elif received.quality in {"derived_review", "derived_stale_review"}:
            issue_codes.append("received_price_derived")
        if received.quality in {"stale_review", "derived_stale_review"}:
            issue_codes.append("received_price_stale")
        if received.confidence is not None and received.confidence < Decimal("0.9"):
            issue_codes.append("received_price_low_confidence")
        if given is not None:
            if given.quality == "missing":
                issue_codes.append("given_price_missing_context")
            elif given.quality in {"derived_review", "derived_stale_review"}:
                issue_codes.append("given_price_derived")
            if given.quality in {"stale_review", "derived_stale_review"}:
                issue_codes.append("given_price_stale")
            if given.confidence is not None and given.confidence < Decimal("0.9"):
                issue_codes.append("given_price_low_confidence")
        issue_codes = sorted(set(issue_codes))
        status = self._line_status(issue_codes)
        digest_payload = {
            "event_id": event.event_id,
            "event_time": event.event_time.isoformat(),
            "source": event.source,
            "source_ref": event.source_ref,
            "event_type": event.event_type,
            "asset": event.asset,
            "quantity": str(event.quantity),
            "quote_asset": event.quote_asset,
            "quote_quantity": str(event.quote_quantity),
            "tx_id": event.tx_id,
            "raw": source_evidence.model_dump(mode="json"),
            "origin_resolution": origin_resolution.model_dump(mode="json"),
            "received_price": received.model_dump(mode="json"),
            "given_price": given.model_dump(mode="json") if given else None,
        }
        return BmfCanonicalEventEvidence(
            event_id=event.event_id,
            event_time=event.event_time,
            source=event.source,
            source_ref=event.source_ref,
            event_type=event.event_type,
            asset=event.asset,
            quantity=event.quantity,
            quote_asset=event.quote_asset,
            quote_quantity=event.quote_quantity,
            tx_id=event.tx_id,
            wallet=event.wallet,
            account=event.account,
            confidence=event.confidence,
            source_evidence=source_evidence,
            origin_resolution=origin_resolution,
            received_price=received,
            given_price=given,
            status=status,
            issue_codes=issue_codes,
            evidence_digest=self._sha256_json(digest_payload),
        )

    def _synthetic_fee_evidence(
        self,
        event_id: str,
        row: BmfCombinedFifoEventRow,
        parents: list[_EventRecord],
        price_lookup: HistoricalPriceLookup,
    ) -> BmfCanonicalEventEvidence:
        if not parents:
            return self._event_evidence(event_id, None, price_lookup)
        parent_evidence = [self._source_evidence(parent) for parent in parents]
        primary = parents[0]
        source_evidence = parent_evidence[0]
        issue_codes = ["synthetic_fee_parent_evidence_review"]
        if not any(item.raw_object_id for item in parent_evidence):
            issue_codes.append("missing_raw_evidence")
        fee_quantity = max(
            abs(row.received_first_wallet_quantity),
            abs(row.active_wallet_quantity),
        )
        given = self._one_price(
            "given",
            row.asset,
            fee_quantity,
            self._as_utc(row.disposed_at),
            price_lookup,
        )
        if given.quality == "missing":
            issue_codes.append("given_price_missing_context")
        elif given.quality in {"derived_review", "derived_stale_review"}:
            issue_codes.append("given_price_derived")
        if given.quality in {"stale_review", "derived_stale_review"}:
            issue_codes.append("given_price_stale")
        if given.confidence is not None and given.confidence < Decimal("0.9"):
            issue_codes.append("given_price_low_confidence")
        issue_codes = sorted(set(issue_codes))
        digest_payload = {
            "event_id": event_id,
            "event_time": self._as_utc(row.disposed_at).isoformat(),
            "asset": row.asset,
            "quantity": str(-fee_quantity),
            "derivation": "wallet_fifo_explicit_transfer_fee",
            "parent_event_ids": [parent.event_id for parent in parents],
            "parent_source_evidence": [
                item.model_dump(mode="json") for item in parent_evidence
            ],
            "given_price": given.model_dump(mode="json"),
        }
        return BmfCanonicalEventEvidence(
            event_id=event_id,
            event_time=self._as_utc(row.disposed_at),
            source="wallet_fifo_preview",
            source_ref=event_id,
            event_type="fee",
            asset=row.asset,
            quantity=-fee_quantity,
            tx_id=primary.tx_id,
            wallet=primary.wallet,
            account=primary.account,
            confidence=Decimal("1"),
            synthetic_derivation="wallet_fifo_explicit_transfer_fee",
            parent_event_ids=[parent.event_id for parent in parents],
            parent_source_evidence=parent_evidence,
            source_evidence=source_evidence,
            received_price=None,
            given_price=given,
            status=self._line_status(issue_codes),  # type: ignore[arg-type]
            issue_codes=issue_codes,
            evidence_digest=self._sha256_json(digest_payload),
        )

    def _source_evidence(self, event: _EventRecord) -> BmfEventSourceEvidence:
        issue_codes: list[str] = []
        if not event.raw_object_id or not event.batch_id:
            issue_codes.append("missing_raw_evidence")
        source_key = event.source.strip().lower()
        if source_key in self.ONCHAIN_SOURCES and not (
            event.tx_id or event.source_ref
        ):
            issue_codes.append("missing_onchain_identifier")
        if source_key == "opening-balance":
            if (
                event.asset.upper() == "HNT"
                and event.source_ref
                == "pionex-hnt-minimum-reconciliation-2022"
                and (event.filename or "").endswith(
                    "pionex_hnt_minimum_reconciliation_2022.csv"
                )
            ):
                issue_codes.append(
                    "opening_balance_minimum_reconstruction_documented"
                )
            elif (event.filename or "").endswith(
                "opening-balance-adjustments.csv"
            ):
                issue_codes.append("opening_balance_adjustment_only_review")
            else:
                issue_codes.append("opening_balance_source_review")

        if event.tx_id:
            identifier_kind = "tx_id"
            identifier_value = event.tx_id
        elif event.source_ref:
            identifier_kind = "source_ref"
            identifier_value = event.source_ref
        elif event.raw_object_id:
            identifier_kind = "raw_batch_row"
            identifier_value = (
                f"{event.batch_id}:{event.row_number}"
                if event.row_number is not None
                else event.raw_object_id
            )
        else:
            identifier_kind = "missing"
            identifier_value = None
        status = self._line_status(issue_codes)
        return BmfEventSourceEvidence(
            raw_object_id=event.raw_object_id,
            batch_id=event.batch_id,
            batch_source=event.batch_source,
            filename=event.filename,
            file_hash=event.file_hash,
            row_number=event.row_number,
            raw_payload_sha256=(
                self._sha256_text(event.payload_json)
                if event.payload_json is not None
                else None
            ),
            identifier_kind=identifier_kind,  # type: ignore[arg-type]
            identifier_value=identifier_value,
            status=status,
            issue_codes=sorted(set(issue_codes)),
        )

    def _price_evidence(
        self,
        event: _EventRecord,
        lookup: HistoricalPriceLookup,
    ) -> tuple[BmfEventPriceEvidence, BmfEventPriceEvidence | None]:
        if event.event_type == "transfer" or (
            event.quantity == 0
            and (event.quote_quantity is None or event.quote_quantity == 0)
        ):
            return (
                BmfEventPriceEvidence(
                    role="received",
                    asset=event.asset.upper(),
                    quantity=abs(event.quantity),
                    quality="not_required",
                ),
                None,
            )
        if (
            event.event_type == "trade"
            and event.quote_asset
            and event.quote_quantity is not None
        ):
            if event.quantity > 0:
                received_asset = event.asset
                received_quantity = abs(event.quantity)
                given_asset = event.quote_asset
                given_quantity = abs(event.quote_quantity)
            else:
                received_asset = event.quote_asset
                received_quantity = abs(event.quote_quantity)
                given_asset = event.asset
                given_quantity = abs(event.quantity)
            return (
                self._one_price(
                    "received",
                    received_asset,
                    received_quantity,
                    event.event_time,
                    lookup,
                ),
                self._one_price(
                    "given",
                    given_asset,
                    given_quantity,
                    event.event_time,
                    lookup,
                ),
            )
        return (
            self._one_price(
                "received",
                event.asset,
                abs(event.quantity),
                event.event_time,
                lookup,
            ),
            None,
        )

    def _one_price(
        self,
        role: str,
        asset: str,
        quantity: Decimal,
        event_time: datetime,
        lookup: HistoricalPriceLookup,
    ) -> BmfEventPriceEvidence:
        point = lookup.at_or_before(asset, event_time)
        if point is None:
            return BmfEventPriceEvidence(
                role=role,  # type: ignore[arg-type]
                asset=asset.upper(),
                quantity=quantity,
                quality="missing",
            )
        priced_at = self._as_utc(point.priced_at)
        age_hours = max(
            Decimal("0"),
            Decimal(str((event_time - priced_at).total_seconds()))
            / Decimal("3600"),
        )
        derived = lookup.is_derived_source(point.source)
        stale = age_hours > self.STALE_PRICE_HOURS
        if derived and stale:
            quality = "derived_stale_review"
        elif derived:
            quality = "derived_review"
        elif stale:
            quality = "stale_review"
        else:
            quality = "independent_current"
        return BmfEventPriceEvidence(
            role=role,  # type: ignore[arg-type]
            asset=asset.upper(),
            quantity=quantity,
            price_id=point.price_id,
            price_eur=point.price_eur,
            priced_at=priced_at,
            source=point.source,
            confidence=point.confidence,
            age_hours=age_hours,
            value_eur=point.price_eur * quantity,
            quality=quality,  # type: ignore[arg-type]
        )

    def _discrepancy_row(
        self,
        row: BmfCombinedFifoEventRow,
        evidence_by_id: dict[str, BmfCanonicalEventEvidence],
    ) -> BmfFifoDiscrepancyEvidenceRow:
        scope = self._scope_for(row)
        if scope is None:
            raise ValueError("Event liegt ausserhalb des Eventbeleg-Pruefumfangs.")
        disposal = evidence_by_id[row.disposal_event_id]
        acquisition_ids = sorted(set(row.acquisition_source_event_ids) | set(row.direct_acquisition_event_ids) | set(row.lineage_event_ids))
        acquisition_evidence = [evidence_by_id[item] for item in acquisition_ids]
        resolved_origin_classifications = sorted(
            {
                self._origin_classification(item)
                for item in acquisition_evidence if item.event_id in row.acquisition_source_event_ids
            }
        )
        if row.lineage_issue_codes:
            resolved_origin_classifications = sorted(set(resolved_origin_classifications) | {"missing_origin"})
        elif not row.acquisition_source_event_ids:
            resolved_origin_classifications = sorted(set(row.origin_classifications) & self.REVIEW_ORIGIN_CLASSIFICATIONS)
        issue_event_ids = [
            item.event_id for item in acquisition_evidence if item.status != "ready"
        ]
        issue_codes = list(disposal.issue_codes)
        if row.lineage_issue_codes:
            issue_codes.append("lot_origin_unresolved")
            issue_codes.extend("lot_origin:" + code for code in row.lineage_issue_codes)
        issue_codes.extend(
            code
            for item in acquisition_evidence
            for code in item.issue_codes
        )
        origin_review = (
            set(resolved_origin_classifications)
            & self.REVIEW_ORIGIN_CLASSIFICATIONS
        )
        issue_codes.extend(
            f"origin:{classification}" for classification in sorted(origin_review)
        )
        issue_codes = sorted(set(issue_codes))
        status = self._line_status(issue_codes)
        acquisition_digest = self._sha256_text(
            "\n".join(
                f"{item.event_id}:{item.evidence_digest}"
                for item in acquisition_evidence
            )
        )
        return BmfFifoDiscrepancyEvidenceRow(
            scope_key=scope.key,
            year=row.year,
            asset=row.asset,
            disposal_event_id=row.disposal_event_id,
            disposed_at=row.disposed_at,
            source=row.source,
            account=row.account,
            tx_id=row.tx_id,
            active_global_gain_loss_eur=row.active_global_gain_loss_eur,
            received_first_global_gain_loss_eur=(
                row.received_first_global_gain_loss_eur
            ),
            active_wallet_gain_loss_eur=row.active_wallet_gain_loss_eur,
            received_first_wallet_gain_loss_eur=(
                row.received_first_wallet_gain_loss_eur
            ),
            price_policy_delta_eur=row.price_policy_delta_eur,
            wallet_scope_delta_eur=row.wallet_scope_delta_eur,
            combined_delta_eur=row.combined_delta_eur,
            interaction_delta_eur=row.interaction_delta_eur,
            disposal_evidence_status=disposal.status,
            acquisition_events_count=len(acquisition_evidence),
            acquisition_ready_count=sum(
                1 for item in acquisition_evidence if item.status == "ready"
            ),
            acquisition_review_count=sum(
                1 for item in acquisition_evidence if item.status == "review"
            ),
            acquisition_blocked_count=sum(
                1 for item in acquisition_evidence if item.status == "blocked"
            ),
            acquisition_raw_ready_count=sum(
                1
                for item in acquisition_evidence
                if item.source_evidence.raw_object_id is not None
            ),
            acquisition_independent_price_count=sum(
                1
                for item in acquisition_evidence
                if item.received_price is not None
                and item.received_price.quality == "independent_current"
            ),
            acquisition_issue_event_ids=issue_event_ids[:50],
            acquisition_issue_event_ids_truncated=len(issue_event_ids) > 50,
            acquisition_evidence_digest=acquisition_digest,
            origin_classifications=resolved_origin_classifications,
            lineage_issue_codes=row.lineage_issue_codes,
            direct_acquisition_event_ids=row.direct_acquisition_event_ids,
            lineage_event_ids=row.lineage_event_ids,
            status=status,
            issue_codes=issue_codes,
            asset_fifo_drilldown_endpoint=(
                f"/api/v1/tax-years/{row.year}/asset-fifo-drilldown?asset={row.asset}"
            ),
        )

    def _group(
        self,
        scope: _Scope,
        rows: list[BmfCombinedFifoEventRow],
        evidence_by_id: dict[str, BmfCanonicalEventEvidence],
    ) -> BmfFifoEventEvidenceGroup:
        selected = [row for row in rows if self._scope_for(row) == scope]
        event_ids = {
            event_id
            for row in selected
            for event_id in (
                row.disposal_event_id,
                *row.acquisition_source_event_ids,
                *row.direct_acquisition_event_ids,
                *row.lineage_event_ids,
            )
        }
        evidence = [evidence_by_id[item] for item in sorted(event_ids)]
        counts = self._evidence_counts(evidence)
        issue_codes = sorted(
            {
                code
                for item in evidence
                for code in item.issue_codes
            }
            | {
                f"origin:{classification}"
                for row in selected
                for event_id in row.acquisition_source_event_ids
                for classification in [
                    self._origin_classification(evidence_by_id[event_id])
                ]
                if classification in self.REVIEW_ORIGIN_CLASSIFICATIONS
            }
            | {"lot_origin_unresolved" for row in selected if row.lineage_issue_codes}
            | {"lot_origin:" + code for row in selected for code in row.lineage_issue_codes}
            | {"origin:" + classification for row in selected if not row.acquisition_source_event_ids
               for classification in row.origin_classifications if classification in self.REVIEW_ORIGIN_CLASSIFICATIONS}
        )
        if not selected:
            status = "not_applicable"
        elif any(item.status == "blocked" for item in evidence) or set(issue_codes) & self.BLOCKING_EVENT_CODES:
            status = "blocked"
        elif issue_codes:
            status = "review"
        else:
            status = "ready"
        return BmfFifoEventEvidenceGroup(
            scope_key=scope.key,
            label=scope.label,
            years=sorted(scope.years),
            assets=sorted(scope.assets),
            status=status,  # type: ignore[arg-type]
            discrepancy_rows_count=len(selected),
            unique_events_count=len(evidence),
            ready_events_count=sum(1 for item in evidence if item.status == "ready"),
            review_events_count=sum(
                1 for item in evidence if item.status == "review"
            ),
            blocked_events_count=sum(
                1 for item in evidence if item.status == "blocked"
            ),
            raw_evidence_ready_count=counts["raw_ready"],
            independent_price_ready_count=counts["independent_price"],
            derived_price_review_count=counts["derived_price"],
            stale_price_review_count=counts["stale_price"],
            missing_price_count=counts["missing_price"],
            signed_combined_delta_eur=sum(
                (row.combined_delta_eur for row in selected), Decimal("0")
            ),
            absolute_combined_delta_eur=sum(
                (abs(row.combined_delta_eur) for row in selected), Decimal("0")
            ),
            issue_codes=issue_codes,
        )

    @classmethod
    def _scope_for(cls, row: BmfCombinedFifoEventRow) -> _Scope | None:
        asset = row.asset.upper()
        return next(
            (
                scope
                for scope in cls.SCOPES
                if asset in scope.assets and row.year in scope.years
            ),
            None,
        )

    @staticmethod
    def _material_delta(row: BmfCombinedFifoEventRow) -> Decimal:
        return max(
            abs(row.price_policy_delta_eur),
            abs(row.wallet_scope_delta_eur),
            abs(row.combined_delta_eur),
        )

    @classmethod
    def _row_sort_key(
        cls,
        row: BmfCombinedFifoEventRow,
    ) -> tuple[Decimal, int, str, str]:
        return (
            -cls._material_delta(row),
            row.year,
            row.asset,
            row.disposal_event_id,
        )

    @staticmethod
    def _issue_sort_key(
        row: BmfCanonicalEventEvidence,
    ) -> tuple[int, str, str]:
        rank = 0 if row.status == "blocked" else 1
        event_time = row.event_time.isoformat() if row.event_time else ""
        return (rank, event_time, row.event_id)

    @classmethod
    def _line_status(cls, issue_codes: list[str]) -> str:
        if set(issue_codes) & cls.BLOCKING_EVENT_CODES:
            return "blocked"
        if issue_codes:
            return "review"
        return "ready"

    @staticmethod
    def _evidence_counts(
        evidence: list[BmfCanonicalEventEvidence],
    ) -> dict[str, int]:
        price_roles = [
            [
                price
                for price in (item.received_price, item.given_price)
                if price is not None
            ]
            for item in evidence
        ]
        return {
            "raw_ready": sum(
                1 for item in evidence if item.source_evidence.raw_object_id
            ),
            "independent_price": sum(
                1
                for roles in price_roles
                if roles
                and all(item.quality == "independent_current" for item in roles)
            ),
            "derived_price": sum(
                1
                for roles in price_roles
                if any(
                    item.quality in {"derived_review", "derived_stale_review"}
                    for item in roles
                )
            ),
            "stale_price": sum(
                1
                for roles in price_roles
                if any(
                    item.quality in {"stale_review", "derived_stale_review"}
                    for item in roles
                )
            ),
            "missing_price": sum(
                1
                for roles in price_roles
                if any(item.quality == "missing" for item in roles)
            )
            + sum(
                1
                for item in evidence
                if item.received_price is None and item.event_type != "fee"
            ),
            "missing_event": sum(
                1 for item in evidence if "missing_canonical_event" in item.issue_codes
            ),
            "missing_raw": sum(
                1 for item in evidence if "missing_raw_evidence" in item.issue_codes
            ),
            "missing_identifier": sum(
                1
                for item in evidence
                if "missing_onchain_identifier" in item.issue_codes
            ),
        }

    @staticmethod
    def _report_status(
        *,
        blocked_events_count: int,
        review_events_count: int,
        unresolved_origin_rows_count: int,
        scope_complete: bool,
        staging_matches_current: bool,
        blocked_origin_rows_count: int = 0,
    ) -> str:
        if blocked_events_count or blocked_origin_rows_count or not staging_matches_current:
            return "blocked"
        if review_events_count or unresolved_origin_rows_count or not scope_complete:
            return "review"
        return "ready_for_professional_review"

    @classmethod
    def _evidence_fingerprint(
        cls,
        staging_run_id: str,
        evidence: list[BmfCanonicalEventEvidence],
    ) -> str:
        return cls._sha256_text(
            staging_run_id
            + "\n"
            + "\n".join(
                f"{item.event_id}:{item.evidence_digest}"
                for item in sorted(evidence, key=lambda row: row.event_id)
            )
        )

    @staticmethod
    def _findings(
        *,
        selected_rows: int,
        unique_events: int,
        counts: dict[str, int],
        review_events: int,
        blocked_events: int,
        unresolved_origin_rows: int,
        scope_complete: bool,
        staging_matches_current: bool,
        full_ledger_scope: bool,
    ) -> list[str]:
        findings = [
            (
                f"{selected_rows} Staging-Delta-Zeilen wurden mit {unique_events} eindeutigen Ledger-/FIFO-Eventbelegen zusammengefuehrt."
                if full_ledger_scope
                else f"{selected_rows} priorisierte Delta-Events binden {unique_events} eindeutige Disposal-/Acquisition-Events."
            ),
            f"{counts['raw_ready']} Events besitzen einen lokalen Rohbeleg; {counts['missing_raw']} Rohbelege fehlen.",
            f"{counts['independent_price']} Events nutzen einen unabhaengigen Preis innerhalb von 24 Stunden; {counts['derived_price']} nutzen einen abgeleiteten und {counts['stale_price']} einen veralteten Preis.",
            f"{blocked_events} Events sind technisch blockiert, {review_events} benoetigen fachliche Preis-/Quellenpruefung.",
            f"{unresolved_origin_rows} Delta-Zeilen enthalten einen offenen oder betrieblichen Reward-Ursprung.",
        ]
        if not scope_complete:
            findings.append(
                "Der angeforderte Zeilen-Limit schneidet den priorisierten Ausschnitt des Staging-Artefakts ab."
            )
        if not staging_matches_current:
            findings.append(
                "Das Staging-Artefakt passt nicht mehr zum aktuellen produktiven Tax-Komponenten-Hash."
            )
        return findings

    @staticmethod
    def _next_actions(
        *,
        counts: dict[str, int],
        unresolved_origin_rows: int,
        staging_matches_current: bool,
    ) -> list[str]:
        actions: list[str] = []
        if not staging_matches_current:
            actions.append(
                "BMF-Gesamt-FIFO-Staging auf dem aktuellen Datenstand neu ausfuehren."
            )
        if counts["missing_event"] or counts["missing_raw"] or counts["missing_identifier"]:
            actions.append(
                "Blockierte Eventbelege aus Original-CEX-Ledger oder On-Chain-TxID nachziehen und erneut binden."
            )
        if counts["derived_price"] or counts["stale_price"]:
            actions.append(
                "Abgeleitete oder mehr als 24 Stunden alte Eventpreise datumsscharf durch eine unabhaengige archivierte EUR-Quelle ersetzen."
            )
        if unresolved_origin_rows:
            actions.append(
                "HNT/IOT/MOBILE-Anschaffungslots als Reward-Betriebsvermoegen, dokumentierte Entnahme oder nicht-betrieblichen Ursprung fachlich versionieren."
            )
        if not actions:
            actions.append(
                "Eventbeleg-Worklist fachlich abnehmen und danach die kombinierte FIFO-Zielmethode separat freigeben."
            )
        return actions

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/bmf_event_evidence"

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(cls.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _sha256_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def _sha256_json(cls, value: object) -> str:
        return cls._sha256_text(
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
