from datetime import datetime, timezone
from decimal import Decimal
import gzip
import json

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.tax_wallet_fifo import WalletFifoPreviewLine
from steuerreport_v2.contracts.wallet_fifo_runs import WalletFifoParallelRunRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


def _clean_fifo_store(tmp_path) -> DuckDbStore:
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
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
                event_time=datetime(2025, 6, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("150"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    return store


def test_wallet_fifo_preview_as_of_excludes_later_events_and_global_lines(tmp_path):
    store = _clean_fifo_store(tmp_path)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 12, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("200"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 12, 15, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("300"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    cutoff = datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

    report = WalletFifoPreviewService(store).preview(year=2025, as_of=cutoff)

    assert report.as_of == cutoff
    assert report.input_events_count == 2
    assert report.tax_lines_count == 1
    assert report.global_gain_loss_eur == Decimal("50")
    assert report.wallet_gain_loss_eur == Decimal("50")
    assert report.delta_gain_loss_eur == Decimal("0")
    assert report.year_summaries[0].global_tax_lines_count == 1


def test_wallet_fifo_parallel_run_writes_versioned_read_only_evidence(tmp_path, monkeypatch):
    store = _clean_fifo_store(tmp_path)
    artifact_root = tmp_path / "wallet-fifo-artifacts"
    service = WalletFifoParallelRunService(store, artifact_root=artifact_root)
    request = WalletFifoParallelRunRequest(
        years=[2025],
        as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    )

    report = service.run(request)

    assert report.status == "ready_for_method_review"
    assert report.strict_ready is False
    assert report.method_acceptance_required is True
    assert report.delta_gain_loss_eur == Decimal("0")
    assert report.input_fingerprint.canonical_events_count == 2
    assert report.all_lots_count == 1
    assert len(report.evidence_files) == 13
    assert report.bitget_strategy_gap_status == "no_gap"
    assert report.bitget_strategy_gap_quantity_reconciled is False
    assert report.bitget_strategy_gap_groups_count == 0
    assert report.bitget_strategy_reconstruction_status == "no_gap"
    assert report.bitget_strategy_reconstruction_groups_count == 0
    assert any(
        item.kind == "bitget_strategy_basis_reconstruction"
        for item in report.evidence_files
    )
    assert any(
        item.kind == "bitget_strategy_basis_reconstruction_csv"
        for item in report.evidence_files
    )
    assert report.event_set_parity_years == [2025]
    assert report.event_set_mismatch_years == []
    assert report.year_results[0].event_set_parity is True
    assert report.year_results[0].asset_reconciliations[0].classification == "exact_match"
    assert (artifact_root / "latest_wallet_fifo_run.json").exists()
    assert service.latest() is not None
    tax_lines_file = next(item for item in report.evidence_files if item.kind == "wallet_fifo_tax_lines")
    tax_lines_path = artifact_root / report.run_id / "wallet_fifo_tax_lines.csv.gz"
    assert tax_lines_file.records_count == 1
    assert tax_lines_file.download_url
    with gzip.open(tax_lines_path, "rt", encoding="utf-8") as handle:
        content = handle.read()
    assert "source_event_id" in content
    assert "acquisition_source_event_id" in content
    assert "BTC" in content
    all_lots_file = next(
        item for item in report.evidence_files if item.kind == "wallet_fifo_all_lots"
    )
    assert all_lots_file.records_count == 1
    assert all_lots_file.download_url
    reconciliation_file = next(
        item for item in report.evidence_files if item.kind == "wallet_fifo_asset_reconciliation"
    )
    assert reconciliation_file.records_count == 1
    delta_report = service.method_delta_explanation(
        run_id=report.run_id,
        year=2025,
    )
    assert delta_report is not None
    assert delta_report.status == "ready_for_method_review"
    assert delta_report.extra_turnover_detected is False
    assert delta_report.groups[0].drivers == ["exact_match"]
    assert report.method_delta_explanation_url

    with store.connect() as con:
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 1
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 1

    repeated = service.run(request)
    repeated_delta = service.method_delta_explanation(run_id=repeated.run_id)
    assert repeated.semantic_sha256 == report.semantic_sha256
    assert repeated_delta is not None
    assert repeated_delta.semantic_sha256 == delta_report.semantic_sha256

    WalletFifoPreviewService._PREVIEW_CACHE.clear()

    def fail_tax_service(*_args, **_kwargs):
        raise AssertionError("cache hit should not initialize the price-backed TaxService")

    monkeypatch.setattr("steuerreport_v2.domain.tax_wallet_fifo.TaxService", fail_tax_service)
    cached_preview_service = WalletFifoPreviewService(store)

    def fail_replay(*_args, **_kwargs):
        raise AssertionError("versioned run should seed the fingerprinted preview disk cache")

    monkeypatch.setattr(cached_preview_service, "replay", fail_replay)
    cached_preview = cached_preview_service.preview(year=2025)
    assert cached_preview.global_gain_loss_eur == report.global_gain_loss_eur
    assert cached_preview.method_version == report.method_version
    cached_all_years = cached_preview_service.preview()
    assert cached_all_years.global_gain_loss_eur == report.global_gain_loss_eur
    assert cached_all_years.method_version == report.method_version

    reusable = service.find_reusable_run(request)
    assert reusable is not None
    assert reusable.run_id == repeated.run_id
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 7, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("1"),
                account="Spot",
            )
        ]
    )
    assert service.find_reusable_run(request) is None


def test_wallet_fifo_input_fingerprint_is_stable_across_fifo_rebuild(tmp_path):
    store = _clean_fifo_store(tmp_path)
    service = WalletFifoParallelRunService(store)
    as_of = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    before = service.input_fingerprint(as_of)
    TaxService(store).rebuild_fifo()
    after = service.input_fingerprint(as_of)

    assert before.fingerprint_version == "wallet_fifo_input_v3_nonfinancial_updates_excluded"
    assert before.component_sha256
    assert after.digest == before.digest
    assert after.component_sha256 == before.component_sha256


def test_wallet_fifo_method_acceptance_is_bound_and_does_not_activate_fifo(tmp_path):
    store = _clean_fifo_store(tmp_path)
    run = WalletFifoParallelRunService(store).run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    client = TestClient(create_app(store))

    readiness = client.get(
        f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-acceptance"
    )
    accepted = client.post(
        f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-acceptance",
        json={
            "decision": "approved_for_controlled_migration",
            "rationale": "Die gebundene Methodenakte wurde fachlich geprueft und soll kontrolliert migriert werden.",
            "actor": "unit-test",
            "acknowledge_material_tax_delta": True,
            "acknowledge_consistent_application": True,
            "acknowledge_no_automatic_activation": True,
        },
    )
    repeated = client.post(
        f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-acceptance",
        json={
            "decision": "approved_for_controlled_migration",
            "rationale": "Die gebundene Methodenakte wurde fachlich geprueft und soll kontrolliert migriert werden.",
            "actor": "unit-test",
            "acknowledge_material_tax_delta": True,
            "acknowledge_consistent_application": True,
            "acknowledge_no_automatic_activation": True,
        },
    )

    assert readiness.status_code == 200
    assert readiness.json()["data"]["decision_ready"] is True
    assert readiness.json()["data"]["input_fingerprint_current"] is True
    assert accepted.status_code == 200
    assert accepted.json()["data"]["created"] is True
    accepted_report = accepted.json()["data"]["report"]
    assert accepted_report["decision_status"] == "approved_for_controlled_migration"
    assert accepted_report["method_acceptance_required"] is False
    assert accepted_report["activation_applied"] is False
    assert accepted_report["activation_ready"] is False
    assert accepted_report["strict_ready"] is False
    assert repeated.status_code == 200
    assert repeated.json()["data"]["created"] is False
    assert repeated.json()["data"]["decision_id"] == accepted.json()["data"]["decision_id"]
    assert WalletFifoMethodAcceptanceService(store).readiness(
        run_id=run.run_id
    ).input_fingerprint_current is True
    with store.connect() as con:
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 1
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 1


def test_wallet_fifo_method_acceptance_binds_full_delta_artifact(tmp_path):
    store = _clean_fifo_store(tmp_path)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("24"),
                quote_asset="EUR",
                quote_quantity=Decimal("2400"),
                account="Spot",
            ),
            *[
                CanonicalEventCreate(
                    source="binance",
                    event_time=datetime(2025, 7, day, tzinfo=timezone.utc),
                    event_type="trade",
                    asset="BTC",
                    quantity=Decimal("-1"),
                    quote_asset="EUR",
                    quote_quantity=Decimal("150"),
                    account="Spot",
                )
                for day in range(1, 25)
            ],
        ]
    )
    TaxService(store).rebuild_fifo()
    run = WalletFifoParallelRunService(store).run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )

    report = WalletFifoMethodAcceptanceService(store).readiness(run_id=run.run_id)

    assert report.input_fingerprint_current is True
    assert report.decision_ready is True
    assert next(
        check for check in report.checks if check.key == "method_delta_bound"
    ).passed is True


