from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/apply_main_solana_evidence_closure_v2.py"
SPEC = importlib.util.spec_from_file_location("apply_main_solana_evidence_closure_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _state():
    return {
        "balances": {asset: str(value) for asset, value in module.EXPECTED_BALANCES.items()},
        "opening_batch_present": False,
        "unmatched_disposals": 0,
        "review_gate": {"allow_export": True, "issues_open": 0},
    }


def test_main_solana_closure_accepts_exact_stage_state():
    module._assert_final_state(_state())


def test_main_solana_closure_rejects_any_quantity_delta():
    state = _state()
    state["balances"]["SOL"] = str(Decimal(state["balances"]["SOL"]) + Decimal("0.000000001"))

    with pytest.raises(RuntimeError, match="final_balance_mismatch"):
        module._assert_final_state(state)
