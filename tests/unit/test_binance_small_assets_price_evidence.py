from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/import_binance_small_assets_price_evidence_v2.py"
SPEC = importlib.util.spec_from_file_location("import_binance_small_assets_price_evidence_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_build_points_converts_usdt_and_btc_quotes_to_eur():
    payload = {
        "fx_rates": {
            "2021-04-28": {
                "usd_eur": "0.8285",
                "source": "frankfurter_timeseries",
            }
        },
        "prices": [
            {
                "asset": "COTI",
                "priced_at": "2021-04-28T05:14:00Z",
                "pair": "COTIUSDT",
                "quote_asset": "USDT",
                "close": "0.36914",
                "open_time_ms": 1619586840000,
            },
            {
                "asset": "WABI",
                "priced_at": "2021-04-28T05:14:00Z",
                "pair": "WABIBTC",
                "quote_asset": "BTC",
                "close": "0.00000956",
                "bridge_pair": "BTCUSDT",
                "bridge_close_usd": "54901.93",
                "open_time_ms": 1619586840000,
            },
        ],
    }

    points = module.build_points(payload)

    assert points[0].asset == "COTI"
    assert points[0].price_eur == Decimal("0.36914") * Decimal("0.8285")
    assert points[1].asset == "WABI"
    assert points[1].price_eur == Decimal("0.00000956") * Decimal("54901.93") * Decimal("0.8285")
    assert points[1].priced_at == datetime(2021, 4, 28, 5, 14, tzinfo=timezone.utc)


def test_default_evidence_package_is_valid_and_unique():
    payload = module._load(module.DEFAULT_PACKAGE)

    points = module.build_points(payload)

    assert len(points) == 17
    assert len({(point.asset, point.priced_at) for point in points}) == 17
    assert {point.asset for point in points} >= {"BNB", "BTC", "BTTC", "CDT", "WABI", "YFIDOWN"}