def test_wallet_fifo_method_acceptance_blocks_approval_for_unmatched_run(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 6, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("150"),
                account="Spot",
            )
        ]
    )
    TaxService(store).rebuild_fifo()
    run = WalletFifoParallelRunService(store).run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    client = TestClient(create_app(store))

    response = client.post(
        f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-acceptance",
        json={
            "decision": "approved_for_controlled_migration",
            "rationale": "Dieser blockierte Lauf darf keine Methodenfreigabe erzeugen koennen.",
            "actor": "unit-test",
            "acknowledge_material_tax_delta": True,
            "acknowledge_consistent_application": True,
            "acknowledge_no_automatic_activation": True,
        },
    )

    assert run.status == "blocked"
    readiness = WalletFifoMethodAcceptanceService(store).readiness(
        run_id=run.run_id
    )
    checks = {check.key: check for check in readiness.checks}
    assert readiness.provider_basis_gap_count == 0
    assert readiness.unexplained_unmatched_count == 1
    assert readiness.provider_basis_resolution_required is False
    assert checks["no_unexplained_unmatched_disposals"].passed is False
    assert checks["provider_basis_complete"].passed is True
    assert response.status_code == 422
    assert "offener Abnahmechecks" in response.json()["detail"]


def test_wallet_fifo_parallel_run_api_blocks_unmatched_pool_and_serves_evidence(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("20"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-5"),
                quote_asset="EUR",
                quote_quantity=Decimal("15"),
                account="wallet-main",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/tax/wallet-fifo-runs",
        json={"years": [2025], "as_of": "2025-12-31T23:59:59Z"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["published_as_latest"] is True
    assert data["latest_artifact_path"]
    assert data["status"] == "blocked"
    assert data["strict_ready"] is False
    assert data["unmatched_count"] == 1
    assert data["provider_basis_gap_count"] == 0
    assert data["unexplained_unmatched_count"] == 1
    assert data["material_delta_years"] == [2025]
    latest = client.get("/api/v1/tax/wallet-fifo-runs/latest")
    assert latest.status_code == 200
    assert latest.json()["data"]["run_id"] == data["run_id"]
    evidence_url = data["evidence_files"][0]["download_url"]
    evidence = client.get(evidence_url)
    assert evidence.status_code == 200
    assert evidence.headers["content-type"] == "application/gzip"
    assert evidence.content.startswith(b"\x1f\x8b")
    bitget_json_url = next(
        item["download_url"]
        for item in data["evidence_files"]
        if item["kind"] == "bitget_strategy_fifo_gap_report"
    )
    bitget_csv_url = next(
        item["download_url"]
        for item in data["evidence_files"]
        if item["kind"] == "bitget_strategy_fifo_gap_disposals"
    )
    bitget_json = client.get(bitget_json_url)
    bitget_csv = client.get(bitget_csv_url)
    assert bitget_json.status_code == 200
    assert bitget_json.headers["content-type"] == "application/json"
    assert bitget_json.json()["status"] == "no_gap"
    assert bitget_csv.status_code == 200
    assert bitget_csv.headers["content-type"] == "application/gzip"
    assert bitget_csv.content.startswith(b"\x1f\x8b")


def test_wallet_fifo_latest_method_delta_returns_null_before_first_run(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    response = TestClient(create_app(store)).get(
        "/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation"
    )

    assert response.status_code == 200
    assert response.json()["data"] is None


def test_wallet_fifo_method_delta_explains_pool_reordering_without_extra_turnover(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("1000"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2025, 3, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("1500"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    service = WalletFifoParallelRunService(store)

    run = service.run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    report = service.method_delta_explanation(
        run_id=run.run_id,
        year=2025,
        asset="btc",
    )

    assert report is not None
    assert report.status == "review"
    assert report.extra_turnover_detected is False
    assert report.material_turnover_delta_detected is False
    assert report.turnover_delta_eur == Decimal("0")
    assert report.proceeds_contribution_to_gain_delta_eur == Decimal("0")
    assert report.gain_loss_delta_eur == Decimal("-900")
    assert report.cost_basis_delta_eur == Decimal("900")
    assert report.cost_basis_contribution_to_gain_delta_eur == Decimal("-900")
    assert report.unexplained_proceeds_delta_groups_count == 0
    assert report.unexplained_proceeds_delta_eur == Decimal("0")
    assert report.pool_reordering_groups_count == 1
    assert report.event_set_gap_groups_count == 0
    assert report.quantity_gap_groups_count == 0
    group = report.groups[0]
    assert group.event_set_parity is True
    assert group.quantity_parity is True
    assert group.proceeds_parity is True
    assert group.drivers == ["pool_fifo_cost_basis_reordering"]
    assert group.pool_reordering_events_count == 1
    assert group.quantity_gap_events_count == 0
    event = group.top_events[0]
    assert event.wallet_pool_ids == ["bitget:Spot"]
    assert event.global_acquisition_source_event_ids
    assert event.wallet_acquisition_source_event_ids
    assert event.global_acquired_at_min == datetime(
        2025, 1, 1, tzinfo=timezone.utc
    )
    assert event.wallet_acquired_at_min == datetime(
        2025, 2, 1, tzinfo=timezone.utc
    )
    assert "andere historische Anschaffungslots" in event.explanation

    client = TestClient(create_app(store))
    response = client.get(
        f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/method-delta-explanation",
        params={"year": 2025, "asset": "BTC", "event_limit": 1},
    )
    assert response.status_code == 200
    assert response.json()["data"]["groups"][0]["top_events"]
    latest = client.get(
        "/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation",
        params={"year": 2025, "asset": "BTC"},
    )
    assert latest.status_code == 200
    json_evidence = client.get(
        f"/api/v1/tax/wallet-fifo-runs/{run.run_id}/evidence/"
        "wallet_fifo_method_delta_explanation.json"
    )
    assert json_evidence.status_code == 200
    assert json_evidence.headers["content-type"] == "application/json"


def test_wallet_fifo_method_delta_confirms_quote_asset_fee_netting_in_both_methods(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                fee_asset="BTC",
                fee_quantity=Decimal("0.01"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-0.99"),
                quote_asset="EUR",
                quote_quantity=Decimal("150"),
                fee_asset="EUR",
                fee_quantity=Decimal("1"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    service = WalletFifoParallelRunService(store)
    run = service.run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )

    report = service.method_delta_explanation(run_id=run.run_id, year=2025)

    assert report is not None
    assert report.global_gain_loss_eur == Decimal("49")
    assert report.wallet_gain_loss_eur == Decimal("49")
    assert report.gain_loss_delta_eur == Decimal("0")
    assert report.proceeds_delta_groups_count == 0
    assert report.unexplained_proceeds_delta_groups_count == 0
    assert report.quote_asset_fee_netting_groups_count == 1
    group = report.groups[0]
    assert group.proceeds_parity is True
    assert group.proceeds_reconciliation_ready is True
    assert group.quote_asset_fee_events_count == 1
    event = group.top_events[0]
    assert event.quote_asset_fee_netting is True
    assert event.global_quote_fee_netting_applied is True
    assert event.wallet_quote_fee_netting_applied is True
    assert event.fee_asset == "EUR"
    assert event.fee_value_eur == Decimal("1")
    assert event.proceeds_delta_eur == Decimal("0")
    assert event.unexplained_proceeds_delta_eur == Decimal("0")


def test_wallet_fifo_method_delta_reconciles_proceeds_for_pool_quantity_gap(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("1"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 4, 12, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("74.32236512"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                fee_asset="HNT",
                fee_quantity=Decimal("0.13513319"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 9, 9, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-74.356"),
                quote_asset="EUR",
                quote_quantity=Decimal("357.434788"),
                fee_asset="EUR",
                fee_quantity=Decimal("0.17871739"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    service = WalletFifoParallelRunService(store)
    run = service.run(
        WalletFifoParallelRunRequest(
            years=[2022],
            as_of=datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )

    report = service.method_delta_explanation(
        run_id=run.run_id,
        year=2022,
        asset="HNT",
    )

    assert report is not None
    assert report.quantity_gap_groups_count == 1
    assert report.proceeds_delta_groups_count == 1
    assert report.reconciled_proceeds_delta_groups_count == 1
    assert report.unexplained_proceeds_delta_groups_count == 0
    group = report.groups[0]
    assert group.quantity_delta == Decimal("-0.16876807")
    assert group.proceeds_reconciliation_ready is True
    assert abs(group.unexplained_proceeds_delta_eur) < Decimal("0.000001")
    assert "quantity_proceeds_allocation" in group.drivers
    assert "proceeds_valuation_delta" not in group.drivers


def test_wallet_fifo_resolves_solana_close_account_program_settlement(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-program-settlement.json", file_hash="settlement")
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "defi_label": "swap",
                    "raw_row": json.dumps(
                        {
                            "meta": {
                                "innerInstructions": [
                                    {
                                        "instructions": [
                                            {
                                                "parsed": {
                                                    "type": "closeAccount",
                                                    "info": {
                                                        "destination": wallet,
                                                        "account": "token-account",
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    ),
                }
            ),
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("0.00510168"),
            account=wallet,
            tx_id="program-settlement-tx",
            raw_object_id=raw.raw_object_id,
        )
    )

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.unresolved_inbound_provenance_count == 0
    assert report.transfer_traces[0].status == "resolved_by_solana_program_settlement"
    assert report.transfer_traces[0].source_pool_id == "solana_program_settlement"


def test_wallet_fifo_resolves_documented_fiat_purchase_transfer(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2021, 4, 19, 17, 16, 48, tzinfo=timezone.utc),
            event_type="transfer",
            asset="USDT",
            quantity=Decimal("1169.434027"),
            quote_asset="EUR",
            quote_quantity=Decimal("1000"),
            account="binance",
            tx_id="documented-fiat-purchase",
        )
    )

    report = WalletFifoPreviewService(store).preview(year=2021)

    assert report.unresolved_inbound_provenance_count == 0
    assert report.transfer_traces[0].status == "resolved_by_documented_fiat_purchase"
    assert report.lots_count == 1


def test_wallet_fifo_resolves_exact_solana_swap_proceeds(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-swap-proceeds.json", file_hash="swap-proceeds")
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "defi_label": "swap",
                    "raw_row": json.dumps(
                        {
                            "meta": {
                                "innerInstructions": [
                                    {
                                        "instructions": [
                                            {
                                                "parsed": {
                                                    "type": "transfer",
                                                    "info": {
                                                        "destination": wallet,
                                                        "lamports": 15_261_428_266,
                                                        "source": "jupiter-order-account",
                                                    },
                                                },
                                                "program": "system",
                                            }
                                        ]
                                    }
                                ],
                                "logMessages": ["Program log: Instruction: Swap"],
                            }
                        }
                    ),
                }
            ),
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2024, 11, 22, 19, 34, 42, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("15.261428266"),
            account=wallet,
            tx_id="jupiter-swap-proceeds",
            raw_object_id=raw.raw_object_id,
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("200"),
            priced_at=datetime(2024, 11, 22, 19, 34, 42, tzinfo=timezone.utc),
            source="unit",
        )
    )

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.unresolved_inbound_provenance_count == 0
    assert report.transfer_traces[0].status == "resolved_by_solana_swap_proceeds"
    closure = WalletFifoPreviewService(store).provenance_closure_report(2024)
    assert closure.items[0].closure_status == "documented_solana_swap_proceeds"
    assert closure.items[0].requires_review is False


def test_wallet_fifo_carries_lots_through_solana_order_cancel_escrow(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-order-cancel.json", file_hash="order-cancel")
    )

    def raw_row(instruction: str) -> str:
        return json.dumps(
            {
                "meta": {"logMessages": [f"Program log: Instruction: {instruction}"]},
                "transaction": {
                    "message": {
                        "accountKeys": [{"pubkey": wallet, "signer": True}],
                    }
                },
            }
        )

    outbound_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json=json.dumps({"raw_row": raw_row("InitializeOrder")})),
    )
    return_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=2, payload_json=json.dumps({"raw_row": raw_row("CancelOrder")})),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 20, 5, 0, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("1000"),
                account=wallet,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 20, 5, 6, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-6.004020040"),
                account=wallet,
                tx_id="initialize-order",
                raw_object_id=outbound_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 20, 5, 7, 33, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("6.003969145"),
                account=wallet,
                tx_id="cancel-order",
                raw_object_id=return_raw.raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert [trace.status for trace in state.transfer_traces] == [
        "solana_program_escrow_outbound",
        "solana_program_escrow_return",
    ]
    assert state.transfer_traces[1].fee_quantity == Decimal("0.000050895")
    assert len(state.tax_lines) == 1
    assert state.tax_lines[0].source_event_id.endswith(":fee")
    assert state.tax_lines[0].quantity == Decimal("0.000050895")
    wallet_quantity = sum(
        (lot.quantity_remaining for lot in state.open_lots if lot.pool_id == f"solana_rpc:{wallet}"),
        Decimal("0"),
    )
    assert wallet_quantity == Decimal("9.999949105")


def test_wallet_fifo_carries_binance_pionex_transfer_with_utc_offset_and_fee(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    binance_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History-202605061835(UTC+2)_test.xlsx",
            file_hash="binance-withdraw",
        )
    )
    pionex_batch = store.create_import_batch(
        ImportBatchCreate(
            source="pionex",
            filename="deposit-withdraw.csv",
            file_hash="pionex-deposit",
        )
    )
    withdrawal_raw = store.add_raw_object(
        binance_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-201",
                    "Coin": "USDT",
                    "Operation": "Withdraw",
                    "Remark": "Withdraw fee is included",
                    "Time": "21-12-25 18:22:42",
                }
            ),
        ),
    )
    deposit_raw = store.add_raw_object(
        pionex_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "amount": "200",
                    "coin": "USDT",
                    "date(UTC+0)": "2021-12-25 16:23:04",
                    "fee": "0",
                    "network": "TRC20",
                    "tx_type": "DEPOSIT",
                    "txid": "pionex-deposit-tx",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("300"),
                quote_asset="EUR",
                quote_quantity=Decimal("300"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 12, 25, 16, 23, 4, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("200"),
                account="pionex",
                tx_id="pionex-deposit-tx",
                raw_object_id=deposit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 12, 25, 18, 22, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-201"),
                account="Spot",
                raw_object_id=withdrawal_raw.raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert len(state.transfer_traces) == 1
    trace = state.transfer_traces[0]
    assert trace.status == "cross_cex_transfer_evidence_partial"
    assert trace.quantity == Decimal("200")
    assert trace.fee_quantity == Decimal("1")
    assert trace.carried_cost_basis_eur == Decimal("200")
    assert len(state.tax_lines) == 1
    assert state.tax_lines[0].quantity == Decimal("1")
    assert abs(state.tax_lines[0].acquisition_cost_eur - Decimal("1")) < Decimal("1e-18")
    quantities = {
        lot.pool_id: lot.quantity_remaining
        for lot in state.open_lots
    }
    assert quantities["binance:Spot"] == Decimal("99")
    assert quantities["pionex:pionex"] == Decimal("200")

    registry_path = tmp_path / "source_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "test-v1",
                "entries": [],
                "transfer_evidence": [
                    {
                        "evidence_id": "approved-pionex-transfer",
                        "tx_id": "pionex-deposit-tx",
                        "source_id": "binance-account",
                        "target_source_id": "pionex-account",
                        "event_time": "2021-12-25T16:23:04Z",
                        "asset": "USDT",
                        "quantity": "200",
                        "fee_quantity": "1",
                        "evidence_status": "approved_complete",
                        "evidence_refs": ["unit-evidence"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    approved_state = WalletFifoPreviewService(
        store,
        source_registry_config_path=registry_path,
    ).replay()

    assert approved_state.transfer_traces[0].status == "cross_cex_transfer_evidence_complete"


def test_wallet_fifo_carries_binance_hot_wallet_withdrawal_to_owned_solana_wallet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    binance_hot_wallet = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
    binance_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History-202605061835(UTC+2)_test.xlsx",
            file_hash="binance-sol-withdraw",
        )
    )
    solana_batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-readonly.sqlite", file_hash="solana-inbound")
    )
    withdrawal_raw = store.add_raw_object(
        binance_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-54.10811",
                    "Coin": "SOL",
                    "Operation": "Withdraw",
                    "Remark": "Withdraw fee is included",
                    "Time": "23-06-10 18:50:42",
                }
            ),
        ),
    )
    acquisition_raw = store.add_raw_object(
        binance_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "54.10811",
                    "Coin": "SOL",
                    "Operation": "Buy",
                    "Time": "23-06-10 18:45:04",
                }
            ),
        ),
    )
    inbound_raw = store.add_raw_object(
        solana_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "raw_row": json.dumps(
                        {
                            "transaction": {
                                "message": {
                                    "accountKeys": [
                                        {"pubkey": binance_hot_wallet, "signer": True},
                                        {"pubkey": wallet, "signer": False},
                                    ]
                                }
                            }
                        }
                    )
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2023, 6, 10, 18, 45, 4, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("54.10811"),
                quote_asset="EUR",
                quote_quantity=Decimal("541.0811"),
                account="Spot",
                raw_object_id=acquisition_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 6, 10, 16, 49, 46, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("54.10011"),
                account=wallet,
                tx_id="binance-hot-wallet-withdrawal",
                raw_object_id=inbound_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2023, 6, 10, 18, 50, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-54.10811"),
                account="Spot",
                raw_object_id=withdrawal_raw.raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert len(state.transfer_traces) == 1
    trace = state.transfer_traces[0]
    assert trace.status == "cross_cex_transfer_evidence_partial"
    assert trace.source_pool_id == "binance:Spot"
    assert trace.target_pool_id == f"solana_rpc:{wallet}"
    assert trace.quantity == Decimal("54.10011")
    assert trace.fee_quantity == Decimal("0.008")
    assert len(state.tax_lines) == 1
    assert state.tax_lines[0].quantity == Decimal("0.008")


def test_wallet_fifo_normalizes_naive_source_event_times_to_utc(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    event = CanonicalEvent(
        event_id="naive-solana-event",
        source="solana_rpc",
        event_time=datetime(2023, 6, 10, 16, 49, 46),
        event_type="transfer",
        asset="SOL",
        quantity=Decimal("1"),
    )

    normalized = service._events_with_source_timezone_utc([event])

    assert normalized[0].event_time == datetime(2023, 6, 10, 16, 49, 46, tzinfo=timezone.utc)


def test_wallet_fifo_uses_manual_cex_deposit_as_cost_evidence_not_second_pool(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    txid = "dcbc4efebeba49a324702c4c557fcfa375e7edc1ce824c849b2bc82ef9088d5e"
    binance_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History-202605061836(UTC+2)_test.xlsx",
            file_hash="binance-btc-deposit",
        )
    )
    manual_batch = store.create_import_batch(
        ImportBatchCreate(source="manual-csv", filename="btc-opening.csv", file_hash="manual-btc-opening")
    )
    deposit_raw = store.add_raw_object(
        binance_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Address": "1KsYCTB1KgzLUz752NkEj9tnXUguaxaWox",
                    "Amount": "0.01036997",
                    "Coin": "BTC",
                    "Network": "BTC",
                    "Status": "Completed",
                    "TXID": txid,
                    "Time": "23-06-09 20:30:41",
                }
            ),
        ),
    )
    internal_raw = store.add_raw_object(
        binance_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "0.01036997",
                    "Coin": "BTC",
                    "Operation": "Deposit",
                    "Time": "23-06-09 20:31:04",
                }
            ),
        ),
    )
    manual_raw = store.add_raw_object(
        manual_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "account": "binance",
                    "amount": "0.01036997",
                    "asset": "BTC",
                    "quote_asset": "EUR",
                    "quote_quantity": "254.942392828916",
                    "source_ref": txid,
                    "type": "deposit",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref=txid,
                event_time=datetime(2023, 6, 9, 20, 30, 41, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("0.01036997"),
                tx_id=txid,
                account="binance",
                raw_object_id=deposit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2023, 6, 9, 20, 31, 4, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("0.01036997"),
                account="Spot",
                raw_object_id=internal_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="manual-csv",
                event_time=datetime(2023, 6, 9, 20, 30, 41, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("0.01036997"),
                quote_asset="EUR",
                quote_quantity=Decimal("254.942392828916"),
                tx_id="manual-opening:binance-btc-deposit-2023-06-09",
                account="binance",
                raw_object_id=manual_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2023, 6, 10, 18, 45, 4, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-0.01036997"),
                quote_asset="EUR",
                quote_quantity=Decimal("300"),
                account="Spot",
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert not any(trace.status == "unresolved_inbound_provenance" for trace in state.transfer_traces)
    assert any(
        trace.status == "resolved_by_documented_manual_cex_deposit_history"
        for trace in state.transfer_traces
    )
    assert any(trace.status == "evidence_mirror_excluded" for trace in state.transfer_traces)
    assert len(state.tax_lines) == 1
    assert state.tax_lines[0].acquisition_cost_eur == Decimal("254.942392828916")
    assert all(lot.pool_id != "manual-csv:binance" for lot in state.open_lots)


def test_wallet_fifo_marks_documented_moonpay_onramp_cost_basis_for_receipt_review(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    artifact_dir = tmp_path / "solana-provenance"
    artifact_dir.mkdir()
    monkeypatch.setattr(
        WalletFifoPreviewService,
        "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR",
        artifact_dir,
    )
    monkeypatch.setattr(
        MoonpayReceiptService,
        "DEFAULT_TRADE_HISTORY_PATH",
        tmp_path / "moonpay-trade-history-missing.csv",
    )
    txid = "moonpay-sol-tx"
    wallet = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    event_time = datetime(2026, 1, 1, 14, 49, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=event_time,
            source="unit",
        )
    )
    event = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=event_time,
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.972"),
                tx_id=txid,
                account=wallet,
            )
        ]
    )[0]
    (artifact_dir / "latest_2026_SOL_provenance_classification.json").write_text(
        json.dumps(
            {
                "failed_count": 0,
                "classifications": [
                    {
                        "event_id": event.event_id,
                        "signature": txid,
                        "status": "external_or_unknown_origin",
                        "asset": "SOL",
                        "matched_amount": "1.972",
                        "sender_owner": WalletFifoPreviewService.MOONPAY_APPLE_PAY_SOLANA_SENDER,
                        "receiver_owner": wallet,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    state = WalletFifoPreviewService(store).replay()
    report = WalletFifoParallelRunService(
        store,
        artifact_root=tmp_path / "wallet-fifo-runs",
    ).run(
        WalletFifoParallelRunRequest(
            years=[2026],
            as_of=datetime(2026, 1, 31, tzinfo=timezone.utc),
        )
    )

    assert state.unmatched == []
    assert state.transfer_traces[0].status == (
        "resolved_by_documented_moonpay_apple_pay_onramp_cost_basis_pending"
    )
    assert state.transfer_traces[0].carried_cost_basis_eur == Decimal("197.2")
    assert report.unresolved_inbound_provenance_count == 0
    assert report.acquisition_cost_evidence_review_count == 1
    assert report.status == "blocked"


def test_wallet_fifo_reconciliation_separates_quantity_from_valuation_parity():
    acquired_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    disposed_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
    global_line = WalletFifoPreviewLine(
        tax_line_id="global",
        pool_id="global",
        asset="BTC",
        acquired_at=acquired_at,
        disposed_at=disposed_at,
        quantity=Decimal("1"),
        acquisition_cost_eur=Decimal("50"),
        disposal_proceeds_eur=Decimal("100"),
        gain_loss_eur=Decimal("50"),
        holding_days=151,
        source_event_id="sell",
        lot_id="global-lot",
    )
    wallet_line = global_line.model_copy(
        update={
            "tax_line_id": "wallet",
            "pool_id": "binance:Spot",
            "disposal_proceeds_eur": Decimal("90"),
            "gain_loss_eur": Decimal("40"),
        }
    )

    result = WalletFifoParallelRunService._asset_reconciliations(
        global_lines=[global_line],
        wallet_lines=[wallet_line],
        year=2025,
        material_threshold=Decimal("0.01"),
    )[0]

    assert result.quantity_parity is True
    assert result.event_set_parity is True
    assert result.proceeds_parity is False
    assert result.classification == "valuation_delta"


def test_wallet_fifo_resolves_documented_external_solana_micro_credit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    sender = "G4k9dJHL9yAfNsVViUkF4uhyU5JS9khBK68HvJpUH3vL"
    batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-readonly.sqlite", file_hash="micro-credit")
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "raw_row": json.dumps(
                        {
                            "meta": {
                                "innerInstructions": [
                                    {
                                        "instructions": [
                                            {
                                                "parsed": {
                                                    "type": "transfer",
                                                    "info": {
                                                        "source": sender,
                                                        "destination": wallet,
                                                        "lamports": 1_385_880,
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                ]
                            },
                            "transaction": {
                                "message": {
                                    "accountKeys": [{"pubkey": sender, "signer": True}]
                                }
                            },
                        }
                    )
                }
            ),
        ),
    )
    event_time = datetime(2023, 5, 8, 4, 42, 9, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=event_time,
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("0.00138588"),
            account=wallet,
            tx_id="micro-credit",
            raw_object_id=raw.raw_object_id,
        )
    )
    store.add_price_point(
        PricePointCreate(asset="SOL", price_eur=Decimal("20"), priced_at=event_time, source="unit")
    )

    report = WalletFifoPreviewService(store).preview(year=2023)

    assert report.unresolved_inbound_provenance_count == 0
    assert report.transfer_traces[0].status == "resolved_by_documented_external_micro_credit"


def test_wallet_fifo_resolves_nonmaterial_solana_program_settlement(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-readonly.sqlite", file_hash="program-micro")
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "raw_row": json.dumps(
                        {
                            "meta": {
                                "logMessages": ["Program log: Instruction: CloseDelegationV0"]
                            },
                            "transaction": {
                                "message": {
                                    "accountKeys": [{"pubkey": wallet, "signer": True}]
                                }
                            },
                        }
                    )
                }
            ),
        ),
    )
    event_time = datetime(2024, 4, 25, 10, 46, 8, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=event_time,
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("0.002249749"),
            account=wallet,
            tx_id="close-delegation",
            raw_object_id=raw.raw_object_id,
        )
    )
    store.add_price_point(
        PricePointCreate(asset="SOL", price_eur=Decimal("140"), priced_at=event_time, source="unit")
    )

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.unresolved_inbound_provenance_count == 0
    assert report.transfer_traces[0].status == "resolved_by_solana_program_settlement"
    assert report.transfer_traces[0].source_pool_id == "solana_program_micro_settlement"


def test_wallet_fifo_legacy_hnt_chain_normalizes_txid_and_excludes_evidence_mirror(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main = WalletFifoPreviewService.MAIN_HELIUM_LEGACY_WALLET
    binance_legacy = "138bCXPVfSq7yyTfoDUrVwztPmUr4WGyA7TED9Y41djmF7rjA8y"
    raw_batch = store.create_import_batch(
        ImportBatchCreate(source="helium", filename="helium-main-raw.csv", file_hash="helium-raw")
    )
    mirror_batch = store.create_import_batch(
        ImportBatchCreate(source="helium", filename="Heliumtracker 2021.xlsx", file_hash="helium-mirror")
    )
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="Binance-Deposit-History.xlsx", file_hash="binance-deposit")
    )
    raw_out = store.add_raw_object(
        raw_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"payer":"' + main + '","payee":"' + binance_legacy
                + '","transaction_hash":"abc.DEF_123","amount":"100"}'
            ),
        ),
    )
    raw_mirror = store.add_raw_object(
        mirror_batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"Receiver":"Binance","Amount":"100"}'),
    )
    raw_deposit = store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json='{"TXID":"abc-DEF-123","Address":"deposit","Network":"HNT"}',
        ),
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="unit",
            confidence=Decimal("1"),
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="mining",
                asset="HNT",
                quantity=Decimal("200"),
                account=main,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 7, 1, 10, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-100"),
                account=main,
                tx_id="abc.DEF_123",
                raw_object_id=raw_out.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 7, 1, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("100"),
                account="Binance",
                raw_object_id=raw_mirror.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 7, 1, 12, 3, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("100"),
                account="binance",
                tx_id="abc-DEF-123",
                raw_object_id=raw_deposit.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 7, 1, 12, 4, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 8, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-100"),
                quote_asset="EUR",
                quote_quantity=Decimal("200"),
                account="Spot",
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2021)

    assert report.unmatched_count == 0
    assert report.unresolved_inbound_provenance_count == 0
    assert any(trace.status == "evidence_mirror_excluded" for trace in report.transfer_traces)
    assert report.sample_lines[0].acquisition_cost_eur == Decimal("100")
    assert report.sample_lines[0].gain_loss_eur == Decimal("100")


