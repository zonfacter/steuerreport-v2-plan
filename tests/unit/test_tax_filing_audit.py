from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient

from steuerreport_v2 import __version__
from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.tax_filing_snapshots import TaxFilingSnapshotCaptureRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditService


def _package(year: int = 2025) -> bytes:
    summary_path = f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json"
    summary = {
        "year": year,
        "generated_at": "2026-07-05T10:31:21+00:00",
        "export_ready": True,
        "taxable_private_disposals_eur": "-10.00",
        "taxable_disposal_proceeds_eur": "100.00",
        "acquisition_cost_eur": "110.00",
        "rewards_mining_staking_income_eur": "2.00",
        "derivative_pnl_eur": "0",
        "tax_free_private_disposals_eur": "0",
        "tax_free_lines_count": 0,
    }
    summary_bytes = json.dumps(summary).encode("utf-8")
    manifest = {
        "generated_at": "2026-07-05T10:31:21+00:00",
        "year": year,
        "files": [
            {
                "path": summary_path,
                "source_endpoint": f"/api/v1/tax-years/{year}/filing-summary",
                "size_bytes": len(summary_bytes),
                "sha256": hashlib.sha256(summary_bytes).hexdigest(),
            }
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("00_Manifest/year-evidence-manifest.json", json.dumps(manifest))
        package.writestr(summary_path, summary_bytes)
    return buffer.getvalue()


def test_audit_snapshot_metadata_and_unknown_cause_are_explicit(tmp_path: Path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = TaxFilingAuditService(store)
    snapshot = service.snapshots.capture_package(
        year=2025,
        package_bytes=_package(),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    ).snapshot

    assert snapshot.software_version == __version__
    assert snapshot.method_version == "bmf_readiness_v3_provider_basis_classification"
    assert snapshot.package_generated_at_europe_berlin == "2026-07-05T12:31:21+02:00"
    assert snapshot.database_fingerprint_sha256 == snapshot.runtime_fingerprint_sha256

    delta = service._delta_from_position(
        {
            "asset": "BTC",
            "quantity": Decimal("1"),
            "gain": Decimal("2"),
            "proceeds": Decimal("3"),
            "acquisition_cost": Decimal("1"),
            "holding_days": 10,
            "taxable": True,
            "disposed_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        },
        None,
        "removed",
        "tax_line",
    )
    assert delta.cause == "unknown"
    assert delta.cause_explanation
    assert delta.review_required is True


def test_audit_report_is_read_only_and_write_once(tmp_path: Path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = TaxFilingAuditService(store)
    service.snapshots.capture_package(
        year=2025,
        package_bytes=_package(),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    )
    with store.connect() as con:
        before = con.execute(
            "select count(*) from tax_filing_snapshots"
        ).fetchone()[0]

    query_time = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    first = service.build(2025, query_time=query_time)
    json_path = service.archive_root / "2025" / f"{first.report_id}.json"
    markdown_path = service.archive_root / "2025" / f"{first.report_id}.md"
    json_before = json_path.read_bytes()
    markdown_before = markdown_path.read_bytes()

    second = service.build(
        2025,
        query_time=datetime(2026, 9, 27, 12, 1, tzinfo=timezone.utc),
    )
    with store.connect() as con:
        after = con.execute(
            "select count(*) from tax_filing_snapshots"
        ).fetchone()[0]

    assert first.report_id == second.report_id
    assert first.report_content_sha256 == second.report_content_sha256
    assert json_path.read_bytes() == json_before
    assert markdown_path.read_bytes() == markdown_before
    assert json_path.stat().st_mode & 0o222 == 0
    assert markdown_path.stat().st_mode & 0o222 == 0
    assert before == after == 1

    client = TestClient(create_app(store))
    response = client.get("/api/v1/tax-years/2025/filing-audit-report.json")
    assert response.status_code == 200
    assert response.headers["x-steuerreport-audit-immutable"] == "true"
    assert json.loads(response.content)["database_mutated"] is False


def test_source_reconciliation_matches_transfer_mirrors_and_quarantines_unmatched_blockpit(
    tmp_path: Path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.health()
    blockpit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="blockpit",
            filename="bitget-2025-blockpit.csv",
            file_hash="sha256:blockpit",
        )
    )
    solana_batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solscan-signatures.json",
            file_hash="sha256:solana",
        )
    )
    binance_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="binance-deposits.xlsx",
            file_hash="sha256:binance",
        )
    )
    blockpit_raw = store.add_raw_object(
        blockpit_batch.batch_id,
        RawObjectCreate(
            row_number=7,
            payload_json=json.dumps(
                {
                    "Integration Name": "bitget",
                    "Source Name": "bitget",
                }
            ),
        ),
    )
    solana_raw = store.add_raw_object(
        solana_batch.batch_id,
        RawObjectCreate(row_number=11, payload_json=json.dumps({"signature": "sig-1"})),
    )
    blockpit_trade_raw = store.add_raw_object(
        blockpit_batch.batch_id,
        RawObjectCreate(
            row_number=8,
            payload_json=json.dumps(
                {
                    "Integration Name": "bitget",
                    "Source Name": "bitget",
                }
            ),
        ),
    )
    primary_transfer_raw = store.add_raw_object(
        binance_batch.batch_id,
        RawObjectCreate(row_number=12, payload_json=json.dumps({"tx_id": "sig-2"})),
    )
    primary_transfer_counterpart_raw = store.add_raw_object(
        solana_batch.batch_id,
        RawObjectCreate(row_number=13, payload_json=json.dumps({"signature": "sig-2"})),
    )
    events = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="blockpit",
                source_ref="sig-1",
                tx_id="sig-1",
                event_time=datetime(2025, 3, 9, 19, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-10"),
                raw_object_id=blockpit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                source_ref="sig-1",
                tx_id="sig-1",
                event_time=datetime(2025, 3, 9, 18, 59, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("10"),
                raw_object_id=solana_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="blockpit",
                source_ref="bitget-trade-1",
                tx_id="bitget-trade-1",
                event_time=datetime(2025, 4, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="JUP",
                quantity=Decimal("5"),
                raw_object_id=blockpit_trade_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="sig-2",
                tx_id="sig-2",
                event_time=datetime(2025, 5, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("10"),
                raw_object_id=primary_transfer_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                source_ref="sig-2",
                tx_id="sig-2",
                event_time=datetime(2025, 5, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("-10"),
                raw_object_id=primary_transfer_counterpart_raw.raw_object_id,
            ),
        ]
    )

    report, evidence = TaxFilingAuditService(store)._source_reconciliation(2025)

    assert report.status == "review_required"
    assert report.matched_mirror_group_count == 1
    assert report.matched_primary_transfer_group_count == 1
    assert report.matched_primary_transfer_event_count == 2
    assert report.unmatched_aggregator_event_count == 1
    assert report.unmatched_aggregator_tax_line_count == 0
    assert evidence[events[0].event_id]["tax_inclusion_status"] == "not_independent_tax_event"
    assert evidence[events[0].event_id]["counterpart_event_ids"] == [events[1].event_id]
    assert evidence[events[2].event_id]["source_validation_status"] == "unmatched_review"
    assert evidence[events[2].event_id]["tax_inclusion_status"] == "pending_review"
    assert evidence[events[3].event_id]["tax_inclusion_status"] == "not_independent_tax_event"
    assert evidence[events[4].event_id]["counterpart_event_ids"] == [events[3].event_id]
    mirror_event = report.mirror_matches[0].events[0]
    assert mirror_event.reported_integration == "bitget"
    assert mirror_event.import_filename == "bitget-2025-blockpit.csv"
