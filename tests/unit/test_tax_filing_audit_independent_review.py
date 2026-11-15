"""Independent baseline probes for existing tax-audit interfaces only."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import socket
import zipfile

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.tax_filing_snapshots import TaxFilingSnapshotCaptureRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditError, TaxFilingAuditService
from test_tax_filing_audit import _package


QUERY_TIME = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _zero_reference_package():
    summary_name = "02_Steuerliche_CSVs/tax-year-2025-filing-summary.json"
    manifest_name = "00_Manifest/year-evidence-manifest.json"
    with zipfile.ZipFile(io.BytesIO(_package())) as source:
        summary = json.loads(source.read(summary_name))
        manifest = json.loads(source.read(manifest_name))
    for field in (
        "taxable_private_disposals_eur",
        "taxable_disposal_proceeds_eur",
        "acquisition_cost_eur",
        "rewards_mining_staking_income_eur",
        "derivative_pnl_eur",
        "tax_free_private_disposals_eur",
    ):
        summary[field] = "0"
    summary["tax_free_lines_count"] = 0
    content = json.dumps(summary).encode("utf-8")
    manifest["files"] = [{
        "path": summary_name,
        "source_endpoint": "/api/v1/tax-years/2025/filing-summary",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr(manifest_name, json.dumps(manifest))
        target.writestr(summary_name, content)
    return output.getvalue()


@pytest.fixture
def audit(tmp_path, monkeypatch):
    def forbidden_network(*args, **kwargs):
        raise AssertionError("Independent audit probe must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    store = DuckDbStore(tmp_path / "synthetic-audit.duckdb")
    service = TaxFilingAuditService(store)
    package = _zero_reference_package()
    snapshot = service.snapshots.capture_package(
        year=2025,
        package_bytes=package,
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="synthetic-independent-review",
    ).snapshot
    yield store, service
    assert service.snapshots.read_package(snapshot.snapshot_id) == package


def test_explained_nonzero_aggregate_delta_does_not_mean_identical_sums(audit):
    store, service = audit
    store.add_canonical_events([
        CanonicalEventCreate(
            source="binance", source_ref="synthetic-buy", account="synthetic-spot",
            event_time=datetime(2025, 1, 2, 12, tzinfo=timezone.utc),
            event_type="trade", asset="SYNTH", quantity=Decimal("1"),
            quote_asset="EUR", quote_quantity=Decimal("10"),
        ),
        CanonicalEventCreate(
            source="binance", source_ref="synthetic-sell", account="synthetic-spot",
            event_time=datetime(2025, 2, 2, 12, tzinfo=timezone.utc),
            event_type="trade", asset="SYNTH", quantity=Decimal("-1"),
            quote_asset="EUR", quote_quantity=Decimal("20"),
        ),
    ])
    tax = TaxService(store)
    rebuilt = tax.rebuild_fifo()
    assert rebuilt.unmatched_disposals == 0
    lines_before = tax.list_tax_lines()
    assert len(lines_before) == 1
    line = lines_before[0]
    assert (line.acquisition_cost_eur, line.disposal_proceeds_eur, line.gain_loss_eur) == (
        Decimal("10"), Decimal("20"), Decimal("10"),
    )

    report = service.build(2025, query_time=QUERY_TIME, materialize=False)
    assert tax.list_tax_lines() == lines_before
    rows = {row.key: row for row in report.reconciliation}
    assert len(rows) == 6
    assert all(row.status == "reconciled" and row.residual_eur == 0 for row in rows.values())
    assert {key: row.aggregate_delta_eur for key, row in rows.items()} == {
        "private_disposals": Decimal("10"),
        "tax_free_disposals": Decimal("0"),
        "rewards_mining_staking": Decimal("0"),
        "derivatives": Decimal("0"),
        "disposal_proceeds": Decimal("20"),
        "acquisition_costs": Decimal("10"),
    }
    assert rows["private_disposals"].individual_delta_eur == Decimal("10")
    assert report.reproducibility.sums_identical is False, (
        "Exact reconciliation explains the nonzero deltas; it does not make old and new sums equal"
    )


def test_untampered_materialization_reuses_original_bytes(audit):
    _, service = audit
    first = service.build(2025, query_time=QUERY_TIME)
    root = service.archive_root / "2025"
    paths = [root / f"{first.report_id}.json", root / f"{first.report_id}.md"]
    before = {path: path.read_bytes() for path in paths}
    again = service._materialize(first)
    assert again == first
    assert {path: path.read_bytes() for path in paths} == before
    assert all(path.stat().st_mode & 0o222 == 0 for path in paths)


@pytest.mark.parametrize("artifact", ["json_status", "markdown_content"])
def test_materialization_rejects_tampered_existing_artifacts_without_repair(audit, artifact):
    _, service = audit
    first = service.build(2025, query_time=QUERY_TIME)
    root = service.archive_root / "2025"
    json_path = root / f"{first.report_id}.json"
    markdown_path = root / f"{first.report_id}.md"
    before = {path: path.read_bytes() for path in (json_path, markdown_path)}
    if artifact == "json_status":
        payload = json.loads(before[json_path])
        payload["status"] = "review_required" if first.status != "review_required" else "reconciled"
        assert payload["status"] != first.status
        # Valid DTO content: rejection must detect integrity, not just bad JSON/schema.
        type(first).model_validate(payload)
        changed_path = json_path
        changed_content = json.dumps(payload).encode("utf-8")
    else:
        changed_path = markdown_path
        changed_content = before[markdown_path] + b"\nSynthetic unauthorized content change.\n"
    changed_path.chmod(0o644)
    changed_path.write_bytes(changed_content)
    changed_path.chmod(0o444)
    expected = {**before, changed_path: changed_content}

    try:
        with pytest.raises(TaxFilingAuditError):
            service._materialize(first)
    finally:
        assert {path: path.read_bytes() for path in expected} == expected, (
            "A rejected immutable artifact must not be silently repaired or overwritten"
        )