def test_wallet_fifo_carries_fairspot_counterparty_lot_without_portfolio_ownership(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main = WalletFifoPreviewService.MAIN_HELIUM_LEGACY_WALLET
    fairspot = WalletFifoPreviewService.FAIRSPOT_STAKING_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(source="helium", filename="helium-fairspot.csv", file_hash="fairspot")
    )
    outbound_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json='{"payer":"' + main + '","payee":"' + fairspot + '","transaction_hash":"out"}',
        ),
    )
    return_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json='{"payer":"' + fairspot + '","payee":"' + main + '","transaction_hash":"back"}',
        ),
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="unit",
            confidence=Decimal("1"),
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="mining",
                asset="HNT",
                quantity=Decimal("100"),
                account=main,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 6, 23, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-100"),
                account=main,
                tx_id="out",
                raw_object_id=outbound_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 7, 8, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("99.75"),
                account=main,
                tx_id="back",
                raw_object_id=return_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 8, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-99.75"),
                quote_asset="EUR",
                quote_quantity=Decimal("199.50"),
                account=main,
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2021)

    assert report.unmatched_count == 0
    assert report.unresolved_inbound_provenance_count == 0
    assert {trace.status for trace in report.transfer_traces} == {
        "known_staking_counterparty_outbound",
        "known_staking_counterparty_return",
    }
    assert report.sample_lines[0].acquisition_cost_eur == Decimal("99.75")
    assert report.sample_lines[0].gain_loss_eur == Decimal("99.75")
    assert all("fairspot" not in line.pool_id.lower() for line in report.sample_lines)


