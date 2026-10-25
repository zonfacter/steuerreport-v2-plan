from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/backfill_solana_token_account_evidence_v2.py"
SPEC = importlib.util.spec_from_file_location("backfill_solana_token_account_evidence_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


WALLET = "wallet"


def _transaction(signature, classification, hnt_delta, token_deltas, *, fee="0.000005", non_fee="0"):
    return {
        "signature": signature,
        "block_time_utc": "2025-01-01T00:00:00+00:00",
        "chain_status": "onchain_success",
        "evidence_status": "canonical_missing_balance_change",
        "movement_classification": classification,
        "classification_reason": "test",
        "quantity_delta": hnt_delta,
        "wallet_fee_sol": fee,
        "wallet_native_sol_delta": str(Decimal(non_fee) - Decimal(fee)),
        "wallet_non_fee_sol_delta": non_fee,
        "wallet_token_deltas": token_deltas,
        "instruction_labels": ["test"],
        "program_ids": ["program"],
        "counterpart_token_accounts": ["counterpart"],
    }


def _payload():
    transactions = [
        _transaction(
            "reward-tx",
            "helium_reward",
            "3.49",
            [{"asset": "HNT", "quantity_delta": "3.49"}],
        ),
        _transaction(
            "swap-tx",
            "swap_or_order_route",
            "-1",
            [
                {"asset": "HNT", "quantity_delta": "-1"},
                {"asset": "JUP", "quantity_delta": "5"},
            ],
        ),
        _transaction(
            "transfer-tx",
            "direct_token_transfer",
            "2",
            [{"asset": "HNT", "quantity_delta": "2"}],
            fee="0",
            non_fee="0",
        ),
    ]
    return {
        "history_complete": True,
        "canonical_quantity_mismatch_count": 0,
        "wallet": WALLET,
        "targets": [{"asset": "HNT", "transactions": transactions}],
    }


def test_build_backfill_rows_keeps_reward_trade_and_transfer_semantics(tmp_path):
    rows, findings = module.build_backfill_rows(
        _payload(),
        audit_path=module.PROJECT_ROOT / "var/evidence.json",
    )

    assert findings == []
    assert len(rows) == 4
    assert {row["event_type"] for row in rows} == {"reward", "token_transfer", "transfer"}
    reward = next(row for row in rows if row["tx_id"] == "reward-tx")
    assert reward["fee_asset"] == "SOL"
    assert reward["fee_quantity"] == "0.000005"


def test_verify_rows_matches_all_normalized_asset_effects(tmp_path):
    payload = _payload()
    rows, findings = module.build_backfill_rows(
        payload,
        audit_path=module.PROJECT_ROOT / "var/evidence.json",
    )

    verification = module.verify_rows(payload, rows, tmp_path)

    assert findings == []
    assert verification["status"] == "ready"
    assert set(verification["balance_effect_delta"]) == {"HNT", "JUP", "SOL"}
    assert all(Decimal(value) == 0 for value in verification["balance_effect_delta"].values())


def test_build_backfill_rows_deduplicates_multi_asset_signature(tmp_path):
    payload = _payload()
    swap = payload["targets"][0]["transactions"][1]
    payload["targets"].append(
        {
            "asset": "JUP",
            "transactions": [
                {
                    **swap,
                    "quantity_delta": "5",
                    "movement_classification": "swap_or_order_route",
                }
            ],
        }
    )

    rows, findings = module.build_backfill_rows(
        payload,
        audit_path=module.PROJECT_ROOT / "var/evidence.json",
    )

    assert findings == []
    assert sum(row["tx_id"] == "swap-tx" for row in rows) == 2


def test_partial_token_backfill_subtracts_existing_native_effect(tmp_path):
    transaction = _transaction(
        "partial",
        "defi_position_transfer",
        "963.536668",
        [{"asset": "SHARK", "quantity_delta": "963.536668"}],
        fee="0.000024308",
        non_fee="0.003006720",
    )
    transaction["evidence_status"] = "canonical_quantity_mismatch"
    payload = {
        "history_complete": True,
        "canonical_quantity_mismatch_count": 1,
        "wallet": WALLET,
        "targets": [{"asset": "SHARK", "transactions": [transaction]}],
    }
    existing = {"partial": {"SOL": Decimal("0.002982412")}}
    rows, findings = module.build_backfill_rows(
        payload,
        audit_path=module.PROJECT_ROOT / "var/evidence.json",
        existing_effects_by_tx=existing,
        existing_fees_by_tx={"partial": Decimal("0.000024308")},
    )

    assert findings == []
    assert len(rows) == 1
    assert rows[0]["asset"] == "SHARK"
    assert "fee_asset" not in rows[0]
    verification = module.verify_rows(payload, rows, tmp_path, existing)
    assert verification["status"] == "ready"
