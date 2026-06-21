from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_blockpit_supplement_v2.py"
SPEC = importlib.util.spec_from_file_location("import_blockpit_supplement_v2", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

_filtered_rows = MODULE._filtered_rows
_readiness_result = MODULE._readiness_result
_row_class = MODULE._row_class
_row_movements = MODULE._row_movements


def _row(
    *,
    label: str,
    incoming_asset: str = "",
    incoming_amount: str = "",
    outgoing_asset: str = "",
    outgoing_amount: str = "",
    fee_asset: str = "",
    fee_amount: str = "",
) -> dict[str, str]:
    return {
        "Date (UTC)": "06.12.2024 12:09:15",
        "Integration Name": "Solana",
        "Label": label,
        "Outgoing Asset": outgoing_asset,
        "Outgoing Amount": outgoing_amount,
        "Incoming Asset": incoming_asset,
        "Incoming Amount": incoming_amount,
        "Fee Asset (optional)": fee_asset,
        "Fee Amount (optional)": fee_amount,
    }


def test_blockpit_supplement_row_classifies_relevant_solana_classes() -> None:
    assert _row_class(_row(label="Deposit", incoming_asset="PYTH", incoming_amount="1")) == (
        "deposit_airdrop_missing_price"
    )
    assert _row_class(
        _row(label="Deposit", incoming_asset="IOT", incoming_amount="10", fee_asset="SOL")
    ) == "deposit_with_sol_fee"
    assert _row_class(_row(label="Withdrawal", outgoing_asset="SOL", outgoing_amount="1")) == (
        "withdrawal_sol"
    )
    assert _row_class(
        _row(label="Trade", incoming_asset="USDT", incoming_amount="100", outgoing_asset="JUP")
    ) == "trade_sell_to_stable"
    assert _row_class(
        _row(label="Trade", incoming_asset="JUP", incoming_amount="100", outgoing_asset="USDC")
    ) == "trade_buy_from_stable"
    assert _row_class(
        _row(label="Trade", incoming_asset="JUP", incoming_amount="100", outgoing_asset="SOL")
    ) == "trade_crypto_crypto"


def test_blockpit_supplement_filters_classes_and_unknown_assets(tmp_path) -> None:
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "06.12.2024 12:09:15;Solana;Deposit;;;IOT;10;SOL;0.001\n"
        "06.12.2024 12:10:15;Solana;Deposit;;;PYTH;1;;\n"
        "06.12.2024 12:11:15;Solana;Trade;USDC;5;JUP;10;SOL;0.001\n"
        "06.12.2024 12:12:15;Solana;Trade;UNKNOWN;5;JUP;10;SOL;0.001\n",
        encoding="utf-8",
    )

    rows, skipped_unknown, class_counts, skipped_class_counts = _filtered_rows(
        csv_path,
        "Solana",
        2024,
        {"IOT", "JUP", "PYTH", "SOL", "USDC"},
        {"deposit_with_sol_fee"},
        {"deposit_airdrop_missing_price"},
    )

    assert len(rows) == 1
    assert skipped_unknown == 1
    assert class_counts == {"deposit_with_sol_fee": 1}
    assert skipped_class_counts == {
        "deposit_airdrop_missing_price": 1,
        "trade_buy_from_stable": 1,
    }


def test_blockpit_supplement_row_movements_include_quote_spend_and_fees() -> None:
    movements = _row_movements(
        _row(
            label="Trade",
            incoming_asset="JUP",
            incoming_amount="10",
            outgoing_asset="USDC",
            outgoing_amount="5",
            fee_asset="SOL",
            fee_amount="0.001",
        )
    )

    assert movements == [
        ("JUP", MODULE.Decimal("10")),
        ("USDC", MODULE.Decimal("-5")),
        ("SOL", MODULE.Decimal("-0.001")),
    ]


def test_blockpit_supplement_readiness_reports_missing_price_and_opening_balance(tmp_path) -> None:
    db_path = tmp_path / "steuerreport_v2.duckdb"
    rows = [
        _row(
            label="Trade",
            incoming_asset="JUP",
            incoming_amount="10",
            outgoing_asset="USDC",
            outgoing_amount="5",
            fee_asset="SOL",
            fee_amount="0.001",
        )
    ]

    readiness = _readiness_result(db_path, rows)

    assert readiness["missing_latest_price_assets"] == ["JUP"]
    assert readiness["required_opening_balance"] == {
        "SOL": "0.001",
        "USDC": "5",
    }
