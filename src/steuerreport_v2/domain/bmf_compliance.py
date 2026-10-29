from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from steuerreport_v2.contracts.tax_methodology import (
    TaxBmfComplianceMatrix,
    TaxBmfComplianceMetric,
    TaxBmfComplianceRequirement,
    TaxBmfComplianceStatus,
    TaxBmfImplementationStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.bitget_strategy_basis_decisions import (
    BitgetStrategyBasisDecisionService,
)
from steuerreport_v2.domain.legal_research import LegalResearchService
from steuerreport_v2.domain.bmf_event_evidence import BmfFifoEventEvidenceService
from steuerreport_v2.domain.bmf_fifo_staging import BmfCombinedFifoStagingService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_filing_snapshots import TaxFilingSnapshotService
from steuerreport_v2.domain.swap_valuation import CryptoSwapValuationReviewService
from steuerreport_v2.domain.swap_valuation_parallel import (
    CryptoSwapFifoParallelPreviewService,
)
from steuerreport_v2.domain.tax_time import TaxTimePolicyService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


class BmfComplianceMatrixService:
    MATRIX_VERSION = "bmf_requirements_2025_v13"
    BMF_REFERENCE = "BMF-Schreiben vom 6. Maerz 2025 zu Kryptowerten"
    BMF_REFERENCE_URL = (
        "https://www.bundesfinanzministerium.de/Content/DE/Downloads/"
        "BMF_Schreiben/Steuerarten/Einkommensteuer/"
        "2025-03-06-einzelfragen-kryptowerte-bmf-schreiben.pdf"
    )
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    WALLET_FIFO_LATEST = PROJECT_ROOT / "var/wallet_fifo_runs/latest_wallet_fifo_run.json"
    WALLET_FIFO_MIGRATION_LATEST = (
        PROJECT_ROOT
        / "var/wallet_fifo_migrations/latest_wallet_fifo_migration_rehearsal.json"
    )
    SOURCE_REGISTRY_LATEST = PROJECT_ROOT / "var/source_registry/latest_source_registry.json"
    STICHTAG_GATE_LATEST = PROJECT_ROOT / "var/valuation_runs/latest_valuation_gate.json"
    LEGAL_RESEARCH_ARTIFACT_ROOT = PROJECT_ROOT / "var/legal_research_freshness"

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        if store.path.resolve() == self.DEFAULT_DB.resolve():
            self.wallet_fifo_latest = self.WALLET_FIFO_LATEST
            self.wallet_fifo_migration_latest = self.WALLET_FIFO_MIGRATION_LATEST
            self.source_registry_latest = self.SOURCE_REGISTRY_LATEST
            self.stichtag_gate_latest = self.STICHTAG_GATE_LATEST
            self.legal_research_artifact_root = self.LEGAL_RESEARCH_ARTIFACT_ROOT
        else:
            artifact_root = store.path.parent / "var"
            self.wallet_fifo_latest = artifact_root / "wallet_fifo_runs/latest_wallet_fifo_run.json"
            self.wallet_fifo_migration_latest = (
                artifact_root
                / "wallet_fifo_migrations/latest_wallet_fifo_migration_rehearsal.json"
            )
            self.source_registry_latest = artifact_root / "source_registry/latest_source_registry.json"
            self.stichtag_gate_latest = artifact_root / "valuation_runs/latest_valuation_gate.json"
            self.legal_research_artifact_root = artifact_root / "legal_research_freshness"

    def matrix(self) -> TaxBmfComplianceMatrix:
        counts = self._counts()
        scope_years = self._available_years()
        filing = self._filing_snapshot(scope_years)
        filing_archives = TaxFilingSnapshotService(self.store).governance_status()
        filing_archive_status: TaxBmfComplianceStatus = (
            "blocked"
            if int(filing_archives["integrity_failures"]) > 0
            else "review"
            if filing_archives["unconfirmed_reference_years"]
            or filing_archives["submission_timestamp_missing_years"]
            else "satisfied"
        )
        wallet_fifo = self._artifact_state(self.wallet_fifo_latest)
        wallet_fifo_migration = self._artifact_state(
            self.wallet_fifo_migration_latest
        )
        wallet_fifo_acceptance = WalletFifoMethodAcceptanceService(
            self.store
        ).readiness()
        bitget_basis_decision = BitgetStrategyBasisDecisionService(
            self.store
        ).readiness()
        active_fifo = TaxMethodologyService(self.store).active_fifo_scope()
        source_registry = self._artifact_state(self.source_registry_latest)
        stichtag_gate = self._artifact_state(self.stichtag_gate_latest)
        legal_research = LegalResearchService(
            artifact_root=self.legal_research_artifact_root
        ).latest()
        legal_research_ready = bool(
            legal_research is not None
            and legal_research.status == "fresh"
            and legal_research.is_fresh
            and legal_research.official_sources_reachable
        )
        time_precision = TaxTimePolicyService(self.store).audit(limit=20)
        business_inventory = BusinessRewardInventoryReviewService(self.store).review()
        swap_valuation = CryptoSwapValuationReviewService(self.store).review(limit=20)
        swap_fifo_parallel = CryptoSwapFifoParallelPreviewService(self.store).latest()
        swap_fifo_parallel_ready = bool(
            swap_fifo_parallel is not None and swap_fifo_parallel.status == "matched"
        )
        combined_fifo_staging = BmfCombinedFifoStagingService(self.store).latest()
        combined_fifo_staging_ready = bool(
            combined_fifo_staging is not None
            and combined_fifo_staging.status == "ready_for_professional_review"
            and combined_fifo_staging.productive_tax_tables_unchanged
            and combined_fifo_staging.potential_business_inventory_tax_lines_count == 0
            and combined_fifo_staging.unresolved_reward_origin_tax_lines_count == 0
            and combined_fifo_staging.active_global.unmatched_count == 0
            and combined_fifo_staging.received_first_global.unmatched_count == 0
            and combined_fifo_staging.active_wallet.unmatched_count == 0
            and combined_fifo_staging.received_first_wallet.unmatched_count == 0
        )
        fifo_event_evidence = BmfFifoEventEvidenceService(self.store).latest()
        fifo_event_evidence_status = (
            "blocked"
            if fifo_event_evidence is None
            or fifo_event_evidence.status == "blocked"
            or not fifo_event_evidence.full_ledger_scope
            or fifo_event_evidence.tax_graph_missing_events_count > 0
            or not fifo_event_evidence.all_event_evidence_artifact_sha256
            or not fifo_event_evidence.staging_matches_current_input
            or (
                combined_fifo_staging is not None
                and fifo_event_evidence.staging_run_id != combined_fifo_staging.run_id
            )
            else "review"
            if fifo_event_evidence.status == "review"
            else "satisfied"
        )
        governance_artifacts = {
            "wallet_fifo": wallet_fifo,
            "source_registry": source_registry,
            "valuation_gate": stichtag_gate,
        }
        available_governance_artifacts = [
            name
            for name, state in governance_artifacts.items()
            if state["status"] not in {"missing", "invalid"}
        ]
        evidence_access_ready = (
            counts["raw_batches_count"] > 0
            and len(available_governance_artifacts) == len(governance_artifacts)
            and time_precision.reporting_policy_applied
        )

        requirements = [
            self._requirement(
                requirement_id="current_legal_sources",
                title="Aktueller Rechts-, Verwaltungs- und Rechtsprechungsstand",
                bmf_paragraphs=["Rechtsstand-Governance"],
                requirement=(
                    "Vor einer BMF- oder Abgabereife-Aussage muessen die versionierten "
                    "offiziellen Gesetzes-, BMF-, BFH- und Gesetzgebungsquellen aktuell, "
                    "erreichbar und ohne ungeprueften Neufund sein."
                ),
                implementation_status="implemented",
                evidence_status="satisfied" if legal_research_ready else "blocked",
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "legal_research_status",
                        "Offizieller Rechtsquellenlauf",
                        legal_research.status if legal_research else "missing",
                        "fresh",
                        "satisfied" if legal_research_ready else "blocked",
                        (
                            f"Generiert {legal_research.generated_at.isoformat()}, "
                            f"gueltig bis {legal_research.fresh_until.isoformat()}."
                            if legal_research
                            else "Kein versionierter Rechtsquellenlauf vorhanden."
                        ),
                    ),
                    self._metric(
                        "legal_research_open_findings",
                        "Offene Quellenfehler oder Neufunde",
                        (
                            len(legal_research.failed_check_ids)
                            + len(legal_research.changed_source_ids)
                            + len(legal_research.review_required_urls)
                            if legal_research
                            else 1
                        ),
                        "0",
                        "satisfied" if legal_research_ready else "blocked",
                        "Neue Fundstellen werden nie automatisch in Steuerregeln uebernommen.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax-methodology/legal-research/freshness",
                    "/api/v1/tax-methodology/legal-research/sources",
                    "configs/legal_research_sources.json",
                ],
                findings=(
                    list(legal_research.findings)
                    if legal_research
                    else ["Rechtsquellen-Freshness-Artefakt fehlt. Aktueller Rechtsstand ist nicht bestaetigt."]
                ),
                next_action=(
                    "Offizielle Rechtsquellen pruefen, Neufunde fachlich einordnen und erst "
                    "danach die deterministische Methodik versioniert anpassen."
                ),
            ),
            self._requirement(
                requirement_id="report_plausibility",
                title="Plausibler und reproduzierbarer Steuerreport",
                bmf_paragraphs=["29b", "90", "101"],
                requirement=(
                    "Report muss vollstaendig, widerspruchsfrei und anhand der Quellen, "
                    "Reporteinstellungen und steuerlichen Methoden nachrechenbar sein."
                ),
                implementation_status="implemented",
                evidence_status=self._filing_status(filing),
                affected_years=filing["conservative_years"] + filing["review_years"] + filing["blocked_years"],
                metrics=[
                    self._metric(
                        "filing_snapshot",
                        "BMF-Filing-Snapshot",
                        filing["snapshot_status"],
                        "available und ohne Review-/Blockerjahre",
                        self._filing_status(filing),
                        "Versionierter Jahresstatus statt Ableitung aus dem Export-Gate.",
                    ),
                    self._metric(
                        "conservative_years",
                        "Konservativ belegbare Jahre",
                        len(filing["conservative_years"]),
                        "0",
                        "review" if filing["conservative_years"] else "satisfied",
                        "Konservative Anlagen sind offen zu legen und keine strenge BMF-Freigabe.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax-methodology/bmf-filing-readiness-snapshot",
                    "/api/v1/tax-methodology/bmf-finalization-matrix",
                ],
                findings=self._filing_findings(filing),
                next_action=(
                    "Alle Matrix-Blocker schliessen und danach einen neuen versionierten "
                    "BMF-Filing-Snapshot erzeugen."
                ),
            ),
            self._requirement(
                requirement_id="filing_snapshot_immutability",
                title="Unveraenderbarer Abgabestand und erkennbare Korrekturen",
                bmf_paragraphs=["90", "95", "96", "98", "101", "§ 146 Abs. 4 AO"],
                requirement=(
                    "Tatsaechlich verwendete Abgabepakete muessen unveraenderlich, "
                    "hashgebunden und mit ihren spaeteren Anpassungen nachvollziehbar "
                    "aufbewahrt werden. Eine Korrektur darf den Altstand nicht ersetzen."
                ),
                implementation_status="implemented",
                evidence_status=filing_archive_status,
                affected_years=sorted(
                    set(filing_archives["unconfirmed_reference_years"])
                    | set(filing_archives["submission_timestamp_missing_years"])
                ),
                metrics=[
                    self._metric(
                        "immutable_filing_snapshots",
                        "Registrierte Abgabestaende",
                        int(filing_archives["snapshots_count"]),
                        "alle tatsaechlich verwendeten Pakete registriert",
                        filing_archive_status,
                        (
                            "ZIP, Manifest, Einzeldateien und Laufzeit-Fingerprint sind "
                            "SHA-256-gebunden und append-only registriert."
                        ),
                    ),
                    self._metric(
                        "submitted_filing_years",
                        "Als tatsaechlich eingereicht bestaetigte Jahre",
                        len(filing_archives["submitted_years"]),
                        "entspricht den tatsaechlich abgegebenen Jahren",
                        (
                            "satisfied"
                            if not filing_archives["unconfirmed_reference_years"]
                            and not filing_archives["submission_timestamp_missing_years"]
                            else "review"
                        ),
                        "Eine Referenz wird nie automatisch als beim Finanzamt eingereicht behauptet.",
                    ),
                    self._metric(
                        "filing_usage_confirmed_years",
                        "Als Erklaerungsgrundlage bestaetigte Referenzjahre",
                        len(filing_archives["usage_confirmed_reference_years"]),
                        "0 ohne Uebermittlungszeitpunkt",
                        (
                            "review"
                            if filing_archives["submission_timestamp_missing_years"]
                            else "satisfied"
                        ),
                        (
                            "Die Paketverwendung ist als Nutzererklaerung append-only belegt; "
                            "sie ersetzt keinen ELSTER-Uebermittlungszeitpunkt."
                        ),
                    ),
                    self._metric(
                        "filing_archive_integrity_failures",
                        "Archiv-Hashfehler",
                        int(filing_archives["integrity_failures"]),
                        "0",
                        (
                            "satisfied"
                            if int(filing_archives["integrity_failures"]) == 0
                            else "blocked"
                        ),
                        "Fehlende oder veraenderte ZIP-Dateien blockieren den Nachweis.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax-filing-snapshots",
                    "/api/v1/tax-years/{year}/filing-snapshot-comparison",
                    "/api/v1/tax-years/{year}/filing-snapshot-comparison.html",
                ],
                findings=(
                    [
                        "Mindestens ein archivierter Paketstand ist nicht mehr hashidentisch vorhanden."
                    ]
                    if int(filing_archives["integrity_failures"]) > 0
                    else [
                        "Paketverwendung bestaetigt, tatsaechlicher ELSTER-"
                        "Uebermittlungszeitpunkt noch offen: "
                        + ", ".join(
                            str(year)
                            for year in filing_archives[
                                "submission_timestamp_missing_years"
                            ]
                        )
                    ]
                    if filing_archives["submission_timestamp_missing_years"]
                    else [
                        "Historische Referenzpakete warten noch auf den Abgleich mit der tatsaechlichen Abgabe: "
                        + ", ".join(
                            str(year)
                            for year in filing_archives["unconfirmed_reference_years"]
                        )
                    ]
                    if filing_archives["unconfirmed_reference_years"]
                    else [
                        "Das append-only Abgabearchiv ist technisch bereit und ohne Integritaetsfehler."
                    ]
                ),
                next_action=(
                    "Referenzpakete nur nach Abgleich mit der tatsaechlich uebermittelten "
                    "Erklaerung als verwendet bestaetigen; den echten ELSTER-Zeitpunkt "
                    "getrennt nachtragen und Abweichungen je Einkunftsart pruefen."
                ),
            ),
            self._requirement(
                requirement_id="source_completeness",
                title="Vollstaendige Quellen und Originalaufzeichnungen",
                bmf_paragraphs=["29a", "87", "88", "89", "101"],
                requirement=(
                    "Alle Wallets, CEX/DEX-Plattformen und Transaktionsuebersichten muessen "
                    "vollstaendig, rechtzeitig und mit Originalbelegen erfasst sein."
                ),
                implementation_status=(
                    "implemented"
                    if source_registry["status"] not in {"missing", "invalid"}
                    else "partial"
                ),
                evidence_status="satisfied" if source_registry["strict_ready"] else "blocked",
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "sources",
                        "Kanonische Quellen",
                        counts["sources_count"],
                        "alle tatsaechlich genutzten Quellen",
                        "review" if counts["sources_count"] else "blocked",
                        "Eine Anzahl allein beweist keine zeitliche Vollstaendigkeit.",
                    ),
                    self._metric(
                        "raw_objects",
                        "Gesicherte Rohobjekte",
                        counts["raw_objects_count"],
                        "> 0 bei importierten Plattformdaten",
                        "satisfied" if counts["raw_objects_count"] else "review",
                        "Rohobjekte bleiben getrennt von Canonical Events erhalten.",
                    ),
                    self._metric(
                        "source_registry",
                        "Zeitabhaengige Quellenregistry",
                        source_registry["status"],
                        "strict_ready",
                        "satisfied" if source_registry["strict_ready"] else "blocked",
                        (
                            "Eigentum, Rolle, Gueltigkeitszeitraum und Abdeckung sind fuer alle Quellen nachgewiesen."
                            if source_registry["strict_ready"]
                            else (
                                "Registry vorhanden: "
                                f"{int(source_registry['provider_coverage_gap_entries_count'])} Provider-Grenzen, "
                                f"fehlende Account-Belege: {int(source_registry['user_evidence_gap_entries_count'])}."
                            )
                        ),
                    ),
                    self._metric(
                        "source_registry_provider_coverage_gaps",
                        "Dokumentierte Provider-Abdeckungsgrenzen",
                        int(source_registry["provider_coverage_gap_entries_count"]),
                        "0 oder fachlich konservativ behandelt",
                        (
                            "satisfied"
                            if int(source_registry["provider_coverage_gap_entries_count"]) == 0
                            else "review"
                        ),
                        "API-Rueckblick- und Exportfeldgrenzen werden getrennt von fehlenden Nutzerbelegen ausgewiesen.",
                    ),
                    self._metric(
                        "source_registry_user_evidence_gaps",
                        "Echte fehlende Nutzer-/Account-Belege",
                        int(source_registry["user_evidence_gap_entries_count"]),
                        "0",
                        (
                            "satisfied"
                            if int(source_registry["user_evidence_gap_entries_count"]) == 0
                            else "blocked"
                        ),
                        "Nur hier fehlt eine originale Account-History oder ein gleichwertiger Primaerbeleg.",
                    ),
                    self._metric(
                        "source_registry_documented_routes",
                        "Bestimmungsgemaesse Evidence-only-Transferpfade",
                        int(source_registry["documented_route_entries_count"]),
                        ">= 0 und explizit klassifiziert",
                        "satisfied",
                        "Historische Service- und Staking-Gegenpfade sind keine aktuellen eigenen Portfolio-Wallets.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/sources/overview",
                    "/api/v1/sources/registry/config",
                    "/api/v1/sources/registry/runs/latest",
                    "/api/v1/import/coverage",
                    "docs/627_QUELLEN_CONNECTOR_SETUP_UND_WALLET_REGISTRY_2026-07-05.md",
                ],
                findings=(
                    ["Die zeitabhaengige Ownership-/Coverage-Registry ist implementiert und strict_ready."]
                    if source_registry["strict_ready"]
                    else [
                        f"Die versionierte Quellenregistry ist vorhanden, aber Status ist {source_registry['status']}.",
                        (
                            f"Provider-bedingte Abdeckungsgrenzen: {int(source_registry['provider_coverage_gap_entries_count'])}; "
                            f"echte fehlende Account-Belege: {int(source_registry['user_evidence_gap_entries_count'])}; "
                            f"bestimmungsgemaesse Evidence-only-Transferpfade: {int(source_registry['documented_route_entries_count'])}."
                        ),
                        "Live-vs-Ledger-Mengendeltas bleiben davon getrennt in den Registry-Findings sichtbar.",
                    ]
                ),
                next_action=(
                    "Echte Account-Belegluecken beschaffen, Provider-Grenzen konservativ "
                    "fachlich behandeln und verbleibende Mengendeltas separat schliessen."
                ),
            ),
            self._requirement(
                requirement_id="transaction_traceability",
                title="Einzeltransaktions- und Lot-Nachvollziehbarkeit",
                bmf_paragraphs=["102", "103"],
                requirement=(
                    "Jeder steuerliche Vorgang muss Asset, Menge, Zeitpunkte, Kurse, "
                    "Anschaffungskosten, Erloes, Gebuehren und Haltedauer erkennen lassen."
                ),
                implementation_status="implemented",
                evidence_status=(
                    "not_applicable"
                    if counts["tax_lines_count"] == 0
                    else "satisfied"
                    if counts["orphan_tax_lines_count"] == 0
                    else "blocked"
                ),
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "tax_lines",
                        "Steuerliche Einzelzeilen",
                        counts["tax_lines_count"],
                        "vollstaendig mit Lot und Ursprungsevent verknuepft",
                        "satisfied" if counts["tax_lines_count"] else "not_applicable",
                        "Tax-Lines enthalten Kostenbasis, Erloes, G/V und Haltedauer.",
                    ),
                    self._metric(
                        "orphan_tax_lines",
                        "Tax-Lines ohne Lot/Event",
                        counts["orphan_tax_lines_count"],
                        "0",
                        "satisfied" if counts["orphan_tax_lines_count"] == 0 else "blocked",
                        "Eine fehlende Verknuepfung verhindert die Einzelpruefung.",
                    ),
                    self._metric(
                        "fee_events",
                        "Events mit Gebuehrennachweis",
                        counts["fee_events_count"],
                        "alle gebuehrenpflichtigen Vorgange",
                        "review",
                        "Die Vollstaendigkeit der Gebuehren muss gegen die Originalquellen geprueft werden.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax/lines",
                    "/api/v1/tax/lots",
                    "/api/v1/export/audit.json",
                ],
                findings=(
                    []
                    if counts["orphan_tax_lines_count"] == 0
                    else [f"{counts['orphan_tax_lines_count']} Tax-Lines haben keine vollstaendige Lot-/Event-Kette."]
                ),
                next_action="Golden-Case- und Referenztests fuer alle Transaktionsklassen weiter ausbauen.",
            ),
            self._requirement(
                requirement_id="wallet_fifo",
                title="Walletbezogene Verbrauchsfolge und Methodenbindung",
                bmf_paragraphs=["61", "62", "103"],
                requirement=(
                    "Einzelbetrachtung bzw. gewaehlte FIFO-/Durchschnittsmethode muss je Wallet "
                    "und Handelsbezeichnung konsistent angewendet und dokumentiert werden."
                ),
                implementation_status=(
                    "implemented"
                    if wallet_fifo["status"] not in {"missing", "invalid"}
                    else "partial"
                ),
                evidence_status=(
                    "satisfied" if wallet_fifo_acceptance.strict_ready else "blocked"
                ),
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "active_tax_fifo",
                        "Aktive Steuer-FIFO",
                        active_fifo,
                        "wallet/depotbezogene produktive Methode",
                        "blocked" if "global_asset" in active_fifo else "satisfied",
                        (
                            "Die aktive Steuer-FIFO gruppiert weiterhin global nach Asset."
                            if "global_asset" in active_fifo
                            else "Die produktive Steuer-FIFO ist wallet-/depotbezogen aktiv."
                        ),
                    ),
                    self._metric(
                        "wallet_fifo_parallel_run",
                        "Versionierter Wallet-FIFO-Parallel-Run",
                        wallet_fifo["status"],
                        "strict_ready",
                        (
                            "satisfied"
                            if wallet_fifo_acceptance.strict_ready
                            else "blocked"
                        ),
                        "Der bisherige Wallet-FIFO-Pfad ist Preview/Evidence und ersetzt die globale FIFO nicht.",
                    ),
                    self._metric(
                        "wallet_fifo_unmatched_classification",
                        "Klassifikation offener Wallet-Abgaenge",
                        str(wallet_fifo["report_schema_version"]),
                        WalletFifoParallelRunService.RUN_REPORT_VERSION,
                        (
                            "satisfied"
                            if wallet_fifo["report_schema_version"]
                            == WalletFifoParallelRunService.RUN_REPORT_VERSION
                            else "blocked"
                        ),
                        (
                            "Trennt mengenbelegte Provider-Kostenbasisluecken von "
                            "tatsaechlich unerklaerten Wallet-Abgaengen."
                        ),
                    ),
                    self._metric(
                        "wallet_fifo_provider_basis_gaps",
                        "Mengenbelegte Provider-Kostenbasisluecken",
                        int(wallet_fifo["provider_basis_gap_count"]),
                        "0 oder fachlich belegte exakte Anschaffungskostenbasis",
                        (
                            "satisfied"
                            if int(wallet_fifo["provider_basis_gap_count"]) == 0
                            else "blocked"
                        ),
                        (
                            "Diese Abgaenge sind einem Provider-Settlement zugeordnet; "
                            "es fehlt nicht die Menge, sondern die exportierte Bot-Fill-Basis."
                        ),
                    ),
                    self._metric(
                        "wallet_fifo_unexplained_unmatched",
                        "Tatsaechlich unerklaerte Wallet-Abgaenge",
                        int(wallet_fifo["unexplained_unmatched_count"]),
                        "0",
                        (
                            "satisfied"
                            if int(wallet_fifo["unexplained_unmatched_count"]) == 0
                            else "blocked"
                        ),
                        (
                            "Zaehlt nur Abgaenge ohne passendes Lot und ohne vollstaendig "
                            "mengenreconcilierten Provider-Nachweis."
                        ),
                    ),
                    self._metric(
                        "wallet_fifo_method_delta_explanation",
                        "Erklaerte globale-/Wallet-FIFO-Differenz",
                        str(wallet_fifo["method_delta_explanation_status"]),
                        "ready_for_method_review",
                        (
                            "satisfied"
                            if wallet_fifo["method_delta_explanation_status"]
                            == "ready_for_method_review"
                            else "review"
                            if wallet_fifo["method_delta_explanation_status"] == "review"
                            else "blocked"
                        ),
                        (
                            "Ereignis-, Mengen-, Erlos- und Cost-Basis-Deltas werden bis auf "
                            "Veraeusserungs- und Anschaffungs-Event erklaert."
                        ),
                    ),
                    self._metric(
                        "wallet_fifo_method_acceptance",
                        "Versionierte Methodenabnahme und Aktivierung",
                        wallet_fifo_acceptance.decision_status,
                        "abgenommen und produktiv wallet-/depotbezogen aktiv",
                        (
                            "satisfied"
                            if wallet_fifo_acceptance.strict_ready
                            else "review"
                            if wallet_fifo_acceptance.decision_ready
                            else "blocked"
                        ),
                        (
                            "Die Abnahmeakte ist an Run-Input und Methodendifferenz gebunden. "
                            f"Entscheidungsreif: {wallet_fifo_acceptance.decision_ready}; "
                            f"Aktiviert: {wallet_fifo_acceptance.activation_applied}."
                        ),
                    ),
                    self._metric(
                        "wallet_fifo_migration_rehearsal",
                        "Read-only Migrationsprobe",
                        str(wallet_fifo_migration["status"]),
                        "ready_for_controlled_migration oder aktiv",
                        (
                            "satisfied"
                            if wallet_fifo_migration["status"]
                            in {"ready_for_controlled_migration", "already_active"}
                            else "review"
                            if wallet_fifo_migration["status"]
                            == "ready_for_method_decision"
                            else "blocked"
                        ),
                        (
                            "Die Probe materialisiert Lots und Tax-Lines nur in einer "
                            "temporaeren DuckDB und prueft Jahresparitaet sowie den "
                            "unveraenderten Produktiv-Fingerprint."
                        ),
                    ),
                    self._metric(
                        "bitget_strategy_basis_reconstruction",
                        "Bitget-Strategy Kostenbasis-Rekonstruktionsakte",
                        str(wallet_fifo["bitget_strategy_reconstruction_status"]),
                        "no_gap oder fachlich freigegebene exakte Kostenbasis",
                        (
                            "satisfied"
                            if wallet_fifo["bitget_strategy_reconstruction_status"]
                            == "no_gap"
                            else "review"
                            if wallet_fifo["bitget_strategy_reconstruction_status"]
                            == "ready_for_professional_review"
                            else "blocked"
                        ),
                        (
                            "Die Akte trennt beobachtete Mengen, Erwerbszeitfenster und "
                            "Verkaufserloese von Nullbasis- und Settlement-Sensitivitaeten; "
                            "sie besitzt keine produktive Steuerwirkung."
                        ),
                    ),
                    self._metric(
                        "bitget_strategy_basis_decision",
                        "Hashgebundene Bitget-Basismethodenentscheidung",
                        bitget_basis_decision.decision_status,
                        "exakte Provider-Basis oder dokumentierte Staging-Entscheidung",
                        (
                            "satisfied"
                            if wallet_fifo["status"] not in {"missing", "invalid"}
                            and int(wallet_fifo["provider_basis_gap_count"]) == 0
                            else "review"
                            if bitget_basis_decision.decision_ready
                            else "blocked"
                        ),
                        (
                            "Die Entscheidung ist an Run, Input-Fingerprint, Gap- und "
                            "Rekonstruktionshash gebunden. "
                            f"Entscheidungsreif: {bitget_basis_decision.decision_ready}; "
                            f"Methode: {bitget_basis_decision.selected_method}; "
                            "produktive Steuerwirkung: keine."
                        ),
                    ),
                    self._metric(
                        "bmf_combined_fifo_staging",
                        "Gemeinsame Preis-/Wallet-/Reward-Entscheidungsakte",
                        (
                            combined_fifo_staging.status
                            if combined_fifo_staging
                            else "missing"
                        ),
                        "ready_for_professional_review",
                        (
                            "satisfied"
                            if combined_fifo_staging_ready
                            else "blocked"
                        ),
                        (
                            f"Kombiniertes G/V-Delta {combined_fifo_staging.combined_delta_eur} EUR; "
                            f"Reward-Betriebsvermoegenszeilen {combined_fifo_staging.potential_business_inventory_tax_lines_count}; "
                            f"offene Reward-Urspruenge {combined_fifo_staging.unresolved_reward_origin_tax_lines_count}."
                            if combined_fifo_staging
                            else "Kein versionierter gemeinsamer Staging-Lauf vorhanden."
                        ),
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax/wallet-fifo-preview",
                    "/api/v1/tax-years/{year}/wallet-fifo-delta",
                    "/api/v1/tax/wallet-fifo-runs/latest",
                    "/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation",
                    "/api/v1/tax/wallet-fifo-runs/latest/method-acceptance",
                    "/api/v1/tax/wallet-fifo-migrations/rehearsals/latest",
                    "/api/v1/tax/wallet-fifo-migrations/apply-readiness",
                    "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction",
                    "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv",
                    "/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision",
                    "/api/v1/tax/wallet-fifo/bitget-strategy-review.html",
                    "/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip",
                    "/api/v1/tax/bmf-combined-fifo-staging/latest",
                    "src/steuerreport_v2/domain/tax.py",
                    "src/steuerreport_v2/domain/tax_wallet_fifo.py",
                ],
                findings=[
                    (
                        "Die Wallet-/Depot-FIFO ist produktiv und methodengebunden aktiv."
                        if wallet_fifo_acceptance.strict_ready
                        else "Die globale Steuer-FIFO und die walletbezogene Vorschau koennen materiell abweichen."
                    ),
                    (
                        "Der versionierte Run bleibt als Methoden- und Migrationsbeleg erhalten."
                        if wallet_fifo_acceptance.strict_ready
                        else "Ein Preview-Status ist keine produktive BMF-Verbrauchsfolge."
                    ),
                    (
                        "Der versionierte Methodendifferenz-Erklaerreport hat Status "
                        f"{wallet_fifo['method_delta_explanation_status']}."
                        if wallet_fifo["method_delta_explanation_status"] != "missing"
                        else "Ein versionierter Methodendifferenz-Erklaerreport fehlt noch."
                    ),
                    (
                        "Die Methodenabnahme ist entscheidungsreif, aber noch nicht "
                        "produktiv aktiviert."
                        if wallet_fifo_acceptance.decision_ready
                        and not wallet_fifo_acceptance.activation_applied
                        else "Die Methodenabnahme besitzt noch offene Bindungs- oder Datenchecks."
                        if not wallet_fifo_acceptance.decision_ready
                        else "Die Wallet-/Depot-FIFO ist produktiv aktiviert."
                    ),
                    (
                        "Die Migrationsprobe hat Status "
                        f"{wallet_fifo_migration['status']}."
                    ),
                ],
                next_action=(
                    "Bei neuen Importen einen Wallet-/Depot-FIFO-Rebuild und die Jahresbelege aktualisieren."
                    if wallet_fifo_acceptance.strict_ready
                    else "Die entscheidungsreife Methodenakte fachlich pruefen, die explizite "
                    "Methodenentscheidung dokumentieren und erst danach eine kontrollierte "
                    "produktive Migration mit Jahresparitaetspruefung ausfuehren."
                    if wallet_fifo_acceptance.decision_ready
                    else "Die in der Methodenabnahmeakte ausgewiesenen Daten- und "
                    "Belegblocker schliessen und danach einen neuen gebundenen Lauf erzeugen."
                ),
            ),
            self._requirement(
                requirement_id="transfer_provenance",
                title="Steuerneutrale Transfers und FIFO-Fortfuehrung",
                bmf_paragraphs=["62", "90", "103", "104"],
                requirement=(
                    "Umschichtungen zwischen eigenen Wallets und Depots muessen mit Herkunft, Ziel "
                    "und fortgefuehrten Anschaffungsdaten nachweisbar sein."
                ),
                implementation_status="partial",
                evidence_status="review" if counts["transfer_events_count"] else "not_applicable",
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "transfer_events",
                        "Transfer-Ereignisse",
                        counts["transfer_events_count"],
                        "vollstaendig klassifiziert",
                        "review" if counts["transfer_events_count"] else "not_applicable",
                        "Transfers benoetigen Ownership- und Gegenbuchungsbelege.",
                    ),
                    self._metric(
                        "txid_events",
                        "Events mit TXID",
                        counts["txid_events_count"],
                        "alle On-chain-Vorgaenge",
                        "review",
                        "CEX-interne Bewegungen koennen statt TXID einen Ledger-Beleg haben.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/transfers/candidates",
                    "/api/v1/tax-years/{year}/wallet-fifo-provenance-closure",
                ],
                findings=["Transfer-Entscheidungen sind vorhanden, aber noch nicht Teil einer produktiven Wallet-FIFO."],
                next_action="Transfer-Lot-Carry in den versionierten Wallet-FIFO-Run uebernehmen und belegen.",
            ),
            self._requirement(
                requirement_id="price_consistency",
                title="Einheitliche EUR-Kurs- und Bewertungsmethode",
                bmf_paragraphs=["43", "58", "59", "91", "103"],
                requirement=(
                    "Kursquelle und Bewertungszeitpunkt muessen dokumentiert und fuer Anschaffung "
                    "und Veraeusserung gleichmaessig angewendet werden."
                ),
                implementation_status="implemented",
                evidence_status=(
                    "blocked"
                    if (
                        counts["invalid_prices_count"]
                        or not swap_valuation.strict_ready
                        or not swap_fifo_parallel_ready
                        or not combined_fifo_staging_ready
                        or fifo_event_evidence_status == "blocked"
                    )
                    else "review"
                    if counts["low_confidence_prices_count"]
                    or fifo_event_evidence_status == "review"
                    else "satisfied"
                ),
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "price_points",
                        "Historische EUR-Preise",
                        counts["price_points_count"],
                        "> 0 fuer bewertete Vorgange",
                        "satisfied" if counts["price_points_count"] else "blocked",
                        "Preisledger behaelt Quelle, Zeitpunkt und Confidence.",
                    ),
                    self._metric(
                        "invalid_prices",
                        "Preise <= 0",
                        counts["invalid_prices_count"],
                        "0",
                        "satisfied" if counts["invalid_prices_count"] == 0 else "blocked",
                        "Nichtpositive Preise duerfen steuerlich nicht wirken.",
                    ),
                    self._metric(
                        "low_confidence_prices",
                        "Preise mit Confidence < 1",
                        counts["low_confidence_prices_count"],
                        "fachlich dokumentiert oder ersetzt",
                        "review" if counts["low_confidence_prices_count"] else "satisfied",
                        "Niedrige Confidence muss je steuerrelevanter Gruppe begruendet sein.",
                    ),
                    self._metric(
                        "crypto_swap_valuation_policy",
                        "Krypto-zu-Krypto-Bewertungsrangfolge",
                        swap_valuation.policy_mismatch_count,
                        "0 Abweichungen von Erhaltener-Token-zuerst",
                        "satisfied" if swap_valuation.strict_ready else "blocked",
                        (
                            f"{swap_valuation.material_delta_count} Materialdeltas; "
                            f"{swap_valuation.received_price_fallback_review_count} Fallback-Reviews; "
                            f"{swap_valuation.missing_both_prices_count} ohne beide Preise."
                        ),
                    ),
                    self._metric(
                        "crypto_swap_fifo_parallel",
                        "Preisrangfolgen-FIFO-Parallelvergleich",
                        swap_fifo_parallel.status if swap_fifo_parallel else "missing",
                        "matched und versioniert",
                        "satisfied" if swap_fifo_parallel_ready else "blocked",
                        (
                            f"G/V-Delta {swap_fifo_parallel.gain_loss_delta_eur} EUR; "
                            f"absolute Jahresdeltas {swap_fifo_parallel.absolute_year_gain_loss_delta_eur} EUR; "
                            f"Stand {swap_fifo_parallel.generated_at}."
                            if swap_fifo_parallel
                            else "Kein versioniertes Latest-Artefakt vorhanden."
                        ),
                    ),
                    self._metric(
                        "bmf_combined_fifo_staging",
                        "Preisregel in Wallet-/Depot-FIFO-Zielvorschau",
                        (
                            combined_fifo_staging.status
                            if combined_fifo_staging
                            else "missing"
                        ),
                        "ready_for_professional_review",
                        "satisfied" if combined_fifo_staging_ready else "blocked",
                        (
                            f"Preisdelta {combined_fifo_staging.price_policy_delta_eur} EUR; "
                            f"Wallet-Delta {combined_fifo_staging.wallet_scope_delta_eur} EUR; "
                            f"kombiniert {combined_fifo_staging.combined_delta_eur} EUR."
                            if combined_fifo_staging
                            else "Die kombinierte Folgewirkung wurde noch nicht versioniert berechnet."
                        ),
                    ),
                    self._metric(
                        "bmf_fifo_event_evidence",
                        "Ledgerweiter FIFO-Event- und Primaerbelegnachweis",
                        (
                            fifo_event_evidence.status
                            if fifo_event_evidence
                            else "missing"
                        ),
                        "full_ledger, ready_for_professional_review und an aktuelles Staging gebunden",
                        fifo_event_evidence_status,
                        (
                            f"{fifo_event_evidence.unique_events_count} Events; "
                            f"{fifo_event_evidence.raw_evidence_ready_count} Rohbelege; "
                            f"{fifo_event_evidence.tax_graph_events_count} FIFO-Graph-Events; "
                            f"{fifo_event_evidence.tax_graph_missing_events_count} fehlende Graph-Events; "
                            f"{fifo_event_evidence.derived_price_review_count} abgeleitete und "
                            f"{fifo_event_evidence.stale_price_review_count} veraltete Preise."
                            if fifo_event_evidence
                            else "Kein versionierter Eventbeleg-Report vorhanden."
                        ),
                    ),
                ],
                evidence_refs=[
                    "/api/v1/prices/quality",
                    "/api/v1/prices/coverage",
                    "/api/v1/export/price-quality.csv",
                    "/api/v1/tax/crypto-swap-valuation-review",
                    "/api/v1/tax/crypto-swap-fifo-parallel-preview/latest",
                    "/api/v1/tax/bmf-combined-fifo-staging/latest",
                    "/api/v1/tax/bmf-fifo-event-evidence/latest",
                    "/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz",
                    "docs/taxgraph/2026-08-19/TG-11_EUR_VALUATION_AND_PRICE_SOURCES.md",
                ],
                findings=(
                    (
                        [f"{counts['low_confidence_prices_count']} Preiszeilen haben Confidence unter 1."]
                        if counts["low_confidence_prices_count"]
                        else []
                    )
                    + swap_valuation.findings
                    + (
                        [
                            f"FIFO-Parallelvergleich: {swap_fifo_parallel.gain_loss_delta_eur} EUR saldiertes G/V-Delta und "
                            f"{swap_fifo_parallel.absolute_year_gain_loss_delta_eur} EUR absolute Jahresdeltas."
                        ]
                        if swap_fifo_parallel
                        else ["Kein versionierter Preisrangfolgen-FIFO-Parallelvergleich vorhanden."]
                    )
                ),
                next_action=(
                    swap_valuation.next_actions[0]
                    if swap_valuation.next_actions
                    else "Preisquellenregel je Asset/Tag pruefen und Abweichungen versioniert dokumentieren."
                ),
            ),
            self._requirement(
                requirement_id="income_rewards",
                title="Mining, Forging, Staking, Lending und Airdrops",
                bmf_paragraphs=["33-48a", "64-65", "70-75", "103"],
                requirement=(
                    "Einnahmeart, Leistungsbezug, Claim-/Zuflusszeitpunkt, Menge und EUR-Wert "
                    "muessen getrennt von der spaeteren Verwertung dokumentiert werden."
                ),
                implementation_status="implemented",
                evidence_status="review" if counts["income_events_count"] else "not_applicable",
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "income_events",
                        "Income-/Reward-/Mining-/Staking-Events",
                        counts["income_events_count"],
                        "vollstaendig klassifiziert und bewertet",
                        "review" if counts["income_events_count"] else "not_applicable",
                        "Technische Labels ersetzen nicht die Einzelfallpruefung der Einkunftsart.",
                    )
                ],
                evidence_refs=[
                    "/api/v1/tax-years/{year}/income-guide",
                    "/api/v1/tax-years/reward-trading-separation",
                ],
                findings=[
                    "HNT/IOT/MOBILE Rewards und spaetere Verwertungen werden technisch getrennt ausgewiesen."
                ],
                next_action="Reward-/Mining-Klassifikation je Quelltyp mit Primaerbelegen und Claim-Zeitpunkt abnehmen.",
            ),
            self._requirement(
                requirement_id="business_private_tax_sphere",
                title="Betriebliche Reward-Bestaende und private Veraeusserungen",
                bmf_paragraphs=["33-48a", "53-63", "103"],
                requirement=(
                    "Aus einer gewerblichen Taetigkeit entstandene Kryptowerte duerfen ohne "
                    "dokumentierte Entnahme nicht automatisch als private Wirtschaftsgueter mit "
                    "privater Haltefrist behandelt werden."
                ),
                implementation_status="implemented",
                evidence_status=(
                    "not_applicable"
                    if business_inventory.total_tax_lines_count == 0
                    and combined_fifo_staging is None
                    else "satisfied"
                    if business_inventory.strict_ready
                    and combined_fifo_staging_ready
                    else "blocked"
                ),
                affected_years=business_inventory.affected_years,
                metrics=[
                    self._metric(
                        "potential_business_tax_lines",
                        "Tax-Lines aus potenziellem Reward-Betriebsvermoegen",
                        business_inventory.potential_business_tax_lines_count,
                        "0 oder durch Entnahme-/Sphaerenbeleg geklaert",
                        (
                            "satisfied"
                            if business_inventory.potential_business_tax_lines_count == 0
                            else "blocked"
                        ),
                        "Direkter Ursprung ist Mining oder ein On-Chain-Reward von HNT/IOT/MOBILE.",
                    ),
                    self._metric(
                        "unresolved_reward_origin_tax_lines",
                        "Tax-Lines mit offenem Reward-Ursprung",
                        business_inventory.unresolved_tax_lines_count,
                        "0",
                        (
                            "satisfied"
                            if business_inventory.unresolved_tax_lines_count == 0
                            else "blocked"
                        ),
                        "Income, Transfer, CEX-Staking oder fehlende Urspruenge benoetigen einen Primaerbeleg.",
                    ),
                    self._metric(
                        "combined_target_reward_sphere",
                        "Reward-Sphaere in kombinierter Zielvorschau",
                        (
                            (
                                combined_fifo_staging.potential_business_inventory_tax_lines_count
                                + combined_fifo_staging.unresolved_reward_origin_tax_lines_count
                            )
                            if combined_fifo_staging
                            else "missing"
                        ),
                        "0 und versioniert",
                        "satisfied" if combined_fifo_staging_ready else "blocked",
                        (
                            "Die Zielvorschau klassifiziert Anschaffungslots nach Reward-Ursprung, "
                            "ohne sie automatisch der privaten Sphaere zuzuordnen."
                        ),
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax-years/business-reward-inventory-review",
                    "/api/v1/tax/bmf-combined-fifo-staging/latest",
                    "docs/taxgraph/2026-08-19/TG-04_HELIUM_REWARDS_INCOME_CLASSIFICATION.md",
                    "docs/taxgraph/2026-08-19/TG-05_BUSINESS_REWARD_TO_LATER_TRADE.md",
                    "docs/taxgraph/2026-08-19/TG-16_HELIUM_EUER_AND_REWARD_INVENTORY.md",
                ],
                findings=business_inventory.findings,
                next_action=(
                    business_inventory.next_actions[0]
                    if business_inventory.next_actions
                    else "Ursprungslot-Audit nach jedem Tax-Rebuild erneut ausfuehren."
                ),
            ),
            self._requirement(
                requirement_id="manual_corrections",
                title="Kenntliche und begruendete Korrekturen",
                bmf_paragraphs=["29b", "90"],
                requirement=(
                    "Manuelle Anpassungen muessen sichtbar, begruendet und mit der betroffenen "
                    "Datenbasis bzw. einem Beleg verknuepft sein."
                ),
                implementation_status="implemented",
                evidence_status=(
                    "satisfied" if counts["review_decisions_missing_evidence_count"] == 0 else "review"
                ),
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "review_decisions",
                        "Dokumentierte Entscheidungen",
                        counts["review_decisions_count"],
                        "jede fachliche Korrektur",
                        "satisfied" if counts["review_decisions_count"] else "review",
                        "Review-Entscheidungen bleiben als Auditdaten erhalten.",
                    ),
                    self._metric(
                        "decisions_without_evidence",
                        "Entscheidungen ohne Belegreferenz",
                        counts["review_decisions_missing_evidence_count"],
                        "0",
                        "satisfied" if counts["review_decisions_missing_evidence_count"] == 0 else "review",
                        "Eine Begruendung ohne Belegreferenz ist bei einer Pruefung schwaecher.",
                    ),
                ],
                evidence_refs=["/api/v1/review/decisions", "/api/v1/export/review-decisions.csv"],
                findings=(
                    [f"{counts['review_decisions_missing_evidence_count']} Entscheidungen haben keine Belegreferenz."]
                    if counts["review_decisions_missing_evidence_count"]
                    else []
                ),
                next_action="Fehlende Belegreferenzen ergaenzen, ohne Entscheidungen automatisch umzudeuten.",
            ),
            self._requirement(
                requirement_id="as_of_holdings_and_source_of_funds",
                title="Stichtagsbestaende, Wallet-Adressen und Mittelherkunft",
                bmf_paragraphs=["104"],
                requirement=(
                    "Wallet-/Account-Bestaende muessen zu verlangten Stichtagen zusammen mit "
                    "Adressen, TXIDs, Plattformkonten und Mittelherkunft pruefbar sein."
                ),
                implementation_status=(
                    "implemented"
                    if stichtag_gate["status"] not in {"missing", "invalid"}
                    else "partial"
                ),
                evidence_status="satisfied" if stichtag_gate["strict_ready"] else "blocked",
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "as_of_endpoint",
                        "Stichtags-Portfolio",
                        "implemented",
                        "belegter Tagesbestand mit hartem Preis-/Quellen-Gate",
                        "review",
                        "Mengen werden aus dem Balance-Ledger rekonstruiert.",
                    ),
                    self._metric(
                        "valuation_gate",
                        "Versioniertes Stichtags-Gate",
                        stichtag_gate["status"],
                        "strict_ready",
                        "satisfied" if stichtag_gate["strict_ready"] else "blocked",
                        "Veraltete Kurse und unvollstaendige Quellen duerfen nicht still im Gesamtwert wirken.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/portfolio/as-of",
                    "/api/v1/divorce/equalization-summary",
                    "/api/v1/divorce/valuation-runs/latest",
                ],
                findings=(
                    ["Das versionierte Stichtagsdossier ist vorhanden und strict_ready."]
                    if stichtag_gate["strict_ready"]
                    else [
                        f"Das versionierte Stichtagsdossier ist vorhanden, aber Status ist {stichtag_gate['status']}.",
                        "Offene Same-Day-Preise, Tokenrisiken oder referenzierte FIFO-Gates bleiben blockierend sichtbar.",
                    ]
                ),
                next_action="Preis-, Quellen- und FIFO-Findings des letzten Stichtagslaufs schliessen.",
            ),
            self._requirement(
                requirement_id="evidence_and_data_access",
                title="Belegpakete und maschinenlesbare Pruefdaten",
                bmf_paragraphs=["90", "101", "102", "103", "104"],
                requirement=(
                    "Steuerreport, Transaktionslisten, Originaldateien, Methoden und Einzelbelege "
                    "muessen menschen- und maschinenlesbar bereitgestellt werden koennen."
                ),
                implementation_status="implemented",
                evidence_status="satisfied" if evidence_access_ready else "blocked",
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "raw_batches",
                        "Import-Batches",
                        counts["raw_batches_count"],
                        "alle verwendeten Originalimporte",
                        "satisfied" if counts["raw_batches_count"] else "review",
                        "Batch, Hash und Rohobjekte bilden die Importspur.",
                    ),
                    self._metric(
                        "annual_evidence_package",
                        "Jahresbelegpaket",
                        "implemented",
                        "ZIP mit Hash-Manifest und Governance-Snapshots",
                        "satisfied",
                        "Der fingerprintgebundene Export enthaelt menschen- und maschinenlesbare Nachweise.",
                    ),
                    self._metric(
                        "governance_snapshots",
                        "Versionierte Governance-Artefakte",
                        f"{len(available_governance_artifacts)}/{len(governance_artifacts)}",
                        f"{len(governance_artifacts)}/{len(governance_artifacts)}",
                        "satisfied" if len(available_governance_artifacts) == len(governance_artifacts) else "blocked",
                        "Inhaltliche Blocker der Artefakte bleiben in ihren eigenen Matrixanforderungen sichtbar.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/export/tax-years/{year}/evidence-package.zip",
                    "/api/v1/tax-years/{year}/filing-summary.html",
                    "/api/v1/tax-methodology/bmf-compliance-matrix",
                    "/api/v1/tax-methodology/time-precision-audit",
                ],
                findings=(
                    [
                        "Jahres-ZIP, Hash-Manifest, Matrix, Zeit-Audit, Wallet-FIFO, "
                        "Quellenregistry und Stichtagsgate sind gemeinsam abrufbar."
                    ]
                    if evidence_access_ready
                    else [
                        "Mindestens ein Originalimport oder versioniertes Governance-Artefakt fehlt."
                    ]
                ),
                next_action=(
                    "Paket nach Daten- oder Methodenveraenderungen neu erzeugen und Hash-Manifest archivieren."
                    if evidence_access_ready
                    else "Fehlende Originalimporte oder Governance-Artefakte erzeugen."
                ),
            ),
            self._requirement(
                requirement_id="time_and_precision",
                title="Zeitpunkt-, Zeitzonen- und Rundungskonsistenz",
                bmf_paragraphs=["43", "55", "58", "91", "102"],
                requirement=(
                    "Transaktions- und Bewertungszeitpunkte sowie Rundungsregeln muessen "
                    "einheitlich, reproduzierbar und im Report dokumentiert sein."
                ),
                implementation_status=(
                    "implemented" if time_precision.reporting_policy_applied else "partial"
                ),
                evidence_status=time_precision.status,
                affected_years=scope_years,
                metrics=[
                    self._metric(
                        "timezone_policy",
                        "Gespeicherte Zeitzone",
                        (
                            f"UTC -> Europe/Berlin; "
                            f"{time_precision.reporting_year_shift_events_count} Jahresverschiebungen"
                        ),
                        "UTC plus dokumentierte steuerliche Lokalzeitdarstellung",
                        "satisfied" if time_precision.reporting_policy_applied else "blocked",
                        (
                            "IANA-Europe/Berlin-Audit trennt echte CET/CEST-Kalendergrenzen "
                            "von belegten Quellperioden-Aggregaten."
                        ),
                    ),
                    self._metric(
                        "decimal_policy",
                        "Rechengenauigkeit",
                        "Decimal backend / 2 Stellen UI",
                        "keine Zwischenrundung",
                        "satisfied",
                        "Backend behaelt Decimal-Genauigkeit; UI rundet nur zur Anzeige.",
                    ),
                ],
                evidence_refs=[
                    "/api/v1/tax-methodology/summary",
                    "/api/v1/tax-methodology/time-precision-audit",
                    "docs/001_REGELN_UND_ANPASSUNG_STEUERLOGIK_2026-07-05.md",
                ],
                findings=(
                    [
                        f"{time_precision.reporting_year_shift_events_count} echte Ereignisse "
                        "sind noch dem deutschen Kalenderjahr zuzuordnen.",
                        f"{time_precision.source_period_aggregate_events_count} Helium-"
                        "Periodenaggregate behalten ihr belegtes Quelljahr.",
                    ]
                    if time_precision.status == "blocked"
                    else [
                        "UTC-, CET-, CEST- und Quellperiodengrenzen sind versioniert geprueft.",
                        f"{time_precision.reporting_year_shift_events_count} echte Ereignisse "
                        "werden reproduzierbar dem deutschen Kalenderjahr zugeordnet.",
                    ]
                ),
                next_action=(
                    "Bei neuen Importquellen Zeitsemantik erfassen und den Grenzfall-Audit "
                    "im Jahresbelegpaket weiterfuehren."
                ),
            ),
        ]

        strict_ready = bool(requirements) and all(item.strict_ready for item in requirements)
        return TaxBmfComplianceMatrix(
            generated_at=datetime.now(timezone.utc).isoformat(),
            matrix_version=self.MATRIX_VERSION,
            bmf_reference=self.BMF_REFERENCE,
            bmf_reference_url=self.BMF_REFERENCE_URL,
            scope_years=scope_years,
            strict_bmf_ready=strict_ready,
            strict_ready_years=filing["ready_years"] if strict_ready else [],
            conservative_years=filing["conservative_years"],
            review_years=filing["review_years"],
            blocked_years=filing["blocked_years"],
            requirements_count=len(requirements),
            satisfied_count=sum(item.evidence_status == "satisfied" for item in requirements),
            review_count=sum(item.evidence_status == "review" for item in requirements),
            blocked_count=sum(item.evidence_status == "blocked" for item in requirements),
            not_applicable_count=sum(item.evidence_status == "not_applicable" for item in requirements),
            requirements=requirements,
            caveats=[
                "Die Matrix ist eine technische Nachweis- und Vollstaendigkeitspruefung, keine Steuer- oder Rechtsberatung.",
                "Ein freies Export-Gate ersetzt weder die strenge BMF-Matrix noch die fachliche Einzelfallpruefung.",
                "Ohne frischen offiziellen Rechtsquellenlauf wird keine aktuelle BMF-Reife behauptet.",
                "NFT und Liquidity Mining sind im BMF-Schreiben vom 6. Maerz 2025 noch nicht abschliessend behandelt.",
            ],
            methodology=(
                "Read-only Compliance-Matrix aus versioniertem BMF-Filing-Snapshot, Datenbankzaehlern "
                "und Freigabeartefakten fuer Rechtsstand, Wallet-FIFO, Quellenregistry und Stichtagsbewertung. "
                "Sie veraendert keine Imports, Preise, Ledger, Tax-Lots, Tax-Lines oder Review-Entscheidungen."
            ),
        )

    def _counts(self) -> dict[str, int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    (select count(*) from raw_import_batches),
                    (select count(*) from raw_objects),
                    (select count(*) from canonical_events),
                    (select count(distinct source) from canonical_events),
                    (select count(*) from canonical_events where tx_id is not null and trim(tx_id) <> ''),
                    (select count(*) from canonical_events where fee_quantity is not null and fee_quantity <> 0),
                    (select count(*) from canonical_events where event_type = 'transfer'),
                    (select count(*) from canonical_events where event_type in ('income', 'reward', 'mining', 'staking')),
                    (select count(*) from price_ledger),
                    (select count(*) from price_ledger where price_eur <= 0),
                    (select count(*) from price_ledger where confidence < 1),
                    (select count(*) from tax_lines),
                    (
                        select count(*)
                        from tax_lines line
                        left join tax_lots lot on lot.lot_id = line.lot_id
                        left join canonical_events event on event.event_id = line.source_event_id
                        where lot.lot_id is null or event.event_id is null
                    )
                """
            ).fetchone()
        decisions = self.store.list_review_decisions()
        keys = [
            "raw_batches_count",
            "raw_objects_count",
            "canonical_events_count",
            "sources_count",
            "txid_events_count",
            "fee_events_count",
            "transfer_events_count",
            "income_events_count",
            "price_points_count",
            "invalid_prices_count",
            "low_confidence_prices_count",
            "tax_lines_count",
            "orphan_tax_lines_count",
        ]
        result = {key: int(value or 0) for key, value in zip(keys, row, strict=True)}
        result["review_decisions_count"] = len(decisions)
        result["review_decisions_missing_evidence_count"] = sum(
            1 for decision in decisions if not str(decision.evidence_ref or "").strip()
        )
        return result

    def _available_years(self) -> list[int]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select distinct cast(extract(year from event_time) as integer) as year
                from canonical_events
                order by year
                """
            ).fetchall()
        return [int(row[0]) for row in rows if row[0] is not None]

    def _filing_snapshot(self, scope_years: list[int]) -> dict[str, object]:
        result: dict[str, object] = {
            "snapshot_status": "not_available",
            "ready_years": [],
            "conservative_years": [],
            "review_years": [],
            "blocked_years": list(scope_years),
        }
        if not self._is_default_store():
            return result
        snapshot = TaxMethodologyService(self.store).bmf_filing_readiness_snapshot()
        result["snapshot_status"] = (
            snapshot.binding_status
            if snapshot.status == "available"
            else snapshot.status
        )
        if (
            snapshot.status != "available"
            or snapshot.binding_status != "current"
            or snapshot.report is None
        ):
            return result
        report = snapshot.report
        covered = set(report.available_years)
        result.update(
            {
                "ready_years": list(report.ready_years),
                "conservative_years": list(report.conservative_appendix_years),
                "review_years": list(report.review_years),
                "blocked_years": sorted(set(report.blocked_years) | (set(scope_years) - covered)),
            }
        )
        return result

    def _is_default_store(self) -> bool:
        try:
            return self.store.path.resolve() == self.DEFAULT_DB.resolve()
        except FileNotFoundError:
            return False

    @staticmethod
    def _filing_status(filing: dict[str, object]) -> TaxBmfComplianceStatus:
        if filing["snapshot_status"] != "available" or filing["blocked_years"]:
            return "blocked"
        if filing["review_years"] or filing["conservative_years"]:
            return "review"
        return "satisfied"

    @staticmethod
    def _filing_findings(filing: dict[str, object]) -> list[str]:
        findings: list[str] = []
        if filing["snapshot_status"] != "available":
            findings.append("Kein gueltiger BMF-Filing-Snapshot fuer diese Datenbank vorhanden.")
        if filing["conservative_years"]:
            findings.append(
                "Konservativ belegbar, aber nicht streng BMF-ready: "
                + ", ".join(str(year) for year in filing["conservative_years"])
            )
        if filing["review_years"]:
            findings.append("Review erforderlich: " + ", ".join(str(year) for year in filing["review_years"]))
        if filing["blocked_years"]:
            findings.append("Blockiert oder nicht im Snapshot: " + ", ".join(str(year) for year in filing["blocked_years"]))
        return findings

    @staticmethod
    def _artifact_state(path: Path) -> dict[str, object]:
        if not path.exists():
            return {
                "status": "missing",
                "strict_ready": False,
                "method_delta_explanation_status": "missing",
                "bitget_strategy_reconstruction_status": "missing",
                "report_schema_version": "missing",
                "provider_basis_gap_count": 0,
                "unexplained_unmatched_count": 0,
                "provider_coverage_gap_entries_count": 0,
                "user_evidence_gap_entries_count": 0,
                "documented_route_entries_count": 0,
                "path": str(path),
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "invalid",
                "strict_ready": False,
                "method_delta_explanation_status": "missing",
                "bitget_strategy_reconstruction_status": "missing",
                "report_schema_version": "invalid",
                "provider_basis_gap_count": 0,
                "unexplained_unmatched_count": 0,
                "provider_coverage_gap_entries_count": 0,
                "user_evidence_gap_entries_count": 0,
                "documented_route_entries_count": 0,
                "path": str(path),
            }
        strict_ready = bool(payload.get("strict_ready") or payload.get("strict_bmf_ready"))
        return {
            "status": str(payload.get("status") or ("strict_ready" if strict_ready else "available")),
            "strict_ready": strict_ready,
            "method_delta_explanation_status": str(
                payload.get("method_delta_explanation_status") or "missing"
            ),
            "bitget_strategy_reconstruction_status": str(
                payload.get("bitget_strategy_reconstruction_status") or "missing"
            ),
            "report_schema_version": str(
                payload.get("report_schema_version") or "wallet_fifo_run_v1"
            ),
            "provider_basis_gap_count": int(
                payload.get("provider_basis_gap_count") or 0
            ),
            "unexplained_unmatched_count": int(
                payload.get("unexplained_unmatched_count")
                if payload.get("unexplained_unmatched_count") is not None
                else payload.get("unmatched_count") or 0
            ),
            "provider_coverage_gap_entries_count": int(
                payload.get("provider_coverage_gap_entries_count") or 0
            ),
            "user_evidence_gap_entries_count": int(
                payload.get("user_evidence_gap_entries_count") or 0
            ),
            "documented_route_entries_count": int(
                payload.get("documented_route_entries_count") or 0
            ),
            "path": str(path),
        }

    @staticmethod
    def _metric(
        key: str,
        label: str,
        value: Decimal | int | str | bool,
        target: str,
        status: TaxBmfComplianceStatus,
        detail: str,
    ) -> TaxBmfComplianceMetric:
        return TaxBmfComplianceMetric(
            key=key,
            label=label,
            value=value,
            target=target,
            status=status,
            detail=detail,
        )

    @staticmethod
    def _requirement(
        *,
        requirement_id: str,
        title: str,
        bmf_paragraphs: list[str],
        requirement: str,
        implementation_status: TaxBmfImplementationStatus,
        evidence_status: TaxBmfComplianceStatus,
        affected_years: list[int],
        metrics: list[TaxBmfComplianceMetric],
        evidence_refs: list[str],
        findings: list[str],
        next_action: str,
    ) -> TaxBmfComplianceRequirement:
        return TaxBmfComplianceRequirement(
            requirement_id=requirement_id,
            title=title,
            bmf_paragraphs=bmf_paragraphs,
            requirement=requirement,
            implementation_status=implementation_status,
            evidence_status=evidence_status,
            strict_ready=implementation_status == "implemented" and evidence_status == "satisfied",
            affected_years=sorted(set(affected_years)),
            metrics=metrics,
            evidence_refs=evidence_refs,
            findings=findings,
            next_action=next_action,
        )
