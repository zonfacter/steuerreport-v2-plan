import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_helium_solana_reward_evidence_v2.py"
SPEC = importlib.util.spec_from_file_location("import_helium_solana_reward_evidence_v2", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


def test_rows_from_artifact_maps_helium_rewards_to_solana_rpc_import_rows(tmp_path):
    artifact = tmp_path / "reward-evidence.json"
    artifact.write_text(
        json.dumps(
            {
                "summary": {"wallet": "wallet-1"},
                "rows": [
                    {
                        "classification": "helium_reward",
                        "signature": "sig-1",
                        "event_time": "2026-06-19T21:40:23+00:00",
                        "asset": "HNT",
                        "quantity": "3.48812900",
                        "reward_instruction_logs": [
                            "Program log: Instruction: SetCurrentRewardsWrapperV1",
                        ],
                    },
                    {
                        "classification": "transfer",
                        "signature": "sig-2",
                        "event_time": "2026-06-19T21:41:00+00:00",
                        "asset": "HNT",
                        "quantity": "1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = importer.rows_from_artifact(artifact)

    assert rows == [
        {
            "timestamp_utc": "2026-06-19T21:40:23+00:00",
            "event_type": "token_transfer",
            "asset": "HNT",
            "quantity": "3.48812900",
            "side": "in",
            "tx_id": "sig-1",
            "wallet_address": "wallet-1",
            "source": "helium_solana_reward_rpc_evidence",
            "artifact_path": str(artifact),
            "reward_instruction_logs": [
                "Program log: Instruction: SetCurrentRewardsWrapperV1",
            ],
            "reward_instruction_detected": True,
        }
    ]


def test_rows_from_artifact_deduplicates_signatures(tmp_path):
    artifact = tmp_path / "reward-evidence.json"
    row = {
        "classification": "helium_reward",
        "signature": "sig-1",
        "event_time": "2026-06-19T21:40:23+00:00",
        "asset": "HNT",
        "quantity": "1.0",
    }
    artifact.write_text(
        json.dumps({"summary": {"wallet": "wallet-1"}, "rows": [row, dict(row)]}),
        encoding="utf-8",
    )

    rows = importer.rows_from_artifact(artifact)

    assert len(rows) == 1
    assert rows[0]["tx_id"] == "sig-1"
