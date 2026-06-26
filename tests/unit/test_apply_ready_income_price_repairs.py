import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "apply_ready_income_price_repairs_20260626.py"
)
SPEC = importlib.util.spec_from_file_location("apply_ready_income_price_repairs_20260626", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_select_ready_rows_requires_ready_status_and_required_ids():
    rows = [
        {"status": "ready_for_execute", "asset": "ADA", "source": "binance", "year": 2023, "coin_id": "cardano"},
        {"status": "provider_or_fx_review_required", "asset": "DOGE", "source": "binance", "year": 2023, "coin_id": "dogecoin"},
        {"status": "ready_for_execute", "asset": "WIN", "source": "binance", "year": 2022},
    ]

    selected = MODULE.select_ready_rows(rows)

    assert selected == [rows[0]]


def test_coinmarketcap_history_from_payload_uses_open_date_and_close_price():
    payload = {
        "data": {
            "quotes": [
                {
                    "timeOpen": "2023-01-01T00:00:00.000Z",
                    "timeClose": "2023-01-01T23:59:59.999Z",
                    "quote": {"close": 0.25},
                },
                {
                    "timeOpen": "2023-01-02T00:00:00.000Z",
                    "quote": {"close": "0.30"},
                },
                {
                    "timeOpen": "2023-01-03T00:00:00.000Z",
                    "quote": {"close": "0"},
                },
            ]
        }
    }

    result = MODULE.coinmarketcap_history_from_payload(payload)

    assert result == {
        date(2023, 1, 1): Decimal("0.25"),
        date(2023, 1, 2): Decimal("0.30"),
    }


def test_select_ready_rows_keeps_cmc_backed_rows_without_requiring_cmc_id():
    rows = [
        {
            "status": "ready_for_execute",
            "asset": "USDT",
            "source": "binance",
            "year": 2024,
            "coin_id": "tether",
            "cmc_id": None,
        }
    ]

    assert MODULE.select_ready_rows(rows) == rows
