from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/audit_solana_token_account_coverage_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_solana_token_account_coverage_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


ACCOUNT = "token-account"
MINT = "token-mint"


def _transaction(pre_amount="100", post_amount="75"):
    return {
        "transaction": {"message": {"accountKeys": [{"pubkey": ACCOUNT}, {"pubkey": "wallet"}]}},
        "meta": {
            "preBalances": [0, 2_000_000_000],
            "postBalances": [0, 1_999_995_000],
            "preTokenBalances": [
                {
                    "accountIndex": 0,
                    "mint": MINT,
                    "uiTokenAmount": {"amount": pre_amount, "decimals": 2},
                }
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 0,
                    "mint": MINT,
                    "uiTokenAmount": {"amount": post_amount, "decimals": 2},
                }
            ],
        },
    }


def test_token_account_delta_uses_account_index_and_raw_decimals():
    assert module.token_account_delta(_transaction(), ACCOUNT, MINT) == {
        "account_index": 0,
        "mint": MINT,
        "decimals": 2,
        "pre_quantity": "1",
        "post_quantity": "0.75",
        "quantity_delta": "-0.25",
    }


def test_wallet_native_and_token_deltas_use_exact_owner_and_mint():
    transaction = _transaction()
    transaction["meta"]["preTokenBalances"][0]["owner"] = "wallet"
    transaction["meta"]["postTokenBalances"][0]["owner"] = "wallet"

    assert module.wallet_native_delta(transaction, "wallet") == Decimal("-0.000005")
    assert module.wallet_token_deltas(transaction, "wallet") == [
        {"mint": MINT, "asset": None, "quantity_delta": "-0.25"}
    ]
    assert module.wallet_token_deltas(transaction, "wallet", {MINT: "SPCXX"}) == [
        {"mint": MINT, "asset": "SPCXX", "quantity_delta": "-0.25"}
    ]


def test_canonical_balance_effect_includes_trade_quote_and_fee():
    rows = [
        {
            "asset": "CWIF",
            "quantity": "100",
            "quote_asset": "HNT",
            "quote_quantity": "1",
            "fee_asset": "HNT",
            "fee_quantity": "0.01",
        },
        {"asset": "HNT", "quantity": "3"},
    ]

    assert module.canonical_balance_effect(rows, "HNT") == Decimal("1.99")
    assert module.canonical_balance_effect(rows, "CWIF") == Decimal("100")


def test_enrich_chain_rows_marks_missing_and_matched_quantities():
    rows = [
        {"signature": "missing", "chain_status": "onchain_success", "quantity_delta": "2"},
        {"signature": "matched", "chain_status": "onchain_success", "quantity_delta": "-1"},
    ]
    canonical = {
        "matched": [
            {
                "asset": "CWIF",
                "quantity": "100",
                "quote_asset": "HNT",
                "quote_quantity": "1",
            }
        ]
    }

    canonical["matched"][0]["account"] = "wallet"
    result = module._enrich_chain_rows(rows, canonical, "HNT", "wallet")

    assert result[0]["evidence_status"] == "canonical_missing_balance_change"
    assert result[1]["evidence_status"] == "canonical_quantity_matched"


def test_movement_classification_separates_rewards_from_swaps():
    reward = module.movement_classification(
        {"instruction_labels": ["SetCurrentRewardsWrapperV1", "DistributeCompressionRewardsV0"]},
        Decimal("3.49"),
    )
    swap = module.movement_classification(
        {"instruction_labels": ["SharedAccountsRoute", "Swap"]},
        Decimal("-3.49"),
    )

    assert reward == ("helium_reward", "explicit_helium_reward_instruction")
    assert swap == ("swap_or_order_route", "swap_or_order_instruction")


def test_movement_classification_recognizes_legacy_iot_claim_and_position_withdraw():
    claim = module.movement_classification(
        {"instruction_labels": ["ClaimRewardsV0", "TransferV0"]},
        Decimal("300"),
    )
    withdraw = module.movement_classification(
        {"instruction_labels": ["ClosePositionV0", "WithdrawV0"]},
        Decimal("300"),
    )

    assert claim == ("helium_reward", "explicit_helium_reward_instruction")
    assert withdraw == ("defi_position_transfer", "position_withdraw_instruction")


def test_enrich_chain_rows_excludes_same_txid_cex_counterparty():
    rows = [{"signature": "transfer", "chain_status": "onchain_success", "quantity_delta": "-5"}]
    canonical = {
        "transfer": [
            {"asset": "JUP", "quantity": "5", "account": "binance"},
        ]
    }

    result = module._enrich_chain_rows(rows, canonical, "JUP", "wallet")

    assert result[0]["evidence_status"] == "canonical_missing_balance_change"
    assert result[0]["canonical_events_count"] == 0
    assert result[0]["counterparty_canonical_events_count"] == 1


def test_classification_summary_only_counts_canonical_gaps():
    rows = [
        {
            "evidence_status": "canonical_missing_balance_change",
            "movement_classification": "helium_reward",
            "quantity_delta": "2.5",
        },
        {
            "evidence_status": "canonical_quantity_matched",
            "movement_classification": "helium_reward",
            "quantity_delta": "99",
        },
    ]

    assert module._classification_summary(rows) == [
        {
            "movement_classification": "helium_reward",
            "transactions_count": 1,
            "quantity_delta": "2.5",
        }
    ]


def test_merge_token_accounts_keeps_closed_history_and_prefers_current_state():
    historical = [
        {"token_account": "old", "mint": MINT, "current_quantity": "0"},
        {"token_account": "current", "mint": MINT, "current_quantity": "0"},
    ]
    current = [{"token_account": "current", "mint": MINT, "current_quantity": "2"}]

    result = module.merge_token_accounts(current, historical)

    assert [row["token_account"] for row in result] == ["current", "old"]
    assert result[0]["current_quantity"] == "2"
    assert result[0]["account_state"] == "current"


def test_aggregate_token_account_rows_nets_internal_account_migration():
    base = {
        "signature": "internal",
        "block_time_utc": "2025-01-01T00:00:00Z",
        "chain_status": "onchain_success",
        "instruction_labels": ["transferChecked"],
        "program_ids": ["token-program"],
        "counterpart_token_accounts": [],
    }
    rows = [
        {**base, "token_account": "old", "quantity_delta": "-5", "pre_quantity": "5", "post_quantity": "0"},
        {**base, "token_account": "new", "quantity_delta": "5", "pre_quantity": "0", "post_quantity": "5"},
    ]

    result = module.aggregate_token_account_rows(rows)

    assert len(result) == 1
    assert result[0]["quantity_delta"] == "0"
    assert result[0]["token_accounts"] == ["new", "old"]
    assert len(result[0]["token_account_components"]) == 2


def test_default_targets_include_case_sensitive_shark_mint():
    assert module.DEFAULT_TARGETS["SHARK"] == "SHARKSYJjqaNyxVfrpnBN9pjgkhwDhatnMyicWPnr1s"
