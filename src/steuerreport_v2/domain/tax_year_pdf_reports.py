from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from steuerreport_v2.contracts.tax_year_pdf_reports import (
    TaxYearPdfReportArtifact,
    TaxYearPdfReportFile,
    TaxYearPdfReportList,
    TaxYearPdfReportManifest,
    TaxYearPdfReportSummary,
    TaxYearPdfTechnicalStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.filing_binding import current_filing_binding
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.domain.valuation import PriceCoverageService

MAX_PDF_PAGES_PER_FILE = 100
REPORT_SCHEMA = "tax_year_pdf_report_manifest_v1"
REPORT_RENDERER_VERSION = "tax_year_pdf_readmodel_renderer_v1"
ARCHIVE_DIRECTORY = "tax_year_report_archive"


class TaxYearPdfReportError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TaxYearPdfReportService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.archive_root = store.path.parent.resolve() / ARCHIVE_DIRECTORY

    def create(self, year: int) -> TaxYearPdfReportArtifact:
        self._validate_year(year)

        with self.store.exclusive_access():
            binding_before = current_filing_binding(self.store)
            calculation_run_id = binding_before[1]
            tax_service = TaxService(self.store)
            tax_run = tax_service.latest_summary()
            if not calculation_run_id or tax_run is None:
                raise TaxYearPdfReportError("tax_calculation_run_missing")
            if str(tax_run.run_id) != calculation_run_id:
                raise TaxYearPdfReportError("tax_calculation_run_binding_mismatch")

            year_service = TaxYearService(self.store)
            filing_summary = year_service.filing_summary(year)
            year_detail = year_service.detail(year)
            income_report = year_service.income_report(year)
            tax_lines = [
                line
                for line in tax_service.list_tax_lines()
                if reporting_tax_year(line.disposed_at) == year
            ]
            acquisition_event_by_lot = {
                lot.lot_id: lot.source_event_id
                for lot in tax_service.list_tax_lots()
            }
            if len(tax_lines) != year_detail.tax_lines_count:
                raise TaxYearPdfReportError("tax_line_read_model_count_mismatch")
            if len({line.tax_line_id for line in tax_lines}) != len(tax_lines):
                raise TaxYearPdfReportError("duplicate_tax_line_identity")
            if sum(item.events_count for item in income_report.assets) != income_report.events_count:
                raise TaxYearPdfReportError("income_read_model_count_mismatch")
            if len({(item.asset, item.event_type, item.classification) for item in income_report.assets}) != len(income_report.assets):
                raise TaxYearPdfReportError("duplicate_income_asset_identity")

            derivative_manager = DerivativesManager(self.store)
            derivative_summary = derivative_manager.latest_summary()
            derivative_lines = [
                line
                for line in derivative_manager.list_lines()
                if reporting_tax_year(line.event_time) == year
            ]
            if len(derivative_lines) != year_detail.derivative_lines_count:
                raise TaxYearPdfReportError("derivative_read_model_count_mismatch")
            if len({line.derivative_line_id for line in derivative_lines}) != len(derivative_lines):
                raise TaxYearPdfReportError("duplicate_derivative_line_identity")
            derivative_missing_price_count = sum(
                1 for line in derivative_lines if line.price_source is None
            )

            readiness = ExportService(self.store).readiness(
                price_coverage=PriceCoverageService(self.store).report()
            )
            created_at = datetime.now(timezone.utc)
            artifact_id = str(uuid4())
            pdf_bytes = _render_year_report_pdf(
                year=year,
                artifact_id=artifact_id,
                calculation_run_id=calculation_run_id,
                input_binding_sha256=binding_before[0],
                created_at=created_at,
                filing_summary=filing_summary,
                year_detail=year_detail,
                income_report=income_report,
                tax_lines=tax_lines,
                acquisition_event_by_lot=acquisition_event_by_lot,
                derivative_lines=derivative_lines,
                technical_status=TaxYearPdfTechnicalStatus(
                    status=(
                        "technical_only"
                        if readiness.technical_export_allowed
                        else "blocked"
                    ),
                    technical_export_allowed=readiness.technical_export_allowed,
                    review_issues_current_open=readiness.review_issues_current_open,
                    review_issues_historical_open=readiness.review_issues_historical_open,
                    review_blocking_issues_open=readiness.review_blocking_issues_open,
                    parity_release_ready=readiness.parity_release_ready,
                    parity_unresolved_groups=readiness.parity_unresolved_groups,
                    parity_blocking_groups=readiness.parity_blocking_groups,
                ),
            )
            pdf_parts = split_pdf_by_page_count(pdf_bytes)
            binding_after = current_filing_binding(self.store)
            if binding_after != binding_before:
                raise TaxYearPdfReportError(
                    "filing_inputs_changed_create_a_new_report"
                )

            file_models: list[TaxYearPdfReportFile] = []
            file_payloads: list[tuple[str, bytes]] = []
            for index, (part_bytes, page_count) in enumerate(pdf_parts, start=1):
                filename = f"steuerreport-jahresbericht-{year}-{artifact_id[:8]}-{index:03d}.pdf"
                file_models.append(
                    TaxYearPdfReportFile(
                        file_index=index,
                        filename=filename,
                        page_count=page_count,
                        size_bytes=len(part_bytes),
                        sha256=hashlib.sha256(part_bytes).hexdigest(),
                        download_endpoint=(
                            f"/api/v1/tax-years/{year}/reports/pdf/"
                            f"{artifact_id}/files/{index}"
                        ),
                    )
                )
                file_payloads.append((filename, part_bytes))

            derivative_run = derivative_summary.run_id if derivative_summary else None
            summary = TaxYearPdfReportSummary(
                taxable_private_disposals_eur=filing_summary.taxable_private_disposals_eur,
                taxable_disposal_proceeds_eur=filing_summary.taxable_disposal_proceeds_eur,
                acquisition_cost_eur=filing_summary.acquisition_cost_eur,
                rewards_mining_staking_income_eur=filing_summary.rewards_mining_staking_income_eur,
                derivative_pnl_eur=filing_summary.derivative_pnl_eur,
                tax_free_private_disposals_eur=filing_summary.tax_free_private_disposals_eur,
                tax_free_lines_count=filing_summary.tax_free_lines_count,
            )
            manifest_payload = {
                "manifest_schema": REPORT_SCHEMA,
                "artifact_id": artifact_id,
                "year": year,
                "created_at": created_at.isoformat(),
                "report_status": "preview",
                "final_filing_allowed": False,
                "calculation_run_id": calculation_run_id,
                "derivative_run_id": derivative_run,
                "fifo_method": tax_run.fifo_method,
                "input_binding_sha256": binding_before[0],
                "filing_summary_status": filing_summary.status_label,
                "filing_summary_export_ready": filing_summary.export_ready,
                "summary": summary.model_dump(mode="json"),
                "technical_status": pdf_technical_status(readiness).model_dump(mode="json"),
                "tax_line_count": len(tax_lines),
                "reward_asset_row_count": len(income_report.assets),
                "reward_missing_value_count": income_report.missing_value_count,
                "derivative_line_count": len(derivative_lines),
                "derivative_missing_price_count": derivative_missing_price_count,
                "unmatched_disposals": year_detail.unmatched_disposals,
                "missing_price_groups": year_detail.missing_price_groups,
                "sections": [
                    "filing_summary",
                    "tax_lines",
                    "reward_income_asset_breakdown",
                    "derivative_event_read_model",
                    "filing_checklist_and_review_decisions",
                    "technical_status_appendix",
                ],
                "source_read_models": [
                    "TaxYearService.filing_summary(year)",
                    "TaxYearService.detail(year)",
                    "TaxYearService.income_report(year).assets",
                    "TaxService.list_tax_lines() filtered with reporting_tax_year",
                    "TaxService.list_tax_lots() for acquisition-event provenance",
                    "DerivativesManager.list_lines() filtered with reporting_tax_year",
                    "ExportService.readiness(PriceCoverageService.report())",
                ],
                "methodology": (
                    f"{REPORT_RENDERER_VERSION}; Darstellung bestehender Read-Models, "
                    "keine eigenstaendige Steuerberechnung. "
                    + filing_summary.methodology
                ),
                "files": [item.model_dump(mode="json") for item in file_models],
            }
            manifest_payload["manifest_sha256"] = "0" * 64
            manifest = TaxYearPdfReportManifest.model_validate(manifest_payload)
            manifest_sha256 = _manifest_sha256(
                manifest.model_dump(mode="json", exclude={"manifest_sha256"})
            )
            manifest = manifest.model_copy(
                update={"manifest_sha256": manifest_sha256}
            )
            manifest_bytes = json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")

            archive_directory = self._archive_directory(year, artifact_id)
            self._write_archive_once(
                archive_directory,
                file_payloads=file_payloads,
                manifest_bytes=manifest_bytes,
            )
            relative_path = archive_directory.relative_to(
                self.store.path.parent.resolve()
            ).as_posix()
            with self.store.connect() as con:
                con.execute(
                    """
                    insert into tax_year_report_pdf_artifacts (
                        artifact_id, year, created_at, calculation_run_id,
                        input_binding_sha256, manifest_sha256,
                        archive_relative_path, manifest_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        artifact_id,
                        year,
                        created_at.replace(tzinfo=None),
                        calculation_run_id,
                        binding_before[0],
                        manifest_sha256,
                        relative_path,
                        manifest_bytes.decode("utf-8"),
                    ],
                )
            return TaxYearPdfReportArtifact(
                manifest=manifest,
                manifest_endpoint=(
                    f"/api/v1/tax-years/{year}/reports/pdf/"
                    f"{artifact_id}/manifest.json"
                ),
            )

    def list(self, year: int) -> TaxYearPdfReportList:
        self._validate_year(year)
        with self.store.connect() as con:
            rows = con.execute(
                """
                select artifact_id, year, manifest_sha256,
                       archive_relative_path, manifest_json
                from tax_year_report_pdf_artifacts
                where year = ?
                order by created_at desc, artifact_id desc
                """,
                [year],
            ).fetchall()
        artifacts = [
            self._artifact_from_row(row)
            for row in rows
        ]
        return TaxYearPdfReportList(
            generated_at=datetime.now(timezone.utc), year=year, artifacts=artifacts
        )

    def get(self, year: int, artifact_id: str) -> TaxYearPdfReportArtifact | None:
        row = self._row(year, artifact_id)
        return self._artifact_from_row(row) if row else None

    def get_manifest_bytes(self, year: int, artifact_id: str) -> tuple[str, bytes] | None:
        row = self._row(year, artifact_id)
        if row is None:
            return None
        self._artifact_from_row(row)
        relative_path = self._safe_archive_relative_path(row[3])
        manifest_path = relative_path / "manifest.json"
        if manifest_path.is_symlink():
            raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid")
        try:
            content = manifest_path.read_bytes()
        except OSError as exc:
            raise TaxYearPdfReportError("tax_year_pdf_manifest_unavailable") from exc
        if content != row[4].encode("utf-8"):
            raise TaxYearPdfReportError("tax_year_pdf_manifest_integrity_failed")
        return f"steuerreport-jahresbericht-{year}-{artifact_id[:8]}-manifest.json", content

    def get_pdf_bytes(
        self, year: int, artifact_id: str, file_index: int
    ) -> tuple[TaxYearPdfReportFile, bytes] | None:
        row = self._row(year, artifact_id)
        if row is None:
            return None
        artifact = self._artifact_from_row(row)
        file_model = next(
            (item for item in artifact.manifest.files if item.file_index == file_index),
            None,
        )
        if file_model is None:
            return None
        archive_directory = self._safe_archive_relative_path(row[3])
        file_path = archive_directory / file_model.filename
        if file_path.is_symlink():
            raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid")
        try:
            content = file_path.read_bytes()
        except OSError as exc:
            raise TaxYearPdfReportError("tax_year_pdf_file_unavailable") from exc
        if (
            len(content) != file_model.size_bytes
            or hashlib.sha256(content).hexdigest() != file_model.sha256
        ):
            raise TaxYearPdfReportError("tax_year_pdf_file_integrity_failed")
        try:
            actual_pages = len(PdfReader(io.BytesIO(content), strict=True).pages)
        except Exception as exc:
            raise TaxYearPdfReportError("tax_year_pdf_file_invalid") from exc
        if actual_pages != file_model.page_count or actual_pages > MAX_PDF_PAGES_PER_FILE:
            raise TaxYearPdfReportError("tax_year_pdf_page_count_mismatch")
        return file_model, content

    def _row(self, year: int, artifact_id: str):
        self._validate_year(year)
        with self.store.connect() as con:
            return con.execute(
                """
                select artifact_id, year, manifest_sha256,
                       archive_relative_path, manifest_json
                from tax_year_report_pdf_artifacts
                where year = ? and artifact_id = ?
                """,
                [year, artifact_id],
            ).fetchone()

    def _artifact_from_row(self, row) -> TaxYearPdfReportArtifact:
        try:
            payload = json.loads(row[4])
            manifest = TaxYearPdfReportManifest.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise TaxYearPdfReportError("tax_year_pdf_manifest_invalid") from exc
        if (
            manifest.artifact_id != row[0]
            or manifest.year != row[1]
            or manifest.manifest_sha256 != row[2]
            or _manifest_sha256(
                manifest.model_dump(mode="json", exclude={"manifest_sha256"})
            )
            != row[2]
        ):
            raise TaxYearPdfReportError("tax_year_pdf_manifest_integrity_failed")
        self._safe_archive_relative_path(row[3])
        return TaxYearPdfReportArtifact(
            manifest=manifest,
            manifest_endpoint=(
                f"/api/v1/tax-years/{row[1]}/reports/pdf/"
                f"{row[0]}/manifest.json"
            ),
        )

    def _archive_directory(self, year: int, artifact_id: str) -> Path:
        return self.archive_root / str(year) / artifact_id

    @staticmethod
    def _validate_year(year: int) -> None:
        if year < 2000 or year > 2100:
            raise TaxYearPdfReportError("tax_year_out_of_range")

    def _safe_archive_relative_path(self, relative_path: str) -> Path:
        posix_path = PurePosixPath(relative_path)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid")
        base = self.store.path.parent.resolve()
        candidate = base
        for part in posix_path.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.archive_root.resolve())
        except ValueError as exc:
            raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid") from exc
        return resolved

    def _write_archive_once(
        self,
        archive_directory: Path,
        *,
        file_payloads: list[tuple[str, bytes]],
        manifest_bytes: bytes,
    ) -> None:
        if self.archive_root.is_symlink():
            raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid")
        year_directory = archive_directory.parent
        year_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if year_directory.is_symlink():
            raise TaxYearPdfReportError("tax_year_pdf_archive_path_invalid")
        archive_directory.mkdir(mode=0o700, exist_ok=False)
        try:
            for filename, content in file_payloads:
                if Path(filename).name != filename:
                    raise TaxYearPdfReportError("tax_year_pdf_filename_invalid")
                _write_once(archive_directory / filename, content)
            _write_once(archive_directory / "manifest.json", manifest_bytes)
            _fsync_directory(archive_directory)
            _fsync_directory(year_directory)
        except Exception:
            # Keep any partially written artifact for forensic recovery; IDs and paths are never reused.
            raise


def pdf_technical_status(readiness) -> TaxYearPdfTechnicalStatus:
    return TaxYearPdfTechnicalStatus(
        status=("technical_only" if readiness.technical_export_allowed else "blocked"),
        technical_export_allowed=readiness.technical_export_allowed,
        review_issues_current_open=readiness.review_issues_current_open,
        review_issues_historical_open=readiness.review_issues_historical_open,
        review_blocking_issues_open=readiness.review_blocking_issues_open,
        parity_release_ready=readiness.parity_release_ready,
        parity_unresolved_groups=readiness.parity_unresolved_groups,
        parity_blocking_groups=readiness.parity_blocking_groups,
    )


def split_pdf_by_page_count(content: bytes) -> list[tuple[bytes, int]]:
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        page_count = len(reader.pages)
    except Exception as exc:
        raise TaxYearPdfReportError("tax_year_pdf_render_invalid") from exc
    if page_count < 1:
        raise TaxYearPdfReportError("tax_year_pdf_render_empty")
    parts: list[tuple[bytes, int]] = []
    for start in range(0, page_count, MAX_PDF_PAGES_PER_FILE):
        end = min(start + MAX_PDF_PAGES_PER_FILE, page_count)
        writer = PdfWriter()
        for page_number in range(start, end):
            writer.add_page(reader.pages[page_number])
        output = io.BytesIO()
        writer.write(output)
        part = output.getvalue()
        actual_part_pages = len(PdfReader(io.BytesIO(part), strict=True).pages)
        if actual_part_pages != end - start or actual_part_pages > MAX_PDF_PAGES_PER_FILE:
            raise TaxYearPdfReportError("tax_year_pdf_page_split_invalid")
        parts.append((part, actual_part_pages))
    return parts


def _render_year_report_pdf(
    *,
    year: int,
    artifact_id: str,
    calculation_run_id: str,
    input_binding_sha256: str,
    created_at: datetime,
    filing_summary,
    year_detail,
    income_report,
    tax_lines,
    acquisition_event_by_lot,
    derivative_lines,
    technical_status: TaxYearPdfTechnicalStatus,
) -> bytes:
    output = io.BytesIO()
    page_size = landscape(A4)
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TaxBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TaxTable",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=6,
            leading=7,
            wordWrap="CJK",
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TaxTableHeader",
            parent=styles["TaxTable"],
            fontName="Helvetica-Bold",
            textColor=colors.white,
        )
    )
    story = [
        Paragraph(f"Steuerreport – Jahresbericht {year}", styles["Title"]),
        Paragraph(
            "VORSCHAU – NICHT FINAL FREIGEGEBEN. Dieser Bericht bildet vorhandene "
            "Jahres-Read-Models ab und trifft keine steuerliche Freigabeentscheidung.",
            styles["Heading3"],
        ),
        Paragraph(
            f"Berichts-ID: {escape(artifact_id)}<br/>"
            f"Berechnungslauf: {escape(calculation_run_id)}<br/>"
            f"Eingabebindung SHA-256: {escape(input_binding_sha256)}<br/>"
            f"Erstellt (UTC): {escape(created_at.isoformat())}<br/>"
            f"Jahresstatus laut Filing-Read-Model: {escape(filing_summary.status_label)}",
            styles["TaxBody"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("Jahreszusammenfassung", styles["Heading2"]),
        Paragraph(escape(filing_summary.plain_language_summary), styles["TaxBody"]),
    ]
    summary_rows = [
        ["Read-Model-Kennzahl", "Wert"],
        ["Private Veräußerungen laut Filing-Read-Model", _decimal_text(filing_summary.taxable_private_disposals_eur) + " EUR"],
        ["Veräußerungserlöse", _decimal_text(filing_summary.taxable_disposal_proceeds_eur) + " EUR"],
        ["Anschaffungskosten", _decimal_text(filing_summary.acquisition_cost_eur) + " EUR"],
        ["Rewards / Mining / Staking", _decimal_text(filing_summary.rewards_mining_staking_income_eur) + " EUR"],
        ["Derivate-Ergebnis laut Jahres-Read-Model", _decimal_text(filing_summary.derivative_pnl_eur) + " EUR"],
        ["Steuerfreie private Veräußerungen", _decimal_text(filing_summary.tax_free_private_disposals_eur) + " EUR"],
        ["Steuerfreie FIFO-Zeilen", str(filing_summary.tax_free_lines_count)],
        ["Offene Veräußerungszuordnungen", str(year_detail.unmatched_disposals)],
        ["Fehlende Preisgruppen", str(year_detail.missing_price_groups)],
        ["Reward-/Income-Events ohne Wert", str(income_report.missing_value_count)],
        ["Derivate-Zeilen ohne Preis", str(sum(1 for line in derivative_lines if line.price_source is None))],
    ]
    story.append(_summary_table(summary_rows, styles))
    if filing_summary.lines:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Vorhandene Filing-Zeilen", styles["Heading3"]))
        filing_rows = [[_para(value, styles, header=True) for value in (
            "Thema", "Betrag EUR", "Behandlung", "Deklarationsziel", "Hinweis"
        )]]
        for item in filing_summary.lines:
            filing_rows.append(
                [
                    _para(item.label, styles),
                    _para(_decimal_text(item.amount_eur) if item.amount_eur is not None else "keine Wertbasis", styles),
                    _para(item.tax_treatment, styles),
                    _para(item.declaration_target, styles),
                    _para(item.note, styles),
                ]
            )
        story.append(_long_table(filing_rows, [90, 65, 115, 190, 210]))
    if filing_summary.warnings:
        story.append(Paragraph("Offene Hinweise im Jahres-Read-Model", styles["Heading3"]))
        story.extend(Paragraph("- " + escape(item), styles["TaxBody"]) for item in filing_summary.warnings)

    story.extend(
        [
            Spacer(1, 3 * mm),
            Paragraph(f"FIFO-Veräußerungspositionen ({len(tax_lines)})", styles["Heading2"]),
            Paragraph(
                "Die Zeilen entsprechen dem bestehenden TaxLine-Read-Model; "
                "diese PDF führt keine eigene FIFO- oder Steuerberechnung aus.",
                styles["TaxBody"],
            ),
        ]
    )
    tax_headers = [
        "Tax-Line-ID", "Verkauf", "Asset", "Menge", "Anschaffung EUR",
        "Erlös EUR", "Ergebnis EUR", "Haltetage", "FIFO-Lot",
        "Verkaufsereignis", "Anschaffungsereignis",
    ]
    tax_rows = [[_para(item, styles, header=True) for item in tax_headers]]
    for line in tax_lines:
        tax_rows.append(
            [
                _para(line.tax_line_id, styles),
                _para(line.disposed_at.isoformat(), styles),
                _para(line.asset, styles),
                _para(_decimal_text(line.quantity), styles),
                _para(_decimal_text(line.acquisition_cost_eur), styles),
                _para(_decimal_text(line.disposal_proceeds_eur), styles),
                _para(_decimal_text(line.gain_loss_eur), styles),
                _para(str(line.holding_days), styles),
                _para(line.lot_id, styles),
                _para(line.source_event_id, styles),
                _para(
                    line.acquisition_source_event_id
                    or acquisition_event_by_lot.get(line.lot_id)
                    or "nicht verfügbar",
                    styles,
                ),
            ]
        )
    story.append(
        _long_table(
            tax_rows,
            [78, 53, 30, 56, 61, 56, 56, 35, 72, 82, 82],
        )
        if tax_lines
        else Paragraph("Keine FIFO-Veräußerungspositionen im Jahres-Read-Model.", styles["TaxBody"])
    )

    story.extend(
        [
            PageBreak(),
            Paragraph("Rewards, Mining und Staking", styles["Heading2"]),
            Paragraph(
                "Jahresaggregate aus TaxYearService.income_report(year).assets; "
                "fehlende Bewertungen bleiben als solche ausgewiesen.",
                styles["TaxBody"],
            ),
        ]
    )
    income_rows = [[_para(value, styles, header=True) for value in (
        "Asset", "Ereignistyp", "Klassifizierung", "Ereignisse", "Menge", "EUR-Wert", "Fehlende Werte", "Quellen"
    )]]
    for item in income_report.assets:
        income_rows.append(
            [
                _para(item.asset, styles),
                _para(item.event_type, styles),
                _para(item.classification, styles),
                _para(str(item.events_count), styles),
                _para(_decimal_text(item.quantity), styles),
                _para(
                    (
                        f"{_decimal_text(item.income_eur)} (Teilwert; unvollständig)"
                        if item.missing_value_count
                        else _decimal_text(item.income_eur)
                    ),
                    styles,
                ),
                _para(str(item.missing_value_count), styles),
                _para(", ".join(item.sources), styles),
            ]
        )
    story.append(
        _long_table(income_rows, [57, 60, 125, 45, 70, 68, 53, 150])
        if income_report.assets
        else Paragraph("Keine Reward-/Income-Assetzeilen im Jahres-Read-Model.", styles["TaxBody"])
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Derivate-Ereignisse ({len(derivative_lines)})", styles["Heading2"]))
    story.append(
        Paragraph(
            "Die Detailzeilen zeigen die vorhandenen Bewertungswerte; ein "
            "positionsweiser Gewinn/Verlust wird hier nicht neu abgeleitet. "
            "Der Jahresbetrag oben stammt unverändert aus dem Filing-Read-Model.",
            styles["TaxBody"],
        )
    )
    derivative_rows = [[_para(value, styles, header=True) for value in (
        "Zeit", "Zeilen-ID", "Ereignis-ID", "Quelle / Konto", "Asset", "Menge", "Preis EUR", "Wert EUR", "Preisquelle"
    )]]
    for line in derivative_lines:
        derivative_rows.append(
            [
                _para(line.event_time.isoformat(), styles),
                _para(line.derivative_line_id, styles),
                _para(line.event_id, styles),
                _para(" / ".join(item for item in (line.source, line.account) if item), styles),
                _para(line.asset, styles),
                _para(_decimal_text(line.quantity), styles),
                _para(_decimal_text(line.price_eur) if line.price_source else "keine Bewertung", styles),
                _para(_decimal_text(line.value_eur) if line.price_source else "keine Bewertung", styles),
                _para(line.price_source or "nicht verfügbar", styles),
            ]
        )
    story.append(
        _long_table(derivative_rows, [82, 82, 82, 92, 45, 70, 65, 65, 90])
        if derivative_lines
        else Paragraph("Keine Derivate-Zeilen im Jahres-Read-Model.", styles["TaxBody"])
    )

    story.extend([PageBreak(), Paragraph("Einreichungs-Checkliste und Review", styles["Heading2"])])
    checklist_rows = [[_para(value, styles, header=True) for value in (
        "Nr.", "Kategorie", "Aufgabe", "Aktion", "Quelle", "Betrag EUR", "Erledigt, wenn"
    )]]
    for item in filing_summary.checklist:
        checklist_rows.append(
            [
                _para(str(item.order), styles),
                _para(item.category, styles),
                _para(item.label, styles),
                _para(item.action, styles),
                _para(item.source_topic, styles),
                _para(_decimal_text(item.amount_eur) if item.amount_eur is not None else "–", styles),
                _para(item.done_when, styles),
            ]
        )
    story.append(
        _long_table(checklist_rows, [24, 52, 130, 145, 68, 62, 175])
        if filing_summary.checklist
        else Paragraph("Keine Checklistenzeilen im Jahres-Read-Model.", styles["TaxBody"])
    )
    if filing_summary.review_decisions:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Vorhandene Review-Entscheidungen", styles["Heading3"]))
        decision_rows = [[_para(value, styles, header=True) for value in (
            "Entscheidungs-ID", "Typ / Geltungsbereich", "Titel", "Wirkungszusammenfassung", "Belegreferenz"
        )]]
        for item in filing_summary.review_decisions:
            decision_rows.append(
                [
                    _para(item.decision_id, styles),
                    _para(f"{item.decision_type} / {item.scope}", styles),
                    _para(item.title, styles),
                    _para(item.effect_summary, styles),
                    _para(item.evidence_ref or "–", styles),
                ]
            )
        story.append(_long_table(decision_rows, [80, 90, 130, 225, 110]))

    story.extend(
        [
            PageBreak(),
            Paragraph("Technischer Prüfstatus – getrennt vom Jahresergebnis", styles["Heading2"]),
            Paragraph(
                "Dieser Abschnitt beschreibt ausschließlich technische Export-/Review-Gates. "
                "Er ist weder eine Steuerberechnung noch eine steuerliche oder menschliche Freigabe.",
                styles["TaxBody"],
            ),
        ]
    )
    status_rows = [
        ["Technische Exportfreigabe", "Erlaubt" if technical_status.technical_export_allowed else "Blockiert"],
        ["Finale Jahresfreigabe", "Nicht erteilt"],
        ["Aktuell offene Review-Hinweise", str(technical_status.review_issues_current_open)],
        ["Historisch offene Review-Hinweise", str(technical_status.review_issues_historical_open)],
        ["Blockierende Review-Hinweise", str(technical_status.review_blocking_issues_open)],
        ["V1/V2 Paritätsstatus", "bereit" if technical_status.parity_release_ready else "offen"],
        ["Offene Paritätsgruppen", str(technical_status.parity_unresolved_groups)],
        ["Blockierende Paritätsgruppen", str(technical_status.parity_blocking_groups)],
    ]
    story.append(_summary_table([["Technischer Prüfpunkt", "Status"], *status_rows], styles))
    story.extend(
        [
            Spacer(1, 5 * mm),
            Paragraph("Methodik und Herkunft", styles["Heading2"]),
            Paragraph(
                "Der Bericht gibt bestehende Filing-, Jahres-, FIFO-, Income- und "
                "Derivate-Read-Models wieder. Er berechnet keine Steuerwerte selbst, "
                "setzt keine offene Review-Entscheidung um und bestätigt keine Abgabe.",
                styles["TaxBody"],
            ),
            Paragraph(escape(filing_summary.methodology), styles["TaxBody"]),
            Paragraph(f"Jahresstatus: {escape(year_detail.state)}; {escape(year_detail.label)}", styles["TaxBody"]),
        ]
    )

    def draw_page(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColor(colors.HexColor("#9b1c1c"))
        canvas.drawString(24 * mm, page_size[1] - 10 * mm, "VORSCHAU – NICHT FINAL FREIGEGEBEN")
        canvas.setFillColor(colors.HexColor("#444444"))
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(page_size[0] - 24 * mm, 10 * mm, f"Seite {document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        output,
        pagesize=page_size,
        rightMargin=24 * mm,
        leftMargin=24 * mm,
        topMargin=16 * mm,
        bottomMargin=17 * mm,
        title=f"Steuerreport Jahresbericht {year} – Vorschau",
        author="Steuerreport V2",
        subject=f"Jahresbezogene Vorschau; Lauf {calculation_run_id}; ID {artifact_id}",
    )
    document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return output.getvalue()


def _summary_table(rows, styles) -> Table:
    table_rows = [
        [_para(str(cell), styles, header=index == 0) for cell in row]
        for index, row in enumerate(rows)
    ]
    table = Table(table_rows, colWidths=[120 * mm, 120 * mm], repeatRows=1)
    table.setStyle(_table_style())
    return table


def _long_table(rows, col_widths) -> LongTable:
    table = LongTable(
        rows,
        colWidths=col_widths,
        repeatRows=1,
        splitByRow=1,
        hAlign="LEFT",
    )
    table.setStyle(_table_style())
    return table


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#30485a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b7c1c8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f3f5")]),
        ]
    )


def _para(value: str, styles, *, header: bool = False) -> Paragraph:
    style = styles["TaxTableHeader"] if header else styles["TaxTable"]
    return Paragraph(escape(str(value)), style)


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return "–"
    return format(value, "f")


def _manifest_sha256(payload: dict) -> str:
    core = dict(payload)
    core.pop("manifest_sha256", None)
    canonical = json.dumps(
        core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_once(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
