from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/audit_solana_wallet_history_coverage_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_solana_wallet_history_coverage_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


WALLET = "wallet-owner"


def _transaction():
    return {
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET, "signer": True},
                    {"pubkey": "counterparty", "signer": False},
                ]
            }
        },
        "meta": {
            "preBalances": [2_000_000_000, 0],
            "postBalances": [1_750_000_000, 250_000_000],
            "preTokenBalances": [
                {
                    "owner": WALLET,
                    "mint": "mint-a",
                    "uiTokenAmount": {"uiAmountString": "10"},
                }
            ],
            "postTokenBalances": [
                {
                    "owner": WALLET,
                    "mint": "mint-a",
                    "uiTokenAmount": {"uiAmountString": "7.5"},
                },
                {
                    "owner": WALLET,
                    "mint": "mint-b",
                    "uiTokenAmount": {"uiAmountString": "4"},
                },
            ],
        },
    }


def test_wallet_history_audit_extracts_native_and_token_deltas():
    transaction = _transaction()

    assert module.wallet_native_delta(transaction, WALLET) == Decimal("-0.25")
    assert module.wallet_token_deltas(transaction, WALLET) == {
        "mint-a": Decimal("-2.5"),
        "mint-b": Decimal("4"),
    }


def test_wallet_history_audit_summarizes_only_successful_rows():
    rows = [
        {
            "status": "onchain_success",
            "native_sol_delta": "0.5",
            "token_deltas": [
                {"mint": "mint-a", "asset": "HNT", "quantity_delta": "3"},
                {"mint": "mint-b", "asset": None, "quantity_delta": "-2"},
            ],
        },
        {"status": "signature_failed", "native_sol_delta": "99", "token_deltas": []},
    ]

    assert module.summarize_rows(rows) == {
        "HNT": "3",
        "SOL": "0.5",
        "mint:mint-b": "-2",
    }


def test_wallet_history_audit_uses_case_sensitive_cwif_mint():
    assert module.MINT_SYMBOLS["7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1"] == "CWIF"
    assert "7ATgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1" not in module.MINT_SYMBOLS
