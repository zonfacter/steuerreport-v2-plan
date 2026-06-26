import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_all_income_price_repair_preview_20260626.py"
)
SPEC = importlib.util.spec_from_file_location("run_all_income_price_repair_preview_20260626", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_load_coin_ids_maps_symbols_aliases_and_store_keys(tmp_path):
    config = tmp_path / "prices.json"
    config.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "symbol": "HNT",
                        "coingecko_id": "helium",
                        "coinmarketcap_id": "5665",
                        "aliases": ["hntyMint"],
                        "store_keys": ["HNTYVP"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    coin_ids = MODULE.load_coin_ids(config)

    assert coin_ids["HNT"] == "helium"
    assert coin_ids["HNTYMINT"] == "helium"
    assert coin_ids["HNTYVP"] == "helium"

    config = MODULE.load_price_config(config)
    assert config["HNT"].coingecko_id == "helium"
    assert config["HNT"].coinmarketcap_id == "5665"


def test_group_status_requires_zero_failures_and_importable_days():
    assert MODULE.group_status({"failure_count": 0, "importable_price_days": 2}) == "ready_for_execute"
    assert (
        MODULE.group_status({"failure_count": 1, "importable_price_days": 2})
        == "provider_or_fx_review_required"
    )
    assert MODULE.group_status({"failure_count": 0, "importable_price_days": 0}) == "no_import_needed"
