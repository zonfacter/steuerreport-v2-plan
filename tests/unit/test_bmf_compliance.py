from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate
from steuerreport_v2.contracts.wallet_fifo_runs import WalletFifoParallelRunRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_compliance import BmfComplianceMatrixService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService
from steuerreport_v2.domain.wallet_fifo_migrations import (
    WalletFifoMigrationRehearsalService,
)


def test_bmf_compliance_matrix_never_claims_strict_ready_without_required_artifacts(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    matrix = BmfComplianceMatrixService(store).matrix()

    assert matrix.strict_bmf_ready is False
    assert matrix.strict_ready_years == []
    assert matrix.matrix_version == "bmf_requirements_2025_v13"
    assert matrix.requirements_count == len(matrix.requirements)
    assert matrix.blocked_count >= 3
    by_id = {item.requirement_id: item for item in matrix.requirements}
    assert by_id["current_legal_sources"].evidence_status == "blocked"
    assert by_id["filing_snapshot_immutability"].evidence_status == "satisfied"
    assert by_id["wallet_fifo"].implementation_status == "partial"
    assert by_id["wallet_fifo"].evidence_status == "blocked"
    assert by_id["source_completeness"].evidence_status == "blocked"
    source_metrics = {
        metric.key: metric for metric in by_id["source_completeness"].metrics
    }
    assert source_metrics["source_registry_provider_coverage_gaps"].value == 0
    assert source_metrics["source_registry_user_evidence_gaps"].value == 0
    assert source_metrics["source_registry_documented_routes"].value == 0
    assert by_id["as_of_holdings_and_source_of_funds"].evidence_status == "blocked"
    assert by_id["transaction_traceability"].evidence_status == "not_applicable"
    assert by_id["business_private_tax_sphere"].evidence_status == "not_applicable"
    price_parallel = next(
        metric
        for metric in by_id["price_consistency"].metrics
        if metric.key == "crypto_swap_fifo_parallel"
    )
    assert price_parallel.value == "missing"
    assert price_parallel.status == "blocked"
    combined_staging = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "bmf_combined_fifo_staging"
    )
    assert combined_staging.value == "missing"
    assert combined_staging.status == "blocked"
    bitget_reconstruction = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "bitget_strategy_basis_reconstruction"
    )
    assert bitget_reconstruction.value == "missing"
    assert bitget_reconstruction.status == "blocked"
    bitget_basis_decision = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "bitget_strategy_basis_decision"
    )
    assert bitget_basis_decision.value == "pending"
    assert bitget_basis_decision.status == "blocked"
    assert by_id["time_and_precision"].implementation_status == "implemented"
    assert by_id["time_and_precision"].evidence_status == "satisfied"


def test_bmf_compliance_matrix_surfaces_traceable_tax_lines_but_keeps_wallet_fifo_blocker(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="buy-1",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="sell-1",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-0.5"),
                quote_asset="EUR",
                quote_quantity=Decimal("75"),
                fee_asset="EUR",
                fee_quantity=Decimal("1"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    WalletFifoParallelRunService(store).run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    WalletFifoMigrationRehearsalService(store).rehearse()

    matrix = BmfComplianceMatrixService(store).matrix()

    by_id = {item.requirement_id: item for item in matrix.requirements}
    traceability = by_id["transaction_traceability"]
    assert traceability.evidence_status == "satisfied"
    assert next(metric for metric in traceability.metrics if metric.key == "tax_lines").value == 1
    assert next(metric for metric in traceability.metrics if metric.key == "orphan_tax_lines").value == 0
    assert by_id["wallet_fifo"].evidence_status == "blocked"
    method_delta = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "wallet_fifo_method_delta_explanation"
    )
    assert method_delta.value == "ready_for_method_review"
    assert method_delta.status == "satisfied"
    method_acceptance = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "wallet_fifo_method_acceptance"
    )
    assert method_acceptance.value == "pending"
    assert method_acceptance.status == "review"
    assert "Entscheidungsreif: True" in method_acceptance.detail
    migration_rehearsal = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "wallet_fifo_migration_rehearsal"
    )
    assert migration_rehearsal.value == "ready_for_method_decision"
    assert migration_rehearsal.status == "review"
    bitget_reconstruction = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "bitget_strategy_basis_reconstruction"
    )
    assert bitget_reconstruction.value == "no_gap"
    assert bitget_reconstruction.status == "satisfied"
    bitget_basis_decision = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "bitget_strategy_basis_decision"
    )
    assert bitget_basis_decision.value == "pending"
    assert bitget_basis_decision.status == "satisfied"
    unmatched_classification = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "wallet_fifo_unmatched_classification"
    )
    assert unmatched_classification.value == (
        "wallet_fifo_run_v2_provider_basis_classification"
    )
    assert unmatched_classification.status == "satisfied"
    provider_basis_gaps = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "wallet_fifo_provider_basis_gaps"
    )
    assert provider_basis_gaps.value == 0
    assert provider_basis_gaps.status == "satisfied"
    unexplained_unmatched = next(
        metric
        for metric in by_id["wallet_fifo"].metrics
        if metric.key == "wallet_fifo_unexplained_unmatched"
    )
    assert unexplained_unmatched.value == 0
    assert unexplained_unmatched.status == "satisfied"
    assert matrix.scope_years == [2025]
    assert matrix.blocked_years == [2025]
    assert matrix.strict_bmf_ready is False


def test_bmf_compliance_matrix_api_endpoint(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    response = TestClient(create_app(store)).get("/api/v1/tax-methodology/bmf-compliance-matrix")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["strict_bmf_ready"] is False
    assert data["matrix_version"] == "bmf_requirements_2025_v13"
    assert any(item["requirement_id"] == "wallet_fifo" for item in data["requirements"])


def test_bmf_evidence_access_is_satisfied_when_required_artifacts_are_available(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.create_import_batch(
        ImportBatchCreate(source="binance", filename="original.csv", file_hash="original")
    )
    artifact_root = tmp_path / "var"
    artifact_paths = [
        artifact_root / "wallet_fifo_runs/latest_wallet_fifo_run.json",
        artifact_root / "source_registry/latest_source_registry.json",
        artifact_root / "valuation_runs/latest_valuation_gate.json",
    ]
    for path in artifact_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"status":"blocked","strict_ready":false}', encoding="utf-8")
    artifact_paths[1].write_text(
        '{"status":"blocked","strict_ready":false,'
        '"provider_coverage_gap_entries_count":2,'
        '"user_evidence_gap_entries_count":1,'
        '"documented_route_entries_count":1}',
        encoding="utf-8",
    )

    matrix = BmfComplianceMatrixService(store).matrix()

    requirement = next(
        item for item in matrix.requirements if item.requirement_id == "evidence_and_data_access"
    )
    assert requirement.implementation_status == "implemented"
    assert requirement.evidence_status == "satisfied"
    assert requirement.strict_ready is True
    governance = next(metric for metric in requirement.metrics if metric.key == "governance_snapshots")
    assert governance.value == "3/3"
    source_requirement = next(
        item for item in matrix.requirements if item.requirement_id == "source_completeness"
    )
    source_metrics = {metric.key: metric for metric in source_requirement.metrics}
    assert source_metrics["source_registry_provider_coverage_gaps"].value == 2
    assert source_metrics["source_registry_provider_coverage_gaps"].status == "review"
    assert source_metrics["source_registry_user_evidence_gaps"].value == 1
    assert source_metrics["source_registry_user_evidence_gaps"].status == "blocked"
    assert source_metrics["source_registry_documented_routes"].value == 1
    assert source_metrics["source_registry_documented_routes"].status == "satisfied"
