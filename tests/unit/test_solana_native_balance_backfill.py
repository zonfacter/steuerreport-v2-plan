from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/backfill_solana_native_balance_evidence_v2.py"
SPEC = importlib.util.spec_from_file_location("backfill_solana_native_balance_evidence_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


AUDIT = module.PROJECT_ROOT / "var/native.json"


def _payload():
    return {
        "wallet": "wallet",
        "history_complete": True,
        "reconciliation": {"chain_net_matches_live": True},
        "chain_transactions": [
            {
                "signature": "missing",
                "block_time_utc": "2025-01-01T00:00:00Z",
                "chain_status": "onchain_success",
                "wallet_native_sol_delta": "-0.000015",
                "wallet_fee_sol": "0.000005",
            },
            {
                "signature": "matched",
                "block_time_utc": "2025-01-02T00:00:00Z",
                "chain_status": "onchain_success",
                "wallet_native_sol_delta": "1",
                "wallet_fee_sol": "0",
            },
        ],
    }


def test_native_backfill_separates_non_fee_movement_and_fee():
    rows, findings, expected = module.build_backfill_rows(
        _payload(),
        canonical_effects={"matched": Decimal("1")},
        canonical_fees={},
        audit_path=AUDIT,
    )

    assert findings == []
    assert len(rows) == 1
    assert rows[0]["quantity"] == "0.000010"
    assert rows[0]["side"] == "out"
    assert rows[0]["fee_quantity"] == "0.000005"
    assert expected == {"missing": Decimal("-0.000015")}


def test_native_backfill_blocks_overcharged_canonical_fee():
    rows, findings, expected = module.build_backfill_rows(
        _payload(),
        canonical_effects={"missing": Decimal("-0.000020"), "matched": Decimal("1")},
        canonical_fees={"missing": Decimal("0.000010")},
        audit_path=AUDIT,
    )

    assert rows == []
    assert expected == {}
    assert findings == ["canonical_fee_exceeds_chain_fee:missing:-0.000005"]


def test_native_backfill_preview_normalizes_to_exact_effect(tmp_path):
    rows, findings, expected = module.build_backfill_rows(
        _payload(),
        canonical_effects={"matched": Decimal("1")},
        canonical_fees={},
        audit_path=AUDIT,
    )

    verification = module.verify_rows(rows, expected, tmp_path)

    assert findings == []
    assert verification["status"] == "ready"
    assert verification["effect_delta"] == "0.000000"
