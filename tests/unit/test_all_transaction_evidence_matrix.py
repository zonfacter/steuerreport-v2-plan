import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_all_transaction_evidence_matrix_20260625.py"
SPEC = importlib.util.spec_from_file_location("run_all_transaction_evidence_matrix_20260625", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


SOLANA_SIG = "37cPEEVnEs3CDcXEMLvEbsd3yR4LkiLNoJcZWyL15MsswqGDkjVGUz7jzLpKN9s3zXUWg2DBMVMszJRrVGUk2ano"


def test_all_transaction_matrix_classifies_solana_and_cex_paths(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("1"),
            tx_id=SOLANA_SIG,
            account="wallet-1",
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            event_type="trade",
            asset="USDT",
            quantity=Decimal("2"),
            tx_id="OF7148144106824448000202",
            account="binance",
        )
    )
    alchemy = tmp_path / "alchemy.json"
    alchemy.write_text(
        json.dumps({"rows": [{"tx_id": SOLANA_SIG, "alchemy_status": "alchemy_found", "review_status": "alchemy_confirmed"}]}),
        encoding="utf-8",
    )
    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"tax_impact_status": "no_direct_tax_impact_detected"}), encoding="utf-8")

    report = MODULE.build_matrix(store, alchemy_audit_path=alchemy, failed_impact_path=failed)

    assert report["tx_count"] == 2
    assert report["solana_signature_count"] == 1
    assert report["non_solana_txid_count"] == 1
    statuses = {row["tx_id"]: row["review_status"] for row in report["rows"]}
    assert statuses[SOLANA_SIG] == "onchain_confirmed"
    assert statuses["OF7148144106824448000202"] == "cex_ledger_evidence_path"


def test_all_transaction_matrix_classifies_failed_solana_without_direct_tax_impact(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("-0.00001"),
            tx_id=SOLANA_SIG,
            account="wallet-1",
        )
    )
    alchemy = tmp_path / "alchemy.json"
    alchemy.write_text(
        json.dumps({"rows": [{"tx_id": SOLANA_SIG, "alchemy_status": "alchemy_found", "review_status": "onchain_transaction_failed"}]}),
        encoding="utf-8",
    )
    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"tax_impact_status": "no_direct_tax_impact_detected"}), encoding="utf-8")

    report = MODULE.build_matrix(store, alchemy_audit_path=alchemy, failed_impact_path=failed)

    assert report["rows"][0]["review_status"] == "onchain_failed_no_direct_tax_impact"
