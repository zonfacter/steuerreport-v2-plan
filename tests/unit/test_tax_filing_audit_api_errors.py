import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditService


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
