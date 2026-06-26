import importlib.util
from decimal import Decimal
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_stablecoin_fx_replacement_tax_impact_20260626.py"
)
SPEC = importlib.util.spec_from_file_location("stablecoin_fx_replacement_tax_impact", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

conclusion = MODULE.conclusion
diff_totals = MODULE.diff_totals


def test_stablecoin_fx_replacement_tax_impact_diff_totals():
    before = {
        "taxable_gain_loss_eur": Decimal("100.00"),
        "stablecoin_lines_count": 3,
        "unmatched_disposals": 0,
    }
    after = {
        "taxable_gain_loss_eur": Decimal("95.25"),
        "stablecoin_lines_count": 3,
        "unmatched_disposals": 1,
    }

    result = diff_totals(before, after)

    assert result["taxable_gain_loss_eur"] == Decimal("-4.75")
    assert result["stablecoin_lines_count"] == 0
    assert result["unmatched_disposals"] == 1


def test_stablecoin_fx_replacement_tax_impact_conclusion_requires_review_on_delta():
    before = {
        "taxable_gain_loss_eur": Decimal("100.00"),
        "stablecoin_lines_count": 3,
        "unmatched_disposals": 0,
    }
    after = {
        "taxable_gain_loss_eur": Decimal("99.98"),
        "stablecoin_lines_count": 3,
        "unmatched_disposals": 0,
    }
    rows = [{"replacement_status": "ready"}]

    assert conclusion(before, after, rows) == "replacement_changes_tax_result_review_required"


def test_stablecoin_fx_replacement_tax_impact_conclusion_allows_quality_only():
    totals = {
        "taxable_gain_loss_eur": Decimal("100.00"),
        "stablecoin_lines_count": 3,
        "unmatched_disposals": 0,
    }
    rows = [{"replacement_status": "ready"}]

    assert conclusion(totals, totals, rows) == "no_tax_delta_replacement_is_quality_closure_only"


def test_stablecoin_fx_replacement_tax_impact_conclusion_blocks_missing_replacements():
    totals = {
        "taxable_gain_loss_eur": Decimal("100.00"),
        "stablecoin_lines_count": 3,
        "unmatched_disposals": 0,
    }
    rows = [{"replacement_status": "missing_replacement"}]

    assert conclusion(totals, totals, rows) == "replacement_not_complete"
