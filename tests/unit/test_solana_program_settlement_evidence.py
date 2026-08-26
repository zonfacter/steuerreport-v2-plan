from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_solana_program_settlement_evidence_v2.py"
)
SPEC = importlib.util.spec_from_file_location(
    "audit_solana_program_settlement_evidence_v2",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)


WALLET = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
EVENT_TIME = datetime(2025, 8, 2, 12, 0, tzinfo=timezone.utc)
QUANTITY = Decimal("0.004182960")
TX_ID = "program-settlement-transaction"


def _transaction(*, wallet_delta_lamports: int = 4_177_146) -> dict[str, object]:
    wallet_pre = 100_000_000
    return {
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET, "signer": True, "writable": True},
                    {"pubkey": "ClosedAccountOne", "signer": False, "writable": True},
                    {"pubkey": "ClosedAccountTwo", "signer": False, "writable": True},
                ],
                "instructions": [{"programId": "HeliumProgram111111111111111111111111111"}],
            }
        },
        "meta": {
            "err": None,
            "fee": 5_814,
            "preBalances": [wallet_pre, 2_143_680, 2_039_280],
            "postBalances": [wallet_pre + wallet_delta_lamports, 0, 0],
            "innerInstructions": [],
        },
    }


def _record(*, event_id: str = "settlement-event") -> dict[str, object]:
    return SCRIPT.analyze_transaction(
        event_id=event_id,
        event_time=EVENT_TIME,
        tx_id=TX_ID,
        wallet=WALLET,
        quantity=QUANTITY,
        transaction=_transaction(),
    )


def _write_artifact(path: Path, record: dict[str, object]) -> None:
    records = [record]
    semantic_sha256 = hashlib.sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "year": 2025,
                "asset": "SOL",
                "wallet": WALLET,
                "records_count": 1,
                "verified_count": int(
                    record["classification"]
                    == "owned_program_account_close_rent_return"
                ),
                "failed_count": 0,
                "semantic_sha256": semantic_sha256,
                "records": records,
            }
        ),
        encoding="utf-8",
    )


def test_program_settlement_analysis_requires_exact_lamport_reconciliation():
    verified = _record()
    mismatched = SCRIPT.analyze_transaction(
        event_id="mismatch",
        event_time=EVENT_TIME,
        tx_id=TX_ID,
        wallet=WALLET,
        quantity=QUANTITY,
        transaction=_transaction(wallet_delta_lamports=4_177_145),
    )

    assert verified["classification"] == "owned_program_account_close_rent_return"
    assert verified["wallet_is_signer"] is True
    assert verified["expected_gross_credit_lamports"] == 4_182_960
    assert verified["wallet_delta_lamports"] == 4_177_146
    assert verified["fee_lamports"] == 5_814
    assert verified["closed_accounts_total_lamports"] == 4_182_960
    assert verified["exact_lamport_reconciliation"] is True
    assert mismatched["classification"] == "review_required"
    assert mismatched["exact_lamport_reconciliation"] is False


def test_target_event_selection_is_exact_and_rejects_wrong_scope(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    valid = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=EVENT_TIME,
                event_type="transfer",
                asset="SOL",
                quantity=QUANTITY,
                account=WALLET,
                tx_id=TX_ID,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=EVENT_TIME,
                event_type="transfer",
                asset="SOL",
                quantity=QUANTITY,
                account="different-wallet",
                tx_id="different-transaction",
            ),
        ]
    )

    selected = SCRIPT.load_target_events(
        store,
        event_ids=[valid[0].event_id, valid[0].event_id],
        year=2025,
        wallet=WALLET,
    )
    assert [event.event_id for event in selected] == [valid[0].event_id]

    with pytest.raises(ValueError, match="wallet_mismatch"):
        SCRIPT.load_target_events(
            store,
            event_ids=[valid[1].event_id],
            year=2025,
            wallet=WALLET,
        )
    with pytest.raises(ValueError, match="target_event_not_found"):
        SCRIPT.load_target_events(
            store,
            event_ids=["missing-event"],
            year=2025,
            wallet=WALLET,
        )


def test_wallet_fifo_uses_only_exact_matching_program_settlement_artifact(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="program-settlement-evidence",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "source": "solana_rpc",
                    "signature": TX_ID,
                    "raw_row": "no embedded close-account detail",
                }
            ),
        ),
    )
    event = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=EVENT_TIME,
                event_type="transfer",
                asset="SOL",
                quantity=QUANTITY,
                account=WALLET,
                tx_id=TX_ID,
                raw_object_id=raw.raw_object_id,
            )
        ]
    )[0]
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=EVENT_TIME,
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()
    evidence_dir = tmp_path / "program-settlement-evidence"
    artifact_path = evidence_dir / "latest_2025_SOL_program_settlement_evidence.json"
    service = WalletFifoPreviewService(
        store,
        program_settlement_evidence_dir=evidence_dir,
    )

    before = service.preview(year=2025)
    assert before.unresolved_inbound_provenance_count == 1

    valid_record = _record(event_id=event.event_id)
    _write_artifact(artifact_path, valid_record)
    resolved = service.preview(year=2025)
    assert resolved.unresolved_inbound_provenance_count == 0
    assert resolved.transfer_traces[0].status == "resolved_by_solana_program_settlement"
    assert resolved.transfer_traces[0].source_pool_id == "solana_program_settlement"
    evidence_report = service.solana_program_settlement_evidence_latest(2025)
    assert evidence_report.status == "ready"
    assert evidence_report.strict_ready is True
    assert evidence_report.artifact_integrity_valid is True
    assert evidence_report.database_binding_valid is True
    assert evidence_report.verified_count == 1

    monkeypatch.setattr(
        WalletFifoPreviewService,
        "DEFAULT_SOLANA_PROGRAM_SETTLEMENT_EVIDENCE_DIR",
        evidence_dir,
    )
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/wallet-fifo-solana-program-settlement-evidence"
    )
    assert response.status_code == 200
    assert response.json()["data"]["strict_ready"] is True

    invalid_record = dict(valid_record)
    invalid_record["tx_id"] = "different-program-settlement-transaction"
    _write_artifact(artifact_path, invalid_record)
    rejected = service.preview(year=2025)
    assert rejected.unresolved_inbound_provenance_count == 1
    assert rejected.transfer_traces[0].status == "unresolved_inbound_provenance"
    rejected_report = service.solana_program_settlement_evidence_latest(2025)
    assert rejected_report.artifact_integrity_valid is True
    assert rejected_report.database_binding_valid is False
    assert rejected_report.strict_ready is False
    assert rejected_report.status == "review_required"
