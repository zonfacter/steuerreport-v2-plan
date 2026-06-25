import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_all_transaction_evidence_closure_20260625.py"
SPEC = importlib.util.spec_from_file_location("run_all_transaction_evidence_closure_20260625", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _matrix_file(tmp_path: Path) -> Path:
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "tx_count": 2,
                "rows": [
                    {"tx_id": "closed-1", "review_status": "onchain_confirmed"},
                    {
                        "tx_id": "review-1",
                        "year": 2026,
                        "sources": "solana_rpc",
                        "event_types": "income",
                        "assets": "USDC",
                        "accounts": "wallet-1",
                        "review_status": "account_not_seen_in_alchemy_tx",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_all_transaction_closure_reports_open_tax_impact(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event = store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            event_type="income",
            asset="USDC",
            quantity=Decimal("100"),
            tx_id="review-1",
            account="wallet-1",
        )
    )
    with store.connect() as con:
        con.execute(
            """
            insert into tax_lots (
                lot_id, asset, acquired_at, quantity_total, quantity_remaining,
                cost_basis_eur_total, source_event_id, created_at
            )
            values ('lot-1', 'USDC', ?, 100, 100, 95, ?, ?)
            """,
            [datetime(2026, 3, 1, tzinfo=timezone.utc), event.event_id, datetime.now(timezone.utc)],
        )

    report = MODULE.build_report(store, _matrix_file(tmp_path))

    assert report["tx_count"] == 2
    assert report["evidence_path_assigned_count"] == 1
    assert report["needs_review_count"] == 1
    assert report["tax_impact_review_count"] == 1
    assert report["open_rows"][0]["tax_lots_count"] == 1
    assert report["open_rows"][0]["next_action"] == "tax_impact_review_before_export"


def test_all_transaction_closure_reports_open_non_tax_review(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("1"),
            tx_id="review-1",
            account="binance",
        )
    )

    report = MODULE.build_report(store, _matrix_file(tmp_path))

    assert report["needs_review_count"] == 1
    assert report["tax_impact_review_count"] == 0
    assert report["open_rows"][0]["next_action"] == "inspect_onchain_route_owner_signer_and_service_program"
