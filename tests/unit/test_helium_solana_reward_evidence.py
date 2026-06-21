from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_helium_solana_rewards_rpc_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_helium_solana_rewards_rpc_v2", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


def test_reward_instruction_logs_detects_helium_rewards():
    logs = [
        "Program log: Instruction: TransferChecked",
        "Program log: Instruction: SetCurrentRewardsWrapperV1",
        "Program log: Instruction: DistributeCompressionRewardsV0",
    ]

    assert scanner.reward_instruction_logs(logs) == [
        "Program log: Instruction: SetCurrentRewardsWrapperV1",
        "Program log: Instruction: DistributeCompressionRewardsV0",
    ]


def test_token_deltas_for_wallet_extracts_positive_hnt_delta_only_for_owner():
    wallet = "wallet-1"
    tx = {
        "meta": {
            "preTokenBalances": [
                {
                    "owner": wallet,
                    "mint": scanner.TOKEN_MINTS["HNT"],
                    "uiTokenAmount": {"uiAmountString": "1.0"},
                },
                {
                    "owner": "other-wallet",
                    "mint": scanner.TOKEN_MINTS["HNT"],
                    "uiTokenAmount": {"uiAmountString": "100.0"},
                },
            ],
            "postTokenBalances": [
                {
                    "owner": wallet,
                    "mint": scanner.TOKEN_MINTS["HNT"],
                    "uiTokenAmount": {"uiAmountString": "4.488129"},
                },
                {
                    "owner": "other-wallet",
                    "mint": scanner.TOKEN_MINTS["HNT"],
                    "uiTokenAmount": {"uiAmountString": "0.0"},
                },
            ],
        }
    }

    assert scanner.token_deltas_for_wallet(tx, wallet) == {"HNT": Decimal("3.488129")}
