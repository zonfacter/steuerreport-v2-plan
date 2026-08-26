from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

from pydantic import BaseModel

from steuerreport_v2.contracts.wallet_fifo_migrations import (
    WalletFifoMigrationApplyCheck,
    WalletFifoMigrationApplyReadinessReport,
    WalletFifoMigrationApplyReport,
    WalletFifoMigrationApplyRequest,
    WalletFifoMigrationCheck,
    WalletFifoMigrationRehearsalReport,
    WalletFifoMigrationRehearsalRequest,
    WalletFifoMigrationYearCheck,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.fifo_methods import (
    GLOBAL_ASSET_FIFO_SCOPE,
    WALLET_DEPOT_FIFO_SCOPE,
    active_fifo_scope,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)
from steuerreport_v2.domain.wallet_fifo_persistence import wallet_fifo_tax_rows
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


class WalletFifoMigrationRehearsalService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/wallet_fifo_migrations"
    APPROVAL = "approved_for_controlled_migration"
    PARITY_TOLERANCE_EUR = Decimal("0.01")
    ARITHMETIC_TOLERANCE_EUR = Decimal("0.000000000001")

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.run_service = WalletFifoParallelRunService(store)
        self.acceptance_service = WalletFifoMethodAcceptanceService(store)
        self.artifact_root = artifact_root or self._default_artifact_root()

    def rehearse(
        self,
        request: WalletFifoMigrationRehearsalRequest | None = None,
    ) -> WalletFifoMigrationRehearsalReport:
        payload = request or WalletFifoMigrationRehearsalRequest()
        run = self.run_service.get(payload.run_id) if payload.run_id else self.run_service.latest()
        if run is None:
            raise ValueError("Ein versionierter Wallet-FIFO-Lauf fehlt.")

        generated_at = datetime.now(timezone.utc)
        acceptance = self.acceptance_service.readiness(run_id=run.run_id)
        provider_classification_current = (
            run.report_schema_version == self.run_service.RUN_REPORT_VERSION
        )
        provider_basis_gap_count = (
            run.provider_basis_gap_count if provider_classification_current else 0
        )
        unexplained_unmatched_count = (
            run.unexplained_unmatched_count
            if provider_classification_current
            else run.unmatched_count
        )
        fingerprint_before = self.run_service.input_fingerprint(run.as_of)
        state = WalletFifoPreviewService(self.store).replay(as_of=run.as_of)
        lots, lines = wallet_fifo_tax_rows(state)

        lot_ids = [item.lot_id for item in lots]
        lot_id_set = set(lot_ids)
        line_ids = [item.tax_line_id for item in lines]
        orphan_source_lines = sum(item.lot_id not in lot_id_set for item in lines)
        duplicate_lot_ids = len(lot_ids) - len(lot_id_set)
        duplicate_line_ids = len(line_ids) - len(set(line_ids))
        source_negative_lots = sum(
            item.quantity_total < 0
            or item.quantity_remaining < 0
            or item.quantity_remaining > item.quantity_total
            for item in lots
        )

        with TemporaryDirectory(prefix="wallet-fifo-rehearsal-") as temporary_dir:
            staging_store = DuckDbStore(Path(temporary_dir) / "staging.duckdb")
            TaxService(staging_store)._replace_tax_tables(
                lots,
                lines,
                [],
                fifo_method=WALLET_DEPOT_FIFO_SCOPE,
                input_fingerprint_digest=run.input_fingerprint.digest,
            )
            staged_lots = TaxService(staging_store).list_tax_lots()
            staged_lines = TaxService(staging_store).list_tax_lines()
            staged_summary = TaxService(staging_store).latest_summary()
            with staging_store.connect() as con:
                staging_orphans = int(
                    con.execute(
                        """
                        select count(*)
                        from tax_lines line
                        left join tax_lots lot on lot.lot_id = line.lot_id
                        where lot.lot_id is null
                        """
                    ).fetchone()[0]
                )

        staging_negative_lots = sum(
            item.quantity_total < 0
            or item.quantity_remaining < 0
            or item.quantity_remaining > item.quantity_total
            for item in staged_lots
        )
        staging_arithmetic_delta = sum(
            (
                item.gain_loss_eur
                - (item.disposal_proceeds_eur - item.acquisition_cost_eur)
                for item in staged_lines
            ),
            Decimal("0"),
        )
        source_years = {item.year: item for item in run.year_results}
        staging_year_totals: dict[int, tuple[Decimal, int]] = defaultdict(
            lambda: (Decimal("0"), 0)
        )
        for line in staged_lines:
            year = reporting_tax_year(line.disposed_at)
            value, count = staging_year_totals[year]
            staging_year_totals[year] = (value + line.gain_loss_eur, count + 1)
        year_checks = []
        for year in run.years:
            source = source_years[year]
            staging_gain, staging_count = staging_year_totals[year]
            delta = staging_gain - source.wallet_gain_loss_eur
            year_checks.append(
                WalletFifoMigrationYearCheck(
                    year=year,
                    source_wallet_gain_loss_eur=source.wallet_gain_loss_eur,
                    staging_gain_loss_eur=staging_gain,
                    delta_eur=delta,
                    source_wallet_tax_lines_count=source.wallet_tax_lines_count,
                    staging_tax_lines_count=staging_count,
                    parity=(
                        abs(delta) <= self.PARITY_TOLERANCE_EUR
                        and staging_count == source.wallet_tax_lines_count
                    ),
                )
            )

        fingerprint_after = self.run_service.input_fingerprint(run.as_of)
        production_unchanged = fingerprint_after.digest == fingerprint_before.digest
        approved_decision_bound = bool(
            acceptance.decision_status == self.APPROVAL
            and acceptance.decision_id
            and acceptance.input_fingerprint_current
        )
        checks = [
            self._check(
                "run_input_current",
                "Run entspricht dem aktuellen Datenstand",
                "technical",
                acceptance.input_fingerprint_current,
                "Run- und aktueller semantischer Input-Fingerprint stimmen ueberein.",
            ),
            self._check(
                "acceptance_data_ready",
                "Methodenakte besteht alle Datenchecks",
                "technical",
                acceptance.decision_ready,
                f"Entscheidungsreif: {acceptance.decision_ready}.",
            ),
            self._check(
                "no_unexplained_wallet_fifo_unmatched",
                "Keine wirklich ungeklaerten Wallet-FIFO-Abgaenge",
                "technical",
                unexplained_unmatched_count == 0,
                (
                    f"Wirklich ungeklaerte Abgaenge: {unexplained_unmatched_count}; "
                    f"belegte Provider-Basisluecken: {provider_basis_gap_count}."
                ),
            ),
            self._check(
                "provider_basis_complete",
                "Provider-Settlement-Kostenbasis ist vollstaendig",
                "technical",
                provider_basis_gap_count == 0,
                (
                    f"Belegte Provider-Basisluecken: {provider_basis_gap_count}. "
                    "Ohne originale Bot-Fills oder eine ausdruecklich freigegebene "
                    "fachliche Behandlung werden diese Mengen nicht produktiv migriert."
                ),
            ),
            self._check(
                "unique_lot_ids",
                "Lot-IDs sind eindeutig",
                "technical",
                duplicate_lot_ids == 0,
                f"Doppelte Lot-IDs: {duplicate_lot_ids}.",
            ),
            self._check(
                "unique_tax_line_ids",
                "Tax-Line-IDs sind eindeutig",
                "technical",
                duplicate_line_ids == 0,
                f"Doppelte Tax-Line-IDs: {duplicate_line_ids}.",
            ),
            self._check(
                "source_lot_references_complete",
                "Jede Tax-Line referenziert ein Replay-Lot",
                "technical",
                orphan_source_lines == 0,
                f"Fehlende Replay-Lot-Referenzen: {orphan_source_lines}.",
            ),
            self._check(
                "source_lot_quantities_valid",
                "Replay-Lot-Mengen sind gueltig",
                "technical",
                source_negative_lots == 0,
                f"Ungueltige Replay-Lots: {source_negative_lots}.",
            ),
            self._check(
                "staging_counts_match",
                "Staging uebernimmt alle Lots und Tax-Lines",
                "technical",
                len(staged_lots) == len(lots) and len(staged_lines) == len(lines),
                (
                    f"Quelle/Staging Lots: {len(lots)}/{len(staged_lots)}; "
                    f"Tax-Lines: {len(lines)}/{len(staged_lines)}."
                ),
            ),
            self._check(
                "staging_references_complete",
                "Staging besitzt keine verwaiste Tax-Line",
                "technical",
                staging_orphans == 0,
                f"Verwaiste Staging-Tax-Lines: {staging_orphans}.",
            ),
            self._check(
                "staging_lot_quantities_valid",
                "Staging-Lot-Mengen sind gueltig",
                "technical",
                staging_negative_lots == 0,
                f"Ungueltige Staging-Lots: {staging_negative_lots}.",
            ),
            self._check(
                "staging_line_arithmetic",
                "Staging-Gewinnformel bleibt exakt",
                "technical",
                abs(staging_arithmetic_delta) <= self.ARITHMETIC_TOLERANCE_EUR,
                f"Summiertes Rundungsdelta: {staging_arithmetic_delta} EUR.",
            ),
            self._check(
                "staging_year_parity",
                "Staging stimmt je Steuerjahr mit dem Wallet-Run ueberein",
                "technical",
                all(item.parity for item in year_checks),
                "Jahreswert und Tax-Line-Anzahl muessen fuer jedes Run-Jahr uebereinstimmen.",
            ),
            self._check(
                "staging_method_metadata",
                "Staging-Zeilen tragen die Zielmethode",
                "technical",
                bool(staged_summary)
                and staged_summary.fifo_method == WALLET_DEPOT_FIFO_SCOPE
                and staged_summary.input_fingerprint_digest
                == run.input_fingerprint.digest
                and all(item.fifo_method == WALLET_DEPOT_FIFO_SCOPE for item in staged_lots)
                and all(item.fifo_method == WALLET_DEPOT_FIFO_SCOPE for item in staged_lines),
                "Lots, Tax-Lines und Run-Summary muessen Methode und Input-Fingerprint tragen.",
            ),
            self._check(
                "production_tax_unchanged",
                "Produktive Steuerdaten blieben unveraendert",
                "technical",
                production_unchanged,
                "Der semantische Produktiv-Fingerprint ist vor und nach der Probe identisch.",
            ),
            self._check(
                "approved_decision_bound",
                "Explizite Methodenfreigabe ist an diesen Run gebunden",
                "governance",
                approved_decision_bound,
                (
                    "Freigabe ist gebunden."
                    if approved_decision_bound
                    else f"Gespeicherte Entscheidung: {acceptance.decision_status}."
                ),
            ),
        ]
        technical_ready = all(
            item.passed for item in checks if item.gate == "technical" and item.blocking
        )
        migration_ready = technical_ready and approved_decision_bound
        status = (
            "already_active"
            if acceptance.activation_applied
            else "blocked"
            if not technical_ready
            else "ready_for_controlled_migration"
            if migration_ready
            else "ready_for_method_decision"
        )
        rehearsal_id = (
            f"wallet-fifo-migration-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{run.input_fingerprint.digest[:12]}-{uuid4().hex[:8]}"
        )
        artifact_path = self.artifact_root / rehearsal_id / "wallet_fifo_migration_rehearsal.json"
        latest_path = self.artifact_root / "latest_wallet_fifo_migration_rehearsal.json"
        blockers = [item.detail for item in checks if item.blocking and not item.passed]
        findings = [
            (
                "Die Wallet-/Depot-FIFO kann technisch verlustfrei in das erweiterte Tax-Schema geschrieben werden."
                if technical_ready
                else (
                    "Die Staging-Tabellen sind strukturell und je Steuerjahr paritaetisch; "
                    "die produktive Migration bleibt ausschliesslich wegen der belegten "
                    "Provider-Kostenbasisluecken gesperrt."
                    if provider_basis_gap_count and not unexplained_unmatched_count
                    else "Die Staging-Materialisierung besitzt mindestens einen technischen Blocker."
                )
            ),
            "Die Probe hat keine produktiven Tax-Lots, Tax-Lines oder Methodensettings geschrieben.",
            (
                "Eine gebundene Freigabe liegt vor; der kontrollierte Apply bleibt ein separater Schritt."
                if approved_decision_bound
                else "Vor einem produktiven Apply fehlt die explizite gebundene Methodenfreigabe."
            ),
        ]
        next_actions = (
            [
                (
                    "Die belegten Provider-Kostenbasisluecken fachlich entscheiden; keine "
                    "weiteren Nutzerexporte anfordern und keine Anschaffungskosten erfinden."
                    if provider_basis_gap_count and not unexplained_unmatched_count
                    else "Technische Checkfehler schliessen und die Migrationsprobe wiederholen."
                ),
            ]
            if not technical_ready
            else [
                "Methodenvergleich fachlich pruefen und die Entscheidung ueber den vorhandenen Abnahmepfad dokumentieren.",
                "Danach kontrollierten Apply mit verifiziertem Backup, atomarem Austausch und Jahresparitaetspruefung ausfuehren.",
            ]
            if not approved_decision_bound
            else [
                "Kontrollierten Apply nur mit verifiziertem Backup und unveraendertem Input-Fingerprint ausfuehren.",
            ]
        )
        report_payload = {
            "run_id": run.run_id,
            "run_semantic_sha256": run.semantic_sha256,
            "input_fingerprint_digest": run.input_fingerprint.digest,
            "status": status,
            "decision_status": acceptance.decision_status,
            "approved_decision_bound": approved_decision_bound,
            "technical_ready": technical_ready,
            "migration_ready": migration_ready,
            "provider_basis_gap_count": provider_basis_gap_count,
            "unexplained_unmatched_count": unexplained_unmatched_count,
            "staging_tax_lots_semantic_sha256": self._semantic_hash(staged_lots),
            "staging_tax_lines_semantic_sha256": self._semantic_hash(staged_lines),
            "year_checks": [item.model_dump(mode="json") for item in year_checks],
            "checks": [item.model_dump(mode="json") for item in checks],
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                report_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        report = WalletFifoMigrationRehearsalReport(
            rehearsal_id=rehearsal_id,
            generated_at=generated_at,
            status=status,
            run_id=run.run_id,
            run_generated_at=run.generated_at,
            run_as_of=run.as_of,
            run_semantic_sha256=run.semantic_sha256,
            input_fingerprint_digest=run.input_fingerprint.digest,
            input_fingerprint_current=acceptance.input_fingerprint_current,
            method_version=run.method_version,
            decision_status=acceptance.decision_status,
            decision_id=acceptance.decision_id,
            decision_ready=acceptance.decision_ready,
            approved_decision_bound=approved_decision_bound,
            active_fifo_scope=acceptance.active_fifo_scope,
            target_fifo_scope=acceptance.target_fifo_scope,
            technical_ready=technical_ready,
            migration_ready=migration_ready,
            production_write_performed=False,
            production_tax_semantic_unchanged=production_unchanged,
            provider_basis_gap_count=provider_basis_gap_count,
            unexplained_unmatched_count=unexplained_unmatched_count,
            source_all_lots_count=len(lots),
            source_open_lots_count=len(state.open_lots),
            source_tax_lines_count=len(lines),
            staging_lots_count=len(staged_lots),
            staging_open_lots_count=sum(item.quantity_remaining > 0 for item in staged_lots),
            staging_tax_lines_count=len(staged_lines),
            staging_orphan_tax_lines_count=staging_orphans,
            staging_negative_lots_count=staging_negative_lots,
            staging_arithmetic_delta_eur=staging_arithmetic_delta,
            staging_tax_lots_semantic_sha256=report_payload[
                "staging_tax_lots_semantic_sha256"
            ],
            staging_tax_lines_semantic_sha256=report_payload[
                "staging_tax_lines_semantic_sha256"
            ],
            semantic_sha256=semantic_sha256,
            year_checks=year_checks,
            checks=checks,
            blockers=blockers,
            findings=findings,
            next_actions=next_actions,
            evidence_refs=[
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}",
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-acceptance",
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/evidence/wallet_fifo_all_lots.csv.gz",
                f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/evidence/wallet_fifo_tax_lines.csv.gz",
            ],
            artifact_path=self._display_path(artifact_path),
            latest_artifact_path=self._display_path(latest_path),
            methodology=(
                "Read-only Migrationsprobe. Der gebundene Wallet-/Depot-FIFO-Replay wird in "
                "eine temporaere DuckDB mit dem erweiterten Tax-Schema geschrieben und wieder "
                "gelesen. Lot-/Line-Referenzen, Mengen, Gewinnformel, Methodenmetadaten, "
                "Jahresparitaet und der unveraenderte Produktiv-Fingerprint werden geprueft. "
                "Die temporaere Datenbank wird automatisch geloescht; die Produktivdatenbank "
                "wird nicht umgeschrieben und die Zielmethode nicht aktiviert."
            ),
        )
        content = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        self._atomic_write(artifact_path, content)
        self._atomic_write(latest_path, content)
        return report

    def latest(self) -> WalletFifoMigrationRehearsalReport | None:
        path = self.artifact_root / "latest_wallet_fifo_migration_rehearsal.json"
        try:
            return WalletFifoMigrationRehearsalReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def get(self, rehearsal_id: str) -> WalletFifoMigrationRehearsalReport | None:
        if not rehearsal_id.startswith("wallet-fifo-migration-"):
            return None
        path = self.artifact_root / rehearsal_id / "wallet_fifo_migration_rehearsal.json"
        try:
            return WalletFifoMigrationRehearsalReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var" / "wallet_fifo_migrations"

    @staticmethod
    def _check(
        key: str,
        label: str,
        gate: str,
        passed: bool,
        detail: str,
    ) -> WalletFifoMigrationCheck:
        return WalletFifoMigrationCheck(
            key=key,
            label=label,
            gate=gate,
            passed=passed,
            blocking=True,
            detail=detail,
        )

    @staticmethod
    def _semantic_hash(rows: list[BaseModel]) -> str:
        payloads = []
        for row in rows:
            payload = WalletFifoMigrationRehearsalService._canonical_value(
                row.model_dump(
                    mode="python",
                    exclude={"lot_id", "tax_line_id", "origin_lot_id"},
                )
            )
            payloads.append(payload)
        payloads.sort(
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )
        return hashlib.sha256(
            json.dumps(
                payloads,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _canonical_value(value: object) -> object:
        if isinstance(value, datetime):
            normalized = (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
            return normalized.replace(tzinfo=None).isoformat(timespec="microseconds")
        if isinstance(value, Decimal):
            with localcontext() as context:
                context.prec = 60
                return format(value.quantize(Decimal("0.000000000000000001")), "f")
        if isinstance(value, dict):
            return {
                str(key): WalletFifoMigrationRehearsalService._canonical_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                WalletFifoMigrationRehearsalService._canonical_value(item)
                for item in value
            ]
        return value

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(cls.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)


class WalletFifoMigrationApplyService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_BACKUP_ROOT = Path(
        "/workspace/backups/steuerreport-v2-plan/database"
    )
    CONFIRMATION_PHRASE = "WALLET_DEPOT_FIFO_V1_AKTIVIEREN"
    BACKUP_HEADROOM_BYTES = 64 * 1024 * 1024

    def __init__(
        self,
        store: DuckDbStore,
        *,
        backup_root: Path | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.run_service = WalletFifoParallelRunService(store)
        self.acceptance_service = WalletFifoMethodAcceptanceService(store)
        self.rehearsal_service = WalletFifoMigrationRehearsalService(
            store,
            artifact_root=artifact_root,
        )
        self.backup_root = backup_root or self._default_backup_root()
        base_artifact_root = artifact_root or self.rehearsal_service.artifact_root
        self.artifact_root = base_artifact_root / "applies"

    def readiness(
        self,
        *,
        run_id: str | None = None,
        rehearsal_id: str | None = None,
    ) -> WalletFifoMigrationApplyReadinessReport:
        generated_at = datetime.now(timezone.utc)
        run = self.run_service.get(run_id) if run_id else self.run_service.latest()
        rehearsal = (
            self.rehearsal_service.get(rehearsal_id)
            if rehearsal_id
            else self.rehearsal_service.latest()
        )
        acceptance = self.acceptance_service.readiness(
            run_id=run.run_id if run is not None else None
        )
        active_scope = active_fifo_scope(self.store)
        required_backup_bytes = self._required_backup_bytes()
        available_backup_bytes, backup_writable = self._backup_capacity()

        run_current = bool(
            run
            and acceptance.run_id == run.run_id
            and acceptance.input_fingerprint_current
        )
        rehearsal_bound = bool(
            run
            and rehearsal
            and rehearsal.run_id == run.run_id
            and rehearsal.input_fingerprint_digest
            == run.input_fingerprint.digest
            and rehearsal.run_semantic_sha256 == run.semantic_sha256
        )
        all_lots_evidence = next(
            (
                item
                for item in (run.evidence_files if run is not None else [])
                if item.kind == "wallet_fifo_all_lots"
            ),
            None,
        )
        checks = [
            self._check(
                "run_input_current",
                "Wallet-FIFO-Run entspricht dem aktuellen Datenstand",
                "technical",
                run_current,
                "Run, Methodenakte und semantischer Input muessen aktuell gebunden sein.",
            ),
            self._check(
                "complete_all_lots_evidence",
                "Vollstaendiger All-Lots-Beleg ist vorhanden",
                "technical",
                bool(
                    run
                    and run.all_lots_count > 0
                    and all_lots_evidence
                    and all_lots_evidence.records_count == run.all_lots_count
                ),
                (
                    f"Run-Lots: {run.all_lots_count if run else 0}; "
                    f"Belegzeilen: {all_lots_evidence.records_count if all_lots_evidence else 0}."
                ),
            ),
            self._check(
                "rehearsal_bound",
                "Migrationsprobe ist an denselben Run gebunden",
                "technical",
                rehearsal_bound,
                "Run-ID, Input-Fingerprint und Run-Semantik muessen uebereinstimmen.",
            ),
            self._check(
                "rehearsal_technical_ready",
                "Migrationsprobe besteht alle Technikchecks",
                "technical",
                bool(rehearsal and rehearsal.technical_ready),
                f"Status: {rehearsal.status if rehearsal else 'missing'}.",
            ),
            self._check(
                "decision_approved_and_bound",
                "Explizite Methodenfreigabe ist gebunden",
                "governance",
                bool(
                    acceptance.decision_status
                    == WalletFifoMigrationRehearsalService.APPROVAL
                    and acceptance.decision_id
                    and acceptance.decision_ready
                ),
                f"Entscheidungsstatus: {acceptance.decision_status}.",
            ),
            self._check(
                "rehearsal_migration_ready",
                "Migrationsprobe bestaetigt die gebundene Freigabe",
                "governance",
                bool(rehearsal and rehearsal.migration_ready),
                "Nach einer Freigabe muss die Probe fuer denselben Run erneut ausgefuehrt werden.",
            ),
            self._check(
                "source_method_supported",
                "Aktive Ausgangsmethode ist kontrolliert",
                "operational",
                active_scope
                in {GLOBAL_ASSET_FIFO_SCOPE, WALLET_DEPOT_FIFO_SCOPE},
                f"Aktive Methode: {active_scope}.",
            ),
            self._check(
                "atomic_replace_available",
                "Atomarer Tax-Tabellentausch ist verfuegbar",
                "operational",
                hasattr(TaxService, "_replace_tax_tables"),
                "Lots, Tax-Lines, Summary und unmatched Abgaenge werden in einer Transaktion ersetzt.",
            ),
            self._check(
                "wallet_rebuild_available",
                "Folge-Rebuilds erhalten Wallet-/Depot-FIFO",
                "operational",
                hasattr(TaxService, "_rebuild_wallet_fifo"),
                "Nach Aktivierung dispatcht der produktive Rebuild anhand des letzten Tax-Run-Summary.",
            ),
            self._check(
                "backup_target_writable",
                "Backup-Ziel ist beschreibbar",
                "operational",
                backup_writable,
                f"Backup-Ziel: {self.backup_root}.",
            ),
            self._check(
                "backup_capacity",
                "Backup-Speicher besitzt ausreichende Reserve",
                "operational",
                available_backup_bytes >= required_backup_bytes,
                (
                    f"Erforderlich: {required_backup_bytes} Bytes; "
                    f"verfuegbar: {available_backup_bytes} Bytes."
                ),
            ),
        ]
        already_active = active_scope == WALLET_DEPOT_FIFO_SCOPE
        ready = all(item.passed for item in checks if item.blocking)
        status = (
            "already_active"
            if already_active
            else "ready_for_controlled_apply"
            if ready
            else "blocked"
        )
        blockers = [item.detail for item in checks if item.blocking and not item.passed]
        next_actions = (
            ["Wallet-/Depot-FIFO ist bereits produktiv aktiv; keinen erneuten Apply ausfuehren."]
            if already_active
            else [
                "Methodenvergleich fachlich pruefen und die gebundene Methodenfreigabe dokumentieren.",
                "Danach die Migrationsprobe erneut ausfuehren und den kontrollierten Apply explizit bestaetigen.",
            ]
            if not ready
            else [
                "Apply mit Run-, Rehearsal- und Decision-ID sowie allen Bestaetigungen ausfuehren."
            ]
        )
        return WalletFifoMigrationApplyReadinessReport(
            generated_at=generated_at,
            status=status,
            ready=ready or already_active,
            run_id=run.run_id if run is not None else None,
            rehearsal_id=(
                rehearsal.rehearsal_id if rehearsal is not None else None
            ),
            decision_id=acceptance.decision_id,
            decision_status=acceptance.decision_status,
            input_fingerprint_current=run_current,
            rehearsal_bound=rehearsal_bound,
            active_fifo_scope=active_scope,
            target_fifo_scope=WALLET_DEPOT_FIFO_SCOPE,
            backup_root=str(self.backup_root),
            required_backup_bytes=required_backup_bytes,
            available_backup_bytes=available_backup_bytes,
            checks=checks,
            blockers=blockers,
            next_actions=next_actions,
            evidence_refs=[
                "/api/v1/tax/wallet-fifo-runs/latest/method-acceptance",
                "/api/v1/tax/wallet-fifo-migrations/rehearsals/latest",
                "/api/v1/tax/wallet-fifo-migrations/apply-readiness",
            ],
            methodology=(
                "Read-only Apply-Gate. Es bindet Quelldatenstand, vollstaendigen "
                "All-Lots-Beleg, Migrationsprobe, explizite Methodenfreigabe, "
                "atomaren Tabellentausch, Folge-Rebuild und Backup-Kapazitaet. "
                "Der Readiness-Aufruf schreibt keine Steuer- oder Methodendaten."
            ),
        )

    def apply(
        self,
        request: WalletFifoMigrationApplyRequest,
    ) -> WalletFifoMigrationApplyReport:
        readiness = self.readiness(
            run_id=request.run_id,
            rehearsal_id=request.rehearsal_id,
        )
        if readiness.status == "already_active":
            if (
                request.run_id != readiness.run_id
                or request.rehearsal_id != readiness.rehearsal_id
                or request.decision_id != readiness.decision_id
            ):
                raise ValueError(
                    "Der idempotente Apply-Aufruf ist nicht an die aktive Methodenakte gebunden."
                )
            summary = TaxService(self.store).latest_summary()
            return self._result(
                request=request,
                readiness=readiness,
                status="already_active",
                applied=False,
                input_fingerprint_digest=(
                    summary.input_fingerprint_digest
                    if summary and summary.input_fingerprint_digest
                    else ""
                ),
            )
        if not request.execute:
            return self._result(
                request=request,
                readiness=readiness,
                status="dry_run",
                applied=False,
                input_fingerprint_digest="",
            )
        self._validate_execution_request(request, readiness)

        run = self.run_service.get(request.run_id)
        rehearsal = self.rehearsal_service.get(request.rehearsal_id)
        if run is None or rehearsal is None:
            raise ValueError("Run oder Migrationsprobe ist nicht mehr verfuegbar.")
        state = WalletFifoPreviewService(self.store).replay(as_of=run.as_of)
        if state.unmatched:
            raise ValueError("Der aktuelle Wallet-FIFO-Replay besitzt unmatched Abgaenge.")
        lots, lines = wallet_fifo_tax_rows(state)
        if (
            self.rehearsal_service._semantic_hash(lots)
            != rehearsal.staging_tax_lots_semantic_sha256
            or self.rehearsal_service._semantic_hash(lines)
            != rehearsal.staging_tax_lines_semantic_sha256
        ):
            raise ValueError(
                "Der aktuelle Wallet-FIFO-Zielzustand weicht von der gebundenen Migrationsprobe ab."
            )

        backup_path: Path | None = None
        backup_sha256: str | None = None
        backup_size = 0
        with self.store.exclusive_access():
            current_fingerprint = self.run_service.input_fingerprint(run.as_of)
            if current_fingerprint.digest != run.input_fingerprint.digest:
                raise ValueError(
                    "Der produktive Datenstand hat sich seit dem gebundenen Run geaendert."
                )
            current_readiness = self.readiness(
                run_id=request.run_id,
                rehearsal_id=request.rehearsal_id,
            )
            if not current_readiness.ready:
                raise ValueError("Apply-Gates sind nicht mehr vollstaendig erfuellt.")
            backup_path, backup_sha256, backup_size = self._create_verified_backup(
                run.input_fingerprint.digest
            )
            TaxService(self.store)._replace_tax_tables(
                lots,
                lines,
                [],
                fifo_method=WALLET_DEPOT_FIFO_SCOPE,
                input_fingerprint_digest=run.input_fingerprint.digest,
            )

        summary = TaxService(self.store).latest_summary()
        if not (
            summary
            and summary.fifo_method == WALLET_DEPOT_FIFO_SCOPE
            and summary.input_fingerprint_digest == run.input_fingerprint.digest
            and summary.tax_lines_count == len(lines)
        ):
            raise RuntimeError(
                "Wallet-/Depot-FIFO wurde geschrieben, aber die Abschlussverifikation ist fehlgeschlagen."
            )
        post_acceptance = self.acceptance_service.readiness(run_id=run.run_id)
        if not post_acceptance.strict_ready:
            raise RuntimeError(
                "Wallet-/Depot-FIFO ist aktiv, aber die gebundene Methodenakte meldet nicht strict_ready."
            )
        readiness_after = self.readiness(
            run_id=request.run_id,
            rehearsal_id=request.rehearsal_id,
        )
        report = self._result(
            request=request,
            readiness=readiness_after,
            status="applied",
            applied=True,
            input_fingerprint_digest=run.input_fingerprint.digest,
            source_fifo_scope=readiness.active_fifo_scope,
            lots_count=len(lots),
            open_lots_count=sum(item.quantity_remaining > 0 for item in lots),
            tax_lines_count=len(lines),
            backup_path=backup_path,
            backup_sha256=backup_sha256,
            backup_size_bytes=backup_size,
            year_checks=rehearsal.year_checks,
        )
        return self._persist_report(report)

    def latest(self) -> WalletFifoMigrationApplyReport | None:
        path = self.artifact_root / "latest_wallet_fifo_migration_apply.json"
        try:
            return WalletFifoMigrationApplyReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _validate_execution_request(
        self,
        request: WalletFifoMigrationApplyRequest,
        readiness: WalletFifoMigrationApplyReadinessReport,
    ) -> None:
        if not readiness.ready or readiness.status != "ready_for_controlled_apply":
            raise ValueError(
                "Kontrollierter Apply ist blockiert: "
                + " | ".join(readiness.blockers)
            )
        if request.decision_id != readiness.decision_id:
            raise ValueError("Decision-ID stimmt nicht mit der gebundenen Freigabe ueberein.")
        rehearsal = self.rehearsal_service.get(request.rehearsal_id)
        if (
            rehearsal is None
            or request.rehearsal_semantic_sha256 != rehearsal.semantic_sha256
        ):
            raise ValueError("Rehearsal-Hash stimmt nicht mit der gebundenen Probe ueberein.")
        if request.confirmation_phrase != self.CONFIRMATION_PHRASE:
            raise ValueError("Explizite Aktivierungsphrase fehlt oder ist falsch.")
        if not all(
            (
                request.acknowledge_verified_backup,
                request.acknowledge_material_tax_delta,
                request.acknowledge_report_regeneration,
            )
        ):
            raise ValueError("Alle Apply-Bestaetigungen muessen ausdruecklich gesetzt sein.")

    def _result(
        self,
        *,
        request: WalletFifoMigrationApplyRequest,
        readiness: WalletFifoMigrationApplyReadinessReport,
        status: str,
        applied: bool,
        input_fingerprint_digest: str,
        source_fifo_scope: str | None = None,
        lots_count: int = 0,
        open_lots_count: int = 0,
        tax_lines_count: int = 0,
        backup_path: Path | None = None,
        backup_sha256: str | None = None,
        backup_size_bytes: int = 0,
        year_checks: list[WalletFifoMigrationYearCheck] | None = None,
    ) -> WalletFifoMigrationApplyReport:
        generated_at = datetime.now(timezone.utc)
        return WalletFifoMigrationApplyReport(
            migration_id=(
                f"wallet-fifo-apply-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
                f"{uuid4().hex[:8]}"
            ),
            generated_at=generated_at,
            status=status,
            applied=applied,
            run_id=request.run_id,
            rehearsal_id=request.rehearsal_id,
            decision_id=request.decision_id,
            actor=request.actor,
            source_fifo_scope=source_fifo_scope or readiness.active_fifo_scope,
            target_fifo_scope=WALLET_DEPOT_FIFO_SCOPE,
            input_fingerprint_digest=input_fingerprint_digest,
            lots_count=lots_count,
            open_lots_count=open_lots_count,
            tax_lines_count=tax_lines_count,
            backup_path=str(backup_path) if backup_path is not None else None,
            backup_size_bytes=backup_size_bytes,
            backup_sha256=backup_sha256,
            year_checks=year_checks or [],
            readiness=readiness,
            methodology=(
                "Kontrollierter, fingerprintgebundener Wallet-/Depot-FIFO-Apply. "
                "Vor dem atomaren Tax-Tabellentausch wird unter exklusivem Store-Lock "
                "eine bytegleich verifizierte Datenbanksicherung erzeugt. Der Aufruf "
                "erfordert eine explizite Methodenentscheidung, aktuelle Migrationsprobe, "
                "Hash-Bindung, Aktivierungsphrase und drei Bestaetigungen."
            ),
        )

    def _persist_report(
        self,
        report: WalletFifoMigrationApplyReport,
    ) -> WalletFifoMigrationApplyReport:
        artifact_path = (
            self.artifact_root
            / report.migration_id
            / "wallet_fifo_migration_apply.json"
        )
        latest_path = self.artifact_root / "latest_wallet_fifo_migration_apply.json"
        report = report.model_copy(
            update={
                "artifact_path": self.rehearsal_service._display_path(artifact_path),
                "latest_artifact_path": self.rehearsal_service._display_path(latest_path),
            }
        )
        content = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        self.rehearsal_service._atomic_write(artifact_path, content)
        self.rehearsal_service._atomic_write(latest_path, content)
        return report

    def _create_verified_backup(
        self,
        input_fingerprint_digest: str,
    ) -> tuple[Path, str, int]:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        generated_at = datetime.now(timezone.utc)
        backup_path = self.backup_root / (
            "steuerreport_v2_before_wallet_fifo_apply_"
            f"{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}_"
            f"{input_fingerprint_digest[:12]}.duckdb"
        )
        if backup_path.exists():
            raise ValueError(f"Backup-Zieldatei existiert bereits: {backup_path}")
        source_hash = self._file_sha256(self.store.path)
        shutil.copy2(self.store.path, backup_path)
        with backup_path.open("rb") as handle:
            os.fsync(handle.fileno())
        backup_hash = self._file_sha256(backup_path)
        if source_hash != backup_hash:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError("Datenbankbackup ist nicht bytegleich; Apply wurde abgebrochen.")
        return backup_path, backup_hash, backup_path.stat().st_size

    def _required_backup_bytes(self) -> int:
        try:
            source_size = self.store.path.stat().st_size
        except OSError:
            source_size = 0
        return source_size + max(
            self.BACKUP_HEADROOM_BYTES,
            source_size // 20,
        )

    def _backup_capacity(self) -> tuple[int, bool]:
        existing_parent = self.backup_root
        while not existing_parent.exists() and existing_parent != existing_parent.parent:
            existing_parent = existing_parent.parent
        try:
            available = shutil.disk_usage(existing_parent).free
            writable = os.access(existing_parent, os.W_OK)
        except OSError:
            return 0, False
        return available, writable

    def _default_backup_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_BACKUP_ROOT
        return self.store.path.parent / "backups"

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _check(
        key: str,
        label: str,
        gate: str,
        passed: bool,
        detail: str,
    ) -> WalletFifoMigrationApplyCheck:
        return WalletFifoMigrationApplyCheck(
            key=key,
            label=label,
            gate=gate,
            passed=passed,
            blocking=True,
            detail=detail,
        )