def test_wallet_fifo_carries_owned_legacy_staking_principal_and_marks_excess_reward(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main = WalletFifoPreviewService.MAIN_HELIUM_LEGACY_WALLET
    staking = WalletFifoPreviewService.LEGACY_STAKING_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(source="helium", filename="helium-legacy-staking.csv", file_hash="legacy-staking")
    )

    def raw(row_number: int, payer: str, payee: str, tx_id: str):
        return store.add_raw_object(
            batch.batch_id,
            RawObjectCreate(
                row_number=row_number,
                payload_json=json.dumps(
                    {"payer": payer, "payee": payee, "transaction_hash": tx_id, "type": "payment_v2"}
                ),
            ),
        )

    out_one = raw(1, main, staking, "stake-out-1")
    out_two = raw(2, main, staking, "stake-out-2")
    back_one = raw(3, staking, main, "stake-back-1")
    back_two = raw(4, staking, main, "stake-back-2")
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    for day in (datetime(2022, 7, 12, tzinfo=timezone.utc), datetime(2022, 12, 31, tzinfo=timezone.utc)):
        store.add_price_point(PricePointCreate(asset="HNT", price_eur=Decimal("1"),
            priced_at=day, source="unit"))
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="mining",
                asset="HNT",
                quantity=Decimal("477.5861356"),
                account=main,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 6, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-400"),
                account=main,
                tx_id="stake-out-1",
                raw_object_id=out_one.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2022, 5, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-77.5861356"),
                account=main,
                tx_id="stake-out-2",
                raw_object_id=out_two.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2022, 7, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("421.3024511"),
                account=main,
                tx_id="stake-back-1",
                raw_object_id=back_one.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2022, 12, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("73.9345895"),
                account=main,
                tx_id="stake-back-2",
                raw_object_id=back_two.raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert sum(lot.quantity_remaining for lot in state.open_lots) == Decimal("495.2370406")
    reward_lot = next(lot for lot in state.open_lots if lot.source_event_id.startswith("staking-reward:"))
    assert reward_lot.quantity_total == Decimal("17.650905")
    assert reward_lot.cost_basis_eur_total == Decimal("17.650905")
    assert any(
        trace.status == "known_staking_return_with_reward_component_review"
        for trace in state.transfer_traces
    )


