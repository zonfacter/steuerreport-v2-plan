from datetime import datetime, timezone

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_solana_tx_alchemy_audit_20260625.py"
SPEC = importlib.util.spec_from_file_location("run_solana_tx_alchemy_audit_20260625", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_solana_tx_audit_row_confirms_time_and_account():
    local = {
        "tx_id": "tx-1",
        "first_event_time": datetime(2024, 2, 1, tzinfo=timezone.utc),
        "last_event_time": datetime(2024, 2, 1, tzinfo=timezone.utc),
        "events_count": 2,
        "sources": "solana_rpc",
        "assets": "HNT, USDC",
        "accounts": ["wallet-1"],
        "gross_quantity": "125",
    }
    raw = {
        "slot": 1,
        "blockTime": int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp()),
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": "wallet-1", "signer": True}],
                "instructions": [{"programId": "jupiter-program"}],
            }
        },
        "meta": {"err": None, "preTokenBalances": [], "postTokenBalances": []},
    }

    result = MODULE._audit_row(local, "alchemy_found", raw, None)

    assert result["review_status"] == "alchemy_confirmed"
    assert result["time_matches_local"] is True
    assert result["account_seen"] is True
    assert result["onchain_confirmed"] is True


def test_solana_tx_audit_redacts_alchemy_url():
    assert (
        MODULE._redacted_rpc_url("https://solana-mainnet.g.alchemy.com/v2/secret-key")
        == "https://solana-mainnet.g.alchemy.com/v2/<redacted>"
    )


def test_solana_tx_audit_detects_plausible_solana_signatures():
    assert MODULE._is_plausible_solana_signature(
        "37cPEEVnEs3CDcXEMLvEbsd3yR4LkiLNoJcZWyL15MsswqGDkjVGUz7jzLpKN9s3zXUWg2DBMVMszJRrVGUk2ano"
    )
    assert not MODULE._is_plausible_solana_signature("OF7148144106824448000202")
    assert not MODULE._is_plausible_solana_signature("manual-opening:binance-btc-deposit-2023-06-09")
