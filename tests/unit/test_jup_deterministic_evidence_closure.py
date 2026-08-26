from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/apply_jup_deterministic_evidence_closure_v2.py"
)
SPEC = importlib.util.spec_from_file_location("apply_jup_deterministic_evidence_closure_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _state():
    return {
        "counts": dict(module.EXPECTED_COUNTS),
        "tax_years": [
            {"year": year, "tax_lines": count, "gain_loss_eur": str(gain)}
            for year, (count, gain) in module.EXPECTED_TAX_YEARS.items()
        ],
        "main_wallet_balances": {
            asset: str(value) for asset, value in module.EXPECTED_MAIN_BALANCES.items()
        },
        "jup_wallet_balances": {
            asset: str(value) for asset, value in module.EXPECTED_JUP_BALANCES.items()
        },
        "unmatched_disposals": 0,
        "zero_or_missing_proceeds": 0,
        "unknown_spcxx_events": 0,
        "spcxx_events": [
            {
                "event_type": "trade",
                "asset": "SPCXX",
                "quantity": "1.182348460000000000",
                "quote_asset": "SOL",
                "quote_quantity": "3.002167496000000000",
                "tx_id": module.SPCXX_TX_ID,
            }
        ],
        "binance_exact_price_points": 17,
        "current_spcxx_prices": 1,
        "review_gate": {"allow_export": True, "issues_open": 0},
        "portfolio": {
            "spcxx_positions": [
                {"account": module.JUP_WALLET, "quantity": "1.18234846", "value_eur": "151.34"}
            ]
        },
    }


def test_closure_accepts_exact_validated_state():
    module._assert_final_state(_state())


def test_closure_rejects_tax_drift():
    state = _state()
    state["tax_years"][3]["gain_loss_eur"] = str(
        Decimal(state["tax_years"][3]["gain_loss_eur"]) + Decimal("0.01")
    )

    with pytest.raises(RuntimeError, match="final_tax_year_mismatch"):
        module._assert_final_state(state)


def test_closure_rejects_wallet_quantity_drift():
    state = _state()
    state["jup_wallet_balances"]["SOL"] = "0.262660280"

    with pytest.raises(RuntimeError, match="jup_wallet_balance_mismatch"):
        module._assert_final_state(state)


def test_closure_rejects_unknown_spcxx_alias():
    state = _state()
    state["unknown_spcxx_events"] = 1

    with pytest.raises(RuntimeError, match="unknown_spcxx_events"):
        module._assert_final_state(state)


def test_native_audit_requires_exact_chain_and_ledger_balance():
    report = {
        "wallet": module.JUP_WALLET,
        "history_complete": True,
        "transaction_missing_count": 0,
        "canonical_missing_balance_change_count": 0,
        "canonical_quantity_mismatch_count": 0,
        "reconciliation": {
            "chain_net_matches_live": True,
            "live_quantity_sol": "0.262660279",
        },
    }
    module._assert_native_audit(report)
    report["canonical_quantity_mismatch_count"] = 1

    with pytest.raises(RuntimeError, match="native_audit_quantity_mismatch"):
        module._assert_native_audit(report)