def test_wallet_fifo_assigns_documented_opening_balance_to_owned_exchange_pool(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="opening-balance",
                event_time=datetime(2023, 3, 10, 9, 10, 57, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("3.1882579185964125"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2023, 3, 10, 9, 10, 58, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("0.0001"),
                quote_asset="USDT",
                quote_quantity=Decimal("3.1882579185964125"),
                account="pionex",
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    opening_trace = next(
        trace for trace in state.transfer_traces if trace.status == "resolved_by_documented_opening_balance"
    )
    assert opening_trace.target_pool_id == "pionex:pionex"


def test_wallet_fifo_carries_btt_bttc_redenomination_cost_basis(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="binance-redenomination.xlsx", file_hash="redenomination")
    )
    source_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json='{"Operation":"Token Swap - Redenomination/Rebranding","Coin":"BTT"}',
        ),
    )
    target_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=2, payload_json='{"Operation":"Airdrop Assets","Coin":"BTTC"}'),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 12, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTTC",
                quantity=Decimal("4194.463999999999999999"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 24, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTTC",
                quantity=Decimal("-4194.464"),
                account="Spot",
                raw_object_id=source_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 24, 18, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTTC",
                quantity=Decimal("4194464"),
                account="Spot",
                raw_object_id=target_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTTC",
                quantity=Decimal("-4194464"),
                quote_asset="EUR",
                quote_quantity=Decimal("200"),
                account="Spot",
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2023)

    assert report.unmatched_count == 0
    assert report.unresolved_inbound_provenance_count == 0
    assert any(trace.status == "token_redenomination" for trace in report.transfer_traces) is False
    assert report.sample_lines[0].acquisition_cost_eur == Decimal("100")
    assert report.sample_lines[0].gain_loss_eur == Decimal("100")
    full = WalletFifoPreviewService(store).preview()
    assert any(trace.status == "token_redenomination" for trace in full.transfer_traces)


def test_wallet_fifo_values_quote_disposal_from_received_stable_asset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 7, 12, 26, tzinfo=timezone.utc),
                event_type="trade",
                asset="TRUMP",
                quantity=Decimal("140"),
                quote_asset="EUR",
                quote_quantity=Decimal("7922.6976"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 8, 49, 58, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("8363.63"),
                quote_asset="TRUMP",
                quote_quantity=Decimal("140"),
                account="Spot",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.96"),
            priced_at=datetime(2025, 1, 20, 8, 49, 58, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="TRUMP",
            price_eur=Decimal("35"),
            priced_at=datetime(2025, 1, 20, 8, 49, 58, tzinfo=timezone.utc),
            source="must-not-price-stable-quote-disposal",
        )
    )

    report = WalletFifoPreviewService(store).preview(year=2025)

    trump_line = next(line for line in report.sample_lines if line.asset == "TRUMP")
    assert trump_line.acquisition_cost_eur == Decimal("7922.6976")
    assert trump_line.disposal_proceeds_eur == Decimal("8029.084800000000000000")
    assert trump_line.gain_loss_eur == Decimal("106.387200000000000000")
