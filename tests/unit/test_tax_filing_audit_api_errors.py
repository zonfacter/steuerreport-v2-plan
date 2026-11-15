import csv
import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditService
from steuerreport_v2.contracts.tax_filing_snapshots import TaxFilingSnapshotCaptureRequest
from test_tax_filing_audit import _package


@pytest.mark.parametrize("suffix", ["", ".json", ".md"])
def test_audit_archive_io_problem_is_a_conflict_without_data_changes(tmp_path, suffix):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    service = TaxFilingAuditService(store)
    blocker = b"synthetic existing file, never replace"
    service.archive_root.write_bytes(blocker)
    client = TestClient(create_app(store))
    before = store.path.read_bytes()
    response = client.get(f"/api/v1/tax-years/2025/filing-audit-report{suffix}")
    assert response.status_code == 409
    assert service.archive_root.read_bytes() == blocker
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("suffix", ["", ".json", ".md"])
def test_invalid_reference_detail_is_not_reported_as_zero_tax_lines(tmp_path, suffix):
    manifest_name = "00_Manifest/year-evidence-manifest.json"
    with zipfile.ZipFile(io.BytesIO(_package())) as original:
        members = {name: original.read(name) for name in original.namelist()}
    manifest = json.loads(members[manifest_name])
    row = {
        "Datum_Verkauf": "2025-02-02T12:00:00+00:00", "Asset": "SYNTH",
        "Menge": "1", "Veraeusserungserloes_EUR": "20",
        "Gewinn_Verlust_EUR": "10", "Haltedauer_Tage": "32", "Steuerpflichtig": "ja",
    }
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    detail_name = "02_Steuerliche_CSVs/tax-year-2025-tax-lines.csv"
    members[detail_name] = buffer.getvalue().encode()
    manifest["files"].append({
        "path": detail_name, "sha256": hashlib.sha256(members[detail_name]).hexdigest(),
        "size_bytes": len(members[detail_name]),
    })
    members[manifest_name] = json.dumps(manifest).encode()
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as target:
        for name, content in members.items():
            target.writestr(name, content)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    service = TaxFilingAuditService(store)
    reference = service.snapshots.capture_package(
        year=2025, package_bytes=package.getvalue(),
        request=TaxFilingSnapshotCaptureRequest(state="reference"), source_kind="synthetic-test",
    ).snapshot
    response = TestClient(create_app(store)).get(f"/api/v1/tax-years/2025/filing-audit-report{suffix}")
    assert response.status_code == 409
    assert not service.archive_root.exists()
    assert service.snapshots.read_package(reference.snapshot_id) == package.getvalue()
