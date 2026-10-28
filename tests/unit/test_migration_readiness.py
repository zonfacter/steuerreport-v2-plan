from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.exports import PdfExportRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.private_disposal_threshold import PrivateDisposalThresholdRequest
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.filing_binding import BINDING_VERSION, current_filing_binding, snapshot_binding_status
from steuerreport_v2.domain.private_disposal_threshold import assess_private_disposal_threshold
from steuerreport_v2.domain.product_readiness import ProductReadinessService
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditService
from test_exports import _clean_store
from test_reports import _store_with_priced_deposit


def test_global_pdf_is_bound_preview_not_final_filing(tmp_path):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    package = service.create_pdf_packages(PdfExportRequest(estimated_pages=1)).packages[0]
    assert package.filing_status == "preview" and package.input_binding_sha256
    ready = service.readiness()
    assert ready.allow_export and ready.technical_export_allowed
    assert not ready.final_filing_allowed and ready.filing_status == "technical_only"
    assert service.get_package(package.package_id).input_binding_sha256 == package.input_binding_sha256
    _, content = service.render_pdf_package(package.package_id)
    assert b"KEINE FINALE JAHRESFREIGABE" in content


@pytest.mark.parametrize("change", ["price", "settings"])
def test_pdf_input_change_blocks_old_download_without_rewriting_binding(tmp_path, change):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    package = service.create_pdf_packages(PdfExportRequest(estimated_pages=1)).packages[0]
    original = service._package_binding(package.package_id)
    if change == "price":
        store.add_price_point(PricePointCreate(asset="USDT", price_eur=Decimal("0.8"),
            priced_at=datetime(2021, 4, 28, 1, tzinfo=timezone.utc), source="synthetic-change"))
    else:
        store.upsert_admin_setting(AdminSettingWrite(key="runtime.synthetic.method", value_json='"changed"'))
    assert service.render_pdf_package(package.package_id) is None
    assert service._package_binding(package.package_id) == original


def test_unrelated_export_metadata_does_not_invalidate_existing_preview(tmp_path):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    first = service.create_pdf_packages(PdfExportRequest(estimated_pages=1)).packages[0]
    second = service.create_pdf_packages(PdfExportRequest(estimated_pages=1)).packages[0]
    assert first.input_binding_sha256 == second.input_binding_sha256
    assert service.render_pdf_package(first.package_id) is not None
    service.delete_package(second.package_id)
    assert service.render_pdf_package(first.package_id) is not None


def test_methodology_snapshot_requires_binding_and_detects_changed_inputs(tmp_path):
    store = _clean_store(tmp_path)
    assert snapshot_binding_status(store, None) == "missing"
    assert snapshot_binding_status(store, SimpleNamespace(ready_years=[2021])) == "unbound"
    digest, run_id = current_filing_binding(store)
    report = SimpleNamespace(input_binding_sha256=digest, latest_tax_run_id=run_id, binding_version=BINDING_VERSION)
    assert snapshot_binding_status(store, report) == "current"
    store.upsert_admin_setting(AdminSettingWrite(key="runtime.synthetic.rule", value_json="2"))
    assert snapshot_binding_status(store, report) == "stale"


def test_price_evidence_is_not_automatic_daily_method_approval(tmp_path):
    store = _clean_store(tmp_path)
    store.add_price_point(PricePointCreate(asset="SOL", price_eur=Decimal("100"),
        priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc), source="historical:v2:synthetic"))
    check = ProductReadinessService(store)._historical_reference_check()
    assert check.status == "warning" and check.count == 1
    assert not ProductReadinessService(store).report().can_file_without_review


def test_year_zip_contains_same_run_binding_and_preview_warning(tmp_path):
    store = _store_with_priced_deposit(tmp_path)
    app = create_app(store)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/export/tax-years/{year}/evidence-package.zip")
    before = current_filing_binding(store)
    response = endpoint(2021)
    assert response.status_code == 200, response.body[:1000]
    with ZipFile(BytesIO(response.body)) as archive:
        manifest = json.loads(archive.read("00_Manifest/year-evidence-manifest.json"))
        assert manifest["input_binding_sha256"] == before[0]
        assert manifest["calculation_run_id"] == before[1]
        assert manifest["filing_status"] == "preview" and not manifest["export_ready"]
        assert "KEINE FINALE JAHRESFREIGABE" in archive.read("README.txt").decode()
    assert current_filing_binding(store) == before
    assert endpoint(2021).headers["x-steuerreport-cache"] == "hit"
    store.add_price_point(PricePointCreate(asset="USDT", price_eur=Decimal("0.89"),
        priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc), source="synthetic-change"))
    assert endpoint(2021).headers["x-steuerreport-cache"] == "miss"


