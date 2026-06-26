import importlib.util
import sqlite3
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_stablecoin_fx_anchor_preview_20260626.py"
)
SPEC = importlib.util.spec_from_file_location("stablecoin_fx_anchor_preview", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

build_anchor_plan = MODULE.build_anchor_plan
summarize_anchor_plan = MODULE.summarize_anchor_plan
summarize_tax_impact = MODULE.summarize_tax_impact


def test_build_anchor_plan_uses_only_replacement_needed_days(tmp_path):
    v1_db = tmp_path / "v1.db"
    create_v1_fx_cache(v1_db, [("2025-01-20", "0.96937")])
    preview = {
        "groups": [
            {
                "days": [
                    stablecoin_day("USDT", 2025, "2025-01-20", "replacement_needed"),
                    stablecoin_day("USDT", 2025, "2025-01-21", "fx_backed_available"),
                ]
            }
        ]
    }

    result = build_anchor_plan(preview, v1_db_path=v1_db)

    assert len(result) == 1
    assert result[0]["anchor_status"] == "ready"
    assert result[0]["asset"] == "USDT"
    assert result[0]["price_point"]["price_eur"] == "0.96937"
    assert result[0]["price_point"]["priced_at"] == "2025-01-20T00:00:00+00:00"
    assert "stablecoin_fx_anchor:v1_fx_cache" in result[0]["price_point"]["source"]


def test_build_anchor_plan_marks_missing_v1_db(tmp_path):
    preview = {"groups": [{"days": [stablecoin_day("BUSD", 2023, "2023-05-02", "replacement_needed")]}]}

    result = build_anchor_plan(preview, v1_db_path=tmp_path / "missing.db")

    assert result[0]["anchor_status"] == "missing_v1_db"
    assert result[0]["price_point"] is None


def test_build_anchor_plan_marks_missing_usd_eur_fx(tmp_path):
    v1_db = tmp_path / "v1.db"
    create_v1_fx_cache(v1_db, [])
    preview = {"groups": [{"days": [stablecoin_day("USDT", 2022, "2022-01-02", "replacement_needed")]}]}

    result = build_anchor_plan(preview, v1_db_path=v1_db)

    assert result[0]["anchor_status"] == "missing_usd_eur_fx"
    assert result[0]["price_point"] is None


def test_summarize_anchor_plan_groups_ready_and_missing_days():
    anchors = [
        {"asset": "USDT", "year": 2024, "anchor_status": "ready", "tax_lines_count": 6},
        {"asset": "USDT", "year": 2024, "anchor_status": "missing_usd_eur_fx", "tax_lines_count": 6},
        {"asset": "BUSD", "year": 2023, "anchor_status": "ready", "tax_lines_count": 2},
    ]

    result = summarize_anchor_plan(anchors)

    assert result["required_days"] == 3
    assert result["ready_days"] == 2
    assert result["missing_days"] == 1
    assert result["groups"][0]["asset"] == "BUSD"
    assert result["groups"][1]["missing_days"] == 1


def test_summarize_tax_impact_totals_delta():
    result = summarize_tax_impact(
        [
            {
                "conclusion": "replacement_changes_tax_result_review_required",
                "delta": {"taxable_gain_loss_eur": "-2.50"},
            },
            {
                "conclusion": "no_tax_delta_replacement_is_quality_closure_only",
                "delta": {"taxable_gain_loss_eur": "0.00"},
            },
        ]
    )

    assert result["groups_count"] == 2
    assert result["groups_requiring_review"] == 1
    assert result["groups_complete_quality_only"] == 1
    assert result["taxable_gain_loss_delta_eur"] == "-2.50"


def stablecoin_day(asset, year, price_date, status):
    return {
        "asset": asset,
        "year": year,
        "price_date": price_date,
        "source": "derived:event_quote",
        "replacement_status": status,
        "tax_lines_count": 4,
        "tax_quantity": "12.5",
        "derived_price_count": 1,
        "min_derived_price_eur": "0.80",
        "max_derived_price_eur": "0.90",
        "sample_event_refs": ["ref-1"],
    }


def create_v1_fx_cache(path, rows):
    with sqlite3.connect(path) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                created_at text
            )
            """
        )
        con.executemany(
            """
            insert into fx_cache (
                rate_date, base_ccy, quote_ccy, rate, source, source_rate_date, created_at
            ) values (?, 'USD', 'EUR', ?, 'frankfurter_timeseries', ?, '2026-06-26T00:00:00+00:00')
            """,
            [(date, rate, date) for date, rate in rows],
        )
