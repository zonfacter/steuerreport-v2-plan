from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.cross_cex_evidence import (
    CrossCexTransferEvidenceService,
)


def test_cross_cex_evidence_binds_registry_raw_hashes_fee_and_fifo_trace(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    source_batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="bitget.csv",
            file_hash="sha256:bitget",
        )
    )
    target_batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana.json",
            file_hash="sha256:solana",
        )
    )
    source_raw = store.add_raw_object(
        source_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps({"Action": "WITHDRAW", "Coin": "USDT"}),
        ),
    )
    target_raw = store.add_raw_object(
        target_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps({"side": "in", "asset": "USDT"}),
        ),
    )
    source_event, target_event = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 1, 13, 33, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-100.000001"),
                fee_asset="USDT",
                fee_quantity=Decimal("-1.5"),
                account="bitget",
                raw_object_id=source_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 12, 1, 13, 32, 32, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("100"),
                tx_id="unit-cross-cex-tx",
                account="wallet-main",
                raw_object_id=target_raw.raw_object_id,
            ),
        ]
    )
    config_path = tmp_path / "source_registry.json"
    config_path.write_text(
        json.dumps(
            {
                "registry_version": "unit",
                "entries": [
                    {
                        "source_id": "bitget-account",
                        "label": "Bitget",
                        "source_type": "exchange",
                        "ownership": "owned",
                        "role": "exchange",
                        "portfolio_policy": "include",
                        "fifo_policy": "owned_pool",
                        "valid_from": "2024-01-01T00:00:00Z",
                        "coverage_status": "complete",
                        "identifiers": [
                            {"kind": "canonical_source", "value": "bitget"}
                        ],
                    },
                    {
                        "source_id": "solana-main-wallet",
                        "label": "Main",
                        "source_type": "wallet",
                        "ownership": "owned",
                        "role": "wallet",
                        "portfolio_policy": "include",
                        "fifo_policy": "owned_pool",
                        "valid_from": "2024-01-01T00:00:00Z",
                        "coverage_status": "complete",
                        "identifiers": [
                            {"kind": "account", "value": "wallet-main"}
                        ],
                    },
                ],
                "ledger_adjustments": [],
                "transfer_evidence": [
                    {
                        "evidence_id": "unit-cross-cex",
                        "tx_id": "unit-cross-cex-tx",
                        "source_id": "bitget-account",
                        "target_source_id": "solana-main-wallet",
                        "event_time": "2024-12-01T13:32:32Z",
                        "asset": "USDT",
                        "quantity": "100",
                        "fee_quantity": "1.500001",
                        "evidence_status": "approved_complete",
                        "evidence_refs": [
                            CrossCexTransferEvidenceService.EVIDENCE_ENDPOINT
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
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
                "tx_id": "unit-cross-cex-tx",
                "asset": "USDT",
                "event_time": "2024-12-01T13:32:32Z",
                "source_pool_id": "bitget:bitget",
                "target_pool_id": "solana_rpc:wallet-main",
                "quantity": "100",
                "fee_quantity": "1.500001",
                "lots_moved": "1",
                "carried_cost_basis_eur": "95",
                "status": "cross_cex_transfer_evidence_complete",
                "source_event_id": source_event.event_id,
                "target_event_id": target_event.event_id,
            }
        )
        writer.writerow(
            {
                "tx_id": "unit-cross-cex-tx",
                "asset": "USDT",
                "event_time": "2024-12-01T13:42:32Z",
                "source_pool_id": "solana_rpc:wallet-main",
                "target_pool_id": "evidence:mirror",
                "quantity": "100",
                "fee_quantity": "",
                "lots_moved": "0",
                "carried_cost_basis_eur": "0",
                "status": "evidence_mirror_excluded",
                "source_event_id": target_event.event_id,
                "target_event_id": target_event.event_id,
            }
        )
    latest_path = tmp_path / "latest_wallet_fifo_run.json"
    latest_path.write_text(
        json.dumps(
            {
                "run_id": "unit-run",
                "semantic_sha256": "unit-semantic",
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
    monkeypatch.setattr(
        CrossCexTransferEvidenceService, "DEFAULT_CONFIG_PATH", config_path
    )
    monkeypatch.setattr(
        CrossCexTransferEvidenceService, "DEFAULT_LATEST_RUN_PATH", latest_path
    )

    report = CrossCexTransferEvidenceService(store).report()

    assert report.status == "ready"
    assert report.strict_ready is True
    assert report.records_count == 1
    assert report.ready_count == 1
    assert report.records[0].fee_quantity == Decimal("1.500001")
    assert all(report.records[0].decision_layer.model_dump().values())
    response = TestClient(create_app(store)).get(
        "/api/v1/tax/cross-cex-transfer-evidence"
    )
    assert response.status_code == 200
    assert response.json()["data"]["strict_ready"] is True
