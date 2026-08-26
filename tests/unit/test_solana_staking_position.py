from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.solana_staking_position import (
    SolanaStakingPositionReconciliationService,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


def test_solana_staking_position_binds_principal_reward_price_fifo_and_rent(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    program_id = "STAKEGztUnitProgram"
    file_hash = "sha256:unit-solana-staking"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-staking.json",
            file_hash=file_hash,
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {"program_ids": program_id, "instruction_labels": "Stake"}
                ),
            ),
            RawObjectCreate(
                row_number=2,
                payload_json=json.dumps(
                    {"program_ids": program_id, "instruction_labels": "Withdraw"}
                ),
            ),
            RawObjectCreate(
                row_number=3,
                payload_json=json.dumps(
                    {"program_ids": program_id, "instruction_labels": "CloseAccount"}
                ),
            ),
        ],
    )
    outbound, principal, reward, native = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 5, 3, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SHARK",
                quantity=Decimal("-8"),
                tx_id="stake-out",
                account=wallet,
                raw_object_id=raw[0].raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SHARK",
                quantity=Decimal("8"),
                tx_id="stake-return",
                account=wallet,
                raw_object_id=raw[1].raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
                event_type="reward",
                asset="SHARK",
                quantity=Decimal("2"),
                tx_id="stake-return",
                account=wallet,
                raw_object_id=raw[1].raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("0.003"),
                tx_id="rent-return",
                account=wallet,
                raw_object_id=raw[2].raw_object_id,
            ),
        ]
    )
    store.add_price_points(
        [
            PricePointCreate(
                asset="SHARK",
                price_eur=Decimal("0.5"),
                priced_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                source="unit",
            ),
            PricePointCreate(
                asset="SOL",
                price_eur=Decimal("100"),
                priced_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                source="unit",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    trace_path = tmp_path / "wallet_fifo_transfer_traces.csv.gz"
    with gzip.open(trace_path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "tx_id",
                "asset",
                "event_time",
                "source_pool_id",
                "target_pool_id",
                "quantity",
                "fee_quantity",
                "lots_moved",
                "carried_cost_basis_eur",
                "status",
                "source_event_id",
                "target_event_id",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "tx_id": "stake-return",
                "asset": "SHARK",
                "event_time": "2026-01-02T00:00:00Z",
                "source_pool_id": f"solana_rpc:{wallet}",
                "target_pool_id": f"solana_rpc:{wallet}",
                "quantity": "8",
                "fee_quantity": "",
                "lots_moved": "1",
                "carried_cost_basis_eur": "4",
                "status": "solana_defi_position_principal_return",
                "source_event_id": outbound.event_id,
                "target_event_id": principal.event_id,
            }
        )
    latest_run_path = tmp_path / "latest_wallet_fifo_run.json"
    latest_run_path.write_text(
        json.dumps(
            {
                "run_id": "unit-wallet-fifo-run",
                "evidence_files": [
                    {
                        "kind": "wallet_fifo_transfer_traces",
                        "path": str(trace_path),
                        "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settlement_sha = "unit-settlement-semantic-sha"
    settlement_payload = {
        "year": 2026,
        "asset": "SOL",
        "artifact_path": "unit",
        "exists": True,
        "status": "ready",
        "strict_ready": True,
        "semantic_sha256": settlement_sha,
        "records": [
            {
                "event_id": native.event_id,
                "quantity": "0.003",
                "exact_lamport_reconciliation": True,
            }
        ],
        "methodology": "unit",
    }
    settlement_report = SimpleNamespace(
        strict_ready=True,
        semantic_sha256=settlement_sha,
        records=[
            SimpleNamespace(
                event_id=native.event_id,
                quantity=Decimal("0.003"),
                exact_lamport_reconciliation=True,
            )
        ],
        model_dump=lambda mode=None: settlement_payload,
    )
    monkeypatch.setattr(
        WalletFifoPreviewService,
        "solana_program_settlement_evidence_latest",
        lambda _self, year: settlement_report,
    )
    config_path = tmp_path / "solana-staking.json"
    config_path.write_text(
        json.dumps(
            {
                "review_status": "approved_evidence_overlay",
                "positions": [
                    {
                        "reconciliation_id": "unit-shark-position",
                        "year": 2026,
                        "wallet": wallet,
                        "program_id": program_id,
                        "asset": "SHARK",
                        "mint": "unit-shark-mint",
                        "principal_outbound": {
                            "event_id": outbound.event_id,
                            "tx_id": "stake-out",
                            "quantity": "8",
                            "source_file_hash": file_hash,
                        },
                        "position_return": {
                            "tx_id": "stake-return",
                            "received_quantity": "10",
                            "principal_quantity": "8",
                            "reward_quantity": "2",
                            "source_file_hash": file_hash,
                        },
                        "native_settlement": {
                            "event_id": native.event_id,
                            "quantity": "0.003",
                            "evidence_semantic_sha256": settlement_sha,
                        },
                        "evidence_refs": ["unit"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = SolanaStakingPositionReconciliationService(
        store,
        config_path=config_path,
        latest_wallet_fifo_path=latest_run_path,
    ).report()

    assert report.status == "ready"
    assert report.strict_ready is True
    assert all(report.decision_layer.model_dump().values())
    assert report.principal_return_event_id == principal.event_id
    assert report.reward_event_id == reward.event_id
    assert report.reward_income_eur == Decimal("1")
    assert report.wallet_fifo_carried_cost_basis_eur == Decimal("4")
    assert report.wallet_fifo_lots_moved == 1

    monkeypatch.setattr(
        SolanaStakingPositionReconciliationService,
        "DEFAULT_CONFIG_PATH",
        config_path,
    )
    monkeypatch.setattr(
        SolanaStakingPositionReconciliationService,
        "DEFAULT_LATEST_WALLET_FIFO_PATH",
        latest_run_path,
    )
    app = create_app(store)
    response = TestClient(app).get(
        "/api/v1/tax/solana-staking-position-reconciliation"
    )
    assert response.status_code == 200
    assert response.json()["data"]["strict_ready"] is True

    package_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )
    package_response = package_route.endpoint(2026)
    with ZipFile(BytesIO(package_response.body)) as package:
        packaged_report = json.loads(
            package.read(
                "06_Solana_FIFO_Belege/"
                "tax-year-2026-solana-staking-position-reconciliation.json"
            )
        )
        manifest = json.loads(
            package.read("00_Manifest/year-evidence-manifest.json")
        )
    assert packaged_report["strict_ready"] is True
    assert (
        "/api/v1/tax/solana-staking-position-reconciliation"
        in manifest["required_refs"]
    )
