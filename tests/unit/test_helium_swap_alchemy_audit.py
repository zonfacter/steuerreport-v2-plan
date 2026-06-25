from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_helium_swap_alchemy_audit_20260625.py"
SPEC = importlib.util.spec_from_file_location("run_helium_swap_alchemy_audit_20260625", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_alchemy_audit_row_confirms_wallet_time_and_helium_delta():
    row = SimpleNamespace(
        tx_id="tx-1",
        year=2024,
        first_event_time="2024-02-01T00:00:00",
        account="wallet-1",
        assets="HNT, USDC",
        context_value_eur=Decimal("50"),
    )
    raw = {
        "slot": 1,
        "blockTime": int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp()),
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": "wallet-1", "signer": True}],
                "instructions": [{"programId": "jupiter-program"}],
            }
        },
        "meta": {
            "err": None,
            "preTokenBalances": [
                {
                    "owner": "wallet-1",
                    "mint": MODULE.TOKEN_MINTS["HNT"],
                    "uiTokenAmount": {"uiAmountString": "0"},
                }
            ],
            "postTokenBalances": [
                {
                    "owner": "wallet-1",
                    "mint": MODULE.TOKEN_MINTS["HNT"],
                    "uiTokenAmount": {"uiAmountString": "25"},
                }
            ],
        },
    }

    result = MODULE._audit_row(row, "alchemy_found", raw, None)

    assert result["review_status"] == "alchemy_confirmed"
    assert result["onchain_confirmed"] is True
    assert result["time_matches_local"] is True
    assert result["wallet_seen"] is True
    assert result["helium_token_delta_seen"] is True
    assert result["helium_token_deltas"][0]["asset"] == "HNT"


def test_alchemy_audit_redacts_rpc_url():
    assert (
        MODULE._redacted_rpc_url("https://solana-mainnet.g.alchemy.com/v2/secret-key")
        == "https://solana-mainnet.g.alchemy.com/v2/<redacted>"
    )
