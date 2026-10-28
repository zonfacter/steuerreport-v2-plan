from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4

from steuerreport_v2.contracts.exports import ExportPackage, ExportReadiness, ExportResult, PdfExportRequest
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.valuation import PriceCoverageReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.filing_binding import BINDING_VERSION, EXPORT_BINDING_PREFIX, current_filing_binding

MAX_PDF_PAGES_PER_FILE = 100


class ExportService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def create_pdf_packages(self, request: PdfExportRequest) -> ExportResult:
        with self.store.exclusive_access():
            return self._create_pdf_packages(request)

    def _create_pdf_packages(self, request: PdfExportRequest) -> ExportResult:
        readiness = self.readiness()
        if not readiness.allow_export:
            block_reason = (
                "review_gate_blocked"
                if readiness.review_blocking_issues_open > 0
                or readiness.review_issues_current_open > 0
                else "parity_release_blocked"
            )
            package = ExportPackage(
                package_id=str(uuid4()),
                kind="pdf",
                label=request.label,
                file_index=1,
                page_count=0,
                status="blocked",
                block_reason=block_reason,
                created_at=datetime.now(timezone.utc),
            )
            self._store_packages([package])
            return ExportResult(
                packages=[package],
                max_pages_per_file=MAX_PDF_PAGES_PER_FILE,
                blocked=True,
            )

        packages = self._split_pdf_packages(request)
        self._store_packages(packages)
        return ExportResult(
            packages=packages,
            max_pages_per_file=MAX_PDF_PAGES_PER_FILE,
            blocked=False,
        )

    def list_packages(self) -> list[ExportPackage]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    package_id, kind, label, file_index, page_count,
                    status, block_reason, created_at
                from export_packages
                order by created_at desc, file_index
                """
            ).fetchall()
        return [
            self._with_binding(ExportPackage(
                package_id=row[0],
                kind=row[1],
                label=row[2],
                file_index=row[3],
                page_count=row[4],
                status=row[5],
                block_reason=row[6],
                created_at=row[7],
            ))
            for row in rows
        ]

    def get_package(self, package_id: str) -> ExportPackage | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    package_id, kind, label, file_index, page_count,
                    status, block_reason, created_at
                from export_packages
                where package_id = ?
                """,
                [package_id],
            ).fetchone()
        if row is None:
            return None
        return self._with_binding(ExportPackage(
            package_id=row[0],
            kind=row[1],
            label=row[2],
            file_index=row[3],
            page_count=row[4],
            status=row[5],
            block_reason=row[6],
            created_at=row[7],
        ))

    def _with_binding(self, package: ExportPackage) -> ExportPackage:
        binding = self._package_binding(package.package_id)
        if binding and binding.get("binding_version") == BINDING_VERSION:
            return package.model_copy(update={"filing_status": "preview",
                "input_binding_sha256": binding.get("input_binding_sha256"),
                "calculation_run_id": binding.get("calculation_run_id")})
        return package

    def render_pdf_package(self, package_id: str) -> tuple[ExportPackage, bytes] | None:
        package = self.get_package(package_id)
        if package is None or package.status != "created":
            return None
        binding = self._package_binding(package_id)
        current, run_id = current_filing_binding(self.store)
        if (not binding or binding.get("binding_version") != BINDING_VERSION
                or binding.get("input_binding_sha256") != current
                or binding.get("calculation_run_id") != run_id):
            return None
        package = package.model_copy(update={"filing_status": "preview", "input_binding_sha256": current,
                                             "calculation_run_id": run_id})
        readiness = self.readiness()
        if not readiness.allow_export:
            return None
        lines = [
            "Steuerreport V2 Exportpaket",
            "VORSCHAU - KEINE FINALE JAHRESFREIGABE",
            f"Gebundener Berechnungslauf: {run_id or 'nicht vorhanden'}",
            "Daten-/Methodenbindung SHA-256:",
            current,
            f"Label: {package.label}",
            f"Paket-ID: {package.package_id}",
            f"Datei-Index: {package.file_index}",
            f"Seiten: {package.page_count}",
            f"Erstellt: {package.created_at.isoformat()}",
            "",
            "Technische Export-Freigabe (nur Vorschau)",
            f"Review aktuell offen: {readiness.review_issues_current_open}",
            f"Review historisch offen: {readiness.review_issues_historical_open}",
            f"Review gesamt sichtbar: {readiness.review_issues_open_total}",
            f"Review blockierend: {readiness.review_blocking_issues_open}",
            f"Review hoch offen: {readiness.review_issues_high_open}",
            f"V1/V2 Parity releasebereit: {_format_bool_de(readiness.parity_release_ready)}",
            f"V1/V2 Parity offen: {readiness.parity_unresolved_groups}",
            f"V1/V2 Parity blockierend: {readiness.parity_blocking_groups}",
            f"V1/V2 Parity akzeptiert: {readiness.parity_accepted_groups}",
            f"V1/V2 Parity Gruppen gesamt: {readiness.parity_groups_total}",
            f"V1/V2 Parity blockierende Differenz EUR: {readiness.parity_blocking_difference_eur}",
            f"FIFO Steuerzeilen: {readiness.tax_lines_count}",
            f"Derivate Zeilen: {readiness.derivative_lines_count}",
            f"Derivate Ergebnis EUR: {readiness.derivative_realized_pnl_eur}",
            f"Derivate fehlende Preise: {readiness.derivative_missing_price_count}",
            f"Nicht zugeordnete Abgaenge: {readiness.unmatched_disposals}",
            f"Max Seiten pro PDF: {readiness.max_pdf_pages_per_file}",
            "ELSTER: Vorbereitung ja, direkte ERiC-Uebertragung nein",
        ]
        content = _minimal_pdf(lines)
        if current_filing_binding(self.store) != (current, run_id):
            return None
        return package, content

    def _package_binding(self, package_id: str) -> dict | None:
        with self.store.connect() as con:
            row = con.execute("select value_json from admin_settings where key=?", [EXPORT_BINDING_PREFIX + package_id]).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def delete_package(self, package_id: str) -> bool:
        with self.store.connect() as con:
            existing = con.execute(
                "select 1 from export_packages where package_id = ?",
                [package_id],
            ).fetchone()
            if existing is None:
                return False
            con.execute("delete from export_packages where package_id = ?", [package_id])
            con.execute("delete from admin_settings where key = ?", [EXPORT_BINDING_PREFIX + package_id])
        return True

    def readiness(self, price_coverage: PriceCoverageReport | None = None) -> ExportReadiness:
        gate = ReviewService(self.store).gate(price_coverage=price_coverage)
        parity = V1ParityService(self.store).release_readiness()
        tax_summary = TaxService(self.store).latest_summary()
        derivative_summary = DerivativesManager(self.store).latest_summary()
        return ExportReadiness(
            allow_export=gate.allow_export and parity.release_ready,
            technical_export_allowed=gate.allow_export and parity.release_ready,
            final_filing_allowed=False,
            filing_status="technical_only" if gate.allow_export and parity.release_ready else "blocked",
            review_issues_open=gate.issues_open,
            review_issues_current_open=(
                gate.issues_current_open
                if gate.issues_current_open is not None
                else gate.issues_open
            ),
            review_issues_historical_open=gate.issues_historical_open,
            review_issues_open_total=(
                gate.issues_open_total
                if gate.issues_open_total is not None
                else gate.issues_open
            ),
            review_blocking_issues_open=gate.blocking_issues_open,
            review_issues_high_open=gate.issues_high_open,
            parity_release_ready=parity.release_ready,
            parity_unresolved_groups=parity.unresolved_groups,
            parity_blocking_groups=parity.blocking_groups,
            parity_blocking_difference_eur=str(parity.blocking_difference_eur),
            parity_accepted_groups=parity.accepted_groups,
            parity_groups_total=parity.groups_total,
            tax_lines_count=tax_summary.tax_lines_count if tax_summary is not None else 0,
            derivative_lines_count=(
                derivative_summary.derivative_lines_count
                if derivative_summary is not None
                else 0
            ),
            derivative_realized_pnl_eur=(
                str(derivative_summary.realized_pnl_eur)
                if derivative_summary is not None
                else "0"
            ),
            derivative_missing_price_count=(
                derivative_summary.missing_price_count
                if derivative_summary is not None
                else 0
            ),
            unmatched_disposals=tax_summary.unmatched_disposals if tax_summary is not None else 0,
            latest_tax_run_id=tax_summary.run_id if tax_summary is not None else None,
            latest_derivative_run_id=(
                derivative_summary.run_id if derivative_summary is not None else None
            ),
            max_pdf_pages_per_file=MAX_PDF_PAGES_PER_FILE,
        )

    def _split_pdf_packages(self, request: PdfExportRequest) -> list[ExportPackage]:
        if request.estimated_pages == 0:
            page_counts = [0]
        else:
            remaining = request.estimated_pages
            page_counts = []
            while remaining > 0:
                page_count = min(remaining, MAX_PDF_PAGES_PER_FILE)
                page_counts.append(page_count)
                remaining -= page_count

        created_at = datetime.now(timezone.utc)
        return [
            ExportPackage(
                package_id=str(uuid4()),
                kind="pdf",
                label=request.label,
                file_index=index,
                page_count=page_count,
                status="created",
                created_at=created_at,
            )
            for index, page_count in enumerate(page_counts, start=1)
        ]

    def _store_packages(self, packages: list[ExportPackage]) -> None:
        with self.store.connect() as con:
            for package in packages:
                con.execute(
                    """
                    insert into export_packages (
                        package_id, kind, label, file_index, page_count,
                        status, block_reason, created_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        package.package_id,
                        package.kind,
                        package.label,
                        package.file_index,
                        package.page_count,
                        package.status,
                        package.block_reason,
                        package.created_at,
                    ],
                )
        if any(package.status == "created" for package in packages):
            digest, run_id = current_filing_binding(self.store)
            settings = []
            for package in packages:
                if package.status != "created":
                    continue
                package.filing_status = "preview"
                package.input_binding_sha256 = digest
                package.calculation_run_id = run_id
                settings.append(AdminSettingWrite(key=EXPORT_BINDING_PREFIX + package.package_id,
                    value_json=json.dumps({"binding_version": BINDING_VERSION, "input_binding_sha256": digest,
                                           "calculation_run_id": run_id, "filing_status": "preview"})))
            self.store.write_admin_settings_batch(settings, [])


def _minimal_pdf(lines: list[str]) -> bytes:
    escaped_lines = [_escape_pdf_text(line) for line in lines]
    text_commands = ["BT", "/F1 12 Tf", "72 760 Td"]
    for index, line in enumerate(escaped_lines):
        if index > 0:
            text_commands.append("0 -18 Td")
        text_commands.append(f"({line}) Tj")
    text_commands.append("ET")
    stream = "\n".join(text_commands).encode("utf-8")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("ascii"))
        content.extend(obj)
        content.extend(b"\nendobj\n")
    xref_start = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(content)


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _format_bool_de(value: bool) -> str:
    return "ja" if value else "nein"
