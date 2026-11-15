"""Synthetische Gegenbeispiele ohne Paket- oder Feldlisten des Produktivcodes."""

from decimal import Decimal
import hashlib
import io
import json
import zipfile

import pytest

from steuerreport_v2.contracts.tax_filing_snapshots import (
    TaxFilingSnapshotCaptureRequest,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_snapshots import (
    SUBMISSION_CONFIRMATION_TEXT,
    TaxFilingSnapshotError,
    TaxFilingSnapshotService,
)
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService


SUMMARY_PATH = "02_Steuerliche_CSVs/tax-year-2025-filing-summary.json"
MANIFEST_PATH = "00_Manifest/year-evidence-manifest.json"


def _summary():
    return {
        "year": 2025,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "export_ready": False,
        "taxable_private_disposals_eur": "100.000000000000000001",
        "taxable_disposal_proceeds_eur": "140",
        "acquisition_cost_eur": "40",
        "rewards_mining_staking_income_eur": "7",
        "derivative_pnl_eur": "-3",
        "tax_free_private_disposals_eur": "2",
        "tax_free_lines_count": 1,
    }


def _archive(summary, *, manifest_change=None, summary_bytes=None):
    content = (
        summary_bytes if summary_bytes is not None else json.dumps(summary).encode()
    )
    manifest = {
        "year": 2025,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "files": [
            {
                "path": SUMMARY_PATH,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    if manifest_change:
        manifest_change(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(MANIFEST_PATH, json.dumps(manifest))
        package.writestr(SUMMARY_PATH, content)
        package.writestr("evidence.txt", b"synthetic")
    return output.getvalue()


@pytest.fixture
def service(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    return TaxFilingSnapshotService(store)


def _capture(service, content):
    return service.capture_package(
        year=2025,
        package_bytes=content,
        request=TaxFilingSnapshotCaptureRequest(),
        source_kind="synthetic-independent",
    ).snapshot


def _zero_summary():
    summary = _summary()
    for field in ("taxable_private_disposals_eur", "taxable_disposal_proceeds_eur",
                  "acquisition_cost_eur", "rewards_mining_staking_income_eur",
                  "derivative_pnl_eur", "tax_free_private_disposals_eur"):
        summary[field] = "0"
    summary["tax_free_lines_count"] = 0
    return summary


def _stored_derivative(service, value):
    with service.store.connect() as con:
        con.execute("""insert into derivative_lines
            (derivative_line_id, event_id, source, event_time, asset, quantity,
             price_eur, value_eur, price_source, created_at)
            values ('synthetic-line', 'synthetic-event', 'synthetic',
                    '2025-06-02', 'EUR', 1, 1, ?, 'synthetic', '2025-06-02')""", [value])


@pytest.mark.parametrize("value, delta", [("1.005", "0.001"), ("1.006", "0.002")])
def test_cent_boundary_compares_rounded_amounts_not_rounded_delta(service, value, delta):
    summary = _zero_summary()
    summary["derivative_pnl_eur"] = "1.004"
    reference = _capture(service, _archive(summary))
    _submit(service, reference)
    _stored_derivative(service, value)
    report = service.comparison(2025)
    row = next(item for item in report.deltas if item.key == "derivative_pnl_eur")
    assert row.delta_eur == Decimal(delta)
    assert row.rounded_amount_delta_eur == Decimal("0.01")
    assert row.changed_at_cent_precision is True
    assert report.declaration_change_detected is True
    assert report.amendment_review_required is True
    assert report.status == "changed_review_required"
    from fastapi.testclient import TestClient
    from steuerreport_v2.api.app import create_app
    human = TestClient(create_app(service.store)).get("/api/v1/tax-years/2025/filing-snapshot-comparison.html")
    assert human.status_code == 200
    assert "<td>1,00 EUR</td>" in human.text
    assert "<td>1,01 EUR</td>" in human.text


def test_derivative_aggregation_retains_fraction_before_delta(service):
    summary = _zero_summary()
    summary["derivative_pnl_eur"] = "10000000000"
    _capture(service, _archive(summary))
    _stored_derivative(service, "10000000000.000000000000000001")
    report = service.comparison(2025)
    assert report.current_values.derivative_pnl_eur == Decimal("10000000000.000000000000000001")
    assert report.comparison_scope.aggregate_status == "different"
    assert report.exact_change_detected is True
    row = next(item for item in report.deltas if item.key == "derivative_pnl_eur")
    assert row.delta_eur == Decimal("0.000000000000000001")
    assert row.changed_at_cent_precision is False


def test_aggregate_delta_does_not_round_through_default_decimal_precision(service):
    old = _zero_summary()
    new = _zero_summary()
    old["taxable_private_disposals_eur"] = "1000000000000000000.123456789012345678"
    new["taxable_private_disposals_eur"] = "-1000000000000000000.123456789012345678"
    rows = service._deltas(service._values_from_mapping(old), service._values_from_mapping(new))
    row = next(item for item in rows if item.key == "taxable_private_disposals_eur")
    assert row.delta_eur == Decimal("-2000000000000000000.246913578024691356")


def test_extreme_current_value_is_not_silently_rounded_or_compared(service, monkeypatch):
    summary = _zero_summary()
    summary["taxable_private_disposals_eur"] = "1e1000000"
    current = service._values_from_mapping(summary)
    _capture(service, _archive(_zero_summary()))
    monkeypatch.setattr("steuerreport_v2.domain.tax_years.TaxYearService.filing_aggregate_values", lambda *args: current)
    report = service.comparison(2025)
    assert report.comparison_scope.aggregate_status == "not_compared"
    assert report.exact_change_detected is None and report.deltas == []
    assert "technischen Praezisionsbereichs" in report.next_action


@pytest.mark.parametrize("amount", ["1e1000000", "1e-1000000", "1.0000000000000000001"])
def test_unrepresentable_reference_is_rejected_before_archive_or_register(service, amount):
    summary = _zero_summary()
    summary["taxable_private_disposals_eur"] = amount
    with pytest.raises(TaxFilingSnapshotError):
        _capture(service, _archive(summary))
    assert service.list().snapshots == []
    assert not list(service.archive_root.glob("**/*.zip"))


def test_largest_exact_storable_reference_is_preserved(service):
    value = Decimal("99999999999999999999.999999999999999999")
    summary = _zero_summary()
    summary["taxable_private_disposals_eur"] = str(value)
    captured = _capture(service, _archive(summary))
    assert service.get(captured.snapshot_id).values.taxable_private_disposals_eur == value
    report = service.comparison(2025)
    row = next(item for item in report.deltas if item.key == "taxable_private_disposals_eur")
    assert row.delta_eur == value.copy_negate()


def test_fresh_aggregate_comparison_does_not_call_full_summary_or_artifact_services(service, monkeypatch):
    content = _archive(_zero_summary())
    snapshot = _capture(service, content)
    def forbidden(*args, **kwargs):
        pytest.fail("Full summary or artifact path must not run")
    from steuerreport_v2.domain.tax_years import TaxYearService
    monkeypatch.setattr(TaxYearService, "filing_summary", forbidden)
    monkeypatch.setattr(TaxYearService, "bmf_closure_appendix", forbidden)
    monkeypatch.setattr(TaxYearService, "declaration_guide", forbidden)
    report = service.comparison(2025)
    assert report.comparison_scope.aggregate_status == "equal"
    assert report.comparison_scope.current_aggregate_binding == "read_transaction"
    assert report.comparison_scope.reference_aggregate_binding == "verified_archive"
    assert report.exact_change_detected is False
    assert len(report.deltas) == 6 and all(item.delta_eur == 0 for item in report.deltas)
    assert report.comparison_scope.events == "not_compared"
    assert service.read_package(snapshot.snapshot_id) == content


def test_real_stored_tax_line_produces_exact_aggregate_deltas(service):
    content = _archive(_zero_summary())
    _capture(service, content)
    with service.store.connect() as con:
        con.execute("""insert into tax_lots
            (lot_id, asset, acquired_at, quantity_total, quantity_remaining,
             cost_basis_eur_total, source_event_id, created_at)
            values ('synthetic-lot', 'SYNTH', '2025-05-28', 1, 0, 20,
                    'synthetic-acquisition', '2025-05-28')""")
        con.execute("""insert into tax_lines
            (tax_line_id, asset, disposed_at, quantity, acquisition_cost_eur,
             disposal_proceeds_eur, gain_loss_eur, holding_days, source_event_id, lot_id, created_at)
            values ('synthetic-line', 'SYNTH', '2025-06-02', 1, 20, 50, 30, 5,
                    'synthetic-source', 'synthetic-lot', '2025-06-02')""")
    report = service.comparison(2025)
    deltas = {row.key: row.delta_eur for row in report.deltas}
    assert report.comparison_scope.aggregate_status == "different"
    assert deltas["taxable_private_disposals_eur"] == Decimal("30")
    assert deltas["taxable_disposal_proceeds_eur"] == Decimal("50")
    assert deltas["acquisition_cost_eur"] == Decimal("20")
    assert report.exact_change_detected is True
    assert report.comparison_scope.detail_reconciliation == "not_compared"


def test_aggregate_comparison_does_not_mix_interleaved_database_versions(service, monkeypatch):
    from fastapi.testclient import TestClient
    from steuerreport_v2.api.app import create_app
    from steuerreport_v2.domain.tax_years import TaxYearService

    _capture(service, _archive(_zero_summary()))
    writer = DuckDbStore(service.store.path)
    writer.health()
    original = TaxYearService._income_totals_by_year
    changed = False
    def interleave(years):
        nonlocal changed
        if not changed:
            changed = True
            with writer.connect() as con:
                con.execute("""insert into derivative_lines
                    (derivative_line_id, event_id, source, event_time, asset, quantity,
                     price_eur, value_eur, price_source, created_at)
                    values ('synthetic-derivative', 'synthetic-event', 'synthetic',
                            '2025-06-02', 'EUR', 10, 1, 10, 'synthetic', '2025-06-02')""")
        return original(years)
    monkeypatch.setattr(TaxYearService, "_income_totals_by_year", interleave)
    monkeypatch.setattr(TaxYearService, "filing_summary", lambda *args: pytest.fail("API must not use cached full summary"))
    client = TestClient(create_app(service.store))
    first = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison").json()["data"]
    assert changed
    assert Decimal(first["current_values"]["derivative_pnl_eur"]) == Decimal("0")
    assert first["comparison_scope"]["aggregate_status"] == "equal"
    second = client.get("/api/v1/tax-years/2025/filing-snapshot-comparison").json()["data"]
    assert Decimal(second["current_values"]["derivative_pnl_eur"]) == Decimal("10")
    assert second["comparison_scope"]["aggregate_status"] == "different"


def test_each_reference_amount_comes_from_verified_archive_not_numeric_columns(service):
    content = _archive(_summary())
    snapshot = _capture(service, content)
    with service.store.connect() as con:
        con.execute(
            "update tax_filing_snapshots set taxable_private_disposals_eur = 0, "
            "rewards_mining_staking_income_eur = 0 where snapshot_id = ?",
            [snapshot.snapshot_id],
        )
    values = service.get(snapshot.snapshot_id).values
    assert values.taxable_private_disposals_eur == Decimal("100.000000000000000001")
    assert values.taxable_disposal_proceeds_eur == Decimal("140")
    assert values.acquisition_cost_eur == Decimal("40")
    assert values.rewards_mining_staking_income_eur == Decimal("7")
    assert values.derivative_pnl_eur == Decimal("-3")
    assert values.tax_free_private_disposals_eur == Decimal("2")
    assert service.read_package(snapshot.snapshot_id) == content


@pytest.mark.parametrize(
    "field",
    [
        "taxable_private_disposals_eur",
        "taxable_disposal_proceeds_eur",
        "acquisition_cost_eur",
        "rewards_mining_staking_income_eur",
        "derivative_pnl_eur",
        "tax_free_private_disposals_eur",
    ],
)
def test_db_only_summary_mutation_cannot_supply_trusted_reference(service, field):
    content = _archive(_summary())
    snapshot = _capture(service, content)
    forged = _summary()
    forged[field] = "0"
    with service.store.connect() as con:
        con.execute(
            "update tax_filing_snapshots set summary_json = ? where snapshot_id = ?",
            [json.dumps(forged), snapshot.snapshot_id],
        )
    report = service.comparison(2025)
    assert report.baseline.integrity_status == "verified"
    assert report.baseline.values is None
    assert report.deltas == []
    assert report.comparison_scope.aggregate_status == "not_compared"
    assert report.exact_change_detected is None
    assert service.read_package(snapshot.snapshot_id) == content


@pytest.mark.parametrize(
    "bad", [None, True, [], {}, "NaN", "Infinity", "-Infinity", "invalid"]
)
def test_new_capture_rejects_invalid_amounts_before_registering(service, bad):
    summary = _summary()
    summary["acquisition_cost_eur"] = bad
    with pytest.raises(TaxFilingSnapshotError):
        _capture(service, _archive(summary))
    assert service.list().snapshots == []
    assert not service.archive_root.exists()


@pytest.mark.parametrize(
    "field",
    [
        "taxable_private_disposals_eur",
        "taxable_disposal_proceeds_eur",
        "acquisition_cost_eur",
        "rewards_mining_staking_income_eur",
        "derivative_pnl_eur",
        "tax_free_private_disposals_eur",
        "tax_free_lines_count",
    ],
)
def test_new_capture_never_substitutes_zero_for_missing_values(service, field):
    summary = _summary()
    del summary[field]
    with pytest.raises(TaxFilingSnapshotError):
        _capture(service, _archive(summary))
    assert service.list().snapshots == []


def test_unmanifested_summary_is_rejected_even_when_zip_hash_would_match(service):
    def omit_summary(manifest):
        manifest["files"] = [
            {
                "path": "evidence.txt",
                "size_bytes": 9,
                "sha256": hashlib.sha256(b"synthetic").hexdigest(),
            }
        ]

    with pytest.raises(TaxFilingSnapshotError):
        _capture(service, _archive(_summary(), manifest_change=omit_summary))


def test_duplicate_manifest_summary_entry_is_not_an_unambiguous_binding(service):
    def duplicate(manifest):
        manifest["files"] *= 2

    with pytest.raises(TaxFilingSnapshotError):
        _capture(service, _archive(_summary(), manifest_change=duplicate))


def test_duplicate_summary_json_key_is_rejected(service):
    raw = json.dumps(_summary()).encode()
    raw = raw[:-1] + b', "acquisition_cost_eur": "0"}'
    with pytest.raises(TaxFilingSnapshotError):
        _capture(service, _archive(None, summary_bytes=raw))


def test_fractional_json_number_is_not_rounded_through_float(service):
    raw = (
        json.dumps(_summary())
        .replace('"100.000000000000000001"', "100.000000000000000001")
        .encode()
    )
    snapshot = _capture(service, _archive(None, summary_bytes=raw))
    assert snapshot.values.taxable_private_disposals_eur == Decimal(
        "100.000000000000000001"
    )


@pytest.mark.parametrize("summary", [[], {}, "invalid"])
def test_invalid_current_summary_input_does_not_crash_or_invent_zero(service, summary):
    _capture(service, _archive(_summary()))
    report = service.comparison(2025, current_summary=summary)
    assert report.current_values is None
    assert report.comparison_scope.aggregate_status == "not_compared"


def _install_legacy_content(service, snapshot, content, summary):
    """Historischen Registerstand unabhaengig vom neuen Capture-Pfad aufbauen."""
    path = service.archive_root / "2025" / f"{snapshot.package_sha256}.zip"
    path.chmod(0o644)
    path.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        manifest_hash = hashlib.sha256(package.read(MANIFEST_PATH)).hexdigest()
    with service.store.connect() as con:
        con.execute(
            "update tax_filing_snapshots set package_sha256 = ?, manifest_sha256 = ?, "
            "summary_json = ?, package_size_bytes = ? where snapshot_id = ?",
            [
                hashlib.sha256(content).hexdigest(),
                manifest_hash,
                json.dumps(summary),
                len(content),
                snapshot.snapshot_id,
            ],
        )


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "null",
        "invalid",
        "nonfinite",
        "wrong_year",
        "fractional_year",
        "null_year",
        "unmanifested",
        "file_hash",
        "file_size",
        "duplicate_entry",
        "duplicate_json_key",
    ],
)
def test_verified_legacy_zip_never_exposes_unbound_or_invalid_values(service, kind):
    snapshot = _capture(service, _archive(_summary()))
    summary = _summary()
    change = None
    raw = None
    if kind == "missing":
        del summary["acquisition_cost_eur"]
    elif kind in ("null", "invalid", "nonfinite"):
        summary["acquisition_cost_eur"] = {
            "null": None,
            "invalid": "invalid",
            "nonfinite": "NaN",
        }[kind]
    elif kind in ("wrong_year", "fractional_year", "null_year"):
        summary["year"] = {
            "wrong_year": 2024,
            "fractional_year": 2025.1,
            "null_year": None,
        }[kind]
    elif kind == "unmanifested":

        def change(manifest):
            manifest["files"] = [
                {
                    "path": "evidence.txt",
                    "size_bytes": 9,
                    "sha256": hashlib.sha256(b"synthetic").hexdigest(),
                }
            ]
    elif kind == "file_hash":

        def change(manifest):
            manifest["files"][0]["sha256"] = "0" * 64
    elif kind == "file_size":

        def change(manifest):
            manifest["files"][0]["size_bytes"] += 1
    elif kind == "duplicate_entry":

        def change(manifest):
            manifest["files"] *= 2
    elif kind == "duplicate_json_key":
        raw = json.dumps(summary).encode()[:-1] + b', "acquisition_cost_eur": "0"}'
    content = _archive(summary, manifest_change=change, summary_bytes=raw)
    _install_legacy_content(service, snapshot, content, summary)
    for report in (service.get(snapshot.snapshot_id), service.list().snapshots[0]):
        assert report.integrity_status == "verified"
        assert report.values is None
    comparison = service.comparison(2025)
    assert comparison.baseline.values is None
    assert comparison.comparison_scope.aggregate_status == "not_compared"
    assert comparison.exact_change_detected is None
    assert service.read_package(snapshot.snapshot_id) == content


def test_manifest_registry_hash_is_part_of_reference_binding(service):
    snapshot = _capture(service, _archive(_summary()))
    with service.store.connect() as con:
        con.execute(
            "update tax_filing_snapshots set manifest_sha256 = ? where snapshot_id = ?",
            ["0" * 64, snapshot.snapshot_id],
        )
    actual = service.get(snapshot.snapshot_id)
    assert actual.integrity_status == "verified"
    assert actual.values is None


def test_explicit_zero_amounts_remain_distinct_from_unavailable_values(service):
    summary = _summary()
    for key in (
        "taxable_private_disposals_eur",
        "taxable_disposal_proceeds_eur",
        "acquisition_cost_eur",
        "rewards_mining_staking_income_eur",
        "derivative_pnl_eur",
        "tax_free_private_disposals_eur",
    ):
        summary[key] = "0"
    snapshot = _capture(service, _archive(summary))
    assert snapshot.values is not None
    assert snapshot.values.acquisition_cost_eur == Decimal("0")
    comparison = service.comparison(2025)
    assert comparison.comparison_scope.aggregate_status == "equal"
    assert comparison.exact_change_detected is False


def _submit(service, reference):
    return service.capture_from_snapshot(
        year=2025,
        request=TaxFilingSnapshotCaptureRequest(
            state="submitted",
            source_snapshot_id=reference.snapshot_id,
            submitted_at="2026-01-02T00:00:00+00:00",
            confirmation_text=SUBMISSION_CONFIRMATION_TEXT,
        ),
    ).snapshot


def test_archive_100_register_0_current_0_is_not_a_proven_equal(service):
    summary = _summary()
    for key in (
        "taxable_private_disposals_eur",
        "taxable_disposal_proceeds_eur",
        "acquisition_cost_eur",
        "rewards_mining_staking_income_eur",
        "derivative_pnl_eur",
        "tax_free_private_disposals_eur",
    ):
        summary[key] = "0"
    summary["taxable_private_disposals_eur"] = "100"
    content = _archive(summary)
    submitted = _submit(service, _capture(service, content))
    summary["taxable_private_disposals_eur"] = "0"
    with service.store.connect() as con:
        con.execute(
            "update tax_filing_snapshots set summary_json = ? where snapshot_id = ?",
            [json.dumps(summary), submitted.snapshot_id],
        )
    report = service.comparison(2025)
    assert report.current_values.taxable_private_disposals_eur == Decimal("0")
    assert report.baseline.integrity_status == "verified"
    assert report.comparison_scope.aggregate_status == "not_compared"
    assert report.baseline.values is None
    assert report.exact_change_detected is None
    assert report.status == "comparison_unavailable"
    assert service.read_package(submitted.snapshot_id) == content


def test_methodology_never_silently_falls_back_to_older_confirmed_reference(service):
    older = _submit(service, _capture(service, _archive(_summary())))
    summary = _summary()
    summary["taxable_private_disposals_eur"] = "200"
    newer = _submit(service, _capture(service, _archive(summary)))
    assert newer.revision > older.revision
    with service.store.connect() as con:
        con.execute(
            "update tax_filing_snapshots set summary_json = 'null' where snapshot_id = ?",
            [newer.snapshot_id],
        )
    assert service.get(older.snapshot_id).values is not None
    assert (
        2025
        not in TaxMethodologyService(service.store)._confirmed_filing_snapshot_amounts()
    )


def test_current_summary_service_returning_none_is_unavailable(service, monkeypatch):
    monkeypatch.setattr(
        "steuerreport_v2.domain.tax_filing_snapshots.TaxYearService.filing_aggregate_values",
        lambda *args: None,
    )
    report = service.comparison(2025)
    assert report.current_values is None
    assert report.comparison_scope.aggregate_status == "not_compared"
