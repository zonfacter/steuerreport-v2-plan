from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4
import zipfile
from zoneinfo import ZoneInfo

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.tax_filing_snapshots import (
    TaxFilingSnapshot,
    TaxFilingSnapshotCaptureRequest,
    TaxFilingSnapshotCaptureResult,
    TaxFilingSnapshotComparison,
    TaxFilingSnapshotDelta,
    TaxFilingSnapshotFile,
    TaxFilingSnapshotList,
    TaxFilingSnapshotUsageConfirmationRequest,
    TaxFilingSnapshotUsageConfirmationResult,
    TaxFilingValues,
)
from steuerreport_v2.contracts.tax_years import TaxYearFilingSummary
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_years import TaxYearService


SUBMISSION_CONFIRMATION_TEXT = "ICH BESTAETIGE DIE TATSAECHLICHE ABGABE"
SOFTWARE_VERSION = __version__
METHOD_VERSION = "bmf_readiness_v3_provider_basis_classification"


class TaxFilingSnapshotError(ValueError):
    pass


class TaxFilingSnapshotService:
    LEGAL_REFERENCE = (
        "BMF-Schreiben vom 6. Maerz 2025, insbesondere Rn. 90, 95 bis 103; "
        "§§ 146, 147 und 153 AO."
    )

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.archive_root = store.path.parent / "tax_filing_archive"

    def capture_package(
        self,
        *,
        year: int,
        package_bytes: bytes,
        request: TaxFilingSnapshotCaptureRequest,
        source_kind: str,
        package_filename: str | None = None,
    ) -> TaxFilingSnapshotCaptureResult:
        self._validate_request(request)
        validated = self._validate_package(year, package_bytes)
        package_sha256 = hashlib.sha256(package_bytes).hexdigest()
        package_filename = package_filename or (
            f"steuerreport-v2-tax-year-{year}-evidence.zip"
        )

        existing = self._find_duplicate(
            year=year,
            package_sha256=package_sha256,
            state=request.state,
            filing_kind=request.filing_kind,
        )
        if existing is not None:
            return TaxFilingSnapshotCaptureResult(
                created=False,
                snapshot=existing,
                comparison_endpoint=(
                    f"/api/v1/tax-years/{year}/filing-snapshot-comparison"
                ),
                message="Dieser unveraenderliche Paketstand ist bereits registriert.",
            )

        archive_path = self._archive_path(year, package_sha256)
        self._write_archive_once(archive_path, package_bytes, package_sha256)
        runtime_fingerprint_sha256, runtime_fingerprint = (
            self._runtime_fingerprint()
        )
        now = datetime.now(timezone.utc)
        submitted_at = self._submitted_at(request, now)
        snapshot_id = str(uuid4())

        with self.store.connect() as con:
            revision = int(
                con.execute(
                    "select coalesce(max(revision), 0) + 1 from tax_filing_snapshots where year = ?",
                    [year],
                ).fetchone()[0]
            )
            values = validated["values"]
            con.execute("begin transaction")
            try:
                con.execute(
                    """
                    insert into tax_filing_snapshots (
                        snapshot_id, year, revision, state, filing_kind, source_kind,
                        source_snapshot_id, package_filename, archive_relative_path,
                        package_sha256, package_size_bytes, manifest_sha256,
                        runtime_fingerprint_sha256, package_generated_at,
                        summary_json, manifest_json, metadata_json,
                        taxable_private_disposals_eur,
                        taxable_disposal_proceeds_eur,
                        acquisition_cost_eur,
                        rewards_mining_staking_income_eur,
                        derivative_pnl_eur,
                        tax_free_private_disposals_eur,
                        tax_free_lines_count, export_ready, note, created_at, submitted_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        snapshot_id,
                        year,
                        revision,
                        request.state,
                        request.filing_kind,
                        source_kind,
                        request.source_snapshot_id,
                        package_filename,
                        str(archive_path.relative_to(self.store.path.parent)),
                        package_sha256,
                        len(package_bytes),
                        validated["manifest_sha256"],
                        runtime_fingerprint_sha256,
                        self._parse_datetime(validated["manifest"]["generated_at"]),
                        json.dumps(validated["summary"], ensure_ascii=False),
                        json.dumps(validated["manifest"], ensure_ascii=False),
                        json.dumps(
                            {
                                "legal_reference": self.LEGAL_REFERENCE,
                                "software_version": SOFTWARE_VERSION,
                                "method_version": METHOD_VERSION,
                                "database_fingerprint_sha256": runtime_fingerprint_sha256,
                                "captured_at_utc": now.isoformat(),
                                "captured_at_europe_berlin": now.astimezone(
                                    ZoneInfo("Europe/Berlin")
                                ).isoformat(),
                                "runtime_fingerprint": runtime_fingerprint,
                                "package_validation": {
                                    "safe_paths": True,
                                    "manifest_file_hashes_verified": True,
                                    "filing_summary_year_verified": True,
                                },
                            },
                            ensure_ascii=False,
                        ),
                        values.taxable_private_disposals_eur,
                        values.taxable_disposal_proceeds_eur,
                        values.acquisition_cost_eur,
                        values.rewards_mining_staking_income_eur,
                        values.derivative_pnl_eur,
                        values.tax_free_private_disposals_eur,
                        values.tax_free_lines_count,
                        values.export_ready,
                        request.note,
                        now.replace(tzinfo=None),
                        submitted_at.replace(tzinfo=None) if submitted_at else None,
                    ],
                )
                for file in validated["files"]:
                    con.execute(
                        """
                        insert into tax_filing_snapshot_files (
                            snapshot_id, path, size_bytes, sha256, source_endpoint
                        ) values (?, ?, ?, ?, ?)
                        """,
                        [
                            snapshot_id,
                            file.path,
                            file.size_bytes,
                            file.sha256,
                            file.source_endpoint,
                        ],
                    )
                con.execute(
                    """
                    insert into tax_filing_snapshot_events (
                        event_id, snapshot_id, event_type, payload_json, created_at
                    ) values (?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid4()),
                        snapshot_id,
                        "snapshot_captured",
                        json.dumps(
                            {
                                "state": request.state,
                                "filing_kind": request.filing_kind,
                                "source_kind": source_kind,
                                "source_snapshot_id": request.source_snapshot_id,
                                "package_sha256": package_sha256,
                            },
                            ensure_ascii=False,
                        ),
                        now.replace(tzinfo=None),
                    ],
                )
                con.execute("commit")
            except Exception:
                con.execute("rollback")
                raise

        snapshot = self.get(snapshot_id)
        return TaxFilingSnapshotCaptureResult(
            created=True,
            snapshot=snapshot,
            comparison_endpoint=(
                f"/api/v1/tax-years/{year}/filing-snapshot-comparison"
            ),
            message=(
                "Tatsaechlich eingereichter Stand unveraenderlich registriert."
                if request.state == "submitted"
                else "Paketstand unveraenderlich als Referenz archiviert; noch nicht als eingereicht bestaetigt."
            ),
        )

    def capture_from_snapshot(
        self,
        *,
        year: int,
        request: TaxFilingSnapshotCaptureRequest,
    ) -> TaxFilingSnapshotCaptureResult:
        if not request.source_snapshot_id:
            raise TaxFilingSnapshotError("source_snapshot_id fehlt.")
        source = self.get(request.source_snapshot_id)
        if source.year != year:
            raise TaxFilingSnapshotError(
                "Der Quell-Snapshot gehoert zu einem anderen Steuerjahr."
            )
        package_bytes = self.read_package(source.snapshot_id)
        return self.capture_package(
            year=year,
            package_bytes=package_bytes,
            request=request,
            source_kind="archived_snapshot_confirmation",
            package_filename=source.package_filename,
        )

    def import_existing_package(
        self,
        *,
        year: int,
        package_path: Path,
        request: TaxFilingSnapshotCaptureRequest,
    ) -> TaxFilingSnapshotCaptureResult:
        if not package_path.is_file():
            raise TaxFilingSnapshotError(f"Paketdatei fehlt: {package_path}")
        return self.capture_package(
            year=year,
            package_bytes=package_path.read_bytes(),
            request=request,
            source_kind="historical_artifact_import",
            package_filename=package_path.name,
        )

    def confirm_package_usage(
        self,
        *,
        snapshot_id: str,
        request: TaxFilingSnapshotUsageConfirmationRequest,
    ) -> TaxFilingSnapshotUsageConfirmationResult:
        snapshot = self.get(snapshot_id)
        if snapshot.state == "submitted":
            raise TaxFilingSnapshotError(
                "Der Snapshot ist bereits mit einem Uebermittlungszeitpunkt als eingereicht registriert."
            )
        if snapshot.integrity_status != "verified":
            raise TaxFilingSnapshotError(
                "Die Paketverwendung kann nur fuer ein hashverifiziertes Archiv bestaetigt werden."
            )
        existing = self._usage_confirmation(snapshot_id)
        if existing is not None:
            return TaxFilingSnapshotUsageConfirmationResult(
                created=False,
                event_id=str(existing["event_id"]),
                snapshot=self.get(snapshot_id),
                comparison_endpoint=(
                    f"/api/v1/tax-years/{snapshot.year}/filing-snapshot-comparison"
                ),
                message="Die Verwendung dieses Paketstands ist bereits bestaetigt.",
            )

        now = datetime.now(timezone.utc)
        event_id = str(uuid4())
        payload = {
            "actor": request.actor,
            "source": request.source,
            "statement": request.statement,
            "package_sha256": snapshot.package_sha256,
            "actual_submission_timestamp_known": False,
        }
        with self.store.connect() as con:
            con.execute(
                """
                insert into tax_filing_snapshot_events (
                    event_id, snapshot_id, event_type, payload_json, created_at
                ) values (?, ?, ?, ?, ?)
                """,
                [
                    event_id,
                    snapshot_id,
                    "filing_package_usage_confirmed",
                    json.dumps(payload, ensure_ascii=False),
                    now.replace(tzinfo=None),
                ],
            )
        return TaxFilingSnapshotUsageConfirmationResult(
            created=True,
            event_id=event_id,
            snapshot=self.get(snapshot_id),
            comparison_endpoint=(
                f"/api/v1/tax-years/{snapshot.year}/filing-snapshot-comparison"
            ),
            message=(
                "Paketverwendung revisionsfest bestaetigt. Der tatsaechliche "
                "Uebermittlungszeitpunkt bleibt bis zum ELSTER-Beleg offen."
            ),
        )

    def list(self, *, year: int | None = None) -> TaxFilingSnapshotList:
        where = "where year = ?" if year is not None else ""
        params = [year] if year is not None else []
        with self.store.connect() as con:
            rows = self._fetch_dicts(
                con,
                f"""
                select * from tax_filing_snapshots
                {where}
                order by year desc, revision desc
                """,
                params,
            )
        snapshots = [self._to_contract(row, include_files=False) for row in rows]
        return TaxFilingSnapshotList(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            snapshots=snapshots,
            submitted_count=sum(item.state == "submitted" for item in snapshots),
            reference_count=sum(item.state == "reference" for item in snapshots),
            integrity_failures=sum(
                item.integrity_status != "verified" for item in snapshots
            ),
            methodology=(
                "Append-only Register unveraenderlicher Jahres-Belegpakete. Jeder "
                "Paketinhalt und jede manifestierte Datei ist SHA-256-gebunden; eine "
                "Abgabebestaetigung erzeugt eine neue Revision und veraendert keinen Altstand."
            ),
        )

    def get(self, snapshot_id: str) -> TaxFilingSnapshot:
        with self.store.connect() as con:
            rows = self._fetch_dicts(
                con,
                "select * from tax_filing_snapshots where snapshot_id = ?",
                [snapshot_id],
            )
            if not rows:
                raise KeyError(snapshot_id)
            file_rows = self._fetch_dicts(
                con,
                """
                select path, size_bytes, sha256, source_endpoint
                from tax_filing_snapshot_files
                where snapshot_id = ?
                order by path
                """,
                [snapshot_id],
            )
        return self._to_contract(rows[0], file_rows=file_rows, include_files=True)

    def read_package(self, snapshot_id: str) -> bytes:
        snapshot = self.get(snapshot_id)
        path = self._path_for_snapshot(snapshot_id)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise FileNotFoundError(path) from exc
        if hashlib.sha256(content).hexdigest() != snapshot.package_sha256:
            raise TaxFilingSnapshotError(
                "Archivintegritaet verletzt: SHA-256 stimmt nicht mit dem Register ueberein."
            )
        return content

    def comparison(
        self,
        year: int,
        *,
        current_summary: TaxYearFilingSummary | None = None,
    ) -> TaxFilingSnapshotComparison:
        snapshots = self.list(year=year).snapshots
        latest_reference = next(
            (item for item in snapshots if item.state == "reference"), None
        )
        usage_confirmed_reference = next(
            (
                item
                for item in snapshots
                if item.state == "reference" and item.filing_usage_confirmed
            ),
            None,
        )
        submitted_hashes = {
            item.package_sha256 for item in snapshots if item.state == "submitted"
        }
        unconfirmed_reference = next(
            (
                item
                for item in snapshots
                if item.state == "reference"
                and item.package_sha256 not in submitted_hashes
            ),
            None,
        )
        baseline = next(
            (item for item in snapshots if item.state == "submitted"),
            usage_confirmed_reference or latest_reference,
        )
        selection = (
            "latest_submitted"
            if baseline is not None and baseline.state == "submitted"
            else "confirmed_used_reference"
            if baseline is not None and baseline.filing_usage_confirmed
            else "latest_reference"
            if baseline is not None
            else "none"
        )
        current = self._values_from_summary(
            current_summary or TaxYearService(self.store).filing_summary(year)
        )
        deltas = self._deltas(baseline.values, current) if baseline else []
        exact_change = any(item.delta_eur != 0 for item in deltas)
        declaration_change = any(
            item.category == "declaration" and item.changed_at_cent_precision
            for item in deltas
        )
        integrity_blocked = bool(
            baseline is not None and baseline.integrity_status != "verified"
        )
        amendment_review = bool(
            baseline is not None
            and (
                baseline.state == "submitted"
                or baseline.filing_usage_confirmed
            )
            and declaration_change
        )
        confirmation_required = bool(
            baseline is not None
            and baseline.state == "reference"
            and not baseline.filing_usage_confirmed
        )
        submission_timestamp_required = bool(
            baseline is not None
            and baseline.state == "reference"
            and baseline.filing_usage_confirmed
        )

        if integrity_blocked:
            status = "integrity_blocked"
            headline = "Archivintegritaet muss sofort geklaert werden"
            next_action = (
                "Archivdatei aus der Sicherung wiederherstellen und SHA-256 erneut pruefen; "
                "bis dahin keinen Korrekturentscheid aus diesem Snapshot ableiten."
            )
        elif baseline is None:
            status = "no_snapshot"
            headline = "Noch kein Abgabestand archiviert"
            next_action = (
                "Den verwendeten Jahresstand als Referenz archivieren. Erst nach Abgleich "
                "mit der tatsaechlich uebermittelten Erklaerung als eingereicht bestaetigen."
            )
        elif confirmation_required:
            status = "reference_confirmation_required"
            headline = "Historisches Paket gefunden, Abgabebestaetigung offen"
            next_action = (
                "Pruefen, ob genau dieses Paket der abgegebenen Erklaerung zugrunde lag; "
                "nur dann ueber die UI als tatsaechlich eingereicht bestaetigen."
            )
        elif amendment_review:
            status = "changed_review_required"
            headline = (
                "Verwendeter Abgabestand weicht vom aktuellen Stand ab"
                if submission_timestamp_required
                else "Aktueller Stand weicht von der Abgabe ab"
            )
            next_action = (
                "Deltas je Einkunftsart mit den uebermittelten Formularwerten und Belegen "
                "abgleichen. Bei moeglicher Steuerverkuerzung die Berichtigungsfrage nach "
                "§ 153 AO unverzueglich fachlich pruefen."
                + (
                    " Den tatsaechlichen ELSTER-Uebermittlungszeitpunkt getrennt nachtragen."
                    if submission_timestamp_required
                    else ""
                )
            )
        elif submission_timestamp_required:
            status = "submission_timestamp_required"
            headline = "Paketverwendung bestaetigt, Uebermittlungszeitpunkt offen"
            next_action = (
                "Den tatsaechlichen ELSTER-Uebermittlungszeitpunkt aus dem "
                "Transferprotokoll nachtragen; nicht aus Paket- oder Dateidatum ableiten."
            )
        else:
            status = "unchanged"
            headline = (
                "Abgabewerte stimmen auf Cent-Ebene mit dem aktuellen Stand ueberein"
                if not declaration_change
                else "Nur nicht eintragungsrelevante Nachweise haben sich geaendert"
            )
            next_action = (
                "Snapshot und Belegpaket unveraendert aufbewahren; neue Quellenimporte "
                "weiterhin gegen diesen Stand vergleichen."
            )

        return TaxFilingSnapshotComparison(
            year=year,
            generated_at=datetime.now(timezone.utc).isoformat(),
            baseline=baseline,
            baseline_selection=selection,
            latest_reference=latest_reference,
            unconfirmed_reference=unconfirmed_reference,
            usage_confirmed_reference=usage_confirmed_reference,
            current_values=current,
            deltas=deltas,
            exact_change_detected=exact_change,
            declaration_change_detected=declaration_change,
            amendment_review_required=amendment_review,
            submission_confirmation_required=confirmation_required,
            submission_timestamp_required=submission_timestamp_required,
            integrity_blocked=integrity_blocked,
            status=status,
            headline=headline,
            next_action=next_action,
            legal_notice=(
                "Die Software dokumentiert und vergleicht Tatsachenstaende, ersetzt aber "
                "keine steuerberatende Einzelfallpruefung. Eine Abweichung loest nicht "
                "automatisch eine Berichtigung aus; massgeblich sind die tatsaechlich "
                "uebermittelten Werte und die Voraussetzungen des § 153 AO."
            ),
            comparison_html_endpoint=(
                f"/api/v1/tax-years/{year}/filing-snapshot-comparison.html"
            ),
            audit_report_endpoint=(
                f"/api/v1/tax-years/{year}/filing-audit-report"
            ),
            methodology=(
                "Verglichen wird vorrangig die neueste als eingereicht bestaetigte Revision, "
                "sonst die neueste Referenz. Deklarationsaenderungen werden je Einkunftsart "
                "getrennt auf Cent-Ebene beurteilt; Verluste und Einkuenfte werden nicht "
                "rechtswidrig oder irrefuehrend miteinander saldiert."
            ),
        )

    def governance_status(self) -> dict[str, object]:
        report = self.list()
        submitted_hashes = {
            (item.year, item.package_sha256)
            for item in report.snapshots
            if item.state == "submitted"
        }
        submitted_years = sorted(
            {item.year for item in report.snapshots if item.state == "submitted"}
        )
        reference_years = sorted(
            {item.year for item in report.snapshots if item.state == "reference"}
        )
        unconfirmed_reference_years = sorted(
            {
                item.year
                for item in report.snapshots
                if item.state == "reference"
                and (item.year, item.package_sha256) not in submitted_hashes
                and not item.filing_usage_confirmed
            }
        )
        usage_confirmed_reference_years = sorted(
            {
                item.year
                for item in report.snapshots
                if item.state == "reference"
                and item.filing_usage_confirmed
                and (item.year, item.package_sha256) not in submitted_hashes
            }
        )
        return {
            "snapshots_count": len(report.snapshots),
            "submitted_years": submitted_years,
            "reference_years": reference_years,
            "unconfirmed_reference_years": unconfirmed_reference_years,
            "usage_confirmed_reference_years": usage_confirmed_reference_years,
            "submission_timestamp_missing_years": usage_confirmed_reference_years,
            "integrity_failures": report.integrity_failures,
        }

    def _validate_request(self, request: TaxFilingSnapshotCaptureRequest) -> None:
        if request.state == "submitted":
            if request.confirmation_text != SUBMISSION_CONFIRMATION_TEXT:
                raise TaxFilingSnapshotError(
                    "Die Abgabe darf nur mit der ausdruecklichen Bestaetigung "
                    f"'{SUBMISSION_CONFIRMATION_TEXT}' registriert werden."
                )
            if not request.submitted_at:
                raise TaxFilingSnapshotError(
                    "Der tatsaechliche Uebermittlungszeitpunkt submitted_at fehlt."
                )
        elif request.submitted_at is not None:
            raise TaxFilingSnapshotError(
                "submitted_at ist nur fuer tatsaechlich eingereichte Snapshots erlaubt."
            )

    def _submitted_at(
        self,
        request: TaxFilingSnapshotCaptureRequest,
        now: datetime,
    ) -> datetime | None:
        if request.state != "submitted":
            return None
        try:
            parsed = self._parse_datetime(request.submitted_at or "")
        except (TypeError, ValueError) as exc:
            raise TaxFilingSnapshotError(
                "submitted_at ist kein gueltiger ISO-8601-Zeitpunkt."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        submitted_at = parsed.astimezone(timezone.utc)
        if submitted_at > now:
            raise TaxFilingSnapshotError(
                "submitted_at darf nicht in der Zukunft liegen."
            )
        return submitted_at

    def _validate_package(self, year: int, package_bytes: bytes) -> dict[str, object]:
        if not package_bytes:
            raise TaxFilingSnapshotError("Das Belegpaket ist leer.")
        try:
            with zipfile.ZipFile(io.BytesIO(package_bytes)) as package:
                names = package.namelist()
                if len(names) != len(set(names)):
                    raise TaxFilingSnapshotError(
                        "Das Belegpaket enthaelt doppelte Dateipfade."
                    )
                for name in names:
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts:
                        raise TaxFilingSnapshotError(
                            f"Unsicherer Dateipfad im Belegpaket: {name}"
                        )
                manifest_path = "00_Manifest/year-evidence-manifest.json"
                if manifest_path not in names:
                    raise TaxFilingSnapshotError(
                        "Das Jahresmanifest fehlt im Belegpaket."
                    )
                manifest_bytes = package.read(manifest_path)
                manifest = json.loads(manifest_bytes.decode("utf-8"))
                if not isinstance(manifest, dict):
                    raise TaxFilingSnapshotError(
                        "Das Jahresmanifest muss ein JSON-Objekt sein."
                    )
                if int(manifest.get("year", -1)) != year:
                    raise TaxFilingSnapshotError(
                        "Das Manifest gehoert zu einem anderen Steuerjahr."
                    )
                try:
                    self._parse_datetime(str(manifest["generated_at"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise TaxFilingSnapshotError(
                        "Das Manifest enthaelt keinen gueltigen generated_at-Zeitpunkt."
                    ) from exc
                summary_path = (
                    f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json"
                )
                if summary_path not in names:
                    raise TaxFilingSnapshotError(
                        "Die jahresbezogene Filing-Summary fehlt im Belegpaket."
                    )
                summary = json.loads(package.read(summary_path).decode("utf-8"))
                if not isinstance(summary, dict):
                    raise TaxFilingSnapshotError(
                        "Die Filing-Summary muss ein JSON-Objekt sein."
                    )
                if int(summary.get("year", -1)) != year:
                    raise TaxFilingSnapshotError(
                        "Die Filing-Summary gehoert zu einem anderen Steuerjahr."
                    )
                files: list[TaxFilingSnapshotFile] = []
                manifest_files = manifest.get("files")
                if not isinstance(manifest_files, list) or not manifest_files:
                    raise TaxFilingSnapshotError(
                        "Das Jahresmanifest enthaelt keine manifestierten Dateien."
                    )
                for item in manifest_files:
                    if not isinstance(item, dict):
                        raise TaxFilingSnapshotError(
                            "Ein Dateieintrag im Jahresmanifest ist ungueltig."
                        )
                    path = str(item.get("path", ""))
                    if not path or path not in names:
                        raise TaxFilingSnapshotError(
                            f"Manifestierte Datei fehlt: {path or '<leer>'}"
                        )
                    content = package.read(path)
                    digest = hashlib.sha256(content).hexdigest()
                    if digest != str(item.get("sha256", "")):
                        raise TaxFilingSnapshotError(
                            f"Dateihash stimmt nicht: {path}"
                        )
                    if len(content) != int(item.get("size_bytes", -1)):
                        raise TaxFilingSnapshotError(
                            f"Dateigroesse stimmt nicht: {path}"
                        )
                    files.append(
                        TaxFilingSnapshotFile(
                            path=path,
                            size_bytes=len(content),
                            sha256=digest,
                            source_endpoint=item.get("source_endpoint"),
                        )
                    )
        except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaxFilingSnapshotError(
                "Das Belegpaket ist kein gueltiges Steuerreport-Jahres-ZIP."
            ) from exc

        return {
            "manifest": manifest,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "summary": summary,
            "values": self._values_from_mapping(summary),
            "files": files,
        }

    def _find_duplicate(
        self,
        *,
        year: int,
        package_sha256: str,
        state: str,
        filing_kind: str,
    ) -> TaxFilingSnapshot | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select snapshot_id
                from tax_filing_snapshots
                where year = ? and package_sha256 = ? and state = ? and filing_kind = ?
                order by revision desc
                limit 1
                """,
                [year, package_sha256, state, filing_kind],
            ).fetchone()
        return self.get(str(row[0])) if row else None

    def _archive_path(self, year: int, package_sha256: str) -> Path:
        return self.archive_root / str(year) / f"{package_sha256}.zip"

    def _write_archive_once(
        self,
        path: Path,
        content: bytes,
        expected_sha256: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
                raise TaxFilingSnapshotError(
                    "Vorhandenes Inhaltsarchiv hat einen abweichenden SHA-256."
                )
            return
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
            try:
                path.chmod(0o444)
            except OSError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink()

    def _path_for_snapshot(self, snapshot_id: str) -> Path:
        with self.store.connect() as con:
            row = con.execute(
                "select archive_relative_path from tax_filing_snapshots where snapshot_id = ?",
                [snapshot_id],
            ).fetchone()
        if not row:
            raise KeyError(snapshot_id)
        path = (self.store.path.parent / str(row[0])).resolve()
        root = self.store.path.parent.resolve()
        if not path.is_relative_to(root):
            raise TaxFilingSnapshotError("Ungueltiger Archivpfad im Register.")
        return path

    def _runtime_fingerprint(self) -> tuple[str, dict[str, object]]:
        with self.store.connect() as con:
            tax_run = con.execute(
                """
                select run_id, fifo_method, input_fingerprint_digest, created_at::varchar
                from tax_run_summaries order by created_at desc limit 1
                """
            ).fetchone()
            derivative_run = con.execute(
                """
                select run_id, derivative_lines_count, realized_pnl_eur::varchar,
                       missing_price_count, created_at::varchar
                from derivative_run_summaries order by created_at desc limit 1
                """
            ).fetchone()
            counts = {
                table: int(con.execute(f"select count(*) from {table}").fetchone()[0])
                for table in (
                    "raw_import_batches",
                    "raw_objects",
                    "canonical_events",
                    "price_ledger",
                    "tax_lots",
                    "tax_lines",
                    "review_decisions",
                )
            }
        payload = {
            "database_name": self.store.path.name,
            "tax_run": list(tax_run) if tax_run else None,
            "derivative_run": list(derivative_run) if derivative_run else None,
            "counts": counts,
        }
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest(), payload

    def _to_contract(
        self,
        row: dict[str, object],
        *,
        file_rows: list[dict[str, object]] | None = None,
        include_files: bool,
    ) -> TaxFilingSnapshot:
        path = (self.store.path.parent / str(row["archive_relative_path"])).resolve()
        integrity = "missing"
        if path.is_file():
            try:
                integrity = (
                    "verified"
                    if hashlib.sha256(path.read_bytes()).hexdigest()
                    == str(row["package_sha256"])
                    else "mismatch"
                )
            except OSError:
                integrity = "missing"
        values = self._values_from_mapping(json.loads(str(row["summary_json"])))
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
        package_generated_at = self._iso(row["package_generated_at"])
        created_at = self._iso(row["created_at"])
        files = [
            TaxFilingSnapshotFile(
                path=str(item["path"]),
                size_bytes=int(item["size_bytes"]),
                sha256=str(item["sha256"]),
                source_endpoint=(
                    str(item["source_endpoint"])
                    if item.get("source_endpoint") is not None
                    else None
                ),
            )
            for item in (file_rows or [])
        ]
        files_count = len(files)
        if not include_files:
            with self.store.connect() as con:
                files_count = int(
                    con.execute(
                        "select count(*) from tax_filing_snapshot_files where snapshot_id = ?",
                        [str(row["snapshot_id"])],
                    ).fetchone()[0]
                )
        usage_confirmation = self._usage_confirmation(str(row["snapshot_id"]))
        usage_payload = (
            json.loads(str(usage_confirmation["payload_json"]))
            if usage_confirmation is not None
            else {}
        )
        return TaxFilingSnapshot(
            snapshot_id=str(row["snapshot_id"]),
            year=int(row["year"]),
            revision=int(row["revision"]),
            state=str(row["state"]),
            filing_kind=str(row["filing_kind"]),
            source_kind=str(row["source_kind"]),
            source_snapshot_id=(
                str(row["source_snapshot_id"])
                if row.get("source_snapshot_id") is not None
                else None
            ),
            package_filename=str(row["package_filename"]),
            package_sha256=str(row["package_sha256"]),
            package_size_bytes=int(row["package_size_bytes"]),
            manifest_sha256=str(row["manifest_sha256"]),
            runtime_fingerprint_sha256=str(row["runtime_fingerprint_sha256"]),
            package_generated_at=package_generated_at,
            package_generated_at_europe_berlin=self._berlin_iso(package_generated_at),
            created_at=created_at,
            created_at_europe_berlin=self._berlin_iso(created_at),
            software_version=str(
                metadata.get("software_version") or "unknown_at_capture"
            ),
            method_version=str(metadata.get("method_version") or "unknown_at_capture"),
            database_fingerprint_sha256=str(
                metadata.get("database_fingerprint_sha256")
                or row["runtime_fingerprint_sha256"]
            ),
            submitted_at=(
                self._iso(row["submitted_at"])
                if row.get("submitted_at") is not None
                else None
            ),
            filing_usage_confirmed=usage_confirmation is not None,
            filing_usage_confirmed_at=(
                self._iso(usage_confirmation["created_at"])
                if usage_confirmation is not None
                else None
            ),
            filing_usage_confirmation_actor=(
                str(usage_payload.get("actor"))
                if usage_payload.get("actor") is not None
                else None
            ),
            filing_usage_confirmation_source=(
                str(usage_payload.get("source"))
                if usage_payload.get("source") is not None
                else None
            ),
            filing_usage_confirmation_statement=(
                str(usage_payload.get("statement"))
                if usage_payload.get("statement") is not None
                else None
            ),
            note=str(row["note"]) if row.get("note") is not None else None,
            integrity_status=integrity,
            values=values,
            files_count=files_count,
            files=files,
            package_download_endpoint=(
                "/api/v1/tax-filing-snapshots/"
                f"{row['snapshot_id']}/package.zip"
            ),
        )

    def _usage_confirmation(self, snapshot_id: str) -> dict[str, object] | None:
        with self.store.connect() as con:
            rows = self._fetch_dicts(
                con,
                """
                select event_id, payload_json, created_at
                from tax_filing_snapshot_events
                where snapshot_id = ?
                  and event_type = 'filing_package_usage_confirmed'
                order by created_at, event_id
                limit 1
                """,
                [snapshot_id],
            )
        return rows[0] if rows else None

    def _deltas(
        self,
        filed: TaxFilingValues,
        current: TaxFilingValues,
    ) -> list[TaxFilingSnapshotDelta]:
        definitions = (
            (
                "taxable_private_disposals_eur",
                "Private Veraeusserungen (§ 23 EStG)",
                "declaration",
            ),
            (
                "rewards_mining_staking_income_eur",
                "Rewards / Mining / Staking",
                "declaration",
            ),
            ("derivative_pnl_eur", "Derivate / Termingeschaefte", "declaration"),
            ("taxable_disposal_proceeds_eur", "Veraeusserungserloese", "supporting"),
            ("acquisition_cost_eur", "Zugeordnete Anschaffungskosten", "supporting"),
            (
                "tax_free_private_disposals_eur",
                "Veraeusserungen ausserhalb der Jahresfrist",
                "informational",
            ),
        )
        rows: list[TaxFilingSnapshotDelta] = []
        for key, label, category in definitions:
            filed_value = Decimal(getattr(filed, key))
            current_value = Decimal(getattr(current, key))
            delta = current_value - filed_value
            changed_at_cent = self._cents(delta) != Decimal("0.00")
            direction = "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
            requires_review = bool(category == "declaration" and changed_at_cent)
            if direction == "unchanged":
                explanation = "Keine Abweichung."
            elif category == "declaration":
                explanation = (
                    "Eintragungsrelevanter Betrag ist heute hoeher; Einkunftsart getrennt pruefen."
                    if delta > 0
                    else "Eintragungsrelevanter Betrag ist heute niedriger; Einkunftsart getrennt pruefen."
                )
            elif category == "supporting":
                explanation = "Nachweisgrundlage der Ergebnisberechnung hat sich geaendert."
            else:
                explanation = "Nachrichtlicher steuerfreier Betrag hat sich geaendert."
            rows.append(
                TaxFilingSnapshotDelta(
                    key=key,
                    label=label,
                    category=category,
                    filed_value_eur=filed_value,
                    current_value_eur=current_value,
                    delta_eur=delta,
                    direction=direction,
                    changed_at_cent_precision=changed_at_cent,
                    requires_review=requires_review,
                    explanation=explanation,
                )
            )
        return rows

    @staticmethod
    def _values_from_summary(summary: TaxYearFilingSummary) -> TaxFilingValues:
        return TaxFilingValues(
            generated_at=summary.generated_at,
            export_ready=summary.export_ready,
            taxable_private_disposals_eur=summary.taxable_private_disposals_eur,
            taxable_disposal_proceeds_eur=summary.taxable_disposal_proceeds_eur,
            acquisition_cost_eur=summary.acquisition_cost_eur,
            rewards_mining_staking_income_eur=(
                summary.rewards_mining_staking_income_eur
            ),
            derivative_pnl_eur=summary.derivative_pnl_eur,
            tax_free_private_disposals_eur=(
                summary.tax_free_private_disposals_eur
            ),
            tax_free_lines_count=summary.tax_free_lines_count,
        )

    @staticmethod
    def _values_from_mapping(payload: dict[str, object]) -> TaxFilingValues:
        return TaxFilingValues(
            generated_at=str(payload.get("generated_at") or ""),
            export_ready=bool(payload.get("export_ready", False)),
            taxable_private_disposals_eur=Decimal(
                str(payload.get("taxable_private_disposals_eur", "0"))
            ),
            taxable_disposal_proceeds_eur=Decimal(
                str(payload.get("taxable_disposal_proceeds_eur", "0"))
            ),
            acquisition_cost_eur=Decimal(
                str(payload.get("acquisition_cost_eur", "0"))
            ),
            rewards_mining_staking_income_eur=Decimal(
                str(payload.get("rewards_mining_staking_income_eur", "0"))
            ),
            derivative_pnl_eur=Decimal(
                str(payload.get("derivative_pnl_eur", "0"))
            ),
            tax_free_private_disposals_eur=Decimal(
                str(payload.get("tax_free_private_disposals_eur", "0"))
            ),
            tax_free_lines_count=int(payload.get("tax_free_lines_count", 0)),
        )

    @staticmethod
    def _fetch_dicts(con, sql: str, params: list[object]) -> list[dict[str, object]]:
        cursor = con.execute(sql, params)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _iso(value: object) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        return str(value)

    @staticmethod
    def _berlin_iso(value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = TaxFilingSnapshotService._parse_datetime(value)
            return parsed.astimezone(ZoneInfo("Europe/Berlin")).isoformat()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _cents(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
