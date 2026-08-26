import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/import_v1_solana_rpc_v2.py"
SPEC = importlib.util.spec_from_file_location("import_v1_solana_rpc_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_v1_solana_wallet_inference_requires_same_transaction_evidence():
    rows = [
        {"tx_id": "owned", "wallet_address": "wallet", "asset": "HNT"},
        {"tx_id": "owned", "asset": "SOL"},
        {"tx_id": "unrelated", "asset": "SOL"},
    ]

    result = module._enrich_missing_wallets(rows)

    assert len(result) == 2
    assert result[1]["wallet_address"] == "wallet"
    assert result[1]["v1_wallet_inferred_from_tx"] == "owned"
    assert all(row["tx_id"] != "unrelated" for row in result)


def test_v1_solana_wallet_inference_uses_verified_ownership_scope():
    rows = [
        {"tx_id": "main", "asset": "HNT"},
        {"tx_id": "token-account", "asset": "USDT"},
        {"tx_id": "pool", "wallet_address": "wrong-default", "asset": "SOL"},
    ]
    ownership = {
        "main": "main_wallet_signature",
        "token-account": "owned_token_account_signature",
    }

    result = module._enrich_missing_wallets(rows, ownership)

    assert [row["tx_id"] for row in result] == ["main", "token-account"]
    assert all(row["wallet_address"] == module.DEFAULT_WALLET for row in result)
    assert result[1]["v2_wallet_ownership_evidence"] == "owned_token_account_signature"