@pytest.mark.parametrize("year,gain,threshold,reached", [
    (2023, "599.99", "600", False), (2023, "600", "600", True),
    (2024, "999.99", "1000", False), (2024, "1000", "1000", True),
])
def test_freigrenze_strict_boundary_is_not_a_deductible_allowance(year, gain, threshold, reached):
    result = assess_private_disposal_threshold(year, Decimal(gain), PrivateDisposalThresholdRequest(
        other_private_gain_loss_eur=Decimal("0"), confirm_other_private_disposals_complete=True))
    assert result.threshold_eur == Decimal(threshold)
    assert result.total_private_gain_loss_eur == Decimal(gain)
    assert result.threshold_reached is reached and not result.final_filing_allowed


@pytest.mark.parametrize("payload", [{}, {"other_private_gain_loss_eur": "0"}, {"confirm_other_private_disposals_complete": True}])
def test_threshold_never_assumes_personal_other_disposals_zero(payload):
    result = assess_private_disposal_threshold(2025, Decimal("100"), PrivateDisposalThresholdRequest(**payload))
    assert result.status == "context_required" and result.total_private_gain_loss_eur is None
    assert result.threshold_reached is None


def test_threshold_readonly_api_and_unsupported_year(tmp_path):
    store = _clean_store(tmp_path)
    client = TestClient(create_app(store))
    before = current_filing_binding(store)
    path = "/api/v1/tax-years/2025/private-disposal-threshold-assessment"
    response = client.post(path, json={})
    assert response.status_code == 200 and response.json()["data"]["status"] == "context_required"
    assert client.post(path, json={"other_private_gain_loss_eur": "NaN"}).status_code == 422
    assert current_filing_binding(store) == before
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/tax-years/{year}/private-disposal-threshold-assessment"]["post"]["x-data-effect"] == "read-only"
    assert assess_private_disposal_threshold(2027, Decimal("1"), PrivateDisposalThresholdRequest()).status == "unsupported_year"


def test_audit_uses_archived_classification_and_new_calendar_classification(tmp_path):
    service = TaxFilingAuditService(_clean_store(tmp_path))
    old = {"asset": "SYNTHETIC", "quantity": Decimal("1"), "gain": Decimal("50"),
        "acquisition_cost": Decimal("100"), "proceeds": Decimal("150"), "holding_days": 366,
        "taxable": False, "classification_policy": "archived_report_label"}
    new = {**old, "taxable": True, "classification_policy": "de_private_calendar_holding_berlin_v1"}
    delta = service._delta_from_position(old, new, "changed", "tax_line")
    assert delta.taxable_old is False and delta.taxable_new is True
    assert service._line_delta([delta], taxable=True) == Decimal("50")
    assert service._line_delta([delta], taxable=False) == Decimal("-50")
    assert delta.cause == "holding_period_classification"


@pytest.mark.parametrize("label,expected", [(" ja ", True), ("NEIN", False), ("ungeklaert", None), ("", None)])
def test_unknown_archive_label_is_not_silently_tax_free(label, expected):
    assert TaxFilingAuditService._archived_taxable(label) is expected


def test_pdf_api_distinguishes_missing_stale_and_blocked(tmp_path):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    package = service.create_pdf_packages(PdfExportRequest(estimated_pages=1)).packages[0]
    client = TestClient(create_app(store))
    prefix = "/api/v1/export/packages/"
    assert client.get(prefix + "missing/download.pdf").status_code == 404
    store.upsert_admin_setting(AdminSettingWrite(key="runtime.synthetic.rule", value_json="2"))
    response = client.get(prefix + package.package_id + "/download.pdf")
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "export_package_stale_or_unbound"
    with store.connect() as con:
        con.execute("update export_packages set status='blocked' where package_id=?", [package.package_id])
    response = client.get(prefix + package.package_id + "/download.pdf")
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "export_package_blocked"
