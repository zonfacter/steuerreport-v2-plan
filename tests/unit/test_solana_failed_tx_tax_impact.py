import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_solana_failed_tx_tax_impact_20260625.py"
SPEC = importlib.util.spec_from_file_location("run_solana_failed_tx_tax_impact_20260625", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _audit_file(tmp_path: Path, *txids: str) -> Path:
    path = tmp_path / "alchemy-audit.json"
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {"tx_id": txid, "review_status": "onchain_transaction_failed"}
                    for txid in txids
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_failed_tx_tax_impact_reports_no_direct_tax_impact(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("-0.00001"),
            tx_id="failed-tx-1",
            account="wallet-1",
        )
    )

    report = MODULE.build_report(store, _audit_file(tmp_path, "failed-tx-1"))

    assert report["failed_tx_count"] == 1
    assert report["failed_tx_with_canonical_events_count"] == 1
    assert report["canonical_events_count"] == 1
    assert report["tax_lines_count"] == 0
    assert report["tax_lots_count"] == 0
    assert report["unmatched_disposals_count"] == 0
    assert report["tax_impact_status"] == "no_direct_tax_impact_detected"


def test_failed_tx_tax_impact_flags_direct_tax_line(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event = store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("-1"),
            tx_id="failed-tx-2",
            account="wallet-1",
        )
    )
    with store.connect() as con:
        con.execute(
            """
            insert into tax_lines (
                tax_line_id, asset, disposed_at, quantity, acquisition_cost_eur,
                disposal_proceeds_eur, gain_loss_eur, holding_days, source_event_id,
                lot_id, created_at
            )
            values (
                'line-1', 'SOL', ?, 1, 10, 7, -3, 1, ?, 'lot-1', ?
            )
            """,
            [datetime(2024, 1, 1, tzinfo=timezone.utc), event.event_id, datetime.now(timezone.utc)],
        )

    report = MODULE.build_report(store, _audit_file(tmp_path, "failed-tx-2"))

    assert report["tax_lines_count"] == 1
    assert report["tax_lines_gain_loss_eur"] == Decimal("-3.000000000000000000")
    assert report["tax_impact_status"] == "direct_tax_impact_needs_correction_review"
