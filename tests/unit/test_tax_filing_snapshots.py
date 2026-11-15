from __future__ import annotations

from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.tax_filing_snapshots import (
    TaxFilingSnapshotCaptureRequest,
    TaxFilingSnapshotComparison,
    TaxFilingSnapshotUsageConfirmationRequest,
)
from steuerreport_v2.contracts.tax_years import TaxYearFilingSummary
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_snapshots import (
    SUBMISSION_CONFIRMATION_TEXT,
    TaxFilingSnapshotError,
    TaxFilingSnapshotService,
)
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditError, TaxFilingAuditService
from steuerreport_v2.domain.tax_years import TaxYearService


def _package(
    year: int,
    *,
    private_result: str = "-2277.91",
    proceeds: str = "144714.04",
    costs: str = "146991.95",
    rewards: str = "45.44",
    derivatives: str = "0",
    tax_free: str = "-37.85",
    omit_field: str | None = None,
) -> bytes:
    summary_path = f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json"
    summary = {
        "year": year,
        "generated_at": "2026-07-05T10:31:21+00:00",
        "export_ready": True,
        "taxable_private_disposals_eur": private_result,
        "taxable_disposal_proceeds_eur": proceeds,
        "acquisition_cost_eur": costs,
        "rewards_mining_staking_income_eur": rewards,
        "derivative_pnl_eur": derivatives,
        "tax_free_private_disposals_eur": tax_free,
        "tax_free_lines_count": 2,
    }
    if omit_field is not None:
        del summary[omit_field]
    summary_bytes = json.dumps(summary).encode("utf-8")
    manifest = {
        "label": f"steuerreport-v2-tax-year-{year}-evidence-package",
        "generated_at": "2026-07-05T10:31:21+00:00",
        "year": year,
        "export_ready": True,
        "files": [
            {
                "path": summary_path,
                "source_endpoint": f"/api/v1/tax-years/{year}/filing-summary",
                "size_bytes": len(summary_bytes),
                "sha256": hashlib.sha256(summary_bytes).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "00_Manifest/year-evidence-manifest.json",
            json.dumps(manifest).encode("utf-8"),
        )
        package.writestr(summary_path, summary_bytes)
    return output.getvalue()


def _service(tmp_path: Path) -> TaxFilingSnapshotService:
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.health()
    return TaxFilingSnapshotService(store)


def test_reference_snapshot_is_content_addressed_immutable_and_deduplicated(tmp_path):
    service = _service(tmp_path)
    content = _package(2025)
    request = TaxFilingSnapshotCaptureRequest(
        state="reference",
        filing_kind="original",
        note="Historisches Paket vor Abgabebestaetigung.",
    )

    first = service.capture_package(
        year=2025,
        package_bytes=content,
        request=request,
        source_kind="test",
    )
    duplicate = service.capture_package(
        year=2025,
        package_bytes=content,
        request=request,
        source_kind="test",
    )

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert first.snapshot.revision == 1
    assert first.snapshot.state == "reference"
    assert first.snapshot.integrity_status == "verified"
    assert first.snapshot.package_sha256 == hashlib.sha256(content).hexdigest()
    assert first.snapshot.files_count == 1
    assert service.read_package(first.snapshot.snapshot_id) == content
    listing = service.list(year=2025)
    assert listing.reference_count == 1
    assert listing.submitted_count == 0
    assert listing.integrity_failures == 0


def test_submitted_snapshot_requires_explicit_confirmation_and_appends_revision(tmp_path):
    service = _service(tmp_path)
    reference = service.capture_package(
        year=2025,
        package_bytes=_package(2025),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    ).snapshot

    with pytest.raises(TaxFilingSnapshotError, match="ausdruecklichen Bestaetigung"):
        service.capture_from_snapshot(
            year=2025,
            request=TaxFilingSnapshotCaptureRequest(
                state="submitted",
                source_snapshot_id=reference.snapshot_id,
            ),
        )

    with pytest.raises(TaxFilingSnapshotError, match="submitted_at fehlt"):
        service.capture_from_snapshot(
            year=2025,
            request=TaxFilingSnapshotCaptureRequest(
                state="submitted",
                confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
                source_snapshot_id=reference.snapshot_id,
            ),
        )

    with pytest.raises(TaxFilingSnapshotError, match="ISO-8601"):
        service.capture_from_snapshot(
            year=2025,
            request=TaxFilingSnapshotCaptureRequest(
                state="submitted",
                confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
                source_snapshot_id=reference.snapshot_id,
                submitted_at="kein-zeitpunkt",
            ),
        )

    with pytest.raises(TaxFilingSnapshotError, match="Zukunft"):
        service.capture_from_snapshot(
            year=2025,
            request=TaxFilingSnapshotCaptureRequest(
                state="submitted",
                confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
                source_snapshot_id=reference.snapshot_id,
                submitted_at="2999-01-01T00:00:00+00:00",
            ),
        )

    submitted = service.capture_from_snapshot(
        year=2025,
        request=TaxFilingSnapshotCaptureRequest(
            state="submitted",
            filing_kind="original",
            confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
            source_snapshot_id=reference.snapshot_id,
            submitted_at="2026-07-06T12:00:00+02:00",
        ),
    ).snapshot

    assert submitted.revision == 2
    assert submitted.state == "submitted"
    assert submitted.source_snapshot_id == reference.snapshot_id
    assert submitted.package_sha256 == reference.package_sha256
    assert submitted.submitted_at == "2026-07-06T10:00:00+00:00"
    assert service.get(reference.snapshot_id).state == "reference"


def test_comparison_uses_submitted_baseline_and_does_not_net_tax_categories(tmp_path):
    service = _service(tmp_path)
    reference = service.capture_package(
        year=2025,
        package_bytes=_package(2025),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    ).snapshot
    service.capture_from_snapshot(
        year=2025,
        request=TaxFilingSnapshotCaptureRequest(
            state="submitted",
            confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
            source_snapshot_id=reference.snapshot_id,
            submitted_at="2026-07-06T10:00:00+00:00",
        ),
    )

    report = service.comparison(2025)
    assert report.baseline_selection == "latest_submitted"
    assert report.amendment_review_required is True
    assert report.status == "changed_review_required"
    assert report.comparison_scope.aggregate_status == "different"
    deltas = {row.key: row.delta_eur for row in report.deltas}
    assert deltas["taxable_private_disposals_eur"] == Decimal("2277.91")
    assert deltas["rewards_mining_staking_income_eur"] == Decimal("-45.44")
    assert report.declaration_change_detected is True


def test_usage_confirmation_is_append_only_and_keeps_used_package_as_baseline(tmp_path):
    service = _service(tmp_path)
    reference = service.capture_package(
        year=2025,
        package_bytes=_package(2025),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    ).snapshot
    request = TaxFilingSnapshotUsageConfirmationRequest(
        statement="Dieses Paket wurde fuer die Steuererklaerung verwendet.",
        actor="user",
        source="chat_user_statement",
    )

    first = service.confirm_package_usage(
        snapshot_id=reference.snapshot_id,
        request=request,
    )
    repeated = service.confirm_package_usage(
        snapshot_id=reference.snapshot_id,
        request=request,
    )
    later_reference = service.capture_package(
        year=2025,
        package_bytes=_package(2025, rewards="99.99"),
        request=TaxFilingSnapshotCaptureRequest(
            state="reference",
            filing_kind="correction",
        ),
        source_kind="test",
    ).snapshot

    confirmed = service.get(reference.snapshot_id)
    report = service.comparison(2025)
    governance = service.governance_status()

    assert first.created is True
    assert repeated.created is False
    assert repeated.event_id == first.event_id
    assert confirmed.filing_usage_confirmed is True
    assert confirmed.filing_usage_confirmation_actor == "user"
    assert confirmed.filing_usage_confirmation_source == "chat_user_statement"
    assert confirmed.filing_usage_confirmation_statement == request.statement
    assert report.latest_reference.snapshot_id == later_reference.snapshot_id
    assert report.baseline.snapshot_id == reference.snapshot_id
    assert report.baseline_selection == "confirmed_used_reference"
    assert report.usage_confirmed_reference.snapshot_id == reference.snapshot_id
    assert report.submission_confirmation_required is False
    assert report.submission_timestamp_required is True
    assert report.amendment_review_required is True
    assert report.status == "changed_review_required"
    assert governance["unconfirmed_reference_years"] == [2025]
    assert governance["usage_confirmed_reference_years"] == [2025]
    assert governance["submission_timestamp_missing_years"] == [2025]

    methodology = TaxMethodologyService(service.store)
    methodology.bmf_submission_guide = lambda years=None: SimpleNamespace(
        years=[
            SimpleNamespace(
                year=2025,
                status="conservative_ready",
                taxable_private_disposals_eur=Decimal("-5120.19"),
                rewards_mining_staking_income_eur=Decimal("419.79"),
                derivative_pnl_eur=Decimal("-3287.61"),
                tax_free_private_disposals_eur=Decimal("466.21"),
                technical_review_requirements_count=3,
                correction_review_recommended=True,
                amendment_reason="Aktueller Stand weicht von der Paketbasis ab.",
                blocking_count=0,
                filing_summary_endpoint="/summary",
                correction_map_endpoint="/correction",
                correction_map_csv_endpoint="/correction.csv",
                evidence_package_endpoint="/evidence.zip",
            )
        ]
    )
    prior = methodology.bmf_prior_filing_comparison(years=[2025])
    prior_row = prior.years[0]
    worklist = methodology.bmf_amendment_worklist(years=[2025])

    assert prior.confirmed_snapshot_years == [2025]
    assert prior.delta_review_years == [2025]
    assert prior.untrusted_declared_years == []
    assert prior_row.declared_values_source == "confirmed_filing_snapshot"
    assert prior_row.declared_values_snapshot_id == reference.snapshot_id
    assert prior_row.declared_taxable_private_disposals_eur == Decimal("-2277.91")
    assert prior_row.delta_taxable_private_disposals_eur == Decimal("-2842.28")
    assert prior_row.elster_field_verification_required is True
    assert prior_row.submission_timestamp_known is False
    assert worklist.compare_declared_years == [2025]
    assert worklist.years[0].prior_filing_values_source == "confirmed_filing_snapshot"
    assert worklist.years[0].prior_filing_snapshot_id == reference.snapshot_id


def test_archive_tampering_is_detected_and_download_is_blocked(tmp_path):
    service = _service(tmp_path)
    snapshot = service.capture_package(
        year=2025,
        package_bytes=_package(2025),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    ).snapshot
    archive_path = (
        service.archive_root / "2025" / f"{snapshot.package_sha256}.zip"
    )
    archive_path.chmod(0o644)
    archive_path.write_bytes(b"manipulated")

    assert service.get(snapshot.snapshot_id).integrity_status == "mismatch"
    comparison = service.comparison(2025)
    assert comparison.integrity_blocked is True
    assert comparison.status == "integrity_blocked"
    assert comparison.comparison_scope.aggregate_status == "not_compared"
    assert comparison.comparison_scope.tax_lines == "not_compared"
    with pytest.raises(TaxFilingSnapshotError, match="Archivintegritaet"):
        service.read_package(snapshot.snapshot_id)


def test_aggregate_scope_distinguishes_missing_baseline_and_supporting_delta(tmp_path):
    service = _service(tmp_path)
    missing = service.comparison(2025)
    assert missing.status == "no_snapshot"
    assert missing.comparison_scope.aggregate_status == "not_compared"
    assert missing.comparison_scope.events == "not_compared"

    package = _package(2025, private_result="0", proceeds="1", costs="0",
                       rewards="0", derivatives="0", tax_free="0")
    reference = service.capture_package(
        year=2025, package_bytes=package,
        request=TaxFilingSnapshotCaptureRequest(state="reference"), source_kind="test",
    ).snapshot
    submitted = service.capture_from_snapshot(
        year=2025,
        request=TaxFilingSnapshotCaptureRequest(
            state="submitted", source_snapshot_id=reference.snapshot_id,
            confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
            submitted_at="2026-07-06T10:00:00+00:00",
        ),
    ).snapshot
    report = service.comparison(2025)
    by_key = {item.key: item for item in report.deltas}
    assert report.status == "unchanged"
    assert report.declaration_change_detected is False
    assert report.amendment_review_required is False
    assert report.comparison_scope.aggregate_status == "different"
    assert by_key["taxable_disposal_proceeds_eur"].delta_eur == Decimal("-1")
    assert service.read_package(submitted.snapshot_id) == package


def test_missing_reference_aggregate_does_not_become_proven_equal(tmp_path):
    service = _service(tmp_path)
    package = _package(
        2025, private_result="0", proceeds="0", costs="0", rewards="0",
        derivatives="0", tax_free="0", omit_field="acquisition_cost_eur",
    )
    with pytest.raises(TaxFilingSnapshotError, match="unvollstaendig oder ungueltig"):
        service.capture_package(
            year=2025, package_bytes=package,
            request=TaxFilingSnapshotCaptureRequest(state="reference"), source_kind="test",
        )
    assert service.list().snapshots == []


def test_package_year_and_manifest_file_hash_are_validated(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(TaxFilingSnapshotError, match="anderen Steuerjahr"):
        service.capture_package(
            year=2024,
            package_bytes=_package(2025),
            request=TaxFilingSnapshotCaptureRequest(state="reference"),
            source_kind="test",
        )


def test_snapshot_api_exposes_human_comparison_and_archived_package(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = TaxFilingSnapshotService(store)
    reference = service.capture_package(
        year=2025,
        package_bytes=_package(2025),
        request=TaxFilingSnapshotCaptureRequest(state="reference"),
        source_kind="test",
    ).snapshot
    client = TestClient(create_app(store))

    listing = client.get("/api/v1/tax-filing-snapshots?year=2025")
    comparison = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison")
    human = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison.html")
    delta_csv = client.get(
        "/api/v1/export/tax-years/2025/filing-snapshot-comparison.csv"
    )
    package = client.get(reference.package_download_endpoint)
    usage_confirmation = client.post(
        f"/api/v1/tax-filing-snapshots/{reference.snapshot_id}/usage-confirmation",
        json={
            "statement": "Dieses Paket wurde fuer die Steuererklaerung verwendet.",
            "actor": "user",
            "source": "api",
        },
    )
    comparison_after_usage = client.get(
        "/api/v1/tax-years/2025/filing-snapshot-comparison"
    )
    submitted = client.post(
        "/api/v1/tax-years/2025/filing-snapshots",
        json={
            "state": "submitted",
            "filing_kind": "original",
            "confirmation_text": SUBMISSION_CONFIRMATION_TEXT,
            "source_snapshot_id": reference.snapshot_id,
            "submitted_at": "2026-07-06T10:00:00+00:00",
        },
    )

    assert listing.status_code == 200
    assert listing.json()["data"]["reference_count"] == 1
    assert comparison.status_code == 200
    assert comparison.json()["data"]["submission_confirmation_required"] is True
    scope = comparison.json()["data"]["comparison_scope"]
    assert scope["aggregate_status"] == "different"
    assert scope["events"] == scope["lots"] == scope["tax_lines"] == "not_compared"
    assert scope["detail_reconciliation"] == "not_compared"
    assert scope["reference_detail_binding"] == scope["current_detail_binding"] == "not_verified"
    assert human.status_code == 200
    assert "Abgabestand-Vergleich" in human.text
    assert "Einzelpositionsparitaet ist nicht nachgewiesen" in human.text
    assert "Drucken / als PDF sichern" in human.text
    assert delta_csv.status_code == 200
    assert "Filed_Value_EUR,Current_Value_EUR,Delta_EUR" in delta_csv.text
    assert package.status_code == 200
    assert package.headers["x-steuerreport-integrity"] == "verified"
    assert usage_confirmation.status_code == 200
    assert usage_confirmation.json()["data"]["created"] is True
    assert usage_confirmation.json()["data"]["snapshot"]["filing_usage_confirmed"] is True
    assert comparison_after_usage.status_code == 200
    assert comparison_after_usage.json()["data"]["baseline_selection"] == "confirmed_used_reference"
    assert comparison_after_usage.json()["data"]["submission_timestamp_required"] is True
    assert submitted.status_code == 200
    assert submitted.json()["data"]["snapshot"]["state"] == "submitted"


def _submitted_synthetic(service, *, private_result="0"):
    package = _package(2025, private_result=private_result, proceeds="0", costs="0",
                       rewards="0", derivatives="0", tax_free="0")
    reference = service.capture_package(
        year=2025, package_bytes=package,
        request=TaxFilingSnapshotCaptureRequest(state="reference"), source_kind="test",
    ).snapshot
    submitted = service.capture_from_snapshot(
        year=2025, request=TaxFilingSnapshotCaptureRequest(
            state="submitted", source_snapshot_id=reference.snapshot_id,
            confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
            submitted_at="2026-07-06T10:00:00+00:00",
        ),
    ).snapshot
    return submitted, package


def test_summary_register_mismatch_with_verified_package_is_not_compared(tmp_path):
    service = _service(tmp_path)
    submitted, package = _submitted_synthetic(service, private_result="100")
    with service.store.connect() as con:
        row = con.execute("select summary_json from tax_filing_snapshots where snapshot_id = ?", [submitted.snapshot_id]).fetchone()
        summary = json.loads(row[0])
        summary["taxable_private_disposals_eur"] = "0"
        con.execute("update tax_filing_snapshots set summary_json = ? where snapshot_id = ?", [json.dumps(summary), submitted.snapshot_id])
    assert service.read_package(submitted.snapshot_id) == package
    report = service.comparison(2025)
    assert report.comparison_scope.aggregate_status == "not_compared"
    assert report.status != "unchanged"
    assert report.baseline.values is None
    assert report.deltas == []
    assert report.amendment_review_required is True
    assert 2025 not in TaxMethodologyService(service.store)._confirmed_filing_snapshot_amounts()
    with pytest.raises(TaxFilingAuditError, match="nicht an das Archiv gebunden"):
        TaxFilingAuditService(service.store).build(2025, materialize=False)


@pytest.mark.parametrize("kind", ["incomplete", "wrong_year", "unbound"])
def test_untrusted_current_summary_is_not_compared(tmp_path, kind):
    service = _service(tmp_path)
    _submitted_synthetic(service)
    summary = TaxYearService(service.store).filing_summary(2025)
    if kind == "wrong_year":
        summary = summary.model_copy(update={"year": 2024})
    elif kind == "incomplete":
        data = summary.model_dump()
        del data["acquisition_cost_eur"]
        summary = TaxYearFilingSummary.model_validate(data)
    report = service.comparison(2025, current_summary=summary)
    assert report.comparison_scope.aggregate_status == "not_compared"
    assert report.status != "unchanged"
    assert report.amendment_review_required is True
    assert report.declaration_change_detected is None
    if kind != "unbound":
        assert report.current_values is None


@pytest.mark.parametrize("invalid", ["null", "{}", "not-json"])
def test_invalid_stored_summary_is_not_compared_or_crashed(tmp_path, invalid):
    service = _service(tmp_path)
    submitted, package = _submitted_synthetic(service)
    with service.store.connect() as con:
        con.execute("update tax_filing_snapshots set summary_json = ? where snapshot_id = ?", [invalid, submitted.snapshot_id])
    report = service.comparison(2025)
    assert report.comparison_scope.aggregate_status == "not_compared"
    assert report.status != "unchanged"
    assert service.read_package(submitted.snapshot_id) == package


def test_not_compared_is_explicit_in_html(tmp_path):
    service = _service(tmp_path)
    submitted, _ = _submitted_synthetic(service)
    with service.store.connect() as con:
        con.execute("update tax_filing_snapshots set summary_json='{}' where snapshot_id=?", [submitted.snapshot_id])
    client = TestClient(create_app(service.store))
    data = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison").json()["data"]
    assert data["comparison_scope"]["aggregate_status"] == "not_compared"
    human = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison.html")
    assert "nicht verglichen" in human.text.lower()
    assert "Keine Abweichung." not in human.text


def test_not_compared_is_explicit_in_csv(tmp_path):
    import csv
    import io

    service = _service(tmp_path)
    submitted, _ = _submitted_synthetic(service)
    with service.store.connect() as con:
        con.execute("update tax_filing_snapshots set summary_json='{}' where snapshot_id=?", [submitted.snapshot_id])
    client = TestClient(create_app(service.store))
    csv_response = client.get("/api/v1/export/tax-years/2025/filing-snapshot-comparison.csv")
    assert csv_response.status_code == 200
    assert "not_compared" in csv_response.text
    row = next(csv.DictReader(io.StringIO(csv_response.text)))
    assert row["Aggregate_Status"] == "not_compared"
    assert row["Delta_EUR"] == ""
    assert "Keine Abweichung." not in csv_response.text


def test_old_comparison_response_deserializes_without_scope(tmp_path):
    service = _service(tmp_path)
    old = service.comparison(2025).model_dump()
    del old["comparison_scope"]
    restored = TaxFilingSnapshotComparison.model_validate(old)
    assert restored.comparison_scope is None
