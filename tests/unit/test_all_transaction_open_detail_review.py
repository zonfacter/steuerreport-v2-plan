import importlib.util
from decimal import Decimal
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_all_transaction_open_detail_review_20260625.py"
SPEC = importlib.util.spec_from_file_location("run_all_transaction_open_detail_review_20260625", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_open_detail_review_extracts_token_owner_deltas():
    raw = {
        "meta": {
            "preTokenBalances": [
                {
                    "owner": "wallet-1",
                    "mint": MODULE.USDC_MINT,
                    "accountIndex": 2,
                    "uiTokenAmount": {"uiAmountString": "1.00"},
                },
                {
                    "owner": "sender-1",
                    "mint": MODULE.USDC_MINT,
                    "accountIndex": 1,
                    "uiTokenAmount": {"uiAmountString": "10.00"},
                },
            ],
            "postTokenBalances": [
                {
                    "owner": "wallet-1",
                    "mint": MODULE.USDC_MINT,
                    "accountIndex": 2,
                    "uiTokenAmount": {"uiAmountString": "4.50"},
                },
                {
                    "owner": "sender-1",
                    "mint": MODULE.USDC_MINT,
                    "accountIndex": 1,
                    "uiTokenAmount": {"uiAmountString": "6.50"},
                },
            ],
        }
    }

    deltas = MODULE._token_deltas(raw)

    assert {
        (item["owner"], item["delta"])
        for item in deltas
    } == {("wallet-1", Decimal("3.50")), ("sender-1", Decimal("-3.50"))}


def test_open_detail_review_classifies_tax_owner_delta_without_local_signer():
    row = {"review_status": "account_not_seen_in_alchemy_tx", "tax_impact_detected": True}
    deltas = [{"owner": "wallet-1", "delta": Decimal("3.50")}]

    assert (
        MODULE._classification(row, deltas, ["sender-1"], {"wallet-1"})
        == "owner_delta_without_local_signer_tax_review"
    )


def test_open_detail_review_classifies_cex_match_required():
    row = {"review_status": "cex_onchain_txid_found_ledger_match_needed", "tax_impact_detected": False}

    assert MODULE._classification(row, [], [], {"binance"}) == "cex_ledger_match_required"
