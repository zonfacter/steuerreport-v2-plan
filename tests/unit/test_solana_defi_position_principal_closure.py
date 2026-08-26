from decimal import Decimal
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/apply_solana_defi_position_principal_closure_v2.py"
)
SPEC = importlib.util.spec_from_file_location(
    "apply_solana_defi_position_principal_closure_v2", SCRIPT
)
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
        "hnt_position_principal": [
            {
                "tx_id": module.HNT_LOCK_TX,
                "event_type": "transfer",
                "asset": "HNT",
                "quantity": "-800.000000000000000000",
                "account": module.MAIN_WALLET,
            },
            {
                "tx_id": module.HNT_RETURN_TX,
                "event_type": "transfer",
                "asset": "HNT",
                "quantity": "800.000000000000000000",
                "account": module.MAIN_WALLET,
            },
        ],
        "hnt_income_2024": {
            "lots": module.EXPECTED_HNT_INCOME_2024["lots"],
            "cost_basis_eur_total": str(
                module.EXPECTED_HNT_INCOME_2024["cost_basis_eur_total"]
            ),
        },
        "main_wallet_balances": {
            asset: str(value) for asset, value in module.EXPECTED_MAIN_BALANCES.items()
        },
        "jup_wallet_balances": {
            asset: str(value) for asset, value in module.EXPECTED_JUP_BALANCES.items()
        },
        "zero_or_missing_proceeds": 0,
        "spcxx_events": 1,
        "spcxx_quantity": "1.182348460000000000",
        "review_gate": {"allow_export": True, "issues_open": 0},
        "portfolio": {"total_value_eur": "6884.50", "positions_count": 42},
    }


def test_closure_accepts_exact_validated_state():
    module._assert_final_state(_state())


def test_closure_rejects_hnt_principal_as_income():
    state = _state()
    state["hnt_position_principal"][1]["event_type"] = "income"

    with pytest.raises(RuntimeError, match="hnt_position_principal_mismatch"):
        module._assert_final_state(state)


def test_closure_rejects_hnt_income_drift():
    state = _state()
    state["hnt_income_2024"]["cost_basis_eur_total"] = str(
        Decimal(state["hnt_income_2024"]["cost_basis_eur_total"]) + Decimal("0.01")
    )

    with pytest.raises(RuntimeError, match="hnt_income_2024_mismatch"):
        module._assert_final_state(state)


def test_closure_rejects_tax_year_drift():
    state = _state()
    state["tax_years"][3]["tax_lines"] += 1

    with pytest.raises(RuntimeError, match="final_tax_year_mismatch"):
        module._assert_final_state(state)


def test_report_supports_output_directory_outside_project(tmp_path):
    report = {"status": "ready"}

    module._write_report(
        report,
        tmp_path,
        datetime(2026, 7, 10, tzinfo=timezone.utc),
    )

    latest = tmp_path / "latest_solana_defi_position_principal_closure.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["artifact_path"].startswith(str(tmp_path))
    assert payload["latest_artifact_path"] == str(latest)
