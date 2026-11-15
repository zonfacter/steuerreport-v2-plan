from decimal import Decimal
import hashlib
import io
import json
import zipfile

from steuerreport_v2.contracts.parity import V1ReferenceMetricCreate
from steuerreport_v2.contracts.tax_filing_snapshots import TaxFilingSnapshotCaptureRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_filing_snapshots import (
    SUBMISSION_CONFIRMATION_TEXT,
    TaxFilingSnapshotService,
)
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def _synthetic_filing_package() -> bytes:
    path = "02_Steuerliche_CSVs/tax-year-2025-filing-summary.json"
    summary = json.dumps({
        "year": 2025,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "export_ready": True,
        "taxable_private_disposals_eur": "60",
        "taxable_disposal_proceeds_eur": "120",
        "acquisition_cost_eur": "60",
        "rewards_mining_staking_income_eur": "0",
        "derivative_pnl_eur": "0",
        "tax_free_private_disposals_eur": "0",
        "tax_free_lines_count": 0,
    }).encode("utf-8")
    manifest = {
        "year": 2025,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "files": [{
            "path": path,
            "source_endpoint": "/api/v1/tax-years/2025/filing-summary",
            "size_bytes": len(summary),
            "sha256": hashlib.sha256(summary).hexdigest(),
        }],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("00_Manifest/year-evidence-manifest.json", json.dumps(manifest))
        archive.writestr(path, summary)
    return output.getvalue()


def test_cross_year_equal_aggregate_does_not_hide_offsetting_asset_deltas(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    content = (
        "time,asset,amount,type,quote_asset,quote_quantity,account\n"
        "2024-12-15T12:00:00Z,SYNTHA,10,buy,EUR,100,Spot\n"
        "2024-12-15T12:01:00Z,SYNTHB,5,buy,EUR,50,Spot\n"
        "2025-06-15T12:00:00Z,SYNTHA,-4,sell,EUR,80,Spot\n"
        "2025-06-15T12:01:00Z,SYNTHB,-2,sell,EUR,40,Spot\n"
    )
    batch = CsvRawImporter(store).import_text(
        source="binance", filename="synthetic-offsets.csv", content=content
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    # Independent reference: costs 50 + 10 = 60, gains 30 + 30 = 60.
    # The inputs instead imply costs 40 + 20 and gains 40 + 20.
    reference = {
        "SYNTHA": {"acquisition_cost_eur": "50", "disposal_proceeds_eur": "80", "gain_loss_eur": "30"},
        "SYNTHB": {"acquisition_cost_eur": "10", "disposal_proceeds_eur": "40", "gain_loss_eur": "30"},
    }
    for asset, metrics in reference.items():
        for metric, value in metrics.items():
            store.add_v1_reference_metric(V1ReferenceMetricCreate(
                scope="tax", metric=metric, unit="EUR", value=Decimal(value),
                year=2025, asset=asset, source="synthetic-independent-reference",
            ))

    snapshots = TaxFilingSnapshotService(store)
    package = _synthetic_filing_package()
    archived = snapshots.capture_package(
        year=2025, package_bytes=package,
        request=TaxFilingSnapshotCaptureRequest(state="reference"), source_kind="test",
    ).snapshot
    submitted = snapshots.capture_from_snapshot(
        year=2025,
        request=TaxFilingSnapshotCaptureRequest(
            state="submitted", source_snapshot_id=archived.snapshot_id,
            confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
            submitted_at="2026-01-02T00:00:00+00:00",
        ),
    ).snapshot
    assert submitted.package_sha256 == hashlib.sha256(package).hexdigest()

    tax = TaxService(store)
    parity = V1ParityService(store)

    def verify():
        result = tax.rebuild_fifo()
        assert result.unmatched_disposals == 0
        lines = {line.asset: line for line in tax.list_tax_lines()}
        lots = {lot.asset: lot for lot in tax.list_tax_lots()}
        assert set(lines) == set(lots) == {"SYNTHA", "SYNTHB"}
        assert (lines["SYNTHA"].quantity, lines["SYNTHA"].acquisition_cost_eur,
                lines["SYNTHA"].disposal_proceeds_eur, lines["SYNTHA"].gain_loss_eur) == (
                    Decimal("4"), Decimal("40"), Decimal("80"), Decimal("40"))
        assert (lines["SYNTHB"].quantity, lines["SYNTHB"].acquisition_cost_eur,
                lines["SYNTHB"].disposal_proceeds_eur, lines["SYNTHB"].gain_loss_eur) == (
                    Decimal("2"), Decimal("20"), Decimal("40"), Decimal("20"))
        assert all(lines[asset].lot_id == lots[asset].lot_id for asset in lines)
        assert (lots["SYNTHA"].quantity_remaining, lots["SYNTHB"].quantity_remaining) == (
            Decimal("6"), Decimal("3")
        )
        years = TaxYearService(store)
        for asset, acquisition_row, disposal_row in (("SYNTHA", 1, 3), ("SYNTHB", 2, 4)):
            drilldown = years.asset_fifo_drilldown(2025, asset=asset)
            assert drilldown.lines_count == 1
            line = drilldown.lines[0]
            assert line.acquired_at.startswith("2024-12-15")
            assert line.disposed_at.startswith("2025-06-15")
            assert line.acquisition_raw.batch_id == line.disposal_raw.batch_id == batch.batch_id
            assert line.acquisition_raw.row_number == acquisition_row
            assert line.disposal_raw.row_number == disposal_row
            assert line.acquisition_event.raw_object_id == line.acquisition_raw.raw_object_id
            assert line.disposal_event.raw_object_id == line.disposal_raw.raw_object_id

        report = parity.compare()
        rows = {(row.reference.asset, row.reference.metric): row for row in report.rows}
        expected = {
            ("SYNTHA", "acquisition_cost_eur"): Decimal("-10"),
            ("SYNTHB", "acquisition_cost_eur"): Decimal("10"),
            ("SYNTHA", "disposal_proceeds_eur"): Decimal("0"),
            ("SYNTHB", "disposal_proceeds_eur"): Decimal("0"),
            ("SYNTHA", "gain_loss_eur"): Decimal("10"),
            ("SYNTHB", "gain_loss_eur"): Decimal("-10"),
        }
        assert (report.compared, report.matches, report.differences, report.missing_v2) == (6, 2, 4, 0)
        assert {key: row.difference for key, row in rows.items()} == expected
        assert all(row.status == ("match" if expected[key] == 0 else "diff") for key, row in rows.items())
        assert sum((row.difference for key, row in rows.items() if key[1] == "gain_loss_eur"), Decimal("0")) == 0
        assert sum((line.gain_loss_eur for line in lines.values()), Decimal("0")) == Decimal("60")
        readiness = parity.release_readiness()
        assert readiness.release_ready is False
        assert readiness.blocking_groups == 2

        comparison = snapshots.comparison(2025)
        assert comparison.baseline.snapshot_id == submitted.snapshot_id
        assert comparison.status == "unchanged"
        assert comparison.comparison_scope.aggregate_status == "equal"
        assert len(comparison.deltas) == 6 and all(row.delta_eur == 0 for row in comparison.deltas)
        assert comparison.exact_change_detected is False
        assert comparison.comparison_scope.events == "not_compared"
        assert comparison.comparison_scope.lots == "not_compared"
        assert comparison.comparison_scope.tax_lines == "not_compared"
        assert comparison.comparison_scope.detail_reconciliation == "not_compared"
        assert comparison.comparison_scope.reference_detail_binding == "not_verified"
        assert comparison.comparison_scope.current_detail_binding == "not_verified"
        assert "keine Einzelpositionsparitaet" in comparison.comparison_scope.explanation
        assert snapshots.read_package(archived.snapshot_id) == package
        assert snapshots.read_package(submitted.snapshot_id) == package
        assert snapshots.get(submitted.snapshot_id).integrity_status == "verified"
        return tuple(sorted((key, row.status, row.v2_value, row.difference) for key, row in rows.items()))

    first = verify()
    assert verify() == first
