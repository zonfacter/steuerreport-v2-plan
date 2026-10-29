from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import hashlib
import json
import re

from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.pdfgen import canvas
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.parity import V1ReferenceMetricCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_year_pdf_reports import (
    MAX_PDF_PAGES_PER_FILE,
    TaxYearPdfReportError,
    TaxYearPdfReportService,
    split_pdf_by_page_count,
)
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def _store_with_two_years(path, *, year_2024_lines: int = 128) -> DuckDbStore:
    store = DuckDbStore(path / "steuerreport_v2.duckdb")
    rows = ["time,asset,amount,type,quote_asset,quote_quantity"]
    rows.extend(
        [
            "2023-01-01T00:00:00Z,BTC,1,buy,EUR,100",
            "2023-01-02T00:00:00Z,BTC,-1,sell,EUR,150",
        ]
    )
    first_day = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(year_2024_lines):
        acquired = first_day + timedelta(days=index * 2)
        disposed = acquired + timedelta(days=1)
        rows.append(
            f"{acquired.isoformat()},ETH,1,buy,EUR,10"
        )
        rows.append(
            f"{disposed.isoformat()},ETH,-1,sell,EUR,12"
        )
    batch = CsvRawImporter(store).import_text(
        source="synthetic-cex",
        filename="two-year-report-fixture.csv",
        content="\n".join(rows) + "\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()
    return store


def _extract_pdf(content: bytes) -> tuple[int, str]:
    reader = PdfReader(BytesIO(content), strict=True)
    return len(reader.pages), "\n".join(page.extract_text() or "" for page in reader.pages)


def test_year_report_uses_selected_year_read_models_and_all_tax_lines(tmp_path):
    store = _store_with_two_years(tmp_path)
    service = TaxYearPdfReportService(store)

    artifact = service.create(2024)
    manifest = artifact.manifest
    assert manifest.year == 2024
    assert manifest.report_status == "preview"
    assert manifest.final_filing_allowed is False
    assert manifest.tax_line_count == 128
    assert manifest.summary.taxable_private_disposals_eur == Decimal("256")
    assert manifest.summary.taxable_disposal_proceeds_eur == Decimal("1536")
    assert manifest.summary.acquisition_cost_eur == Decimal("1280")
    manifest_core = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    expected_manifest_hash = hashlib.sha256(
        json.dumps(
            manifest_core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert manifest.manifest_sha256 == expected_manifest_hash
    assert sum(item.page_count for item in manifest.files) > 1
    assert all(1 <= item.page_count <= MAX_PDF_PAGES_PER_FILE for item in manifest.files)

    all_lines = TaxService(store).list_tax_lines()
    selected_ids = {
        line.tax_line_id
        for line in all_lines
        if line.disposed_at.year == 2024
    }
    other_year_ids = {
        line.tax_line_id
        for line in all_lines
        if line.disposed_at.year == 2023
    }
    extracted = ""
    page_total = 0
    for item in manifest.files:
        loaded = service.get_pdf_bytes(2024, manifest.artifact_id, item.file_index)
        assert loaded is not None
        file_model, content = loaded
        actual_pages, text = _extract_pdf(content)
        assert actual_pages == file_model.page_count
        assert hashlib.sha256(content).hexdigest() == file_model.sha256
        page_total += actual_pages
        extracted += "\n" + text

    compact_text = re.sub(r"\s+", "", extracted)
    assert page_total == sum(item.page_count for item in manifest.files)
    assert all(compact_text.count(line_id) == 1 for line_id in selected_ids)
    assert all(line_id not in compact_text for line_id in other_year_ids)
    assert "Jahresbericht2024" in compact_text
    assert manifest.calculation_run_id in compact_text
    assert manifest.input_binding_sha256 in compact_text
    assert "VORSCHAU" in extracted
    assert "NICHTFINALFREIGEGEBEN" in compact_text
    assert "TechnischerPrüfstatus" in compact_text


def test_pdf_split_uses_parser_page_count_and_never_duplicates_pages():
    source = BytesIO()
    document = canvas.Canvas(source, pagesize=(250, 180))
    for page in range(207):
        document.drawString(12, 90, f"SOURCE_PAGE_{page:03d}")
        document.showPage()
    document.save()

    parts = split_pdf_by_page_count(source.getvalue())

    assert [page_count for _, page_count in parts] == [100, 100, 7]
    extracted_markers = []
    for content, expected_pages in parts:
        reader = PdfReader(BytesIO(content), strict=True)
        assert len(reader.pages) == expected_pages <= 100
        for page in reader.pages:
            extracted_markers.extend(re.findall(r"SOURCE_PAGE_\d{3}", page.extract_text() or ""))
    assert len(extracted_markers) == 207
    assert len(set(extracted_markers)) == 207
    assert set(extracted_markers) == {f"SOURCE_PAGE_{page:03d}" for page in range(207)}


def test_report_remains_preview_when_technical_export_gate_is_blocked(tmp_path):
    store = _store_with_two_years(tmp_path, year_2024_lines=2)
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="year:2024:asset:ETH",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("999"),
            year=2024,
            asset="ETH",
            source="synthetic-test",
            note="test gate only",
        )
    )

    artifact = TaxYearPdfReportService(store).create(2024)

    assert artifact.manifest.technical_status.technical_export_allowed is False
    assert artifact.manifest.technical_status.status == "blocked"
    assert artifact.manifest.final_filing_allowed is False
    assert artifact.manifest.report_status == "preview"
    _, content = TaxYearPdfReportService(store).get_pdf_bytes(
        2024, artifact.manifest.artifact_id, 1
    )
    _, text = _extract_pdf(content)
    assert "VORSCHAU" in text
    assert "Finale Jahresfreigabe" in text
    assert "Nicht erteilt" in text


def test_archived_report_bytes_and_manifest_survive_new_calculation_run(tmp_path):
    store = _store_with_two_years(tmp_path, year_2024_lines=3)
    service = TaxYearPdfReportService(store)
    first = service.create(2024)
    old_file = service.get_pdf_bytes(2024, first.manifest.artifact_id, 1)
    old_manifest = service.get_manifest_bytes(2024, first.manifest.artifact_id)
    assert old_file is not None and old_manifest is not None

    TaxService(store).rebuild_fifo()
    second = service.create(2024)
    reloaded_old_file = service.get_pdf_bytes(2024, first.manifest.artifact_id, 1)
    reloaded_old_manifest = service.get_manifest_bytes(2024, first.manifest.artifact_id)

    assert second.manifest.artifact_id != first.manifest.artifact_id
    assert second.manifest.calculation_run_id != first.manifest.calculation_run_id
    assert reloaded_old_file == old_file
    assert reloaded_old_manifest == old_manifest
    assert len(service.list(2024).artifacts) == 2


def test_archive_download_rejects_modified_pdf_bytes(tmp_path):
    store = _store_with_two_years(tmp_path, year_2024_lines=2)
    service = TaxYearPdfReportService(store)
    artifact = service.create(2024)
    file_model = artifact.manifest.files[0]
    archived_file = (
        service.archive_root
        / "2024"
        / artifact.manifest.artifact_id
        / file_model.filename
    )
    archived_file.write_bytes(archived_file.read_bytes() + b"tampered")

    with pytest.raises(TaxYearPdfReportError, match="tax_year_pdf_file_integrity_failed"):
        service.get_pdf_bytes(2024, artifact.manifest.artifact_id, file_model.file_index)


def test_report_requires_a_calculation_run_without_inventing_zero_values(tmp_path):
    store = DuckDbStore(tmp_path / "empty.duckdb")

    try:
        TaxYearPdfReportService(store).create(2024)
    except TaxYearPdfReportError as exc:
        assert exc.code == "tax_calculation_run_missing"
    else:
        raise AssertionError("report without a tax run must be blocked")


def test_input_change_during_render_requires_a_new_report(tmp_path, monkeypatch):
    store = _store_with_two_years(tmp_path, year_2024_lines=2)
    import steuerreport_v2.domain.tax_year_pdf_reports as report_module

    original_binding = report_module.current_filing_binding
    calls = 0

    def changed_binding(current_store):
        nonlocal calls
        calls += 1
        digest, run_id = original_binding(current_store)
        if calls == 2:
            return "f" * 64, run_id
        return digest, run_id

    monkeypatch.setattr(report_module, "current_filing_binding", changed_binding)
    with pytest.raises(TaxYearPdfReportError, match="filing_inputs_changed_create_a_new_report"):
        TaxYearPdfReportService(store).create(2024)

    assert calls == 2
    assert not (tmp_path / "tax_year_report_archive").exists()


def test_report_api_creates_lists_and_downloads_immutable_artifacts(tmp_path):
    store = _store_with_two_years(tmp_path, year_2024_lines=2)
    client = TestClient(create_app(store))

    created = client.post("/api/v1/tax-years/2024/reports/pdf")
    assert created.status_code == 200
    artifact = created.json()["data"]
    artifact_id = artifact["manifest"]["artifact_id"]

    listed = client.get("/api/v1/tax-years/2024/reports/pdf")
    assert listed.status_code == 200
    assert listed.json()["data"]["artifacts"][0]["manifest"]["artifact_id"] == artifact_id

    manifest_response = client.get(artifact["manifest_endpoint"])
    assert manifest_response.status_code == 200
    assert manifest_response.json()["artifact_id"] == artifact_id

    file_info = artifact["manifest"]["files"][0]
    pdf_response = client.get(file_info["download_endpoint"])
    assert pdf_response.status_code == 200
    assert pdf_response.headers["x-report-sha256"] == file_info["sha256"]
    assert len(PdfReader(BytesIO(pdf_response.content), strict=True).pages) == file_info["page_count"]

    missing = client.get(
        f"/api/v1/tax-years/2024/reports/pdf/{artifact_id}/files/99"
    )
    assert missing.status_code == 404
