import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/audit_solana_v1_ownership_scope_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_solana_v1_ownership_scope_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_v1_ownership_scope_requires_wallet_or_owned_token_account_signature():
    rows = [
        {"tx_id": "main"},
        {"tx_id": "token"},
        {"tx_id": "pool"},
        {"asset": "SOL"},
    ]

    result = module.classify_v1_rows(rows, {"main"}, {"token"})

    assert result["scope_counts"] == {
        "main_wallet_signature": 1,
        "outside_owned_wallet_scope": 1,
        "owned_token_account_signature": 1,
    }
    assert result["missing_txid_rows_count"] == 1
    assert result["ownership_by_txid"] == {
        "main": "main_wallet_signature",
        "token": "owned_token_account_signature",
    }
    assert result["outside_owned_wallet_scope_txids"] == ["pool"]
