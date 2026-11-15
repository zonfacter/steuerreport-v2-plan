"""Independent I/O-error probes for the existing audit materializer."""

from datetime import datetime, timezone
import errno
from pathlib import Path
import socket

import pytest

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditError, TaxFilingAuditService


@pytest.fixture
def prepared_audit(tmp_path, monkeypatch):
    def forbidden_network(*args, **kwargs):
        raise AssertionError("Audit I/O probe must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    store = DuckDbStore(tmp_path / "synthetic-audit-io.duckdb")
    store.health()
    service = TaxFilingAuditService(store)
    report = service.build(
        2025, query_time=datetime(2026, 9, 27, 12, tzinfo=timezone.utc), materialize=False,
    )
    assert not service.archive_root.exists()
    return service, report


def test_archive_root_file_conflict_is_domain_error_and_preserves_original(prepared_audit):
    service, report = prepared_audit
    path = service.archive_root
    path.write_bytes(b"synthetic existing bytes must not be altered\n")
    before = path.read_bytes()
    inode = path.stat().st_ino
    try:
        with pytest.raises(TaxFilingAuditError):
            service._materialize(report)
    finally:
        assert path.is_file() and path.read_bytes() == before
        assert path.stat().st_ino == inode


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.ENOSPC], ids=["permission", "no_space"])
def test_exact_archive_directory_creation_failure_is_domain_error(
    prepared_audit, monkeypatch, error_number,
):
    service, report = prepared_audit
    root = service.archive_root / str(report.year)
    original_mkdir = Path.mkdir
    attempts = []

    def fail_exact_root(path, *args, **kwargs):
        if path == root:
            attempts.append(path)
            raise OSError(error_number, "synthetic directory creation failure", str(path))
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_exact_root)
    try:
        with pytest.raises(TaxFilingAuditError):
            service._materialize(report)
    finally:
        assert attempts == [root]
        assert not service.archive_root.exists()
