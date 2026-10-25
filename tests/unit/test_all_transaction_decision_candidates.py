import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_all_transaction_decision_candidates_20260626.py"
SPEC = importlib.util.spec_from_file_location("run_all_transaction_decision_candidates_20260626", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _detail_file(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "detail.json"
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return path


def test_decision_candidates_marks_binance_deposit_evidence_ready(tmp_path):
    path = _detail_file(
        tmp_path,
        [
            {
                "tx_id": "tx-1",
                "sources": "binance",
                "assets": "SOL",
                "gross_quantity": "1.4",
                "detail_classification": "cex_ledger_match_required",
                "tax_impact_detected": False,
                "raw_rows": [
                    {
                        "payload_preview": json.dumps(
                            {
                                "Address": MODULE.BINANCE_DEPOSIT_ADDRESS,
                                "Amount": "1.4",
                                "Coin": "SOL",
                                "Status": "Completed",
                            }
                        )
                    }
                ],
            }
        ],
    )

    report = MODULE.build_report(path)

    assert report["rows"][0]["candidate_status"] == "cex_deposit_ledger_onchain_evidence_ready"
    assert report["rows"][0]["manual_decision_safe"] is False
    assert report["rows"][0]["decision_payload"]["deposit_address"] == MODULE.BINANCE_DEPOSIT_ADDRESS


def test_decision_candidates_marks_owned_binance_withdrawal_safe(tmp_path):
    path = _detail_file(
        tmp_path,
        [
            {
                "tx_id": "tx-2",
                "sources": "binance_withdrawal_api",
                "assets": "JUP",
                "detail_classification": "cex_ledger_match_required",
                "tax_impact_detected": False,
                "raw_rows": [
                    {
                        "payload_preview": json.dumps(
                            {
                                "address": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                                "amount": "5530.555703",
                                "asset": "JUP",
                                "transaction_fee": "1.72",
                            }
                        )
                    }
                ],
            }
        ],
    )

    report = MODULE.build_report(path)

    assert report["rows"][0]["candidate_status"] == "cex_withdrawal_to_owned_wallet_evidence_ready"
    assert report["rows"][0]["manual_decision_safe"] is True


def test_decision_candidates_keeps_external_usdc_inflow_open(tmp_path):
    path = _detail_file(
        tmp_path,
        [
            {
                "tx_id": "tx-3",
                "sources": "solana_rpc",
                "assets": "USDC",
                "accounts": "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu",
                "detail_classification": "owner_delta_without_local_signer_tax_review",
                "tax_impact_detected": True,
                "signers": ["external-signer"],
                "token_deltas": [
                    {
                        "owner": "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu",
                        "asset_hint": "USDC",
                        "delta": "274.85",
                    }
                ],
            }
        ],
    )

    report = MODULE.build_report(path)

    assert report["rows"][0]["candidate_status"] == "external_token_inflow_tax_review_required"
    assert report["rows"][0]["manual_decision_safe"] is False
    assert report["rows"][0]["decision_payload"]["local_token_delta"] == "274.85"
