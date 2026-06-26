#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.tax import TaxService  # noqa: E402
from steuerreport_v2.domain.valuation import PriceQualityService  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "stablecoin_fx_replacement_tax_impact"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only tax/FIFO impact preview for Stablecoin FX replacement. "
            "Uses temporary DuckDB copies and never writes to the live database."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--asset", default="USDT")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--source", default="derived:event_quote")
    args = parser.parse_args()

    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="steuerreport_stablecoin_fx_impact_") as tmp:
        tmp_dir = Path(tmp)
        baseline_db = tmp_dir / f"baseline_{db_path.name}"
        patched_db = tmp_dir / f"patched_{db_path.name}"
        shutil.copy2(db_path, baseline_db)
        shutil.copy2(db_path, patched_db)

        baseline = rebuild_and_totals(baseline_db, year=args.year, stable_asset=args.asset)
        replacement_plan = replacement_rows(patched_db, asset=args.asset, year=args.year, source=args.source)
        applied_replacements = apply_replacements(patched_db, replacement_plan)
        patched = rebuild_and_totals(patched_db, year=args.year, stable_asset=args.asset)

    report = {
        "mode": "read-only_temp_db_copies",
        "generated_at": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "asset": args.asset.upper(),
        "year": args.year,
        "source": args.source,
        "replacement_plan": {
            "rows_count": len(replacement_plan),
            "ready_rows": sum(1 for row in replacement_plan if row["replacement_status"] == "ready"),
            "missing_rows": sum(1 for row in replacement_plan if row["replacement_status"] != "ready"),
            "applied_rows": applied_replacements,
            "rows": replacement_plan,
        },
        "baseline": baseline,
        "patched": patched,
        "delta": diff_totals(baseline, patched),
        "conclusion": conclusion(baseline, patched, replacement_plan),
        "methodology": (
            "The script copies the DuckDB twice. It rebuilds FIFO once on the baseline copy, "
            "then replaces only ready derived stablecoin price rows in a patched copy with "
            "their selected same-day replacement prices and rebuilds FIFO again. The live DB "
            "is never opened for writes."
        ),
    }

    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_{args.asset.upper()}_{args.year}_tax_impact.json"
    latest_path = output_dir / f"latest_{args.asset.upper()}_{args.year}_tax_impact.json"
    payload = json.dumps(report, indent=2, ensure_ascii=False, default=json_default)
    output_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "latest_path": str(latest_path),
                "summary": {
                    "applied_rows": applied_replacements,
                    "taxable_gain_loss_delta_eur": report["delta"]["taxable_gain_loss_eur"],
                    "stablecoin_gain_loss_delta_eur": report["delta"]["stablecoin_gain_loss_eur"],
                    "unmatched_delta": report["delta"]["unmatched_disposals"],
                    "conclusion": report["conclusion"],
                },
            },
            indent=2,
            ensure_ascii=False,
            default=json_default,
        )
    )


def replacement_rows(db_path: Path, *, asset: str, year: int, source: str) -> list[dict[str, Any]]:
    report = PriceQualityService(DuckDbStore(db_path)).stablecoin_fx_replacement_impact(
        asset=asset,
        year=year,
        source=source,
        limit=10_000,
    )
    return [row.model_dump(mode="json") for row in report.rows]


def apply_replacements(db_path: Path, rows: list[dict[str, Any]]) -> int:
    ready_rows = [row for row in rows if row["replacement_status"] == "ready"]
    with duckdb.connect(str(db_path)) as con:
        for row in ready_rows:
            con.execute(
                """
                update price_ledger
                set price_eur = cast(? as decimal(38, 18)),
                    source = ?,
                    confidence = cast('1.0' as decimal(18, 8))
                where price_id = ?
                """,
                [
                    str(row["replacement_price_eur"]),
                    f"stablecoin_fx_replacement_preview:{row['replacement_source']}",
                    row["price_id"],
                ],
            )
    return len(ready_rows)


def rebuild_and_totals(db_path: Path, *, year: int, stable_asset: str) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    result = TaxService(store).rebuild_fifo()
    with store.connect() as con:
        tax = con.execute(
            """
            select
                coalesce(sum(case when holding_days <= 365 then gain_loss_eur else 0 end), 0),
                coalesce(sum(case when holding_days <= 365 then disposal_proceeds_eur else 0 end), 0),
                coalesce(sum(case when holding_days <= 365 then acquisition_cost_eur else 0 end), 0),
                count(*) filter (where holding_days <= 365)::integer,
                coalesce(sum(case when holding_days > 365 then gain_loss_eur else 0 end), 0),
                count(*) filter (where holding_days > 365)::integer
            from tax_lines
            where date_part('year', disposed_at)::integer = ?
            """,
            [year],
        ).fetchone()
        stable = con.execute(
            """
            select
                coalesce(sum(gain_loss_eur), 0),
                coalesce(sum(disposal_proceeds_eur), 0),
                coalesce(sum(acquisition_cost_eur), 0),
                count(*)::integer
            from tax_lines
            where date_part('year', disposed_at)::integer = ?
              and upper(asset) = ?
            """,
            [year, stable_asset.upper()],
        ).fetchone()
    return {
        "taxable_gain_loss_eur": tax[0],
        "taxable_disposal_proceeds_eur": tax[1],
        "taxable_acquisition_cost_eur": tax[2],
        "taxable_lines_count": int(tax[3] or 0),
        "tax_free_gain_loss_eur": tax[4],
        "tax_free_lines_count": int(tax[5] or 0),
        "stablecoin_gain_loss_eur": stable[0],
        "stablecoin_disposal_proceeds_eur": stable[1],
        "stablecoin_acquisition_cost_eur": stable[2],
        "stablecoin_lines_count": int(stable[3] or 0),
        "unmatched_disposals": int(result.unmatched_disposals),
    }


def diff_totals(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, before_value in before.items():
        after_value = after[key]
        if isinstance(before_value, Decimal):
            result[key] = after_value - before_value
        elif isinstance(before_value, int):
            result[key] = int(after_value) - before_value
    return result


def conclusion(before: dict[str, Any], after: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    missing = sum(1 for row in rows if row["replacement_status"] != "ready")
    delta = diff_totals(before, after)
    if missing:
        return "replacement_not_complete"
    material = any(
        isinstance(value, Decimal) and abs(value) >= Decimal("0.01")
        for value in delta.values()
    )
    if material:
        return "replacement_changes_tax_result_review_required"
    return "no_tax_delta_replacement_is_quality_closure_only"


def json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    main()
