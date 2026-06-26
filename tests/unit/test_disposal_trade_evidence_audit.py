import importlib.util
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_disposal_trade_evidence_audit_20260626.py"
)
SPEC = importlib.util.spec_from_file_location("run_disposal_trade_evidence_audit_20260626", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_review_reasons_flags_missing_primary_derived_large_gain_and_cross_source():
    reasons = MODULE.review_reasons(
        {
            "acquisition_raw_object_id": "raw-acq",
            "disposal_raw_object_id": "raw-disp",
            "acquisition_price_eur": Decimal("1"),
            "disposal_price_eur": Decimal("2"),
            "acquisition_same_day_primary": False,
            "disposal_same_day_primary": True,
            "acquisition_price_source": "derived:event_quote",
            "disposal_price_source": "coingecko_history",
            "acquisition_priced_at": datetime(2024, 1, 1),
            "acquired_at": datetime(2024, 1, 10),
            "disposal_priced_at": datetime(2024, 2, 1),
            "disposed_at": datetime(2024, 2, 1),
            "gain_loss_eur": Decimal("60"),
            "disposal_proceeds_eur": Decimal("100"),
            "acquisition_source": "binance",
            "disposal_source": "solana_rpc",
        }
    )

    assert "acquisition_same_day_primary_missing" in reasons
    assert "acquisition_derived_price" in reasons
    assert "acquisition_stale_price" in reasons
    assert "large_gain_loss_ratio" in reasons
    assert "cross_source_fifo" in reasons


def test_review_reasons_returns_evidence_path_present_for_clean_row():
    reasons = MODULE.review_reasons(
        {
            "acquisition_raw_object_id": "raw-acq",
            "disposal_raw_object_id": "raw-disp",
            "acquisition_price_eur": Decimal("1"),
            "disposal_price_eur": Decimal("2"),
            "acquisition_same_day_primary": True,
            "disposal_same_day_primary": True,
            "acquisition_price_source": "coingecko",
            "disposal_price_source": "coingecko",
            "gain_loss_eur": Decimal("1"),
            "disposal_proceeds_eur": Decimal("100"),
            "acquisition_source": "binance",
            "disposal_source": "binance",
        }
    )

    assert reasons == ["evidence_path_present"]


def test_fiat_eur_source_is_not_derived():
    assert MODULE.is_derived("fiat:eur") is False


def test_annual_status_treats_eur_quote_as_available_fiat_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    acquired_at = datetime(2021, 2, 6, 23, 18, 2)
    disposed_at = datetime(2021, 2, 6, 23, 23, 58)
    with store.connect() as con:
        con.execute(
            """
            insert into canonical_events (
                event_id, source, source_ref, event_time, event_type, asset, quantity,
                quote_asset, quote_quantity, fee_asset, fee_quantity, tx_id, wallet,
                account, confidence, raw_object_id
            )
            values
              ('acq', 'binance', null, ?, 'trade', 'BNB', 1.625, 'EUR', 100, null, null, null, null, 'binance', 1, 'raw-acq'),
              ('disp', 'binance', null, ?, 'trade', 'BNB', -1.6, null, null, null, null, null, null, 'binance', 1, 'raw-disp')
            """,
            [acquired_at, disposed_at],
        )
        con.execute(
            """
            insert into tax_lots (
                lot_id, asset, acquired_at, quantity_total, quantity_remaining,
                cost_basis_eur_total, source_event_id, created_at
            )
            values ('lot-1', 'BNB', ?, 1.625, 0.025, 100, 'acq', ?)
            """,
            [acquired_at, acquired_at],
        )
        con.execute(
            """
            insert into tax_lines (
                tax_line_id, asset, disposed_at, quantity, acquisition_cost_eur,
                disposal_proceeds_eur, gain_loss_eur, holding_days, source_event_id,
                lot_id, created_at
            )
            values ('tax-1', 'BNB', ?, 1.6, 98.461538461538, 96.59, -1.871538461538, 0, 'disp', 'lot-1', ?)
            """,
            [disposed_at, disposed_at],
        )

        rows = MODULE.annual_status(con)

    assert rows[0]["acquisition_missing_price_count"] == 0
    assert rows[0]["acquisition_missing_same_day_primary_count"] == 0
