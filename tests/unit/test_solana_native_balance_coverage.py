from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/audit_solana_native_balance_coverage_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_solana_native_balance_coverage_v2", SCRIPT)
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
            "fee": 5000,
            "preBalances": [2_000_000_000, 0],
            "postBalances": [1_749_995_000, 250_000_000],
        },
    }


def test_native_audit_extracts_exact_lamport_delta_and_fee():
    transaction = _transaction()
    row = module._chain_row(
        {"signature": "tx", "slot": 1, "blockTime": 1},
        transaction,
        WALLET,
    )

    assert module.wallet_native_delta(transaction, WALLET) == Decimal("-0.250005")
    assert row["wallet_native_sol_delta"] == "-0.250005"
    assert row["wallet_fee_sol"] == "0.000005"
    assert row["wallet_paid_fee"] is True


def test_native_audit_keeps_failed_transaction_fee_as_balance_effect():
    transaction = _transaction()
    transaction["meta"]["err"] = {"InstructionError": [1, "failed"]}

    row = module._chain_row(
        {"signature": "failed", "slot": 1, "blockTime": 1, "err": transaction["meta"]["err"]},
        transaction,
        WALLET,
    )
    enriched = module.enrich_rows([row], {})[0]

    assert row["chain_status"] == "onchain_failed"
    assert row["wallet_native_sol_delta"] == "-0.250005"
    assert enriched["evidence_status"] == "canonical_missing_balance_change"


def test_native_audit_discovers_closed_owned_token_account():
    transaction = _transaction()
    transaction["transaction"]["message"]["accountKeys"].append(
        {"pubkey": "closed-token-account", "signer": False}
    )
    transaction["meta"]["preBalances"].append(2_039_280)
    transaction["meta"]["postBalances"].append(0)
    transaction["meta"]["preTokenBalances"] = [
        {
            "accountIndex": 2,
            "mint": "mint",
            "owner": WALLET,
            "uiTokenAmount": {"amount": "1250000", "decimals": 6},
        }
    ]
    transaction["meta"]["postTokenBalances"] = []

    changes = module.wallet_token_account_changes(transaction, WALLET)
    accounts = module.historical_token_accounts(
        [
            {
                "chain_status": "onchain_success",
                "slot": 10,
                "block_time_utc": "2025-01-01T00:00:00Z",
                "wallet_token_account_changes": changes,
            }
        ]
    )

    assert changes == [
        {
            "token_account": "closed-token-account",
            "account_index": 2,
            "mint": "mint",
            "decimals": 6,
            "pre_quantity": "1.25",
            "post_quantity": "0",
            "quantity_delta": "-1.25",
        }
    ]
    assert accounts[0]["token_account"] == "closed-token-account"
    assert accounts[0]["transactions_count"] == 1


def test_native_audit_marks_missing_mismatch_and_match():
    rows = [
        {"signature": "missing", "chain_status": "onchain_success", "wallet_native_sol_delta": "1"},
        {"signature": "mismatch", "chain_status": "onchain_success", "wallet_native_sol_delta": "-2"},
        {"signature": "matched", "chain_status": "onchain_success", "wallet_native_sol_delta": "3"},
    ]

    enriched = module.enrich_rows(
        rows,
        {"mismatch": Decimal("-1"), "matched": Decimal("3")},
    )

    assert [row["evidence_status"] for row in enriched] == [
        "canonical_missing_balance_change",
        "canonical_quantity_mismatch",
        "canonical_quantity_matched",
    ]
    assert [row["missing_native_sol_effect"] for row in enriched] == ["1", "-1", "0"]


def test_native_reconciliation_replaces_documented_opening_balance():
    rows = [
        {
            "chain_status": "onchain_success",
            "wallet_native_sol_delta": "0.25",
            "canonical_native_sol_effect": "0.10",
        }
    ]
    ledger = {
        "current_ledger_quantity": "0.11",
        "documented_opening_balance_quantity": "0.01",
        "non_chain_signature_quantity": "0.01",
    }
    balance = {"quantity_sol": "0.25"}

    summary = module.reconciliation_summary(rows, ledger, balance, balance, True)

    assert summary["missing_exact_tx_native_sol_total"] == "0.15"
    assert summary["ledger_after_exact_tx_corrections"] == "0.26"
    assert summary["ledger_after_non_chain_replacement"] == "0.25"
    assert summary["chain_net_matches_live"] is True
    assert summary["replacement_plan_matches_live"] is True
