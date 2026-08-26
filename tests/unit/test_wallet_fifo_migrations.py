from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.wallet_fifo_migrations import (
    WalletFifoMigrationApplyRequest,
    WalletFifoMigrationRehearsalRequest,
)
from steuerreport_v2.contracts.wallet_fifo_runs import (
    WalletFifoMethodAcceptanceRequest,
    WalletFifoParallelRunRequest,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.fifo_methods import (
    GLOBAL_ASSET_FIFO_SCOPE,
    WALLET_DEPOT_FIFO_SCOPE,
    active_fifo_scope,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)
from steuerreport_v2.domain.wallet_fifo_migrations import (
    WalletFifoMigrationApplyService,
    WalletFifoMigrationRehearsalService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


def _ready_store(tmp_path) -> DuckDbStore:
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("2"),
                quote_asset="EUR",
                quote_quantity=Decimal("200"),
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


def _run(store: DuckDbStore):
    return WalletFifoParallelRunService(store).run(
        WalletFifoParallelRunRequest(
            years=[2025],
            as_of=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )


def test_wallet_fifo_migration_rehearsal_is_read_only_and_waits_for_decision(
    tmp_path,
):
    store = _ready_store(tmp_path)
    run = _run(store)
    before_lots = TaxService(store).list_tax_lots()
    before_lines = TaxService(store).list_tax_lines()

    report = WalletFifoMigrationRehearsalService(store).rehearse(
        WalletFifoMigrationRehearsalRequest(run_id=run.run_id)
    )

    assert report.status == "ready_for_method_decision"
    assert report.technical_ready is True
    assert report.migration_ready is False
    assert report.approved_decision_bound is False
    assert report.production_write_performed is False
    assert report.production_tax_semantic_unchanged is True
    assert report.provider_basis_gap_count == 0
    assert report.unexplained_unmatched_count == 0
    assert report.source_all_lots_count == 1
    assert report.source_open_lots_count == 1
    assert report.source_tax_lines_count == 1
    assert report.staging_lots_count == 1
    assert report.staging_open_lots_count == 1
    assert report.staging_tax_lines_count == 1
    assert report.staging_orphan_tax_lines_count == 0
    assert report.staging_negative_lots_count == 0
    assert report.year_checks[0].parity is True
    assert all(
        item.passed for item in report.checks if item.gate == "technical"
    )
    assert next(
        item for item in report.checks if item.key == "approved_decision_bound"
    ).passed is False
    assert TaxService(store).list_tax_lots() == before_lots
    assert TaxService(store).list_tax_lines() == before_lines
    assert TaxService(store).latest_summary().fifo_method == GLOBAL_ASSET_FIFO_SCOPE
    assert WalletFifoMigrationRehearsalService(store).latest() is not None
    assert (store.path.parent / report.artifact_path).exists()


def test_wallet_fifo_migration_rehearsal_accepts_only_bound_approval(tmp_path):
    store = _ready_store(tmp_path)
    run = _run(store)
    decision = WalletFifoMethodAcceptanceService(store).accept(
        run.run_id,
        WalletFifoMethodAcceptanceRequest(
            decision="approved_for_controlled_migration",
            rationale="Die gebundene Methodenakte wurde fachlich geprueft und kontrolliert freigegeben.",
            actor="unit-test",
            acknowledge_material_tax_delta=True,
            acknowledge_consistent_application=True,
            acknowledge_no_automatic_activation=True,
        ),
    )

    report = WalletFifoMigrationRehearsalService(store).rehearse(
        WalletFifoMigrationRehearsalRequest(run_id=run.run_id)
    )

    assert decision.created is True
    assert report.status == "ready_for_controlled_migration"
    assert report.decision_id == decision.decision_id
    assert report.approved_decision_bound is True
    assert report.technical_ready is True
    assert report.migration_ready is True
    assert report.active_fifo_scope == GLOBAL_ASSET_FIFO_SCOPE
    assert report.target_fifo_scope == WALLET_DEPOT_FIFO_SCOPE
    assert report.production_write_performed is False
    assert TaxService(store).latest_summary().fifo_method == GLOBAL_ASSET_FIFO_SCOPE


def test_wallet_fifo_migration_rehearsal_blocks_unmatched_run(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
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
    )
    TaxService(store).rebuild_fifo()
    run = _run(store)

    report = WalletFifoMigrationRehearsalService(store).rehearse(
        WalletFifoMigrationRehearsalRequest(run_id=run.run_id)
    )

    assert run.status == "blocked"
    assert report.status == "blocked"
    assert report.technical_ready is False
    assert report.migration_ready is False
    assert next(
        item
        for item in report.checks
        if item.key == "no_unexplained_wallet_fifo_unmatched"
    ).passed is False
    assert next(
        item for item in report.checks if item.key == "provider_basis_complete"
    ).passed is True
    assert report.provider_basis_gap_count == 0
    assert report.unexplained_unmatched_count == 1
    assert report.production_write_performed is False


def test_wallet_fifo_migration_rehearsal_api_routes(tmp_path):
    store = _ready_store(tmp_path)
    run = _run(store)
    client = TestClient(create_app(store))

    created = client.post(
        "/api/v1/tax/wallet-fifo-migrations/rehearsals",
        json={"run_id": run.run_id},
    )
    latest = client.get(
        "/api/v1/tax/wallet-fifo-migrations/rehearsals/latest"
    )
    rehearsal_id = created.json()["data"]["rehearsal_id"]
    by_id = client.get(
        f"/api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}"
    )

    assert created.status_code == 200
    assert created.json()["data"]["status"] == "ready_for_method_decision"
    assert latest.status_code == 200
    assert latest.json()["data"]["rehearsal_id"] == rehearsal_id
    assert by_id.status_code == 200
    assert by_id.json()["data"]["semantic_sha256"] == created.json()["data"][
        "semantic_sha256"
    ]


def test_wallet_fifo_apply_readiness_is_blocked_without_explicit_decision(tmp_path):
    store = _ready_store(tmp_path)
    run = _run(store)
    rehearsal = WalletFifoMigrationRehearsalService(store).rehearse(
        WalletFifoMigrationRehearsalRequest(run_id=run.run_id)
    )
    before_lots = TaxService(store).list_tax_lots()
    before_lines = TaxService(store).list_tax_lines()

    report = WalletFifoMigrationApplyService(
        store,
        backup_root=tmp_path / "offsite-backups",
    ).readiness(run_id=run.run_id, rehearsal_id=rehearsal.rehearsal_id)

    assert report.status == "blocked"
    assert report.ready is False
    assert report.decision_status == "pending"
    assert report.rehearsal_bound is True
    assert next(
        item for item in report.checks if item.key == "decision_approved_and_bound"
    ).passed is False
    assert next(
        item for item in report.checks if item.key == "atomic_replace_available"
    ).passed is True
    assert next(
        item for item in report.checks if item.key == "wallet_rebuild_available"
    ).passed is True
    assert TaxService(store).list_tax_lots() == before_lots
    assert TaxService(store).list_tax_lines() == before_lines
    assert not (tmp_path / "offsite-backups").exists()


def test_wallet_fifo_controlled_apply_backs_up_activates_and_is_idempotent(tmp_path):
    store = _ready_store(tmp_path)
    run = _run(store)
    decision = WalletFifoMethodAcceptanceService(store).accept(
        run.run_id,
        WalletFifoMethodAcceptanceRequest(
            decision="approved_for_controlled_migration",
            rationale="Die gebundene Methodenakte wurde fachlich geprueft und kontrolliert freigegeben.",
            actor="unit-test",
            acknowledge_material_tax_delta=True,
            acknowledge_consistent_application=True,
            acknowledge_no_automatic_activation=True,
        ),
    )
    rehearsal = WalletFifoMigrationRehearsalService(store).rehearse(
        WalletFifoMigrationRehearsalRequest(run_id=run.run_id)
    )
    backup_root = tmp_path / "offsite-backups"
    service = WalletFifoMigrationApplyService(store, backup_root=backup_root)
    readiness = service.readiness(
        run_id=run.run_id,
        rehearsal_id=rehearsal.rehearsal_id,
    )
    request = WalletFifoMigrationApplyRequest(
        run_id=run.run_id,
        rehearsal_id=rehearsal.rehearsal_id,
        rehearsal_semantic_sha256=rehearsal.semantic_sha256,
        decision_id=decision.decision_id,
        actor="unit-test",
        rationale="Kontrollierter Apply nach erfolgreicher technischer und fachlicher Abnahme.",
        execute=True,
        confirmation_phrase=service.CONFIRMATION_PHRASE,
        acknowledge_verified_backup=True,
        acknowledge_material_tax_delta=True,
        acknowledge_report_regeneration=True,
    )

    assert readiness.status == "ready_for_controlled_apply"
    assert readiness.ready is True
    report = service.apply(request)

    assert report.status == "applied"
    assert report.applied is True
    assert report.source_fifo_scope == GLOBAL_ASSET_FIFO_SCOPE
    assert report.target_fifo_scope == WALLET_DEPOT_FIFO_SCOPE
    assert report.lots_count == rehearsal.source_all_lots_count
    assert report.tax_lines_count == rehearsal.source_tax_lines_count
    assert report.backup_path is not None
    backup_path = tmp_path / report.backup_path
    if not backup_path.exists():
        backup_path = service.backup_root / report.backup_path.split("/")[-1]
    assert backup_path.exists()
    assert report.backup_size_bytes == backup_path.stat().st_size
    assert report.backup_sha256 == service._file_sha256(backup_path)
    assert active_fifo_scope(store) == WALLET_DEPOT_FIFO_SCOPE
    assert TaxMethodologyService(store).policy().fifo_scope == WALLET_DEPOT_FIFO_SCOPE
    summary = TaxService(store).latest_summary()
    assert summary is not None
    assert summary.fifo_method == WALLET_DEPOT_FIFO_SCOPE
    assert summary.input_fingerprint_digest == run.input_fingerprint.digest
    assert WalletFifoMethodAcceptanceService(store).readiness(
        run_id=run.run_id
    ).strict_ready is True

    backup_count = len(list(backup_root.glob("*.duckdb")))
    repeated = service.apply(request)
    assert repeated.status == "already_active"
    assert repeated.applied is False
    assert len(list(backup_root.glob("*.duckdb"))) == backup_count

    rebuilt = TaxService(store).rebuild_fifo()
    assert rebuilt.unmatched_disposals == 0
    assert TaxService(store).latest_summary().fifo_method == WALLET_DEPOT_FIFO_SCOPE


def test_atomic_tax_table_replace_rolls_back_on_orphan_line(tmp_path):
    store = _ready_store(tmp_path)
    tax = TaxService(store)
    before_lots = tax.list_tax_lots()
    before_lines = tax.list_tax_lines()
    before_summary = tax.latest_summary()
    orphan_line = before_lines[0].model_copy(
        update={"tax_line_id": "orphan-line", "lot_id": "missing-lot"}
    )

    try:
        tax._replace_tax_tables(before_lots, [orphan_line], [])
    except ValueError as exc:
        assert "Integritaetschecks" in str(exc)
    else:
        raise AssertionError("Orphan-Tax-Line muss den atomaren Austausch abbrechen")

    assert tax.list_tax_lots() == before_lots
    assert tax.list_tax_lines() == before_lines
    assert tax.latest_summary() == before_summary


def test_wallet_fifo_apply_api_is_read_only_until_all_gates_pass(tmp_path):
    store = _ready_store(tmp_path)
    run = _run(store)
    rehearsal = WalletFifoMigrationRehearsalService(store).rehearse(
        WalletFifoMigrationRehearsalRequest(run_id=run.run_id)
    )
    client = TestClient(create_app(store))

    readiness = client.get(
        "/api/v1/tax/wallet-fifo-migrations/apply-readiness",
        params={"run_id": run.run_id, "rehearsal_id": rehearsal.rehearsal_id},
    )
    blocked = client.post(
        "/api/v1/tax/wallet-fifo-migrations/apply",
        json={
            "run_id": run.run_id,
            "rehearsal_id": rehearsal.rehearsal_id,
            "rehearsal_semantic_sha256": rehearsal.semantic_sha256,
            "decision_id": "missing-decision",
            "actor": "unit-test",
            "rationale": "Dieser Aufruf muss ohne explizite Methodenfreigabe blockiert bleiben.",
            "execute": True,
            "confirmation_phrase": "WALLET_DEPOT_FIFO_V1_AKTIVIEREN",
            "acknowledge_verified_backup": True,
            "acknowledge_material_tax_delta": True,
            "acknowledge_report_regeneration": True,
        },
    )
    latest = client.get(
        "/api/v1/tax/wallet-fifo-migrations/applies/latest"
    )

    assert readiness.status_code == 200
    assert readiness.json()["data"]["status"] == "blocked"
    assert blocked.status_code == 422
    assert TaxService(store).latest_summary().fifo_method == GLOBAL_ASSET_FIFO_SCOPE
    assert latest.status_code == 200
    assert latest.json()["data"] is None
